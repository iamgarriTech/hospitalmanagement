"""Admission, the stay, and discharge.

An admission request and an admission are separate on purpose: a clinician
decides a patient needs a bed, and the ward decides which bed and when. Bundling
them would mean a doctor cannot ask for a bed without knowing whether one is
free, which is not how a hospital works.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from patients.models import NumberSequence


class AdmissionRequest(models.Model):
    PENDING = "pending"
    ADMITTED = "admitted"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (PENDING, "Awaiting a bed"), (ADMITTED, "Admitted"),
        (DECLINED, "Declined"), (CANCELLED, "Cancelled"),
    ]

    ROUTINE = "routine"
    URGENT = "urgent"
    PRIORITY_CHOICES = [(ROUTINE, "Routine"), (URGENT, "Urgent")]

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="admission_requests"
    )
    visit = models.ForeignKey(
        "visits.Visit", on_delete=models.PROTECT, null=True, blank=True,
        related_name="admission_requests",
        help_text="The attendance the request came out of, where there was one.",
    )
    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT, related_name="admission_requests"
    )
    ward = models.ForeignKey(
        "wards.Ward", on_delete=models.PROTECT, related_name="admission_requests",
        help_text="Where the requesting clinician believes the patient should go.",
    )

    reason = models.TextField()
    working_diagnosis = models.CharField(max_length=255)
    responsible_consultant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="admission_requests_under_care",
    )
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=ROUTINE)

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="admission_requests_made"
    )
    requested_at = models.DateTimeField(default=timezone.now)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="admission_requests_decided",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-priority", "requested_at"]
        indexes = [models.Index(fields=["ward", "status", "requested_at"])]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(status="declined") | ~models.Q(decline_reason=""),
                name="declined_request_states_a_reason",
            )
        ]
        permissions = [
            ("decide_admissionrequest", "Can accept or decline an admission request"),
        ]

    def __str__(self):
        return f"{self.patient.full_name} → {self.ward.name} ({self.status})"

    @property
    def waiting_minutes(self):
        end = self.decided_at or timezone.now()
        return int((end - self.requested_at).total_seconds() // 60)


class Admission(models.Model):
    ADMITTED = "admitted"
    DISCHARGE_PLANNED = "discharge_planned"
    DISCHARGED = "discharged"
    STATUS_CHOICES = [
        (ADMITTED, "Admitted"),
        (DISCHARGE_PLANNED, "Discharge planned"),
        (DISCHARGED, "Discharged"),
    ]

    HOME = "home"
    TRANSFERRED = "transferred"
    ABSCONDED = "absconded"
    DIED = "died"
    DESTINATION_CHOICES = [
        (HOME, "Home"), (TRANSFERRED, "Transferred to another facility"),
        (ABSCONDED, "Absconded"), (DIED, "Died"),
    ]

    admission_number = models.CharField(max_length=40, unique=True, editable=False)
    request = models.OneToOneField(
        AdmissionRequest, on_delete=models.PROTECT, null=True, blank=True,
        related_name="admission",
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="admissions"
    )
    visit = models.ForeignKey(
        "visits.Visit", on_delete=models.PROTECT, null=True, blank=True,
        related_name="admissions",
    )
    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT, related_name="admissions"
    )

    admission_reason = models.TextField()
    admission_diagnosis = models.CharField(max_length=255)
    responsible_consultant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="patients_under_care"
    )
    admitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="admissions_made"
    )
    admitted_at = models.DateTimeField(default=timezone.now)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=ADMITTED)

    # Discharge planning, recorded before the discharge itself.
    expected_discharge_date = models.DateField(null=True, blank=True)
    discharge_destination = models.CharField(
        max_length=15, choices=DESTINATION_CHOICES, blank=True
    )
    discharge_plan_notes = models.TextField(blank=True)

    discharged_at = models.DateTimeField(null=True, blank=True)
    discharged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="discharges_completed",
    )
    discharge_diagnosis = models.CharField(max_length=255, blank=True)
    follow_up_instructions = models.TextField(blank=True)
    # Recorded when someone discharges despite an outstanding balance.
    billing_override_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-admitted_at"]
        indexes = [
            models.Index(fields=["facility", "status", "-admitted_at"]),
            models.Index(fields=["patient", "-admitted_at"]),
        ]
        constraints = [
            # One open admission per patient. A patient cannot be an inpatient
            # twice, and a duplicate admission is how a stay ends up split
            # across two records with half the medication on each.
            models.UniqueConstraint(
                fields=["patient"],
                condition=~models.Q(status="discharged"),
                name="one_open_admission_per_patient",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="discharged")
                | (models.Q(discharged_at__isnull=False) & ~models.Q(discharge_diagnosis="")),
                name="discharged_admission_is_complete",
            ),
        ]
        permissions = [
            ("admit_patient", "Can admit a patient and allocate a bed"),
            ("transfer_patient", "Can move an inpatient between beds or wards"),
            ("plan_discharge", "Can record a discharge plan"),
            ("discharge_patient", "Can complete a discharge"),
            ("override_discharge_billing", "Can discharge despite an unpaid balance"),
        ]

    def __str__(self):
        return f"{self.admission_number} — {self.patient.full_name}"

    def save(self, *args, **kwargs):
        if not self.admission_number:
            self.admission_number = NumberSequence.allocate("admission_number")
        return super().save(*args, **kwargs)

    # --- where the patient is -------------------------------------------------

    @property
    def current_occupancy(self):
        for occupancy in self.occupancies.all():
            if occupancy.period.upper is None:
                return occupancy
        return None

    @property
    def current_bed(self):
        occupancy = self.current_occupancy
        return occupancy.bed if occupancy else None

    @property
    def current_ward(self):
        bed = self.current_bed
        return bed.room.ward if bed else None

    @property
    def is_open(self):
        return self.status != self.DISCHARGED

    @property
    def length_of_stay_nights(self):
        """Nights, by calendar date. A patient admitted at 23:00 and discharged
        at 09:00 the next morning stayed one night, not eleven hours."""
        end = self.discharged_at or timezone.now()
        return max((end.date() - self.admitted_at.date()).days, 0)

    @property
    def movement(self):
        """Every bed this patient has been in, in order — the answer to "where
        has this patient been"."""
        return [
            {
                "bed": str(occupancy.bed),
                "ward": occupancy.bed.room.ward.name,
                "from": occupancy.period.lower,
                "to": occupancy.period.upper,
                "nights": occupancy.nights,
            }
            for occupancy in self.occupancies.select_related("bed__room__ward").order_by(
                "period"
            )
        ]


class BedTransfer(models.Model):
    """A move from one bed to another, and why.

    The occupancies alone say where the patient has been; this says who decided
    to move them and what for, which is the part a later reviewer asks about.
    """

    admission = models.ForeignKey(
        Admission, on_delete=models.PROTECT, related_name="transfers"
    )
    from_occupancy = models.ForeignKey(
        "wards.BedOccupancy", on_delete=models.PROTECT, related_name="transfers_out"
    )
    to_occupancy = models.ForeignKey(
        "wards.BedOccupancy", on_delete=models.PROTECT, related_name="transfers_in"
    )
    reason = models.CharField(max_length=255)
    authorised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="transfers_authorised"
    )
    moved_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-moved_at"]

    def __str__(self):
        return f"{self.admission.patient.full_name}: {self.from_occupancy.bed} → {self.to_occupancy.bed}"

    @property
    def changed_ward(self):
        return self.from_occupancy.bed.room.ward_id != self.to_occupancy.bed.room.ward_id


@transaction.atomic
def transfer(*, admission, to_bed, reason, actor, at=None):
    """Move an inpatient to another bed.

    The old occupancy closes and the new one opens in one transaction, so the
    patient is never recorded in two beds and never in none. The exclusion
    constraint on the occupancy period is what makes that safe under concurrency
    rather than merely intended.
    """
    from wards.models import BedOccupancy

    if not reason.strip():
        raise ValidationError("A reason is required to move a patient.")
    if not admission.is_open:
        raise ValidationError("That admission has been discharged.")

    current = admission.current_occupancy
    if current is None:
        raise ValidationError("This admission has no bed to move from.")
    if current.bed_id == to_bed.pk:
        raise ValidationError("The patient is already in that bed.")

    moment = at or timezone.now()
    current.close(actor=actor, at=moment, reason="transferred")
    replacement = BedOccupancy.allocate(
        bed=to_bed, admission=admission, actor=actor, at=moment
    )
    return BedTransfer.objects.create(
        admission=admission,
        from_occupancy=current,
        to_occupancy=replacement,
        reason=reason.strip(),
        authorised_by=actor,
        moved_at=moment,
    )
