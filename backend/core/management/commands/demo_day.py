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
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from billing.models import (
    CashierSession,
    Invoice,
    Payment,
    PaymentMethod,
    charge,
    open_invoice_for,
)
from clinical.models import Diagnosis, Encounter, EncounterVersion, VitalSigns
from facilities.models import Clinic, Facility
from imaging.models import ImagingOrder, ImagingOrderItem
from inpatient.models import FluidBalanceEntry
from laboratory.models import LabOrder, LabOrderItem, LabTest
from laboratory.results import enter_results, verify_results
from patients.models import Patient, PatientAllergy, PatientChronicCondition
from pharmacy.models import (
    Dispense,
    Medication,
    Prescription,
    PrescriptionItem,
    StockBatch,
    take_from_batch,
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

# Reasons a patient in a Nigerian general hospital is kept in rather than sent
# home. Prose, because a ward list of "Diagnosis 3" demonstrates nothing.
ADMISSION_DIAGNOSES = [
    "Severe malaria with anaemia",
    "Community-acquired pneumonia",
    "Hypertensive emergency",
    "Diabetic ketoacidosis",
    "Acute gastroenteritis with dehydration",
    "Sickle cell vaso-occlusive crisis",
    "Typhoid fever",
    "Congestive cardiac failure",
    "Acute kidney injury",
]

NURSING_SUMMARIES = [
    "Settled overnight, taking oral fluids well.",
    "Pyrexial at midnight, paracetamol given, temperature settling.",
    "Mobilising to the toilet with one nurse. No falls.",
    "Poor appetite, review by the dietitian requested.",
    "Cannula resited in the left forearm, site clean.",
]

NURSING_NOTES = [
    "Reviewed on the ward round. Plan: continue current treatment, repeat FBC in "
    "the morning. Family updated at the bedside.",
    "Complained of pain at the drip site. Cannula removed and resited. No "
    "phlebitis. Observations stable.",
    "Passed urine 400 mL. Bowels opened. Ate half of lunch. Encouraged oral "
    "fluids.",
    "Slept poorly. Reported headache, analgesia given with good effect.",
]

IMAGING_QUESTIONS = [
    "Consolidation? Cough and fever for five days.",
    "Free air? Abdominal pain and guarding.",
    "Pneumothorax after central line insertion?",
    "Cardiomegaly? Breathless on minimal exertion.",
    "Effusion? Reduced air entry at the right base.",
]

IMAGING_FINDINGS = [
    "Right lower lobe airspace opacification. Heart size normal. No effusion.",
    "Lung fields clear. Cardiothoracic ratio within normal limits.",
    "Blunting of the right costophrenic angle consistent with a small effusion.",
    "Cardiomegaly with upper lobe venous diversion.",
]


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
        self._seeded_critical_finding = False
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
                ("ward_doctor", "warddoctor@demo.test"),
                ("ward_nurse", "wardnurse@demo.test"),
                ("ward_manager", "wardmanager@demo.test"),
                ("radiographer", "radiographer@demo.test"),
                ("radiologist", "radiologist@demo.test"),
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

        counts = dict.fromkeys(["waiting", "with_doctor", "in_lab", "critical", "at_pharmacy", "at_cash_desk", "completed", "admitted", "discharged"], 0)

        total = options["patients"]
        for index in range(total):
            patient = self._make_patient(facility, index)
            visit = Visit.objects.create(
                patient=patient, facility=facility, clinic=clinic,
                arrived_at=timezone.now() - timedelta(minutes=random.randint(5, 240)),
                reason=random.choice(COMPLAINTS)[0],
                checked_in_by=staff["reception"],
            )

            # How far this patient has got. Roughly a real mid-morning
            # distribution, with a few too unwell to go home.
            stage = random.choices(
                ["waiting", "with_doctor", "in_lab", "at_pharmacy", "at_cash_desk",
                 "completed", "admitted"],
                weights=[16, 10, 18, 13, 9, 22, 12],
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

            if stage == "admitted":
                # Too unwell to go home. The stay carries on from here, and the
                # attendance closes as admitted rather than sitting in the queue.
                encounter.finalise(actor=clinician)
                if self._admit_and_run_the_stay(
                    patient=patient, visit=visit, facility=facility, staff=staff,
                    clinician=clinician, complaint=complaint,
                    counts=counts, session=session, cash=cash,
                ):
                    continue
                # No bed free — the request stays pending, which is itself a
                # realistic state for a ward list to show.
                counts["admitted"] += 1
                continue

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

    # --- the inpatient stay --------------------------------------------------

    def _admit_and_run_the_stay(self, *, patient, visit, facility, staff, clinician,
                                complaint, counts, session, cash):
        """Admit, then run the stay forward a realistic distance.

        Returns False when no bed is free, leaving the request pending — which
        is a state a ward list has to be able to show, not an error.
        """
        from inpatient.models import Admission, AdmissionRequest
        from inpatient.services import (
            admit,
            charge_bed_nights,
            discharge,
            plan_discharge,
            transfer,
        )

        # One admission in six is unwell enough for intensive care, so that
        # ward has patients and its tighter thresholds are visibly in use.
        ward = self._ward_for(patient, facility, intensive=random.random() < 0.16)
        if ward is None:
            return False

        request = AdmissionRequest.objects.create(
            patient=patient, visit=visit, facility=facility, ward=ward,
            reason=complaint[0],
            working_diagnosis=random.choice(ADMISSION_DIAGNOSES),
            responsible_consultant=staff["consultant"],
            requested_by=clinician,
            priority=AdmissionRequest.URGENT if random.random() < 0.4
            else AdmissionRequest.ROUTINE,
        )

        bed = self._free_bed(ward)
        if bed is None:
            return False

        # Backdate the stay so there are bed nights to bill and a chart with
        # history on it. A ward where everybody arrived this morning shows
        # nothing.
        nights = random.randint(0, 6)
        started = timezone.now() - timedelta(days=nights, hours=random.randint(0, 8))
        admission, occupancy = admit(
            request=request, bed=bed, actor=staff["ward_doctor"], at=started
        )
        visit.move_to(Visit.ADMITTED, actor=staff["ward_doctor"],
                      note=f"Admitted as {admission.admission_number}")
        counts["admitted"] += 1

        self._observe_on_the_ward(admission, staff, ward, started)
        self._chart_and_give_medication(admission, staff, started)
        self._ward_imaging(admission, staff, facility)

        if random.random() < 0.25 and nights >= 2:
            other = self._free_bed(ward)
            if other is not None:
                transfer(admission=admission, to_bed=other,
                         reason="Moved closer to the nurses' station",
                         actor=staff["ward_doctor"],
                         at=started + timedelta(days=1))

        # Planning a discharge and completing one are alternatives here. Doing
        # both to the same stay always consumes the plan, and the ward's
        # discharge list — the screen AC-99 is about — comes out empty.
        outcome = random.choices(
            ["staying", "planned", "discharged"],
            weights=[45, 30, 25] if nights >= 3 else [70, 30, 0],
        )[0]

        if outcome == "planned":
            plan_discharge(
                admission=admission, actor=staff["ward_doctor"],
                expected_date=(timezone.now() + timedelta(days=1)).date(),
                destination=Admission.HOME,
                notes="Needs the discharge medication dispensed and a BP diary",
            )

        if outcome == "discharged":
            charge_bed_nights(admission=admission, actor=staff["ward_doctor"])
            invoice = Invoice.objects.filter(
                admission=admission, status=Invoice.DRAFT
            ).first()
            if invoice is not None and invoice.items.exists():
                invoice.status = Invoice.FINALISED
                invoice.finalised_at = timezone.now()
                invoice.save(update_fields=["status", "finalised_at"])
                Payment.objects.create(
                    invoice=invoice, cashier_session=session, method=cash,
                    amount=invoice.balance, received_by=staff["cashier"],
                    idempotency_key=f"demo-stay-{admission.pk}",
                )
                invoice.refresh_from_db()
                if invoice.balance <= 0:
                    invoice.status = Invoice.PAID
                    invoice.save(update_fields=["status"])
            try:
                discharge(
                    admission=admission, actor=staff["ward_doctor"],
                    diagnosis=f"{admission.admission_diagnosis}, treated",
                    destination=Admission.HOME,
                    instructions="Review in clinic in two weeks.",
                )
                counts["discharged"] += 1
                counts["admitted"] -= 1
            except ValidationError:
                # The billing gate refused. Left as it is, because a ward with an
                # unsettled stay on it is exactly what the discharge list is for.
                pass
        return True

    @staticmethod
    def _ward_for(patient, facility, *, intensive=False):
        """The ward a patient of this age and sex would actually go to."""
        from inpatient.models import Ward

        if intensive:
            icu = Ward.objects.filter(facility=facility, code="ICU").first()
            if icu is not None:
                return icu
        age = patient.age_years or 30
        if age < 16:
            code = "CW"
        elif patient.sex == "female":
            code = "FMW"
        else:
            code = "MMW"
        return Ward.objects.filter(facility=facility, code=code).first()

    @staticmethod
    def _free_bed(ward):
        from inpatient.models import Bed

        return Bed.allocatable(ward=ward).order_by("room__code", "code").first()

    def _observe_on_the_ward(self, admission, staff, ward, started):
        """Four rounds a day, with a few breaching the ward's thresholds."""
        from inpatient.models import NursingAssessment, NursingNote
        from inpatient.services import record_observation_escalations

        hours = int((timezone.now() - started).total_seconds() // 3600)
        for hour in range(0, max(hours, 1), 6):
            moment = started + timedelta(hours=hour)
            if moment > timezone.now():
                break
            # One reading in eight is outside the ward's bounds, so the
            # escalation list is neither empty nor absurd.
            unwell = random.random() < 0.12
            systolic = random.randint(182, 205) if unwell else random.randint(105, 140)
            observations = VitalSigns.objects.create(
                patient=admission.patient, admission=admission,
                facility=admission.facility, recorded_by=staff["ward_nurse"],
                recorded_at=moment,
                temperature_c=Decimal(str(round(random.uniform(36.2, 38.9), 1))),
                systolic_bp=systolic,
                diastolic_bp=random.randint(60, min(systolic - 25, 105)),
                pulse_bpm=random.randint(62, 118),
                respiratory_rate=random.randint(14, 22),
                oxygen_saturation=random.randint(89, 99) if unwell
                else random.randint(95, 100),
            )
            raised = record_observation_escalations(
                observations=observations, admission=admission,
                actor=staff["ward_nurse"], ward=ward,
            )
            # Most escalations get answered; a couple are left outstanding so the
            # ward board has work on it.
            for escalation in raised:
                if random.random() < 0.6:
                    escalation.acknowledge(
                        actor=staff["ward_doctor"],
                        action_taken="Reviewed at the bedside, treatment adjusted.",
                        at=moment + timedelta(minutes=random.randint(5, 40)),
                    )

            if hour % 12 == 0:
                NursingAssessment.objects.create(
                    admission=admission, patient=admission.patient,
                    shift=random.choice(["early", "late", "night"]),
                    observations=observations, recorded_by=staff["ward_nurse"],
                    recorded_at=moment,
                    falls_risk=random.random() < 0.3,
                    summary=random.choice(NURSING_SUMMARIES),
                )
                NursingNote.objects.create(
                    admission=admission, patient=admission.patient,
                    shift="early", note=random.choice(NURSING_NOTES),
                    author=staff["ward_nurse"], recorded_at=moment,
                )
            for direction, route, low, high in [
                ("intake", "oral", 100, 400), ("intake", "iv", 200, 600),
                ("output", "urine", 150, 500),
            ]:
                FluidBalanceEntry.objects.create(
                    admission=admission, patient=admission.patient,
                    direction=direction, route=route,
                    volume_ml=random.randint(low, high),
                    recorded_by=staff["ward_nurse"], recorded_at=moment,
                )

    def _chart_and_give_medication(self, admission, staff, started):
        """A drug chart with history: most doses given, a few not, with reasons."""
        from inpatient.models import MedicationAdministration
        from inpatient.services import record_administration, schedule_doses

        prescription = Prescription.objects.create(
            admission=admission, patient=admission.patient,
            facility=admission.facility, prescribed_by=staff["ward_doctor"],
            prescribed_at=started,
        )
        days = max((timezone.now().date() - started.date()).days, 1) + 2
        medications = random.sample(
            list(Medication.objects.filter(is_active=True)),
            min(3, Medication.objects.filter(is_active=True).count()),
        )
        for medication in medications:
            item = PrescriptionItem.objects.create(
                prescription=prescription, medication=medication,
                dose=random.choice(["250", "500", "1000"]), dose_unit="mg",
                route=medication.default_route,
                frequency_per_day=random.choice([1, 2, 3]),
                duration_days=days, quantity_prescribed=days * 3,
                instructions=random.choice(["After food", "With water", ""]),
            )
            doses = schedule_doses(
                prescription_item=item, admission=admission, start=started
            )
            for dose in doses:
                if dose.due_at > timezone.now():
                    continue
                # Re-selected per dose. A batch picked once and reused drains
                # and then refuses — which is correct of `take_from_batch` and
                # wrong of the ward, where a nurse takes from whatever has stock.
                batch = medication.batches.filter(
                    quantity_on_hand__gt=0, facility=admission.facility
                ).order_by("expiry_date").first()
                roll = random.random()
                if roll < 0.82 and batch is not None:
                    record_administration(
                        scheduled_dose=dose,
                        state=MedicationAdministration.ADMINISTERED,
                        actor=staff["ward_nurse"], batch=batch,
                        administered_at=dose.due_at
                        + timedelta(minutes=random.randint(0, 35)),
                    )
                elif roll < 0.88:
                    record_administration(
                        scheduled_dose=dose,
                        state=MedicationAdministration.REFUSED,
                        actor=staff["ward_nurse"],
                        reason="Patient declined, felt nauseated.",
                    )
                elif roll < 0.92:
                    record_administration(
                        scheduled_dose=dose,
                        state=MedicationAdministration.WITHHELD,
                        actor=staff["ward_nurse"],
                        reason="Withheld pending review of renal function.",
                    )
                # The remainder are left unrecorded on purpose: an overdue dose
                # is indistinguishable from one nobody gave, and that is the
                # thing the ward list exists to surface.

    def _ward_imaging(self, admission, staff, facility):
        """An imaging request, left at a realistic point in the department."""
        from imaging.models import ImagingProcedure
        from imaging.reporting import perform, verify, write_report

        procedure = ImagingProcedure.objects.filter(
            is_active=True, modality__code="CR"
        ).order_by("?").first()
        if procedure is None:
            return
        order = ImagingOrder.objects.create(
            admission=admission, patient=admission.patient, facility=facility,
            ordered_by=staff["ward_doctor"],
            clinical_question=random.choice(IMAGING_QUESTIONS),
            priority=ImagingOrder.URGENT if random.random() < 0.3 else ImagingOrder.ROUTINE,
        )
        item = ImagingOrderItem.objects.create(order=order, procedure=procedure)

        # One critical finding is guaranteed rather than left to chance, the way
        # the laboratory arm guarantees one critical result: an empty chase list
        # demonstrates nothing about AC-98.
        forced_critical = not self._seeded_critical_finding
        reached = "verified" if forced_critical else random.choices(
            ["requested", "performed", "reported", "verified"],
            weights=[25, 20, 20, 35],
        )[0]
        if reached == "requested":
            return
        perform(
            order_item=item, actor=staff["radiographer"],
            accession_number=f"ACC-{order.pk:06d}", views_taken="PA erect",
        )
        if reached == "performed":
            return
        critical = forced_critical or random.random() < 0.16
        if critical:
            self._seeded_critical_finding = True
        report = write_report(
            order_item=item, actor=staff["radiologist"],
            findings=random.choice(IMAGING_FINDINGS),
            conclusion="Right lower lobe consolidation." if not critical
            else "Large right pneumothorax.",
            is_critical=critical,
            critical_finding="Large pneumothorax — decompress now" if critical else "",
        )
        if reached == "reported":
            return
        verify(report=report, actor=staff["radiologist"])

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
