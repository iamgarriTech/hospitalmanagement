"""Reading the log, and being able to check it.

The log's value rests on it being verifiable, so the verification is exposed —
otherwise "tamper-evident" is a claim nobody can test.
"""
import pytest
from conftest import PASSWORD, _client_for, perm
from django.urls import reverse

from accounts.models import Role, RoleAssignment, User
from audit.models import AuditEvent


@pytest.fixture
def auditor(db, facility_a):
    user = User.objects.create_user("auditor@example.test", "Ada Auditor", PASSWORD)
    role = Role.objects.create(name="Auditor")
    role.permissions.add(perm("audit", "view_auditevent"))
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def as_auditor(auditor):
    return _client_for(auditor)


@pytest.mark.django_db
def test_the_log_is_readable_and_filterable(as_auditor, editor):
    AuditEvent.record(action="test.allowed", actor=editor)
    AuditEvent.record(action="test.refused", actor=editor, outcome=AuditEvent.DENIED)

    everything = as_auditor.get(reverse("auditevent-list"))
    assert everything.status_code == 200
    assert everything.data["count"] >= 2

    refused = as_auditor.get(reverse("auditevent-list"), {"outcome": "denied"})
    assert all(row["outcome"] == "denied" for row in refused.data["results"])

    by_action = as_auditor.get(reverse("auditevent-list"), {"action": "test.allowed"})
    assert [row["action"] for row in by_action.data["results"]] == ["test.allowed"]


@pytest.mark.django_db
def test_the_chain_can_be_verified_through_the_api(as_auditor, editor):
    for index in range(3):
        AuditEvent.record(action=f"test.{index}", actor=editor)
    response = as_auditor.get(reverse("auditevent-verify"))
    assert response.status_code == 200
    assert response.data["intact"] is True
    assert response.data["problems"] == []
    assert response.data["events"] >= 3


@pytest.mark.django_db(transaction=True)
def test_verification_reports_tampering_that_bypassed_the_trigger(as_auditor, editor):
    """The alarm has to be reachable by the people who would need it."""
    from django.db import connection

    events = [AuditEvent.record(action=f"test.{i}", actor=editor) for i in range(3)]
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE audit_auditevent DISABLE TRIGGER audit_event_no_update_delete")
        cursor.execute(
            "UPDATE audit_auditevent SET action = 'edited' WHERE id = %s", [events[1].pk]
        )
        cursor.execute("ALTER TABLE audit_auditevent ENABLE TRIGGER audit_event_no_update_delete")

    response = as_auditor.get(reverse("auditevent-verify"))
    assert response.data["intact"] is False
    assert any(f"event {events[1].pk}" in problem for problem in response.data["problems"])


@pytest.mark.django_db
def test_the_log_is_refused_without_its_own_permission(as_viewer):
    """(negative) The log names which staff opened which patient's record, so it
    is a privacy surface in its own right — clinical access does not imply it."""
    assert as_viewer.get(reverse("auditevent-list")).status_code == 403
    assert as_viewer.get(reverse("auditevent-verify")).status_code == 403


@pytest.mark.django_db
def test_there_is_no_write_endpoint_at_all(as_auditor, editor):
    """(negative) The viewset defines no write handler at all.

    Asserted on the viewset rather than only on status codes: a write arrives as
    403 rather than 405 because the permission class runs during `initial()`,
    before DRF resolves that no handler exists. Either way it is refused — but
    the absence of the handler is the stronger claim, so check that directly.
    """
    from audit.views import AuditEventViewSet

    for handler in ("create", "update", "partial_update", "destroy"):
        assert not hasattr(AuditEventViewSet, handler), (
            f"AuditEventViewSet must not define {handler}"
        )

    event = AuditEvent.record(action="test.event", actor=editor)
    for response in (
        as_auditor.post(reverse("auditevent-list"), {}, format="json"),
        as_auditor.patch(
            reverse("auditevent-detail", args=[event.pk]), {"action": "x"}, format="json"
        ),
        as_auditor.delete(reverse("auditevent-detail", args=[event.pk])),
    ):
        assert response.status_code in (403, 405), response.status_code

    event.refresh_from_db()
    assert event.action == "test.event"
