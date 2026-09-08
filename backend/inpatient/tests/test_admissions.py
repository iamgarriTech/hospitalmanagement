"""AC-61 to AC-66, AC-74 to AC-77, AC-99 to AC-109 — the stay, end to end.

The gate in this file is AC-100: a discharge cannot complete while the stay is
unbilled or unpaid. A patient walking out with an unreconciled bill is money the
hospital never sees and a record that cannot be closed.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from billing.models import Invoice
from inpatient.models import Admission, AdmissionRequest, Bed, BedOccupancy
from inpatient.services import charge_bed_nights, discharge, transfer
from visits.models import Visit


# --- requesting a bed ---------------------------------------------------------

@pytest.mark.django_db
def test_a_request_records_who_asked_and_why_without_a_bed(
    as_ward_doctor, patient, facility_a, ward, ward_doctor
):
    """AC-61."""
    response = as_ward_doctor.post(
        reverse("admissionrequest-list"),
        {
            "patient": patient.pk,
            "facility": facility_a.pk,
            "ward": ward.pk,
            "reason": "Blood pressure 210/130, unresponsive to oral treatment",
            "working_diagnosis": "Hypertensive urgency",
            "responsible_consultant": ward_doctor.pk,
            "priority": "urgent",
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["status"] == "pending"
    assert response.data["requested_by"] == ward_doctor.pk
    assert response.data["consultant_name"] == "Kola Ward"
    assert response.data["admission"] is None

    # No bed has been touched: the whole ward is still free.
    assert ward.occupancy()["occupied"] == 0

    pending = as_ward_doctor.get(
        reverse("admissionrequest-pending"), {"ward": ward.pk}
    )
    assert [row["id"] for row in pending.data] == [response.data["id"]]
    assert pending.data[0]["waiting_minutes"] >= 0


@pytest.mark.django_db
def test_a_declined_request_has_to_say_why(as_ward_doctor, patient, facility_a, ward,
                                           ward_doctor):
    """AC-61. The check constraint requires the reason; the API refuses without."""
    created = as_ward_doctor.post(
        reverse("admissionrequest-list"),
        {"patient": patient.pk, "facility": facility_a.pk, "ward": ward.pk,
         "reason": "Needs observation", "working_diagnosis": "Chest pain",
         "responsible_consultant": ward_doctor.pk},
        format="json",
    )
    request_id = created.data["id"]

    blank = as_ward_doctor.post(
        reverse("admissionrequest-decline", args=[request_id]), {"reason": ""},
        format="json",
    )
    assert blank.status_code == 400

    declined = as_ward_doctor.post(
        reverse("admissionrequest-decline", args=[request_id]),
        {"reason": "No isolation bed available; referred to Ikeja"}, format="json",
    )
    assert declined.status_code == 200
    assert declined.data["status"] == "declined"
    assert "isolation" in declined.data["decline_reason"]


# --- admitting ----------------------------------------------------------------

@pytest.mark.django_db
def test_admitting_from_a_request_carries_the_clinical_detail_forward(
    as_ward_doctor, patient, facility_a, ward, beds, ward_doctor, open_visit,
    inpatient_numbers,
):
    """AC-62, AC-65, AC-66.

    The reason, diagnosis, consultant and visit come from the request. A ward
    clerk retyping a diagnosis produces a second, worse diagnosis.
    """
    created = as_ward_doctor.post(
        reverse("admissionrequest-list"),
        {"patient": patient.pk, "facility": facility_a.pk, "visit": open_visit.pk,
         "ward": ward.pk, "reason": "Uncontrolled hypertension",
         "working_diagnosis": "Hypertensive urgency",
         "responsible_consultant": ward_doctor.pk},
        format="json",
    )
    assert created.status_code == 201, created.data

    admitted = as_ward_doctor.post(
        reverse("admission-admit"),
        {"request": created.data["id"], "bed": beds[0].pk},
        format="json",
    )
    assert admitted.status_code == 201, admitted.data
    assert admitted.data["admission_number"].startswith("ADM")
    assert admitted.data["admission_diagnosis"] == "Hypertensive urgency"
    assert admitted.data["visit"] == open_visit.pk
    assert admitted.data["consultant_name"] == "Kola Ward"
    assert admitted.data["bed"]["label"] == str(beds[0])
    assert admitted.data["bed"]["ward_name"] == "Male Medical Ward"

    # The request is closed out rather than left pending forever.
    AdmissionRequest.objects.get(pk=created.data["id"]).status == AdmissionRequest.ADMITTED

    # AC-65: the queue reflects the admission rather than showing them twice.
    open_visit.refresh_from_db()
    assert open_visit.status == Visit.ADMITTED
    assert open_visit.closed_at is not None

    # AC-66: bed, ward, reason and consultant all audited.
    event = AuditEvent.objects.get(action="admission.admitted")
    after = event.changes["after"]
    assert after["bed"] == str(beds[0])
    assert after["ward"] == "Male Medical Ward"
    assert after["diagnosis"] == "Hypertensive urgency"
    assert after["consultant"] == "ward@example.test"
    assert event.patient_id == patient.pk


@pytest.mark.django_db
def test_a_direct_admission_needs_a_diagnosis_and_a_consultant(
    as_ward_doctor, patient, facility_a, beds, ward_doctor, inpatient_numbers
):
    """AC-62. A patient can arrive by ambulance with no outpatient visit, but
    not with no diagnosis and nobody responsible for them."""
    missing = as_ward_doctor.post(
        reverse("admission-admit"),
        {"patient": patient.pk, "facility": facility_a.pk, "bed": beds[0].pk,
         "reason": "Brought in collapsed"},
        format="json",
    )
    assert missing.status_code == 400
    assert "consultant" in str(missing.data).lower()

    admitted = as_ward_doctor.post(
        reverse("admission-admit"),
        {"patient": patient.pk, "facility": facility_a.pk, "bed": beds[0].pk,
         "reason": "Brought in collapsed", "diagnosis": "Diabetic ketoacidosis",
         "responsible_consultant": ward_doctor.pk},
        format="json",
    )
    assert admitted.status_code == 201, admitted.data
    assert admitted.data["visit"] is None


@pytest.mark.django_db
def test_a_patient_already_an_inpatient_cannot_be_admitted_again(
    as_ward_doctor, admission, beds, ward_doctor, facility_a
):
    """AC-63 (negative). The partial unique constraint is what refuses it, so a
    race cannot split one stay across two records with half the chart on each."""
    second = as_ward_doctor.post(
        reverse("admission-admit"),
        {"patient": admission.patient_id, "facility": facility_a.pk, "bed": beds[1].pk,
         "reason": "again", "diagnosis": "again",
         "responsible_consultant": ward_doctor.pk},
        format="json",
    )
    assert second.status_code == 400
    assert "already an inpatient" in str(second.data)
    assert admission.admission_number in str(second.data)
    assert Admission.objects.filter(patient=admission.patient).count() == 1
    assert AuditEvent.objects.filter(
        action="admission.refused", outcome=AuditEvent.DENIED
    ).exists()


@pytest.mark.django_db
def test_a_nurse_who_may_record_observations_cannot_admit(
    as_ward_nurse, patient, facility_a, beds, ward_doctor, inpatient_numbers
):
    """AC-64 (negative)."""
    response = as_ward_nurse.post(
        reverse("admission-admit"),
        {"patient": patient.pk, "facility": facility_a.pk, "bed": beds[0].pk,
         "reason": "x", "diagnosis": "x", "responsible_consultant": ward_doctor.pk},
        format="json",
    )
    assert response.status_code == 403
    assert not Admission.objects.exists()
    denial = AuditEvent.objects.filter(
        action="permission.denied", outcome=AuditEvent.DENIED
    ).first()
    assert denial is not None
    assert denial.changes["after"]["permission"] == "inpatient.admit_patient"


@pytest.mark.django_db
def test_admitting_to_a_bed_in_another_facility_is_refused(
    as_ward_doctor, patient, facility_a, facility_b, beds, ward_doctor, inpatient_numbers
):
    """A bed belongs to a ward, and a ward to a facility. Admitting across that
    line would put a patient in a bed the receiving hospital does not know about."""
    from inpatient.models import Room, Ward

    other_ward = Ward.objects.create(
        facility=facility_b, name="Ikeja Ward", code="IKW"
    )
    other_room = Room.objects.create(ward=other_ward, name="Room 1", code="R1")
    other_bed = Bed.objects.create(room=other_room, code="A")

    response = as_ward_doctor.post(
        reverse("admission-admit"),
        {"patient": patient.pk, "facility": facility_a.pk, "bed": other_bed.pk,
         "reason": "x", "diagnosis": "Sepsis",
         "responsible_consultant": ward_doctor.pk},
        format="json",
    )
    assert response.status_code == 400
    assert "IKJ" in str(response.data)
    assert not Admission.objects.exists()


@pytest.mark.django_db
def test_admitting_to_a_bed_being_cleaned_is_refused_by_name(
    as_ward_doctor, patient, facility_a, beds, ward_doctor, inpatient_numbers
):
    """AC-70 (negative). The refusal names the state so the ward knows what to
    do about it — "unavailable" alone tells a clerk nothing."""
    beds[0].set_service_state(Bed.CLEANING, note="terminal clean after C. difficile")

    response = as_ward_doctor.post(
        reverse("admission-admit"),
        {"patient": patient.pk, "facility": facility_a.pk, "bed": beds[0].pk,
         "reason": "x", "diagnosis": "Pneumonia",
         "responsible_consultant": ward_doctor.pk},
        format="json",
    )
    assert response.status_code == 400
    assert "being cleaned" in str(response.data)
    assert "C. difficile" in str(response.data)


# --- transfers ----------------------------------------------------------------

@pytest.mark.django_db
def test_a_transfer_closes_one_occupancy_and_opens_another(
    as_ward_doctor, admission, beds
):
    """AC-74, AC-75. Never in two beds, never in none."""
    response = as_ward_doctor.post(
        reverse("admission-transfer", args=[admission.pk]),
        {"to_bed": beds[2].pk, "reason": "Moved to the observation bay"},
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["from_bed"] == str(beds[0])
    assert response.data["to_bed"] == str(beds[2])
    assert response.data["authorised_by_name"] == "Kola Ward"
    assert response.data["reason"] == "Moved to the observation bay"

    occupancies = list(admission.occupancies.order_by("period"))
    assert len(occupancies) == 2
    assert occupancies[0].ended_at is not None
    assert occupancies[1].ended_at is None
    # No gap: the new occupancy starts exactly where the old one ended.
    assert occupancies[0].ended_at == occupancies[1].started_at
    # Exactly one open occupancy at any moment.
    assert admission.occupancies.filter(period__endswith__isnull=True).count() == 1

    event = AuditEvent.objects.get(action="admission.transferred")
    assert event.changes["before"]["bed"] == str(beds[0])
    assert event.changes["after"]["bed"] == str(beds[2])
    assert event.changes["after"]["changed_ward"] is False


@pytest.mark.django_db
def test_a_transfer_to_an_occupied_bed_is_refused(
    as_ward_doctor, admission, beds, facility_a, ward_doctor, hospital_numbers
):
    """AC-76 (negative). Refused by the exclusion constraint, not by a check."""
    from patients.models import Patient

    other = Patient.objects.create(
        given_name="Tunde", family_name="Okoro", sex="male", facility=facility_a
    )
    other_admission = Admission.objects.create(
        patient=other, facility=facility_a, admission_reason="x",
        admission_diagnosis="Malaria", responsible_consultant=ward_doctor,
        admitted_by=ward_doctor,
    )
    BedOccupancy.allocate(bed=beds[1], admission=other_admission, actor=ward_doctor)

    response = as_ward_doctor.post(
        reverse("admission-transfer", args=[admission.pk]),
        {"to_bed": beds[1].pk, "reason": "closer to the nurses' station"},
        format="json",
    )
    assert response.status_code == 409
    assert "occupied" in str(response.data)
    # Neither patient moved.
    admission.refresh_from_db()
    assert admission.current_bed == beds[0]
    assert other_admission.current_bed == beds[1]


@pytest.mark.django_db
def test_a_transfer_needs_a_reason(as_ward_doctor, admission, beds):
    """AC-75 (negative). A move with no reason cannot be reviewed later."""
    response = as_ward_doctor.post(
        reverse("admission-transfer", args=[admission.pk]),
        {"to_bed": beds[2].pk, "reason": "  "}, format="json",
    )
    assert response.status_code == 400
    assert admission.occupancies.count() == 1


@pytest.mark.django_db
def test_the_whole_movement_is_reconstructable_from_the_admission(
    as_ward_doctor, admission, beds, ward_doctor, facility_a
):
    """AC-77. Every bed, every ward, the time in each — from one record."""
    from inpatient.models import Room, Ward

    intensive = Ward.objects.create(
        facility=facility_a, name="Intensive Care", code="ICU", ward_type=Ward.INTENSIVE
    )
    icu_room = Room.objects.create(ward=intensive, name="Bay 1", code="B1")
    icu_bed = Bed.objects.create(room=icu_room, code="1")

    transfer(admission=admission, to_bed=icu_bed, reason="Deteriorating",
             actor=ward_doctor)
    transfer(admission=admission, to_bed=beds[2], reason="Stepped down",
             actor=ward_doctor)

    response = as_ward_doctor.get(reverse("admission-detail", args=[admission.pk]))
    assert response.status_code == 200
    movement = response.data["movement"]
    assert [entry["bed"] for entry in movement] == [
        str(beds[0]), str(icu_bed), str(beds[2])
    ]
    assert [entry["ward"] for entry in movement] == [
        "Male Medical Ward", "Intensive Care", "Male Medical Ward"
    ]
    # Only the last leg is still open.
    assert [entry["to"] is None for entry in movement] == [False, False, True]

    ward_change = [row for row in response.data["transfers"] if row["changed_ward"]]
    assert len(ward_change) == 2


# --- bed nights ---------------------------------------------------------------

@pytest.mark.django_db
def test_bed_nights_are_charged_from_the_occupancy_without_anyone_typing_them(
    admission, ward, tariff, ward_doctor
):
    """AC-106, AC-107. The rule is on the invoice line, not implicit."""
    ward.nightly_service = tariff["bed_night"]
    ward.save(update_fields=["nightly_service"])

    occupancy = admission.current_occupancy
    occupancy.period = type(occupancy.period)(
        timezone.now() - timedelta(days=3), None
    )
    occupancy.save(update_fields=["period"])

    charged = charge_bed_nights(admission=admission, actor=ward_doctor)
    assert len(charged) == 3

    invoice = Invoice.objects.get(admission=admission)
    lines = list(invoice.items.all())
    assert len(lines) == 3
    assert all(
        line.unit_price == tariff["bed_night"].price_at(admission.facility)
        for line in lines
    )
    # AC-107: the rule a cashier has to be able to explain, on the line itself.
    assert all(
        "charged where the patient occupied the bed at midnight" in line.description
        for line in lines
    )
    assert AuditEvent.objects.filter(action="admission.bed_nights_charged").exists()


@pytest.mark.django_db
def test_bed_nights_cannot_be_charged_twice(admission, ward, tariff, ward_doctor):
    """AC-106 (negative). A bed night charged twice is an error a patient
    notices and a hospital cannot explain."""
    ward.nightly_service = tariff["bed_night"]
    ward.save(update_fields=["nightly_service"])

    occupancy = admission.current_occupancy
    occupancy.period = type(occupancy.period)(
        timezone.now() - timedelta(days=2), None
    )
    occupancy.save(update_fields=["period"])

    first = charge_bed_nights(admission=admission, actor=ward_doctor)
    second = charge_bed_nights(admission=admission, actor=ward_doctor)
    third = charge_bed_nights(admission=admission, actor=ward_doctor)

    assert len(first) == 2
    assert second == [] and third == []
    assert Invoice.objects.get(admission=admission).items.count() == 2


@pytest.mark.django_db
def test_a_night_already_settled_is_not_charged_again_on_the_next_invoice(
    admission, ward, tariff, ward_doctor, finalise_invoice
):
    """AC-106 (negative), across invoices.

    A long stay is billed in stages. Once the first invoice is finalised the
    next charge opens a fresh draft, and idempotency keyed only on the invoice
    would put every already-settled night on it — the patient pays twice for the
    same night and nobody can tell which line is the duplicate. This is the case
    the single-invoice test above cannot see.
    """
    ward.nightly_service = tariff["bed_night"]
    ward.save(update_fields=["nightly_service"])

    occupancy = admission.current_occupancy
    start = timezone.now() - timedelta(days=2)
    occupancy.period = type(occupancy.period)(start, None)
    occupancy.save(update_fields=["period"])
    admission.admitted_at = start
    admission.save(update_fields=["admitted_at"])

    charge_bed_nights(admission=admission, actor=ward_doctor)
    interim = Invoice.objects.get(admission=admission)
    assert interim.items.count() == 2
    finalise_invoice(interim)

    # Another night passes and the stay is charged again.
    occupancy.period = type(occupancy.period)(
        timezone.now() - timedelta(days=3), None
    )
    occupancy.save(update_fields=["period"])
    charge_bed_nights(admission=admission, actor=ward_doctor)

    lines = [
        item
        for invoice in Invoice.objects.filter(admission=admission)
        for item in invoice.items.all()
    ]
    # Three nights slept, three lines in total across both invoices.
    assert len(lines) == 3
    assert len({item.source_id for item in lines}) == 3


@pytest.mark.django_db
@pytest.mark.parametrize("nights", [0, 1, 3, 9, 21])
def test_nights_charged_equals_nights_occupied(
    admission, ward, tariff, ward_doctor, nights
):
    """AC-109. A property over generated stays: the two figures reconcile."""
    ward.nightly_service = tariff["bed_night"]
    ward.save(update_fields=["nightly_service"])

    occupancy = admission.current_occupancy
    start = timezone.now() - timedelta(days=nights)
    occupancy.period = type(occupancy.period)(start, None)
    occupancy.save(update_fields=["period"])
    admission.admitted_at = start
    admission.save(update_fields=["admitted_at"])

    charge_bed_nights(admission=admission, actor=ward_doctor)

    invoice = Invoice.objects.filter(admission=admission).first()
    charged = invoice.items.count() if invoice else 0
    assert charged == nights == admission.length_of_stay_nights


# --- discharge ----------------------------------------------------------------

@pytest.mark.django_db
def test_discharge_planning_records_the_plan_and_appears_on_a_list(
    as_ward_doctor, admission
):
    """AC-99."""
    tomorrow = (timezone.now() + timedelta(days=1)).date()
    response = as_ward_doctor.post(
        reverse("admission-plan-discharge", args=[admission.pk]),
        {"expected_date": str(tomorrow), "destination": "home",
         "notes": "Needs the TTO dispensed and a district nurse referral"},
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["status"] == "discharge_planned"
    assert response.data["expected_discharge_date"] == str(tomorrow)
    assert response.data["destination_display"] == "Home"

    listed = as_ward_doctor.get(
        reverse("admission-list"), {"discharge_planned": "true"}
    )
    assert [row["id"] for row in listed.data["results"]] == [admission.pk]

    event = AuditEvent.objects.get(action="admission.discharge_planned")
    assert "district nurse" in event.reason


@pytest.mark.django_db
def test_a_discharge_is_refused_while_the_stay_is_unbilled(
    as_ward_doctor, admission, ward, tariff, ward_doctor
):
    """AC-100 — the gate (negative).

    The bed nights are charged as part of the check. A check that ran first and
    charged afterwards would pass, and then bill a patient already at home.
    """
    ward.nightly_service = tariff["bed_night"]
    ward.save(update_fields=["nightly_service"])
    occupancy = admission.current_occupancy
    occupancy.period = type(occupancy.period)(
        timezone.now() - timedelta(days=2), None
    )
    occupancy.save(update_fields=["period"])

    response = as_ward_doctor.post(
        reverse("admission-discharge", args=[admission.pk]),
        {"diagnosis": "Hypertension, controlled", "destination": "home"},
        format="json",
    )
    assert response.status_code == 409, response.data
    assert "draft" in str(response.data).lower()

    admission.refresh_from_db()
    assert admission.is_open
    assert admission.current_bed is not None
    # The nights were still charged: the check does the charging.
    assert Invoice.objects.get(admission=admission).items.count() == 2
    assert AuditEvent.objects.filter(
        action="admission.discharge_refused", outcome=AuditEvent.DENIED
    ).exists()


@pytest.mark.django_db
def test_a_discharge_is_refused_while_the_invoice_is_unpaid(
    as_ward_doctor, admission, ward, tariff, ward_doctor, finalise_invoice
):
    """AC-100 — the gate (negative), the other half: finalised but not paid."""
    ward.nightly_service = tariff["bed_night"]
    ward.save(update_fields=["nightly_service"])
    occupancy = admission.current_occupancy
    occupancy.period = type(occupancy.period)(
        timezone.now() - timedelta(days=1), None
    )
    occupancy.save(update_fields=["period"])

    charge_bed_nights(admission=admission, actor=ward_doctor)
    invoice = Invoice.objects.get(admission=admission)
    finalise_invoice(invoice)

    response = as_ward_doctor.post(
        reverse("admission-discharge", args=[admission.pk]),
        {"diagnosis": "Hypertension, controlled", "destination": "home"},
        format="json",
    )
    assert response.status_code == 409
    assert "outstanding balance" in str(response.data)
    admission.refresh_from_db()
    assert admission.is_open


@pytest.mark.django_db
def test_an_override_needs_the_permission_as_well_as_a_reason(
    as_ward_doctor, admission, ward, tariff, ward_doctor
):
    """AC-100 (negative).

    A required text box anyone can fill in is not a control. The ward doctor has
    every other admission permission and still cannot do this.
    """
    ward.nightly_service = tariff["bed_night"]
    ward.save(update_fields=["nightly_service"])
    occupancy = admission.current_occupancy
    occupancy.period = type(occupancy.period)(
        timezone.now() - timedelta(days=1), None
    )
    occupancy.save(update_fields=["period"])

    response = as_ward_doctor.post(
        reverse("admission-discharge", args=[admission.pk]),
        {"diagnosis": "Hypertension", "destination": "home",
         "override_reason": "Patient insisted on leaving"},
        format="json",
    )
    assert response.status_code == 403
    assert "override permission" in str(response.data)
    admission.refresh_from_db()
    assert admission.is_open
    assert AuditEvent.objects.filter(
        action="admission.discharge_override_denied", outcome=AuditEvent.DENIED
    ).exists()


@pytest.mark.django_db
def test_someone_holding_the_override_can_discharge_and_it_is_recorded_as_such(
    as_ward_manager, admission, ward, tariff, ward_doctor
):
    """AC-100. The escape hatch exists, and using it leaves a mark."""
    ward.nightly_service = tariff["bed_night"]
    ward.save(update_fields=["nightly_service"])
    occupancy = admission.current_occupancy
    occupancy.period = type(occupancy.period)(
        timezone.now() - timedelta(days=1), None
    )
    occupancy.save(update_fields=["period"])

    response = as_ward_manager.post(
        reverse("admission-discharge", args=[admission.pk]),
        {"diagnosis": "Hypertension, controlled", "destination": "home",
         "override_reason": "Absconded overnight; bill referred to accounts"},
        format="json",
    )
    assert response.status_code == 200, response.data
    admission.refresh_from_db()
    assert admission.status == Admission.DISCHARGED
    assert "Absconded" in admission.billing_override_reason

    flagged = AuditEvent.objects.get(action="admission.discharged_with_balance")
    assert flagged.outcome == AuditEvent.DENIED
    assert "Absconded" in flagged.reason


@pytest.mark.django_db
def test_a_clean_discharge_frees_the_bed_for_cleaning_and_closes_the_stay(
    as_ward_doctor, admission, ward, tariff, ward_doctor, as_cashier, cashier_session,
    finalise_invoice,
):
    """AC-101, AC-105. The bed goes for cleaning, never straight to available —
    a bed a patient has just left is not ready for the next one."""
    ward.nightly_service = tariff["bed_night"]
    ward.save(update_fields=["nightly_service"])
    occupancy = admission.current_occupancy
    bed = occupancy.bed
    occupancy.period = type(occupancy.period)(
        timezone.now() - timedelta(days=2), None
    )
    occupancy.save(update_fields=["period"])
    admission.admitted_at = occupancy.period.lower
    admission.save(update_fields=["admitted_at"])

    charge_bed_nights(admission=admission, actor=ward_doctor)
    invoice = Invoice.objects.get(admission=admission)
    finalise_invoice(invoice)
    paid = as_cashier.post(
        reverse("payment-list"),
        {"invoice": invoice.pk, "amount": str(invoice.total),
         "method": tariff["cash"].pk, "session": cashier_session["id"],
         "idempotency_key": "discharge-settlement-1"},
        format="json",
    )
    assert paid.status_code == 201, paid.data

    response = as_ward_doctor.post(
        reverse("admission-discharge", args=[admission.pk]),
        {"diagnosis": "Hypertension, controlled on amlodipine",
         "destination": "home",
         "instructions": "Review in clinic in two weeks with a BP diary"},
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["status"] == "discharged"
    assert response.data["bed"] is None
    assert response.data["length_of_stay_nights"] == 2

    bed.refresh_from_db()
    assert bed.service_state == Bed.CLEANING
    assert bed.is_occupied is False
    assert bed.state == Bed.CLEANING  # not "available"

    occupancy.refresh_from_db()
    assert occupancy.ended_at is not None
    assert occupancy.reason_ended == "discharged"

    event = AuditEvent.objects.get(action="admission.discharged")
    assert event.changes["before"]["admission_diagnosis"] == "Hypertensive urgency"
    assert event.changes["after"]["discharge_diagnosis"].startswith("Hypertension")
    assert event.changes["after"]["destination"] == "home"
    assert event.changes["after"]["nights"] == 2
    assert event.changes["after"]["billing_overridden"] is False


@pytest.mark.django_db
def test_a_discharge_needs_both_a_diagnosis_and_a_destination(
    as_ward_doctor, admission
):
    """AC-105 (negative). The check constraint refuses an incomplete discharge
    even if the API is bypassed."""
    for payload in (
        {"diagnosis": "", "destination": "home"},
        {"diagnosis": "Resolved", "destination": ""},
    ):
        response = as_ward_doctor.post(
            reverse("admission-discharge", args=[admission.pk]), payload, format="json"
        )
        assert response.status_code == 400, payload
    admission.refresh_from_db()
    assert admission.is_open


@pytest.mark.django_db
def test_a_discharged_admission_cannot_be_discharged_again(
    admission, ward_doctor
):
    """AC-101 (negative)."""
    from django.core.exceptions import ValidationError

    discharge(admission=admission, actor=ward_doctor, diagnosis="Resolved",
              destination="home")
    with pytest.raises(ValidationError, match="already been discharged"):
        discharge(admission=admission, actor=ward_doctor, diagnosis="Resolved",
                  destination="home")


# --- the summary --------------------------------------------------------------

@pytest.mark.django_db
def test_the_discharge_summary_is_assembled_from_the_record(
    as_ward_doctor, admission, ward_doctor, formulary, fbc, lab_catalogue
):
    """AC-102, AC-104.

    Nothing here is retyped: the reviews are the encounters, the results are the
    verified results, the medication is the discharge prescription.
    """
    from clinical.models import Encounter, EncounterVersion, Diagnosis
    from pharmacy.models import Prescription, PrescriptionItem

    encounter = Encounter.objects.create(
        admission=admission, visit=None, patient=admission.patient,
        facility=admission.facility, clinician=ward_doctor,
        encounter_type=Encounter.DAILY_REVIEW, status=Encounter.FINAL,
        finalised_at=timezone.now(),
    )
    version = EncounterVersion.objects.create(
        encounter=encounter, version_number=1, authored_by=ward_doctor,
        clinical_notes="BP settling on amlodipine 10 mg", is_current=True,
    )
    Diagnosis.objects.create(
        version=version, description="Hypertensive urgency", is_primary=True
    )

    prescription = Prescription.objects.create(
        admission=admission, visit=None, patient=admission.patient,
        facility=admission.facility, prescribed_by=ward_doctor,
        is_discharge_medication=True,
    )
    PrescriptionItem.objects.create(
        prescription=prescription, medication=formulary["amoxicillin"],
        dose="500", dose_unit="mg", route="oral", frequency_per_day=3,
        duration_days=5, quantity_prescribed=15, instructions="After food",
    )

    discharge(admission=admission, actor=ward_doctor,
              diagnosis="Hypertension, controlled", destination="home",
              instructions="Clinic in two weeks")

    first = as_ward_doctor.get(reverse("admission-summary", args=[admission.pk]))
    assert first.status_code == 200, first.data
    summary = first.data
    assert summary["admission_diagnosis"] == "Hypertensive urgency"
    assert summary["discharge_diagnosis"] == "Hypertension, controlled"
    assert summary["destination"] == "Home"
    assert summary["hospital_number"] == admission.patient.hospital_number
    assert summary["reviews"][0]["notes"] == "BP settling on amlodipine 10 mg"
    assert summary["reviews"][0]["diagnoses"] == ["Hypertensive urgency"]
    assert len(summary["discharge_medication"]) == 1
    assert summary["discharge_medication"][0]["instructions"] == "After food"
    assert "3 times a day for 5 days" in summary["discharge_medication"][0]["directions"]
    assert summary["follow_up_instructions"] == "Clinic in two weeks"
    assert summary["movement"][0]["ward"] == "Male Medical Ward"

    # AC-104: a reprint is identical, and both prints are logged.
    second = as_ward_doctor.get(reverse("admission-summary", args=[admission.pk]))
    assert second.data == first.data
    assert AuditEvent.objects.filter(
        action="admission.discharge_summary_printed"
    ).count() == 2


# --- inpatient billing --------------------------------------------------------

@pytest.mark.django_db
def test_inpatient_charges_land_on_the_admission_not_a_stale_visit(
    admission, open_visit, tariff, ward_doctor, finalise_invoice
):
    """AC-108.

    A stay accrues charges for weeks after the outpatient bill was paid and
    frozen. Billing ward work to that invoice would either fail or reopen a
    reconciled record.
    """
    from billing.models import charge, open_invoice_for

    outpatient = open_invoice_for(visit=open_visit)
    charge(visit=open_visit, service_code=tariff["consult"].code,
           description="Consultation", source_type="visits.Visit",
           source_id=open_visit.pk, actor=ward_doctor)
    finalise_invoice(outpatient)

    item, created = charge(
        admission=admission, service_code=tariff["consult"].code,
        description="Ward review", source_type="clinical.Encounter",
        source_id="ward-1", actor=ward_doctor,
    )
    assert created is True
    assert item.invoice.admission_id == admission.pk
    assert item.invoice_id != outpatient.pk
    assert item.invoice.visit_id is None
    outpatient.refresh_from_db()
    assert outpatient.items.count() == 1
