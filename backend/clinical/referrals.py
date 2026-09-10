"""Referring a patient, and the letter that goes with it.

The letter is assembled from the record on every read rather than stored as
text. That is what makes AC-166's "reprints identically" true rather than
merely intended: there is no second copy to drift from the first, and a
reprint of a referral written in March renders from the same fields it always
did.
"""

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from patients.models import NumberSequence

from .models import Referral, ReferralPrint


class ReferralError(ValidationError):
    """A refusal the referring clinician needs to read."""


def _reference():
    sequence, _ = NumberSequence.objects.get_or_create(
        key="referral_number",
        defaults={"prefix": "REF", "include_year": True, "width": 5},
    )
    return NumberSequence.allocate(sequence.key)


@transaction.atomic
def refer(*, patient, facility, kind, reason, clinical_question, actor,
          to_department=None, to_clinician=None, to_organisation="",
          to_external_clinician="", to_address="", what_was_sent="",
          urgency=Referral.ROUTINE, encounter=None, visit=None, admission=None):
    """AC-164, AC-165."""
    if not reason.strip():
        raise ReferralError("Say why the patient is being referred.")
    if not clinical_question.strip():
        raise ReferralError(
            "State the clinical question. A referral without one is a transfer "
            "of responsibility rather than a request for an opinion, and the "
            "person receiving it has no way to know what you want."
        )
    if kind == Referral.INTERNAL and to_department is None and to_clinician is None:
        raise ReferralError("Name the department or the clinician it is going to.")
    if kind == Referral.EXTERNAL and not to_organisation.strip():
        raise ReferralError("Name the organisation it is going to.")
    if kind == Referral.INTERNAL and to_department is not None:
        if to_department.facility_id != facility.pk:
            raise ReferralError(
                f"{to_department.name} is at another facility. Refer externally, "
                f"or to a department at this one."
            )

    return Referral.objects.create(
        reference=_reference(), kind=kind, patient=patient, facility=facility,
        encounter=encounter, visit=visit, admission=admission,
        to_department=to_department, to_clinician=to_clinician,
        to_organisation=to_organisation,
        to_external_clinician=to_external_clinician, to_address=to_address,
        reason=reason, clinical_question=clinical_question,
        what_was_sent=what_was_sent, urgency=urgency, referred_by=actor,
    )


@transaction.atomic
def send(referral, *, actor):
    """Move it from draft to sent, which is when it appears on the other list."""
    if referral.status != Referral.DRAFT:
        raise ReferralError(
            f"{referral.reference} is already "
            f"{referral.get_status_display().lower()}."
        )
    referral.status = Referral.SENT
    referral.sent_at = timezone.now()
    referral.save(update_fields=["status", "sent_at"])
    return referral


@transaction.atomic
def accept(referral, *, actor):
    """The receiving clinician taking it on. AC-164."""
    if referral.status != Referral.SENT:
        raise ReferralError(
            f"{referral.reference} is {referral.get_status_display().lower()} "
            f"and is not waiting to be accepted."
        )
    referral.status = Referral.ACCEPTED
    referral.save(update_fields=["status"])
    return referral


@transaction.atomic
def record_outcome(referral, *, actor, outcome, declined=False):
    """AC-165. What came back.

    A declined referral is an outcome too, and one the referrer needs to see:
    a patient sitting in a queue that never accepted them is the failure this
    records against.
    """
    if not outcome.strip():
        raise ReferralError(
            "Record what came back. A closed referral with no outcome tells the "
            "referring clinician nothing about their patient."
        )
    if referral.status in (Referral.SEEN, Referral.DECLINED):
        raise ReferralError(
            f"{referral.reference} is already closed as "
            f"{referral.get_status_display().lower()}."
        )
    if referral.status == Referral.DRAFT:
        raise ReferralError(f"{referral.reference} has not been sent yet.")

    referral.status = Referral.DECLINED if declined else Referral.SEEN
    referral.outcome = outcome
    referral.outcome_recorded_by = actor
    referral.outcome_recorded_at = timezone.now()
    referral.save(update_fields=["status", "outcome", "outcome_recorded_by",
                                 "outcome_recorded_at"])
    return referral


@transaction.atomic
def cancel(referral, *, actor, reason):
    if not reason.strip():
        raise ReferralError("Say why it is being cancelled.")
    if referral.status in (Referral.SEEN, Referral.DECLINED):
        raise ReferralError("That referral is already closed.")
    referral.status = Referral.CANCELLED
    referral.outcome = f"Cancelled: {reason}"
    referral.outcome_recorded_by = actor
    referral.outcome_recorded_at = timezone.now()
    referral.save(update_fields=["status", "outcome", "outcome_recorded_by",
                                 "outcome_recorded_at"])
    return referral


def letter(referral):
    """AC-166. The letter, assembled from the record.

    Returns structured content rather than formatted text, so the same
    referral renders identically on screen, in a PDF and in a printed page —
    and so a change to the layout cannot change what a past letter said.
    """
    patient = referral.patient
    return {
        "reference": referral.reference,
        "written_on": referral.referred_at,
        "sent_on": referral.sent_at,
        "urgency": referral.get_urgency_display(),
        "from": {
            "clinician": referral.referred_by.full_name,
            "facility": referral.facility.name,
            # From the attendance's clinic, which is where the referring
            # clinician was sitting. An encounter carries no clinic of its own.
            "department": (
                referral.visit.clinic.department.name
                if referral.visit_id and referral.visit.clinic_id
                and referral.visit.clinic.department_id else ""
            ),
        },
        "to": {
            "kind": referral.get_kind_display(),
            "name": referral.destination,
            "address": referral.to_address,
        },
        "patient": {
            "name": patient.full_name,
            "hospital_number": patient.hospital_number,
            "date_of_birth": patient.date_of_birth,
            "age_years": patient.age_years,
            "sex": patient.get_sex_display(),
            "phone": patient.phone_primary,
        },
        "reason": referral.reason,
        "clinical_question": referral.clinical_question,
        "what_was_sent": referral.what_was_sent,
        "outcome": referral.outcome,
    }


@transaction.atomic
def record_print(referral, *, actor):
    """AC-166. Every print, including the first, is logged."""
    is_reprint = referral.print_count > 0
    ReferralPrint.objects.create(
        referral=referral, printed_by=actor, is_reprint=is_reprint
    )
    Referral.objects.filter(pk=referral.pk).update(
        print_count=models.F("print_count") + 1
    )
    referral.refresh_from_db(fields=["print_count"])
    return is_reprint
