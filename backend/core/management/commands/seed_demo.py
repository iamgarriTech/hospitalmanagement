"""Synthetic demo hospital. Never real patient data.

Idempotent: safe to re-run. Refuses to run with DEBUG off unless forced, so it cannot
quietly seed a live deployment.
"""
from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Role, RoleAssignment, User
from facilities.models import Clinic, Department, Facility, Organization
from patients.models import NumberSequence

DEMO_PASSWORD = "demo-password-not-for-real-use"

FACILITIES = [
    ("Ilesa General Hospital", "MAIN", "Africa/Lagos"),
    ("Ikeja Branch Clinic", "IKJ", "Africa/Lagos"),
]

DEPARTMENTS = [
    ("General Outpatient", "GOPD", ["Morning Clinic", "Afternoon Clinic"]),
    ("Internal Medicine", "MED", ["Consultant Clinic"]),
    ("Laboratory", "LAB", []),
    ("Pharmacy", "PHA", []),
    ("Billing", "BIL", []),
]

# Permission sets grow as each Phase 1 slice adds its own. Qualified as app.codename.
ROLES = {
    "Hospital Administrator": [
        "facilities.view_facility", "facilities.add_facility", "facilities.change_facility",
        "patients.view_patient", "patients.view_patient_access_log",
    ],
    "Facility Manager": ["facilities.view_facility", "facilities.change_facility"],
    "Receptionist": [
        "facilities.view_facility",
        "patients.view_patient", "patients.add_patient", "patients.change_patient",
        "visits.view_visit", "visits.check_in_patient", "visits.move_queue",
        "visits.change_visit",
    ],
    "Medical Records Officer": [
        "facilities.view_facility",
        "patients.view_patient", "patients.add_patient", "patients.change_patient",
        "patients.merge_patient", "patients.register_duplicate_patient",
        "patients.view_patient_access_log",
    ],
    "Nurse": [
        "facilities.view_facility", "patients.view_patient",
        "visits.view_visit", "visits.move_queue",
    ],
    "Doctor": [
        "facilities.view_facility", "patients.view_patient",
        "visits.view_visit", "visits.move_queue",
    ],
    "Pharmacist": [
        "facilities.view_facility", "patients.view_patient",
        "visits.view_visit", "visits.move_queue",
    ],
    "Laboratory Scientist": [
        "facilities.view_facility", "patients.view_patient",
        "visits.view_visit", "visits.move_queue",
    ],
    "Cashier": [
        "facilities.view_facility", "patients.view_patient",
        "visits.view_visit", "visits.move_queue",
    ],
}

STAFF = [
    ("admin@demo.test", "Adaeze Okonkwo", "Hospital Administrator", None),
    ("manager@demo.test", "Tunde Bakare", "Facility Manager", "MAIN"),
    ("reception@demo.test", "Ngozi Eze", "Receptionist", "MAIN"),
    ("nurse@demo.test", "Fatima Bello", "Nurse", "MAIN"),
    ("doctor@demo.test", "Chukwuma Nwosu", "Doctor", "MAIN"),
    ("pharmacist@demo.test", "Yemi Adeyemi", "Pharmacist", "MAIN"),
    ("lab@demo.test", "Ibrahim Sani", "Laboratory Scientist", "MAIN"),
    ("cashier@demo.test", "Blessing Uche", "Cashier", "MAIN"),
    ("records@demo.test", "Segun Adewale", "Medical Records Officer", "MAIN"),
]


class Command(BaseCommand):
    help = "Seed a synthetic demo hospital (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--allow-in-production",
            action="store_true",
            help="Required when DEBUG is off. Demo data does not belong in a live system.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG and not options["allow_in_production"]:
            raise CommandError(
                "DEBUG is off. Re-run with --allow-in-production if you really mean it."
            )

        org, _ = Organization.objects.get_or_create(name="Ilesa Health Group")

        facilities = {}
        for name, code, tz in FACILITIES:
            facility, _ = Facility.objects.get_or_create(
                code=code, defaults={"organization": org, "name": name, "timezone": tz}
            )
            facilities[code] = facility

        main = facilities["MAIN"]
        for dept_name, dept_code, clinics in DEPARTMENTS:
            department, _ = Department.objects.get_or_create(
                facility=main, code=dept_code, defaults={"name": dept_name}
            )
            for clinic_name in clinics:
                Clinic.objects.get_or_create(
                    department=department,
                    code=clinic_name[:3].upper(),
                    defaults={"name": clinic_name},
                )

        NumberSequence.objects.get_or_create(
            key="hospital_number",
            defaults={"prefix": "ILS", "include_year": True, "width": 5},
        )
        NumberSequence.objects.get_or_create(
            key="visit_number",
            defaults={"prefix": "V", "include_year": True, "width": 6},
        )

        roles = {}
        for role_name, qualified in ROLES.items():
            role, _ = Role.objects.get_or_create(name=role_name)
            wanted = Permission.objects.none()
            for entry in qualified:
                app_label, codename = entry.split(".")
                wanted = wanted | Permission.objects.filter(
                    content_type__app_label=app_label, codename=codename
                )
            role.permissions.set(wanted)
            roles[role_name] = role

        for email, full_name, role_name, facility_code in STAFF:
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User.objects.create_user(email, full_name, DEMO_PASSWORD)
            RoleAssignment.objects.get_or_create(
                user=user,
                role=roles[role_name],
                facility=facilities.get(facility_code) if facility_code else None,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {Organization.objects.count()} organization, "
                f"{Facility.objects.count()} facilities, "
                f"{Department.objects.count()} departments, "
                f"{Role.objects.count()} roles, {User.objects.count()} users."
            )
        )
        self.stdout.write(f"Demo password for every account: {DEMO_PASSWORD}")
