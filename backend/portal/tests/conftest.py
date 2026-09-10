"""Fixtures for the portal only.

Local rather than in the root conftest because nothing outside the portal has
any business holding a portal session, and a fixture that exists everywhere is
a fixture somebody eventually uses by accident.
"""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from portal.models import PortalAccount

PORTAL_PASSWORD = "patient-portal-pass"


def _account_for(patient, identifier):
    account = PortalAccount(patient=patient, login_identifier=identifier)
    account.set_password(PORTAL_PASSWORD)
    account.must_change_password = False
    account.save()
    return account


def sign_in(identifier, password=PORTAL_PASSWORD):
    """A client holding a real portal session, obtained the way a patient does."""
    client = APIClient()
    response = client.post(
        reverse("portal-login"),
        {"login_identifier": identifier, "password": password},
        format="json",
    )
    assert response.status_code == 200, response.data
    return client


@pytest.fixture
def portal_account(patient):
    """Amina's own portal login."""
    return _account_for(patient, "08031234567")


@pytest.fixture
def other_portal_account(male_patient):
    """Emeka's. Exists so "another patient" is a real account, not a hypothetical."""
    return _account_for(male_patient, "08079999999")


@pytest.fixture
def as_patient(portal_account):
    return sign_in(portal_account.login_identifier)
