"""AC-181 and AC-182, and guarantee 10 behind both.

Guarantee 10 is the one that matters clinically: external-service failure
never blocks a clinical or financial write. The outbox makes that true by
never touching the network on the write path — `queue()` is one INSERT — so
the tests here come in two halves.

First: a provider that is broken, unreachable, slow or absent does not disturb
the transaction that queued the message. Second: the message itself is handled
honestly — retried with backoff, visible as failed when it runs out of
attempts, and never quietly dropped.
"""
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from accounts.models import RoleAssignment, User
from audit.models import AuditEvent
from conftest import PASSWORD, _client_for, _role
from notifications import outbox
from notifications.models import OutboundMessage


def queue_one(**overrides):
    payload = {
        "channel": OutboundMessage.SMS,
        "to_address": "08031234567",
        "body": "Your appointment is on Tuesday at 10am.",
    }
    payload.update(overrides)
    return outbox.queue(**payload)


def unavailable(message):
    raise outbox.Unavailable("The gateway did not answer.")


def rejected(message):
    raise outbox.Rejected("That number is not a mobile number.")


def exploding(message):
    """A provider client raising something of its own. Not `Unavailable`."""
    raise OSError("[Errno 8] nodename nor servname provided")


def working(message):
    return "provider-ref-1"


@pytest.fixture
def outbox_operator(db, facility_a):
    user = User.objects.create_user("outbox@example.test", "Kemi Ops", PASSWORD)
    role = _role(
        "Systems Operator",
        "notifications.view_outbox",
        "notifications.retry_outbound_message",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return _client_for(user)


# --- guarantee 10: the write survives whatever the provider does --------------

@pytest.mark.django_db
def test_queueing_never_contacts_a_provider(monkeypatch):
    """AC-181. `queue()` takes no sender and has no way to reach one.

    Every provider in this module is made to explode; queueing still works,
    because sending is not part of it. That is the whole reason the table
    exists.
    """
    monkeypatch.setattr(outbox, "console_sender", exploding)

    message = queue_one()

    assert message.status == OutboundMessage.PENDING
    assert message.attempts == 0
    assert message.sent_at is None


@pytest.mark.django_db
def test_a_critical_result_commits_even_though_the_provider_is_down(
    as_lab, fbc_order_item, fbc, monkeypatch
):
    """AC-181, guarantee 10 — the case the guarantee is written for.

    A haemoglobin of 5.9 is entered. The hospital has an email provider that
    is on fire. The result must be recorded, flagged critical, and the
    clinician notified in-app regardless; the email waits in the outbox.

    The provider is replaced by something that raises on *any* call, so if the
    write path ever starts sending inline this test fails rather than
    silently becoming a slow request.
    """
    from laboratory.models import LabResult
    from notifications.models import Notification

    def never_call_me(*args, **kwargs):
        raise AssertionError("The write path must not send anything itself.")

    monkeypatch.setattr(outbox, "send_pending", never_call_me)
    monkeypatch.setattr(outbox, "console_sender", never_call_me)

    as_lab.post(reverse("laborderitem-collect", args=[fbc_order_item.pk]), {},
                format="json")
    as_lab.post(reverse("laborderitem-start-processing", args=[fbc_order_item.pk]),
                {}, format="json")
    parameters = {p.name: p.pk for p in fbc.parameters.all()}
    response = as_lab.post(
        reverse("laborderitem-results", args=[fbc_order_item.pk]),
        {"entries": [
            {"parameter": parameters["Haemoglobin"], "value_numeric": "5.9"},
            {"parameter": parameters["White cell count"], "value_numeric": "9.0"},
            {"parameter": parameters["Platelets"], "value_numeric": "230"},
            {"parameter": parameters["Haematocrit"], "value_numeric": "21.0"},
        ]},
        format="json",
    )

    assert response.status_code == 201, response.data
    haemoglobin = LabResult.objects.get(parameter__name="Haemoglobin", is_current=True)
    assert haemoglobin.is_critical
    assert Notification.objects.filter(kind=Notification.CRITICAL_RESULT).exists()

    queued = OutboundMessage.objects.get(source_type="laboratory.LabResult")
    assert queued.status == OutboundMessage.PENDING
    assert queued.channel == OutboundMessage.EMAIL


@pytest.mark.django_db
def test_the_queued_email_carries_no_clinical_detail(as_lab, resulted_item):
    """An in-app notification is read by somebody who has authenticated. An
    email is read by whoever is holding the phone, so the number stays inside
    the hospital."""
    queued = OutboundMessage.objects.get(source_type="laboratory.LabResult")

    assert "5.9" not in queued.body
    assert "Haemoglobin" not in queued.body
    assert "Amina" not in queued.body
    assert "no clinical detail" in queued.body
    # The hospital number is there so an operator can trace a failure. That is
    # an identifier, not a diagnosis.
    assert queued.patient_reference


@pytest.mark.django_db
def test_a_failing_send_does_not_touch_what_caused_it(as_lab, resulted_item):
    """AC-181. Draining the queue against a dead provider changes the message
    and nothing else."""
    from laboratory.models import LabResult

    before = LabResult.objects.filter(is_current=True).count()

    counts = outbox.send_pending(unavailable)

    assert counts["retrying"] == 1
    assert LabResult.objects.filter(is_current=True).count() == before
    resulted_item.refresh_from_db()
    assert resulted_item.results.filter(is_current=True).exists()


@pytest.mark.django_db
def test_queueing_inside_a_transaction_does_not_hold_it_open():
    """AC-181. The row is written in the same transaction as the thing that
    caused it and commits with it — one table, no contention, no network."""
    with transaction.atomic():
        message = queue_one()
        assert OutboundMessage.objects.filter(pk=message.pk).exists()

    assert OutboundMessage.objects.get(pk=message.pk).status == (
        OutboundMessage.PENDING
    )


@pytest.mark.django_db
def test_a_rolled_back_write_takes_its_message_with_it():
    """The other direction, and it matters too: a consultation that fails
    validation must not leave an SMS behind telling the patient about it."""
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            queue_one()
            raise RuntimeError("the clinical write failed")

    assert not OutboundMessage.objects.exists()


# --- AC-182: retried with backoff, visible as failed, never dropped -----------

@pytest.mark.django_db
def test_an_unavailable_provider_delays_rather_than_fails():
    """AC-181. "Delays delivery" — the message stays pending with a later
    attempt time, and the failure is recorded on it."""
    message = queue_one()

    outbox.attempt(message, unavailable)

    message.refresh_from_db()
    assert message.status == OutboundMessage.PENDING
    assert message.attempts == 1
    assert message.next_attempt_at > timezone.now()
    assert "did not answer" in message.last_error


@pytest.mark.django_db
def test_the_backoff_grows():
    """AC-182. One minute, then two, then five: an SMS gateway having a bad
    moment is worth waiting for; a number that will never work is not worth
    hammering."""
    message = queue_one()
    gaps = []

    for _ in range(3):
        outbox.attempt(message, unavailable)
        message.refresh_from_db()
        gaps.append(message.next_attempt_at - timezone.now())
        # Make it due again so the next attempt is allowed.
        OutboundMessage.objects.filter(pk=message.pk).update(
            next_attempt_at=timezone.now()
        )

    assert gaps[0] < gaps[1] < gaps[2]
    assert gaps[0] < timedelta(minutes=2)


@pytest.mark.django_db
def test_it_gives_up_after_its_attempts_and_says_so():
    """AC-182. Visible as failed after the retries — not deleted, not
    pending forever, and carrying the reason."""
    message = queue_one(max_attempts=3)

    for _ in range(3):
        outbox.attempt(message, unavailable)
        OutboundMessage.objects.filter(pk=message.pk).update(
            next_attempt_at=timezone.now()
        )

    message.refresh_from_db()
    assert message.status == OutboundMessage.FAILED
    assert message.attempts == 3
    assert message.failed_at is not None
    assert message.last_error
    assert OutboundMessage.objects.filter(pk=message.pk).exists()


@pytest.mark.django_db
def test_a_failed_message_is_never_silently_dropped():
    """AC-182, stated as the property rather than the mechanism."""
    message = queue_one(max_attempts=1)

    outbox.attempt(message, unavailable)

    assert OutboundMessage.objects.count() == 1
    assert OutboundMessage.objects.get(pk=message.pk).status == (
        OutboundMessage.FAILED
    )


@pytest.mark.django_db
def test_a_rejected_message_fails_immediately():
    """A malformed number is not worth four more attempts to reach the same
    place."""
    message = queue_one(max_attempts=5)

    outbox.attempt(message, rejected)

    message.refresh_from_db()
    assert message.status == OutboundMessage.FAILED
    assert message.attempts == 1
    assert "not a mobile number" in message.last_error


@pytest.mark.django_db
def test_a_provider_raising_its_own_error_is_retried_not_fatal():
    """A socket error, a DNS failure or a library bug all mean "this did not
    send". None of them may escape and kill the worker mid-queue."""
    first = queue_one()
    second = queue_one(to_address="08039999999")

    counts = outbox.send_pending(exploding)

    assert counts["retrying"] == 2
    for message in (first, second):
        message.refresh_from_db()
        assert message.status == OutboundMessage.PENDING
        assert "OSError" in message.last_error


@pytest.mark.django_db
def test_a_successful_send_records_when_and_which_provider():
    message = queue_one()

    outbox.attempt(message, working)

    message.refresh_from_db()
    assert message.status == OutboundMessage.SENT
    assert message.sent_at is not None
    assert message.provider_reference == "provider-ref-1"
    assert message.last_error == ""


@pytest.mark.django_db
def test_a_sent_message_is_not_sent_twice():
    """A terminal message is left alone however often the worker runs."""
    message = queue_one()
    outbox.attempt(message, working)

    calls = []

    def counting(msg):
        calls.append(msg.pk)
        return "again"

    outbox.attempt(message, counting)

    assert calls == []
    message.refresh_from_db()
    assert message.provider_reference == "provider-ref-1"


@pytest.mark.django_db
def test_a_message_not_yet_due_is_not_attempted():
    message = queue_one()
    OutboundMessage.objects.filter(pk=message.pk).update(
        next_attempt_at=timezone.now() + timedelta(minutes=10)
    )

    counts = outbox.send_pending(working)

    assert counts == {"sent": 0, "retrying": 0, "failed": 0, "skipped": 0}
    message.refresh_from_db()
    assert message.status == OutboundMessage.PENDING


@pytest.mark.django_db
def test_the_console_sender_says_that_nothing_left_the_building():
    """AC-189. With no provider configured the queue still drains, and the
    row records that the message did not actually go anywhere. A hospital
    must never read "sent" and believe a patient was contacted."""
    message = queue_one()

    outbox.attempt(message, outbox.console_sender)

    message.refresh_from_db()
    assert message.status == OutboundMessage.SENT
    assert "not actually sent" in message.provider_reference


# --- the shape of the row ------------------------------------------------------

@pytest.mark.django_db
def test_a_message_needs_somewhere_to_go():
    with pytest.raises(ValidationError):
        queue_one(to_address="   ")


@pytest.mark.django_db
def test_a_message_needs_a_body():
    with pytest.raises(ValidationError):
        queue_one(body="  \n ")


@pytest.mark.django_db
def test_the_database_refuses_a_sent_row_with_no_time():
    """A "sent" row with no timestamp is indistinguishable from one somebody
    flipped by hand, so the constraint is declarative rather than a rule in
    the application."""
    from django.db import IntegrityError

    message = queue_one()

    with pytest.raises(IntegrityError):
        OutboundMessage.objects.filter(pk=message.pk).update(
            status=OutboundMessage.SENT, sent_at=None
        )


# --- what an operator sees -----------------------------------------------------

@pytest.mark.django_db
def test_the_queue_is_visible_to_an_operator(outbox_operator):
    queue_one()
    failed = queue_one(to_address="08079999999", max_attempts=1)
    outbox.attempt(failed, unavailable)

    response = outbox_operator.get(reverse("outbox-list"))

    assert response.status_code == 200, response.data
    assert len(response.data["results"]) == 2

    only_failed = outbox_operator.get(reverse("outbox-list"), {"failed": "true"})
    assert [row["id"] for row in only_failed.data["results"]] == [failed.pk]


@pytest.mark.django_db
def test_the_summary_shows_what_is_stuck_and_what_gave_up(outbox_operator):
    queue_one()
    gave_up = queue_one(to_address="08079999999", max_attempts=1)
    outbox.attempt(gave_up, unavailable)

    response = outbox_operator.get(reverse("outbox-summary"))

    assert response.status_code == 200, response.data
    assert response.data["pending"] == 1
    assert response.data["failed"] == 1
    assert response.data["oldest_pending"] is not None


@pytest.mark.django_db
def test_an_operator_can_retry_a_failed_message(outbox_operator):
    message = queue_one(max_attempts=1)
    outbox.attempt(message, unavailable)

    response = outbox_operator.post(reverse("outbox-retry", args=[message.pk]))

    assert response.status_code == 200, response.data
    message.refresh_from_db()
    assert message.status == OutboundMessage.PENDING
    assert message.attempts == 0
    assert message.failed_at is None
    assert AuditEvent.objects.filter(action="outbox.retried").exists()


@pytest.mark.django_db
def test_retrying_something_that_has_not_failed_is_refused(outbox_operator):
    """(negative) Pressing retry on a message that is merely waiting would
    reset its backoff and start the clock again."""
    message = queue_one()

    response = outbox_operator.post(reverse("outbox-retry", args=[message.pk]))

    assert response.status_code == 409
    message.refresh_from_db()
    assert message.status == OutboundMessage.PENDING


@pytest.mark.django_db
def test_staff_without_the_permission_cannot_see_the_queue(as_doctor):
    """(negative) The outbox names patients' phone numbers and email
    addresses. It is an operations screen, not a clinical one."""
    queue_one()

    response = as_doctor.get(reverse("outbox-list"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_reading_the_queue_does_not_let_you_edit_it(outbox_operator):
    """(negative) Apart from retry, the outbox is read-only: a row is the
    record of an attempt to contact somebody and must not be editable after
    the fact."""
    message = queue_one()

    for method in ["patch", "put", "delete"]:
        response = getattr(outbox_operator, method)(
            reverse("outbox-detail", args=[message.pk]), {}, format="json"
        )
        assert response.status_code in (403, 405), method

    assert OutboundMessage.objects.filter(pk=message.pk).exists()


@pytest.mark.django_db
def test_the_send_command_drains_the_queue_and_reports():
    from io import StringIO

    from django.core.management import call_command

    queue_one()
    output = StringIO()

    call_command("send_outbox", stdout=output)

    assert "sent 1" in output.getvalue()
    assert OutboundMessage.objects.get().status == OutboundMessage.SENT


@pytest.mark.django_db
def test_the_send_command_can_show_the_queue_without_sending():
    from io import StringIO

    from django.core.management import call_command

    queue_one()
    output = StringIO()

    call_command("send_outbox", "--show-queue", stdout=output)

    assert "pending" in output.getvalue()
    assert OutboundMessage.objects.get().status == OutboundMessage.PENDING
