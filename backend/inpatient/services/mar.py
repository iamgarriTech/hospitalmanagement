"""Building the drug chart, and recording what happened to each dose.

The rules that matter live here rather than in a view: when doses fall due, what
a nurse must say before a dose can be recorded as not given, and the fact that
the allergy check runs again at the bedside.
"""
from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.models import AuditEvent
from billing.models import charge
from pharmacy.models import PrescriptionItem, StockBatch, take_from_batch

from core.formatting import trim_decimal

from ..models import MedicationAdministration, ScheduledDose, times_for


@transaction.atomic
def schedule_doses(*, prescription_item, admission, actor=None, start=None):
    """Generate the due doses for an inpatient prescription line.

    Idempotent: the unique constraint on (item, due time) means running this
    twice — a retry, a re-save — cannot double the chart.
    """
    if prescription_item.status == PrescriptionItem.CANCELLED:
        raise ValidationError("That prescription line was cancelled.")

    begin = start or timezone.now()
    hours = times_for(prescription_item.frequency_per_day)
    created = []
    sequence = 1

    for day in range(prescription_item.duration_days):
        date = (begin + timedelta(days=day)).date()
        for hour in hours:
            due = timezone.make_aware(
                datetime.combine(date, time(hour=hour)),
                timezone.get_current_timezone(),
            )
            # Doses that would already have fallen due before the prescription
            # was written are not put on the chart — a nurse cannot give
            # yesterday's dose, and an unfillable row reads as a missed one.
            if due < begin:
                continue
            dose, made = ScheduledDose.objects.get_or_create(
                prescription_item=prescription_item,
                due_at=due,
                defaults={
                    "admission": admission,
                    "patient": admission.patient,
                    "sequence": sequence,
                    "dose": prescription_item.dose,
                    "dose_unit": prescription_item.dose_unit,
                    "route": prescription_item.route,
                },
            )
            if made:
                created.append(dose)
            sequence += 1

    if created and actor is not None:
        AuditEvent.record(
            action="mar.doses_scheduled",
            actor=actor,
            resource=admission,
            patient=admission.patient,
            facility=admission.facility,
            after={
                "medication": str(prescription_item.medication),
                "doses": len(created),
                "first_due": created[0].due_at.isoformat(),
                "last_due": created[-1].due_at.isoformat(),
            },
        )
    return created


@transaction.atomic
def discontinue(*, prescription_item, actor, reason, at=None):
    """Stop a course.

    Future doses are cancelled; doses already given stay exactly as they were.
    A discontinuation that erased the history would hide the fact that the drug
    was ever administered.
    """
    if not reason.strip():
        raise ValidationError("A reason is required to discontinue a medication.")

    moment = at or timezone.now()
    # Doses that already have an outcome are left alone. Marking a dose that was
    # given as "discontinued" would replace the fact that it reached the patient
    # with the fact that the course was later stopped — losing the more
    # important of the two.
    future = ScheduledDose.objects.filter(
        prescription_item=prescription_item, due_at__gte=moment, cancelled_at__isnull=True,
        administrations__isnull=True,
    )
    cancelled = future.update(cancelled_at=moment, cancelled_reason=reason.strip())

    prescription_item.status = PrescriptionItem.CANCELLED
    prescription_item.cancelled_reason = reason.strip()[:255]
    prescription_item.save(update_fields=["status", "cancelled_reason"])

    admission = prescription_item.prescription.admission
    AuditEvent.record(
        action="mar.medication_discontinued",
        actor=actor,
        resource=admission or prescription_item.prescription,
        patient=prescription_item.prescription.patient,
        facility=prescription_item.prescription.facility,
        after={
            "medication": str(prescription_item.medication),
            "future_doses_cancelled": cancelled,
            "doses_already_given": MedicationAdministration.objects.filter(
                scheduled_dose__prescription_item=prescription_item,
                state__in=list(MedicationAdministration.CONSUMES_STOCK),
            ).count(),
        },
        reason=reason.strip(),
    )
    return cancelled


def bedside_warnings(*, patient, medication):
    """The check that runs again at the bedside.

    A nurse is the last person between a prescription and a patient, so the
    allergy match runs at administration as well as at prescribing — the
    prescriber may have overridden it, the allergy may have been recorded since,
    or this may simply be the wrong patient's trolley.
    """
    from pharmacy.safety import _check_allergies

    return _check_allergies(patient, medication)


def record_administration(*, scheduled_dose, state, actor, administered_at=None,
                         dose_given=None, batch=None, reason="", note="",
                         override_reason="", request=None):
    """Record what happened to one due dose.

    Returns `(administration, created)`. A second attempt on the same dose
    returns the first outcome rather than creating another: the unique
    constraint makes a double-tap idempotent instead of a double dose.

    Validation runs *before* any transaction opens, deliberately. An earlier
    version refused an expired batch from inside `transaction.atomic`, which
    rolled the refusal's own audit row back along with the refusal — the near
    miss was refused correctly and then left no trace, which is the half of it
    that matters afterwards.
    """
    existing = MedicationAdministration.objects.filter(
        scheduled_dose=scheduled_dose
    ).first()
    if existing is not None:
        return existing, False

    if scheduled_dose.is_cancelled:
        raise ValidationError(
            f"That dose was discontinued — {scheduled_dose.cancelled_reason}"
        )
    if state not in dict(MedicationAdministration.STATE_CHOICES):
        raise ValidationError(f"{state!r} is not a recognised outcome.")
    if state in MedicationAdministration.REQUIRE_REASON and not reason.strip():
        raise ValidationError(
            {"reason": f"A reason is required when a dose is recorded as {state}."}
        )

    item = scheduled_dose.prescription_item
    medication = item.medication
    admission = scheduled_dose.admission
    consumes = state in MedicationAdministration.CONSUMES_STOCK

    if consumes:  # noqa: SIM102 — validated outside any transaction, see docstring
        if administered_at is None:
            administered_at = timezone.now()
        if batch is None:
            raise ValidationError({"batch": "Say which batch the dose came from."})
        batch = StockBatch.objects.select_related("medication").get(pk=batch.pk)
        if batch.medication_id != medication.pk:
            raise ValidationError(
                {"batch": f"That batch is {batch.medication.generic_name}, "
                          f"not {medication.generic_name}."}
            )
        if batch.is_expired:
            AuditEvent.record(
                action="mar.expired_batch_refused",
                actor=actor,
                outcome=AuditEvent.DENIED,
                patient=scheduled_dose.patient,
                facility=admission.facility,
                after={"batch": batch.batch_number, "expiry": str(batch.expiry_date)},
                request=request,
            )
            raise ValidationError(
                {"batch": f"Batch {batch.batch_number} expired on {batch.expiry_date}."}
            )

        warnings = bedside_warnings(patient=scheduled_dose.patient, medication=medication)
        if warnings and not override_reason.strip():
            raise ValidationError({
                "override_reason": [warning.detail for warning in warnings],
            })

    return _commit_administration(
        scheduled_dose=scheduled_dose, state=state, actor=actor,
        administered_at=administered_at, dose_given=dose_given, batch=batch,
        reason=reason, note=note, override_reason=override_reason, request=request,
        consumes=consumes, medication=medication, admission=admission,
    )


@transaction.atomic
def _commit_administration(*, scheduled_dose, state, actor, administered_at, dose_given,
                           batch, reason, note, override_reason, request, consumes,
                           medication, admission):
    """The write half, once everything has been checked."""
    administration = MedicationAdministration(
        scheduled_dose=scheduled_dose,
        admission=admission,
        patient=scheduled_dose.patient,
        state=state,
        administered_by=actor,
        administered_at=administered_at if consumes else None,
        dose_given=(dose_given if dose_given is not None else scheduled_dose.dose)
        if consumes else None,
        dose_unit=scheduled_dose.dose_unit if consumes else "",
        batch=batch if consumes else None,
        reason=reason.strip(),
        note=note,
        override_reason=override_reason.strip(),
    )
    administration.full_clean(exclude=["dose_unit"])
    try:
        administration.save()
    except IntegrityError:
        # Lost a race on the same dose; return the winner.
        return MedicationAdministration.objects.get(scheduled_dose=scheduled_dose), False

    if consumes:
        take_from_batch(
            batch=batch,
            quantity=1,
            actor=actor,
            reason=f"Administered on {admission.admission_number}",
        )
        # Ward medication bills to the admission, not to the outpatient visit
        # that may have closed weeks ago.
        if medication.selling_price:
            charge(
                admission=admission,
                service_code="",
                description=f"{medication} — dose given {administered_at:%d %b %H:%M}",
                source_type="inpatient.MedicationAdministration",
                source_id=administration.pk,
                quantity=1,
                unit_price=medication.selling_price,
                actor=actor,
            )

    AuditEvent.record(
        action=f"mar.{state}",
        actor=actor,
        resource=admission,
        patient=scheduled_dose.patient,
        facility=admission.facility,
        after={
            "medication": str(medication),
            "due_at": scheduled_dose.due_at.isoformat(),
            "state": state,
            "dose_given": str(administration.dose_given or ""),
            "batch": batch.batch_number if consumes and batch else None,
            "minutes_late": administration.minutes_late,
            "overridden": bool(override_reason.strip()),
        },
        reason=reason.strip() or override_reason.strip(),
        request=request,
    )
    return administration, True


def chart(*, admission, days=7, now=None, overdue_after_minutes=60):
    """The MAR as a chart: a row per medication, a column per due time.

    Built this way because that is how a drug chart is read — across a row to
    see whether a course is being given, and down a column to see what is due
    at this round.
    """
    moment = now or timezone.now()
    window_start = moment - timedelta(days=days)
    doses = (
        ScheduledDose.objects.filter(admission=admission, due_at__gte=window_start)
        .select_related("prescription_item__medication")
        .prefetch_related("administrations__administered_by")
        .order_by("due_at")
    )

    columns = sorted({dose.due_at for dose in doses})
    rows = {}
    for dose in doses:
        item = dose.prescription_item
        row = rows.setdefault(item.pk, {
            "item_id": item.pk,
            "medication": str(item.medication),
            "medication_id": item.medication_id,
            "directions": (
                f"{trim_decimal(item.dose)} {item.dose_unit} {item.route}, "
                f"{item.frequency_per_day} times a day"
            ),
            "status": item.status,
            "cells": {},
        })
        outcome = dose.outcome
        row["cells"][dose.due_at.isoformat()] = {
            "dose_id": dose.pk,
            "due_at": dose.due_at,
            "status": dose.status(overdue_after_minutes=overdue_after_minutes, now=moment),
            "state_label": (
                outcome.get_state_display() if outcome
                else dict(
                    scheduled="Not yet due", due="Due", overdue="Overdue"
                )[dose.status(overdue_after_minutes=overdue_after_minutes, now=moment)]
                if not dose.is_cancelled else "Discontinued"
            ),
            "by": outcome.administered_by.full_name if outcome else None,
            "at": outcome.administered_at if outcome else None,
            "minutes_late": outcome.minutes_late if outcome else None,
            "reason": outcome.reason if outcome else dose.cancelled_reason,
        }
    return {"columns": columns, "rows": list(rows.values())}


# How far back a ward list looks by default. A dose that fell due six days ago
# and was never recorded is a records problem for someone to reconcile, not a
# handover item — and putting a week of them on the board buried the ones from
# this shift under three hundred rows.
DEFAULT_OVERDUE_LOOKBACK_HOURS = 24


# A stay that has not been discharged. Named because three queries here filter
# on it and a fourth got it subtly wrong.
OPEN_ADMISSION_STATUSES = ["admitted", "discharge_planned"]


def current_admission_ids(ward):
    """The open admissions occupying a bed on this ward right now.

    The status filter belongs here, on forty rows, rather than on the dose
    query, where Postgres checked the admission's status once per dose — 4,032
    primary-key lookups and 8,064 buffer hits for one render of the board.
    """
    from ..models import BedOccupancy

    return BedOccupancy.objects.filter(
        bed__room__ward=ward,
        period__endswith__isnull=True,
        admission__status__in=OPEN_ADMISSION_STATUSES,
    ).values_list("admission_id", flat=True)


def overdue_doses(*, facility=None, ward=None, admission_ids=None,
                  overdue_after_minutes=60, now=None,
                  lookback_hours=DEFAULT_OVERDUE_LOOKBACK_HOURS):
    """Doses nobody has recorded, past their window.

    The list a ward has to be able to see: a dose with no outcome is
    indistinguishable from a dose nobody gave.

    `lookback_hours=None` returns the whole backlog, which is what the
    dedicated overdue endpoint offers and what a reconciliation report wants.
    """
    moment = now or timezone.now()
    cutoff = moment - timedelta(minutes=overdue_after_minutes)
    doses = ScheduledDose.objects.filter(
        due_at__lt=cutoff,
        cancelled_at__isnull=True,
        administrations__isnull=True,
    ).select_related(
        "prescription_item__medication", "patient", "admission"
    ).prefetch_related(
        # Every dose here has no outcome by construction — that is the filter
        # above. Prefetching anyway costs one query that returns nothing and
        # gives `outcome` a cache to find empty, instead of it asking per dose.
        "administrations"
    ).order_by("due_at")
    if lookback_hours is not None:
        doses = doses.filter(due_at__gte=moment - timedelta(hours=lookback_hours))
    if facility is not None:
        doses = doses.filter(admission__facility=facility)
    if admission_ids is not None:
        # The caller already knows who is on the ward — the board has the beds
        # in hand — so it passes the ids rather than making this re-derive them
        # through occupancies, rooms and beds.
        doses = doses.filter(admission_id__in=admission_ids)
    elif ward is not None:
        # Resolved to admission ids first. Filtering through
        # `admission__occupancies__…` twice makes Django join the occupancy
        # table twice for one condition, and the ward's current admissions are
        # forty rows — which also carries the open-status check.
        doses = doses.filter(admission_id__in=current_admission_ids(ward))
    else:
        doses = doses.filter(admission__status__in=OPEN_ADMISSION_STATUSES)
    return doses


def older_overdue_count(*, ward=None, admission_ids=None, now=None,
                        lookback_hours=DEFAULT_OVERDUE_LOOKBACK_HOURS):
    """How many overdue doses fall outside the list's window.

    Reported alongside the list rather than dropped. A dose that quietly stops
    being shown after a day is a dose nobody will ever account for.
    """
    moment = now or timezone.now()
    if admission_ids is None:
        admission_ids = current_admission_ids(ward)
    return ScheduledDose.objects.filter(
        due_at__lt=moment - timedelta(hours=lookback_hours),
        cancelled_at__isnull=True,
        administrations__isnull=True,
        admission_id__in=admission_ids,
    ).count()


def board_overdue(*, admission_ids, limit, overdue_after_minutes=60, now=None,
                  lookback_hours=DEFAULT_OVERDUE_LOOKBACK_HOURS):
    """The soonest-overdue doses per patient, plus the counts.

    Same shape and same reason as `board_escalations`: capped in SQL so the
    board builds what it shows.

    Returns `(shown_by_admission, count_by_admission)`.
    """
    from django.db.models import Count, F, Window
    from django.db.models.functions import RowNumber

    moment = now or timezone.now()
    outstanding = ScheduledDose.objects.filter(
        due_at__lt=moment - timedelta(minutes=overdue_after_minutes),
        due_at__gte=moment - timedelta(hours=lookback_hours),
        cancelled_at__isnull=True,
        administrations__isnull=True,
        admission_id__in=admission_ids,
    )
    counts = dict(
        outstanding.values_list("admission_id").annotate(total=Count("pk"))
    )

    ranked = outstanding.annotate(
        position=Window(
            expression=RowNumber(),
            partition_by=[F("admission_id")],
            order_by=F("due_at").asc(),
        )
    ).values("pk", "position")
    keep = [row["pk"] for row in ranked if row["position"] <= limit]

    shown = {}
    for dose in ScheduledDose.objects.filter(pk__in=keep).select_related(
        "prescription_item__medication"
    ).order_by("due_at"):
        shown.setdefault(dose.admission_id, []).append(dose)
    return shown, counts
