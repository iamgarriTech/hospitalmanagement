"""Consultations, their version history, and vital signs.

The versioning here is the reason this app exists rather than a flat notes table.
A clinical record is evidence: what a clinician wrote on a given day, and what they knew
when they wrote it. Correcting today's entry must never quietly rewrite an older one, and
an amendment has to say who changed it and why.

So the narrative and the diagnoses both live on an immutable version. A draft is editable
while the consultation is happening; once finalised, every further change appends a new
version and the previous one stays exactly as it was.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone

from core.models import Coding


class Encounter(models.Model):
    DRAFT = "draft"
    FINAL = "final"
    AMENDED = "amended"
    STATUS_CHOICES = [
        (DRAFT, "Draft"), (FINAL, "Final"), (AMENDED, "Amended"),
    ]

    CONSULTATION = "consultation"
    REVIEW = "review"
    TRIAGE = "triage"
    DAILY_REVIEW = "daily_review"
    TYPE_CHOICES = [
        (CONSULTATION, "Consultation"), (REVIEW, "Review"), (TRIAGE, "Triage"),
        (DAILY_REVIEW, "Inpatient daily review"),
    ]

    # A record belongs to an attendance or to an admission. An inpatient stay
    # outlives the visit that started it — a daily review on day nine has
    # nothing to do with that morning's outpatient queue — and a direct
    # admission has no visit at all.
    visit = models.ForeignKey(
        "visits.Visit", on_delete=models.PROTECT, null=True, blank=True,
        related_name="encounters",
    )
    admission = models.ForeignKey(
        "inpatient.Admission", on_delete=models.PROTECT, null=True, blank=True,
        related_name="encounters",
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="encounters"
    )
    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT, related_name="encounters"
    )
    clinician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="encounters"
    )
    encounter_type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default=CONSULTATION
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)

    started_at = models.DateTimeField(default=timezone.now)
    finalised_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["patient", "-started_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(visit__isnull=False) | models.Q(admission__isnull=False),
                name="encounter_belongs_to_a_visit_or_an_admission",
            )
        ]
        permissions = [
            ("finalise_encounter", "Can finalise a consultation record"),
            ("amend_encounter", "Can amend a finalised consultation record"),
        ]

    def __str__(self):
        return f"{self.get_encounter_type_display()} — {self.patient.full_name}"

    @property
    def current_version(self):
        """Walk the prefetched versions instead of filtering them.

        `self.versions.filter(...)` issues a fresh query even when the relation
        has been prefetched, because a filtered manager cannot use the cache.
        With one query per encounter for this and another for the count, a list
        of fifty encounters cost 158 queries and the patient profile took over
        three seconds under load. Iterating the cache costs none.
        """
        for version in self.versions.all():
            if version.is_current:
                return version
        return None

    @property
    def version_count(self):
        # len() over the prefetched list; .count() would be another query each.
        return len(self.versions.all())

    @transaction.atomic
    def finalise(self, *, actor):
        if self.status != self.DRAFT:
            raise ValidationError("Only a draft encounter can be finalised.")
        version = self.current_version
        if version is None:
            raise ValidationError("Nothing has been recorded on this encounter yet.")
        self.status = self.FINAL
        self.finalised_at = timezone.now()
        self.save(update_fields=["status", "finalised_at"])
        return version

    @transaction.atomic
    def amend(self, *, actor, reason, changes, diagnoses=None):
        """Append a new version. The previous one is left untouched.

        A reason is mandatory: an amended clinical record without a stated reason is not
        auditable, and this is the field a later reviewer actually reads.
        """
        if self.status == self.DRAFT:
            raise ValidationError(
                "This encounter is still a draft; edit it directly rather than amending."
            )
        if not (reason or "").strip():
            raise ValidationError("A reason is required to amend a clinical record.")

        previous = EncounterVersion.objects.select_for_update().get(
            encounter=self, is_current=True
        )
        carried = {field: getattr(previous, field) for field in EncounterVersion.NARRATIVE}
        carried.update({key: value for key, value in changes.items() if key in carried})

        self.versions.filter(is_current=True).update(is_current=False)
        version = EncounterVersion.objects.create(
            encounter=self,
            version_number=previous.version_number + 1,
            authored_by=actor,
            amendment_reason=reason.strip(),
            amends=previous,
            is_current=True,
            **carried,
        )
        # Diagnoses belong to the version, so the earlier set survives the amendment.
        source = diagnoses if diagnoses is not None else [
            {
                "description": diagnosis.description,
                "certainty": diagnosis.certainty,
                "is_primary": diagnosis.is_primary,
                "code_system": diagnosis.code_system,
                "code": diagnosis.code,
                "code_display": diagnosis.code_display,
                "code_version": diagnosis.code_version,
            }
            for diagnosis in previous.diagnoses.all()
        ]
        for entry in source:
            Diagnosis.objects.create(version=version, **entry)

        self.status = self.AMENDED
        self.save(update_fields=["status"])
        return version


class EncounterVersion(models.Model):
    """One immutable revision of a consultation record."""

    NARRATIVE = [
        "presenting_complaint",
        "history_of_presenting_complaint",
        "past_medical_history",
        "surgical_history",
        "family_history",
        "social_history",
        "medication_history",
        "examination_findings",
        "clinical_notes",
        "treatment_plan",
        "follow_up_plan",
    ]

    encounter = models.ForeignKey(
        Encounter, on_delete=models.CASCADE, related_name="versions"
    )
    version_number = models.PositiveIntegerField()
    is_current = models.BooleanField(default=True)

    presenting_complaint = models.TextField(blank=True)
    history_of_presenting_complaint = models.TextField(blank=True)
    past_medical_history = models.TextField(blank=True)
    surgical_history = models.TextField(blank=True)
    family_history = models.TextField(blank=True)
    social_history = models.TextField(blank=True)
    medication_history = models.TextField(blank=True)
    examination_findings = models.TextField(blank=True)
    clinical_notes = models.TextField(blank=True)
    treatment_plan = models.TextField(blank=True)
    follow_up_plan = models.TextField(blank=True)

    authored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="encounter_versions"
    )
    authored_at = models.DateTimeField(auto_now_add=True)
    amendment_reason = models.TextField(blank=True)
    amends = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="amended_by"
    )

    class Meta:
        ordering = ["encounter", "version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["encounter", "version_number"], name="encounter_version_unique"
            ),
            models.UniqueConstraint(
                fields=["encounter"],
                condition=models.Q(is_current=True),
                name="one_current_version_per_encounter",
            ),
            models.CheckConstraint(
                condition=models.Q(version_number=1) | ~models.Q(amendment_reason=""),
                name="amendment_states_a_reason",
            ),
        ]

    def __str__(self):
        return f"{self.encounter_id} v{self.version_number}"


class Diagnosis(Coding):
    """Attached to a version, not the encounter.

    This is what stops an amendment today from rewriting what was diagnosed at an
    earlier consultation.
    """

    CONFIRMED = "confirmed"
    PROVISIONAL = "provisional"
    DIFFERENTIAL = "differential"
    CERTAINTY_CHOICES = [
        (CONFIRMED, "Confirmed"),
        (PROVISIONAL, "Provisional"),
        (DIFFERENTIAL, "Differential"),
    ]

    version = models.ForeignKey(
        EncounterVersion, on_delete=models.CASCADE, related_name="diagnoses"
    )
    description = models.CharField(max_length=255)
    certainty = models.CharField(
        max_length=15, choices=CERTAINTY_CHOICES, default=PROVISIONAL
    )
    is_primary = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "diagnoses"
        ordering = ["-is_primary", "id"]

    def __str__(self):
        return f"{self.description} ({self.certainty})"


class VitalSigns(models.Model):
    """One set of observations taken at one moment.

    Not versioned: a reading is a reading. A wrong entry is corrected by recording a new
    set and marking the old one an error, so the original stays visible — the same reason
    clinical notes are not overwritten.

    The bounds are deliberately wide enough to admit genuinely extreme but real values,
    and narrow enough to catch a slipped decimal point or a wrong unit.
    """

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="vital_signs"
    )
    visit = models.ForeignKey(
        "visits.Visit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="vital_signs",
    )
    # Observations taken on the ward belong to the stay. The patient FK above is
    # what makes the trend one series: an inpatient temperature sits on the same
    # chart as the one taken in clinic rather than starting a new one.
    admission = models.ForeignKey(
        "inpatient.Admission",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="vital_signs",
    )
    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT, related_name="vital_signs"
    )

    temperature_c = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(Decimal("25.0")), MaxValueValidator(Decimal("45.0"))],
    )
    systolic_bp = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(40), MaxValueValidator(300)]
    )
    diastolic_bp = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(20), MaxValueValidator(200)]
    )
    pulse_bpm = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(20), MaxValueValidator(250)]
    )
    respiratory_rate = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(4), MaxValueValidator(80)]
    )
    oxygen_saturation = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(40), MaxValueValidator(100)]
    )
    weight_kg = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.30")), MaxValueValidator(Decimal("400.00"))],
    )
    height_cm = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(Decimal("20.0")), MaxValueValidator(Decimal("260.0"))],
    )
    blood_glucose_mmol = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.5")), MaxValueValidator(Decimal("50.0"))],
    )
    pain_score = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(10)]
    )

    is_erroneous = models.BooleanField(
        default=False, help_text="Marked as recorded in error. The reading is kept."
    )
    error_reason = models.TextField(blank=True)

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="vitals_recorded"
    )
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "vital signs"
        verbose_name_plural = "vital signs"
        ordering = ["-recorded_at"]
        indexes = [models.Index(fields=["patient", "-recorded_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(systolic_bp__isnull=True)
                | models.Q(diastolic_bp__isnull=True)
                | models.Q(systolic_bp__gt=models.F("diastolic_bp")),
                name="systolic_above_diastolic",
            ),
            models.CheckConstraint(
                condition=models.Q(is_erroneous=False) | ~models.Q(error_reason=""),
                name="erroneous_vitals_state_a_reason",
            ),
        ]

    def __str__(self):
        return f"{self.patient.full_name} @ {self.recorded_at:%Y-%m-%d %H:%M}"

    @property
    def bmi(self):
        """Derived, never entered. Recomputes whenever height or weight changes."""
        if not (self.weight_kg and self.height_cm):
            return None
        metres = float(self.height_cm) / 100
        if metres <= 0:
            return None
        return round(float(self.weight_kg) / (metres * metres), 1)

    @property
    def blood_pressure(self):
        if self.systolic_bp and self.diastolic_bp:
            return f"{self.systolic_bp}/{self.diastolic_bp}"
        return None


# --- referrals --------------------------------------------------------------
#
# Here rather than in an app of their own: a referral is a clinical
# communication about a patient — a reason, a question, and what was sent —
# and it belongs beside the encounter that prompted it.


class Referral(models.Model):
    """Sending a patient to somebody else. AC-164, AC-165.

    Internal and external in one model, because the clinical content is
    identical — who, why, what question, what was sent, what came back — and
    only the destination differs. Two models would mean writing the letter
    generator twice.
    """

    INTERNAL = "internal"
    EXTERNAL = "external"
    KIND_CHOICES = [
        (INTERNAL, "Within this hospital group"),
        (EXTERNAL, "To another organisation"),
    ]

    DRAFT = "draft"
    SENT = "sent"
    ACCEPTED = "accepted"
    SEEN = "seen"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (DRAFT, "Draft"), (SENT, "Sent"), (ACCEPTED, "Accepted"),
        (SEEN, "Patient seen"), (DECLINED, "Declined"), (CANCELLED, "Cancelled"),
    ]

    ROUTINE = "routine"
    URGENT = "urgent"
    TWO_WEEK = "two_week"
    URGENCY_CHOICES = [
        (ROUTINE, "Routine"), (URGENT, "Urgent"),
        (TWO_WEEK, "Urgent, suspected cancer"),
    ]

    reference = models.CharField(max_length=30, unique=True)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="referrals"
    )
    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT, related_name="referrals"
    )
    encounter = models.ForeignKey(
        Encounter, on_delete=models.PROTECT, null=True, blank=True,
        related_name="referrals",
        help_text="The consultation this came out of, where there was one.",
    )
    visit = models.ForeignKey(
        "visits.Visit", on_delete=models.PROTECT, null=True, blank=True,
        related_name="referrals",
    )
    admission = models.ForeignKey(
        "inpatient.Admission", on_delete=models.PROTECT, null=True, blank=True,
        related_name="referrals",
    )

    # --- internal destination ---
    to_department = models.ForeignKey(
        "facilities.Department", on_delete=models.PROTECT, null=True, blank=True,
        related_name="referrals_in",
    )
    to_clinician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="referrals_received",
        help_text="Named clinician, where the referral is to a person rather than "
                  "a department.",
    )

    # --- external destination ---
    to_organisation = models.CharField(max_length=200, blank=True)
    to_external_clinician = models.CharField(max_length=200, blank=True)
    to_address = models.TextField(blank=True)

    # --- the clinical content ---
    reason = models.TextField(help_text="Why this patient is being referred.")
    clinical_question = models.TextField(
        help_text="What is being asked of the person receiving it. A referral "
                  "without a question is a transfer of responsibility, not a "
                  "request for an opinion."
    )
    what_was_sent = models.TextField(
        blank=True,
        help_text="Results, images and letters that went with it.",
    )
    urgency = models.CharField(max_length=10, choices=URGENCY_CHOICES, default=ROUTINE)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)

    referred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="referrals_made"
    )
    referred_at = models.DateTimeField(default=timezone.now)
    sent_at = models.DateTimeField(null=True, blank=True)

    # --- what came back. AC-165 ---
    outcome = models.TextField(
        blank=True, help_text="What the receiving clinician found or advised."
    )
    outcome_recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="referral_outcomes_recorded",
    )
    outcome_recorded_at = models.DateTimeField(null=True, blank=True)

    # AC-166. Counted rather than stored, because the letter is assembled from
    # the record on every read — which is what makes a reprint identical
    # rather than merely intended to be.
    print_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-referred_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(reason=""), name="referral_states_a_reason"
            ),
            models.CheckConstraint(
                condition=~models.Q(clinical_question=""),
                name="referral_asks_a_question",
            ),
            # An internal referral goes to a department or a person; an
            # external one goes to a named organisation. Neither may be blank,
            # or the referral goes nowhere.
            models.CheckConstraint(
                condition=(
                    models.Q(kind="internal", to_department__isnull=False)
                    | models.Q(kind="internal", to_clinician__isnull=False)
                    | models.Q(kind="external") & ~models.Q(to_organisation="")
                ),
                name="referral_has_a_destination",
            ),
            models.CheckConstraint(
                condition=~models.Q(status__in=["seen", "declined"])
                | models.Q(outcome_recorded_at__isnull=False),
                name="closed_referral_records_its_outcome",
            ),
        ]
        permissions = [
            ("make_referral", "Can refer a patient"),
            ("record_referral_outcome", "Can record what a referral came back with"),
        ]

    def __str__(self):
        return f"{self.reference} — {self.patient.full_name}"

    @property
    def destination(self):
        """Where it is going, in words, whichever kind it is."""
        if self.kind == self.INTERNAL:
            if self.to_clinician is not None:
                return self.to_clinician.full_name
            return self.to_department.name if self.to_department else "—"
        parts = [self.to_external_clinician, self.to_organisation]
        return ", ".join(part for part in parts if part)

    @property
    def is_open(self):
        return self.status in (self.DRAFT, self.SENT, self.ACCEPTED)


class ReferralPrint(models.Model):
    """Every time a referral letter was produced. AC-166.

    A row per print rather than a counter alone, because "who printed this
    patient's referral, and when" is a question that gets asked — and a
    counter cannot answer it.
    """

    referral = models.ForeignKey(
        Referral, on_delete=models.CASCADE, related_name="prints"
    )
    printed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="referral_prints",
    )
    printed_at = models.DateTimeField(default=timezone.now)
    is_reprint = models.BooleanField(default=False)

    class Meta:
        ordering = ["-printed_at", "-id"]

    def __str__(self):
        kind = "Reprint" if self.is_reprint else "Print"
        return f"{kind} of {self.referral.reference}"
