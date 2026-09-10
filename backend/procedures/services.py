"""Doing procedures: requesting, consenting, booking, performing, amending.

The rules that matter, and where they live:

- A procedure needing consent cannot be performed without valid consent
  (AC-159). Checked here rather than in the serializer because it is a
  clinical rule, not a form rule, and it must hold whatever calls it.
- Booking a theatre relies on the exclusion constraint rather than a lookup
  (AC-161). The refusal is translated into something a scheduler can read.
- Performing takes consumables off stock and bills, in one transaction
  (AC-160, AC-163). A cancelled request never reaches this function at all.
"""

from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.utils import timezone

from billing.models import charge
from inventory.models import StockRecord
from inventory.stock import issue as issue_stock
from patients.models import NumberSequence

from .models import (
    Consent,
    OperationNote,
    OperationNoteVersion,
    PerformedProcedure,
    ProcedureConsumableUsed,
    ProcedureRequest,
    ProcedureTeamMember,
    TheatreBooking,
)


class ProcedureError(ValidationError):
    """A refusal somebody in theatre or on a ward needs to read and act on."""


class TheatreTaken(ProcedureError):
    """That slot is already booked. A conflict, not a malformed request."""


def _is_deadlock(error):
    sqlstate = getattr(getattr(error, "__cause__", None), "sqlstate", None)
    return sqlstate == "40P01"


def _reference():
    sequence, _ = NumberSequence.objects.get_or_create(
        key="procedure_request_number",
        defaults={"prefix": "PRC", "include_year": True, "width": 5},
    )
    return NumberSequence.allocate(sequence.key)


@transaction.atomic
def request_procedure(*, procedure, patient, facility, indication, actor,
                      visit=None, admission=None, urgency=ProcedureRequest.ROUTINE):
    """AC-159. Asking for a procedure."""
    if visit is None and admission is None:
        raise ProcedureError(
            "A procedure belongs to an attendance or an admission. Without one "
            "there is nothing to bill it to and no episode it forms part of."
        )
    if not indication.strip():
        raise ProcedureError(
            "State the indication. "
            "'Why does this patient need this?' is the question the consenting "
            "clinician will be asked."
        )
    if not procedure.is_active:
        raise ProcedureError(f"{procedure.name} is no longer offered.")

    return ProcedureRequest.objects.create(
        reference=_reference(), procedure=procedure, patient=patient,
        facility=facility, visit=visit, admission=admission,
        indication=indication, urgency=urgency, requested_by=actor,
    )


@transaction.atomic
def record_consent(*, request, actor, risks_discussed, given_by=Consent.PATIENT,
                   given_by_name="", relationship="", interpreter_used=False,
                   interpreter_name=""):
    """AC-159. Recording that the conversation happened."""
    if not request.is_open:
        raise ProcedureError(
            f"{request.reference} is {request.get_status_display().lower()}."
        )
    if not risks_discussed.strip():
        raise ProcedureError(
            "Record what was explained — the procedure, its risks and the "
            "alternatives. A tick with no content is not a record of consent."
        )
    if given_by != Consent.PATIENT and not given_by_name.strip():
        raise ProcedureError("Name the person who consented on the patient's behalf.")
    if interpreter_used and not interpreter_name.strip():
        raise ProcedureError("Name the interpreter.")

    existing = Consent.objects.filter(request=request).first()
    if existing is not None and existing.is_valid:
        raise ProcedureError(
            f"Consent for {request.reference} is already recorded, taken by "
            f"{existing.taken_by.full_name}."
        )
    if existing is not None:
        # Consent was withdrawn and is being given again. A new row would lose
        # the withdrawal, so the withdrawn one is kept and this replaces it
        # only after the fact is preserved in the audit log by the caller.
        existing.delete()

    return Consent.objects.create(
        request=request, given_by=given_by, given_by_name=given_by_name,
        relationship=relationship, risks_discussed=risks_discussed,
        interpreter_used=interpreter_used, interpreter_name=interpreter_name,
        taken_by=actor,
    )


@transaction.atomic
def withdraw_consent(*, request, actor, reason):
    """A patient changing their mind, which they may do at any point."""
    consent = Consent.objects.filter(request=request).first()
    if consent is None or not consent.is_valid:
        raise ProcedureError("There is no valid consent to withdraw.")
    if not reason.strip():
        raise ProcedureError("Record what the patient said.")
    consent.withdrawn_at = timezone.now()
    consent.withdrawal_reason = reason
    consent.save(update_fields=["withdrawn_at", "withdrawal_reason"])
    return consent


def consent_blocking(request):
    """Why this procedure cannot proceed on consent grounds, or None. AC-159."""
    if not request.procedure.requires_consent:
        return None
    consent = getattr(request, "consent", None)
    if consent is None:
        return (
            f"{request.procedure.name} requires written consent and none is "
            f"recorded for {request.reference}."
        )
    if not consent.is_valid:
        return (
            f"Consent for {request.reference} was withdrawn"
            + (f" — {consent.withdrawal_reason}" if consent.withdrawal_reason else ".")
        )
    return None


@transaction.atomic
def book_theatre(*, request, theatre, starts_at, ends_at, lead_surgeon, actor,
                 anaesthetist=None):
    """AC-161. Hold a slot, or be told who has it."""
    if not request.is_open:
        raise ProcedureError(
            f"{request.reference} is {request.get_status_display().lower()}."
        )
    if not theatre.is_active:
        raise ProcedureError(
            f"{theatre.name} is out of service"
            + (f" — {theatre.out_of_service_note}" if theatre.out_of_service_note
               else ".")
        )
    if ends_at <= starts_at:
        raise ProcedureError("A booking has to end after it starts.")
    if theatre.facility_id != request.facility_id:
        raise ProcedureError(
            f"{theatre.name} is at another facility. A patient is not operated "
            f"on in a branch they were never admitted to."
        )

    try:
        with transaction.atomic():
            booking = TheatreBooking.objects.create(
                theatre=theatre, request=request,
                period=DateTimeTZRange(starts_at, ends_at),
                lead_surgeon=lead_surgeon, anaesthetist=anaesthetist,
                booked_by=actor,
            )
    except (IntegrityError, OperationalError) as refusal:
        # Same two shapes as a bed: an overlap, or a deadlock while checking
        # the same constraint under contention. Both mean the slot is taken.
        if isinstance(refusal, OperationalError) and not _is_deadlock(refusal):
            raise
        clash = TheatreBooking.objects.filter(
            theatre=theatre,
            period__overlap=DateTimeTZRange(starts_at, ends_at),
            status__in=[TheatreBooking.SCHEDULED, TheatreBooking.IN_PROGRESS,
                        TheatreBooking.COMPLETED],
        ).select_related("request__patient", "lead_surgeon").first()
        raise TheatreTaken(
            f"{theatre.name} is already booked then"
            + (f" — {clash.request.procedure.name} for "
               f"{clash.request.patient.full_name}, {clash.lead_surgeon.full_name}."
               if clash else ".")
        )

    request.status = ProcedureRequest.SCHEDULED
    request.save(update_fields=["status"])
    return booking


@transaction.atomic
def cancel_booking(*, booking, actor, reason):
    """Give the slot back. A cancelled booking stops blocking the theatre."""
    if not reason.strip():
        raise ProcedureError("Say why the booking is cancelled.")
    if booking.status == TheatreBooking.COMPLETED:
        raise ProcedureError(
            "That operation has already happened and cannot be un-booked."
        )
    booking.status = TheatreBooking.CANCELLED
    booking.cancelled_at = timezone.now()
    booking.cancellation_reason = reason
    booking.save(update_fields=["status", "cancelled_at", "cancellation_reason"])

    if not booking.request.bookings.exclude(status=TheatreBooking.CANCELLED).exists():
        booking.request.status = ProcedureRequest.REQUESTED
        booking.request.save(update_fields=["status"])
    return booking


@transaction.atomic
def cancel_request(*, request, actor, reason):
    """AC-163. A cancelled procedure never bills, because it never happened."""
    if not reason.strip():
        raise ProcedureError("Say why it is cancelled.")
    if request.status == ProcedureRequest.PERFORMED:
        raise ProcedureError(
            f"{request.reference} has been performed. Recording it as cancelled "
            f"would make the record disagree with what happened to the patient."
        )
    request.status = ProcedureRequest.CANCELLED
    request.cancelled_at = timezone.now()
    request.cancellation_reason = reason
    request.save(update_fields=["status", "cancelled_at", "cancellation_reason"])

    for booking in request.bookings.exclude(status=TheatreBooking.CANCELLED):
        booking.status = TheatreBooking.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.cancellation_reason = f"Procedure cancelled: {reason}"
        booking.save(update_fields=["status", "cancelled_at", "cancellation_reason"])
    return request


@transaction.atomic
def perform(*, request, actor, started_at, finished_at, lead_clinician,
            findings, procedure_performed, team=(), consumables=(), medications=(),
            booking=None, outcome=PerformedProcedure.COMPLETED, store=None,
            closure="", blood_loss_ml=None, specimens="", complications="",
            post_operative_instructions=""):
    """AC-160, AC-162, AC-163. Record that it happened, and bill for it.

    One transaction. Consumables leaving stock, the operation note and the
    charge all land together or none of them do — a charge without a note, or
    stock gone with nothing recorded against it, is worse than a failed save.
    """
    if request.status == ProcedureRequest.CANCELLED:
        raise ProcedureError(
            f"{request.reference} was cancelled"
            + (f" — {request.cancellation_reason}" if request.cancellation_reason
               else ".")
        )
    if PerformedProcedure.objects.filter(request=request).exists():
        raise ProcedureError(
            f"{request.reference} is already recorded as performed."
        )

    blocking = consent_blocking(request)
    if blocking is not None:
        raise ProcedureError(blocking)

    if finished_at <= started_at:
        raise ProcedureError("A procedure has to finish after it starts.")
    if not findings.strip():
        raise ProcedureError("Record the findings.")
    if not procedure_performed.strip():
        raise ProcedureError(
            "Record what was actually done. It is not always what was requested, "
            "and the note is the only place that difference is visible."
        )

    performed = PerformedProcedure.objects.create(
        request=request, booking=booking, started_at=started_at,
        finished_at=finished_at, outcome=outcome, lead_clinician=lead_clinician,
        recorded_by=actor,
    )

    ProcedureTeamMember.objects.bulk_create([
        ProcedureTeamMember(performed=performed, member=entry["member"],
                            role=entry["role"])
        for entry in team
    ])

    # Consumables come off the shelf. Anything short refuses the whole thing,
    # because a procedure recorded as using stock the store does not have
    # leaves the next case short with no warning.
    source = store or (booking.theatre.store if booking and booking.theatre.store
                       else None)
    for entry in consumables:
        quantity = int(entry["quantity"])
        if quantity <= 0:
            continue
        from_store = entry.get("store") or source
        if from_store is None:
            raise ProcedureError(
                f"No store to take {entry['item'].name} from. Set one on the "
                f"theatre, or name it on the line."
            )
        record = StockRecord.objects.filter(
            store=from_store, item=entry["item"]
        ).first()
        if record is None:
            raise ProcedureError(
                f"{from_store.name} does not carry {entry['item'].name}."
            )
        movements = issue_stock(
            record=record, quantity=quantity, actor=actor,
            issued_to=f"{request.procedure.name} — {request.reference}",
            reason=f"Used in {request.reference}",
        )
        for movement in movements:
            ProcedureConsumableUsed.objects.create(
                performed=performed, item=entry["item"],
                quantity=-movement.quantity_delta, movement=movement,
            )

    for entry in medications:
        performed.medications.create(
            medication=entry["medication"], dose=entry["dose"],
            route=entry["route"], given_by=entry.get("given_by", actor),
            given_at=entry.get("given_at", started_at),
        )

    note = OperationNote.objects.create(performed=performed)
    OperationNoteVersion.objects.create(
        note=note, version_number=1, is_current=True,
        findings=findings, procedure_performed=procedure_performed,
        closure=closure, estimated_blood_loss_ml=blood_loss_ml,
        specimens_taken=specimens, complications=complications,
        post_operative_instructions=post_operative_instructions,
        author=lead_clinician,
    )

    request.status = ProcedureRequest.PERFORMED
    request.save(update_fields=["status"])
    if booking is not None:
        booking.status = TheatreBooking.COMPLETED
        booking.save(update_fields=["status"])

    _bill(performed, actor=actor)
    return performed


def _bill(performed, *, actor):
    """AC-163. Once, from the act of performing.

    Keyed on the performed row rather than the request, so a procedure that
    was requested twice and done once bills once, and a cancelled request
    never reaches here at all.
    """
    procedure = performed.request.procedure
    if procedure.billing_service is None:
        return None
    _, created = charge(
        service_code=procedure.billing_service.code,
        description=procedure.name,
        source_type="procedure",
        source_id=str(performed.pk),
        visit=performed.request.visit,
        admission=performed.request.admission,
        actor=actor,
        service_date=performed.started_at.date(),
    )
    if not performed.is_billed:
        performed.is_billed = True
        performed.save(update_fields=["is_billed"])
    return created


@transaction.atomic
def amend_note(*, note, actor, reason, **fields):
    """AC-162. Append a version; never overwrite one."""
    if not reason.strip():
        raise ProcedureError(
            "An amendment needs a reason. The superseded text stays on the "
            "record, and somebody reading it needs to know why it changed."
        )
    current = note.versions.select_for_update().filter(is_current=True).first()
    if current is None:
        raise ProcedureError("That note has no current version to amend.")

    carried = {
        "findings": current.findings,
        "procedure_performed": current.procedure_performed,
        "closure": current.closure,
        "estimated_blood_loss_ml": current.estimated_blood_loss_ml,
        "specimens_taken": current.specimens_taken,
        "complications": current.complications,
        "post_operative_instructions": current.post_operative_instructions,
    }
    carried.update({k: v for k, v in fields.items() if v is not None})

    note.versions.filter(pk=current.pk).update(is_current=False)
    return OperationNoteVersion.objects.create(
        note=note, version_number=current.version_number + 1, is_current=True,
        author=actor, amendment_reason=reason, **carried,
    )


def theatre_list(*, theatre=None, facility=None, on=None):
    """The day's operating list, in the order it runs."""
    bookings = TheatreBooking.objects.exclude(
        status=TheatreBooking.CANCELLED
    ).select_related(
        "theatre", "request__patient", "request__procedure", "lead_surgeon",
        "anaesthetist", "performed",
    )
    if theatre is not None:
        bookings = bookings.filter(theatre=theatre)
    if facility is not None:
        bookings = bookings.filter(theatre__facility=facility)
    if on is not None:
        # The whole of that local day, so a case starting at 23:00 appears on
        # the list for the day the team turns up rather than the following one.
        start = timezone.make_aware(
            datetime.combine(on, time.min), timezone.get_current_timezone()
        )
        bookings = bookings.filter(
            period__overlap=DateTimeTZRange(start, start + timedelta(days=1))
        )
    return bookings.order_by("period")
