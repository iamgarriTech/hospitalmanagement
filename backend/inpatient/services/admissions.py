"""Admitting, discharging, and charging for the stay.

Kept out of the views because the rules are the substance: what carries forward
from an outpatient attendance, which nights count, and what must be settled
before a patient can be discharged.
"""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.models import AuditEvent
from billing.models import Invoice, charge, open_invoice_for
from core.formatting import trim_decimal

from ..models import Admission, AdmissionRequest, Bed, BedOccupancy, BedTransfer

# A night is charged where the patient occupied the bed across midnight. The
# admission night counts, the discharge day does not. Stated on every invoice
# line rather than left implicit, because "why am I being charged for four
# nights when I was here three days" is a conversation a cashier has to be able
# to win.
BED_NIGHT_RULE = "charged where the patient occupied the bed at midnight"


@transaction.atomic
def admit(*, request=None, patient=None, facility=None, bed, actor, reason="",
          diagnosis="", consultant=None, visit=None, at=None):
    """Admit a patient and put them in a bed.

    Where an admission request exists, the reason, diagnosis, consultant and
    originating visit come from it — a ward clerk should not be retyping what
    the referring clinician already wrote, and a retyped diagnosis is a
    different diagnosis.
    """
    if request is not None:
        if request.status != AdmissionRequest.PENDING:
            raise ValidationError(
                f"That request is already {request.get_status_display().lower()}."
            )
        patient = request.patient
        facility = request.facility
        reason = reason or request.reason
        diagnosis = diagnosis or request.working_diagnosis
        consultant = consultant or request.responsible_consultant
        visit = visit or request.visit

    if patient is None or facility is None:
        raise ValidationError("An admission needs a patient and a facility.")
    if consultant is None:
        raise ValidationError("An admission needs a responsible consultant.")
    if not diagnosis.strip():
        raise ValidationError("An admission diagnosis is required.")

    if bed.room.ward.facility_id != facility.pk:
        raise ValidationError(
            f"{bed} is at {bed.room.ward.facility.code}, not {facility.code}."
        )

    try:
        # A savepoint. Without it the constraint violation poisons the
        # transaction and the handler below cannot run its own query — the
        # refusal then arrives as a TransactionManagementError instead of the
        # sentence that names the admission the patient is already under.
        with transaction.atomic():
            admission = Admission.objects.create(
                request=request, patient=patient, visit=visit, facility=facility,
                admission_reason=reason, admission_diagnosis=diagnosis.strip(),
                responsible_consultant=consultant, admitted_by=actor,
                admitted_at=at or timezone.now(),
            )
    except IntegrityError:
        # The partial unique constraint on open admissions. A patient already an
        # inpatient must not get a second record — that is how a stay ends up
        # split with half the drug chart on each.
        open_admission = Admission.objects.filter(patient=patient).exclude(
            status=Admission.DISCHARGED
        ).first()
        raise ValidationError(
            f"{patient.full_name} is already an inpatient"
            + (f" under {open_admission.admission_number}." if open_admission else ".")
        )

    occupancy = BedOccupancy.allocate(
        bed=bed, admission=admission, actor=actor, at=admission.admitted_at
    )

    if request is not None:
        request.status = AdmissionRequest.ADMITTED
        request.decided_by = actor
        request.decided_at = timezone.now()
        request.save(update_fields=["status", "decided_by", "decided_at"])

    AuditEvent.record(
        action="admission.admitted",
        actor=actor,
        resource=admission,
        patient=patient,
        facility=facility,
        after={
            "admission_number": admission.admission_number,
            "ward": bed.room.ward.name,
            "bed": str(bed),
            "diagnosis": admission.admission_diagnosis,
            "consultant": consultant.email,
        },
    )
    return admission, occupancy


@transaction.atomic
def plan_discharge(*, admission, actor, expected_date=None, destination="", notes=""):
    """Record the intention to discharge, before the discharge itself.

    Separate from discharging because the plan is what the ward, pharmacy and
    cash desk work towards — a discharge nobody saw coming is a discharge with
    no medication ready and an unsettled bill.
    """
    if not admission.is_open:
        raise ValidationError("That admission has already been discharged.")
    before = {
        "expected_discharge_date": str(admission.expected_discharge_date or ""),
        "destination": admission.discharge_destination,
    }
    admission.expected_discharge_date = expected_date
    admission.discharge_destination = destination
    admission.discharge_plan_notes = notes
    admission.status = Admission.DISCHARGE_PLANNED
    admission.save(
        update_fields=["expected_discharge_date", "discharge_destination",
                       "discharge_plan_notes", "status"]
    )
    AuditEvent.record(
        action="admission.discharge_planned",
        actor=actor,
        resource=admission,
        patient=admission.patient,
        facility=admission.facility,
        before=before,
        after={"expected_discharge_date": str(expected_date or ""),
               "destination": destination},
        reason=notes,
    )
    return admission


@transaction.atomic
def charge_bed_nights(*, admission, actor=None, upto=None):
    """Charge every night slept that has not been charged yet.

    Keyed on the occupancy and the date, so running this nightly, again at
    discharge, and once more after a retry all produce the same charges. A bed
    night charged twice is the kind of error a patient notices and a hospital
    cannot explain.
    """
    ward_nights = []
    horizon = upto or timezone.now()
    for occupancy in admission.occupancies.select_related("bed__room__ward").all():
        ward = occupancy.bed.room.ward
        if ward.nightly_service_id is None:
            continue
        end = occupancy.period.upper or horizon
        night = occupancy.period.lower.date()
        while night < end.date():
            item, created = charge(
                admission=admission,
                service_code=ward.nightly_service.code,
                description=(
                    f"{ward.name} bed night, {night:%d %b %Y} "
                    f"({BED_NIGHT_RULE})"
                ),
                source_type="inpatient.BedNight",
                source_id=f"{occupancy.pk}:{night.isoformat()}",
                actor=actor,
            )
            if created:
                ward_nights.append((ward.name, night))
            night += timedelta(days=1)

    if ward_nights and actor is not None:
        AuditEvent.record(
            action="admission.bed_nights_charged",
            actor=actor,
            resource=admission,
            patient=admission.patient,
            facility=admission.facility,
            after={"nights": [f"{name} {night.isoformat()}" for name, night in ward_nights]},
        )
    return ward_nights


def outstanding_before_discharge(admission):
    """What still has to be settled. Empty means the patient can go."""
    problems = []
    invoice = Invoice.objects.filter(
        admission=admission, status=Invoice.DRAFT
    ).first()
    if invoice is not None and invoice.items.exists():
        problems.append(
            f"{invoice.invoice_number} is still a draft with "
            f"{invoice.items.count()} charge(s) — finalise it first."
        )
    for other in Invoice.objects.filter(admission=admission).exclude(
        status__in=[Invoice.VOID, Invoice.DRAFT]
    ):
        if other.balance > 0:
            problems.append(
                f"{other.invoice_number} has an outstanding balance of {other.balance}."
            )
    return problems


def discharge(*, admission, actor, diagnosis, destination, instructions="",
              override_reason="", at=None):
    """Complete a discharge.

    Refuses while the stay is unbilled or unpaid, unless someone holding the
    override permission says why. This is the third gate for the phase: a
    patient walking out with an unreconciled bill is money the hospital never
    sees and a record that cannot be closed.

    Nothing here runs inside a transaction until everything has been checked,
    and that is the point. An earlier version wrapped the whole function in
    `transaction.atomic`, so a refused discharge rolled back the bed nights it
    had just charged — the ward was told "settle the bill first" and the cashier
    was shown an invoice with nothing on it. The charging has to survive the
    refusal, because the refusal is what sends the patient to the cash desk.
    """
    if not admission.is_open:
        raise ValidationError("That admission has already been discharged.")
    if not diagnosis.strip():
        raise ValidationError("A discharge diagnosis is required.")
    if not destination:
        raise ValidationError("A discharge destination is required.")

    moment = at or timezone.now()
    # Charge the nights before checking the balance, or the check passes and the
    # stay bills after the patient has gone.
    charge_bed_nights(admission=admission, actor=actor, upto=moment)

    problems = outstanding_before_discharge(admission)
    if problems and not override_reason.strip():
        raise ValidationError(problems)

    return _complete_discharge(
        admission=admission, actor=actor, diagnosis=diagnosis,
        destination=destination, instructions=instructions,
        override_reason=override_reason, moment=moment, problems=problems,
    )


@transaction.atomic
def _complete_discharge(*, admission, actor, diagnosis, destination, instructions,
                        override_reason, moment, problems):
    """The write half: release the bed and close the stay, together."""
    occupancy = admission.current_occupancy
    if occupancy is not None:
        occupancy.close(actor=actor, at=moment, reason="discharged")

    admission.status = Admission.DISCHARGED
    admission.discharged_at = moment
    admission.discharged_by = actor
    admission.discharge_diagnosis = diagnosis.strip()
    admission.discharge_destination = destination
    admission.follow_up_instructions = instructions
    admission.billing_override_reason = override_reason.strip()
    admission.save(
        update_fields=["status", "discharged_at", "discharged_by", "discharge_diagnosis",
                       "discharge_destination", "follow_up_instructions",
                       "billing_override_reason"]
    )

    AuditEvent.record(
        action="admission.discharged",
        actor=actor,
        resource=admission,
        patient=admission.patient,
        facility=admission.facility,
        before={"admission_diagnosis": admission.admission_diagnosis},
        after={
            "discharge_diagnosis": admission.discharge_diagnosis,
            "destination": destination,
            "nights": admission.length_of_stay_nights,
            "bed_released": str(occupancy.bed) if occupancy else None,
            "billing_overridden": bool(override_reason.strip()),
        },
        reason=override_reason,
    )
    if override_reason.strip():
        AuditEvent.record(
            action="admission.discharged_with_balance",
            actor=actor,
            outcome=AuditEvent.DENIED,
            resource=admission,
            patient=admission.patient,
            facility=admission.facility,
            after={"outstanding": problems},
            reason=override_reason.strip(),
        )
    return admission


def discharge_summary(admission):
    """Assembled from the record, not retyped.

    A summary someone types from memory is a second, worse version of the notes
    — and the one the next clinician will read.
    """
    from clinical.models import Encounter
    from imaging.models import ImagingOrder
    from laboratory.models import LabOrder
    from pharmacy.models import Prescription

    encounters = Encounter.objects.filter(admission=admission)
    reviews = [
        {
            "date": encounter.started_at,
            "clinician": encounter.clinician.full_name,
            "notes": encounter.current_version.clinical_notes if encounter.current_version else "",
            "diagnoses": [
                diagnosis.description
                for diagnosis in (
                    encounter.current_version.diagnoses.all()
                    if encounter.current_version else []
                )
            ],
        }
        for encounter in encounters.select_related("clinician").order_by("started_at")
    ]

    investigations = []
    for order in LabOrder.objects.filter(admission=admission).prefetch_related(
        "items__test", "items__results__parameter"
    ):
        for item in order.items.all():
            if item.status != "verified":
                continue
            investigations.append({
                "test": item.test.name,
                "when": order.ordered_at,
                "results": [
                    {
                        "parameter": result.parameter.name,
                        "value": f"{result.display_value} {result.unit}".strip(),
                        "flag": result.flag_label,
                    }
                    for result in item.results.all() if result.is_current
                ],
            })

    # Only verified reports. An unreleased report has not been stood behind and
    # must not be quoted in a summary the next clinician will read as settled.
    imaging = []
    for order in ImagingOrder.objects.filter(admission=admission).prefetch_related(
        "items__procedure", "items__reports"
    ):
        for item in order.items.all():
            report = item.current_report
            if report is None or not report.is_verified:
                continue
            imaging.append({
                "procedure": item.procedure.name,
                "when": item.performed_at,
                "conclusion": report.conclusion,
                "amended": report.is_amended,
            })

    medication = []
    for prescription in Prescription.objects.filter(
        admission=admission, is_discharge_medication=True
    ).prefetch_related("items__medication"):
        for item in prescription.items.all():
            medication.append({
                "medication": str(item.medication),
                "directions": (
                    f"{trim_decimal(item.dose)} {item.dose_unit} {item.route}, "
                    f"{item.frequency_per_day} times a day for {item.duration_days} days"
                ),
                "instructions": item.instructions,
                "quantity": item.quantity_prescribed,
            })

    return {
        "admission_number": admission.admission_number,
        "patient_name": admission.patient.full_name,
        "hospital_number": admission.patient.hospital_number,
        "sex": admission.patient.sex,
        "age_years": admission.patient.age_years,
        "facility": admission.facility.name,
        "admitted_at": admission.admitted_at,
        "discharged_at": admission.discharged_at,
        "nights": admission.length_of_stay_nights,
        "admission_diagnosis": admission.admission_diagnosis,
        "discharge_diagnosis": admission.discharge_diagnosis,
        "destination": admission.get_discharge_destination_display()
        if admission.discharge_destination else "",
        "responsible_consultant": admission.responsible_consultant.full_name,
        "movement": admission.movement,
        "reviews": reviews,
        "investigations": investigations,
        "imaging": imaging,
        "discharge_medication": medication,
        "follow_up_instructions": admission.follow_up_instructions,
    }


@transaction.atomic
def transfer(*, admission, to_bed, reason, actor, at=None):
    """Move an inpatient to another bed.

    The old occupancy closes and the new one opens in one transaction, so the
    patient is never recorded in two beds and never in none. The exclusion
    constraint on the occupancy period is what makes that safe under concurrency
    rather than merely intended.
    """
    if not reason.strip():
        raise ValidationError("A reason is required to move a patient.")
    if not admission.is_open:
        raise ValidationError("That admission has been discharged.")

    current = admission.current_occupancy
    if current is None:
        raise ValidationError("This admission has no bed to move from.")
    if current.bed_id == to_bed.pk:
        raise ValidationError("The patient is already in that bed.")

    moment = at or timezone.now()
    current.close(actor=actor, at=moment, reason="transferred")
    replacement = BedOccupancy.allocate(
        bed=to_bed, admission=admission, actor=actor, at=moment
    )
    return BedTransfer.objects.create(
        admission=admission,
        from_occupancy=current,
        to_occupancy=replacement,
        reason=reason.strip(),
        authorised_by=actor,
        moved_at=moment,
    )
