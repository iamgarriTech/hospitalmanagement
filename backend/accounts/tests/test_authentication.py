"""AC-6 (lockout), plus the login half of the Phase 0 gate."""
import pytest
from django.conf import settings
from django.urls import reverse

from accounts.models import FailedLoginAttempt
from audit.models import AuditEvent
from conftest import PASSWORD


@pytest.mark.django_db
def test_login_succeeds_and_is_audited(api, editor):
    response = api.post(
        reverse("login"), {"email": editor.email, "password": PASSWORD}, format="json"
    )
    assert response.status_code == 200
    assert response.data["email"] == editor.email

    event = AuditEvent.objects.get(action="login.succeeded")
    assert event.actor == editor
    assert event.actor_email == editor.email
    assert event.outcome == AuditEvent.ALLOWED
    assert event.occurred_at is not None


@pytest.mark.django_db
def test_wrong_password_is_refused_and_audited(api, editor):
    response = api.post(
        reverse("login"), {"email": editor.email, "password": "wrong"}, format="json"
    )
    assert response.status_code == 401
    event = AuditEvent.objects.get(action="login.failed")
    assert event.outcome == AuditEvent.DENIED
    assert event.changes["after"]["email"] == editor.email
    assert FailedLoginAttempt.objects.count() == 1


@pytest.mark.django_db
def test_unknown_email_does_not_reveal_that_the_account_is_missing(api, editor):
    unknown = api.post(
        reverse("login"), {"email": "nobody@example.test", "password": "wrong"}, format="json"
    )
    known = api.post(
        reverse("login"), {"email": editor.email, "password": "wrong"}, format="json"
    )
    assert unknown.status_code == known.status_code == 401
    assert unknown.data["detail"] == known.data["detail"]


@pytest.mark.django_db
def test_account_locks_after_the_configured_number_of_failures(api, editor):
    """AC-6 (negative). The correct password stops working once locked."""
    for _ in range(settings.FAILED_LOGIN_LIMIT):
        api.post(reverse("login"), {"email": editor.email, "password": "wrong"}, format="json")

    locked = api.post(
        reverse("login"), {"email": editor.email, "password": PASSWORD}, format="json"
    )
    assert locked.status_code == 429
    assert AuditEvent.objects.filter(action="login.locked_out").exists()


@pytest.mark.django_db
def test_me_requires_authentication(api):
    assert api.get(reverse("me")).status_code == 403
