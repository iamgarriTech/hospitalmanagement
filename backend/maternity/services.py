"""Booking a pregnancy, seeing her through it, and delivering.

The rule that matters is AC-172: a baby gets a patient record at the moment
of birth, created in the same transaction as the delivery. Not "should be
registered afterwards" — a newborn who needs resuscitating needs a chart
before anybody has time to fill in a registration form.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from patients.models import Patient

from .models import AntenatalVisit, Baby, Delivery, Pregnancy


class MaternityError(ValidationError):
    """A refusal a midwife or obstetrician needs to read."""


def edd_from_lmp(last_menstrual_period):
    """Naegele's rule: 280 days from the first day of the last period.

    The convention every maternity service uses, and the reason `edd_basis`
    exists — a scan-dated pregnancy will disagree with this by up to a
    fortnight, and which one is in use changes what counts as premature.
    """
    return last_menstrual_period + timedelta(days=280)


@transaction.atomic
def book(*, patient, facility, actor, estimated_delivery_date=None,
         last_menstrual_period=None, edd_basis=Pregnancy.LMP, edd_basis_note="",
         gravida=1, parity=0, previous_losses=0, risk_factors=""):
    """AC-171."""
    if estimated_delivery_date is None:
        if last_menstrual_period is None:
            raise MaternityError(
                "Give an estimated delivery date, or the date of the last "
                "menstrual period to calculate one from."
            )
        estimated_delivery_date = edd_from_lmp(last_menstrual_period)

    if gravida < 1:
        raise MaternityError("This pregnancy counts, so gravida is at least 1.")
    if parity + previous_losses >= gravida:
        raise MaternityError(
            f"Gravida {gravida} cannot be fewer than {parity} births plus "
            f"{previous_losses} losses plus this pregnancy."
        )

    try:
        with transaction.atomic():
            return Pregnancy.objects.create(
                patient=patient, facility=facility,
                last_menstrual_period=last_menstrual_period,
                estimated_delivery_date=estimated_delivery_date,
                edd_basis=edd_basis, edd_basis_note=edd_basis_note,
                gravida=gravida, parity=parity, previous_losses=previous_losses,
                risk_factors=risk_factors, booked_by=actor,
            )
    except IntegrityError:
        open_one = Pregnancy.objects.filter(
            patient=patient, status=Pregnancy.ONGOING
        ).first()
        raise MaternityError(
            f"{patient.full_name} already has an ongoing pregnancy"
            + (f", booked {open_one.booked_at:%d %b %Y} with an EDD of "
               f"{open_one.estimated_delivery_date:%d %b %Y}."
               if open_one else ".")
        )


@transaction.atomic
def revise_edd(*, pregnancy, actor, estimated_delivery_date, basis, note):
    """Re-dating after a scan. The basis and the note say why."""
    if not pregnancy.is_open:
        raise MaternityError("That pregnancy is closed.")
    if not note.strip():
        raise MaternityError(
            "Say what the new date is based on — which scan, at what gestation. "
            "A re-dated pregnancy with no explanation cannot be judged later."
        )
    pregnancy.estimated_delivery_date = estimated_delivery_date
    pregnancy.edd_basis = basis
    pregnancy.edd_basis_note = note
    pregnancy.save(update_fields=["estimated_delivery_date", "edd_basis",
                                  "edd_basis_note"])
    return pregnancy


@transaction.atomic
def record_antenatal_visit(*, pregnancy, actor, seen_at=None, visit=None, **findings):
    """AC-171. One contact, in sequence."""
    if not pregnancy.is_open:
        raise MaternityError(
            f"That pregnancy is {pregnancy.get_status_display().lower()}."
        )
    last = pregnancy.antenatal_visits.order_by("-sequence").first()
    sequence = 1 if last is None else last.sequence + 1

    seen_at = seen_at or timezone.now()
    gestation = pregnancy.gestation_at(timezone.localtime(seen_at).date())
    findings.setdefault(
        "gestation_weeks", gestation["weeks"] if gestation else None
    )

    return AntenatalVisit.objects.create(
        pregnancy=pregnancy, visit=visit, sequence=sequence, seen_at=seen_at,
        seen_by=actor, **findings,
    )


@transaction.atomic
def deliver(*, pregnancy, actor, delivered_at, mode, delivered_by, babies,
            admission=None, procedure=None, **details):
    """AC-172. The delivery, and a patient record for every baby.

    `babies` is a list of dicts: family_name, given_name, sex, outcome,
    birth_weight_grams, apgar scores, and so on. Each one becomes a
    `patients.Patient` in this transaction — there is no path through this
    function that records a birth without one.
    """
    if not pregnancy.is_open:
        raise MaternityError(
            f"That pregnancy is already {pregnancy.get_status_display().lower()}."
        )
    if hasattr(pregnancy, "delivery"):
        raise MaternityError("That pregnancy already has a delivery recorded.")
    if not babies:
        raise MaternityError(
            "Record at least one baby, live or stillborn. A delivery with none "
            "is not a delivery."
        )

    delivery = Delivery.objects.create(
        pregnancy=pregnancy, admission=admission, procedure=procedure,
        delivered_at=delivered_at, mode=mode, delivered_by=delivered_by,
        recorded_by=actor, **details,
    )

    mother = pregnancy.patient
    born_on = timezone.localtime(delivered_at).date()
    for order, entry in enumerate(babies, start=1):
        # The baby's own record, created here rather than left to somebody to
        # do afterwards. A newborn who needs help needs a chart immediately,
        # and "register the baby later" is how that chart is missing exactly
        # when it matters.
        baby_patient = Patient.objects.create(
            facility=pregnancy.facility,
            family_name=entry.get("family_name") or mother.family_name,
            given_name=entry.get("given_name") or "Baby",
            other_names=entry.get("other_names", ""),
            sex=entry.get("sex", "unknown"),
            date_of_birth=born_on,
            date_of_birth_is_estimated=False,
            address_line=mother.address_line,
            city=mother.city,
            state=mother.state,
            country=mother.country,
            phone_primary=mother.phone_primary,
            registered_by=actor,
        )
        Baby.objects.create(
            delivery=delivery, patient=baby_patient,
            birth_order=entry.get("birth_order", order),
            outcome=entry.get("outcome", Baby.LIVE_BIRTH),
            birth_weight_grams=entry.get("birth_weight_grams"),
            apgar_one_minute=entry.get("apgar_one_minute"),
            apgar_five_minutes=entry.get("apgar_five_minutes"),
            resuscitation=entry.get("resuscitation", ""),
            congenital_abnormality=entry.get("congenital_abnormality", ""),
        )

    pregnancy.status = Pregnancy.DELIVERED
    pregnancy.ended_at = delivered_at
    pregnancy.save(update_fields=["status", "ended_at"])
    return delivery


@transaction.atomic
def end_pregnancy(*, pregnancy, actor, reason, status=Pregnancy.ENDED):
    """A pregnancy that ended without a delivery, or moved elsewhere."""
    if not pregnancy.is_open:
        raise MaternityError("That pregnancy is already closed.")
    if not reason.strip():
        raise MaternityError("Say why it is being closed.")
    pregnancy.status = status
    pregnancy.ended_at = timezone.now()
    pregnancy.ended_reason = reason
    pregnancy.save(update_fields=["status", "ended_at", "ended_reason"])
    return pregnancy


def due_soon(*, facility, within_days=28):
    """Who is due, so the ward can plan. AC-171."""
    horizon = timezone.localdate() + timedelta(days=within_days)
    return Pregnancy.objects.filter(
        facility=facility, status=Pregnancy.ONGOING,
        estimated_delivery_date__lte=horizon,
    ).select_related("patient").order_by("estimated_delivery_date")


def overdue(*, facility):
    """Past the estimated date and still ongoing."""
    return Pregnancy.objects.filter(
        facility=facility, status=Pregnancy.ONGOING,
        estimated_delivery_date__lt=timezone.localdate(),
    ).select_related("patient").order_by("estimated_delivery_date")
