"""Procurement over HTTP: who may do which step, and to whose orders.

The mechanics are proved in `test_procurement.py`. This file is about the
separations — a buyer who cannot approve, an approver who cannot buy, and an
order at another facility that does not exist as far as either is concerned.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from inventory.models import (
    PurchaseOrder,
    PurchaseRequest,
    StockMovement,
    StockRecord,
    SupplierInvoice,
)


def _submit(client, request):
    return client.post(reverse("purchaserequest-submit", args=[request.pk]))


def _decide(client, request, approve=True, note="Agreed."):
    return client.post(
        reverse("purchaserequest-decide", args=[request.pk]),
        {"approve": approve, "note": note}, format="json",
    )


def _raise(client, request, supplier, prices=None, days=7):
    return client.post(
        reverse("raisepurchaseorder-list"),
        {"request": request.pk, "supplier": supplier.pk,
         "expected_date": str(timezone.localdate() + timedelta(days=days)),
         "prices": prices or {
             str(line.item_id): "1500.00" for line in request.lines.all()
         }},
        format="json",
    )


# --- the whole run, end to end -------------------------------------------

@pytest.mark.django_db
def test_the_whole_purchase_runs_from_request_to_approved_invoice(
    as_buyer, as_approver, supplier, stores, stock_items, purchase_buyer,
    purchase_approver
):
    """AC-151 to AC-157 in one pass, each step by whoever may do it.

    Every step through the API, including raising the request — the point is
    that the whole run works over HTTP and leaves a complete trail, so a step
    taken in Python here would be a step nobody proved.
    """
    raised_request = as_buyer.post(
        reverse("purchaserequest-list"),
        {"store": stores["main"].pk,
         "justification": "Theatre list next week and the shelf is empty.",
         "lines": [
             {"item": stock_items["gloves"].pk, "quantity": 100,
              "estimated_unit_cost": "1500.00"},
             {"item": stock_items["spirit"].pk, "quantity": 40,
              "estimated_unit_cost": "800.00"},
         ]},
        format="json",
    )
    assert raised_request.status_code == 201, raised_request.data
    assert raised_request.data["needs_approval"] is True
    assert raised_request.data["estimated_value"] == "182000.00"
    purchase_request = PurchaseRequest.objects.get(pk=raised_request.data["id"])

    assert _submit(as_buyer, purchase_request).status_code == 200
    assert _decide(as_approver, purchase_request).status_code == 200

    raised = _raise(as_buyer, purchase_request, supplier)
    assert raised.status_code == 201, raised.data
    order_id = raised.data["id"]
    order = PurchaseOrder.objects.get(pk=order_id)

    # Everything arrives.
    deliveries = [
        {"order_line": line.pk, "quantity": line.quantity_ordered,
         "lot_number": f"LMS-{line.item.code}",
         "expiry_date": str(timezone.localdate() + timedelta(days=540))}
        for line in order.lines.all()
    ]
    received = as_buyer.post(
        reverse("purchaseorder-receive", args=[order_id]),
        {"deliveries": deliveries, "delivery_note": "DN-88410"}, format="json",
    )
    assert received.status_code == 201, received.data
    assert len(received.data["lines"]) == 2

    order.refresh_from_db()
    assert order.status == PurchaseOrder.RECEIVED
    # On the shelf, in the store the request named.
    for line in order.lines.all():
        record = StockRecord.objects.get(store=stores["main"], item=line.item)
        assert record.on_hand() == line.quantity_ordered

    # The invoice.
    invoice = as_buyer.post(
        reverse("supplierinvoice-list"),
        {"order": order_id, "supplier_reference": "LMS-INV-9001",
         "invoice_date": str(timezone.localdate()),
         "amount": order.total_ordered()},
        format="json",
    )
    assert invoice.status_code == 201, invoice.data
    invoice_id = invoice.data["id"]

    matched = as_buyer.post(reverse("supplierinvoice-match", args=[invoice_id]))
    assert matched.status_code == 200
    assert matched.data["status"] == SupplierInvoice.MATCHED
    assert matched.data["discrepancies"] == []

    approved = as_approver.post(
        reverse("supplierinvoice-approve", args=[invoice_id]), {}, format="json",
    )
    assert approved.status_code == 200
    assert approved.data["status"] == SupplierInvoice.APPROVED
    assert approved.data["approved_by_email"] == purchase_approver.email

    # And every step left a trail.
    actions = set(AuditEvent.objects.values_list("action", flat=True))
    assert {
        "purchase_request.raised", "purchase_request.submitted",
        "purchase_request.decided", "purchase_order.raised", "goods.received",
        "supplier_invoice.recorded", "supplier_invoice.matched",
        "supplier_invoice.approved",
    } <= actions


# --- the separations -----------------------------------------------------

@pytest.mark.django_db
def test_a_buyer_cannot_approve_a_request(as_buyer, purchase_request):
    """Guarantee 4. Asking and committing money are different jobs."""
    _submit(as_buyer, purchase_request)
    response = _decide(as_buyer, purchase_request)
    assert response.status_code == 403
    purchase_request.refresh_from_db()
    assert purchase_request.status == PurchaseRequest.SUBMITTED


@pytest.mark.django_db
def test_an_approver_cannot_raise_the_order_they_approved(
    as_buyer, as_approver, purchase_request, supplier
):
    _submit(as_buyer, purchase_request)
    _decide(as_approver, purchase_request)
    response = _raise(as_approver, purchase_request, supplier)
    assert response.status_code == 403
    assert not PurchaseOrder.objects.exists()


@pytest.mark.django_db
def test_an_approver_cannot_approve_their_own_request_over_http(
    as_approver, stores, stock_items, purchase_approver
):
    """AC-153 (negative), through the API."""
    from inventory.procurement import new_request

    own = new_request(
        store=stores["main"], justification="I need this.",
        actor=purchase_approver,
        lines=[{"item": stock_items["gloves"], "quantity": 100, "cost": "1500.00"}],
    )
    assert as_approver.post(
        reverse("purchaserequest-submit", args=[own.pk])
    ).status_code == 403  # the approver holds no change_purchaserequest

    own.status = PurchaseRequest.SUBMITTED
    own.submitted_at = timezone.now()
    own.save(update_fields=["status", "submitted_at"])

    response = _decide(as_approver, own)
    assert response.status_code == 400
    assert "cannot be approved by the person who raised it" in response.data["detail"]
    own.refresh_from_db()
    assert own.status == PurchaseRequest.SUBMITTED


@pytest.mark.django_db
def test_the_person_who_entered_an_invoice_cannot_approve_it_over_http(
    as_buyer, as_approver, purchase_request, supplier, purchase_approver
):
    """The approver enters one, then tries to release it themselves."""
    _submit(as_buyer, purchase_request)
    _decide(as_approver, purchase_request)
    order_id = _raise(as_buyer, purchase_request, supplier).data["id"]
    order = PurchaseOrder.objects.get(pk=order_id)
    as_buyer.post(
        reverse("purchaseorder-receive", args=[order_id]),
        {"deliveries": [
            {"order_line": line.pk, "quantity": line.quantity_ordered,
             "lot_number": f"F-{line.item.code}",
             "expiry_date": str(timezone.localdate() + timedelta(days=540))}
            for line in order.lines.all()
        ]}, format="json",
    )

    # Entered by the buyer, so the buyer must not be the one approving it.
    invoice_id = as_buyer.post(
        reverse("supplierinvoice-list"),
        {"order": order_id, "supplier_reference": "INV-1",
         "invoice_date": str(timezone.localdate()), "amount": order.total_ordered()},
        format="json",
    ).data["id"]
    as_buyer.post(reverse("supplierinvoice-match", args=[invoice_id]))

    self_approved = as_buyer.post(
        reverse("supplierinvoice-approve", args=[invoice_id]), {}, format="json",
    )
    assert self_approved.status_code == 403  # no approve_supplier_invoice at all

    ok = as_approver.post(
        reverse("supplierinvoice-approve", args=[invoice_id]), {}, format="json",
    )
    assert ok.status_code == 200


# --- AC-155, AC-156 over HTTP -------------------------------------------

@pytest.mark.django_db
def test_a_short_delivery_over_http_leaves_the_order_open(
    as_buyer, as_approver, purchase_request, supplier
):
    """AC-155 (negative)."""
    _submit(as_buyer, purchase_request)
    _decide(as_approver, purchase_request)
    order_id = _raise(as_buyer, purchase_request, supplier).data["id"]
    order = PurchaseOrder.objects.get(pk=order_id)
    gloves = order.lines.get(item__code="GLV-M")

    received = as_buyer.post(
        reverse("purchaseorder-receive", args=[order_id]),
        {"deliveries": [
            {"order_line": gloves.pk, "quantity": 60, "lot_number": "PART-1",
             "expiry_date": str(timezone.localdate() + timedelta(days=540))}
        ], "delivery_note": "DN-1 of 2"}, format="json",
    )
    assert received.status_code == 201

    detail = as_buyer.get(reverse("purchaseorder-detail", args=[order_id]))
    assert detail.data["status"] == PurchaseOrder.PARTIALLY_RECEIVED
    lines = {line["item_code"]: line for line in detail.data["lines"]}
    assert lines["GLV-M"]["outstanding"] == 40
    assert lines["GLV-M"]["is_complete"] is False
    assert lines["SPT-500"]["quantity_received"] == 0

    # Still on the list of orders to chase.
    outstanding = as_buyer.get(f"{reverse('purchaseorder-list')}?outstanding=true")
    assert order_id in [row["id"] for row in outstanding.data["results"]]


@pytest.mark.django_db
def test_over_delivery_is_refused_over_http_and_nothing_is_shelved(
    as_buyer, as_approver, purchase_request, supplier
):
    _submit(as_buyer, purchase_request)
    _decide(as_approver, purchase_request)
    order_id = _raise(as_buyer, purchase_request, supplier).data["id"]
    order = PurchaseOrder.objects.get(pk=order_id)
    gloves = order.lines.get(item__code="GLV-M")

    response = as_buyer.post(
        reverse("purchaseorder-receive", args=[order_id]),
        {"deliveries": [
            {"order_line": gloves.pk, "quantity": 140, "lot_number": "TOO-MANY",
             "expiry_date": str(timezone.localdate() + timedelta(days=540))}
        ]}, format="json",
    )
    assert response.status_code == 400
    assert "still outstanding" in response.data["detail"]
    gloves.refresh_from_db()
    assert gloves.quantity_received == 0
    assert StockMovement.objects.count() == 0


@pytest.mark.django_db
def test_the_receipt_names_the_movement_that_shelved_each_line(
    as_buyer, as_approver, purchase_request, supplier
):
    """AC-156 over HTTP. The client can see the two are one act."""
    _submit(as_buyer, purchase_request)
    _decide(as_approver, purchase_request)
    order_id = _raise(as_buyer, purchase_request, supplier).data["id"]
    order = PurchaseOrder.objects.get(pk=order_id)
    gloves = order.lines.get(item__code="GLV-M")

    receipt = as_buyer.post(
        reverse("purchaseorder-receive", args=[order_id]),
        {"deliveries": [
            {"order_line": gloves.pk, "quantity": 100, "lot_number": "L-1",
             "expiry_date": str(timezone.localdate() + timedelta(days=540))}
        ]}, format="json",
    ).data

    line = receipt["lines"][0]
    assert line["movement"] is not None
    assert line["movement_balance"] == 100
    movement = StockMovement.objects.get(pk=line["movement"])
    assert movement.kind == StockMovement.RECEIPT
    assert movement.quantity_delta == 100


@pytest.mark.django_db
def test_a_goods_receipt_cannot_be_posted_directly(as_buyer):
    """A receipt is created by shelving goods, never on its own."""
    response = as_buyer.post(reverse("goodsreceipt-list"), {}, format="json")
    assert response.status_code in (403, 405)


# --- AC-157 over HTTP ---------------------------------------------------

@pytest.mark.django_db
def test_an_invoice_for_goods_that_never_came_is_queried_over_http(
    as_buyer, as_approver, purchase_request, supplier
):
    """AC-157. The discrepancies come back in words a person can read."""
    _submit(as_buyer, purchase_request)
    _decide(as_approver, purchase_request)
    order_id = _raise(as_buyer, purchase_request, supplier).data["id"]
    order = PurchaseOrder.objects.get(pk=order_id)
    gloves = order.lines.get(item__code="GLV-M")
    as_buyer.post(
        reverse("purchaseorder-receive", args=[order_id]),
        {"deliveries": [
            {"order_line": gloves.pk, "quantity": 60, "lot_number": "SHORT",
             "expiry_date": str(timezone.localdate() + timedelta(days=540))}
        ]}, format="json",
    )

    invoice_id = as_buyer.post(
        reverse("supplierinvoice-list"),
        {"order": order_id, "supplier_reference": "INV-SHORT",
         "invoice_date": str(timezone.localdate()), "amount": order.total_ordered()},
        format="json",
    ).data["id"]

    matched = as_buyer.post(reverse("supplierinvoice-match", args=[invoice_id]))
    assert matched.data["status"] == SupplierInvoice.QUERIED
    problems = " | ".join(matched.data["discrepancies"])
    assert "100 ordered, 60 received" in problems
    assert Decimal(matched.data["matched_value"]) == Decimal("90000.00")

    # Approving it needs a stated reason.
    blind = as_approver.post(
        reverse("supplierinvoice-approve", args=[invoice_id]), {}, format="json",
    )
    assert blind.status_code == 400
    assert "Say why it is being approved" in blind.data["detail"]

    with_reason = as_approver.post(
        reverse("supplierinvoice-approve", args=[invoice_id]),
        {"note": "Short delivery agreed; supplier will credit the difference."},
        format="json",
    )
    assert with_reason.status_code == 200
    assert with_reason.data["discrepancies"] != []

    event = AuditEvent.objects.get(action="supplier_invoice.approved")
    assert event.changes["after"]["discrepancies"] != []
    assert "credit the difference" in event.reason


# --- guarantee 1: facility isolation ------------------------------------

@pytest.mark.django_db
def test_a_request_for_another_facilitys_store_is_not_visible(
    as_buyer, stores, stock_items, purchase_buyer
):
    """Guarantee 1. 404 on the act, absent from the list."""
    from inventory.procurement import new_request

    theirs = new_request(
        store=stores["other_facility"],
        justification="Abuja needs gloves.", actor=purchase_buyer,
        lines=[{"item": stock_items["gloves"], "quantity": 10, "cost": "1500.00"}],
    )

    listed = as_buyer.get(reverse("purchaserequest-list"))
    assert theirs.pk not in [row["id"] for row in listed.data["results"]]

    assert as_buyer.post(
        reverse("purchaserequest-submit", args=[theirs.pk])
    ).status_code == 404


@pytest.mark.django_db
def test_an_order_cannot_be_raised_against_another_facilitys_request(
    as_buyer, stores, stock_items, purchase_buyer, supplier, purchase_approver
):
    from inventory.procurement import decide_request, new_request, submit_request

    theirs = new_request(
        store=stores["other_facility"],
        justification="Abuja needs gloves.", actor=purchase_buyer,
        lines=[{"item": stock_items["gloves"], "quantity": 10, "cost": "1500.00"}],
    )
    submit_request(theirs, actor=purchase_buyer)
    decide_request(theirs, approve=True, actor=purchase_approver, note="Agreed.")

    response = _raise(as_buyer, theirs, supplier)
    assert response.status_code == 404
    assert not PurchaseOrder.objects.exists()


@pytest.mark.django_db
def test_nobody_without_the_verb_touches_procurement(as_cashier, purchase_request):
    for url in (
        reverse("purchaserequest-list"),
        reverse("purchaseorder-list"),
        reverse("supplier-list"),
        reverse("supplierinvoice-list"),
    ):
        assert as_cashier.get(url).status_code == 403, url


# --- AC-151 over HTTP ---------------------------------------------------

@pytest.mark.django_db
def test_suspending_a_supplier_is_audited(as_approver, supplier):
    """Suspending stops new orders across every branch."""
    response = as_approver.patch(
        reverse("supplier-detail", args=[supplier.pk]),
        {"is_approved": False, "approval_note": "Two deliveries of expired stock."},
        format="json",
    )
    assert response.status_code == 200
    event = AuditEvent.objects.get(action="supplier.approval_changed")
    assert event.changes["before"]["is_approved"] is True
    assert event.changes["after"]["is_approved"] is False
    assert "expired stock" in event.reason


@pytest.mark.django_db
def test_only_approved_suppliers_can_be_filtered_for_ordering(
    as_buyer, supplier, suspended_supplier
):
    response = as_buyer.get(f"{reverse('supplier-list')}?approved=true")
    codes = [row["code"] for row in response.data["results"]]
    assert "LMS" in codes
    assert "CIL" not in codes
