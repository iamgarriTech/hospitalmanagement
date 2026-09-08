"""Build the inpatient load fixture for AC-115 and AC-116.

Separate from `seed_demo` because this is not a demo: it is a full 40-bed ward
with the medication, observation and nursing volume a real ward carries, which
is unpleasant to click through and is the only shape the performance criteria
are meaningful against. A ward board that is fast with three patients on it
tells you nothing.
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Role, RoleAssignment, User
from billing.models import Service, ServiceCategory, ServicePrice
from clinical.models import VitalSigns
from facilities.models import Facility, Organization
from inpatient.models import (
    Admission,
    Bed,
    BedOccupancy,
    Escalation,
    EscalationThreshold,
    FluidBalanceEntry,
    NursingAssessment,
    NursingNote,
    Room,
    ScheduledDose,
    Ward,
)
from inpatient.services import record_administration, schedule_doses
from patients.models import NumberSequence, Patient, PatientAllergy
from pharmacy.models import (
    Medication,
    MedicationCategory,
    Prescription,
    PrescriptionItem,
    StockBatch,
)

SURNAMES = [
    "Adeyemi", "Okonkwo", "Bello", "Eze", "Yusuf", "Obi", "Lawal", "Nwosu",
    "Danjuma", "Afolabi", "Ibrahim", "Chukwu", "Sanni", "Uche", "Mohammed",
]
GIVEN = [
    "Amina", "Emeka", "Fatima", "Chidi", "Ngozi", "Musa", "Adaeze", "Tunde",
    "Halima", "Kelechi", "Zainab", "Obinna", "Aisha", "Segun", "Chiamaka",
]
DIAGNOSES = [
    "Community-acquired pneumonia", "Hypertensive emergency", "Severe malaria",
    "Diabetic ketoacidosis", "Congestive cardiac failure", "Acute kidney injury",
    "Sickle cell crisis", "Typhoid fever", "Cerebrovascular accident",
]
ALLERGENS = ["Penicillin", "Sulphonamides", "Aspirin", "Codeine", "Ibuprofen"]


class Command(BaseCommand):
    help = "Seed a full 40-bed ward for the inpatient performance benchmark."

    def add_arguments(self, parser):
        parser.add_argument("--beds", type=int, default=40)
        parser.add_argument(
            "--medications", type=int, default=8,
            help="Active medications per patient. AC-116's patient gets 20.",
        )
        parser.add_argument("--days", type=int, default=7, help="Length of stay.")
        parser.add_argument("--seed", type=int, default=20260907)

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(options["seed"])
        bed_count = options["beds"]
        days = options["days"]

        organization, _ = Organization.objects.get_or_create(name="Benchmark Group")
        facility, _ = Facility.objects.get_or_create(
            organization=organization, code="BENCH",
            defaults={"name": "Benchmark Teaching Hospital"},
        )
        for key, prefix, width in [
            ("hospital_number", "BEN", 6), ("admission_number", "ADM", 6),
            ("prescription_number", "RX", 6), ("invoice_number", "INV", 6),
        ]:
            NumberSequence.objects.get_or_create(
                key=key, defaults={"prefix": prefix, "include_year": True,
                                   "width": width},
            )

        staff = self._staff(facility)
        ward = self._ward(facility, bed_count)
        medications = self._formulary(facility, options["medications"] + 20)

        self.stdout.write(f"Ward {ward.code}: {ward.bed_count} beds")

        beds = list(Bed.objects.filter(room__ward=ward).order_by("room__code", "code"))
        start = timezone.now() - timedelta(days=days)
        admissions = []
        for index, bed in enumerate(beds):
            patient = Patient.objects.create(
                given_name=random.choice(GIVEN),
                family_name=random.choice(SURNAMES),
                sex=random.choice(["male", "female"]),
                date_of_birth=timezone.now().date()
                - timedelta(days=random.randint(6_000, 30_000)),
                phone_primary=f"080{random.randint(10_000_000, 99_999_999)}",
                facility=facility,
            )
            for allergen in random.sample(ALLERGENS, random.randint(0, 2)):
                PatientAllergy.objects.create(
                    patient=patient, substance=allergen, reaction="Rash",
                    severity=random.choice(["mild", "moderate", "severe"]),
                    recorded_by=staff["doctor"],
                )
            admission = Admission.objects.create(
                patient=patient, facility=facility,
                admission_reason="Benchmark admission",
                admission_diagnosis=random.choice(DIAGNOSES),
                responsible_consultant=staff["doctor"], admitted_by=staff["doctor"],
                admitted_at=start,
            )
            BedOccupancy.allocate(
                bed=bed, admission=admission, actor=staff["doctor"], at=start
            )
            admissions.append(admission)
            # The first patient carries AC-116's 20 medications; the rest carry
            # a realistic ward load.
            count = 20 if index == 0 else options["medications"]
            self._medicate(
                admission, medications[:count], staff, days=days, start=start
            )
            self._observe(admission, staff, days=days, start=start, ward=ward)
            if index % 10 == 0:
                self.stdout.write(f"  {index + 1}/{len(beds)} beds filled")

        self.stdout.write(self.style.SUCCESS(
            f"{len(admissions)} admissions · "
            f"{ScheduledDose.objects.filter(admission__in=admissions).count()} doses · "
            f"{VitalSigns.objects.filter(admission__in=admissions).count()} observations · "
            f"{Escalation.objects.filter(admission__in=admissions).count()} escalations"
        ))
        self.stdout.write(
            f"AC-116 patient: admission {admissions[0].pk} "
            f"({admissions[0].scheduled_doses.count()} doses over {days} days)"
        )
        self.stdout.write(f"AC-115 ward: {ward.pk}")
        self.stdout.write("Benchmark login: bench@example.test / benchmark-password-only")

    # --- fixtures -------------------------------------------------------------

    def _staff(self, facility):
        from django.contrib.auth.models import Permission

        role, created = Role.objects.get_or_create(name="Benchmark Ward Staff")
        if created:
            # Everything the benchmarked screens read and write, and nothing else.
            role.permissions.set(Permission.objects.filter(
                content_type__app_label__in=[
                    "inpatient", "clinical", "pharmacy", "patients", "billing",
                    "laboratory", "visits",
                ]
            ))
        users = {}
        for key, email, name in [
            ("doctor", "bench@example.test", "Bench Doctor"),
            ("nurse", "benchnurse@example.test", "Bench Nurse"),
        ]:
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User.objects.create_user(email, name, "benchmark-password-only")
                RoleAssignment.objects.create(user=user, role=role, facility=facility)
            users[key] = user
        return users

    def _ward(self, facility, bed_count):
        category, _ = ServiceCategory.objects.get_or_create(
            name="Accommodation", defaults={"display_order": 9}
        )
        service, _ = Service.objects.get_or_create(
            code="BED-BENCH", defaults={"category": category, "name": "Bed night"}
        )
        ServicePrice.objects.get_or_create(
            service=service, facility=facility, defaults={"amount": "12000.00"}
        )
        ward, _ = Ward.objects.get_or_create(
            facility=facility, code="BW",
            defaults={"name": "Benchmark Ward", "nightly_service": service},
        )
        for measurement, low, high in [
            ("systolic_bp", 90, 180), ("oxygen_saturation", 92, None),
            ("temperature_c", None, Decimal("38.5")), ("pulse_bpm", 50, 120),
        ]:
            EscalationThreshold.objects.get_or_create(
                ward=ward, measurement=measurement,
                defaults={"low": low, "high": high,
                          "instruction": "Tell the registrar"},
            )
        # Four beds to a room, which is how a Nigerian general ward is laid out.
        made = Bed.objects.filter(room__ward=ward).count()
        room_index = Room.objects.filter(ward=ward).count() + 1
        while made < bed_count:
            room = Room.objects.create(
                ward=ward, name=f"Room {room_index}", code=f"R{room_index}"
            )
            for letter in "ABCD":
                if made >= bed_count:
                    break
                Bed.objects.create(room=room, code=letter)
                made += 1
            room_index += 1
        return ward

    def _formulary(self, facility, count):
        category, _ = MedicationCategory.objects.get_or_create(name="Benchmark")
        medications = []
        for index in range(count):
            medication, created = Medication.objects.get_or_create(
                code=f"BENCH-{index:03d}",
                defaults={
                    "category": category,
                    "generic_name": f"Benchmarkicillin {index}",
                    "brand_name": f"Benchmark {index}",
                    "strength": "500 mg",
                    "dosage_form": "tablet",
                    "default_route": "oral",
                    "selling_price": Decimal("120.00"),
                },
            )
            if created or not medication.batches.exists():
                StockBatch.objects.create(
                    medication=medication, facility=facility,
                    batch_number=f"B{index:04d}",
                    expiry_date=timezone.now().date() + timedelta(days=365),
                    quantity_on_hand=100_000, unit_cost=Decimal("60.00"),
                )
            medications.append(medication)
        return medications

    def _medicate(self, admission, medications, staff, *, days, start):
        prescription = Prescription.objects.create(
            admission=admission, patient=admission.patient,
            facility=admission.facility, prescribed_by=staff["doctor"],
            prescribed_at=start,
        )
        for medication in medications:
            item = PrescriptionItem.objects.create(
                prescription=prescription, medication=medication,
                dose="500", dose_unit="mg", route="oral",
                frequency_per_day=random.choice([1, 2, 3]), duration_days=days,
                quantity_prescribed=days * 3,
            )
            doses = schedule_doses(
                prescription_item=item, admission=admission, start=start
            )
            # Most past doses are recorded, and a few are not — a ward with no
            # gaps in the chart is not a ward, and the overdue query is the one
            # the board pays for.
            batch = medication.batches.first()
            for dose in doses:
                if dose.due_at > timezone.now() or random.random() < 0.08:
                    continue
                record_administration(
                    scheduled_dose=dose, state="administered", actor=staff["nurse"],
                    administered_at=dose.due_at + timedelta(minutes=random.randint(0, 40)),
                    batch=batch,
                )

    def _observe(self, admission, staff, *, days, start, ward):
        from inpatient.services import record_observation_escalations

        # Four rounds of observations a day, which is a normal general ward.
        for hour in range(0, days * 24, 6):
            moment = start + timedelta(hours=hour)
            if moment > timezone.now():
                break
            observations = VitalSigns.objects.create(
                patient=admission.patient, admission=admission,
                facility=admission.facility, recorded_by=staff["nurse"],
                recorded_at=moment,
                temperature_c=Decimal(str(round(random.uniform(36.0, 39.2), 1))),
                # Derived from the systolic rather than drawn independently: two
                # independent draws produce a diastolic above the systolic often
                # enough that the check constraint refuses the row.
                systolic_bp=(systolic := random.randint(85, 195)),
                diastolic_bp=random.randint(50, min(systolic - 20, 105)),
                pulse_bpm=random.randint(48, 130),
                respiratory_rate=random.randint(12, 28),
                oxygen_saturation=random.randint(88, 100),
            )
            record_observation_escalations(
                observations=observations, admission=admission,
                actor=staff["nurse"], ward=ward,
            )
            if hour % 12 == 0:
                NursingAssessment.objects.create(
                    admission=admission, patient=admission.patient,
                    shift=random.choice(["early", "late", "night"]),
                    observations=observations, recorded_by=staff["nurse"],
                    recorded_at=moment, summary="Benchmark assessment",
                )
                NursingNote.objects.create(
                    admission=admission, patient=admission.patient,
                    shift="early", note="Benchmark nursing note. " * 8,
                    author=staff["nurse"], recorded_at=moment,
                )
            for direction, route in [("intake", "oral"), ("output", "urine")]:
                FluidBalanceEntry.objects.create(
                    admission=admission, patient=admission.patient,
                    direction=direction, route=route,
                    volume_ml=random.randint(100, 600),
                    recorded_by=staff["nurse"], recorded_at=moment,
                )
