"""AC-151 to AC-157 — buying things.

Two criteria carry the weight here. AC-153, that an approver cannot approve
their own request, is the only thing making the approval step mean anything.
AC-156, that a goods receipt and a stock movement cannot exist without each
other, is what stops a delivery being recorded on paper and never reaching a
shelf — stock the hospital believes it has and cannot find.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from inventory.models import (
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseRequest,
    StockMovement,
    StockRecord,
    SupplierInvoice,
)
from inventory.procurement import (
    approve_invoice,
    cancel_order,
    decide_request,
    match_invoice,
    new_request,
    outstanding_orders,
    raise_order,
    receive_goods,
    run_match,
    submit_request,
)


def _prices(request, amount="1500.00"):
    return {line.item_id: amount for line in request.lines.all()}


def _order(request, supplier, actor, prices=None):
    submit_request(request, actor=request.requested_by)
    decide_request(request, approve=True, actor=actor, note="Agreed.")
    return raise_order(
        request=request, supplier=supplier, actor=request.requested_by,
        prices=prices or _prices(request),
        expected_date=timezone.localdate() + timedelta(days=7),
    )


# --- AC-151: suppliers ----------------------------------------------------

@pytest.mark.django_db
def test_a_supplier_carries_terms_and_whether_they_may_supply(
    supplier, suspended_supplier
):
    """AC-151."""
    assert supplier.payment_terms_days == 30
    assert supplier.is_approved is True
    assert suspended_supplier.is_approved is False
    assert "expired stock" in suspended_supplier.approval_note


@pytest.mark.django_db
def test_an_unapproved_supplier_cannot_be_ordered_from(
    purchase_request, suspended_supplier, purchase_approver
):
    """AC-151. And the refusal says why, so nobody re-tries it blindly."""
    submit_request(purchase_request, actor=purchase_request.requested_by)
    decide_request(purchase_request, approve=True, actor=purchase_approver,
                   note="Agreed.")
    with pytest.raises(ValidationError, match="expired stock"):
        raise_order(
            request=purchase_request, supplier=suspended_supplier,
            actor=purchase_request.requested_by, prices=_prices(purchase_request),
        )
    assert not PurchaseOrder.objects.exists()


@pytest.mark.django_db
def test_suspending_a_supplier_does_not_disturb_their_past_orders(
    purchase_request, supplier, purchase_approver
):
    """Approval is a state, not a deletion.

    A supplier who supplied for three years and is now suspended still has to
    appear on the orders they fulfilled.
    """
    order = _order(purchase_request, supplier, purchase_approver)
    supplier.is_approved = False
    supplier.approval_note = "Under review."
    supplier.save(update_fields=["is_approved", "approval_note"])

    order.refresh_from_db()
    assert order.supplier == supplier
    assert order.supplier.name == "Lagos Medical Supplies"


# --- AC-152, AC-153: asking and approving ---------------------------------

@pytest.mark.django_db
def test_a_request_records_who_where_what_and_why(purchase_request, stores):
    """AC-152."""
    assert purchase_request.store == stores["main"]
    assert "shelf is empty" in purchase_request.justification
    assert purchase_request.lines.count() == 2
    assert purchase_request.status == PurchaseRequest.DRAFT
    # 100 × 1,500 + 40 × 800 = 182,000
    assert purchase_request.estimated_value() == Decimal("182000.00")


@pytest.mark.django_db
def test_a_request_above_the_stores_limit_needs_approval(purchase_request, stores):
    """AC-152. ₦182,000 against the main store's ₦10,000 limit."""
    assert purchase_request.needs_approval() is True


@pytest.mark.django_db
def test_a_small_request_can_be_ordered_without_a_decision(
    stores, stock_items, purchase_buyer, supplier
):
    """AC-152. Requiring a signature for a ₦3,000 box of gloves teaches
    everybody to route around the control."""
    small = new_request(
        store=stores["main"], justification="Two boxes to see the week out.",
        actor=purchase_buyer,
        lines=[{"item": stock_items["gloves"], "quantity": 2, "cost": "1500.00"}],
    )
    assert small.needs_approval() is False
    submit_request(small, actor=purchase_buyer)
    order = raise_order(
        request=small, supplier=supplier, actor=purchase_buyer,
        prices=_prices(small),
    )
    assert order.status == PurchaseOrder.OPEN


@pytest.mark.django_db
def test_an_approver_cannot_approve_their_own_request(
    stores, stock_items, purchase_approver
):
    """AC-153 (negative). The one thing that makes the step mean anything."""
    own = new_request(
        store=stores["main"], justification="I need this.",
        actor=purchase_approver,
        lines=[{"item": stock_items["gloves"], "quantity": 100, "cost": "1500.00"}],
    )
    submit_request(own, actor=purchase_approver)
    with pytest.raises(ValidationError, match="cannot be approved by the person"):
        decide_request(own, approve=True, actor=purchase_approver, note="Fine.")

    own.refresh_from_db()
    assert own.status == PurchaseRequest.SUBMITTED
    assert own.decided_by is None


@pytest.mark.django_db
def test_the_database_refuses_a_self_approved_request_too(
    stores, stock_items, purchase_approver
):
    """AC-153. The service checks it; the database makes it unrepresentable."""
    own = new_request(
        store=stores["main"], justification="I need this.",
        actor=purchase_approver,
        lines=[{"item": stock_items["gloves"], "quantity": 1, "cost": "1.00"}],
    )
    with pytest.raises(IntegrityError):
        PurchaseRequest.objects.filter(pk=own.pk).update(
            status=PurchaseRequest.APPROVED, decided_by=purchase_approver,
            decided_at=timezone.now(),
        )


@pytest.mark.django_db
def test_a_request_cannot_be_marked_approved_with_nobody_named(
    purchase_request
):
    """A decision with no decider is not a decision."""
    with pytest.raises(IntegrityError):
        PurchaseRequest.objects.filter(pk=purchase_request.pk).update(
            status=PurchaseRequest.APPROVED
        )


@pytest.mark.django_db
def test_an_empty_request_cannot_be_submitted(stores, purchase_buyer):
    """"We need things" is not something an approver can approve."""
    empty = new_request(
        store=stores["main"], justification="Stock is low across the board.",
        actor=purchase_buyer, lines=[],
    )
    with pytest.raises(ValidationError, match="at least one item"):
        submit_request(empty, actor=purchase_buyer)


@pytest.mark.django_db
def test_a_rejection_must_say_why(purchase_request, purchase_approver):
    """A rejection with no reason leaves the requester with nothing to change."""
    submit_request(purchase_request, actor=purchase_request.requested_by)
    with pytest.raises(ValidationError, match="Say why it is rejected"):
        decide_request(purchase_request, approve=False, actor=purchase_approver)

    purchase_request.refresh_from_db()
    assert purchase_request.status == PurchaseRequest.SUBMITTED


@pytest.mark.django_db
def test_a_large_request_cannot_be_ordered_without_approval(
    purchase_request, supplier
):
    """AC-152 (negative)."""
    submit_request(purchase_request, actor=purchase_request.requested_by)
    with pytest.raises(ValidationError, match="needs approval"):
        raise_order(
            request=purchase_request, supplier=supplier,
            actor=purchase_request.requested_by, prices=_prices(purchase_request),
        )


# --- AC-154: the order ----------------------------------------------------

@pytest.mark.django_db
def test_an_order_carries_the_supplier_the_agreed_prices_and_the_date(
    purchase_request, supplier, purchase_approver, stock_items
):
    """AC-154. The agreed price, not the estimate."""
    order = _order(
        purchase_request, supplier, purchase_approver,
        prices={
            stock_items["gloves"].pk: "1425.00",   # negotiated down
            stock_items["spirit"].pk: "800.00",
        },
    )
    assert order.supplier == supplier
    assert order.store == purchase_request.store
    assert order.expected_date == timezone.localdate() + timedelta(days=7)
    prices = {line.item.code: line.unit_cost for line in order.lines.all()}
    assert prices["GLV-M"] == Decimal("1425.00")
    # 100 × 1,425 + 40 × 800 = 174,500 — the estimate was 182,000.
    assert order.total_ordered() == Decimal("174500.00")
    assert purchase_request.estimated_value() == Decimal("182000.00")

    purchase_request.refresh_from_db()
    assert purchase_request.status == PurchaseRequest.ORDERED


@pytest.mark.django_db
def test_an_order_needs_a_price_for_every_line(
    purchase_request, supplier, purchase_approver, stock_items
):
    submit_request(purchase_request, actor=purchase_request.requested_by)
    decide_request(purchase_request, approve=True, actor=purchase_approver,
                   note="Agreed.")
    with pytest.raises(ValidationError, match="Methylated spirit"):
        raise_order(
            request=purchase_request, supplier=supplier,
            actor=purchase_request.requested_by,
            prices={stock_items["gloves"].pk: "1500.00"},
        )


# --- AC-155, AC-156: goods arriving --------------------------------------

@pytest.mark.django_db
def test_receiving_goods_puts_them_on_the_shelf(
    purchase_request, supplier, purchase_approver, purchase_buyer, stores
):
    """AC-156. The receipt and the movement are one act."""
    order = _order(purchase_request, supplier, purchase_approver)
    gloves_line = order.lines.get(item__code="GLV-M")

    receipt = receive_goods(
        order=order, actor=purchase_buyer, delivery_note="DN-88410",
        deliveries=[{
            "order_line": gloves_line, "quantity": 100, "lot_number": "LMS-4410",
            "expiry_date": timezone.localdate() + timedelta(days=540),
        }],
    )

    record = StockRecord.objects.get(store=stores["main"], item=gloves_line.item)
    assert record.on_hand() == 100
    lot = record.lots.get(lot_number="LMS-4410")
    assert lot.unit_cost == gloves_line.unit_cost

    line = receipt.lines.get()
    assert line.movement.kind == StockMovement.RECEIPT
    assert line.movement.quantity_delta == 100
    assert line.movement.lot == lot
    assert order.reference in line.movement.reason


@pytest.mark.django_db
def test_a_receipt_line_cannot_exist_without_a_stock_movement(
    purchase_request, supplier, purchase_approver, purchase_buyer
):
    """AC-156 (negative).

    Not "the code always creates one" — the column is not nullable, so a
    delivery recorded on paper and never shelved is unrepresentable.
    """
    order = _order(purchase_request, supplier, purchase_approver)
    line = order.lines.first()
    with pytest.raises((IntegrityError, ValueError)):
        GoodsReceiptLine.objects.create(
            receipt=receive_goods(
                order=order, actor=purchase_buyer,
                deliveries=[{
                    "order_line": line, "quantity": 1, "lot_number": "X",
                    "expiry_date": timezone.localdate() + timedelta(days=90),
                }],
            ),
            order_line=line, quantity=5, lot_number="GHOST",
            expiry_date=timezone.localdate() + timedelta(days=90),
            movement=None,
        )


@pytest.mark.django_db
def test_a_short_delivery_leaves_the_line_open(
    purchase_request, supplier, purchase_approver, purchase_buyer
):
    """AC-155 (negative).

    The tempting implementation marks a line received when anything arrives
    against it, which turns every partial delivery into a silent write-off of
    the rest — and a storekeeper stops chasing goods the hospital paid for.
    """
    order = _order(purchase_request, supplier, purchase_approver)
    gloves = order.lines.get(item__code="GLV-M")

    receive_goods(
        order=order, actor=purchase_buyer, delivery_note="DN-1 of 2",
        deliveries=[{
            "order_line": gloves, "quantity": 60, "lot_number": "PART-1",
            "expiry_date": timezone.localdate() + timedelta(days=540),
        }],
    )

    gloves.refresh_from_db()
    order.refresh_from_db()
    assert gloves.quantity_received == 60
    assert gloves.outstanding == 40
    assert gloves.is_complete is False
    assert order.status == PurchaseOrder.PARTIALLY_RECEIVED
    assert order in list(outstanding_orders(store=order.store))

    # The rest arrives later, on its own lot with its own expiry.
    receive_goods(
        order=order, actor=purchase_buyer, delivery_note="DN-2 of 2",
        deliveries=[{
            "order_line": gloves, "quantity": 40, "lot_number": "PART-2",
            "expiry_date": timezone.localdate() + timedelta(days=600),
        }],
    )
    gloves.refresh_from_db()
    assert gloves.is_complete is True
    assert {lot.lot_number for lot in gloves.item.records.get().lots.all()} == {
        "PART-1", "PART-2"
    }


@pytest.mark.django_db
def test_more_cannot_be_received_than_was_ordered(
    purchase_request, supplier, purchase_approver, purchase_buyer
):
    """An over-delivery changes what the hospital owes."""
    order = _order(purchase_request, supplier, purchase_approver)
    gloves = order.lines.get(item__code="GLV-M")
    with pytest.raises(ValidationError, match="still outstanding"):
        receive_goods(
            order=order, actor=purchase_buyer,
            deliveries=[{
                "order_line": gloves, "quantity": 140, "lot_number": "TOO-MANY",
                "expiry_date": timezone.localdate() + timedelta(days=540),
            }],
        )
    gloves.refresh_from_db()
    assert gloves.quantity_received == 0
    assert StockMovement.objects.count() == 0


@pytest.mark.django_db
def test_the_database_refuses_an_over_received_line(
    purchase_request, supplier, purchase_approver
):
    order = _order(purchase_request, supplier, purchase_approver)
    gloves = order.lines.get(item__code="GLV-M")
    with pytest.raises(IntegrityError):
        order.lines.filter(pk=gloves.pk).update(quantity_received=101)


@pytest.mark.django_db
def test_receiving_expired_goods_is_refused_and_nothing_is_shelved(
    purchase_request, supplier, purchase_approver, purchase_buyer
):
    """AC-148 reaching back into procurement.

    Expired stock is not received into a store; it is refused at the door. The
    order line stays open, which is right — the hospital has not had what it
    ordered.
    """
    order = _order(purchase_request, supplier, purchase_approver)
    gloves = order.lines.get(item__code="GLV-M")
    with pytest.raises(ValidationError, match="expired on"):
        receive_goods(
            order=order, actor=purchase_buyer,
            deliveries=[{
                "order_line": gloves, "quantity": 10, "lot_number": "DEAD",
                "expiry_date": timezone.localdate() - timedelta(days=1),
            }],
        )
    gloves.refresh_from_db()
    assert gloves.quantity_received == 0
    assert StockMovement.objects.count() == 0


@pytest.mark.django_db
def test_an_order_with_goods_on_the_shelf_cannot_be_cancelled(
    purchase_request, supplier, purchase_approver, purchase_buyer
):
    """The stock is real and the hospital owes for it."""
    order = _order(purchase_request, supplier, purchase_approver)
    gloves = order.lines.get(item__code="GLV-M")
    receive_goods(
        order=order, actor=purchase_buyer,
        deliveries=[{
            "order_line": gloves, "quantity": 10, "lot_number": "ARRIVED",
            "expiry_date": timezone.localdate() + timedelta(days=540),
        }],
    )
    with pytest.raises(ValidationError, match="close the order short"):
        cancel_order(order, actor=purchase_buyer, reason="Changed our minds.")
    order.refresh_from_db()
    assert order.status == PurchaseOrder.PARTIALLY_RECEIVED


@pytest.mark.django_db
def test_an_untouched_order_can_be_cancelled_with_a_reason(
    purchase_request, supplier, purchase_approver, purchase_buyer
):
    order = _order(purchase_request, supplier, purchase_approver)
    with pytest.raises(ValidationError, match="Say why"):
        cancel_order(order, actor=purchase_buyer, reason="  ")

    cancel_order(order, actor=purchase_buyer, reason="Supplier out of stock.")
    order.refresh_from_db()
    assert order.status == PurchaseOrder.CANCELLED
    assert order.cancellation_reason == "Supplier out of stock."


# --- AC-157: matching the invoice ---------------------------------------

def _invoice(order, actor, amount):
    return SupplierInvoice.objects.create(
        order=order, supplier_reference="LMS-INV-9001",
        invoice_date=timezone.localdate(), amount=Decimal(amount),
        recorded_by=actor,
    )


@pytest.mark.django_db
def test_an_invoice_matching_what_arrived_is_matched(
    purchase_request, supplier, purchase_approver, purchase_buyer
):
    """AC-157."""
    order = _order(purchase_request, supplier, purchase_approver)
    for line in order.lines.all():
        receive_goods(
            order=order, actor=purchase_buyer,
            deliveries=[{
                "order_line": line, "quantity": line.quantity_ordered,
                "lot_number": f"FULL-{line.item.code}",
                "expiry_date": timezone.localdate() + timedelta(days=540),
            }],
        )
    order.refresh_from_db()
    assert order.status == PurchaseOrder.RECEIVED

    invoice = _invoice(order, purchase_buyer, order.total_ordered())
    run_match(invoice, actor=purchase_buyer)
    assert invoice.status == SupplierInvoice.MATCHED
    assert invoice.discrepancies == []
    assert invoice.matched_value == order.total_ordered()


@pytest.mark.django_db
def test_an_invoice_for_goods_that_never_came_is_queried_not_paid(
    purchase_request, supplier, purchase_approver, purchase_buyer
):
    """AC-157 — the criterion's whole point.

    Three-way matching is the only thing between a hospital and paying for a
    delivery that never arrived.
    """
    order = _order(purchase_request, supplier, purchase_approver)
    gloves = order.lines.get(item__code="GLV-M")
    receive_goods(
        order=order, actor=purchase_buyer,
        deliveries=[{
            "order_line": gloves, "quantity": 60, "lot_number": "SHORT",
            "expiry_date": timezone.localdate() + timedelta(days=540),
        }],
    )

    invoice = _invoice(order, purchase_buyer, order.total_ordered())
    run_match(invoice, actor=purchase_buyer)

    assert invoice.status == SupplierInvoice.QUERIED
    problems = " | ".join(invoice.discrepancies)
    assert "100 ordered, 60 received" in problems
    assert "Methylated spirit 500 mL: 40 ordered, 0 received" in problems
    assert "more than" in problems
    # 60 × 1,500 = 90,000 actually arrived.
    assert invoice.matched_value == Decimal("90000.00")


@pytest.mark.django_db
def test_an_unmatched_invoice_cannot_be_approved(
    purchase_request, supplier, purchase_approver, purchase_buyer
):
    """AC-157 (negative). A mismatch must not reach payment unseen."""
    order = _order(purchase_request, supplier, purchase_approver)
    invoice = _invoice(order, purchase_buyer, "1000.00")
    with pytest.raises(ValidationError, match="Match the invoice"):
        approve_invoice(invoice, actor=purchase_approver)
    assert invoice.status == SupplierInvoice.RECEIVED


@pytest.mark.django_db
def test_a_queried_invoice_needs_a_stated_reason_to_be_approved(
    purchase_request, supplier, purchase_approver, purchase_buyer
):
    order = _order(purchase_request, supplier, purchase_approver)
    gloves = order.lines.get(item__code="GLV-M")
    receive_goods(
        order=order, actor=purchase_buyer,
        deliveries=[{
            "order_line": gloves, "quantity": 60, "lot_number": "SHORT",
            "expiry_date": timezone.localdate() + timedelta(days=540),
        }],
    )
    invoice = _invoice(order, purchase_buyer, "90000.00")
    run_match(invoice, actor=purchase_buyer)
    assert invoice.status == SupplierInvoice.QUERIED

    with pytest.raises(ValidationError, match="Say why it is being approved"):
        approve_invoice(invoice, actor=purchase_approver)

    approve_invoice(
        invoice, actor=purchase_approver,
        note="Short delivery agreed with the supplier; billed correctly for 60.",
    )
    invoice.refresh_from_db()
    assert invoice.status == SupplierInvoice.APPROVED
    assert invoice.approved_by == purchase_approver
    # The discrepancies stay on the record.
    assert invoice.discrepancies != []


@pytest.mark.django_db
def test_the_person_who_entered_an_invoice_cannot_approve_it(
    purchase_request, supplier, purchase_approver, purchase_buyer
):
    order = _order(purchase_request, supplier, purchase_approver)
    for line in order.lines.all():
        receive_goods(
            order=order, actor=purchase_buyer,
            deliveries=[{
                "order_line": line, "quantity": line.quantity_ordered,
                "lot_number": f"F-{line.item.code}",
                "expiry_date": timezone.localdate() + timedelta(days=540),
            }],
        )
    invoice = _invoice(order, purchase_buyer, order.total_ordered())
    run_match(invoice, actor=purchase_buyer)
    with pytest.raises(ValidationError, match="who entered it"):
        approve_invoice(invoice, actor=purchase_buyer)


@pytest.mark.django_db
def test_the_database_refuses_an_approved_invoice_with_nobody_named(
    purchase_request, supplier, purchase_approver, purchase_buyer
):
    order = _order(purchase_request, supplier, purchase_approver)
    invoice = _invoice(order, purchase_buyer, "1000.00")
    with pytest.raises(IntegrityError):
        SupplierInvoice.objects.filter(pk=invoice.pk).update(
            status=SupplierInvoice.APPROVED
        )


@pytest.mark.django_db
def test_the_matched_figures_are_frozen_at_the_time_of_matching(
    purchase_request, supplier, purchase_approver, purchase_buyer
):
    """The order carries on changing; what was queried stays what was queried."""
    order = _order(purchase_request, supplier, purchase_approver)
    gloves = order.lines.get(item__code="GLV-M")
    receive_goods(
        order=order, actor=purchase_buyer,
        deliveries=[{
            "order_line": gloves, "quantity": 60, "lot_number": "SHORT",
            "expiry_date": timezone.localdate() + timedelta(days=540),
        }],
    )
    invoice = _invoice(order, purchase_buyer, order.total_ordered())
    run_match(invoice, actor=purchase_buyer)
    frozen_value = invoice.matched_value
    frozen_problems = list(invoice.discrepancies)

    # The rest of the gloves turn up afterwards.
    receive_goods(
        order=order, actor=purchase_buyer,
        deliveries=[{
            "order_line": gloves, "quantity": 40, "lot_number": "LATER",
            "expiry_date": timezone.localdate() + timedelta(days=560),
        }],
    )

    invoice.refresh_from_db()
    assert invoice.matched_value == frozen_value
    assert invoice.discrepancies == frozen_problems
    # A fresh match sees the new position — which is why it is a separate act.
    _, problems_now = match_invoice(invoice)
    assert "100 ordered, 60 received" not in " | ".join(problems_now)


@pytest.mark.django_db
def test_one_supplier_reference_cannot_be_billed_twice_against_one_order(
    purchase_request, supplier, purchase_approver, purchase_buyer
):
    """A duplicated invoice is the commonest way a hospital pays twice."""
    order = _order(purchase_request, supplier, purchase_approver)
    _invoice(order, purchase_buyer, "1000.00")
    with pytest.raises(IntegrityError):
        _invoice(order, purchase_buyer, "1000.00")
