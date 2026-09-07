"""Append-only, tamper-evident audit log.

Two independent mechanisms back the guarantee:

* a hash chain, so altering any historical row is *detectable*
* a database trigger refusing UPDATE and DELETE, so it is *refused* even for a
  connection that bypasses the ORM

The trigger is row-level only, so TRUNCATE still works and test databases can be
flushed between tests.
"""
import hashlib
import json

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone

GENESIS_HASH = "0" * 64

# The hashed payload shape is versioned, and every row records the version it was
# hashed under. Without this, adding a field to this model silently invalidates every
# historical hash and the whole log reads as tampered — which is exactly the alarm you
# never want to be false. Bump this when the payload changes, and extend hash_payload
# to keep reproducing older shapes verbatim.
CURRENT_HASH_VERSION = 2


class AuditEvent(models.Model):
    ALLOWED = "allowed"
    DENIED = "denied"
    OUTCOME_CHOICES = [(ALLOWED, "Allowed"), (DENIED, "Denied")]

    occurred_at = models.DateTimeField(db_index=True)
    action = models.CharField(max_length=100, db_index=True)
    outcome = models.CharField(max_length=10, choices=OUTCOME_CHOICES, default=ALLOWED)

    # PROTECT, not SET_NULL: a user who has acted cannot be deleted, and the chain
    # cannot be invalidated by removing them. Deactivate instead.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    actor_email = models.CharField(
        max_length=254, blank=True, help_text="Snapshot, so the row reads correctly later."
    )

    facility = models.ForeignKey(
        "facilities.Facility",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_events",
        help_text="Which patient this action concerned, where one applies.",
    )
    resource_type = models.CharField(max_length=100, blank=True, db_index=True)
    resource_id = models.CharField(max_length=64, blank=True, db_index=True)

    changes = models.JSONField(
        default=dict, blank=True, help_text='{"before": {...}, "after": {...}}'
    )
    reason = models.TextField(blank=True)

    request_id = models.CharField(max_length=36, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True)

    hash_version = models.PositiveSmallIntegerField(default=CURRENT_HASH_VERSION)
    prev_hash = models.CharField(max_length=64)
    row_hash = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["resource_type", "resource_id"])]

    def __str__(self):
        return f"[{self.id}] {self.action} by {self.actor_email or 'anonymous'}"

    # --- hashing -------------------------------------------------------------

    def hash_payload(self):
        """Reproduce the payload for this row's own hash version, not the current one."""
        payload = {
            "prev_hash": self.prev_hash,
            "occurred_at": self.occurred_at.isoformat(),
            "action": self.action,
            "outcome": self.outcome,
            "actor_id": self.actor_id,
            "actor_email": self.actor_email,
            "facility_id": self.facility_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "changes": self.changes,
            "reason": self.reason,
        }
        if self.hash_version >= 2:
            payload["patient_id"] = self.patient_id
        return payload

    def compute_hash(self):
        canonical = json.dumps(
            self.hash_payload(), sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    # --- append-only ---------------------------------------------------------

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise IntegrityError("Audit events are append-only and cannot be modified.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise IntegrityError("Audit events cannot be deleted.")

    @classmethod
    def record(
        cls,
        *,
        action,
        actor=None,
        outcome=ALLOWED,
        resource=None,
        resource_type="",
        resource_id="",
        facility=None,
        patient=None,
        before=None,
        after=None,
        reason="",
        request=None,
    ):
        """Append one event. Serialized against concurrent appends so the chain is
        contiguous."""
        if resource is not None:
            resource_type = f"{resource._meta.app_label}.{resource._meta.object_name}"
            resource_id = str(resource.pk)
            if facility is None:
                facility = getattr(resource, "facility", None)
            if patient is None:
                patient = resource if resource.__class__.__name__ == "Patient" else getattr(
                    resource, "patient", None
                )

        changes = {}
        if before is not None:
            changes["before"] = before
        if after is not None:
            changes["after"] = after

        actor_is_real = actor is not None and getattr(actor, "pk", None) is not None
        event = cls(
            occurred_at=timezone.now(),
            action=action,
            outcome=outcome,
            actor=actor if actor_is_real else None,
            actor_email=getattr(actor, "email", "") or "",
            facility=facility,
            patient=patient,
            resource_type=resource_type,
            resource_id=resource_id,
            changes=changes,
            reason=reason,
        )
        if request is not None:
            event.request_id = getattr(request, "request_id", "") or ""
            event.ip_address = _client_ip(request)
            event.user_agent = (request.META.get("HTTP_USER_AGENT") or "")[:400]

        with transaction.atomic():
            last = cls.objects.select_for_update().order_by("-id").first()
            event.prev_hash = last.row_hash if last else GENESIS_HASH
            event.row_hash = event.compute_hash()
            event.save(force_insert=True)
        return event

    # --- verification --------------------------------------------------------

    @classmethod
    def verify_chain(cls):
        """Return (ok, problems). Each problem names the row and what failed."""
        problems = []
        expected_prev = GENESIS_HASH
        for event in cls.objects.order_by("id").iterator():
            if event.prev_hash != expected_prev:
                problems.append(
                    f"event {event.id}: prev_hash {event.prev_hash[:12]}… "
                    f"does not link to {expected_prev[:12]}…"
                )
            recomputed = event.compute_hash()
            if recomputed != event.row_hash:
                problems.append(
                    f"event {event.id}: contents altered "
                    f"(stored {event.row_hash[:12]}…, recomputed {recomputed[:12]}…, "
                    f"hash version {event.hash_version})"
                )
            expected_prev = event.row_hash
        return (not problems), problems


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
