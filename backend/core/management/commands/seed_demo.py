"""Synthetic demo hospital: configuration, catalogues, stock and staff.

Never real patient data. Idempotent, so it can be re-run. Refuses to run with DEBUG off
unless forced, so it cannot quietly seed a live deployment.

Run `seed_demo` for the configured hospital, then `demo_day` to walk patients through it.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Role, RoleAssignment, User
from billing.models import PaymentMethod, Service, ServiceCategory, ServicePrice
from facilities.models import Clinic, Department, Facility, Organization
from imaging.models import ImagingModality, ImagingProcedure
from inpatient.models import Bed, EscalationThreshold, Room, Ward
from laboratory.models import LabTest, LabTestCategory, LabTestParameter, ReferenceRange
from patients.models import NumberSequence
from pharmacy.models import (
    ContraindicationRule,
    DoseRange,
    Medication,
    MedicationCategory,
    StockBatch,
    StockMovement,
)

DEMO_PASSWORD = "demo-password-not-for-real-use"

SEQUENCES = [
    ("hospital_number", "ILS", True, 5),
    ("visit_number", "V", True, 6),
    ("lab_order_number", "LAB", True, 6),
    ("specimen_id", "SPC", False, 7),
    ("prescription_number", "RX", True, 6),
    ("invoice_number", "INV", True, 6),
    ("receipt_number", "RCP", True, 6),
    ("refund_reference", "REF", True, 6),
    ("admission_number", "ADM", True, 6),
    ("imaging_order_number", "IMG", True, 6),
    ("claim_number", "CLM", True, 6),
]

FACILITIES = [
    ("Ilesa General Hospital", "MAIN", "Africa/Lagos"),
    ("Ikeja Branch Clinic", "IKJ", "Africa/Lagos"),
]

DEPARTMENTS = [
    ("General Outpatient", "GOPD", ["Morning Clinic", "Afternoon Clinic"]),
    ("Internal Medicine", "MED", ["Consultant Clinic"]),
    ("Paediatrics", "PAED", ["Children's Clinic"]),
    ("Laboratory", "LAB", []),
    ("Radiology", "RAD", []),
    ("Pharmacy", "PHA", []),
    ("Billing", "BIL", []),
    ("Inpatient", "WARD", []),
]

# Wards, and the beds in them. Four beds to a room, which is how a Nigerian
# general ward is laid out.
WARDS = [
    ("Male Medical Ward", "MMW", "male", "BED-GEN", ["R1", "R2", "R3"], 4),
    ("Female Medical Ward", "FMW", "female", "BED-GEN", ["R1", "R2", "R3"], 4),
    ("Children's Ward", "CW", "paediatric", "BED-GEN", ["R1", "R2"], 4),
    ("Intensive Care Unit", "ICU", "intensive", "BED-ICU", ["B1"], 4),
]

# When an observation on a ward has to be escalated. Per ward, because the same
# figure means different things in intensive care and on a general ward.
ESCALATION_THRESHOLDS = {
    "default": [
        ("systolic_bp", 90, 180, "Tell the registrar and repeat in 15 minutes"),
        ("pulse_bpm", 50, 120, "Repeat manually and tell the nurse in charge"),
        ("respiratory_rate", 10, 24, "Sit the patient up, check saturations, call the doctor"),
        ("oxygen_saturation", 92, None, "Start oxygen and call the doctor"),
        ("temperature_c", None, "38.5", "Take blood cultures before antibiotics"),
    ],
    # Tighter bounds in intensive care: the same reading there means something
    # different, and a single hospital-wide threshold would either cry wolf or
    # stay silent.
    "ICU": [
        ("systolic_bp", 100, 160, "Tell the intensivist now"),
        ("pulse_bpm", 55, 110, "Tell the intensivist now"),
        ("oxygen_saturation", 94, None, "Increase FiO2 and tell the intensivist"),
        ("temperature_c", "35.5", "38.0", "Active warming or cooling per protocol"),
    ],
}

# The imaging catalogue: modality, body part, preparation and price.
MODALITIES = [
    ("X-ray", "CR", 1),
    ("Ultrasound", "US", 2),
    ("CT", "CT", 3),
]

IMAGING_PROCEDURES = [
    ("CR", "Chest X-ray, PA", "CXR", "Chest", "IMG-CXR", 10, False, "", "",
     "LOINC", "36643-5"),
    ("CR", "Abdominal X-ray, supine", "AXR", "Abdomen", "IMG-AXR", 10, False, "", "",
     "LOINC", "74212-6"),
    ("CR", "Pelvis X-ray, AP", "XR-PELV", "Pelvis", "IMG-XRP", 10, False,
     "Remove metal from pockets.", "", "", ""),
    ("US", "Abdominal ultrasound", "USG-ABD", "Abdomen", "IMG-USG", 20, False,
     "Nil by mouth for 4 hours. Full bladder.", "", "LOINC", "24851-3"),
    ("US", "Obstetric ultrasound", "USG-OBS", "Pelvis", "IMG-USO", 20, False,
     "Full bladder.", "", "", ""),
    ("CT", "CT head, non-contrast", "CT-HEAD", "Head", "IMG-CTH", 15, False,
     "Remove hairpins and earrings.", "Pregnancy", "LOINC", "24725-9"),
    ("CT", "CT abdomen and pelvis with contrast", "CTAP", "Abdomen and pelvis",
     "IMG-CTAP", 30, True,
     "Nil by mouth for 6 hours. Cannulate before arrival.",
     "Renal impairment, contrast allergy, pregnancy", "", ""),
]

# Permission sets per role. Everything is a database row; nothing branches on a name.
ROLES = {
    "Hospital Administrator": {
        "discount_limit": "100000.00",
        "permissions": [
            "facilities.*",
            # Configuration: roles, staff access, identifier formats.
            "accounts.*",
            "patients.view_patient", "patients.view_patient_access_log",
            "patients.view_numbersequence", "patients.change_numbersequence",
            "visits.view_visit", "clinical.view_encounter", "clinical.view_vitalsigns",
            "laboratory.view_laborder", "laboratory.*_labtest*",
            "pharmacy.view_medication", "pharmacy.*_medication*", "billing.*",
            # The log is a privacy surface in its own right, so it is granted
            # explicitly rather than swept in by a wildcard.
            "audit.view_auditevent",
        ],
    },
    "Medical Records Officer": {
        "permissions": [
            "facilities.view_facility", "patients.*", "visits.view_visit",
            "clinical.view_encounter", "audit.view_auditevent",
        ],
    },
    "Receptionist": {
        "permissions": [
            "facilities.view_facility",
            "patients.view_patient", "patients.add_patient", "patients.change_patient",
            "visits.view_visit", "visits.add_visit", "visits.change_visit",
            "visits.check_in_patient", "visits.move_queue",
            "billing.view_invoice",
        ],
    },
    "Nurse": {
        "permissions": [
            "facilities.view_facility", "patients.view_patient",
            "visits.view_visit", "visits.move_queue",
            "clinical.view_encounter",
            "clinical.view_vitalsigns", "clinical.add_vitalsigns",
            "clinical.change_vitalsigns",
        ],
    },
    "Doctor": {
        "permissions": [
            "facilities.view_facility", "patients.view_patient",
            "visits.view_visit", "visits.move_queue",
            "clinical.*", "laboratory.view_laborder", "laboratory.add_laborder",
            "laboratory.view_labtest", "laboratory.acknowledge_critical_result",
            "pharmacy.view_prescription", "pharmacy.add_prescription",
            "pharmacy.view_medication", "billing.view_invoice",
        ],
    },
    "Consultant": {
        "discount_limit": "0.00",
        "permissions": [
            "facilities.view_facility", "patients.view_patient",
            "visits.view_visit", "visits.move_queue", "clinical.*",
            "laboratory.view_laborder", "laboratory.add_laborder",
            "laboratory.acknowledge_critical_result",
            "pharmacy.view_prescription", "pharmacy.add_prescription",
            "pharmacy.override_safety_warning", "pharmacy.view_medication",
        ],
    },
    "Laboratory Scientist": {
        "permissions": [
            "facilities.view_facility", "patients.view_patient", "visits.view_visit",
            "laboratory.view_laborder", "laboratory.view_labtest",
            "laboratory.collect_specimen", "laboratory.add_labresult",
            "laboratory.verify_labresult", "laboratory.amend_labresult",
            "laboratory.change_laborderitem",
        ],
    },
    "Laboratory Technician": {
        "permissions": [
            "facilities.view_facility", "patients.view_patient", "visits.view_visit",
            "laboratory.view_laborder", "laboratory.collect_specimen",
            "laboratory.add_labresult",
        ],
    },
    "Pharmacist": {
        "permissions": [
            "facilities.view_facility", "patients.view_patient",
            "visits.view_visit", "visits.move_queue",
            "pharmacy.view_prescription", "pharmacy.dispense_medication",
            "pharmacy.view_medication", "pharmacy.view_stockbatch",
            "pharmacy.add_stockbatch",
        ],
    },
    "Cashier": {
        "discount_limit": "500.00",
        "permissions": [
            "facilities.view_facility", "patients.view_patient",
            "visits.view_visit", "visits.move_queue",
            "billing.view_invoice", "billing.change_invoice",
            "billing.view_payment", "billing.add_payment",
            "billing.view_cashiersession", "billing.add_cashiersession",
            "billing.change_cashiersession", "billing.view_paymentmethod",
        ],
    },
    "Accountant": {
        "discount_limit": "100000.00",
        "permissions": [
            "facilities.view_facility", "patients.view_patient", "visits.view_visit",
            "billing.*",
        ],
    },
    # --- inpatient ------------------------------------------------------------
    "Ward Nurse": {
        "permissions": [
            "facilities.view_facility", "patients.view_patient",
            "clinical.view_encounter", "clinical.view_vitalsigns",
            "clinical.add_vitalsigns", "clinical.change_vitalsigns",
            "inpatient.view_ward", "inpatient.view_room", "inpatient.view_bed",
            "inpatient.manage_beds", "inpatient.view_bedoccupancy",
            "inpatient.view_escalationthreshold",
            "inpatient.view_admission",
            "inpatient.view_nursingassessment", "inpatient.add_nursingassessment",
            "inpatient.view_nursingnote", "inpatient.add_nursingnote",
            "inpatient.view_fluidbalanceentry", "inpatient.add_fluidbalanceentry",
            "inpatient.view_escalation",
            # Gives medication; cannot prescribe or stop it.
            "inpatient.view_scheduleddose",
            "inpatient.view_medicationadministration",
            "inpatient.add_medicationadministration",
            "pharmacy.view_prescription", "pharmacy.view_medication",
            "pharmacy.view_stockbatch",
            "imaging.view_imagingorder",
        ],
    },
    "Ward Doctor": {
        "permissions": [
            "facilities.view_facility", "patients.view_patient",
            "visits.view_visit", "visits.move_queue",
            "clinical.*",
            "inpatient.view_ward", "inpatient.view_room", "inpatient.view_bed",
            "inpatient.view_bedoccupancy", "inpatient.view_escalationthreshold",
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
            "laboratory.view_laborder", "laboratory.add_laborder",
            "laboratory.view_labtest", "laboratory.acknowledge_critical_result",
            "imaging.view_imagingorder", "imaging.add_imagingorder",
            "imaging.view_imagingprocedure", "imaging.view_imagingmodality",
            "imaging.acknowledge_critical_finding",
            "pharmacy.view_prescription", "pharmacy.add_prescription",
            "pharmacy.view_medication", "pharmacy.view_stockbatch",
            "billing.view_invoice",
        ],
    },
    "Ward Manager": {
        "permissions": [
            "facilities.view_facility", "patients.view_patient",
            "clinical.view_encounter", "clinical.view_vitalsigns",
            "inpatient.*",
            "laboratory.view_laborder", "imaging.view_imagingorder",
            "pharmacy.view_prescription",
            "billing.view_invoice",
        ],
    },
    # --- radiology ------------------------------------------------------------
    "Radiographer": {
        "permissions": [
            "facilities.view_facility", "patients.view_patient", "visits.view_visit",
            "imaging.view_imagingorder", "imaging.view_imagingprocedure",
            "imaging.view_imagingmodality",
            "imaging.schedule_imaging", "imaging.perform_imaging",
            "imaging.change_imagingorderitem",
            "inpatient.view_admission",
        ],
    },
    "Radiologist": {
        "permissions": [
            "facilities.view_facility", "patients.view_patient", "visits.view_visit",
            "imaging.view_imagingorder", "imaging.view_imagingprocedure",
            "imaging.view_imagingmodality", "imaging.perform_imaging",
            "imaging.add_imagingreport", "imaging.verify_imagingreport",
            "imaging.amend_imagingreport",
            "inpatient.view_admission",
        ],
    },
    "Imaging Registrar": {
        "permissions": [
            "facilities.view_facility", "patients.view_patient",
            "imaging.view_imagingorder", "imaging.view_imagingprocedure",
            # Writes reports; cannot release them. The separation AC-96 turns on.
            "imaging.add_imagingreport",
        ],
    },
}

STAFF = [
    ("admin@demo.test", "Adaeze Okonkwo", "Hospital Administrator", None),
    ("records@demo.test", "Segun Adewale", "Medical Records Officer", "MAIN"),
    ("reception@demo.test", "Ngozi Eze", "Receptionist", "MAIN"),
    ("nurse@demo.test", "Fatima Bello", "Nurse", "MAIN"),
    ("doctor@demo.test", "Chukwuma Nwosu", "Doctor", "MAIN"),
    ("consultant@demo.test", "Olusegun Ayodele", "Consultant", "MAIN"),
    ("lab@demo.test", "Ibrahim Sani", "Laboratory Scientist", "MAIN"),
    ("labtech@demo.test", "Grace Ojo", "Laboratory Technician", "MAIN"),
    ("pharmacist@demo.test", "Yemi Adeyemi", "Pharmacist", "MAIN"),
    ("cashier@demo.test", "Blessing Uche", "Cashier", "MAIN"),
    ("accounts@demo.test", "Femi Balogun", "Accountant", "MAIN"),
    ("wardnurse@demo.test", "Amaka Nwachukwu", "Ward Nurse", "MAIN"),
    ("warddoctor@demo.test", "Kolawole Ajayi", "Ward Doctor", "MAIN"),
    ("wardmanager@demo.test", "Ngozi Okafor", "Ward Manager", "MAIN"),
    ("radiographer@demo.test", "Yemisi Oladele", "Radiographer", "MAIN"),
    ("radiologist@demo.test", "Tayo Bankole", "Radiologist", "MAIN"),
    ("imgregistrar@demo.test", "Uchenna Obi", "Imaging Registrar", "MAIN"),
]

SERVICES = [
    ("Consultations", 1, [
        ("General consultation", "CONSULT", "5000.00"),
        ("Consultant review", "CONSULT-SP", "12000.00"),
        ("Registration", "REG", "1000.00"),
    ]),
    ("Laboratory", 2, [
        ("Full blood count", "LAB-FBC", "3500.00"),
        ("Malaria parasites", "LAB-MP", "1500.00"),
        ("Fasting blood glucose", "LAB-FBS", "2000.00"),
        ("Urinalysis", "LAB-URIN", "2500.00"),
    ]),
    ("Procedures", 3, [
        ("Wound dressing", "PROC-DRESS", "3000.00"),
        ("Intramuscular injection", "PROC-IM", "1000.00"),
    ]),
    ("Radiology", 4, [
        ("Chest X-ray", "IMG-CXR", "8000.00"),
        ("Abdominal X-ray", "IMG-AXR", "8000.00"),
        ("Pelvis X-ray", "IMG-XRP", "8000.00"),
        ("Abdominal ultrasound", "IMG-USG", "12000.00"),
        ("Obstetric ultrasound", "IMG-USO", "12000.00"),
        ("CT head", "IMG-CTH", "65000.00"),
        ("CT abdomen and pelvis with contrast", "IMG-CTAP", "95000.00"),
    ]),
    # Bed nights are billed through the ordinary service machinery, so a ward's
    # rate is per facility and a change to it is audited like any other price.
    ("Accommodation", 5, [
        ("General ward bed night", "BED-GEN", "12000.00"),
        ("Intensive care bed night", "BED-ICU", "85000.00"),
    ]),
]

PAYMENT_METHODS = [
    ("Cash", "CASH", False),
    ("POS / card", "POS", True),
    ("Bank transfer", "TRANSFER", True),
]

LAB_TESTS = [
    {
        "category": "Haematology", "name": "Full blood count", "code": "FBC",
        "service": "LAB-FBC", "specimen": "blood", "requirements": "EDTA bottle, 3 mL",
        "loinc": "58410-2",
        "parameters": [
            ("Haemoglobin", "g/dL", 1, "718-7", [
                ("female", None, None, 12, 16, 7, 20),
                ("male", None, None, 13, 17, 7, 20),
                ("any", 0, 1, 14, 22, 9, 24),
            ]),
            ("White cell count", "×10⁹/L", 1, "6690-2", [
                ("any", None, None, 4, 11, 1, 50),
            ]),
            ("Platelets", "×10⁹/L", 0, "777-3", [
                ("any", None, None, 150, 400, 20, 1000),
            ]),
            ("Haematocrit", "%", 1, "4544-3", [
                ("female", None, None, 36, 46, 20, None),
                ("male", None, None, 40, 50, 20, None),
            ]),
        ],
    },
    {
        "category": "Haematology", "name": "Malaria parasites", "code": "MP",
        "service": "LAB-MP", "specimen": "blood", "requirements": "Thick and thin film",
        "parameters": [("Malaria parasites", "", 0, None, [])],
        "choice": "Positive,Negative",
    },
    {
        "category": "Chemistry", "name": "Fasting blood glucose", "code": "FBS",
        "service": "LAB-FBS", "specimen": "blood",
        "requirements": "Fluoride oxalate; fasting 8 hours", "loinc": "1558-6",
        "parameters": [
            ("Glucose", "mmol/L", 1, "1558-6", [
                ("any", None, None, "3.9", "5.5", "2.2", "25.0"),
            ]),
        ],
    },
]

MEDICATIONS = [
    {
        "category": "Antibiotics", "generic": "Amoxicillin", "strength": "500 mg",
        "form": "capsule", "unit": "capsule", "atc": "J01CA", "code": "J01CA04",
        "price": "120.00", "reorder": 100,
        "doses": [("oral", None, None, 250, 1000, "mg", 3000)],
    },
    {
        "category": "Antibiotics", "generic": "Amoxicillin", "strength": "125 mg/5 mL",
        "form": "suspension", "unit": "bottle", "atc": "J01CA", "code": "J01CA04",
        "price": "950.00", "reorder": 20,
        "doses": [("oral", 0, 12, 62.5, 500, "mg", 1500)],
    },
    {
        "category": "Antimalarials", "generic": "Artemether/Lumefantrine",
        "strength": "20/120 mg", "form": "tablet", "unit": "tablet", "atc": "P01BF",
        "price": "180.00", "reorder": 200,
        "doses": [("oral", 5, None, 1, 4, "tablet", 8)],
    },
    {
        "category": "Analgesics", "generic": "Paracetamol", "strength": "500 mg",
        "form": "tablet", "unit": "tablet", "atc": "N02BE", "code": "N02BE01",
        "price": "20.00", "reorder": 500,
        "doses": [("oral", 12, None, 500, 1000, "mg", 4000),
                  ("oral", 0, 11, 120, 500, "mg", 2000)],
    },
    {
        "category": "Analgesics", "generic": "Diclofenac", "strength": "50 mg",
        "form": "tablet", "unit": "tablet", "atc": "M01AB", "price": "45.00",
        "reorder": 200, "renal": True, "paediatric": True,
        "caution": "Not recommended under 14 years.",
        "doses": [("oral", 14, None, 25, 50, "mg", 150)],
        "contraindications": [
            ("peptic ulcer", "Contraindicated in active peptic ulcer disease."),
            ("asthma", "May precipitate bronchospasm in aspirin-sensitive asthma."),
        ],
    },
]


def _expand(patterns):
    """Turn permission patterns into Permission rows.

    Supports `app.codename`, `app.*` and `app.prefix*`, so a role definition stays
    readable as the number of permissions grows.
    """
    from django.db.models import Q

    query = Q()
    for pattern in patterns:
        app_label, _, codename = pattern.partition(".")
        if codename in ("", "*"):
            query |= Q(content_type__app_label=app_label)
        elif codename.endswith("*"):
            query |= Q(content_type__app_label=app_label,
                       codename__startswith=codename.rstrip("*"))
        elif "*" in codename:
            head, _, tail = codename.partition("*")
            query |= Q(content_type__app_label=app_label, codename__startswith=head,
                       codename__endswith=tail)
        else:
            query |= Q(content_type__app_label=app_label, codename=codename)
    return Permission.objects.filter(query)


class Command(BaseCommand):
    help = "Seed a synthetic demo hospital (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--allow-in-production", action="store_true",
            help="Required when DEBUG is off. Demo data does not belong in a live system.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG and not options["allow_in_production"]:
            raise CommandError(
                "DEBUG is off. Re-run with --allow-in-production if you really mean it."
            )

        for key, prefix, include_year, width in SEQUENCES:
            NumberSequence.objects.get_or_create(
                key=key,
                defaults={"prefix": prefix, "include_year": include_year, "width": width},
            )

        org, _ = Organization.objects.get_or_create(name="Ilesa Health Group")
        facilities = {}
        for name, code, tz in FACILITIES:
            facility, _ = Facility.objects.get_or_create(
                code=code, defaults={"organization": org, "name": name, "timezone": tz}
            )
            facilities[code] = facility
        main = facilities["MAIN"]

        departments = {}
        for dept_name, dept_code, clinics in DEPARTMENTS:
            department, _ = Department.objects.get_or_create(
                facility=main, code=dept_code, defaults={"name": dept_name}
            )
            departments[dept_code] = department
            for clinic_name in clinics:
                Clinic.objects.get_or_create(
                    department=department, code=clinic_name[:3].upper(),
                    defaults={"name": clinic_name},
                )

        # Services and prices, per facility.
        services = {}
        for category_name, order, entries in SERVICES:
            category, _ = ServiceCategory.objects.get_or_create(
                name=category_name, defaults={"display_order": order}
            )
            for name, code, amount in entries:
                service, _ = Service.objects.get_or_create(
                    code=code, defaults={"category": category, "name": name}
                )
                services[code] = service
                for facility in facilities.values():
                    # The branch charges less than the main hospital.
                    price = Decimal(amount) * (
                        Decimal("0.8") if facility.code == "IKJ" else Decimal("1")
                    )
                    ServicePrice.objects.get_or_create(
                        service=service, facility=facility, is_active=True,
                        defaults={"amount": price.quantize(Decimal("0.01"))},
                    )

        for name, code, needs_reference in PAYMENT_METHODS:
            PaymentMethod.objects.get_or_create(
                code=code,
                defaults={"name": name, "requires_reference": needs_reference},
            )

        # Laboratory catalogue.
        for entry in LAB_TESTS:
            category, _ = LabTestCategory.objects.get_or_create(name=entry["category"])
            test, _ = LabTest.objects.get_or_create(
                short_code=entry["code"],
                defaults={
                    "category": category, "name": entry["name"],
                    "specimen_type": entry["specimen"],
                    "specimen_requirements": entry.get("requirements", ""),
                    "service": Service.objects.filter(code=entry["service"]).first(),
                    "code_system": "LOINC" if entry.get("loinc") else "",
                    "code": entry.get("loinc", ""),
                    "code_version": "2.78" if entry.get("loinc") else "",
                },
            )
            for order, (name, unit, places, loinc, ranges) in enumerate(
                entry["parameters"], start=1
            ):
                parameter, _ = LabTestParameter.objects.get_or_create(
                    test=test, name=name,
                    defaults={
                        "unit": unit, "decimal_places": places, "display_order": order,
                        "value_type": (
                            LabTestParameter.CHOICE if entry.get("choice")
                            else LabTestParameter.NUMERIC
                        ),
                        "choices_csv": entry.get("choice", ""),
                        "code_system": "LOINC" if loinc else "",
                        "code": loinc or "",
                    },
                )
                for sex, min_age, max_age, low, high, crit_low, crit_high in ranges:
                    ReferenceRange.objects.get_or_create(
                        parameter=parameter, sex=sex,
                        min_age_years=min_age, max_age_years=max_age,
                        defaults={
                            "low": Decimal(str(low)) if low is not None else None,
                            "high": Decimal(str(high)) if high is not None else None,
                            "critical_low": (
                                Decimal(str(crit_low)) if crit_low is not None else None
                            ),
                            "critical_high": (
                                Decimal(str(crit_high)) if crit_high is not None else None
                            ),
                        },
                    )

        fever_panel, _ = LabTest.objects.get_or_create(
            short_code="FEVER",
            defaults={
                "category": LabTestCategory.objects.get(name="Haematology"),
                "name": "Fever screen", "is_panel": True,
            },
        )
        fever_panel.panel_members.set(
            LabTest.objects.filter(short_code__in=["FBC", "MP"])
        )

        # Formulary and stock.
        today = timezone.localdate()
        for entry in MEDICATIONS:
            category, _ = MedicationCategory.objects.get_or_create(
                name=entry["category"]
            )
            medication, _ = Medication.objects.get_or_create(
                generic_name=entry["generic"], strength=entry["strength"],
                dosage_form=entry["form"], brand_name="",
                defaults={
                    "category": category, "dispensing_unit": entry["unit"],
                    "ingredients_csv": entry["generic"],
                    "atc_class": entry.get("atc", ""),
                    "code_system": "ATC" if entry.get("code") else "",
                    "code": entry.get("code", ""),
                    "selling_price": Decimal(entry["price"]),
                    "reorder_level": entry["reorder"],
                    "avoid_in_renal_impairment": entry.get("renal", False),
                    "paediatric_caution": entry.get("paediatric", False),
                    "caution_note": entry.get("caution", ""),
                },
            )
            for route, min_age, max_age, low, high, unit, daily in entry["doses"]:
                DoseRange.objects.get_or_create(
                    medication=medication, route=route,
                    min_age_years=min_age, max_age_years=max_age,
                    defaults={
                        "min_single_dose": Decimal(str(low)),
                        "max_single_dose": Decimal(str(high)),
                        "dose_unit": unit,
                        "max_daily_dose": Decimal(str(daily)) if daily else None,
                    },
                )
            for keyword, note in entry.get("contraindications", []):
                ContraindicationRule.objects.get_or_create(
                    medication=medication, condition_keyword=keyword,
                    defaults={"note": note},
                )
            batch, created = StockBatch.objects.get_or_create(
                medication=medication, facility=main,
                batch_number=f"{entry['generic'][:3].upper()}-2027A",
                defaults={
                    "expiry_date": today + timedelta(days=540),
                    "quantity_on_hand": 400,
                    "unit_cost": (Decimal(entry["price"]) * Decimal("0.6")).quantize(
                        Decimal("0.01")
                    ),
                },
            )
            if created:
                StockMovement.objects.create(
                    batch=batch, kind=StockMovement.RECEIPT, quantity_delta=400,
                    quantity_after=400, reason="Opening stock",
                    recorded_by=User.objects.filter(
                        email="pharmacist@demo.test"
                    ).first() or self._bootstrap_user(),
                )
            # One nearly-expired batch, so expiry handling is visible in the demo.
            StockBatch.objects.get_or_create(
                medication=medication, facility=main,
                batch_number=f"{entry['generic'][:3].upper()}-SHORT",
                defaults={
                    "expiry_date": today + timedelta(days=21),
                    "quantity_on_hand": 30,
                },
            )

        # --- wards, rooms and beds -------------------------------------------
        wards = {}
        for ward_name, ward_code, ward_type, rate_code, room_codes, per_room in WARDS:
            ward, _ = Ward.objects.update_or_create(
                facility=facilities["MAIN"], code=ward_code,
                defaults={
                    "name": ward_name,
                    "ward_type": ward_type,
                    "department": departments.get("WARD"),
                    "nightly_service": services.get(rate_code),
                },
            )
            wards[ward_code] = ward
            for room_code in room_codes:
                room, _ = Room.objects.get_or_create(
                    ward=ward, code=room_code,
                    defaults={"name": f"Room {room_code}"},
                )
                for index in range(per_room):
                    Bed.objects.get_or_create(
                        room=room, code="ABCDEF"[index]
                    )
            for measurement, low, high, instruction in ESCALATION_THRESHOLDS.get(
                ward_code, ESCALATION_THRESHOLDS["default"]
            ):
                EscalationThreshold.objects.update_or_create(
                    ward=ward, measurement=measurement,
                    defaults={
                        "low": Decimal(str(low)) if low is not None else None,
                        "high": Decimal(str(high)) if high is not None else None,
                        "instruction": instruction,
                    },
                )

        # --- imaging catalogue -----------------------------------------------
        modalities = {}
        for name, code, order in MODALITIES:
            modality, _ = ImagingModality.objects.update_or_create(
                code=code, defaults={"name": name, "display_order": order}
            )
            modalities[code] = modality

        for (modality_code, name, short, body_part, service_code, minutes,
             contrast, preparation, contraindications, system, code) in IMAGING_PROCEDURES:
            ImagingProcedure.objects.update_or_create(
                code_short=short,
                defaults={
                    "modality": modalities[modality_code],
                    "name": name,
                    "body_part": body_part,
                    "service": services.get(service_code),
                    "typical_minutes": minutes,
                    "requires_contrast": contrast,
                    "preparation_instructions": preparation,
                    "contraindications": contraindications,
                    "code_system": system,
                    "code": code,
                },
            )

        roles = {}
        for role_name, spec in ROLES.items():
            role, _ = Role.objects.get_or_create(name=role_name)
            role.permissions.set(_expand(spec["permissions"]))
            limit = spec.get("discount_limit")
            if limit and str(role.discount_limit) != limit:
                role.discount_limit = Decimal(limit)
                role.save(update_fields=["discount_limit"])
            roles[role_name] = role

        for email, full_name, role_name, facility_code in STAFF:
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User.objects.create_user(email, full_name, DEMO_PASSWORD)
            RoleAssignment.objects.get_or_create(
                user=user, role=roles[role_name],
                facility=facilities.get(facility_code) if facility_code else None,
            )

        self.stdout.write(self.style.SUCCESS("Demo hospital configured:"))
        for label, count in [
            ("facilities", Facility.objects.count()),
            ("departments", Department.objects.count()),
            ("services", Service.objects.count()),
            ("laboratory tests", LabTest.objects.count()),
            ("imaging procedures", ImagingProcedure.objects.count()),
            ("medications", Medication.objects.count()),
            ("stock batches", StockBatch.objects.count()),
            ("wards", Ward.objects.count()),
            ("beds", Bed.objects.count()),
            ("escalation thresholds", EscalationThreshold.objects.count()),
            ("roles", Role.objects.count()),
            ("staff", User.objects.count()),
        ]:
            self.stdout.write(f"  {count:>4} {label}")
        self.stdout.write(f"\nEvery account's password: {DEMO_PASSWORD}")
        self.stdout.write("Next: python backend/manage.py demo_day")

    def _bootstrap_user(self):
        user, _ = User.objects.get_or_create(
            email="system@demo.test", defaults={"full_name": "System"}
        )
        return user
