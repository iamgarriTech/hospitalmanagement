"""In-app notifications.

Phase 1 delivers in-app only. External channels (SMS, email) go through the outbox when
they arrive, which is why delivery is not modelled here as a boolean on the row.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    CRITICAL_RESULT = "critical_result"
    RESULT_READY = "result_ready"
    KIND_CHOICES = [
        (CRITICAL_RESULT, "Critical result"),
        (RESULT_READY, "Result ready"),
    ]

    URGENT = "urgent"
    NORMAL = "normal"
    URGENCY_CHOICES = [(URGENT, "Urgent"), (NORMAL, "Normal")]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(max_length=30, choices=KIND_CHOICES)
    urgency = models.CharField(max_length=10, choices=URGENCY_CHOICES, default=NORMAL)
    subject = models.CharField(max_length=200)
    body = models.TextField(blank=True)

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, null=True, blank=True,
        related_name="notifications",
    )
    resource_type = models.CharField(max_length=100, blank=True)
    resource_id = models.CharField(max_length=64, blank=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "read_at"])]

    def __str__(self):
        return f"{self.subject} → {self.recipient.email}"


class OutboundMessage(models.Model):
    """A message waiting to leave the building. AC-181, AC-182.

    The whole point of this table is that **sending is not part of the
    transaction that caused it.** A critical result is recorded, an SMS row is
    written beside it, and the transaction commits. Whether the SMS provider
    is reachable is somebody else's problem, resolved later by a worker.

    Doing it the obvious way — calling the provider inside the request —
    means a provider timeout rolls back the result, or leaves the clinician
    staring at a spinner while a socket hangs. Guarantee 10 exists because
    that is not acceptable behaviour for a system recording a potassium of
    7.2, and this table is how it is avoided.

    Retries back off. A failed message is visible as failed and is never
    quietly dropped, because "the patient was told" and "we tried to tell the
    patient and could not" need to be distinguishable afterwards.
    """

    SMS = "sms"
    EMAIL = "email"
    CHANNEL_CHOICES = [(SMS, "SMS"), (EMAIL, "Email")]

    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (PENDING, "Waiting to send"), (SENDING, "Sending"), (SENT, "Sent"),
        (FAILED, "Failed"), (CANCELLED, "Cancelled"),
    ]

    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    to_address = models.CharField(
        max_length=200, help_text="A phone number or an email address."
    )
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()

    # What caused it, so an operator looking at a stuck queue can tell whether
    # it matters. Deliberately loose strings rather than a generic foreign
    # key: the outbox must not hold a reference that stops a record being
    # deleted, and it outlives whatever produced it.
    source_type = models.CharField(max_length=60, blank=True)
    source_id = models.CharField(max_length=64, blank=True)
    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="outbound_messages",
    )
    # Never the message body's subject matter. A queue row is not a place for
    # a diagnosis, and this column exists so an operator can chase a failure
    # without reading anybody's results.
    patient_reference = models.CharField(
        max_length=40, blank=True,
        help_text="Hospital number, for tracing. Never clinical detail.",
    )

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    # When it may next be tried. Backoff moves this forward rather than
    # sleeping, so nothing holds a worker or a connection open.
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)

    last_error = models.CharField(max_length=255, blank=True)
    provider_reference = models.CharField(max_length=120, blank=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["next_attempt_at", "id"]
        indexes = [
            models.Index(fields=["status", "next_attempt_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(body=""), name="outbound_message_has_a_body"
            ),
            models.CheckConstraint(
                condition=~models.Q(to_address=""),
                name="outbound_message_has_somewhere_to_go",
            ),
            # A message marked sent has to say when. AC-182: "sent" with no
            # time is indistinguishable from a row somebody flipped by hand.
            models.CheckConstraint(
                condition=~models.Q(status="sent") | models.Q(sent_at__isnull=False),
                name="sent_message_records_when",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="failed")
                | models.Q(failed_at__isnull=False),
                name="failed_message_records_when",
            ),
        ]
        permissions = [
            ("view_outbox", "Can see the outbound message queue"),
            ("retry_outbound_message", "Can put a failed message back in the queue"),
        ]

    def __str__(self):
        return f"{self.get_channel_display()} to {self.to_address} ({self.status})"

    @property
    def is_terminal(self):
        return self.status in (self.SENT, self.FAILED, self.CANCELLED)

    @property
    def attempts_left(self):
        return max(self.max_attempts - self.attempts, 0)
