"""The medication administration record.

Called the MAR because that is what nurses call it.

The shape here follows one fact: **a due dose and an administration are
different things**. A dose becomes due whether or not anyone gives it, and the
interesting clinical events are the ones where nothing was administered — a dose
missed, refused or deliberately withheld. A model that only records
administrations cannot answer "was this patient's midday antibiotic given?",
which is the question a ward round actually asks.

So a prescription generates a schedule of due doses, and each due dose gets at
most one outcome. The outcome names who was responsible and when, always.
"""
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

# Standard ward drug rounds. A dose due "three times a day" is not due every
# eight hours to the minute — it is due at the rounds the ward actually runs.
STANDARD_TIMES = {
    1: [8],
    2: [8, 20],
    3: [8, 14, 20],
    4: [6, 12, 18, 22],
    5: [6, 10, 14, 18, 22],
    6: [2, 6, 10, 14, 18, 22],
}


def times_for(frequency_per_day):
    """The hours of the day a dose at this frequency falls due."""
    if frequency_per_day in STANDARD_TIMES:
        return STANDARD_TIMES[frequency_per_day]
    if frequency_per_day <= 0:
        return [8]
    # Anything unusual is spread evenly from the morning round.
    step = 24 / frequency_per_day
    return [int((8 + step * index) % 24) for index in range(frequency_per_day)]


class ScheduledDose(models.Model):
    """One dose falling due at one time.

    Dose and unit are copied from the prescription rather than read through it:
    a prescriber changing the dose tomorrow must not silently rewrite what was
    due — and given — yesterday.
    """

    prescription_item = models.ForeignKey(
        "pharmacy.PrescriptionItem", on_delete=models.PROTECT, related_name="scheduled_doses"
    )
    admission = models.ForeignKey(
        "inpatient.Admission", on_delete=models.PROTECT, related_name="scheduled_doses"
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="scheduled_doses"
    )

    due_at = models.DateTimeField(db_index=True)
    sequence = models.PositiveIntegerField(help_text="Position in the course, from 1.")
    dose = models.DecimalField(max_digits=10, decimal_places=3)
    dose_unit = models.CharField(max_length=20)
    route = models.CharField(max_length=15)

    # A discontinued course keeps its given doses and loses its future ones.
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["due_at", "prescription_item_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["prescription_item", "due_at"],
                name="one_dose_per_item_per_due_time",
            ),
            models.CheckConstraint(
                condition=models.Q(cancelled_at__isnull=True) | ~models.Q(cancelled_reason=""),
                name="cancelled_dose_states_a_reason",
            ),
        ]
        indexes = [
            models.Index(fields=["admission", "due_at"]),
            # For "what is outstanding on this ward". Without `due_at` in the
            # index the planner fetched every dose for each admission — a
            # hundred rows a patient — and filtered the date in the heap.
            # Partial, because a cancelled dose is never outstanding, and a
            # long-running ward's table is mostly history.
            models.Index(
                fields=["admission", "due_at"],
                condition=models.Q(cancelled_at__isnull=True),
                name="outstanding_doses_by_admission",
            ),
        ]

    def __str__(self):
        return f"{self.prescription_item.medication.generic_name} due {self.due_at:%d %b %H:%M}"

    @property
    def is_cancelled(self):
        return self.cancelled_at is not None

    @property
    def minutes_overdue(self):
        """How late this dose is, or None if it has an outcome or is not yet due."""
        if self.outcome is not None:
            return None
        minutes = int((timezone.now() - self.due_at).total_seconds() // 60)
        return minutes if minutes > 0 else None

    @property
    def outcome(self):
        """The single recorded outcome for this dose, if there is one.

        Walks `all()` rather than calling `.first()`. `.first()` adds ordering
        and a slice, so it issues a fresh query *even when the relation has been
        prefetched* — and the ward board reads this once per due dose. On a full
        40-bed ward that was 305 extra queries in one request, which under 50
        concurrent users came out as 4.2 seconds at p95 against a 500 ms target.
        The unique constraint on `scheduled_dose` means there is at most one.
        """
        for administration in self.administrations.all():
            return administration
        return None

    def status(self, *, overdue_after_minutes=60, now=None):
        """What the chart cell should say.

        `due` and `overdue` are the states with no outcome yet — and `overdue`
        is the one a ward needs surfaced, because a dose nobody has recorded is
        indistinguishable from a dose nobody gave.
        """
        # A recorded outcome outranks a cancellation. If the dose was given and
        # the course was stopped afterwards, the chart must still say it was
        # given — what reached the patient is the more important fact.
        outcome = self.outcome
        if outcome is not None:
            return outcome.state
        if self.is_cancelled:
            return MedicationAdministration.DISCONTINUED
        moment = now or timezone.now()
        if moment > self.due_at + timedelta(minutes=overdue_after_minutes):
            return "overdue"
        if moment >= self.due_at:
            return "due"
        return "scheduled"


class MedicationAdministration(models.Model):
    """What happened to one due dose.

    The state set is the PRD's, in full. Four of the six mean the drug did not
    reach the patient, and each of those requires a reason — "missed" with no
    explanation is not a record, it is a gap someone will have to guess about.
    """

    ADMINISTERED = "administered"
    MISSED = "missed"
    DELAYED = "delayed"
    REFUSED = "refused"
    WITHHELD = "withheld"
    DISCONTINUED = "discontinued"
    STATE_CHOICES = [
        (ADMINISTERED, "Administered"),
        (MISSED, "Missed"),
        (DELAYED, "Given late"),
        (REFUSED, "Refused by patient"),
        (WITHHELD, "Withheld"),
        (DISCONTINUED, "Discontinued"),
    ]

    # The states where nothing reached the patient, or where a clinical decision
    # was taken. All of them have to say why.
    REQUIRE_REASON = {MISSED, REFUSED, WITHHELD, DISCONTINUED}
    # The states where stock actually left the trolley.
    CONSUMES_STOCK = {ADMINISTERED, DELAYED}

    scheduled_dose = models.ForeignKey(
        ScheduledDose, on_delete=models.PROTECT, related_name="administrations"
    )
    admission = models.ForeignKey(
        "inpatient.Admission", on_delete=models.PROTECT, related_name="administrations"
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="administrations"
    )

    state = models.CharField(max_length=15, choices=STATE_CHOICES)
    # Never null. A dose with no named nurse is not an auditable record, which
    # is the whole point of a drug chart.
    administered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="administrations_given"
    )
    recorded_at = models.DateTimeField(default=timezone.now)
    administered_at = models.DateTimeField(
        null=True, blank=True, help_text="When the drug actually reached the patient."
    )

    dose_given = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True
    )
    dose_unit = models.CharField(max_length=20, blank=True)
    batch = models.ForeignKey(
        "pharmacy.StockBatch", on_delete=models.PROTECT, null=True, blank=True,
        related_name="administrations",
    )

    reason = models.TextField(blank=True)
    note = models.CharField(max_length=255, blank=True)
    # Recorded when a nurse gives a drug past a safety warning.
    override_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-recorded_at"]
        constraints = [
            # One outcome per due dose. This is what makes a double-tap or a
            # retried request produce one administration rather than two, and a
            # duplicate dose is the error this whole model exists to prevent.
            models.UniqueConstraint(
                fields=["scheduled_dose"], name="one_outcome_per_scheduled_dose"
            ),
            models.CheckConstraint(
                condition=~models.Q(state__in=["missed", "refused", "withheld", "discontinued"])
                | ~models.Q(reason=""),
                name="unadministered_dose_states_a_reason",
            ),
            models.CheckConstraint(
                condition=~models.Q(state__in=["administered", "delayed"])
                | models.Q(administered_at__isnull=False),
                name="administered_dose_records_when",
            ),
        ]
        indexes = [models.Index(fields=["admission", "-recorded_at"])]

    def __str__(self):
        return f"{self.get_state_display()} by {self.administered_by.email}"

    @property
    def minutes_late(self):
        if self.administered_at is None:
            return None
        delta = self.administered_at - self.scheduled_dose.due_at
        return int(delta.total_seconds() // 60)

    def clean(self):
        if self.state in self.REQUIRE_REASON and not self.reason.strip():
            raise ValidationError(
                {"reason": f"A reason is required when a dose is {self.state}."}
            )
        if self.state in self.CONSUMES_STOCK and self.administered_at is None:
            raise ValidationError(
                {"administered_at": "Record when the dose was actually given."}
            )
