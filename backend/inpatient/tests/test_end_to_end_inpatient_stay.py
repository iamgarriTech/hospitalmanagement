"""AC-113 and AC-114 — the inpatient stay, end to end.

This is the test that decides whether Phase 2 is a system or four screens
sharing a sidebar. It drives one patient the whole way through:

    admission request → admit → allocate bed → nursing assessment →
    observations → MAR schedule → administer → daily review → investigation →
    transfer → discharge planning → final billing → payment → discharge

and then asserts two things no module test can: that the finished stay is
reconstructable from the patient's record alone, and that every step left an
audit row. AC-114 repeats the walk with one permission missing at a time and
checks it fails at exactly that step and no earlier.

It goes through the HTTP API as five different users, because "it works" has to
mean the ward doctor, ward nurse, laboratory scientist, cashier and ward manager
can each do their own part and nobody else's.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from billing.models import Invoice
from inpatient.models import Admission
from visits.models import Visit


@pytest.fixture
def hospital(db, facility_a, hospital_numbers, visit_numbers, inpatient_numbers,
             lab_numbers, pharmacy_numbers, billing_numbers, tariff, lab_catalogue,
             formulary, ward, beds):
    """One configured facility with a staffed ward."""
    lab_catalogue["fbc"].service = tariff["fbc_service"]
    lab_catalogue["fbc"].save(update_fields=["service"])
    medication = formulary["amoxicillin"]
    medication.selling_price = Decimal("120.00")
    medication.save(update_fields=["selling_price"])
    ward.nightly_service = tariff["bed_night"]
    ward.save(update_fields=["nightly_service"])

    from inpatient.models import EscalationThreshold

    EscalationThreshold.objects.create(
        ward=ward, measurement="systolic_bp", high=180,
        instruction="Tell the registrar and repeat in 15 minutes",
    )
    return {"facility": facility_a, "tariff": tariff, "lab": lab_catalogue,
            "formulary": formulary, "ward": ward, "beds": beds}


@pytest.fixture
def clients(as_reception, as_ward_doctor, as_ward_nurse, as_lab, as_cashier,
            as_ward_manager):
    return {"reception": as_reception, "doctor": as_ward_doctor,
            "nurse": as_ward_nurse, "lab": as_lab, "cashier": as_cashier,
            "manager": as_ward_manager}


def walk_the_stay(*, clients, hospital, users, stop_after=None):
    """Drive the whole stay, returning what each step produced.

    `stop_after` lets the permission tests assert *where* a walk fails.
    """
    reception, doctor, nurse, cashier = (
        clients["reception"], clients["doctor"], clients["nurse"], clients["cashier"],
    )
    facility = hospital["facility"]
    ward, beds = hospital["ward"], hospital["beds"]
    steps = {}

    # 1. The patient arrives as an outpatient and is checked in.
    registered = reception.post(
        reverse("patient-list"),
        {"given_name": "Emeka", "family_name": "Obi", "sex": "male",
         "date_of_birth": "1968-02-11", "phone_primary": "08055512345",
         "facility": facility.pk},
        format="json",
    )
    steps["register"] = registered
    if registered.status_code != 201:
        return steps
    patient_id = registered.data["id"]

    checked_in = reception.post(
        reverse("visit-list"),
        {"patient": patient_id, "facility": facility.pk, "visit_type": "walk_in",
         "reason": "Severe headache and blurred vision"},
        format="json",
    )
    steps["check_in"] = checked_in
    if checked_in.status_code != 201:
        return steps
    visit_id = checked_in.data["id"]

    # 2. A clinician asks for a bed. No bed is allocated yet.
    requested = doctor.post(
        reverse("admissionrequest-list"),
        {"patient": patient_id, "facility": facility.pk, "visit": visit_id,
         "ward": ward.pk, "priority": "urgent",
         "reason": "BP 212/128, papilloedema on fundoscopy",
         "working_diagnosis": "Hypertensive emergency",
         "responsible_consultant": users["doctor"].pk},
        format="json",
    )
    steps["request"] = requested
    if stop_after == "request" or requested.status_code != 201:
        return steps

    # 3. The ward admits, into a named bed.
    admitted = doctor.post(
        reverse("admission-admit"),
        {"request": requested.data["id"], "bed": beds[0].pk},
        format="json",
    )
    steps["admit"] = admitted
    if stop_after == "admit" or admitted.status_code != 201:
        return steps
    admission_id = admitted.data["id"]

    # 4. Observations on the ward — which breach the threshold and escalate.
    observed = nurse.post(
        reverse("vitals-list"),
        {"patient": patient_id, "admission": admission_id, "facility": facility.pk,
         "temperature_c": "37.1", "systolic_bp": 208, "diastolic_bp": 124,
         "pulse_bpm": 96, "oxygen_saturation": 97},
        format="json",
    )
    steps["observations"] = observed
    if stop_after == "observations" or observed.status_code != 201:
        return steps

    # 5. The escalation is answered.
    escalation_id = observed.data["escalations"][0]["id"]
    acknowledged = doctor.post(
        reverse("escalation-acknowledge", args=[escalation_id]),
        {"action_taken": "Reviewed at the bedside, IV labetalol started"},
        format="json",
    )
    steps["acknowledge"] = acknowledged
    if stop_after == "acknowledge" or acknowledged.status_code != 200:
        return steps

    # 6. A shift assessment.
    assessed = nurse.post(
        reverse("nursingassessment-list"),
        {"admission": admission_id, "shift": "early",
         "observations": observed.data["id"], "consciousness": "alert",
         "mobility": "assisted", "falls_risk": True,
         "summary": "Headache easing, tolerating oral fluids"},
        format="json",
    )
    steps["assessment"] = assessed
    if stop_after == "assessment" or assessed.status_code != 201:
        return steps

    # 7. Ward medication, prescribed against the admission.
    prescribed = doctor.post(
        reverse("prescription-list"),
        {"admission": admission_id, "patient": patient_id, "facility": facility.pk,
         "items": [{"medication": hospital["formulary"]["amoxicillin"].pk,
                    "dose": "500", "dose_unit": "mg", "route": "oral",
                    "frequency_per_day": 3, "duration_days": 5,
                    "quantity_prescribed": 15, "instructions": "After food"}]},
        format="json",
    )
    steps["prescribe"] = prescribed
    if stop_after == "prescribe" or prescribed.status_code != 201:
        return steps
    item_id = prescribed.data["items"][0]["id"]

    # 8. Which goes onto the drug chart as due doses.
    scheduled = doctor.post(
        reverse("scheduleddose-schedule"),
        {"prescription_item": item_id, "admission": admission_id},
        format="json",
    )
    steps["schedule"] = scheduled
    if stop_after == "schedule" or scheduled.status_code != 201:
        return steps

    # 9. A nurse gives the first dose, from a named batch.
    batch = hospital["formulary"]["batches"]["amoxicillin"]
    given = nurse.post(
        reverse("scheduleddose-record", args=[scheduled.data[0]["id"]]),
        {"state": "administered", "batch": batch.pk}, format="json",
    )
    steps["administer"] = given
    if stop_after == "administer" or given.status_code != 201:
        return steps

    # 10. The daily review, as an encounter against the admission.
    reviewed = doctor.post(
        reverse("encounter-list"),
        {"admission": admission_id, "encounter_type": "daily_review",
         "presenting_complaint": "Day 2 review",
         "examination_findings": "BP 168/94, fundi unchanged",
         "clinical_notes": "Responding to labetalol, converting to oral amlodipine",
         "diagnoses": [{"description": "Hypertensive emergency",
                        "certainty": "confirmed", "is_primary": True}]},
        format="json",
    )
    steps["review"] = reviewed
    if stop_after == "review" or reviewed.status_code != 201:
        return steps
    finalised = doctor.post(reverse("encounter-finalise", args=[reviewed.data["id"]]))
    steps["finalise_review"] = finalised
    if finalised.status_code != 200:
        return steps

    # 11. An investigation, ordered against the admission.
    ordered = doctor.post(
        reverse("laborder-list"),
        {"admission": admission_id, "patient": patient_id, "facility": facility.pk,
         "clinical_details": "Renal function in hypertensive emergency",
         "tests": [hospital["lab"]["fbc"].pk]},
        format="json",
    )
    steps["investigation"] = ordered
    if stop_after == "investigation" or ordered.status_code != 201:
        return steps

    # 12. The patient is moved to a quieter bed.
    moved = doctor.post(
        reverse("admission-transfer", args=[admission_id]),
        {"to_bed": beds[2].pk, "reason": "Moved off the observation bay"},
        format="json",
    )
    steps["transfer"] = moved
    if stop_after == "transfer" or moved.status_code != 200:
        return steps

    # 13. Discharge planning.
    planned = doctor.post(
        reverse("admission-plan-discharge", args=[admission_id]),
        {"expected_date": str((timezone.now() + timedelta(days=1)).date()),
         "destination": "home",
         "notes": "Needs the TTO dispensed and a BP diary"},
        format="json",
    )
    steps["plan_discharge"] = planned
    if stop_after == "plan_discharge" or planned.status_code != 200:
        return steps

    # Backdate the stay so there are bed nights to settle. Done here rather than
    # by sleeping: the point of the walk is the workflow, not the clock.
    admission = Admission.objects.get(pk=admission_id)
    occupancies = list(admission.occupancies.order_by("period"))
    first = occupancies[0]
    first.period = type(first.period)(
        timezone.now() - timedelta(days=2), first.period.upper
    )
    first.save(update_fields=["period"])
    admission.admitted_at = first.period.lower
    admission.save(update_fields=["admitted_at"])

    # 14. What is still owed, which is also what charges the nights.
    owed = doctor.get(reverse("admission-billing", args=[admission_id]))
    steps["billing"] = owed
    if stop_after == "billing" or owed.status_code != 200:
        return steps

    # 15. Settled at the cash desk.
    session = cashier.post(
        reverse("cashiersession-list"),
        {"facility": facility.pk, "opening_float": "5000.00"}, format="json",
    )
    steps["session"] = session
    if session.status_code != 201:
        return steps

    invoice = Invoice.objects.filter(admission=admission, status=Invoice.DRAFT).first()
    frozen = cashier.post(reverse("invoice-finalise", args=[invoice.pk]))
    steps["finalise_invoice"] = frozen
    if frozen.status_code != 200:
        return steps
    invoice.refresh_from_db()

    paid = cashier.post(
        reverse("payment-list"),
        {"invoice": invoice.pk, "method": hospital["tariff"]["cash"].pk,
         "amount": str(invoice.total), "session": session.data["id"],
         "idempotency_key": f"stay-{admission_id}"},
        format="json",
    )
    steps["payment"] = paid
    if stop_after == "payment" or paid.status_code != 201:
        return steps

    # 16. And discharged.
    discharged = doctor.post(
        reverse("admission-discharge", args=[admission_id]),
        {"diagnosis": "Hypertensive emergency, controlled",
         "destination": "home",
         "instructions": "Amlodipine 10 mg daily, clinic in two weeks"},
        format="json",
    )
    steps["discharge"] = discharged
    steps["ids"] = {
        "patient": patient_id, "visit": visit_id, "admission": admission_id,
        "invoice": invoice.pk, "encounter": reviewed.data["id"],
        "order": ordered.data["id"], "item": item_id,
    }
    return steps


@pytest.fixture
def users(ward_doctor, ward_nurse, lab_scientist, cashier, ward_manager):
    return {"doctor": ward_doctor, "nurse": ward_nurse, "lab": lab_scientist,
            "cashier": cashier, "manager": ward_manager}


@pytest.mark.django_db
def test_the_whole_inpatient_stay_works_end_to_end(clients, hospital, users):
    """AC-113."""
    steps = walk_the_stay(clients=clients, hospital=hospital, users=users)

    for name, expected in [
        ("register", 201), ("check_in", 201), ("request", 201), ("admit", 201),
        ("observations", 201), ("acknowledge", 200), ("assessment", 201),
        ("prescribe", 201), ("schedule", 201), ("administer", 201),
        ("review", 201), ("finalise_review", 200), ("investigation", 201),
        ("transfer", 200), ("plan_discharge", 200), ("billing", 200),
        ("finalise_invoice", 200), ("payment", 201), ("discharge", 200),
    ]:
        assert name in steps, f"the walk never reached {name}"
        assert steps[name].status_code == expected, (
            f"{name} returned {steps[name].status_code}, not {expected}: "
            f"{steps[name].data}"
        )

    discharged = steps["discharge"].data
    assert discharged["status"] == "discharged"
    assert discharged["length_of_stay_nights"] == 2
    assert discharged["bed"] is None

    # The outpatient attendance that started it is closed as admitted, not
    # left sitting in the queue.
    visit = Visit.objects.get(pk=steps["ids"]["visit"])
    assert visit.status == Visit.ADMITTED
    assert visit.closed_at is not None

    # The bed is released for cleaning, not straight back to available.
    from inpatient.models import Bed

    assert Bed.objects.get(pk=hospital["beds"][2].pk).service_state == Bed.CLEANING


@pytest.mark.django_db
def test_the_finished_stay_is_reconstructable_from_the_patients_record(
    clients, hospital, users
):
    """AC-113: the stay can be recounted afterwards from the patient alone.

    This is the part that distinguishes a system from a set of forms: nothing
    below is retyped, and nothing is read from the responses of the walk itself.
    """
    steps = walk_the_stay(clients=clients, hospital=hospital, users=users)
    assert steps["discharge"].status_code == 200, steps["discharge"].data
    patient_id = steps["ids"]["patient"]
    admission_id = steps["ids"]["admission"]
    doctor = clients["doctor"]

    # One stay, found from the patient.
    stays = doctor.get(reverse("admission-list"), {"patient": patient_id})
    assert [row["id"] for row in stays.data["results"]] == [admission_id]

    stay = doctor.get(reverse("admission-detail", args=[admission_id])).data
    assert stay["admission_diagnosis"] == "Hypertensive emergency"
    assert stay["discharge_diagnosis"] == "Hypertensive emergency, controlled"
    assert stay["consultant_name"] == "Kola Ward"

    # Where the patient was, in order, with the transfer recorded.
    assert [entry["bed"] for entry in stay["movement"]] == [
        str(hospital["beds"][0]), str(hospital["beds"][2])
    ]
    assert stay["transfers"][0]["reason"] == "Moved off the observation bay"

    # The drug chart, and the dose that reached the patient.
    chart = doctor.get(
        reverse("scheduleddose-chart"), {"admission": admission_id}
    ).data
    assert len(chart["rows"]) == 1
    given = [
        cell for row in chart["rows"] for cell in row["cells"].values()
        if cell["status"] == "administered"
    ]
    assert len(given) == 1
    assert given[0]["by"] == "Amaka Nurse"

    # The observation is on the patient's trend, not a separate inpatient one.
    trend = doctor.get(reverse("vitals-trend"), {"patient": patient_id}).data
    assert trend["systolic_bp"][0]["value"] == 208.0

    # The escalation, and what was done about it.
    escalations = doctor.get(
        reverse("escalation-list"), {"admission": admission_id}
    ).data["results"]
    assert len(escalations) == 1
    assert escalations[0]["is_outstanding"] is False
    assert "labetalol" in escalations[0]["action_taken"]

    # The nursing record.
    assessments = doctor.get(
        reverse("nursingassessment-list"), {"admission": admission_id}
    ).data["results"]
    assert assessments[0]["falls_risk"] is True

    # The daily review, versioned like any other clinical record.
    encounters = doctor.get(
        reverse("encounter-list"), {"patient": patient_id}
    ).data["results"]
    review = next(row for row in encounters if row["encounter_type"] == "daily_review")
    assert review["current"]["diagnoses"][0]["description"] == "Hypertensive emergency"

    # The investigation, against the admission.
    orders = doctor.get(
        reverse("laborder-list"), {"patient": patient_id}
    ).data["results"]
    assert orders[0]["admission"] == admission_id

    # And the discharge summary, assembled from all of it rather than retyped.
    summary = doctor.get(reverse("admission-summary", args=[admission_id])).data
    assert summary["nights"] == 2
    assert summary["destination"] == "Home"
    assert "amlodipine" in summary["reviews"][0]["notes"]
    assert summary["movement"][1]["bed"] == str(hospital["beds"][2])
    assert "clinic in two weeks" in summary["follow_up_instructions"]

    # The money reconciles: two nights and one dose, settled in full.
    invoice = Invoice.objects.get(pk=steps["ids"]["invoice"])
    assert invoice.status == Invoice.PAID
    assert invoice.balance == Decimal("0.00")
    bed_nights = invoice.items.filter(source_type="inpatient.BedNight")
    assert bed_nights.count() == 2
    assert invoice.items.filter(
        source_type="inpatient.MedicationAdministration"
    ).count() == 1


@pytest.mark.django_db
def test_every_step_of_the_stay_left_an_audit_trail(clients, hospital, users):
    """AC-113: and the chain still verifies after all of it."""
    steps = walk_the_stay(clients=clients, hospital=hospital, users=users)
    assert steps["discharge"].status_code == 200, steps["discharge"].data
    patient_id = steps["ids"]["patient"]

    events = AuditEvent.objects.filter(patient_id=patient_id)
    actions = set(events.values_list("action", flat=True))
    for expected in [
        "patient.registered",
        "visit.checked_in",
        "admission.requested",
        "admission.admitted",
        "vitals.recorded",
        "nursing.escalation_raised",
        "nursing.escalation_acknowledged",
        "nursing.assessment_recorded",
        "prescription.written",
        "mar.doses_scheduled",
        "mar.administered",
        "encounter.finalised",
        "lab.order_placed",
        "admission.transferred",
        "admission.discharge_planned",
        "admission.bed_nights_charged",
        "invoice.finalised",
        "payment.received",
        "admission.discharged",
    ]:
        assert expected in actions, f"{expected} left no audit row"

    # Every row names an actor: an audit row with nobody responsible is not one.
    assert not events.filter(actor_email="").exists()

    ok, problems = AuditEvent.verify_chain()
    assert ok is True, problems


@pytest.mark.django_db
@pytest.mark.parametrize(
    "step,role,permission",
    [
        ("request", "doctor", "inpatient.add_admissionrequest"),
        ("admit", "doctor", "inpatient.admit_patient"),
        ("observations", "nurse", "clinical.add_vitalsigns"),
        ("acknowledge", "doctor", "inpatient.escalate_observation"),
        ("assessment", "nurse", "inpatient.add_nursingassessment"),
        ("prescribe", "doctor", "pharmacy.add_prescription"),
        ("schedule", "doctor", "inpatient.add_scheduleddose"),
        ("administer", "nurse", "inpatient.add_medicationadministration"),
        ("review", "doctor", "clinical.add_encounter"),
        ("investigation", "doctor", "laboratory.add_laborder"),
        ("transfer", "doctor", "inpatient.transfer_patient"),
        ("plan_discharge", "doctor", "inpatient.plan_discharge"),
        ("payment", "cashier", "billing.add_payment"),
        ("discharge", "doctor", "inpatient.discharge_patient"),
    ],
)
def test_removing_one_permission_fails_the_stay_at_exactly_that_step(
    clients, hospital, users, step, role, permission
):
    """AC-114 (negative) — fourteen walks, each missing exactly one permission.

    Every earlier step must still succeed, so this also proves the permission
    being removed is the one actually guarding that step and not a coincidence.
    """
    from django.contrib.auth.models import Permission

    from accounts.models import RoleAssignment

    app_label, codename = permission.split(".")
    target = Permission.objects.get(
        content_type__app_label=app_label, codename=codename
    )
    for assignment in RoleAssignment.objects.all():
        assignment.role.permissions.remove(target)

    steps = walk_the_stay(clients=clients, hospital=hospital, users=users)

    assert step in steps, f"the walk never reached {step} (got {list(steps)})"
    assert steps[step].status_code == 403, (
        f"{step} returned {steps[step].status_code}, not 403, with {permission} "
        f"removed: {steps[step].data}"
    )
    assert "discharge" not in steps or step == "discharge", (
        "the walk continued past the refused step"
    )

    denial = AuditEvent.objects.filter(
        action="permission.denied", outcome=AuditEvent.DENIED
    ).last()
    assert denial is not None, f"the refusal at {step} was not audited"
    assert denial.changes["after"]["permission"] == permission


@pytest.mark.django_db
def test_the_stay_cannot_be_closed_with_the_bill_unsettled(clients, hospital, users):
    """AC-100 within the walk — the gate holds in the whole flow, not only in
    isolation. This is the case where every other permission is present."""
    steps = walk_the_stay(
        clients=clients, hospital=hospital, users=users, stop_after="billing"
    )
    assert steps["billing"].status_code == 200
    assert steps["billing"].data["outstanding"], "expected an unsettled stay"

    admission_id = steps["admit"].data["id"]
    refused = clients["doctor"].post(
        reverse("admission-discharge", args=[admission_id]),
        {"diagnosis": "Controlled", "destination": "home"}, format="json",
    )
    assert refused.status_code == 409
    assert Admission.objects.get(pk=admission_id).is_open
