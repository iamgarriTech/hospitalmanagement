"""Visits and the patient queue.

The queue is not a list with a flag on it — it is where the patient actually is in the
building, and reception needs to answer "who is waiting, who is with a doctor, who went
to the lab and hasn't come back". So visit status *is* the queue state, every change is
recorded with who made it, and illegal moves are refused rather than accepted quietly.
"""
from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from patients.models import NumberSequence


class InvalidTransition(Exception):
    """A queue move that the workflow does not allow."""


class Visit(models.Model):
    SCHEDULED = "scheduled"
    WAITING = "waiting"
    CALLED = "called"
    IN_CONSULTATION = "in_consultation"
    SENT_FOR_INVESTIGATION = "sent_for_investigation"
    SENT_TO_PHARMACY = "sent_to_pharmacy"
    SENT_FOR_BILLING = "sent_for_billing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

    # Admission ends the attendance: the stay takes over, and the patient must
    # not also be sitting in the outpatient queue. Terminal here, because
    # anything further about them belongs to the admission.
    ADMITTED = "admitted"

    STATUS_CHOICES = [
        (SCHEDULED, "Scheduled"),
        (WAITING, "Waiting"),
        (CALLED, "Called"),
        (IN_CONSULTATION, "In consultation"),
        (SENT_FOR_INVESTIGATION, "Sent for investigation"),
        (SENT_TO_PHARMACY, "Sent to pharmacy"),
        (SENT_FOR_BILLING, "Sent for billing"),
        (ADMITTED, "Admitted"),
        (COMPLETED, "Completed"),
        (CANCELLED, "Cancelled"),
    ]

    # A patient can come back from the lab or the pharmacy, so this is a graph rather
    # than a line. Terminal states have no exits: a completed visit is not reopened,
    # it is followed by a new one.
    TRANSITIONS = {
        SCHEDULED: {WAITING, CANCELLED},
        # A patient can deteriorate in the waiting room, so admission is
        # reachable from anywhere the patient is still in the building.
        WAITING: {CALLED, ADMITTED, CANCELLED},
        CALLED: {IN_CONSULTATION, WAITING, ADMITTED, CANCELLED},
        IN_CONSULTATION: {
            SENT_FOR_INVESTIGATION, SENT_TO_PHARMACY, SENT_FOR_BILLING, ADMITTED,
            COMPLETED, WAITING,
        },
        SENT_FOR_INVESTIGATION: {
            IN_CONSULTATION, WAITING, SENT_TO_PHARMACY, SENT_FOR_BILLING, ADMITTED,
            COMPLETED,
        },
        SENT_TO_PHARMACY: {IN_CONSULTATION, SENT_FOR_BILLING, ADMITTED, COMPLETED},
        SENT_FOR_BILLING: {IN_CONSULTATION, SENT_TO_PHARMACY, ADMITTED, COMPLETED},
        ADMITTED: set(),
        COMPLETED: set(),
        CANCELLED: set(),
    }

    ACTIVE_STATUSES = [
        WAITING, CALLED, IN_CONSULTATION,
        SENT_FOR_INVESTIGATION, SENT_TO_PHARMACY, SENT_FOR_BILLING,
    ]

    OUTPATIENT = "outpatient"
    WALK_IN = "walk_in"
    FOLLOW_UP = "follow_up"
    TYPE_CHOICES = [
        (OUTPATIENT, "Outpatient"), (WALK_IN, "Walk-in"), (FOLLOW_UP, "Follow-up"),
    ]

    visit_number = models.CharField(max_length=40, unique=True, editable=False)
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="visits"
    )
    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT, related_name="visits"
    )
    clinic = models.ForeignKey(
        "facilities.Clinic",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="visits",
    )
    visit_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=WALK_IN)
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default=WAITING)

    scheduled_for = models.DateTimeField(null=True, blank=True)
    arrived_at = models.DateTimeField(default=timezone.now)
    called_at = models.DateTimeField(null=True, blank=True)
    consultation_started_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    reason = models.CharField(max_length=255, blank=True)
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="visits_checked_in",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["arrived_at"]
        indexes = [
            models.Index(fields=["facility", "status", "arrived_at"]),
            models.Index(fields=["patient", "-arrived_at"]),
        ]
        constraints = [
            # One open visit per patient: a second concurrent check-in is a mistake, and
            # it is what splits one attendance across two charts.
            models.UniqueConstraint(
                fields=["patient"],
                condition=models.Q(closed_at__isnull=True),
                name="one_open_visit_per_patient",
            )
        ]
        permissions = [
            ("check_in_patient", "Can check a patient in"),
            ("move_queue", "Can move a patient through the queue"),
        ]

    def __str__(self):
        return f"{self.visit_number} — {self.patient.full_name} ({self.status})"

    @property
    def is_open(self):
        return self.closed_at is None

    @property
    def waiting_minutes(self):
        end = self.consultation_started_at or timezone.now()
        return int((end - self.arrived_at).total_seconds() // 60)

    def save(self, *args, **kwargs):
        if not self.visit_number:
            self.visit_number = NumberSequence.allocate("visit_number")
        return super().save(*args, **kwargs)

    def can_move_to(self, status):
        return status in self.TRANSITIONS.get(self.status, set())

    @transaction.atomic
    def move_to(self, status, *, actor, note=""):
        """Move through the queue, refusing anything the workflow does not allow.

        Re-read under a row lock so two staff acting at the same instant cannot both
        succeed: the second one sees the first one's result and is refused.
        """
        locked = Visit.objects.select_for_update().get(pk=self.pk)
        if status == locked.status:
            raise InvalidTransition(
                f"{locked.patient.full_name} is already {locked.get_status_display().lower()}."
            )
        if not locked.can_move_to(status):
            raise InvalidTransition(
                f"Cannot move from {locked.get_status_display().lower()} to "
                f"{dict(self.STATUS_CHOICES)[status].lower()}."
            )

        previous = locked.status
        locked.status = status
        now = timezone.now()
        touched = ["status"]
        if status == self.CALLED and locked.called_at is None:
            locked.called_at = now
            touched.append("called_at")
        if status == self.IN_CONSULTATION and locked.consultation_started_at is None:
            locked.consultation_started_at = now
            touched.append("consultation_started_at")
        if status in (self.COMPLETED, self.CANCELLED, self.ADMITTED):
            locked.closed_at = now
            touched.append("closed_at")
        locked.save(update_fields=touched)

        VisitStateChange.objects.create(
            visit=locked,
            from_status=previous,
            to_status=status,
            changed_by=actor,
            note=note,
        )
        self.refresh_from_db()
        return locked


class VisitStateChange(models.Model):
    """Who moved the patient, from where to where, and when.

    The queue's history is how you reconstruct a patient's movement through the building
    and how waiting times are measured later.
    """

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="state_changes")
    from_status = models.CharField(max_length=25)
    to_status = models.CharField(max_length=25)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True
    )
    changed_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["changed_at", "id"]

    def __str__(self):
        return f"{self.from_status} → {self.to_status}"


# --- the emergency department -----------------------------------------------
#
# In this app rather than one of its own: an emergency attendance is a visit —
# the patient arrives, waits, is seen, and leaves — and the queue, the state
# machine and the clinic all already exist here. What the ED adds is a
# severity that reorders the queue and an episode that has to end in exactly
# one outcome.


class TriageScale(models.Model):
    """The severity scale this hospital triages on. AC-168.

    Configurable because there is no single scale: Manchester, ESI, South
    African and CTAS all differ in level count, colour and target time, and a
    hospital's protocol is a fact about that hospital.

    **Not clinically reviewed.** The levels a hospital seeds here are its own;
    nothing in this software knows whether they are right.
    """

    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT, related_name="triage_scales"
    )
    name = models.CharField(max_length=80)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["facility", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "name"], name="one_triage_scale_name_per_facility"
            ),
            models.UniqueConstraint(
                fields=["facility"], condition=models.Q(is_active=True),
                name="one_active_triage_scale_per_facility",
            ),
        ]

    def __str__(self):
        return f"{self.name} — {self.facility.code}"


class TriageLevel(models.Model):
    """One step on the scale. AC-168.

    `rank` is what the queue sorts by, lowest first, so 1 is the sickest
    whatever the hospital chooses to call it.
    """

    scale = models.ForeignKey(
        TriageScale, on_delete=models.CASCADE, related_name="levels"
    )
    rank = models.PositiveSmallIntegerField(
        help_text="1 is the most urgent. The queue sorts by this."
    )
    name = models.CharField(max_length=60)
    colour = models.CharField(
        max_length=20, blank=True,
        help_text="What the department calls it on the wall: red, orange, green.",
    )
    target_minutes = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="How long this level should wait before being seen.",
    )
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["scale", "rank"]
        constraints = [
            models.UniqueConstraint(
                fields=["scale", "rank"], name="one_level_per_rank_per_scale"
            ),
            models.CheckConstraint(
                condition=models.Q(rank__gte=1), name="triage_rank_starts_at_one"
            ),
        ]

    def __str__(self):
        return f"{self.rank}. {self.name}"


class EmergencyEpisode(models.Model):
    """An attendance at the emergency department. AC-167 to AC-170.

    Hangs off a `Visit`, which carries the queue position and the state
    machine. What lives here is what the ED needs and a clinic attendance does
    not: how they arrived, the triage history, and an outcome that must be
    recorded exactly once.
    """

    WALK_IN = "walk_in"
    AMBULANCE = "ambulance"
    POLICE = "police"
    REFERRED = "referred"
    TRANSFER = "transfer"
    ARRIVAL_CHOICES = [
        (WALK_IN, "Walked in"), (AMBULANCE, "Ambulance"), (POLICE, "Police"),
        (REFERRED, "Referred by another clinician"),
        (TRANSFER, "Transferred from another hospital"),
    ]

    ADMITTED = "admitted"
    TRANSFERRED = "transferred"
    REFERRED_OUT = "referred"
    DISCHARGED = "discharged"
    DIED = "died"
    LEFT_WITHOUT_BEING_SEEN = "lwbs"
    OUTCOME_CHOICES = [
        (ADMITTED, "Admitted"), (TRANSFERRED, "Transferred to another hospital"),
        (REFERRED_OUT, "Referred on"), (DISCHARGED, "Discharged"),
        (DIED, "Died"), (LEFT_WITHOUT_BEING_SEEN, "Left without being seen"),
    ]

    visit = models.OneToOneField(
        Visit, on_delete=models.PROTECT, related_name="emergency_episode"
    )
    arrival_mode = models.CharField(
        max_length=12, choices=ARRIVAL_CHOICES, default=WALK_IN
    )
    presenting_complaint = models.CharField(max_length=255)
    brought_in_by = models.CharField(
        max_length=200, blank=True,
        help_text="Ambulance service, relative, police unit — whoever handed over.",
    )
    circumstances = models.TextField(
        blank=True,
        help_text="What the crew could say: where they were found, what they were "
                  "wearing. Often the only thing that lets a relative confirm an "
                  "unidentified patient is theirs.",
    )

    # AC-170. Exactly one outcome, recorded with a time. Enforced by the
    # constraint below rather than by convention: an episode with two outcomes
    # makes the department's own figures unanswerable, and one with none never
    # closes.
    outcome = models.CharField(max_length=12, choices=OUTCOME_CHOICES, blank=True)
    outcome_at = models.DateTimeField(null=True, blank=True)
    outcome_note = models.TextField(blank=True)
    outcome_recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="emergency_outcomes",
    )

    opened_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-opened_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(presenting_complaint=""),
                name="emergency_episode_states_a_complaint",
            ),
            # An outcome and its time arrive together or not at all. Half of
            # one is a closed episode nobody can date, or a time attached to
            # nothing.
            models.CheckConstraint(
                condition=(
                    models.Q(outcome="", outcome_at__isnull=True)
                    | ~models.Q(outcome="") & models.Q(outcome_at__isnull=False)
                ),
                name="emergency_outcome_carries_its_time",
            ),
            models.CheckConstraint(
                condition=models.Q(outcome="")
                | models.Q(outcome_recorded_by__isnull=False),
                name="emergency_outcome_names_who_recorded_it",
            ),
        ]
        permissions = [
            ("triage_patient", "Can triage a patient in the emergency department"),
            ("close_emergency_episode", "Can record how an emergency episode ended"),
        ]

    def __str__(self):
        return f"ED — {self.visit.patient.full_name}"

    @property
    def patient(self):
        return self.visit.patient

    @property
    def facility_id(self):
        return self.visit.facility_id

    @property
    def is_open(self):
        return self.outcome == ""

    def current_triage(self):
        """The latest assessment. AC-169 — the earlier ones are still there.

        Reads the prefetched list where there is one, so the emergency board
        is one query rather than one per patient waiting.
        """
        cache = getattr(self, "_prefetched_objects_cache", {})
        if "triage_assessments" in cache:
            assessments = list(cache["triage_assessments"])
            # Model ordering is by sequence ascending, so the last is current.
            return assessments[-1] if assessments else None
        return self.triage_assessments.order_by("-sequence").first()

    def waiting_minutes(self):
        end = self.outcome_at or timezone.now()
        return int((end - self.visit.arrived_at).total_seconds() // 60)


class TriageAssessment(models.Model):
    """One triage. AC-168, AC-169.

    Re-triage appends rather than edits. A patient who arrived green and went
    red did not "have their severity corrected" — they deteriorated, and the
    time that happened is the clinically interesting fact. Editing the first
    assessment would erase exactly the thing an incident review looks for.
    """

    episode = models.ForeignKey(
        EmergencyEpisode, on_delete=models.CASCADE, related_name="triage_assessments"
    )
    level = models.ForeignKey(
        TriageLevel, on_delete=models.PROTECT, related_name="assessments"
    )
    sequence = models.PositiveSmallIntegerField(
        help_text="1 for the triage on arrival; higher for each re-triage."
    )

    complaint = models.CharField(max_length=255, blank=True)
    observations = models.TextField(
        blank=True, help_text="What was measured or seen at this assessment."
    )
    reason_for_retriage = models.CharField(
        max_length=255, blank=True,
        help_text="Required on a re-triage. Why the severity changed.",
    )

    assessed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="triage_assessments",
    )
    assessed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["episode", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["episode", "sequence"],
                name="one_assessment_per_sequence_per_episode",
            ),
            # AC-169. A re-triage says why. Without it the record shows a
            # severity that changed for no stated reason, which is the same as
            # not knowing whether the patient deteriorated or somebody
            # mis-triaged them first time.
            models.CheckConstraint(
                condition=models.Q(sequence=1) | ~models.Q(reason_for_retriage=""),
                name="retriage_states_why",
            ),
        ]

    def __str__(self):
        return f"Triage {self.sequence}: {self.level.name}"
