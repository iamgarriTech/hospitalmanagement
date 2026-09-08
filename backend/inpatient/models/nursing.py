"""The nursing record: assessments, notes, fluid balance, escalations.

Two shapes here are deliberate and worth stating.

**A nursing note never changes.** There is no mutable column on the model at
all: a correction is a *new* note pointing at the one it corrects, and the
original stays exactly as written. A note that could be edited is a note whose
earlier reading cannot be trusted, and the earlier reading is often the one that
explains what someone did next. A database trigger refuses UPDATE and DELETE, so
this holds even against a bug or a console.

**An escalation carries a copy of the threshold it breached.** Thresholds are
editable configuration; an escalation raised last week must still say what the
instruction was last week. Reading it back through a live FK would silently
rewrite history the first time a ward manager adjusts a bound.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.formatting import trim_decimal

# Ward shifts. Named rather than derived from the clock because a handover at
# 19:45 belongs to the shift that is ending, not the one that starts at 20:00.
EARLY = "early"
LATE = "late"
NIGHT = "night"
SHIFT_CHOICES = [(EARLY, "Early"), (LATE, "Late"), (NIGHT, "Night")]


class NursingAssessment(models.Model):
    """A shift assessment, attached to the admission rather than to a visit.

    The observations themselves are not duplicated here — they are a
    `clinical.VitalSigns` row, so an inpatient temperature lands on the same
    trend as the one taken in clinic and the chart does not restart at
    admission. What this model adds is the nursing judgement around them.
    """

    ALERT = "alert"
    VOICE = "voice"
    PAIN = "pain"
    UNRESPONSIVE = "unresponsive"
    CONSCIOUSNESS_CHOICES = [
        (ALERT, "Alert"), (VOICE, "Responds to voice"),
        (PAIN, "Responds to pain"), (UNRESPONSIVE, "Unresponsive"),
    ]

    INDEPENDENT = "independent"
    ASSISTED = "assisted"
    BEDBOUND = "bedbound"
    MOBILITY_CHOICES = [
        (INDEPENDENT, "Independent"), (ASSISTED, "Needs assistance"),
        (BEDBOUND, "Bedbound"),
    ]

    admission = models.ForeignKey(
        "inpatient.Admission", on_delete=models.PROTECT, related_name="nursing_assessments"
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="nursing_assessments"
    )
    shift = models.CharField(max_length=10, choices=SHIFT_CHOICES)
    observations = models.OneToOneField(
        "clinical.VitalSigns", on_delete=models.PROTECT, null=True, blank=True,
        related_name="nursing_assessment",
        help_text="The observations taken as part of this assessment.",
    )

    consciousness = models.CharField(
        max_length=12, choices=CONSCIOUSNESS_CHOICES, default=ALERT
    )
    mobility = models.CharField(max_length=12, choices=MOBILITY_CHOICES, default=INDEPENDENT)
    falls_risk = models.BooleanField(default=False)
    pressure_area_concern = models.BooleanField(default=False)
    eating_and_drinking = models.CharField(max_length=255, blank=True)
    continence = models.CharField(max_length=255, blank=True)
    summary = models.TextField(blank=True)

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="nursing_assessments_recorded",
    )
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-recorded_at"]
        indexes = [models.Index(fields=["admission", "-recorded_at"])]
        permissions = [
            ("escalate_observation", "Can raise and acknowledge an observation escalation"),
        ]

    def __str__(self):
        return f"{self.patient.full_name} {self.shift} shift {self.recorded_at:%d %b}"


class NursingNote(models.Model):
    """One note, written once.

    Every field is set at creation and none is ever updated — there is no
    `superseded_by` column, because writing one would mean touching a note after
    the fact. Whether a note has been corrected is answered by looking for the
    note that supersedes it.
    """

    admission = models.ForeignKey(
        "inpatient.Admission", on_delete=models.PROTECT, related_name="nursing_notes"
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="nursing_notes"
    )
    shift = models.CharField(max_length=10, choices=SHIFT_CHOICES)
    note = models.TextField()

    supersedes = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True,
        related_name="correction",
        help_text="The note this one corrects. The original stays legible.",
    )
    correction_reason = models.CharField(max_length=255, blank=True)

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="nursing_notes_written"
    )
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-recorded_at"]
        indexes = [models.Index(fields=["admission", "-recorded_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(supersedes__isnull=True) | ~models.Q(correction_reason=""),
                name="correcting_note_states_a_reason",
            ),
        ]

    def __str__(self):
        return f"{self.patient.full_name} {self.recorded_at:%d %b %H:%M} ({self.author.email})"

    @property
    def is_superseded(self):
        return hasattr(self, "correction")

    def clean(self):
        if self.supersedes_id and self.supersedes.admission_id != self.admission_id:
            raise ValidationError(
                {"supersedes": "A correction has to belong to the same admission."}
            )


class FluidBalanceEntry(models.Model):
    """One volume in or out.

    The running balance is *not* a column: it is the sum of these rows over
    whatever period is asked for. A stored balance is a second source of truth
    that goes wrong the first time an entry is added out of order, and a fluid
    balance that is quietly wrong is a clinical decision made on bad numbers.
    """

    INTAKE = "intake"
    OUTPUT = "output"
    DIRECTION_CHOICES = [(INTAKE, "Intake"), (OUTPUT, "Output")]

    ROUTES = [
        ("oral", "Oral"), ("iv", "Intravenous"), ("ng", "Nasogastric"),
        ("other_in", "Other intake"),
        ("urine", "Urine"), ("vomit", "Vomit"), ("drain", "Drain"),
        ("stool", "Stool"), ("other_out", "Other output"),
    ]

    admission = models.ForeignKey(
        "inpatient.Admission", on_delete=models.PROTECT, related_name="fluid_entries"
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="fluid_entries"
    )
    direction = models.CharField(max_length=6, choices=DIRECTION_CHOICES)
    route = models.CharField(max_length=10, choices=ROUTES)
    volume_ml = models.PositiveIntegerField()
    note = models.CharField(max_length=255, blank=True)

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="fluid_entries_recorded"
    )
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name_plural = "fluid balance entries"
        ordering = ["-recorded_at"]
        indexes = [models.Index(fields=["admission", "-recorded_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(volume_ml__gt=0), name="fluid_volume_is_positive"
            ),
            # An intake route on an output row would make the balance nonsense
            # while still adding up, which is the worst kind of wrong.
            models.CheckConstraint(
                condition=(
                    models.Q(direction="intake", route__in=["oral", "iv", "ng", "other_in"])
                    | models.Q(
                        direction="output",
                        route__in=["urine", "vomit", "drain", "stool", "other_out"],
                    )
                ),
                name="fluid_route_matches_direction",
            ),
        ]

    def __str__(self):
        return f"{self.get_direction_display()} {self.volume_ml} mL ({self.route})"

    @property
    def signed_ml(self):
        return self.volume_ml if self.direction == self.INTAKE else -self.volume_ml


class Escalation(models.Model):
    """An observation outside the ward's thresholds, and what happened about it.

    Carries a copy of the bound and the instruction as they were when it was
    raised. The threshold row can later be edited or removed; this record still
    says what the nurse was told to do at the time.
    """

    LOW = "low"
    HIGH = "high"
    DIRECTION_CHOICES = [(LOW, "Below the low bound"), (HIGH, "Above the high bound")]

    admission = models.ForeignKey(
        "inpatient.Admission", on_delete=models.PROTECT, related_name="escalations"
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="escalations"
    )
    observations = models.ForeignKey(
        "clinical.VitalSigns", on_delete=models.PROTECT, related_name="escalations"
    )
    threshold = models.ForeignKey(
        "inpatient.EscalationThreshold", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="escalations",
    )

    measurement = models.CharField(max_length=30)
    value = models.DecimalField(max_digits=8, decimal_places=2)
    direction = models.CharField(max_length=4, choices=DIRECTION_CHOICES)
    breached_bound = models.DecimalField(max_digits=8, decimal_places=2)
    instruction = models.CharField(max_length=255, blank=True)

    raised_at = models.DateTimeField(default=timezone.now, db_index=True)
    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="escalations_raised"
    )

    # Who was told, and when. Separate from acknowledgement because telling
    # someone and their responding are different events, and the gap between
    # them is the thing a review asks about.
    escalated_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="escalations_received",
    )
    escalated_at = models.DateTimeField(null=True, blank=True)

    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="escalations_acknowledged",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    action_taken = models.TextField(blank=True)

    class Meta:
        ordering = ["-raised_at"]
        indexes = [
            models.Index(fields=["admission", "-raised_at"]),
            # The ward list is "everything still outstanding", so that is the
            # query the index is for.
            models.Index(
                fields=["-raised_at"],
                condition=models.Q(acknowledged_at__isnull=True),
                name="outstanding_escalations",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(acknowledged_at__isnull=True)
                | (models.Q(acknowledged_by__isnull=False) & ~models.Q(action_taken="")),
                name="acknowledged_escalation_says_who_and_what",
            ),
        ]

    def __str__(self):
        return f"{self.patient.full_name} {self.measurement} {self.value} ({self.direction})"

    @property
    def is_outstanding(self):
        return self.acknowledged_at is None

    @property
    def minutes_waiting(self):
        end = self.acknowledged_at or timezone.now()
        return int((end - self.raised_at).total_seconds() // 60)

    @property
    def summary(self):
        bound = "below" if self.direction == self.LOW else "above"
        return (
            f"{self.get_measurement_display()} {trim_decimal(self.value)} — "
            f"{bound} the ward bound of {trim_decimal(self.breached_bound)}"
        )

    def get_measurement_display(self):
        from .wards import EscalationThreshold

        return dict(EscalationThreshold.MEASUREMENTS).get(self.measurement, self.measurement)

    def acknowledge(self, *, actor, action_taken, at=None):
        if not self.is_outstanding:
            raise ValidationError("That escalation has already been acknowledged.")
        if not action_taken.strip():
            raise ValidationError(
                {"action_taken": "Say what was done. An acknowledgement with no "
                                 "action is a tick box, not a record."}
            )
        self.acknowledged_by = actor
        self.acknowledged_at = at or timezone.now()
        self.action_taken = action_taken.strip()
        self.save(update_fields=["acknowledged_by", "acknowledged_at", "action_taken"])
        return self
