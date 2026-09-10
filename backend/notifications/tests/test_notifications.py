"""In-app notifications: a user reads their own, and nobody else's.

There is no permission codename on this endpoint — the queryset is the
boundary. That is a reasonable design and an easy one to break, so the
negative test here is the one that matters: a second clinician's critical
result must be invisible, including through its own primary key.
"""
import pytest
from django.urls import reverse

from notifications.models import Notification

LIST = reverse("notification-list")


@pytest.fixture
def alert_for_doctor(resulted_item, doctor):
    """The critical haemoglobin from the bench fixture, addressed to the
    clinician who ordered it."""
    return Notification.objects.get(
        recipient=doctor, kind=Notification.CRITICAL_RESULT
    )


@pytest.mark.django_db
def test_a_critical_result_notifies_the_ordering_clinician(alert_for_doctor, as_doctor):
    """Communicated on entry, not on verification: waiting for a second pair
    of eyes before telling anybody is how a critical result gets missed."""
    response = as_doctor.get(LIST)

    assert response.status_code == 200, response.data
    rows = response.data["results"]
    assert len(rows) == 1
    assert rows[0]["urgency"] == Notification.URGENT
    assert "CRITICAL" in rows[0]["subject"]
    assert "5.9" in rows[0]["subject"]


@pytest.mark.django_db
def test_a_user_cannot_read_another_users_notifications(alert_for_doctor, as_nurse):
    """(negative) The nurse did not order the test. The alert is not hers to
    read, and the endpoint has no permission codename standing between them —
    the queryset is the whole boundary, so it is tested directly."""
    response = as_nurse.get(LIST)

    assert response.status_code == 200
    assert response.data["results"] == []


@pytest.mark.django_db
def test_marking_another_users_notification_read_does_nothing(
    alert_for_doctor, as_nurse
):
    """(negative) Reaching for the row by its own primary key.

    Silently marking somebody else's urgent alert as read would be worse than
    a leak: the clinician who needs it would never see it was there.
    """
    response = as_nurse.post(
        reverse("notification-mark-read", args=[alert_for_doctor.pk])
    )

    assert response.status_code == 200
    assert response.data["marked_read"] == 0
    alert_for_doctor.refresh_from_db()
    assert alert_for_doctor.read_at is None


@pytest.mark.django_db
def test_marking_your_own_notification_read(alert_for_doctor, as_doctor):
    response = as_doctor.post(
        reverse("notification-mark-read", args=[alert_for_doctor.pk])
    )

    assert response.status_code == 200
    assert response.data["marked_read"] == 1
    alert_for_doctor.refresh_from_db()
    assert alert_for_doctor.read_at is not None


@pytest.mark.django_db
def test_marking_it_read_twice_changes_nothing(alert_for_doctor, as_doctor):
    """A double-clicked button. Guarantee 7's habit, applied to something
    harmless, so the count is honest rather than the timestamp moving."""
    url = reverse("notification-mark-read", args=[alert_for_doctor.pk])
    as_doctor.post(url)
    alert_for_doctor.refresh_from_db()
    first_time = alert_for_doctor.read_at

    second = as_doctor.post(url)

    assert second.data["marked_read"] == 0
    alert_for_doctor.refresh_from_db()
    assert alert_for_doctor.read_at == first_time


@pytest.mark.django_db
def test_the_unread_filter(alert_for_doctor, as_doctor, doctor, patient):
    read = Notification.objects.create(
        recipient=doctor, kind=Notification.RESULT_READY,
        subject="Urea and electrolytes verified", patient=patient,
    )
    as_doctor.post(reverse("notification-mark-read", args=[read.pk]))

    unread = as_doctor.get(LIST, {"unread": "true"})

    assert [row["id"] for row in unread.data["results"]] == [alert_for_doctor.pk]


@pytest.mark.django_db
def test_verification_notifies_that_the_result_is_ready(as_lab, resulted_item,
                                                        as_doctor):
    verified = as_lab.post(
        reverse("laborderitem-verify", args=[resulted_item.pk]), {}, format="json"
    )
    assert verified.status_code == 200, verified.data

    kinds = {
        row["kind"] for row in as_doctor.get(LIST).data["results"]
    }

    assert kinds == {Notification.CRITICAL_RESULT, Notification.RESULT_READY}


@pytest.mark.django_db
def test_an_unauthenticated_request_reads_nothing(api, alert_for_doctor):
    response = api.get(LIST)

    assert response.status_code in (401, 403)
