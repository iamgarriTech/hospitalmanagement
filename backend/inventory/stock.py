"""Moving stock. Plain functions, because each one spans several rows.

The concurrency discipline is the same one the pharmacy uses on its batches: a
conditional UPDATE rather than read-then-write, with a CHECK constraint behind
it. Copied rather than shared — the two guard different tables and there is no
third caller — but deliberately identical, so somebody reading one recognises
the other.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from .models import (
    StockAdjustment,
    StockLot,
    StockMovement,
    StockRecord,
    StockTransfer,
)


class StockError(ValidationError):
    """A refusal a storekeeper needs to read and act on."""


@transaction.atomic
def receive(*, record, quantity, actor, lot_number="", expiry_date=None,
            unit_cost=Decimal("0.00"), reason=""):
    """Book a delivery into a store.

    A repeat delivery of the same lot number adds to the lot rather than
    creating a second one, because two rows for one physical lot means two
    expiry dates to keep in step.
    """
    if quantity <= 0:
        raise StockError("A receipt must be for a positive quantity.")
    if record.item.tracks_expiry and expiry_date is None:
        raise StockError(
            f"{record.item.name} is tracked by expiry date. Record the expiry on "
            f"the delivery."
        )
    if not record.item.tracks_expiry and expiry_date is not None:
        raise StockError(
            f"{record.item.name} is not tracked by expiry date."
        )
    if expiry_date is not None and expiry_date < timezone.localdate():
        raise StockError(
            f"That delivery expired on {expiry_date:%d %b %Y}. Expired stock is "
            f"not received into a store; it is returned or written off."
        )

    lot, created = StockLot.objects.select_for_update().get_or_create(
        record=record,
        lot_number=lot_number or _next_lot_number(record),
        defaults={"expiry_date": expiry_date, "unit_cost": unit_cost,
                  "quantity_on_hand": 0},
    )
    if not created and lot.expiry_date != expiry_date:
        raise StockError(
            f"Lot {lot.lot_number} is already recorded with expiry "
            f"{lot.expiry_date or 'none'}. Two expiry dates for one lot number "
            f"cannot both be right — use a different lot number."
        )

    StockLot.objects.filter(pk=lot.pk).update(
        quantity_on_hand=F("quantity_on_hand") + quantity
    )
    lot.refresh_from_db(fields=["quantity_on_hand"])
    return _record_movement(
        lot, StockMovement.RECEIPT, quantity, actor, reason=reason
    )


def _next_lot_number(record):
    """For an item with no supplier lot of its own — linen, bed pans."""
    taken = record.lots.count() + 1
    return f"{record.item.code}-{taken:04d}"


@transaction.atomic
def issue(*, record, quantity, actor, issued_to="", reason=""):
    """Issue stock out of a store, oldest expiry first.

    AC-146 and AC-148. Refuses rather than going negative, and refuses expired
    stock naming the date, because "issue failed" tells a storekeeper nothing
    they can act on.
    """
    if quantity <= 0:
        raise StockError("An issue must be for a positive quantity.")
    if record.item.is_controlled and not issued_to.strip():
        raise StockError(
            f"{record.item.name} is a controlled item. Record who it went to."
        )

    today = timezone.localdate()
    usable = list(
        record.lots.filter(quantity_on_hand__gt=0).filter(
            Q(expiry_date__isnull=True) | Q(expiry_date__gte=today)
        )
    )
    available = sum(lot.quantity_on_hand for lot in usable)
    if available < quantity:
        expired = record.lots.filter(
            quantity_on_hand__gt=0, expiry_date__lt=today
        ).order_by("expiry_date")
        if expired.exists() and available + sum(
            lot.quantity_on_hand for lot in expired
        ) >= quantity:
            first = expired.first()
            raise StockError(
                f"Only {available} of {record.item.name} is in date at "
                f"{record.store.name}. The rest expired on "
                f"{first.expiry_date:%d %b %Y} and cannot be issued."
            )
        raise StockError(
            f"Only {available} {record.item.unit_of_issue} of {record.item.name} "
            f"is available at {record.store.name}; {quantity} was requested."
        )

    movements = []
    outstanding = quantity
    for lot in usable:
        if outstanding == 0:
            break
        take = min(outstanding, lot.quantity_on_hand)
        # The gate. Conditional on the quantity still being there, so two
        # storekeepers issuing the last box cannot both succeed.
        updated = StockLot.objects.filter(
            pk=lot.pk, quantity_on_hand__gte=take
        ).update(quantity_on_hand=F("quantity_on_hand") - take)
        if not updated:
            # Somebody took it between the read and the write. Start again
            # rather than issuing a partial quantity nobody asked for.
            raise StockError(
                f"{record.item.name} at {record.store.name} was taken by somebody "
                f"else while this was being issued. Check the balance and try again."
            )
        lot.refresh_from_db(fields=["quantity_on_hand"])
        movements.append(
            _record_movement(
                lot, StockMovement.ISSUE, -take, actor,
                issued_to=issued_to, reason=reason,
            )
        )
        outstanding -= take
    return movements


@transaction.atomic
def transfer(*, item, from_store, to_store, quantity, actor, reason=""):
    """Move stock between two stores. AC-145.

    Out of one and into the other, as two movements under one transfer, so
    each store's ledger balances on its own.
    """
    if from_store.pk == to_store.pk:
        raise StockError("A transfer needs two different stores.")
    if from_store.facility_id != to_store.facility_id:
        # Stock crossing facilities is a sale or an inter-branch supply with its
        # own paperwork, not a store transfer. Refusing is honest; pretending
        # otherwise loses the audit trail at the facility boundary.
        raise StockError(
            "Those stores are at different facilities. Stock does not move "
            "between facilities as a store transfer."
        )

    source = StockRecord.objects.filter(store=from_store, item=item).first()
    if source is None:
        raise StockError(f"{from_store.name} does not carry {item.name}.")

    destination, _ = StockRecord.objects.get_or_create(
        store=to_store, item=item,
        defaults={"reorder_level": item.default_reorder_level},
    )

    movement = StockTransfer.objects.create(
        from_store=from_store, to_store=to_store, item=item, quantity=quantity,
        reason=reason, moved_by=actor,
    )

    out = issue(
        record=source, quantity=quantity, actor=actor,
        issued_to=f"{to_store.name} (transfer)", reason=reason,
    )
    for entry in out:
        entry.kind = StockMovement.TRANSFER_OUT
        entry.transfer = movement
        entry.save(update_fields=["kind", "transfer"])

    # Received as lots matching what left, so expiry travels with the stock.
    # A transfer that lands as fresh stock is how expired goods reach a ward.
    for entry in out:
        lot = entry.lot
        received = receive(
            record=destination, quantity=-entry.quantity_delta, actor=actor,
            lot_number=lot.lot_number, expiry_date=lot.expiry_date,
            unit_cost=lot.unit_cost, reason=reason,
        )
        received.kind = StockMovement.TRANSFER_IN
        received.transfer = movement
        received.save(update_fields=["kind", "transfer"])

    return movement


def authorisation_required(*, lot, quantity_delta):
    """Is a second signature needed for this adjustment? AC-147."""
    value = abs(Decimal(quantity_delta) * lot.unit_cost)
    return value > lot.record.store.adjustment_authorisation_limit, value


@transaction.atomic
def adjust(*, lot, quantity_delta, kind, reason, actor, authorised_by=None):
    """Correct what a store is recorded as holding. AC-147.

    Above the store's limit this refuses without a second person, and the
    second person cannot be the first — a signature somebody supplies for
    themselves is not a control.
    """
    if quantity_delta == 0:
        raise StockError("An adjustment of zero corrects nothing.")
    if not reason.strip():
        raise StockError("An adjustment needs a reason. State what was found.")

    needs_authorisation, value = authorisation_required(
        lot=lot, quantity_delta=quantity_delta
    )
    if needs_authorisation and authorised_by is None:
        limit = lot.record.store.adjustment_authorisation_limit
        raise StockError(
            f"That adjustment is worth {value} and {lot.record.store.name} requires "
            f"a second person's authorisation above {limit}."
        )
    if authorised_by is not None and authorised_by.pk == actor.pk:
        raise StockError(
            "An adjustment cannot be authorised by the person who raised it."
        )

    if quantity_delta < 0:
        updated = StockLot.objects.filter(
            pk=lot.pk, quantity_on_hand__gte=-quantity_delta
        ).update(quantity_on_hand=F("quantity_on_hand") + quantity_delta)
        if not updated:
            current = StockLot.objects.get(pk=lot.pk).quantity_on_hand
            raise StockError(
                f"Lot {lot.lot_number} holds {current}; {-quantity_delta} cannot be "
                f"written off it."
            )
    else:
        StockLot.objects.filter(pk=lot.pk).update(
            quantity_on_hand=F("quantity_on_hand") + quantity_delta
        )

    lot.refresh_from_db(fields=["quantity_on_hand"])
    record = StockAdjustment.objects.create(
        lot=lot, kind=kind, quantity_delta=quantity_delta, value=value,
        reason=reason, raised_by=actor, authorised_by=authorised_by,
    )
    _record_movement(
        lot, StockMovement.ADJUSTMENT, quantity_delta, actor,
        reason=reason, adjustment=record,
    )
    return record


def _record_movement(lot, kind, delta, actor, *, reason="", issued_to="",
                     adjustment=None):
    return StockMovement.objects.create(
        lot=lot,
        kind=kind,
        quantity_delta=delta,
        quantity_after=lot.quantity_on_hand,
        reason=reason,
        issued_to=issued_to,
        adjustment=adjustment,
        recorded_by=actor,
    )


# --- what a storekeeper needs to look at -----------------------------------

def low_stock(*, store=None, facility=None):
    """Records at or below their reorder level. AC-149.

    Expired stock does not count towards the level: a store holding forty
    expired boxes and none in date is out, and reporting it as full is how a
    ward discovers the problem at the bedside.
    """
    records = StockRecord.objects.filter(is_active=True, item__is_active=True)
    if store is not None:
        records = records.filter(store=store)
    if facility is not None:
        records = records.filter(store__facility=facility)
    records = records.select_related("item", "store", "store__facility")
    return [
        record for record in records
        if record.usable_on_hand() <= record.reorder_level
    ]


def expiring(*, store=None, facility=None, horizon_days=None):
    """Lots expiring inside the horizon, or already expired. AC-149.

    Each store sets its own horizon, so the default comes from the store rather
    than from one hospital-wide figure that suits nobody.
    """
    lots = StockLot.objects.filter(
        quantity_on_hand__gt=0, expiry_date__isnull=False
    ).select_related("record__item", "record__store")
    if store is not None:
        lots = lots.filter(record__store=store)
    if facility is not None:
        lots = lots.filter(record__store__facility=facility)

    today = timezone.localdate()
    matched = []
    for lot in lots:
        days = horizon_days
        if days is None:
            days = lot.record.store.expiry_horizon_days
        if lot.expiry_date <= today + timedelta(days=days):
            matched.append(lot)
    return sorted(matched, key=lambda lot: lot.expiry_date)


def reconstruct_balance(lot):
    """The running balance from the movements. AC-150.

    Returns the balance after each movement in order, so a test can assert the
    ledger and the recorded quantity agree at every point rather than only at
    the end. A ledger that only agrees at the end cannot say when it diverged.
    """
    running = 0
    trail = []
    for movement in lot.movements.order_by("recorded_at", "id"):
        running += movement.quantity_delta
        trail.append({
            "movement": movement.pk,
            "kind": movement.kind,
            "delta": movement.quantity_delta,
            "running": running,
            "recorded": movement.quantity_after,
        })
    return trail
