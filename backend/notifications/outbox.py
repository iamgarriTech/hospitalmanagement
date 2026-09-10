"""The outbox: getting messages out of the building without risking anything.

AC-181 and AC-182, and guarantee 10 behind both.

`queue()` writes a row and returns. It never contacts a provider, so it
cannot be slow and cannot fail, which is what lets it be called from inside
the transaction that records a critical result without putting that result at
risk. Everything that can go wrong — an unreachable provider, a rejected
number, a timeout — happens later in `send_pending()`, where the only thing
at stake is the message.

Retries back off exponentially and stop at `max_attempts`. A message that has
run out of attempts is `failed`, visible as failed, and stays in the table.
Nothing is deleted: "we told the patient" and "we tried and could not" have to
be different answers.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import OutboundMessage

# Doubling, in minutes, from the first failure. Five attempts spans about
# half an hour, which is the right order for an SMS gateway having a bad
# moment and the wrong order for a number that will never work — hence the
# cap rather than retrying forever.
BACKOFF_MINUTES = [1, 2, 5, 15, 30]


class Unavailable(Exception):
    """The provider could not be reached. Worth retrying."""


class Rejected(Exception):
    """The provider refused the message. Retrying will not help."""


def queue(*, channel, to_address, body, subject="", source_type="", source_id="",
          facility=None, patient_reference="", max_attempts=5):
    """Put a message in the outbox. Never talks to anybody.

    Safe to call inside a clinical or financial transaction: it is one INSERT
    against a table nothing else contends on, and it cannot reach the network.
    """
    if not str(to_address).strip():
        raise ValidationError("A message needs somewhere to go.")
    if not body.strip():
        raise ValidationError("A message needs a body.")

    return OutboundMessage.objects.create(
        channel=channel, to_address=str(to_address).strip(), subject=subject,
        body=body, source_type=source_type, source_id=str(source_id),
        facility=facility, patient_reference=patient_reference,
        max_attempts=max_attempts,
    )


def due(*, limit=50):
    """Messages ready to be tried, oldest first."""
    return OutboundMessage.objects.filter(
        status__in=[OutboundMessage.PENDING, OutboundMessage.SENDING],
        next_attempt_at__lte=timezone.now(),
    ).order_by("next_attempt_at", "id")[:limit]


def _backoff(attempts):
    index = min(attempts - 1, len(BACKOFF_MINUTES) - 1)
    return timedelta(minutes=BACKOFF_MINUTES[max(index, 0)])


@transaction.atomic
def attempt(message, sender):
    """Try to send one message. Records the outcome either way.

    `sender` is a callable taking the message and returning a provider
    reference. It raises `Unavailable` for something worth retrying and
    `Rejected` for something that is not.

    The row is locked for the duration so two workers cannot both send it —
    which for an SMS means the patient's phone buzzing twice, and for an
    appointment reminder means them turning up on the wrong day.
    """
    message = OutboundMessage.objects.select_for_update(
        skip_locked=True
    ).filter(pk=message.pk).first()
    if message is None:
        return None  # another worker has it
    if message.is_terminal:
        return message

    message.attempts += 1
    message.status = OutboundMessage.SENDING
    message.save(update_fields=["attempts", "status"])

    try:
        reference = sender(message)
    except Rejected as refusal:
        # No amount of retrying fixes a malformed number. Fail it now rather
        # than burning four more attempts to reach the same place.
        message.status = OutboundMessage.FAILED
        message.failed_at = timezone.now()
        message.last_error = str(refusal)[:255]
        message.save(update_fields=["status", "failed_at", "last_error"])
        return message
    except Exception as problem:
        # Deliberately everything, not just `Unavailable`. A provider client
        # that raises its own socket error, a DNS failure, a library bug —
        # all of them mean "this did not send", and none of them may be
        # allowed to escape and kill the worker. `Rejected` above is the one
        # case that is not worth retrying, and it is handled separately.
        message.last_error = f"{type(problem).__name__}: {problem}"[:255]
        if message.attempts_left <= 0:
            # Out of attempts. Visible as failed, and still here — AC-182
            # forbids it silently disappearing.
            message.status = OutboundMessage.FAILED
            message.failed_at = timezone.now()
            message.save(update_fields=["status", "failed_at", "last_error"])
        else:
            message.status = OutboundMessage.PENDING
            message.next_attempt_at = timezone.now() + _backoff(message.attempts)
            message.save(update_fields=["status", "next_attempt_at", "last_error"])
        return message

    message.status = OutboundMessage.SENT
    message.sent_at = timezone.now()
    message.provider_reference = str(reference or "")[:120]
    message.last_error = ""
    message.save(update_fields=["status", "sent_at", "provider_reference",
                                "last_error"])
    return message


def send_pending(sender, *, limit=50):
    """Work through the queue once. Returns a count per outcome."""
    counts = {"sent": 0, "retrying": 0, "failed": 0, "skipped": 0}
    for message in list(due(limit=limit)):
        result = attempt(message, sender)
        if result is None:
            counts["skipped"] += 1
        elif result.status == OutboundMessage.SENT:
            counts["sent"] += 1
        elif result.status == OutboundMessage.FAILED:
            counts["failed"] += 1
        else:
            counts["retrying"] += 1
    return counts


@transaction.atomic
def retry(message, *, actor=None):
    """Put a failed message back in the queue.

    Resets the attempt count, because an operator retrying by hand has
    usually fixed the thing that was wrong — a corrected number, a provider
    back on its feet — and making them press it five more times helps nobody.
    """
    if message.status != OutboundMessage.FAILED:
        raise ValidationError(
            f"That message is {message.get_status_display().lower()}, not failed."
        )
    message.status = OutboundMessage.PENDING
    message.attempts = 0
    message.failed_at = None
    message.next_attempt_at = timezone.now()
    message.save(update_fields=["status", "attempts", "failed_at",
                                "next_attempt_at"])
    return message


def console_sender(message):
    """The default 'provider': write it to the log and call it sent.

    A hospital with no SMS contract still needs the queue to drain, and the
    honest behaviour is to record that nothing actually left the building
    rather than to pretend a message was delivered. `provider_reference` says
    so in as many words.
    """
    import logging

    logging.getLogger("notifications.outbox").info(
        "%s to %s: %s", message.channel, message.to_address, message.subject or
        message.body[:60],
    )
    return "console: not actually sent"


def summary():
    """What an operator needs to see: what is stuck, and what gave up."""
    from django.db.models import Count

    counts = dict(
        OutboundMessage.objects.values_list("status").annotate(n=Count("id"))
    )
    return {
        "pending": counts.get(OutboundMessage.PENDING, 0),
        "sent": counts.get(OutboundMessage.SENT, 0),
        "failed": counts.get(OutboundMessage.FAILED, 0),
        "cancelled": counts.get(OutboundMessage.CANCELLED, 0),
        "oldest_pending": OutboundMessage.objects.filter(
            status=OutboundMessage.PENDING
        ).order_by("created_at").values_list("created_at", flat=True).first(),
    }
