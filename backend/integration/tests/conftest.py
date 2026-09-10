"""Fixtures for the external API facade.

The important one is `as_integration`: a caller holding
`integration.use_external_api` **at one facility only**. AC-180 asks for the
scoping to be tested with exactly that, because a caller permitted everywhere
proves nothing about the boundary.
"""
import pytest
from django.urls import reverse

from accounts.models import RoleAssignment, User
from conftest import PASSWORD, _client_for, _role

ROOT = reverse("facade-root-list")
PATIENTS = reverse("facade-patient-list")
ENCOUNTERS = reverse("facade-encounter-list")
CONDITIONS = reverse("facade-condition-list")
OBSERVATIONS = reverse("facade-observation-list")
MEDICATION_REQUESTS = reverse("facade-medicationrequest-list")


@pytest.fixture
def integration_user(db, facility_a):
    """A national reporting system's account. Facility A, and nothing else."""
    user = User.objects.create_user("integration@example.test", "Analyser", PASSWORD)
    role = _role("External Integration", "integration.use_external_api")
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def as_integration(integration_user):
    return _client_for(integration_user)


@pytest.fixture
def patient_at_b(db, facility_b, hospital_numbers):
    """A patient the integration account may not see. AC-180."""
    from patients.models import Patient

    return Patient.objects.create(
        given_name="Ifeoma", family_name="Ndukwe", sex="female",
        date_of_birth="1979-11-02", facility=facility_b,
    )
