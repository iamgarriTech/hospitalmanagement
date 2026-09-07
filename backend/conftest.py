import pytest
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient

from accounts.models import Role, RoleAssignment, User
from facilities.models import Organization, Facility
from patients.models import NumberSequence

BACKEND = "accounts.backends.EmailBackend"
PASSWORD = "correct-horse-battery"


def perm(app_label, codename):
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


@pytest.fixture(autouse=True)
def _no_tls_redirect(settings):
    """Tests exercise the app directly; TLS is terminated by the proxy in production."""
    settings.SECURE_SSL_REDIRECT = False


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Ilesa Health Group")


@pytest.fixture
def facility_a(organization):
    return Facility.objects.create(organization=organization, name="Main Hospital", code="MAIN")


@pytest.fixture
def facility_b(organization):
    return Facility.objects.create(organization=organization, name="Ikeja Branch", code="IKJ")


@pytest.fixture
def viewer_role(db):
    role = Role.objects.create(name="Records Clerk")
    role.permissions.add(perm("facilities", "view_facility"))
    return role


@pytest.fixture
def editor_role(db):
    role = Role.objects.create(name="Facility Manager")
    role.permissions.add(
        perm("facilities", "view_facility"), perm("facilities", "change_facility")
    )
    return role


@pytest.fixture
def viewer(db, viewer_role, facility_a):
    user = User.objects.create_user("clerk@example.test", "Ada Clerk", PASSWORD)
    RoleAssignment.objects.create(user=user, role=viewer_role, facility=facility_a)
    return user


@pytest.fixture
def editor(db, editor_role, facility_a):
    user = User.objects.create_user("manager@example.test", "Bola Manager", PASSWORD)
    RoleAssignment.objects.create(user=user, role=editor_role, facility=facility_a)
    return user


@pytest.fixture
def api():
    return APIClient()


def _client_for(user):
    client = APIClient()
    client.force_login(user, backend=BACKEND)
    return client


@pytest.fixture
def as_viewer(viewer):
    return _client_for(viewer)


@pytest.fixture
def as_editor(editor):
    return _client_for(editor)


@pytest.fixture
def hospital_numbers(db):
    return NumberSequence.objects.create(
        key="hospital_number", prefix="ILS", include_year=True, width=5
    )


def _role(name, *qualified):
    role = Role.objects.create(name=name)
    role.permissions.add(*[perm(*entry.split(".")) for entry in qualified])
    return role


@pytest.fixture
def receptionist(db, facility_a, hospital_numbers):
    """Can register and search, cannot merge or override a suspected duplicate."""
    user = User.objects.create_user("front@example.test", "Chidi Front", PASSWORD)
    role = _role(
        "Receptionist",
        "patients.view_patient",
        "patients.add_patient",
        "patients.change_patient",
        "visits.view_visit",
        "visits.add_visit",
        "visits.change_visit",
        "visits.check_in_patient",
        "visits.move_queue",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def records_officer(db, facility_a, hospital_numbers):
    user = User.objects.create_user("records@example.test", "Sade Records", PASSWORD)
    role = _role(
        "Medical Records Officer",
        "patients.view_patient",
        "patients.add_patient",
        "patients.change_patient",
        "patients.merge_patient",
        "patients.register_duplicate_patient",
        "patients.view_patient_access_log",
        "visits.view_visit",
        "visits.check_in_patient",
        "visits.move_queue",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def as_reception(receptionist):
    return _client_for(receptionist)


@pytest.fixture
def as_records(records_officer):
    return _client_for(records_officer)


@pytest.fixture
def patient_payload(facility_a):
    def build(**overrides):
        payload = {
            "given_name": "Amina",
            "family_name": "Yusuf",
            "other_names": "",
            "date_of_birth": "1991-04-17",
            "sex": "female",
            "phone_primary": "08031234567",
            "address_line": "12 Adeola Street",
            "city": "Ilesa",
            "state": "Osun",
            "blood_group": "O+",
            "genotype": "AS",
            "facility": facility_a.pk,
        }
        payload.update(overrides)
        return payload

    return build


@pytest.fixture
def visit_numbers(db):
    return NumberSequence.objects.create(
        key="visit_number", prefix="V", include_year=True, width=6
    )


@pytest.fixture
def patient(db, facility_a, hospital_numbers):
    from patients.models import Patient

    return Patient.objects.create(
        given_name="Amina", family_name="Yusuf", sex="female",
        date_of_birth="1991-04-17", phone_primary="08031234567", facility=facility_a,
    )


@pytest.fixture
def open_visit(db, patient, facility_a, visit_numbers):
    from visits.models import Visit

    return Visit.objects.create(patient=patient, facility=facility_a)


@pytest.fixture
def doctor(db, facility_a):
    user = User.objects.create_user("doctor@example.test", "Chukwuma Nwosu", PASSWORD)
    role = _role(
        "Doctor",
        "patients.view_patient",
        "visits.view_visit",
        "visits.move_queue",
        "clinical.view_encounter",
        "clinical.add_encounter",
        "clinical.change_encounter",
        "clinical.finalise_encounter",
        "clinical.amend_encounter",
        "clinical.view_vitalsigns",
        "clinical.add_vitalsigns",
        "laboratory.view_laborder",
        "laboratory.add_laborder",
        "laboratory.view_labtest",
        "laboratory.acknowledge_critical_result",
        "pharmacy.view_prescription",
        "pharmacy.add_prescription",
        "pharmacy.view_medication",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def nurse(db, facility_a):
    """Records observations and reads notes; cannot amend a clinical record."""
    user = User.objects.create_user("nurse@example.test", "Fatima Bello", PASSWORD)
    role = _role(
        "Nurse",
        "patients.view_patient",
        "visits.view_visit",
        "visits.move_queue",
        "clinical.view_encounter",
        "clinical.view_vitalsigns",
        "clinical.add_vitalsigns",
        "clinical.change_vitalsigns",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def as_doctor(doctor):
    return _client_for(doctor)


@pytest.fixture
def as_nurse(nurse):
    return _client_for(nurse)


@pytest.fixture
def finalised_encounter(as_doctor, open_visit):
    from django.urls import reverse

    created = as_doctor.post(
        reverse("encounter-list"),
        {
            "visit": open_visit.pk,
            "presenting_complaint": "Fever for three days",
            "clinical_notes": "Suspected malaria, awaiting RDT",
            "diagnoses": [{"description": "Malaria", "certainty": "provisional",
                           "is_primary": True}],
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    finalised = as_doctor.post(reverse("encounter-finalise", args=[created.data["id"]]))
    assert finalised.status_code == 200, finalised.data
    return finalised.data


# --- laboratory ------------------------------------------------------------------

@pytest.fixture
def lab_numbers(db):
    NumberSequence.objects.create(
        key="lab_order_number", prefix="LAB", include_year=True, width=6
    )
    NumberSequence.objects.create(
        key="specimen_id", prefix="SPC", include_year=False, width=7
    )


@pytest.fixture
def lab_catalogue(db, lab_numbers):
    """A small but realistic catalogue.

    Haemoglobin carries sex-specific ranges because that is the case a single "normal
    range" column gets wrong, and malaria parasites are a text result because not every
    test produces a number.
    """
    from laboratory.models import LabTest, LabTestCategory, LabTestParameter, ReferenceRange

    haematology = LabTestCategory.objects.create(name="Haematology", display_order=1)

    fbc = LabTest.objects.create(
        category=haematology, name="Full blood count", short_code="FBC",
        specimen_type=LabTest.BLOOD, specimen_requirements="EDTA bottle, 3 mL",
        code_system="LOINC", code="58410-2", code_display="CBC panel - Blood",
        code_version="2.78",
    )
    haemoglobin = LabTestParameter.objects.create(
        test=fbc, name="Haemoglobin", unit="g/dL", decimal_places=1, display_order=1,
        code_system="LOINC", code="718-7",
    )
    ReferenceRange.objects.create(
        parameter=haemoglobin, sex="female", low=12, high=16,
        critical_low=7, critical_high=20,
    )
    ReferenceRange.objects.create(
        parameter=haemoglobin, sex="male", low=13, high=17,
        critical_low=7, critical_high=20,
    )
    white_cells = LabTestParameter.objects.create(
        test=fbc, name="White cell count", unit="×10⁹/L", decimal_places=1, display_order=2
    )
    ReferenceRange.objects.create(
        parameter=white_cells, low=4, high=11, critical_low=1, critical_high=50
    )
    platelets = LabTestParameter.objects.create(
        test=fbc, name="Platelets", unit="×10⁹/L", decimal_places=0, display_order=3
    )
    ReferenceRange.objects.create(
        parameter=platelets, low=150, high=400, critical_low=20
    )
    haematocrit = LabTestParameter.objects.create(
        test=fbc, name="Haematocrit", unit="%", decimal_places=1, display_order=4
    )
    ReferenceRange.objects.create(parameter=haematocrit, low=36, high=46)

    malaria = LabTest.objects.create(
        category=haematology, name="Malaria parasites", short_code="MP",
        specimen_type=LabTest.BLOOD, specimen_requirements="Thick and thin film",
    )
    LabTestParameter.objects.create(
        test=malaria, name="Malaria parasites", value_type=LabTestParameter.CHOICE,
        choices_csv="Positive,Negative", display_order=1,
    )

    panel = LabTest.objects.create(
        category=haematology, name="Fever screen", short_code="FEVER", is_panel=True
    )
    panel.panel_members.set([fbc, malaria])

    return {"category": haematology, "fbc": fbc, "malaria": malaria, "panel": panel}


@pytest.fixture
def fbc(lab_catalogue):
    return lab_catalogue["fbc"]


@pytest.fixture
def lab_scientist(db, facility_a):
    """Enters and verifies results."""
    user = User.objects.create_user("lab@example.test", "Ibrahim Sani", PASSWORD)
    role = _role(
        "Laboratory Scientist",
        "patients.view_patient", "visits.view_visit",
        "laboratory.view_laborder", "laboratory.view_labtest",
        "laboratory.collect_specimen", "laboratory.add_labresult",
        "laboratory.verify_labresult", "laboratory.amend_labresult",
        "laboratory.change_laborderitem",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def lab_technician(db, facility_a):
    """Collects specimens and enters results, but cannot sign them off."""
    user = User.objects.create_user("tech@example.test", "Grace Tech", PASSWORD)
    role = _role(
        "Laboratory Technician",
        "patients.view_patient", "visits.view_visit",
        "laboratory.view_laborder", "laboratory.collect_specimen",
        "laboratory.add_labresult",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def as_lab(lab_scientist):
    return _client_for(lab_scientist)


@pytest.fixture
def as_lab_tech(lab_technician):
    return _client_for(lab_technician)


@pytest.fixture
def female_patient(db, facility_a, hospital_numbers):
    from patients.models import Patient

    return Patient.objects.create(
        given_name="Amina", family_name="Yusuf", sex="female",
        date_of_birth="1991-04-17", facility=facility_a,
    )


@pytest.fixture
def male_patient(db, facility_a, hospital_numbers):
    from patients.models import Patient

    return Patient.objects.create(
        given_name="Emeka", family_name="Obi", sex="male",
        date_of_birth="1985-02-08", facility=facility_a,
    )


@pytest.fixture
def order_for(db, doctor, facility_a, visit_numbers, lab_numbers):
    """Factory: place an order for one test and return its order item."""
    from laboratory.models import LabOrder, LabOrderItem
    from visits.models import Visit

    def place(patient, test, priority=LabOrder.ROUTINE):
        visit = Visit.objects.create(patient=patient, facility=facility_a)
        order = LabOrder.objects.create(
            visit=visit, patient=patient, facility=facility_a,
            ordered_by=doctor, priority=priority,
            clinical_details="Fever for three days",
        )
        return LabOrderItem.objects.create(order=order, test=test)

    return place


@pytest.fixture
def fbc_order_item(order_for, female_patient, fbc):
    return order_for(female_patient, fbc)


@pytest.fixture
def resulted_item(as_lab, fbc_order_item, fbc):
    """A full blood count with a critically low haemoglobin, entered but not verified."""
    from django.urls import reverse

    as_lab.post(reverse("laborderitem-collect", args=[fbc_order_item.pk]), {},
                format="json")
    as_lab.post(reverse("laborderitem-start-processing", args=[fbc_order_item.pk]), {},
                format="json")
    parameters = {p.name: p.pk for p in fbc.parameters.all()}
    response = as_lab.post(
        reverse("laborderitem-results", args=[fbc_order_item.pk]),
        {"entries": [
            {"parameter": parameters["Haemoglobin"], "value_numeric": "5.9"},
            {"parameter": parameters["White cell count"], "value_numeric": "9.0"},
            {"parameter": parameters["Platelets"], "value_numeric": "230"},
            {"parameter": parameters["Haematocrit"], "value_numeric": "21.0"},
        ]},
        format="json",
    )
    assert response.status_code == 201, response.data
    fbc_order_item.refresh_from_db()
    return fbc_order_item


# --- pharmacy --------------------------------------------------------------------

@pytest.fixture
def pharmacy_numbers(db):
    NumberSequence.objects.create(
        key="prescription_number", prefix="RX", include_year=True, width=6
    )


@pytest.fixture
def formulary(db, pharmacy_numbers, facility_a):
    """A small formulary with the cases that matter: a penicillin (allergy), a drug
    with a dose ceiling, and one carrying a paediatric caution."""
    from datetime import timedelta

    from django.utils import timezone

    from pharmacy.models import (
        ContraindicationRule, DoseRange, Medication, MedicationCategory, StockBatch,
    )

    antibiotics = MedicationCategory.objects.create(name="Antibiotics", display_order=1)
    analgesics = MedicationCategory.objects.create(name="Analgesics", display_order=2)

    amoxicillin = Medication.objects.create(
        category=antibiotics, generic_name="Amoxicillin", strength="500 mg",
        dosage_form="capsule", default_route=Medication.ORAL,
        dispensing_unit="capsule", ingredients_csv="Amoxicillin",
        atc_class="J01CA", code_system="ATC", code="J01CA04",
    )
    DoseRange.objects.create(
        medication=amoxicillin, route=Medication.ORAL,
        min_single_dose=250, max_single_dose=1000, dose_unit="mg", max_daily_dose=3000,
    )

    ampicillin = Medication.objects.create(
        category=antibiotics, generic_name="Ampicillin", strength="250 mg",
        dosage_form="capsule", ingredients_csv="Ampicillin", atc_class="J01CA",
    )

    paracetamol = Medication.objects.create(
        category=analgesics, generic_name="Paracetamol", strength="500 mg",
        dosage_form="tablet", dispensing_unit="tablet", ingredients_csv="Paracetamol",
        atc_class="N02BE",
    )
    DoseRange.objects.create(
        medication=paracetamol, route=Medication.ORAL,
        min_single_dose=500, max_single_dose=1000, dose_unit="mg", max_daily_dose=4000,
    )

    diclofenac = Medication.objects.create(
        category=analgesics, generic_name="Diclofenac", strength="50 mg",
        dosage_form="tablet", dispensing_unit="tablet", ingredients_csv="Diclofenac",
        atc_class="M01AB", avoid_in_renal_impairment=True, paediatric_caution=True,
        caution_note="Not recommended under 14 years.",
    )
    DoseRange.objects.create(
        medication=diclofenac, route=Medication.ORAL,
        min_single_dose=25, max_single_dose=50, dose_unit="mg", max_daily_dose=150,
    )
    ContraindicationRule.objects.create(
        medication=diclofenac, condition_keyword="peptic ulcer",
        severity=ContraindicationRule.WARNING,
        note="Diclofenac is contraindicated in active peptic ulcer disease.",
    )

    today = timezone.localdate()
    batches = {
        "amoxicillin": StockBatch.objects.create(
            medication=amoxicillin, facility=facility_a, batch_number="AMX-2027A",
            expiry_date=today + timedelta(days=365), quantity_on_hand=40, unit_cost="25.00",
        ),
        "amoxicillin_expired": StockBatch.objects.create(
            medication=amoxicillin, facility=facility_a, batch_number="AMX-EXPIRED",
            expiry_date=today - timedelta(days=10), quantity_on_hand=100,
        ),
        "paracetamol": StockBatch.objects.create(
            medication=paracetamol, facility=facility_a, batch_number="PCM-2028A",
            expiry_date=today + timedelta(days=700), quantity_on_hand=500,
        ),
    }
    return {
        "amoxicillin": amoxicillin, "ampicillin": ampicillin,
        "paracetamol": paracetamol, "diclofenac": diclofenac, "batches": batches,
    }


@pytest.fixture
def pharmacist(db, facility_a):
    user = User.objects.create_user("pharm@example.test", "Yemi Adeyemi", PASSWORD)
    role = _role(
        "Pharmacist",
        "patients.view_patient", "visits.view_visit", "visits.move_queue",
        "pharmacy.view_prescription", "pharmacy.dispense_medication",
        "pharmacy.view_medication", "pharmacy.view_stockbatch",
        "pharmacy.add_stockbatch",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def as_pharmacist(pharmacist):
    return _client_for(pharmacist)


@pytest.fixture
def prescriber(db, facility_a):
    """A doctor who may prescribe past a warning, with a reason."""
    user = User.objects.create_user("prescriber@example.test", "Ada Prescriber", PASSWORD)
    role = _role(
        "Senior Doctor",
        "patients.view_patient", "visits.view_visit",
        "pharmacy.view_prescription", "pharmacy.add_prescription",
        "pharmacy.override_safety_warning", "pharmacy.view_medication",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def junior_prescriber(db, facility_a):
    """May prescribe, but may not override a safety warning."""
    user = User.objects.create_user("junior@example.test", "Ben Junior", PASSWORD)
    role = _role(
        "House Officer",
        "patients.view_patient", "visits.view_visit",
        "pharmacy.view_prescription", "pharmacy.add_prescription",
        "pharmacy.view_medication",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def as_prescriber(prescriber):
    return _client_for(prescriber)


@pytest.fixture
def as_junior(junior_prescriber):
    return _client_for(junior_prescriber)


@pytest.fixture
def amoxicillin_prescription(as_prescriber, open_visit, formulary):
    """15 capsules of amoxicillin, nothing dispensed yet."""
    from django.urls import reverse

    response = as_prescriber.post(
        reverse("prescription-list"),
        {"visit": open_visit.pk, "items": [{
            "medication": formulary["amoxicillin"].pk, "dose": "500", "dose_unit": "mg",
            "route": "oral", "frequency_per_day": 3, "duration_days": 5,
            "quantity_prescribed": 15, "instructions": "After food",
        }]},
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data


# --- billing ---------------------------------------------------------------------

@pytest.fixture
def billing_numbers(db):
    for key, prefix, width in [
        ("invoice_number", "INV", 6),
        ("receipt_number", "RCP", 6),
        ("refund_reference", "REF", 6),
    ]:
        NumberSequence.objects.create(
            key=key, prefix=prefix, include_year=True, width=width
        )


@pytest.fixture
def tariff(db, billing_numbers, facility_a):
    from billing.models import PaymentMethod, Service, ServiceCategory, ServicePrice

    consultations = ServiceCategory.objects.create(name="Consultations", display_order=1)
    laboratory = ServiceCategory.objects.create(name="Laboratory", display_order=2)

    consult = Service.objects.create(
        category=consultations, name="General consultation", code="CONSULT"
    )
    ServicePrice.objects.create(service=consult, facility=facility_a, amount="5000.00")

    fbc_service = Service.objects.create(
        category=laboratory, name="Full blood count", code="LAB-FBC"
    )
    ServicePrice.objects.create(service=fbc_service, facility=facility_a, amount="3500.00")

    cash = PaymentMethod.objects.create(name="Cash", code="CASH")
    transfer = PaymentMethod.objects.create(
        name="Bank transfer", code="TRANSFER", requires_reference=True
    )
    return {"consult": consult, "fbc_service": fbc_service, "cash": cash,
            "transfer": transfer}


@pytest.fixture
def cashier(db, facility_a):
    """Takes payments and small discounts; cannot approve a large one or refund."""
    user = User.objects.create_user("cashier@example.test", "Blessing Uche", PASSWORD)
    role = _role(
        "Cashier",
        "patients.view_patient", "visits.view_visit", "visits.move_queue",
        "billing.view_invoice", "billing.change_invoice",
        "billing.view_payment", "billing.add_payment",
        "billing.view_cashiersession", "billing.add_cashiersession",
        "billing.change_cashiersession",
    )
    role.discount_limit = "500.00"
    role.save(update_fields=["discount_limit"])
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def accountant(db, facility_a):
    """Approves discounts, issues refunds, reconciles the day."""
    user = User.objects.create_user("accounts@example.test", "Femi Accounts", PASSWORD)
    role = _role(
        "Accountant",
        "patients.view_patient", "visits.view_visit",
        "billing.view_invoice", "billing.change_invoice", "billing.approve_discount",
        "billing.void_invoice", "billing.issue_refund",
        "billing.view_payment", "billing.add_payment",
        "billing.view_cashiersession", "billing.add_cashiersession",
        "billing.change_cashiersession", "billing.reconcile_cashiersession",
    )
    role.discount_limit = "100000.00"
    role.save(update_fields=["discount_limit"])
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def as_cashier(cashier):
    return _client_for(cashier)


@pytest.fixture
def as_accountant(accountant):
    return _client_for(accountant)


@pytest.fixture
def cashier_session(as_cashier, facility_a, billing_numbers):
    from django.urls import reverse

    response = as_cashier.post(
        reverse("cashiersession-list"),
        {"facility": facility_a.pk, "opening_float": "2000.00"},
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data


@pytest.fixture
def billed_visit(as_doctor, open_visit, tariff):
    """A finalised consultation, which is what puts a charge on the visit's invoice."""
    from django.urls import reverse

    encounter = as_doctor.post(
        reverse("encounter-list"),
        {"visit": open_visit.pk, "presenting_complaint": "Fever",
         "clinical_notes": "Malaria suspected"},
        format="json",
    ).data
    finalised = as_doctor.post(reverse("encounter-finalise", args=[encounter["id"]]))
    assert finalised.status_code == 200, finalised.data
    from billing.models import Invoice

    return Invoice.objects.get(visit=open_visit)
