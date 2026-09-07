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
