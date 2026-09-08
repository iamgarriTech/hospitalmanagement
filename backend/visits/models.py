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
