from datetime import date

import pytest
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient

from accounts.models import Role, RoleAssignment, User
from facilities.models import Facility, Organization
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
        date_of_birth=date(1991, 4, 17), phone_primary="08031234567",
        facility=facility_a,
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
        "imaging.view_imagingorder", "imaging.add_imagingorder",
        "imaging.view_imagingprocedure", "imaging.view_imagingmodality",
        "imaging.acknowledge_critical_finding",
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
        date_of_birth=date(1991, 4, 17), facility=facility_a,
    )


@pytest.fixture
def male_patient(db, facility_a, hospital_numbers):
    from patients.models import Patient

    return Patient.objects.create(
        given_name="Emeka", family_name="Obi", sex="male",
        date_of_birth=date(1985, 2, 8), facility=facility_a,
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
        ContraindicationRule,
        DoseRange,
        Medication,
        MedicationCategory,
        StockBatch,
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

    accommodation = ServiceCategory.objects.create(name="Accommodation", display_order=3)
    bed_night = Service.objects.create(
        category=accommodation, name="General ward bed night", code="BED-GEN"
    )
    ServicePrice.objects.create(
        service=bed_night, facility=facility_a, amount="12000.00"
    )

    cash = PaymentMethod.objects.create(name="Cash", code="CASH")
    transfer = PaymentMethod.objects.create(
        name="Bank transfer", code="TRANSFER", requires_reference=True
    )
    return {"consult": consult, "fbc_service": fbc_service, "bed_night": bed_night,
            "cash": cash, "transfer": transfer}


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
        "billing.change_cashiersession", "billing.receive_till",
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
        # Writing off what a scheme did not pay is the same class of decision as
        # approving a discount, so it sits with the accountant rather than the
        # billing desk that raised the claim.
        "insurance.view_claimbatch", "insurance.view_providerpayment",
        "insurance.add_providerpayment", "insurance.record_claim_outcome",
        "insurance.write_off_claim_shortfall",
        "billing.view_payment", "billing.add_payment",
        "billing.view_cashiersession", "billing.add_cashiersession",
        "billing.change_cashiersession", "billing.reconcile_cashiersession",
        "billing.adjust_cashiersession",
    )
    role.discount_limit = "100000.00"
    role.save(update_fields=["discount_limit"])
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def relief_cashier(db, cashier, facility_a):
    """The cashier coming on shift. Same role, deliberately a second person."""
    user = User.objects.create_user("relief@example.test", "Ngozi Relief", PASSWORD)
    role = RoleAssignment.objects.get(user=cashier).role
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def as_cashier(cashier):
    return _client_for(cashier)


@pytest.fixture
def as_relief_cashier(relief_cashier):
    return _client_for(relief_cashier)


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
def finalise_invoice(as_cashier):
    """Freeze an invoice through the API, which is where the rule lives.

    Called from tests rather than reaching into the model, so what is exercised
    is the path a cashier actually takes.
    """
    from django.urls import reverse

    def freeze(invoice):
        response = as_cashier.post(reverse("invoice-finalise", args=[invoice.pk]))
        assert response.status_code == 200, response.data
        invoice.refresh_from_db()
        return invoice

    return freeze


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


# --- insurance ---------------------------------------------------------------

@pytest.fixture
def claim_numbers(db):
    NumberSequence.objects.create(
        key="claim_number", prefix="CLM", include_year=True, width=6
    )


@pytest.fixture
def scheme(db, tariff, facility_a, claim_numbers):
    """One HMO with one plan, and rules of every shape.

    Deliberately mixed: a category rule, a service rule that overrides it, an
    exclusion, a co-pay and a service nobody wrote a rule for — because those
    five are the cases a single "percentage covered" column gets wrong.
    """
    from billing.models import Service, ServiceCategory, ServicePrice
    from insurance.models import CoverageRule, InsuranceProvider, Plan

    provider = InsuranceProvider.objects.create(
        name="Hygeia HMO", code="HYG", provider_type=InsuranceProvider.HMO,
        settlement_days=30,
    )
    plan = Plan.objects.create(
        provider=provider, name="Gold", code="GOLD",
        unruled_services=Plan.EXCLUDED, default_scheme_percent="100.00",
    )

    consultations = ServiceCategory.objects.get(name="Consultations")
    laboratory = ServiceCategory.objects.get(name="Laboratory")

    # Consultations at 90% for the category…
    CoverageRule.objects.create(
        plan=plan, category=consultations, basis=CoverageRule.PERCENTAGE,
        scheme_percent="90.00",
    )
    # …but this one consultation in full, to prove the service rule wins.
    CoverageRule.objects.create(
        plan=plan, service=tariff["consult"], basis=CoverageRule.FULL,
    )
    # Laboratory with a flat patient co-pay.
    CoverageRule.objects.create(
        plan=plan, category=laboratory, basis=CoverageRule.FIXED_COPAY,
        patient_copay="500.00",
    )

    cosmetic_category = ServiceCategory.objects.create(
        name="Cosmetic", display_order=8
    )
    cosmetic = Service.objects.create(
        category=cosmetic_category, name="Cosmetic procedure", code="COSM"
    )
    ServicePrice.objects.create(
        service=cosmetic, facility=facility_a, amount="40000.00"
    )
    CoverageRule.objects.create(
        plan=plan, category=cosmetic_category, basis=CoverageRule.EXCLUDED,
        exclusion_reason="Cosmetic procedures are not a scheme benefit",
    )

    # And one service with no rule at all.
    unruled_category = ServiceCategory.objects.create(
        name="Physiotherapy", display_order=9
    )
    unruled = Service.objects.create(
        category=unruled_category, name="Physiotherapy session", code="PHYSIO"
    )
    ServicePrice.objects.create(
        service=unruled, facility=facility_a, amount="7000.00"
    )

    return {"provider": provider, "plan": plan, "cosmetic": cosmetic,
            "unruled": unruled}


@pytest.fixture
def insured_patient(db, patient, scheme, records_officer):
    """A patient holding a policy that is in force today."""
    from datetime import timedelta

    from insurance.models import PatientPolicy

    PatientPolicy.objects.create(
        patient=patient, plan=scheme["plan"], policy_number="HYG/12345",
        starts_on=date.today() - timedelta(days=365),
        ends_on=date.today() + timedelta(days=365),
        recorded_by=records_officer,
    )
    return patient


@pytest.fixture
def billing_officer(db, facility_a):
    """Runs the insurance desk: policies, eligibility, claims, provider money."""
    user = User.objects.create_user("insurance@example.test", "Tolu Billing", PASSWORD)
    role = _role(
        "Billing Officer",
        "patients.view_patient", "visits.view_visit",
        "billing.view_invoice", "billing.change_invoice", "billing.view_service",
        "billing.view_payment", "billing.view_paymentmethod",
        "insurance.view_insuranceprovider", "insurance.add_insuranceprovider",
        "insurance.change_insuranceprovider", "insurance.manage_coverage",
        "insurance.view_plan", "insurance.add_plan", "insurance.change_plan",
        "insurance.view_coveragerule", "insurance.add_coveragerule",
        "insurance.view_patientpolicy", "insurance.add_patientpolicy",
        "insurance.change_patientpolicy",
        "insurance.view_eligibilitycheck", "insurance.verify_eligibility",
        "insurance.view_preauthorisation", "insurance.request_preauthorisation",
        "insurance.view_claimbatch", "insurance.add_claimbatch",
        "insurance.submit_claim", "insurance.record_claim_outcome",
        "insurance.view_providerpayment", "insurance.add_providerpayment",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def as_billing_officer(billing_officer):
    return _client_for(billing_officer)


# --- imaging -----------------------------------------------------------------

@pytest.fixture
def imaging_numbers(db):
    NumberSequence.objects.create(
        key="imaging_order_number", prefix="IMG", include_year=True, width=6
    )


@pytest.fixture
def imaging_catalogue(db, imaging_numbers, facility_a, tariff):
    """A small but realistic catalogue.

    A chest X-ray because it is the commonest request in a Nigerian hospital,
    and a contrast CT because contrast, contraindications and preparation are
    the fields a single "test name" column gets wrong.
    """
    from billing.models import Service, ServiceCategory, ServicePrice
    from imaging.models import ImagingModality, ImagingProcedure

    radiology = ServiceCategory.objects.create(name="Radiology", display_order=4)

    xray = ImagingModality.objects.create(name="X-ray", code="CR", display_order=1)
    ct = ImagingModality.objects.create(name="CT", code="CT", display_order=3)

    cxr_service = Service.objects.create(
        category=radiology, name="Chest X-ray", code="IMG-CXR"
    )
    ServicePrice.objects.create(
        service=cxr_service, facility=facility_a, amount="8000.00"
    )
    cxr = ImagingProcedure.objects.create(
        modality=xray, name="Chest X-ray, PA", code_short="CXR",
        body_part="Chest", service=cxr_service, typical_minutes=10,
        code_system="LOINC", code="36643-5", code_display="XR Chest PA",
    )

    ct_service = Service.objects.create(
        category=radiology, name="CT abdomen with contrast", code="IMG-CTA"
    )
    ServicePrice.objects.create(
        service=ct_service, facility=facility_a, amount="95000.00"
    )
    ct_abdomen = ImagingProcedure.objects.create(
        modality=ct, name="CT abdomen and pelvis with contrast",
        code_short="CTAP", body_part="Abdomen and pelvis", service=ct_service,
        typical_minutes=30, requires_contrast=True,
        preparation_instructions="Nil by mouth for 6 hours. Cannulate before arrival.",
        contraindications="Renal impairment, contrast allergy, pregnancy",
    )

    ultrasound = ImagingModality.objects.create(
        name="Ultrasound", code="US", display_order=2
    )
    usg = ImagingProcedure.objects.create(
        modality=ultrasound, name="Abdominal ultrasound", code_short="USG-ABD",
        body_part="Abdomen",
        preparation_instructions="Full bladder. Nil by mouth for 4 hours.",
    )

    return {"xray": xray, "ct": ct, "ultrasound": ultrasound,
            "cxr": cxr, "ct_abdomen": ct_abdomen, "usg": usg,
            "radiology_category": radiology}


@pytest.fixture
def radiographer(db, facility_a):
    """Schedules and performs examinations. Does not report them."""
    user = User.objects.create_user("radiog@example.test", "Yemi Radiographer", PASSWORD)
    role = _role(
        "Radiographer",
        "patients.view_patient", "visits.view_visit",
        "imaging.view_imagingorder", "imaging.view_imagingprocedure",
        "imaging.view_imagingmodality",
        "imaging.schedule_imaging", "imaging.perform_imaging",
        "imaging.change_imagingorderitem",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def radiologist(db, facility_a):
    """Reports, verifies and amends."""
    user = User.objects.create_user("radiol@example.test", "Tayo Radiologist", PASSWORD)
    role = _role(
        "Radiologist",
        "patients.view_patient", "visits.view_visit",
        "imaging.view_imagingorder", "imaging.view_imagingprocedure",
        "imaging.add_imagingreport", "imaging.verify_imagingreport",
        "imaging.amend_imagingreport",
        "imaging.perform_imaging",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def imaging_registrar(db, facility_a):
    """Writes reports but cannot sign them off — the separation AC-96 turns on."""
    user = User.objects.create_user("imgreg@example.test", "Uche Registrar", PASSWORD)
    role = _role(
        "Imaging Registrar",
        "patients.view_patient",
        "imaging.view_imagingorder", "imaging.add_imagingreport",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def as_radiographer(radiographer):
    return _client_for(radiographer)


@pytest.fixture
def as_radiologist(radiologist):
    return _client_for(radiologist)


@pytest.fixture
def as_imaging_registrar(imaging_registrar):
    return _client_for(imaging_registrar)


@pytest.fixture
def imaging_admin(db, facility_a):
    """Maintains the catalogue."""
    user = User.objects.create_user("imgadmin@example.test", "Bisi Admin", PASSWORD)
    role = _role(
        "Imaging Administrator",
        "imaging.view_imagingmodality", "imaging.add_imagingmodality",
        "imaging.change_imagingmodality",
        "imaging.view_imagingprocedure", "imaging.add_imagingprocedure",
        "imaging.change_imagingprocedure",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def as_imaging_admin(imaging_admin):
    return _client_for(imaging_admin)


@pytest.fixture
def cxr_order(as_doctor, open_visit, imaging_catalogue, facility_a):
    """A requested chest X-ray, not yet scheduled."""
    from django.urls import reverse

    response = as_doctor.post(
        reverse("imagingorder-list"),
        {"visit": open_visit.pk, "priority": "urgent",
         "clinical_question": "Pneumothorax after central line insertion?",
         "relevant_history": "Right subclavian line sited 30 minutes ago",
         "procedures": [imaging_catalogue["cxr"].pk]},
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data


# --- inpatient ---------------------------------------------------------------

@pytest.fixture
def inpatient_numbers(db):
    NumberSequence.objects.create(
        key="admission_number", prefix="ADM", include_year=True, width=6
    )


@pytest.fixture
def ward(db, facility_a):
    """A small ward: two rooms, four beds."""
    from inpatient.models import Bed, Room, Ward

    ward = Ward.objects.create(
        facility=facility_a, name="Male Medical Ward", code="MMW",
        ward_type=Ward.MALE,
    )
    for room_code in ("R1", "R2"):
        room = Room.objects.create(ward=ward, name=f"Room {room_code}", code=room_code)
        for bed_code in ("A", "B"):
            Bed.objects.create(room=room, code=bed_code)
    return ward


@pytest.fixture
def beds(ward):
    from inpatient.models import Bed

    return list(Bed.objects.filter(room__ward=ward).order_by("room__code", "code"))


@pytest.fixture
def ward_doctor(db, facility_a):
    """Requests admissions, admits, transfers, plans and completes discharge."""
    user = User.objects.create_user("ward@example.test", "Kola Ward", PASSWORD)
    role = _role(
        "Ward Doctor",
        "patients.view_patient",
        "visits.view_visit", "visits.move_queue",
        "clinical.view_encounter", "clinical.add_encounter",
        "clinical.change_encounter", "clinical.finalise_encounter",
        "clinical.amend_encounter", "clinical.view_vitalsigns",
        "inpatient.view_ward", "inpatient.view_bed", "inpatient.view_bedoccupancy",
        "inpatient.view_admissionrequest", "inpatient.add_admissionrequest",
        "inpatient.decide_admissionrequest",
        "inpatient.view_admission", "inpatient.admit_patient",
        "inpatient.transfer_patient", "inpatient.plan_discharge",
        "inpatient.discharge_patient",
        "inpatient.view_nursingassessment", "inpatient.view_nursingnote",
        "inpatient.add_nursingnote", "inpatient.view_fluidbalanceentry",
        "inpatient.view_escalation", "inpatient.escalate_observation",
        "inpatient.view_scheduleddose", "inpatient.add_scheduleddose",
        "inpatient.change_scheduleddose",
        "inpatient.view_medicationadministration",
        "pharmacy.view_prescription", "pharmacy.add_prescription",
        "pharmacy.view_medication", "pharmacy.view_stockbatch",
        # Orders bloods and reads the report; does not enter or sign results.
        "laboratory.view_laborder", "laboratory.add_laborder",
        "laboratory.view_labtest", "laboratory.acknowledge_critical_result",
        "imaging.view_imagingorder", "imaging.add_imagingorder",
        "imaging.view_imagingprocedure",
        "imaging.acknowledge_critical_finding",
        "billing.view_invoice",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def ward_nurse(db, facility_a):
    """Records observations and gives medication; cannot admit or discharge."""
    user = User.objects.create_user("wardnurse@example.test", "Amaka Nurse", PASSWORD)
    role = _role(
        "Ward Nurse",
        "patients.view_patient",
        "clinical.view_encounter", "clinical.view_vitalsigns",
        "clinical.add_vitalsigns", "clinical.change_vitalsigns",
        "inpatient.view_ward", "inpatient.view_bed", "inpatient.manage_beds",
        "inpatient.view_bedoccupancy", "inpatient.view_admission",
        "inpatient.view_nursingassessment", "inpatient.add_nursingassessment",
        "inpatient.view_nursingnote", "inpatient.add_nursingnote",
        "inpatient.view_fluidbalanceentry", "inpatient.add_fluidbalanceentry",
        "inpatient.view_escalation",
        "inpatient.view_escalationthreshold",
        # Gives medication, and cannot prescribe or discontinue one.
        "inpatient.view_scheduleddose",
        "inpatient.view_medicationadministration",
        "inpatient.add_medicationadministration",
        "pharmacy.view_medication", "pharmacy.view_stockbatch",
        "pharmacy.view_prescription",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def ward_manager(db, facility_a):
    """Runs the ward. The only role that can discharge past an unsettled bill,
    and doing so is recorded as an exception rather than as a discharge."""
    user = User.objects.create_user("wardmgr@example.test", "Ngozi Manager", PASSWORD)
    role = _role(
        "Ward Manager",
        "patients.view_patient",
        "clinical.view_encounter", "clinical.view_vitalsigns",
        "inpatient.view_ward", "inpatient.change_ward", "inpatient.view_bed",
        "inpatient.manage_beds", "inpatient.view_bedoccupancy",
        "inpatient.view_escalationthreshold", "inpatient.add_escalationthreshold",
        "inpatient.change_escalationthreshold",
        "inpatient.view_admissionrequest", "inpatient.decide_admissionrequest",
        "inpatient.view_admission", "inpatient.admit_patient",
        "inpatient.transfer_patient", "inpatient.plan_discharge",
        "inpatient.discharge_patient", "inpatient.override_discharge_billing",
        "inpatient.view_nursingassessment", "inpatient.view_nursingnote",
        "inpatient.view_fluidbalanceentry",
        "inpatient.view_escalation", "inpatient.escalate_observation",
        "inpatient.view_scheduleddose", "inpatient.view_medicationadministration",
        "billing.view_invoice",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def as_ward_manager(ward_manager):
    return _client_for(ward_manager)


@pytest.fixture
def as_ward_doctor(ward_doctor):
    return _client_for(ward_doctor)


@pytest.fixture
def as_ward_nurse(ward_nurse):
    return _client_for(ward_nurse)


@pytest.fixture
def admission(db, patient, facility_a, ward, beds, ward_doctor, inpatient_numbers):
    """An admitted patient in the first bed."""
    from inpatient.models import Admission, BedOccupancy

    record = Admission.objects.create(
        patient=patient, facility=facility_a,
        admission_reason="Uncontrolled hypertension",
        admission_diagnosis="Hypertensive urgency",
        responsible_consultant=ward_doctor, admitted_by=ward_doctor,
    )
    BedOccupancy.allocate(bed=beds[0], admission=record, actor=ward_doctor)
    return record


@pytest.fixture
def inpatient_prescription(db, admission, formulary, ward_doctor):
    """Amoxicillin three times a day for five days, on the ward."""
    from pharmacy.models import Prescription, PrescriptionItem

    prescription = Prescription.objects.create(
        admission=admission, visit=None, patient=admission.patient,
        facility=admission.facility, prescribed_by=ward_doctor,
    )
    item = PrescriptionItem.objects.create(
        prescription=prescription, medication=formulary["amoxicillin"],
        dose="500", dose_unit="mg", route="oral", frequency_per_day=3,
        duration_days=5, quantity_prescribed=15, instructions="After food",
    )
    return item


@pytest.fixture
def drug_chart(inpatient_prescription, admission, ward_doctor):
    """A scheduled course, ready to be given.

    Anchored to the next midnight rather than to "now" so the chart is the same
    fifteen doses whatever time of day the suite runs. Left on `now`, the count
    depended on how many of today's rounds had already passed, and the test
    failed only when run after the evening round — a test that fails by the
    clock is worse than no test.
    """
    from datetime import datetime, time, timedelta

    from django.utils import timezone

    from inpatient.services import schedule_doses

    tomorrow = (timezone.localtime() + timedelta(days=1)).date()
    start = timezone.make_aware(
        datetime.combine(tomorrow, time(hour=0, minute=1)),
        timezone.get_current_timezone(),
    )
    return schedule_doses(
        prescription_item=inpatient_prescription, admission=admission,
        actor=ward_doctor, start=start,
    )


# --- stores and stock -------------------------------------------------------

@pytest.fixture
def stores(db, facility_a, facility_b):
    from decimal import Decimal

    from inventory.models import Store

    # Decimal, not a string: a string assigned to a DecimalField stays a string
    # on the in-memory instance, and the comparison against it raises rather
    # than failing an assertion, which reads like a code defect and is not one.
    return {
        "main": Store.objects.create(
            facility=facility_a, name="Main store", code="MAIN-ST",
            kind=Store.MAIN, adjustment_authorisation_limit=Decimal("10000.00"),
        ),
        "theatre": Store.objects.create(
            facility=facility_a, name="Theatre store", code="THEATRE-ST",
            kind=Store.THEATRE, adjustment_authorisation_limit=Decimal("0.00"),
        ),
        "other_facility": Store.objects.create(
            facility=facility_b, name="Abuja main store", code="MAIN-ST",
            kind=Store.MAIN,
        ),
    }


@pytest.fixture
def stock_items(db):
    from inventory.models import InventoryItem, ItemCategory

    consumables = ItemCategory.objects.create(name="Consumables", display_order=1)
    equipment = ItemCategory.objects.create(name="Equipment", display_order=2)
    return {
        "gloves": InventoryItem.objects.create(
            category=consumables, name="Examination gloves, medium",
            code="GLV-M", unit_of_issue="box of 100", default_reorder_level=20,
        ),
        "spirit": InventoryItem.objects.create(
            category=consumables, name="Methylated spirit 500 mL",
            code="SPT-500", unit_of_issue="bottle", default_reorder_level=10,
            is_controlled=True,
        ),
        "bedpan": InventoryItem.objects.create(
            category=equipment, name="Bed pan, stainless", code="BDP-1",
            unit_of_issue="each", default_reorder_level=4, tracks_expiry=False,
        ),
    }


@pytest.fixture
def gloves_in_main(stores, stock_items, storekeeper):
    """A stocked record with two lots, the older expiring first."""
    from datetime import timedelta
    from decimal import Decimal

    from django.utils import timezone

    from inventory.models import StockRecord
    from inventory.stock import receive

    record = StockRecord.objects.create(
        store=stores["main"], item=stock_items["gloves"], reorder_level=20
    )
    today = timezone.localdate()
    receive(record=record, quantity=30, actor=storekeeper, lot_number="L-OLD",
            expiry_date=today + timedelta(days=45), unit_cost=Decimal("1500.00"))
    receive(record=record, quantity=50, actor=storekeeper, lot_number="L-NEW",
            expiry_date=today + timedelta(days=400), unit_cost=Decimal("1600.00"))
    return record


@pytest.fixture
def storekeeper(db, facility_a):
    """Runs the store: receives, issues, transfers, adjusts. Cannot authorise."""
    user = User.objects.create_user("stores@example.test", "Danladi Musa", PASSWORD)
    role = _role(
        "Storekeeper",
        "facilities.view_facility",
        "inventory.view_store", "inventory.view_inventoryitem",
        "inventory.view_itemcategory", "inventory.view_stockrecord",
        "inventory.view_stocklot", "inventory.view_stockmovement",
        "inventory.view_stockadjustment", "inventory.view_stocktransfer",
        "inventory.receive_stock", "inventory.issue_stock",
        "inventory.transfer_stock", "inventory.adjust_stock",
        "inventory.add_stockrecord", "inventory.change_stockrecord",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def stores_manager(db, facility_a):
    """Authorises what the storekeeper cannot authorise for themselves."""
    user = User.objects.create_user("storesmgr@example.test", "Halima Yusuf", PASSWORD)
    role = _role(
        "Stores Manager",
        "facilities.view_facility",
        "inventory.view_store", "inventory.add_store", "inventory.change_store",
        "inventory.view_inventoryitem", "inventory.add_inventoryitem",
        "inventory.change_inventoryitem",
        "inventory.view_itemcategory", "inventory.add_itemcategory",
        "inventory.view_stockrecord", "inventory.add_stockrecord",
        "inventory.change_stockrecord",
        "inventory.view_stocklot", "inventory.view_stockmovement",
        "inventory.view_stockadjustment", "inventory.view_stocktransfer",
        "inventory.receive_stock", "inventory.issue_stock",
        "inventory.transfer_stock", "inventory.adjust_stock",
        "inventory.authorise_stock_adjustment",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def as_storekeeper(storekeeper):
    return _client_for(storekeeper)


@pytest.fixture
def as_stores_manager(stores_manager):
    return _client_for(stores_manager)


# --- procurement ------------------------------------------------------------

@pytest.fixture
def supplier(db):
    from inventory.models import Supplier

    return Supplier.objects.create(
        name="Lagos Medical Supplies", code="LMS",
        contact_name="Bode Adeyinka", phone="+234 802 000 0000",
        payment_terms_days=30,
    )


@pytest.fixture
def suspended_supplier(db):
    from inventory.models import Supplier

    return Supplier.objects.create(
        name="Cheap Imports Ltd", code="CIL", is_approved=False,
        approval_note="Two deliveries of expired stock in 2026.",
    )


@pytest.fixture
def purchase_buyer(db, facility_a):
    """Raises orders and receives goods. Cannot approve a request."""
    user = User.objects.create_user("buyer@example.test", "Chika Eze", PASSWORD)
    # Spelled out rather than wildcarded: a test role should say exactly what it
    # holds, or a permission test proves less than it looks like it does.
    role = _role(
        "Buyer",
        "facilities.view_facility",
        "inventory.view_store", "inventory.view_inventoryitem",
        "inventory.view_stockrecord", "inventory.view_stocklot",
        "inventory.view_stockmovement",
        "inventory.view_supplier",
        "inventory.view_purchaserequest", "inventory.view_purchaserequestline",
        "inventory.view_purchaseorder", "inventory.view_purchaseorderline",
        "inventory.view_goodsreceipt", "inventory.view_goodsreceiptline",
        "inventory.view_supplierinvoice",
        "inventory.add_purchaserequest", "inventory.change_purchaserequest",
        "inventory.add_purchaserequestline",
        "inventory.raise_purchase_order", "inventory.receive_goods",
        "inventory.add_supplierinvoice",
        "inventory.receive_stock", "inventory.add_stockrecord",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def purchase_approver(db, facility_a):
    """Approves requests and releases supplier invoices for payment."""
    user = User.objects.create_user("approver@example.test", "Bola Sanni", PASSWORD)
    role = _role(
        "Purchasing Approver",
        "facilities.view_facility",
        "inventory.view_store", "inventory.view_inventoryitem",
        "inventory.view_stockrecord", "inventory.view_stockmovement",
        "inventory.view_supplier",
        "inventory.view_purchaserequest", "inventory.view_purchaserequestline",
        "inventory.view_purchaseorder", "inventory.view_purchaseorderline",
        "inventory.view_goodsreceipt", "inventory.view_supplierinvoice",
        "inventory.approve_purchase_request",
        "inventory.approve_supplier_invoice",
        "inventory.add_supplier", "inventory.change_supplier",
        # Deliberately not raise_purchase_order or receive_goods: approving the
        # spend and committing it are different jobs.
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def as_buyer(purchase_buyer):
    return _client_for(purchase_buyer)


@pytest.fixture
def as_approver(purchase_approver):
    return _client_for(purchase_approver)


@pytest.fixture
def purchase_request(db, stores, stock_items, purchase_buyer):
    """A request worth more than the main store's authorisation limit."""
    from inventory.procurement import new_request

    return new_request(
        store=stores["main"],
        justification="Theatre list next week and the shelf is empty.",
        actor=purchase_buyer,
        lines=[
            {"item": stock_items["gloves"], "quantity": 100, "cost": "1500.00"},
            {"item": stock_items["spirit"], "quantity": 40, "cost": "800.00"},
        ],
    )
