"""AC-143 to AC-150 — stores, stock, and the one thing that must never happen.

Stock going negative is not an accounting untidiness. It means a theatre list
was planned against gloves that are not in the building, and somebody finds out
with the patient already asleep.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connections, transaction
from django.utils import timezone

from inventory.models import (
    StockAdjustment,
    StockLot,
    StockMovement,
    StockRecord,
)
from inventory.stock import (
    adjust,
    expiring,
    issue,
    low_stock,
    receive,
    reconstruct_balance,
    transfer,
)

# --- AC-143, AC-144: what is stocked, and where ----------------------------

@pytest.mark.django_db
def test_an_item_is_administrable_without_touching_code(stock_items):
    """AC-143."""
    gloves = stock_items["gloves"]
    assert gloves.unit_of_issue == "box of 100"
    assert gloves.default_reorder_level == 20
    assert gloves.is_controlled is False
    assert stock_items["spirit"].is_controlled is True
    # A bed pan does not expire, and the form should not ask.
    assert stock_items["bedpan"].tracks_expiry is False


@pytest.mark.django_db
def test_stock_is_held_per_store_not_per_facility(stores, stock_items, storekeeper):
    """AC-144. The theatre running out while the main store is full.

    Treating a facility as one pool is exactly the bug this criterion exists to
    prevent: the number on the screen is right for the hospital and wrong for
    the room the patient is in.
    """
    main = StockRecord.objects.create(
        store=stores["main"], item=stock_items["gloves"], reorder_level=20
    )
    theatre = StockRecord.objects.create(
        store=stores["theatre"], item=stock_items["gloves"], reorder_level=5
    )
    receive(record=main, quantity=40, actor=storekeeper, lot_number="M-1",
            expiry_date=timezone.localdate() + timedelta(days=200))

    assert main.on_hand() == 40
    assert theatre.on_hand() == 0
    # And the theatre is the one that is out, whatever the facility holds.
    assert theatre.is_low is True
    assert main.is_low is False


@pytest.mark.django_db
def test_a_store_carrying_nothing_differs_from_a_store_not_carrying_it(
    stores, stock_items, storekeeper
):
    """"We are out of gloves" and "we do not stock gloves" need different acts."""
    carried = StockRecord.objects.create(
        store=stores["theatre"], item=stock_items["gloves"], reorder_level=5
    )
    assert carried.on_hand() == 0
    assert carried.is_low is True
    assert not StockRecord.objects.filter(
        store=stores["theatre"], item=stock_items["bedpan"]
    ).exists()


# --- AC-145: every movement says what, how much, where, why and who --------

@pytest.mark.django_db
def test_every_movement_records_the_act_behind_it(gloves_in_main, storekeeper):
    """AC-145."""
    issue(record=gloves_in_main, quantity=10, actor=storekeeper,
          issued_to="Theatre 2", reason="Elective list, Tuesday")

    movement = StockMovement.objects.filter(kind=StockMovement.ISSUE).get()
    assert movement.quantity_delta == -10
    assert movement.issued_to == "Theatre 2"
    assert movement.reason == "Elective list, Tuesday"
    assert movement.recorded_by == storekeeper
    assert movement.lot.record.store == gloves_in_main.store
    # And the balance afterwards, so a discrepancy has a point in time.
    assert movement.quantity_after == 20


@pytest.mark.django_db
def test_a_transfer_is_two_movements_so_each_store_balances(
    gloves_in_main, stores, storekeeper
):
    """AC-145. One row with a from and a to leaves neither ledger provable."""
    record = transfer(
        item=gloves_in_main.item, from_store=stores["main"],
        to_store=stores["theatre"], quantity=25, actor=storekeeper,
        reason="Theatre topped up for the week",
    )

    out = record.movements.filter(kind=StockMovement.TRANSFER_OUT)
    into = record.movements.filter(kind=StockMovement.TRANSFER_IN)
    assert sum(m.quantity_delta for m in out) == -25
    assert sum(m.quantity_delta for m in into) == 25

    theatre = StockRecord.objects.get(store=stores["theatre"], item=gloves_in_main.item)
    assert theatre.on_hand() == 25
    assert gloves_in_main.on_hand() == 55


@pytest.mark.django_db
def test_a_transfer_carries_the_expiry_date_with_the_stock(
    gloves_in_main, stores, storekeeper
):
    """Stock landing on a ward as fresh is how expired goods reach a bedside."""
    transfer(item=gloves_in_main.item, from_store=stores["main"],
             to_store=stores["theatre"], quantity=30, actor=storekeeper)

    theatre = StockRecord.objects.get(store=stores["theatre"], item=gloves_in_main.item)
    landed = {lot.lot_number: lot.expiry_date for lot in theatre.lots.all()}
    original = {lot.lot_number: lot.expiry_date for lot in gloves_in_main.lots.all()}
    assert landed["L-OLD"] == original["L-OLD"]


@pytest.mark.django_db
def test_stock_does_not_move_between_facilities_as_a_store_transfer(
    gloves_in_main, stores, storekeeper
):
    """The audit trail must not go quiet at the facility boundary. Guarantee 1."""
    with pytest.raises(ValidationError, match="different facilities"):
        transfer(item=gloves_in_main.item, from_store=stores["main"],
                 to_store=stores["other_facility"], quantity=5, actor=storekeeper)
    assert gloves_in_main.on_hand() == 80


# --- AC-146 (the gate): stock cannot go negative under concurrency ---------

@pytest.mark.django_db(transaction=True)
def test_twelve_simultaneous_issues_of_the_last_box_produce_one_issue(
    stores, stock_items, storekeeper
):
    """AC-146, the gate.

    Twelve people pressing Issue on the last box at the same instant. Eleven
    have to be told no, and the store has to end on zero rather than on minus
    eleven — a negative balance is a number nobody can act on and a shortage
    nobody was warned about.
    """
    record = StockRecord.objects.create(
        store=stores["main"], item=stock_items["gloves"], reorder_level=0
    )
    receive(record=record, quantity=1, actor=storekeeper, lot_number="LAST",
            expiry_date=timezone.localdate() + timedelta(days=90))

    def take(_):
        try:
            with transaction.atomic():
                issue(record=record, quantity=1, actor=storekeeper,
                      issued_to="Ward 1")
            return "issued"
        except ValidationError:
            return "refused"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=12) as pool:
        outcomes = list(pool.map(take, range(12)))

    assert outcomes.count("issued") == 1, outcomes
    assert outcomes.count("refused") == 11
    assert record.on_hand() == 0
    assert StockMovement.objects.filter(kind=StockMovement.ISSUE).count() == 1


@pytest.mark.django_db
def test_issuing_more_than_is_there_is_refused_with_the_figure(
    gloves_in_main, storekeeper
):
    """A refusal a storekeeper can act on names the number."""
    with pytest.raises(ValidationError, match="Only 80 box of 100"):
        issue(record=gloves_in_main, quantity=100, actor=storekeeper,
              issued_to="Ward 1")
    assert gloves_in_main.on_hand() == 80


@pytest.mark.django_db
def test_the_database_refuses_a_negative_balance_even_if_the_code_asks(
    gloves_in_main
):
    """The constraint behind the conditional UPDATE. AC-146."""
    from django.db import IntegrityError

    lot = gloves_in_main.lots.first()
    with pytest.raises(IntegrityError):
        StockLot.objects.filter(pk=lot.pk).update(quantity_on_hand=-1)


@pytest.mark.django_db
def test_issuing_takes_the_soonest_expiry_first(gloves_in_main, storekeeper):
    """Not a preference: stock issued newest-first expires on the shelf."""
    issue(record=gloves_in_main, quantity=30, actor=storekeeper, issued_to="Ward 1")

    old = gloves_in_main.lots.get(lot_number="L-OLD")
    new = gloves_in_main.lots.get(lot_number="L-NEW")
    assert old.quantity_on_hand == 0
    assert new.quantity_on_hand == 50


@pytest.mark.django_db
def test_an_issue_spanning_two_lots_records_a_movement_for_each(
    gloves_in_main, storekeeper
):
    """One movement for 40 across two lots would make the ledger unprovable."""
    movements = issue(record=gloves_in_main, quantity=40, actor=storekeeper,
                      issued_to="Ward 1")
    assert len(movements) == 2
    assert sorted(m.quantity_delta for m in movements) == [-30, -10]
    assert gloves_in_main.on_hand() == 40


# --- AC-147: an adjustment needs a reason, and sometimes a second person ---

@pytest.mark.django_db
def test_a_small_adjustment_needs_only_a_reason(gloves_in_main, storekeeper):
    """AC-147. ₦1,500 against a ₦10,000 limit."""
    lot = gloves_in_main.lots.get(lot_number="L-OLD")
    record = adjust(lot=lot, quantity_delta=-1, kind=StockAdjustment.DAMAGE,
                    reason="One box crushed in the delivery.", actor=storekeeper)
    assert record.authorised_by is None
    assert record.value == Decimal("1500.00")
    lot.refresh_from_db()
    assert lot.quantity_on_hand == 29


@pytest.mark.django_db
def test_a_large_adjustment_is_refused_without_a_second_person(
    gloves_in_main, storekeeper
):
    """AC-147 (negative). ₦15,000 against a ₦10,000 limit."""
    lot = gloves_in_main.lots.get(lot_number="L-OLD")
    with pytest.raises(ValidationError, match="second person's authorisation"):
        adjust(lot=lot, quantity_delta=-10, kind=StockAdjustment.LOSS,
               reason="Ten boxes unaccounted for at the monthly count.",
               actor=storekeeper)
    lot.refresh_from_db()
    assert lot.quantity_on_hand == 30
    assert not StockAdjustment.objects.exists()


@pytest.mark.django_db
def test_a_large_adjustment_goes_through_with_one(
    gloves_in_main, storekeeper, stores_manager
):
    lot = gloves_in_main.lots.get(lot_number="L-OLD")
    record = adjust(lot=lot, quantity_delta=-10, kind=StockAdjustment.LOSS,
                    reason="Ten boxes unaccounted for at the monthly count.",
                    actor=storekeeper, authorised_by=stores_manager)
    assert record.authorised_by == stores_manager
    assert record.value == Decimal("15000.00")
    lot.refresh_from_db()
    assert lot.quantity_on_hand == 20


@pytest.mark.django_db
def test_nobody_authorises_their_own_adjustment(gloves_in_main, storekeeper):
    """A signature somebody supplies for themselves is not a control."""
    lot = gloves_in_main.lots.get(lot_number="L-OLD")
    with pytest.raises(ValidationError, match="cannot be authorised by the person"):
        adjust(lot=lot, quantity_delta=-10, kind=StockAdjustment.LOSS,
               reason="Counted short.", actor=storekeeper,
               authorised_by=storekeeper)
    assert not StockAdjustment.objects.exists()


@pytest.mark.django_db
def test_a_store_can_require_authorisation_for_everything(
    stores, stock_items, storekeeper
):
    """A limit of zero. Reasonable for implants, miserable for linen — which is
    why it is the store's setting rather than the code's."""
    record = StockRecord.objects.create(
        store=stores["theatre"], item=stock_items["gloves"], reorder_level=5
    )
    receive(record=record, quantity=10, actor=storekeeper, lot_number="T-1",
            expiry_date=timezone.localdate() + timedelta(days=90),
            unit_cost=Decimal("1500.00"))
    lot = record.lots.get()
    with pytest.raises(ValidationError, match="above 0.00"):
        adjust(lot=lot, quantity_delta=-1, kind=StockAdjustment.DAMAGE,
               reason="One box torn.", actor=storekeeper)


@pytest.mark.django_db
def test_an_adjustment_without_a_reason_is_refused(gloves_in_main, storekeeper):
    """AC-147 (negative)."""
    lot = gloves_in_main.lots.get(lot_number="L-OLD")
    with pytest.raises(ValidationError, match="needs a reason"):
        adjust(lot=lot, quantity_delta=-1, kind=StockAdjustment.DAMAGE,
               reason="   ", actor=storekeeper)


@pytest.mark.django_db
def test_an_adjustment_cannot_write_off_more_than_the_lot_holds(
    gloves_in_main, storekeeper, stores_manager
):
    lot = gloves_in_main.lots.get(lot_number="L-OLD")
    with pytest.raises(ValidationError, match="holds 30"):
        adjust(lot=lot, quantity_delta=-40, kind=StockAdjustment.LOSS,
               reason="Whole lot missing.", actor=storekeeper,
               authorised_by=stores_manager)


# --- AC-148: expired stock cannot be issued -------------------------------

@pytest.mark.django_db
def test_expired_stock_cannot_be_issued_and_the_refusal_names_the_date(
    stores, stock_items, storekeeper
):
    """AC-148 (negative).

    "Cannot issue" sends a storekeeper to look for the problem. "Expired on
    03 Aug 2026" tells them which boxes to pull off the shelf.
    """
    record = StockRecord.objects.create(
        store=stores["main"], item=stock_items["gloves"], reorder_level=0
    )
    expired_on = timezone.localdate() - timedelta(days=30)
    # Received in date, then time passed — the only honest way to get there,
    # since receiving expired stock is itself refused.
    receive(record=record, quantity=20, actor=storekeeper, lot_number="GONE",
            expiry_date=timezone.localdate() + timedelta(days=1))
    StockLot.objects.filter(record=record).update(expiry_date=expired_on)
    receive(record=record, quantity=5, actor=storekeeper, lot_number="GOOD",
            expiry_date=timezone.localdate() + timedelta(days=200))

    with pytest.raises(ValidationError) as refusal:
        issue(record=record, quantity=10, actor=storekeeper, issued_to="Ward 1")
    message = str(refusal.value)
    assert "Only 5" in message
    assert expired_on.strftime("%d %b %Y") in message

    # The in-date stock is still issuable.
    issue(record=record, quantity=5, actor=storekeeper, issued_to="Ward 1")
    assert record.usable_on_hand() == 0
    # And the expired boxes are still on the shelf, to be written off.
    assert record.on_hand() == 20


@pytest.mark.django_db
def test_expired_stock_is_not_received_into_a_store(
    stores, stock_items, storekeeper
):
    record = StockRecord.objects.create(
        store=stores["main"], item=stock_items["gloves"], reorder_level=0
    )
    with pytest.raises(ValidationError, match="expired on"):
        receive(record=record, quantity=10, actor=storekeeper, lot_number="DEAD",
                expiry_date=timezone.localdate() - timedelta(days=1))


@pytest.mark.django_db
def test_an_item_tracked_by_expiry_cannot_be_received_without_one(
    stores, stock_items, storekeeper
):
    record = StockRecord.objects.create(
        store=stores["main"], item=stock_items["gloves"], reorder_level=0
    )
    with pytest.raises(ValidationError, match="tracked by expiry date"):
        receive(record=record, quantity=10, actor=storekeeper, lot_number="NO-DATE")


@pytest.mark.django_db
def test_an_item_that_does_not_expire_is_not_asked_for_a_date(
    stores, stock_items, storekeeper
):
    """Asking for an expiry on a bed pan teaches a storekeeper to invent one."""
    record = StockRecord.objects.create(
        store=stores["main"], item=stock_items["bedpan"], reorder_level=4
    )
    receive(record=record, quantity=6, actor=storekeeper)
    assert record.on_hand() == 6
    assert record.lots.get().expiry_date is None
    assert record.usable_on_hand() == 6


@pytest.mark.django_db
def test_one_lot_number_cannot_carry_two_expiry_dates(
    stores, stock_items, storekeeper
):
    record = StockRecord.objects.create(
        store=stores["main"], item=stock_items["gloves"], reorder_level=0
    )
    today = timezone.localdate()
    receive(record=record, quantity=10, actor=storekeeper, lot_number="SAME",
            expiry_date=today + timedelta(days=90))
    with pytest.raises(ValidationError, match="cannot both be right"):
        receive(record=record, quantity=10, actor=storekeeper, lot_number="SAME",
                expiry_date=today + timedelta(days=180))


@pytest.mark.django_db
def test_a_repeat_delivery_of_one_lot_adds_to_it(stores, stock_items, storekeeper):
    record = StockRecord.objects.create(
        store=stores["main"], item=stock_items["gloves"], reorder_level=0
    )
    expiry = timezone.localdate() + timedelta(days=90)
    receive(record=record, quantity=10, actor=storekeeper, lot_number="SAME",
            expiry_date=expiry)
    receive(record=record, quantity=15, actor=storekeeper, lot_number="SAME",
            expiry_date=expiry)
    assert record.lots.count() == 1
    assert record.on_hand() == 25


# --- controlled items -----------------------------------------------------

@pytest.mark.django_db
def test_a_controlled_item_cannot_leave_without_a_named_recipient(
    stores, stock_items, storekeeper
):
    record = StockRecord.objects.create(
        store=stores["main"], item=stock_items["spirit"], reorder_level=10
    )
    receive(record=record, quantity=20, actor=storekeeper, lot_number="SP-1",
            expiry_date=timezone.localdate() + timedelta(days=365))
    with pytest.raises(ValidationError, match="controlled item"):
        issue(record=record, quantity=2, actor=storekeeper)
    assert record.on_hand() == 20

    issue(record=record, quantity=2, actor=storekeeper,
          issued_to="Sister Fatima Bello, Ward 2")
    assert record.on_hand() == 18


# --- AC-149: low stock and expiry, per store ------------------------------

@pytest.mark.django_db
def test_low_stock_is_reported_per_store_against_its_own_level(
    stores, stock_items, storekeeper
):
    """AC-149."""
    main = StockRecord.objects.create(
        store=stores["main"], item=stock_items["gloves"], reorder_level=20
    )
    theatre = StockRecord.objects.create(
        store=stores["theatre"], item=stock_items["gloves"], reorder_level=5
    )
    expiry = timezone.localdate() + timedelta(days=200)
    receive(record=main, quantity=15, actor=storekeeper, lot_number="M", expiry_date=expiry)
    receive(record=theatre, quantity=15, actor=storekeeper, lot_number="T", expiry_date=expiry)

    low = low_stock(store=stores["main"])
    assert [record.pk for record in low] == [main.pk]
    # Same quantity, different level, different answer.
    assert low_stock(store=stores["theatre"]) == []


@pytest.mark.django_db
def test_expired_stock_does_not_count_towards_the_reorder_level(
    stores, stock_items, storekeeper
):
    """A store with forty expired boxes and none in date is out.

    Counting them would report the store as full, and the shortage would be
    discovered at the point of use.
    """
    record = StockRecord.objects.create(
        store=stores["main"], item=stock_items["gloves"], reorder_level=20
    )
    receive(record=record, quantity=40, actor=storekeeper, lot_number="OLD",
            expiry_date=timezone.localdate() + timedelta(days=1))
    StockLot.objects.filter(record=record).update(
        expiry_date=timezone.localdate() - timedelta(days=5)
    )

    assert record.on_hand() == 40
    assert record.usable_on_hand() == 0
    assert [entry.pk for entry in low_stock(store=stores["main"])] == [record.pk]


@pytest.mark.django_db
def test_expiring_stock_is_reported_against_each_store_s_own_horizon(
    stores, stock_items, storekeeper
):
    """AC-149. One hospital-wide horizon suits nobody."""
    stores["main"].expiry_horizon_days = 30
    stores["main"].save(update_fields=["expiry_horizon_days"])
    stores["theatre"].expiry_horizon_days = 180
    stores["theatre"].save(update_fields=["expiry_horizon_days"])

    in_60_days = timezone.localdate() + timedelta(days=60)
    main = StockRecord.objects.create(
        store=stores["main"], item=stock_items["gloves"], reorder_level=0
    )
    theatre = StockRecord.objects.create(
        store=stores["theatre"], item=stock_items["gloves"], reorder_level=0
    )
    receive(record=main, quantity=10, actor=storekeeper, lot_number="M",
            expiry_date=in_60_days)
    receive(record=theatre, quantity=10, actor=storekeeper, lot_number="T",
            expiry_date=in_60_days)

    assert expiring(store=stores["main"]) == []
    assert [lot.record_id for lot in expiring(store=stores["theatre"])] == [theatre.pk]


@pytest.mark.django_db
def test_an_item_with_no_expiry_never_appears_as_expiring(
    stores, stock_items, storekeeper
):
    record = StockRecord.objects.create(
        store=stores["main"], item=stock_items["bedpan"], reorder_level=0
    )
    receive(record=record, quantity=6, actor=storekeeper)
    assert expiring(store=stores["main"], horizon_days=3650) == []


# --- AC-150: the ledger reconstructs the balance --------------------------

@pytest.mark.django_db
def test_the_movements_reconstruct_the_balance_at_every_point(
    stores, stock_items, storekeeper, stores_manager
):
    """AC-150.

    A property over a generated sequence rather than a single scripted case.
    The running total has to equal the balance recorded on each movement at
    *every* step, not only at the end — a ledger that agrees only on the last
    row cannot say when it diverged, which is the one question a stock
    discrepancy asks.
    """
    import random

    random.seed(20260909)
    record = StockRecord.objects.create(
        store=stores["main"], item=stock_items["gloves"], reorder_level=0
    )
    expiry = timezone.localdate() + timedelta(days=365)
    receive(record=record, quantity=200, actor=storekeeper, lot_number="P",
            expiry_date=expiry, unit_cost=Decimal("10.00"))
    lot = record.lots.get()

    for _ in range(40):
        action = random.choice(["receive", "issue", "adjust_down", "adjust_up"])
        quantity = random.randint(1, 12)
        try:
            if action == "receive":
                receive(record=record, quantity=quantity, actor=storekeeper,
                        lot_number="P", expiry_date=expiry, unit_cost=Decimal("10.00"))
            elif action == "issue":
                issue(record=record, quantity=quantity, actor=storekeeper,
                      issued_to="Ward 1")
            elif action == "adjust_down":
                adjust(lot=lot, quantity_delta=-quantity,
                       kind=StockAdjustment.DAMAGE, reason="Damaged in store.",
                       actor=storekeeper, authorised_by=stores_manager)
            else:
                adjust(lot=lot, quantity_delta=quantity,
                       kind=StockAdjustment.COUNT_CORRECTION,
                       reason="Found at the count.", actor=storekeeper,
                       authorised_by=stores_manager)
        except ValidationError:
            # A refusal is a legitimate outcome and must leave the ledger
            # untouched — which the assertions below check on the next pass.
            pass

        trail = reconstruct_balance(lot)
        for step in trail:
            assert step["running"] == step["recorded"], (
                f"ledger diverged at movement {step['movement']}: "
                f"running {step['running']} against recorded {step['recorded']}"
            )

    lot.refresh_from_db()
    trail = reconstruct_balance(lot)
    assert trail, "the sequence produced no movements at all"
    assert trail[-1]["running"] == lot.quantity_on_hand
    assert lot.quantity_on_hand >= 0


@pytest.mark.django_db
def test_a_refused_issue_leaves_no_movement_behind(gloves_in_main, storekeeper):
    """Half an issue in the ledger is worse than none."""
    before = StockMovement.objects.count()
    with pytest.raises(ValidationError):
        issue(record=gloves_in_main, quantity=500, actor=storekeeper,
              issued_to="Ward 1")
    assert StockMovement.objects.count() == before
    assert gloves_in_main.on_hand() == 80
