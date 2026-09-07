"""Sample logins are a demo affordance, and must not exist in production.

Working credentials rendered on a live hospital's sign-in page would be a
serious hole, and the frontend cannot be the thing that decides — a build could
ship with the wrong flag. So the server withholds them.
"""
import pytest
from django.urls import reverse

META = reverse("meta")


@pytest.mark.django_db
def test_sample_logins_are_offered_in_demo_mode(api, settings, receptionist, doctor):
    settings.DEMO_MODE = True
    response = api.get(META)
    assert response.status_code == 200
    assert response.data["demo_mode"] is True
    # Only seeded demo accounts appear; real staff accounts never do.
    assert response.data["sample_logins"] == []


@pytest.mark.django_db
def test_demo_accounts_are_listed_with_their_role_and_facility(api, settings, facility_a):
    from accounts.models import Role, RoleAssignment, User

    settings.DEMO_MODE = True
    settings.DEMO_PASSWORD = "demo-password-not-for-real-use"
    user = User.objects.create_user("nurse@demo.test", "Fatima Bello", "irrelevant")
    RoleAssignment.objects.create(
        user=user, role=Role.objects.create(name="Nurse"), facility=facility_a
    )

    entry = api.get(META).data["sample_logins"][0]
    assert entry == {
        "role": "Nurse",
        "name": "Fatima Bello",
        "email": "nurse@demo.test",
        "password": "demo-password-not-for-real-use",
        "facility": "MAIN",
    }


@pytest.mark.django_db
def test_production_serves_no_credentials_at_all(api, settings, facility_a):
    """(negative) — the criterion that matters."""
    from accounts.models import Role, RoleAssignment, User

    user = User.objects.create_user("nurse@demo.test", "Fatima Bello", "irrelevant")
    RoleAssignment.objects.create(
        user=user, role=Role.objects.create(name="Nurse"), facility=facility_a
    )

    settings.DEMO_MODE = False
    response = api.get(META)
    assert response.data["demo_mode"] is False
    assert response.data["sample_logins"] == []
    assert "demo-password" not in response.content.decode()


@pytest.mark.django_db
def test_the_endpoint_is_reachable_before_signing_in(api, settings):
    """It has to be: it is what the sign-in screen reads."""
    settings.DEMO_MODE = True
    assert api.get(META).status_code == 200
