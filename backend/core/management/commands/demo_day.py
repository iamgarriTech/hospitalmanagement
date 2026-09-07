"""Walk synthetic patients through the outpatient day.

Leaves the hospital mid-shift rather than tidy: people waiting, people with a doctor,
specimens in the laboratory, one critical result awaiting acknowledgement, prescriptions
part-dispensed and bills part-paid. An evaluator opening any role's screen should find
work on it, because an empty queue demonstrates nothing.

Synthetic data only.
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from billing.models import (
    CashierSession, Invoice, Payment, PaymentMethod, charge, open_invoice_for,
)
from clinical.models import Diagnosis, Encounter, EncounterVersion, VitalSigns
from facilities.models import Clinic, Facility
from laboratory.models import LabOrder, LabOrderItem, LabTest
from laboratory.results import enter_results, verify_results
from patients.models import Patient, PatientAllergy, PatientChronicCondition
from pharmacy.models import (
    Medication, Prescription, PrescriptionItem, StockBatch, Dispense, take_from_batch,
)
from visits.models import Visit

GIVEN_F = ["Amina", "Ngozi", "Fatima", "Blessing", "Adaeze", "Kemi", "Halima",
           "Chinwe", "Folake", "Zainab", "Ifeoma", "Yetunde"]
GIVEN_M = ["Emeka", "Chidi", "Tunde", "Ibrahim", "Segun", "Musa", "Obinna", "Bola",
           "Uche", "Kunle", "Sani", "Femi"]
FAMILY = ["Yusuf", "Obi", "Okonkwo", "Bakare", "Eze", "Bello", "Adeyemi", "Nwosu",
          "Adewale", "Balogun", "Okafor", "Danjuma", "Aliyu", "Lawal", "Afolabi"]

COMPLAINTS = [
    ("Fever and headache for three days", "Malaria", "provisional"),
    ("Cough for two weeks", "Lower respiratory tract infection", "provisional"),
    ("Burning on passing urine", "Urinary tract infection", "confirmed"),
    ("Generalised body pain", "Musculoskeletal pain", "provisional"),
    ("Vomiting and loose stool since yesterday", "Acute gastroenteritis", "confirmed"),
    ("Headache and dizziness", "Hypertension", "confirmed"),
]

ALLERGIES = [("Penicillin", "Anaphylaxis", "severe"), ("Sulfa", "Rash", "mild"),
             ("Aspirin", "Wheeze", "moderate")]
CONDITIONS = ["Hypertension", "Type 2 diabetes mellitus", "Asthma",
              "Sickle cell disease", "Peptic ulcer disease"]


class Command(BaseCommand):
    help = "Walk synthetic patients through the outpatient day (idempotent-ish; adds more)."

    def add_arguments(self, parser):
        parser.add_argument("--patients", type=int, default=24)
        parser.add_argument("--seed", type=int, default=7)
        parser.add_argument("--allow-in-production", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG and not options["allow_in_production"]:
            raise CommandError("DEBUG is off. Re-run with --allow-in-production.")

        random.seed(options["seed"])
        facility = Facility.objects.filter(code="MAIN").first()
        if facility is None:
            raise CommandError("Run seed_demo first.")

        staff = {
            key: User.objects.filter(email=email).first()
            for key, email in [
                ("reception", "reception@demo.test"), ("nurse", "nurse@demo.test"),
                ("doctor", "doctor@demo.test"), ("consultant", "consultant@demo.test"),
                ("lab", "lab@demo.test"), ("pharmacist", "pharmacist@demo.test"),
                ("cashier", "cashier@demo.test"),
            ]
        }
        if not all(staff.values()):
            raise CommandError("Demo staff missing. Run seed_demo first.")

        clinic = Clinic.objects.filter(department__facility=facility).first()
        fbc = LabTest.objects.get(short_code="FBC")
        malaria = LabTest.objects.get(short_code="MP")
        cash = PaymentMethod.objects.get(code="CASH")
        session = CashierSession.objects.filter(
            cashier=staff["cashier"], facility=facility, status=CashierSession.OPEN
        ).first() or CashierSession.objects.create(
            cashier=staff["cashier"], facility=facility, opening_float=Decimal("5000.00")
        )

        counts = {stage: 0 for stage in
                  ["waiting", "with_doctor", "in_lab", "critical", "at_pharmacy",
                   "at_cash_desk", "completed"]}

        total = options["patients"]
        for index in range(total):
            patient = self._make_patient(facility, index)
            visit = Visit.objects.create(
                patient=patient, facility=facility, clinic=clinic,
                arrived_at=timezone.now() - timedelta(minutes=random.randint(5, 240)),
                reason=random.choice(COMPLAINTS)[0],
                checked_in_by=staff["reception"],
            )

            # How far this patient has got. Roughly a real mid-morning distribution.
            stage = random.choices(
                ["waiting", "with_doctor", "in_lab", "at_pharmacy", "at_cash_desk",
                 "completed"],
                weights=[18, 12, 20, 15, 10, 25],
            )[0]

            if stage == "waiting":
                counts["waiting"] += 1
                continue

            self._record_vitals(patient, visit, facility, staff["nurse"])
            visit.move_to(Visit.CALLED, actor=staff["reception"], note="Room 2")
            visit.move_to(Visit.IN_CONSULTATION, actor=staff["doctor"])

            if stage == "with_doctor":
                counts["with_doctor"] += 1
                continue

            clinician = random.choice([staff["doctor"], staff["consultant"]])
            encounter, complaint = self._consult(patient, visit, facility, clinician)
            charge(visit=visit, service_code="CONSULT",
                   description=f"Consultation — {clinician.full_name}",
                   source_type="clinical.Encounter", source_id=encounter.pk)

            order = LabOrder.objects.create(
                visit=visit, patient=patient, facility=facility,
                ordered_by=clinician, clinical_details=complaint[0],
                priority=LabOrder.URGENT if random.random() < 0.2 else LabOrder.ROUTINE,
            )
            for test in ([fbc, malaria] if random.random() < 0.5 else [fbc]):
                item = LabOrderItem.objects.create(order=order, test=test)
                if test.service_id:
                    charge(visit=visit, service_code=test.service.code,
                           description=test.name,
                           source_type="laboratory.LabOrderItem", source_id=item.pk)
            visit.move_to(Visit.SENT_FOR_INVESTIGATION, actor=clinician)

            if stage == "in_lab":
                # Leave these at different points on the bench.
                for item in order.items.all():
                    reached = random.choice(["ordered", "collected", "resulted"])
                    if reached in ("collected", "resulted"):
                        self._collect(item, staff["lab"])
                    if reached == "resulted":
                        item.advance_to(LabOrderItem.PROCESSING)
                        item.save(update_fields=["status"])
                        self._enter(item, staff["lab"], critical=False)
                counts["in_lab"] += 1
                continue

            # Results in, one patient made critical so the alert list is not empty.
            critical = counts["critical"] == 0 and index > total // 3
            for item in order.items.all():
                self._collect(item, staff["lab"])
                item.advance_to(LabOrderItem.PROCESSING)
                item.save(update_fields=["status"])
                self._enter(item, staff["lab"], critical=critical and item.test == fbc)
                verify_results(order_item=item, actor=staff["lab"],
                               comment="Reviewed")
            if critical:
                counts["critical"] += 1

            visit.move_to(Visit.IN_CONSULTATION, actor=clinician)
            prescription = self._prescribe(patient, visit, facility, encounter, clinician)
            encounter.finalise(actor=clinician)
            visit.move_to(Visit.SENT_TO_PHARMACY, actor=clinician)

            if stage == "at_pharmacy":
                counts["at_pharmacy"] += 1
                continue

            self._dispense(prescription, staff["pharmacist"], facility,
                           partial=random.random() < 0.3)
            visit.move_to(Visit.SENT_FOR_BILLING, actor=staff["pharmacist"])

            invoice = open_invoice_for(visit)
            if stage == "at_cash_desk":
                counts["at_cash_desk"] += 1
                continue

            invoice.status = Invoice.FINALISED
            invoice.finalised_at = timezone.now()
            invoice.save(update_fields=["status", "finalised_at"])
            amount = invoice.balance
            if random.random() < 0.25:
                amount = (amount / 2).quantize(Decimal("0.01"))  # part payment
            if amount > 0:
                Payment.objects.create(
                    invoice=invoice, cashier_session=session, method=cash,
                    amount=amount, received_by=staff["cashier"],
                    idempotency_key=f"demo-{visit.pk}-{timezone.now().timestamp()}",
                )
                invoice.refresh_from_db()
                if invoice.balance <= 0:
                    invoice.status = Invoice.PAID
                    invoice.save(update_fields=["status"])
            if invoice.balance <= 0:
                visit.move_to(Visit.COMPLETED, actor=staff["cashier"])
                counts["completed"] += 1
            else:
                counts["at_cash_desk"] += 1

        self.stdout.write(self.style.SUCCESS(f"Walked {total} synthetic patients:"))
        for stage, count in counts.items():
            self.stdout.write(f"  {count:>3} {stage.replace('_', ' ')}")
        self.stdout.write(
            f"\n  {Patient.objects.count()} patients, "
            f"{Visit.objects.count()} visits, "
            f"{Invoice.objects.count()} invoices, "
            f"{Prescription.objects.count()} prescriptions"
        )

    # --- steps ---------------------------------------------------------------

    def _make_patient(self, facility, index):
        sex = random.choice(["female", "male"])
        given = random.choice(GIVEN_F if sex == "female" else GIVEN_M)
        patient = Patient.objects.create(
            given_name=given, family_name=random.choice(FAMILY),
            sex=sex,
            date_of_birth=timezone.localdate() - timedelta(
                days=random.randint(300, 26000)
            ),
            date_of_birth_is_estimated=random.random() < 0.15,
            phone_primary=f"080{random.randint(10000000, 99999999)}",
            address_line=f"{random.randint(1, 90)} Demo Street",
            city="Ilesa", state="Osun",
            blood_group=random.choice(["A+", "B+", "O+", "AB+", "O-"]),
            genotype=random.choice(["AA", "AA", "AA", "AS", "SS"]),
            facility=facility,
        )
        if random.random() < 0.25:
            substance, reaction, severity = random.choice(ALLERGIES)
            PatientAllergy.objects.create(
                patient=patient, substance=substance, reaction=reaction,
                severity=severity,
            )
        if random.random() < 0.3:
            PatientChronicCondition.objects.create(
                patient=patient, condition=random.choice(CONDITIONS),
                code_system="ICD-10", code="I10", code_display="Essential hypertension",
                code_version="2019",
            )
        return patient

    def _record_vitals(self, patient, visit, facility, nurse):
        VitalSigns.objects.create(
            patient=patient, visit=visit, facility=facility, recorded_by=nurse,
            temperature_c=Decimal(str(round(random.uniform(36.2, 39.4), 1))),
            systolic_bp=random.randint(100, 165),
            diastolic_bp=random.randint(62, 98),
            pulse_bpm=random.randint(58, 118),
            respiratory_rate=random.randint(14, 26),
            oxygen_saturation=random.randint(93, 100),
            weight_kg=Decimal(str(round(random.uniform(14, 96), 2))),
            height_cm=Decimal(str(round(random.uniform(96, 186), 1))),
            pain_score=random.randint(0, 7),
        )

    def _consult(self, patient, visit, facility, clinician):
        complaint = random.choice(COMPLAINTS)
        encounter = Encounter.objects.create(
            visit=visit, patient=patient, facility=facility, clinician=clinician,
        )
        version = EncounterVersion.objects.create(
            encounter=encounter, version_number=1, authored_by=clinician,
            presenting_complaint=complaint[0],
            history_of_presenting_complaint="Gradual onset, no prior treatment.",
            examination_findings="Alert, well hydrated. Chest clear.",
            clinical_notes=f"Working diagnosis {complaint[1]}. Investigations requested.",
            treatment_plan="Treat as below; review with results.",
            follow_up_plan="Review in 5 days or sooner if worse.",
        )
        Diagnosis.objects.create(
            version=version, description=complaint[1], certainty=complaint[2],
            is_primary=True, code_system="ICD-10", code="B54",
            code_display=complaint[1], code_version="2019",
        )
        return encounter, complaint

    def _collect(self, item, lab):
        from laboratory.models import Specimen

        if hasattr(item, "specimen"):
            return
        item.advance_to(LabOrderItem.COLLECTED)
        item.save(update_fields=["status"])
        Specimen.objects.create(
            order_item=item, specimen_type=item.test.specimen_type,
            collected_by=lab,
        )

    def _enter(self, item, lab, *, critical):
        entries = []
        parameters = list(item.test.parameters.all())
        critical_parameter = parameters[0].pk if critical and parameters else None
        for parameter in parameters:
            if parameter.value_type == parameter.CHOICE:
                entries.append({
                    "parameter": parameter.pk,
                    "value_text": random.choice(parameter.choices_csv.split(",")),
                })
                continue
            reference = parameter.reference_ranges.first()
            if reference and reference.low is not None and reference.high is not None:
                if parameter.pk == critical_parameter and reference.critical_low is not None:
                    value = reference.critical_low - Decimal("0.5")
                else:
                    spread = float(reference.high) - float(reference.low)
                    value = Decimal(str(round(
                        random.uniform(float(reference.low) - spread * 0.2,
                                       float(reference.high) + spread * 0.2),
                        parameter.decimal_places,
                    )))
            else:
                value = Decimal(str(round(random.uniform(1, 40), 1)))
            entries.append({"parameter": parameter.pk, "value_numeric": str(value)})
        enter_results(order_item=item, entries=entries, actor=lab)

    def _prescribe(self, patient, visit, facility, encounter, clinician):
        prescription = Prescription.objects.create(
            visit=visit, encounter=encounter, patient=patient, facility=facility,
            prescribed_by=clinician,
        )
        choices = list(Medication.objects.filter(is_active=True))
        for medication in random.sample(choices, k=min(2, len(choices))):
            dose_range = medication.dose_ranges.first()
            PrescriptionItem.objects.create(
                prescription=prescription, medication=medication,
                dose=dose_range.max_single_dose if dose_range else Decimal("500"),
                dose_unit=dose_range.dose_unit if dose_range else "mg",
                route=medication.default_route,
                frequency_per_day=random.choice([2, 3]),
                duration_days=random.choice([3, 5, 7]),
                quantity_prescribed=random.choice([10, 15, 21]),
                instructions=random.choice(["After food", "Before food",
                                            "With plenty of water"]),
            )
        return prescription

    def _dispense(self, prescription, pharmacist, facility, *, partial):
        for item in prescription.items.all():
            batch = StockBatch.objects.filter(
                medication=item.medication, facility=facility,
                quantity_on_hand__gt=0, expiry_date__gt=timezone.localdate(),
            ).order_by("expiry_date").first()
            if batch is None:
                continue
            quantity = item.quantity_prescribed
            if partial:
                quantity = max(1, quantity // 2)
            quantity = min(quantity, batch.quantity_on_hand)
            dispense = Dispense.objects.create(
                prescription_item=item, batch=batch, quantity=quantity,
                dispensed_by=pharmacist,
            )
            take_from_batch(batch=batch, quantity=quantity, actor=pharmacist,
                            dispense=dispense,
                            reason=f"Dispensed on "
                                   f"{prescription.prescription_number}")
            if item.medication.selling_price:
                charge(visit=prescription.visit, service_code="",
                       description=f"{item.medication} × {quantity}",
                       source_type="pharmacy.Dispense", source_id=dispense.pk,
                       quantity=quantity, unit_price=item.medication.selling_price)
            item.quantity_dispensed += quantity
            item.status = (PrescriptionItem.DISPENSED if item.is_fully_dispensed
                           else PrescriptionItem.PARTIALLY_DISPENSED)
            item.save(update_fields=["quantity_dispensed", "status"])
        prescription.refresh_status()
