"""Buying things: request, approve, order, receive, match, pay.

The two rules worth stating up front, because they are what make the rest
worth having:

*Approving is a different act from asking.* A storekeeper knows the shelf is
empty; committing the hospital's money is somebody else's decision, and the
same person cannot be both — checked here and again in the database.

*Receiving goods and shelving them are one act.* `GoodsReceiptLine.movement` is
not nullable, so a receipt without a stock movement cannot exist. A delivery
recorded on paper but never put on the shelf is stock the hospital believes it
has and cannot find, and that is exactly the state AC-156 exists to make
impossible rather than merely unlikely.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from patients.models import NumberSequence

from .models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequest,
    PurchaseRequestLine,
    StockRecord,
    SupplierInvoice,
)
from .stock import receive as receive_stock


class ProcurementError(ValidationError):
    """A refusal somebody in the stores or accounts office needs to read."""


def _reference(key, fallback_prefix):
    """A configurable reference, falling back to a plain one.

    The sequence is created on first use rather than required by a migration,
    so a hospital that never buys anything is not forced to configure a format
    for purchase orders it will not raise.
    """
    sequence, _ = NumberSequence.objects.get_or_create(
        key=key,
        defaults={"prefix": fallback_prefix, "include_year": True, "width": 5},
    )
    return NumberSequence.allocate(sequence.key)


# --- AC-152, AC-153: asking, and approving ---------------------------------

@transaction.atomic
def submit_request(request, *, actor):
    """Send a request for a decision.

    A request with no lines is refused: "we need things" is not something an
    approver can approve, and an empty request approved for an unbounded amount
    is worse than no control at all.
    """
    if request.status != PurchaseRequest.DRAFT:
        raise ProcurementError(
            f"{request.reference} is already {request.get_status_display().lower()}."
        )
    if not request.lines.exists():
        raise ProcurementError("Add at least one item before submitting a request.")

    request.status = PurchaseRequest.SUBMITTED
    request.submitted_at = timezone.now()
    request.save(update_fields=["status", "submitted_at"])
    return request


@transaction.atomic
def decide_request(request, *, approve, actor, note=""):
    """Approve or reject. AC-152 and AC-153."""
    if request.status != PurchaseRequest.SUBMITTED:
        raise ProcurementError(
            f"{request.reference} is {request.get_status_display().lower()} and is "
            f"not awaiting a decision."
        )
    if actor.pk == request.requested_by_id:
        raise ProcurementError(
            "A request cannot be approved by the person who raised it. Ask "
            "somebody else with the approving permission."
        )
    if not approve and not note.strip():
        raise ProcurementError(
            "Say why it is rejected. A rejection with no reason leaves the "
            "requester with nothing to change."
        )

    request.status = (
        PurchaseRequest.APPROVED if approve else PurchaseRequest.REJECTED
    )
    request.decided_by = actor
    request.decided_at = timezone.now()
    request.decision_note = note
    request.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])
    return request


# --- AC-154: the order -----------------------------------------------------

@transaction.atomic
def raise_order(*, request, supplier, actor, prices, expected_date=None, note=""):
    """Raise an order from an approved request.

    `prices` maps item id to the agreed unit cost, because the estimate on the
    request is what the storekeeper guessed and the order carries what the
    supplier actually quoted. Conflating the two means the invoice match later
    compares an invoice against a guess.
    """
    if request.needs_approval() and request.status != PurchaseRequest.APPROVED:
        raise ProcurementError(
            f"{request.reference} is worth {request.estimated_value()} and needs "
            f"approval before an order can be raised against it."
        )
    if request.status in (PurchaseRequest.REJECTED, PurchaseRequest.DRAFT):
        raise ProcurementError(
            f"{request.reference} is {request.get_status_display().lower()}."
        )
    if not supplier.is_approved:
        raise ProcurementError(
            f"{supplier.name} is not currently approved to supply"
            + (f" — {supplier.approval_note}" if supplier.approval_note else ".")
        )

    lines = list(request.lines.select_related("item"))
    missing = [
        line.item.name for line in lines if line.item_id not in prices
    ]
    if missing:
        raise ProcurementError(
            "An agreed price is needed for every line: " + ", ".join(missing) + "."
        )

    order = PurchaseOrder.objects.create(
        reference=_reference("purchase_order_number", "PO"),
        request=request, supplier=supplier, store=request.store,
        expected_date=expected_date, raised_by=actor, note=note,
    )
    PurchaseOrderLine.objects.bulk_create([
        PurchaseOrderLine(
            order=order, item=line.item, quantity_ordered=line.quantity,
            unit_cost=Decimal(str(prices[line.item_id])),
        )
        for line in lines
    ])

    request.status = PurchaseRequest.ORDERED
    request.save(update_fields=["status"])
    return order


@transaction.atomic
def cancel_order(order, *, actor, reason):
    """Cancel what has not arrived.

    An order with goods already on the shelf cannot be cancelled: the stock is
    real and the hospital owes for it. Closing it short is the honest action,
    and it is a different one.
    """
    if not reason.strip():
        raise ProcurementError("Say why the order is cancelled.")
    if order.status == PurchaseOrder.CANCELLED:
        raise ProcurementError(f"{order.reference} is already cancelled.")
    if order.receipts.exists():
        raise ProcurementError(
            f"{order.reference} has goods received against it. Those are on the "
            f"shelf and owed for — close the order short instead of cancelling it."
        )
    order.status = PurchaseOrder.CANCELLED
    order.cancelled_at = timezone.now()
    order.cancellation_reason = reason
    order.save(update_fields=["status", "cancelled_at", "cancellation_reason"])
    return order


# --- AC-155, AC-156: goods arriving ---------------------------------------

@transaction.atomic
def receive_goods(*, order, deliveries, actor, delivery_note="", note=""):
    """Book a delivery in, line by line, and put it on the shelf.

    `deliveries` is a list of {order_line, quantity, lot_number, expiry_date}.

    Each one creates a stock movement, and the receipt line holds a
    non-nullable reference to it. AC-156 is therefore a property of the schema
    rather than of this function remembering: there is no way to write a
    receipt line whose goods never reached a shelf.

    A short delivery leaves the line open. AC-155 says so explicitly because
    the tempting implementation — mark the line received when a delivery
    arrives against it — turns every partial delivery into a silent write-off
    of the rest.
    """
    if order.status == PurchaseOrder.CANCELLED:
        raise ProcurementError(f"{order.reference} is cancelled.")
    if not deliveries:
        raise ProcurementError("Record at least one line as received.")

    receipt = GoodsReceipt.objects.create(
        reference=_reference("goods_receipt_number", "GRN"),
        order=order, delivery_note=delivery_note, received_by=actor, note=note,
    )

    for delivery in deliveries:
        line = delivery["order_line"]
        quantity = int(delivery["quantity"])
        if line.order_id != order.pk:
            raise ProcurementError(
                f"{line.item.name} is not on {order.reference}."
            )
        if quantity <= 0:
            raise ProcurementError(
                f"A delivery of {line.item.name} must be a positive quantity."
            )
        if quantity > line.outstanding:
            raise ProcurementError(
                f"{line.outstanding} of {line.item.name} is still outstanding on "
                f"{order.reference}; {quantity} was delivered. An over-delivery "
                f"changes what the hospital owes, so it needs a decision rather "
                f"than a quiet acceptance."
            )

        record, _ = StockRecord.objects.get_or_create(
            store=order.store, item=line.item,
            defaults={"reorder_level": line.item.default_reorder_level},
        )
        movement = receive_stock(
            record=record,
            quantity=quantity,
            actor=actor,
            lot_number=delivery.get("lot_number", ""),
            expiry_date=delivery.get("expiry_date"),
            unit_cost=line.unit_cost,
            reason=f"{receipt.reference} against {order.reference}",
        )
        GoodsReceiptLine.objects.create(
            receipt=receipt, order_line=line, quantity=quantity,
            lot_number=movement.lot.lot_number,
            expiry_date=movement.lot.expiry_date,
            movement=movement,
        )
        PurchaseOrderLine.objects.filter(pk=line.pk).update(
            quantity_received=F("quantity_received") + quantity
        )

    order.refresh_from_db()
    lines = list(order.lines.all())
    order.status = (
        PurchaseOrder.RECEIVED if all(line.is_complete for line in lines)
        else PurchaseOrder.PARTIALLY_RECEIVED
    )
    order.save(update_fields=["status"])
    return receipt


# --- AC-157: matching the invoice ----------------------------------------

def match_invoice(invoice):
    """Three-way match: what was ordered, what arrived, what is being billed.

    Returns the discrepancies in words. Nothing is decided here — the caller
    records the result and somebody reads it. A function that quietly accepted
    the invoice figure would remove the only thing standing between a hospital
    and paying for goods that never came.
    """
    order = invoice.order
    problems = []

    received_value = Decimal("0.00")
    for line in order.lines.select_related("item"):
        line_value = Decimal(line.quantity_received) * line.unit_cost
        received_value += line_value
        if line.quantity_received < line.quantity_ordered:
            problems.append(
                f"{line.item.name}: {line.quantity_ordered} ordered, "
                f"{line.quantity_received} received."
            )

    difference = invoice.amount - received_value
    if difference != 0:
        direction = "more than" if difference > 0 else "less than"
        problems.append(
            f"Invoiced {invoice.amount}, which is {abs(difference)} {direction} the "
            f"{received_value} of goods actually received at ordered prices."
        )

    if not order.receipts.exists():
        problems.append(
            f"Nothing has been received against {order.reference} at all."
        )

    return received_value, problems


@transaction.atomic
def run_match(invoice, *, actor):
    """Match, and record the outcome as at this moment.

    The figures are frozen on the invoice rather than recomputed on every view:
    the order and its receipts carry on changing, and what was queried has to
    stay what was queried.
    """
    if invoice.status in (SupplierInvoice.APPROVED, SupplierInvoice.PAID):
        raise ProcurementError(
            f"That invoice is already {invoice.get_status_display().lower()}."
        )

    received_value, problems = match_invoice(invoice)
    invoice.matched_at = timezone.now()
    invoice.matched_value = received_value
    invoice.discrepancies = problems
    invoice.status = (
        SupplierInvoice.QUERIED if problems else SupplierInvoice.MATCHED
    )
    invoice.save(update_fields=["matched_at", "matched_value", "discrepancies",
                                "status"])
    return invoice


@transaction.atomic
def approve_invoice(invoice, *, actor, note=""):
    """Release an invoice for payment. AC-157 (the negative).

    A queried invoice can still be approved — sometimes a short delivery is
    agreed and the supplier has billed correctly for what came — but only with
    a stated reason, and the discrepancies stay on the record. What must not
    happen is a mismatch reaching payment without anybody having seen it.
    """
    if invoice.status == SupplierInvoice.RECEIVED:
        raise ProcurementError(
            "Match the invoice against the order and the delivery before "
            "approving it."
        )
    if invoice.status in (SupplierInvoice.APPROVED, SupplierInvoice.PAID):
        raise ProcurementError(
            f"That invoice is already {invoice.get_status_display().lower()}."
        )
    if invoice.status == SupplierInvoice.QUERIED and not note.strip():
        raise ProcurementError(
            "This invoice does not match what arrived. Say why it is being "
            "approved anyway: " + "; ".join(invoice.discrepancies)
        )
    if actor.pk == invoice.recorded_by_id:
        raise ProcurementError(
            "An invoice cannot be approved by the person who entered it."
        )

    invoice.status = SupplierInvoice.APPROVED
    invoice.approved_by = actor
    invoice.approved_at = timezone.now()
    if note.strip():
        invoice.query_note = note
    invoice.save(update_fields=["status", "approved_by", "approved_at", "query_note"])
    return invoice


def outstanding_orders(*, facility=None, store=None):
    """Orders with something still to come. What a storekeeper chases."""
    orders = PurchaseOrder.objects.filter(
        status__in=[PurchaseOrder.OPEN, PurchaseOrder.PARTIALLY_RECEIVED]
    ).select_related("supplier", "store", "request")
    if facility is not None:
        orders = orders.filter(store__facility=facility)
    if store is not None:
        orders = orders.filter(store=store)
    return orders


def new_request(*, store, justification, actor, lines):
    """A draft request with its lines. `lines` is [{item, quantity, cost, note}]."""
    if not justification.strip():
        raise ProcurementError(
            "Say why this is needed. An approver cannot approve a blank."
        )
    with transaction.atomic():
        request = PurchaseRequest.objects.create(
            reference=_reference("purchase_request_number", "PR"),
            store=store, justification=justification, requested_by=actor,
        )
        PurchaseRequestLine.objects.bulk_create([
            PurchaseRequestLine(
                request=request, item=line["item"], quantity=line["quantity"],
                estimated_unit_cost=Decimal(str(line.get("cost", 0))),
                note=line.get("note", ""),
            )
            for line in lines
        ])
    return request
