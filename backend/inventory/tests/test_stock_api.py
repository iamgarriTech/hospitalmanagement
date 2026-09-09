"""Stores and stock over HTTP: who may do what, and to whose stock.

The mechanics are proved in `test_stock.py`. This file is about the boundaries
— guarantee 1 (a store at another facility does not exist as far as you are
concerned) and guarantee 4 (every boundary has a test proving it refuses).
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from inventory.models import StockAdjustment, StockMovement, StockRecord

RECORDS = "/api/stock-records/"


def _receive_url(record):
    return reverse("stockrecord-receive", args=[record.pk])


def _issue_url(record):
    return reverse("stockrecord-issue", args=[record.pk])


# --- AC-143, AC-144: the configuration screens --------------------------

@pytest.mark.django_db
def test_a_stores_manager_administers_the_catalogue(as_stores_manager):
    """AC-143."""
    category = as_stores_manager.post(
        reverse("itemcategory-list"), {"name": "Linen", "display_order": 3},
        format="json",
    )
    assert category.status_code == 201

    item = as_stores_manager.post(
        reverse("inventoryitem-list"),
        {"category": category.data["id"], "name": "Bed sheet, single",
         "code": "LIN-SHT", "unit_of_issue": "each", "default_reorder_level": 40,
         "tracks_expiry": False},
        format="json",
    )
    assert item.status_code == 201, item.data
    assert item.data["tracks_expiry"] is False


@pytest.mark.django_db
def test_a_storekeeper_cannot_change_the_catalogue(as_storekeeper, stock_items):
    """Running a store and deciding what the hospital stocks are different jobs."""
    response = as_storekeeper.post(
        reverse("itemcategory-list"), {"name": "Linen"}, format="json",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_a_store_at_another_facility_does_not_exist_to_this_caller(
    as_storekeeper, stores
):
    """Guarantee 1. 404, not 403."""
    listed = as_storekeeper.get(reverse("store-list"))
    codes = {store["id"] for store in listed.data["results"]}
    assert stores["main"].pk in codes
    assert stores["other_facility"].pk not in codes

    detail = as_storekeeper.get(
        reverse("store-detail", args=[stores["other_facility"].pk])
    )
    assert detail.status_code == 404


@pytest.mark.django_db
def test_another_facility_s_stock_is_invisible(
    as_storekeeper, stores, stock_items, storekeeper
):
    from inventory.stock import receive

    theirs = StockRecord.objects.create(
        store=stores["other_facility"], item=stock_items["gloves"], reorder_level=5
    )
    receive(record=theirs, quantity=10, actor=storekeeper, lot_number="X",
            expiry_date=timezone.localdate() + timedelta(days=90))

    listed = as_storekeeper.get(RECORDS)
    assert [row["id"] for row in listed.data["results"]] == []

    refused = as_storekeeper.post(
        _issue_url(theirs), {"quantity": 1, "issued_to": "Ward 1"}, format="json",
    )
    assert refused.status_code == 404
    assert theirs.on_hand() == 10


# --- receiving and issuing over HTTP ------------------------------------

@pytest.mark.django_db
def test_receiving_and_issuing_through_the_api(
    as_storekeeper, stores, stock_items, storekeeper
):
    record = StockRecord.objects.create(
        store=stores["main"], item=stock_items["gloves"], reorder_level=20
    )
    received = as_storekeeper.post(
        _receive_url(record),
        {"quantity": 40, "lot_number": "API-1",
         "expiry_date": str(timezone.localdate() + timedelta(days=200)),
         "unit_cost": "1500.00", "reason": "Delivery note 4471"},
        format="json",
    )
    assert received.status_code == 201, received.data
    assert received.data["on_hand"] == 40
    assert received.data["is_low"] is False

    issued = as_storekeeper.post(
        _issue_url(record),
        {"quantity": 25, "issued_to": "Theatre 2", "reason": "Tuesday list"},
        format="json",
    )
    assert issued.status_code == 200, issued.data
    assert issued.data["on_hand"] == 15
    assert issued.data["is_low"] is True

    event = AuditEvent.objects.get(action="stock.issued")
    assert event.changes["after"]["issued_to"] == "Theatre 2"
    assert event.changes["after"]["balance_after"] == "15"


@pytest.mark.django_db
def test_issuing_more_than_is_there_is_a_conflict_not_a_server_error(
    as_storekeeper, gloves_in_main
):
    """AC-146 over HTTP. A refusal, with the figure in it."""
    response = as_storekeeper.post(
        _issue_url(gloves_in_main), {"quantity": 500, "issued_to": "Ward 1"},
        format="json",
    )
    assert response.status_code == 409
    assert "Only 80" in response.data["detail"]
    assert gloves_in_main.on_hand() == 80


@pytest.mark.django_db
def test_the_quantity_on_hand_cannot_be_patched(as_storekeeper, gloves_in_main):
    """A writable quantity would be a read-then-write from the client.

    Which is exactly the race AC-146 forbids, and it would leave a balance
    nobody could trace to an act.
    """
    response = as_storekeeper.patch(
        reverse("stockrecord-detail", args=[gloves_in_main.pk]),
        {"reorder_level": 30, "on_hand": 5000}, format="json",
    )
    assert response.status_code == 200
    gloves_in_main.refresh_from_db()
    assert gloves_in_main.reorder_level == 30
    assert gloves_in_main.on_hand() == 80


@pytest.mark.django_db
def test_the_ledger_has_no_write_verb_at_all(as_storekeeper, gloves_in_main):
    """AC-145. A movement records what happened; it is not editable."""
    movement = StockMovement.objects.get(
        kind=StockMovement.RECEIPT, lot__lot_number="L-OLD"
    )
    original = movement.quantity_delta
    for method, payload in (
        ("post", {"lot": movement.lot_id, "kind": "receipt", "quantity_delta": 1}),
        ("patch", {"quantity_delta": 999}),
        ("delete", None),
    ):
        url = (reverse("stockmovement-list") if method == "post"
               else reverse("stockmovement-detail", args=[movement.pk]))
        response = getattr(as_storekeeper, method)(
            url, payload, format="json"
        ) if payload else getattr(as_storekeeper, method)(url)
        assert response.status_code in (403, 405), (method, response.status_code)

    movement.refresh_from_db()
    assert movement.quantity_delta == original


# --- AC-147 over HTTP ---------------------------------------------------

@pytest.mark.django_db
def test_a_large_adjustment_is_refused_over_http_without_a_second_person(
    as_storekeeper, gloves_in_main
):
    """AC-147 (negative)."""
    lot = gloves_in_main.lots.get(lot_number="L-OLD")
    response = as_storekeeper.post(
        reverse("stockadjustment-list"),
        {"lot": lot.pk, "kind": StockAdjustment.LOSS, "quantity_delta": -10,
         "reason": "Ten boxes unaccounted for at the monthly count."},
        format="json",
    )
    assert response.status_code == 400
    assert "second person's authorisation" in response.data["detail"]
    assert not StockAdjustment.objects.exists()


@pytest.mark.django_db
def test_an_authoriser_must_actually_hold_the_permission(
    as_storekeeper, gloves_in_main, cashier
):
    """A name in a box is not an authorisation.

    Without this check the control is defeated by naming any colleague who
    happens to have an account.
    """
    lot = gloves_in_main.lots.get(lot_number="L-OLD")
    response = as_storekeeper.post(
        reverse("stockadjustment-list"),
        {"lot": lot.pk, "kind": StockAdjustment.LOSS, "quantity_delta": -10,
         "reason": "Counted short.", "authorised_by": cashier.pk},
        format="json",
    )
    assert response.status_code == 400
    assert "cannot authorise stock adjustments" in response.data["authorised_by"][0]
    assert not StockAdjustment.objects.exists()


@pytest.mark.django_db
def test_an_authorised_adjustment_is_recorded_with_both_names(
    as_storekeeper, gloves_in_main, stores_manager
):
    lot = gloves_in_main.lots.get(lot_number="L-OLD")
    response = as_storekeeper.post(
        reverse("stockadjustment-list"),
        {"lot": lot.pk, "kind": StockAdjustment.LOSS, "quantity_delta": -10,
         "reason": "Ten boxes unaccounted for at the monthly count.",
         "authorised_by": stores_manager.pk},
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["value"] == "15000.00"
    assert response.data["authorised_by_email"] == stores_manager.email

    event = AuditEvent.objects.get(action="stock.adjusted")
    assert event.changes["after"]["authorised_by"] == stores_manager.email
    assert event.changes["after"]["balance_after"] == "20"


@pytest.mark.django_db
def test_nobody_without_the_verb_can_adjust_stock(as_cashier, gloves_in_main):
    lot = gloves_in_main.lots.get(lot_number="L-OLD")
    response = as_cashier.post(
        reverse("stockadjustment-list"),
        {"lot": lot.pk, "kind": StockAdjustment.DAMAGE, "quantity_delta": -1,
         "reason": "Torn."}, format="json",
    )
    assert response.status_code == 403


# --- transfers over HTTP ------------------------------------------------

@pytest.mark.django_db
def test_a_transfer_over_http_moves_the_stock_and_the_expiry(
    as_storekeeper, gloves_in_main, stores
):
    response = as_storekeeper.post(
        reverse("stocktransfer-list"),
        {"item": gloves_in_main.item_id, "from_store": stores["main"].pk,
         "to_store": stores["theatre"].pk, "quantity": 30,
         "reason": "Theatre topped up"},
        format="json",
    )
    assert response.status_code == 201, response.data

    theatre = StockRecord.objects.get(
        store=stores["theatre"], item=gloves_in_main.item
    )
    assert theatre.on_hand() == 30
    assert theatre.lots.get(lot_number="L-OLD").expiry_date == (
        gloves_in_main.lots.get(lot_number="L-OLD").expiry_date
    )
    assert AuditEvent.objects.filter(action="stock.transferred").exists()


@pytest.mark.django_db
def test_a_transfer_across_facilities_is_refused_over_http(
    as_storekeeper, gloves_in_main, stores
):
    response = as_storekeeper.post(
        reverse("stocktransfer-list"),
        {"item": gloves_in_main.item_id, "from_store": stores["main"].pk,
         "to_store": stores["other_facility"].pk, "quantity": 5},
        format="json",
    )
    # The destination is outside the caller's scope, so it is not even a valid
    # choice — refused as a bad request rather than acted on.
    assert response.status_code in (400, 409)
    assert gloves_in_main.on_hand() == 80


# --- AC-149 over HTTP ---------------------------------------------------

@pytest.mark.django_db
def test_the_alerts_endpoint_reports_low_and_expiring_per_store(
    as_storekeeper, stores, stock_items, storekeeper
):
    """AC-149."""
    from inventory.models import StockLot
    from inventory.stock import receive

    low = StockRecord.objects.create(
        store=stores["main"], item=stock_items["gloves"], reorder_level=20
    )
    receive(record=low, quantity=5, actor=storekeeper, lot_number="LOW",
            expiry_date=timezone.localdate() + timedelta(days=400),
            unit_cost=Decimal("1500.00"))

    soon = StockRecord.objects.create(
        store=stores["main"], item=stock_items["spirit"], reorder_level=0
    )
    receive(record=soon, quantity=30, actor=storekeeper, lot_number="SOON",
            expiry_date=timezone.localdate() + timedelta(days=10))

    gone = StockRecord.objects.create(
        store=stores["main"], item=stock_items["bedpan"], reorder_level=0
    )
    receive(record=gone, quantity=2, actor=storekeeper)
    assert StockLot.objects.filter(record=gone).get().expiry_date is None

    response = as_storekeeper.get(reverse("stockalert-list"))
    assert response.status_code == 200

    low_items = {row["item_name"]: row for row in response.data["low"]}
    assert stock_items["gloves"].name in low_items
    assert low_items[stock_items["gloves"].name]["usable_on_hand"] == 5
    assert low_items[stock_items["gloves"].name]["reorder_level"] == 20

    expiring = {row["lot_number"]: row for row in response.data["expiring"]}
    assert "SOON" in expiring
    assert expiring["SOON"]["days_left"] == 10
    assert expiring["SOON"]["is_expired"] is False
    # An item with no expiry never appears here.
    assert all(row["item_name"] != stock_items["bedpan"].name
               for row in response.data["expiring"])


@pytest.mark.django_db
def test_the_alerts_endpoint_shows_nothing_from_another_facility(
    as_storekeeper, stores, stock_items, storekeeper
):
    """Guarantee 1 again, on the screen a storekeeper reads every morning."""
    from inventory.stock import receive

    theirs = StockRecord.objects.create(
        store=stores["other_facility"], item=stock_items["gloves"], reorder_level=99
    )
    receive(record=theirs, quantity=1, actor=storekeeper, lot_number="THEIRS",
            expiry_date=timezone.localdate() + timedelta(days=5))

    response = as_storekeeper.get(reverse("stockalert-list"))
    assert all(row["store"] != stores["other_facility"].pk
               for row in response.data["low"])
    assert all(row["lot_number"] != "THEIRS" for row in response.data["expiring"])


@pytest.mark.django_db
def test_the_record_ledger_reads_back_every_act(as_storekeeper, gloves_in_main):
    """AC-145 and AC-150 over HTTP."""
    as_storekeeper.post(
        _issue_url(gloves_in_main), {"quantity": 10, "issued_to": "Ward 1"},
        format="json",
    )
    response = as_storekeeper.get(
        reverse("stockrecord-movements", args=[gloves_in_main.pk])
    )
    assert response.status_code == 200
    kinds = [row["kind"] for row in response.data]
    assert kinds.count("receipt") == 2
    assert kinds.count("issue") == 1
    issued = next(row for row in response.data if row["kind"] == "issue")
    assert issued["quantity_delta"] == -10
    assert issued["quantity_after"] == 20
    assert issued["issued_to"] == "Ward 1"
