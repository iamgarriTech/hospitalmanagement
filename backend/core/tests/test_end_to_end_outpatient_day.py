"""AC-50 and AC-51 — the outpatient day, end to end.

This is the test that decides whether Phase 1 is a system or ten modules sharing a
navigation bar. It drives one patient the whole way through:

    register → check-in → queue → vitals → consultation → lab order → specimen
    → result → verification → clinician review → prescription → dispense → invoice
    → payment → visit closed

and then asserts two things the individual module tests cannot: that the completed visit
is reconstructable from the patient's history alone, and that every step left an audit
trail. AC-51 repeats the walk with one permission missing at a time and checks it fails
at exactly that step and no earlier.

It goes through the HTTP API as six different users, because "it works" has to mean the
receptionist, nurse, doctor, laboratory scientist, pharmacist and cashier can each do
their own part and nobody else's.
"""
from decimal import Decimal

import pytest
from django.urls import reverse

from audit.models import AuditEvent
from billing.models import Invoice
from laboratory.models import LabOrderItem
from pharmacy.models import StockBatch
from visits.models import Visit


@pytest.fixture
def hospital(db, facility_a, hospital_numbers, visit_numbers, lab_numbers,
             pharmacy_numbers, billing_numbers, tariff, lab_catalogue, formulary):
    """One configured facility: tariff, laboratory catalogue and formulary."""
    lab_catalogue["fbc"].service = tariff["fbc_service"]
    lab_catalogue["fbc"].save(update_fields=["service"])
    medication = formulary["amoxicillin"]
    medication.selling_price = Decimal("120.00")
    medication.save(update_fields=["selling_price"])
    return {"facility": facility_a, "tariff": tariff, "lab": lab_catalogue,
            "formulary": formulary}


def walk_the_day(*, clients, hospital, stop_after=None):
    """Drive the whole flow, returning what each step produced.

    `stop_after` lets the permission tests assert *where* a walk fails.
    """
    reception, nurse, doctor, lab, pharmacist, cashier = (
        clients["reception"], clients["nurse"], clients["doctor"],
        clients["lab"], clients["pharmacist"], clients["cashier"],
    )
    facility = hospital["facility"]
    steps = {}

    # 1. Registration
    registered = reception.post(
        reverse("patient-list"),
        {"given_name": "Ifeoma", "family_name": "Adeyinka", "sex": "female",
         "date_of_birth": "1988-03-12", "phone_primary": "08055512345",
         "facility": facility.pk,
         "allergies": [{"substance": "Sulfa", "reaction": "Rash", "severity": "mild"}]},
        format="json",
    )
    steps["register"] = registered
    if stop_after == "register" or registered.status_code != 201:
        return steps
    patient_id = registered.data["id"]

    # 2. Check-in
    checked_in = reception.post(
        reverse("visit-list"),
        {"patient": patient_id, "facility": facility.pk, "visit_type": "walk_in",
         "reason": "Fever and headache"},
        format="json",
    )
    steps["check_in"] = checked_in
    if stop_after == "check_in" or checked_in.status_code != 201:
        return steps
    visit_id = checked_in.data["id"]

    # 3. Vitals at triage
    vitals = nurse.post(
        reverse("vitals-list"),
        {"patient": patient_id, "visit": visit_id, "facility": facility.pk,
         "temperature_c": "38.7", "systolic_bp": 118, "diastolic_bp": 76,
         "pulse_bpm": 98, "respiratory_rate": 20, "oxygen_saturation": 98,
         "weight_kg": "62.40", "height_cm": "162.0"},
        format="json",
    )
    steps["vitals"] = vitals
    if stop_after == "vitals" or vitals.status_code != 201:
        return steps

    # 4. Called through to the doctor
    move = reverse("visit-move", args=[visit_id])
    reception.post(move, {"to": Visit.CALLED, "note": "Room 2"}, format="json")
    reception.post(move, {"to": Visit.IN_CONSULTATION}, format="json")

    # 5. Consultation
    encounter = doctor.post(
        reverse("encounter-list"),
        {"visit": visit_id,
         "presenting_complaint": "Fever and headache for two days",
         "examination_findings": "Temp 38.7, no neck stiffness",
         "clinical_notes": "Query malaria. FBC requested.",
         "diagnoses": [{"description": "Malaria", "certainty": "provisional",
                        "is_primary": True}]},
        format="json",
    )
    steps["consultation"] = encounter
    if stop_after == "consultation" or encounter.status_code != 201:
        return steps
    encounter_id = encounter.data["id"]

    # 6. Investigation requested
    order = doctor.post(
        reverse("laborder-list"),
        {"visit": visit_id, "tests": [hospital["lab"]["fbc"].pk],
         "clinical_details": "Fever, query malaria"},
        format="json",
    )
    steps["lab_order"] = order
    if stop_after == "lab_order" or order.status_code != 201:
        return steps
    item_id = order.data["items"][0]["id"]
    doctor.post(move, {"to": Visit.SENT_FOR_INVESTIGATION}, format="json")

    # 7. Specimen collected and labelled
    collected = lab.post(reverse("laborderitem-collect", args=[item_id]), {},
                         format="json")
    steps["collect"] = collected
    if stop_after == "collect" or collected.status_code != 200:
        return steps

    # 8. Result entered
    lab.post(reverse("laborderitem-start-processing", args=[item_id]), {}, format="json")
    parameters = {p.name: p.pk for p in hospital["lab"]["fbc"].parameters.all()}
    entered = lab.post(
        reverse("laborderitem-results", args=[item_id]),
        {"entries": [
            {"parameter": parameters["Haemoglobin"], "value_numeric": "10.8"},
            {"parameter": parameters["White cell count"], "value_numeric": "9.4"},
            {"parameter": parameters["Platelets"], "value_numeric": "180"},
            {"parameter": parameters["Haematocrit"], "value_numeric": "34.0"},
        ]},
        format="json",
    )
    steps["enter_results"] = entered
    if stop_after == "enter_results" or entered.status_code != 201:
        return steps

    # 9. Verified and released
    verified = lab.post(reverse("laborderitem-verify", args=[item_id]),
                        {"comment": "Film reviewed"}, format="json")
    steps["verify"] = verified
    if stop_after == "verify" or verified.status_code != 200:
        return steps

    # 10. Clinician reviews, then prescribes
    review = doctor.get(reverse("laborder-report", args=[order.data["id"]]))
    steps["review"] = review
    doctor.post(move, {"to": Visit.IN_CONSULTATION}, format="json")
    prescription = doctor.post(
        reverse("prescription-list"),
        {"visit": visit_id, "encounter": encounter_id,
         "items": [{"medication": hospital["formulary"]["amoxicillin"].pk,
                    "dose": "500", "dose_unit": "mg", "route": "oral",
                    "frequency_per_day": 3, "duration_days": 5,
                    "quantity_prescribed": 15, "instructions": "After food"}]},
        format="json",
    )
    steps["prescribe"] = prescription
    if stop_after == "prescribe" or prescription.status_code != 201:
        return steps

    doctor.post(reverse("encounter-finalise", args=[encounter_id]))
    doctor.post(move, {"to": Visit.SENT_TO_PHARMACY}, format="json")

    # 11. Dispensed
    batch = StockBatch.objects.get(batch_number="AMX-2027A")
    dispensed = pharmacist.post(
        reverse("prescriptionitem-dispense",
                args=[prescription.data["items"][0]["id"]]),
        {"batch": batch.pk, "quantity": 15},
        format="json",
    )
    steps["dispense"] = dispensed
    if stop_after == "dispense" or dispensed.status_code != 200:
        return steps

    # 12. Billed and paid
    pharmacist.post(move, {"to": Visit.SENT_FOR_BILLING}, format="json")
    invoice = Invoice.objects.get(visit_id=visit_id)
    cashier.post(reverse("cashiersession-list"),
                 {"facility": facility.pk, "opening_float": "1000.00"}, format="json")
    cashier.post(reverse("invoice-finalise", args=[invoice.pk]))
    payment = cashier.post(
        reverse("payment-list"),
        {"invoice": invoice.pk, "method": hospital["tariff"]["cash"].pk,
         "amount": str(invoice.total), "idempotency_key": f"e2e-{visit_id}"},
        format="json",
    )
    steps["payment"] = payment
    if stop_after == "payment" or payment.status_code != 201:
        return steps

    # 13. Visit closed
    closed = cashier.post(move, {"to": Visit.COMPLETED}, format="json")
    steps["close"] = closed
    steps["ids"] = {"patient": patient_id, "visit": visit_id,
                    "encounter": encounter_id, "invoice": invoice.pk,
                    "order": order.data["id"]}
    return steps


@pytest.fixture
def clients(as_reception, as_nurse, as_doctor, as_lab, as_pharmacist, as_cashier):
    return {"reception": as_reception, "nurse": as_nurse, "doctor": as_doctor,
            "lab": as_lab, "pharmacist": as_pharmacist, "cashier": as_cashier}


@pytest.mark.django_db
def test_the_whole_outpatient_day_works_end_to_end(clients, hospital, as_doctor):
    """AC-50."""
    steps = walk_the_day(clients=clients, hospital=hospital)

    assert steps["register"].status_code == 201
    assert steps["check_in"].status_code == 201
    assert steps["vitals"].status_code == 201
    assert steps["consultation"].status_code == 201
    assert steps["lab_order"].status_code == 201
    assert steps["collect"].status_code == 200
    assert steps["enter_results"].status_code == 201
    assert steps["verify"].status_code == 200
    assert steps["prescribe"].status_code == 201
    assert steps["dispense"].status_code == 200
    assert steps["payment"].status_code == 201
    assert steps["close"].status_code == 200
    assert steps["close"].data["status"] == Visit.COMPLETED

    ids = steps["ids"]

    # The money adds up: consultation 5000 + FBC 3500 + 15 capsules × 120 = 10300
    invoice = Invoice.objects.get(pk=ids["invoice"])
    assert invoice.subtotal == Decimal("10300.00")
    assert invoice.balance == Decimal("0.00")
    assert invoice.status == Invoice.PAID
    assert {item.source_type for item in invoice.items.all()} == {
        "clinical.Encounter", "laboratory.LabOrderItem", "pharmacy.Dispense"
    }

    # Stock moved by exactly what was dispensed.
    assert StockBatch.objects.get(batch_number="AMX-2027A").quantity_on_hand == 25

    # The result reached the clinician as a finding, not as "pending".
    entry = steps["review"].data["items"][0]
    assert entry.get("pending") is None
    assert {row["parameter_name"] for row in entry["results"]} == {
        "Haemoglobin", "White cell count", "Platelets", "Haematocrit"
    }


@pytest.mark.django_db
def test_the_completed_visit_is_reconstructable_from_the_patients_history(
    clients, hospital
):
    """AC-50: the visit can be recounted afterwards from the patient alone."""
    steps = walk_the_day(clients=clients, hospital=hospital)
    patient_id = steps["ids"]["patient"]
    doctor = clients["doctor"]

    visits = doctor.get(reverse("visit-list"), {"patient": patient_id}).data["results"]
    assert len(visits) == 1
    assert visits[0]["status"] == Visit.COMPLETED

    trail = [change["to_status"] for change in
             doctor.get(reverse("visit-detail", args=[steps["ids"]["visit"]])
                        ).data["state_changes"]]
    assert trail == [
        Visit.CALLED, Visit.IN_CONSULTATION, Visit.SENT_FOR_INVESTIGATION,
        Visit.IN_CONSULTATION, Visit.SENT_TO_PHARMACY, Visit.SENT_FOR_BILLING,
        Visit.COMPLETED,
    ]

    encounters = doctor.get(reverse("encounter-list"),
                            {"patient": patient_id}).data["results"]
    assert encounters[0]["current"]["diagnoses"][0]["description"] == "Malaria"
    assert encounters[0]["status"] == "final"

    trend = doctor.get(reverse("vitals-trend"), {"patient": patient_id}).data
    assert trend["temperature_c"][0]["value"] == 38.7
    assert trend["bmi"][0]["value"] == pytest.approx(23.8, abs=0.1)

    orders = doctor.get(reverse("laborder-list"), {"patient": patient_id}).data["results"]
    assert orders[0]["items"][0]["status"] == LabOrderItem.VERIFIED

    prescriptions = doctor.get(reverse("prescription-list"),
                               {"patient": patient_id}).data["results"]
    assert prescriptions[0]["status"] == "dispensed"
    assert prescriptions[0]["items"][0]["quantity_dispensed"] == 15

    history = clients["pharmacist"].get(
        reverse("prescription-history"), {"patient": patient_id}
    ).data
    assert history[0]["batch_number"] == "AMX-2027A"


@pytest.mark.django_db
def test_every_step_of_the_day_left_an_audit_trail(clients, hospital):
    """AC-50: and the chain still verifies after all of it."""
    steps = walk_the_day(clients=clients, hospital=hospital)
    patient_id = steps["ids"]["patient"]

    actions = set(
        AuditEvent.objects.filter(patient_id=patient_id).values_list("action", flat=True)
    )
    for expected in [
        "patient.registered", "visit.checked_in", "vitals.recorded",
        "encounter.opened", "encounter.finalised", "lab.order_placed",
        "lab.specimen_collected", "lab.results_entered", "lab.results_verified",
        "prescription.written", "medication.dispensed", "payment.received",
        "visit.moved",
    ]:
        assert expected in actions, f"{expected} was not audited"

    ok, problems = AuditEvent.verify_chain()
    assert ok, problems

    # Six different people did the work, and the log says which.
    actors = set(
        AuditEvent.objects.filter(patient_id=patient_id)
        .exclude(actor_email="")
        .values_list("actor_email", flat=True)
    )
    assert actors >= {
        "front@example.test", "nurse@example.test", "doctor@example.test",
        "lab@example.test", "pharm@example.test", "cashier@example.test",
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    "step,role,permission",
    [
        ("register", "reception", "patients.add_patient"),
        ("check_in", "reception", "visits.check_in_patient"),
        ("vitals", "nurse", "clinical.add_vitalsigns"),
        ("consultation", "doctor", "clinical.add_encounter"),
        ("lab_order", "doctor", "laboratory.add_laborder"),
        ("collect", "lab", "laboratory.collect_specimen"),
        ("enter_results", "lab", "laboratory.add_labresult"),
        ("verify", "lab", "laboratory.verify_labresult"),
        ("prescribe", "doctor", "pharmacy.add_prescription"),
        ("dispense", "pharmacist", "pharmacy.dispense_medication"),
        ("payment", "cashier", "billing.add_payment"),
    ],
)
def test_removing_one_permission_fails_the_walk_at_exactly_that_step(
    clients, hospital, step, role, permission
):
    """AC-51 (negative) — eleven walks, each missing exactly one permission.

    Every earlier step must still succeed, so this also proves the permission being
    removed is the one actually guarding that step and not a coincidence.
    """
    from django.contrib.auth.models import Permission

    from accounts.models import RoleAssignment

    app_label, codename = permission.split(".")
    target = Permission.objects.get(
        content_type__app_label=app_label, codename=codename
    )
    for assignment in RoleAssignment.objects.all():
        assignment.role.permissions.remove(target)

    steps = walk_the_day(clients=clients, hospital=hospital, stop_after=None)

    assert step in steps, f"the walk never reached {step}"
    assert steps[step].status_code == 403, (
        f"{step} returned {steps[step].status_code}, not 403, with {permission} removed"
    )
    assert "close" not in steps, "the walk continued past the refused step"

    denials = AuditEvent.objects.filter(action="permission.denied")
    assert denials.exists(), f"the refusal at {step} was not audited"
