import pytest
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient

from accounts.models import Role, RoleAssignment, User
from facilities.models import Organization, Facility
from patients.models import NumberSequence

BACKEND = "accounts.backends.EmailBackend"
PASSWORD = "correct-horse-battery"


def perm(app_label, codename):
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


@pytest.fixture(autouse=True)
def _no_tls_redirect(settings):
    """Tests exercise the app directly; TLS is terminated by the proxy in production."""
    settings.SECURE_SSL_REDIRECT = False


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Ilesa Health Group")


@pytest.fixture
def facility_a(organization):
    return Facility.objects.create(organization=organization, name="Main Hospital", code="MAIN")


@pytest.fixture
def facility_b(organization):
    return Facility.objects.create(organization=organization, name="Ikeja Branch", code="IKJ")


@pytest.fixture
def viewer_role(db):
    role = Role.objects.create(name="Records Clerk")
    role.permissions.add(perm("facilities", "view_facility"))
    return role


@pytest.fixture
def editor_role(db):
    role = Role.objects.create(name="Facility Manager")
    role.permissions.add(
        perm("facilities", "view_facility"), perm("facilities", "change_facility")
    )
    return role


@pytest.fixture
def viewer(db, viewer_role, facility_a):
    user = User.objects.create_user("clerk@example.test", "Ada Clerk", PASSWORD)
    RoleAssignment.objects.create(user=user, role=viewer_role, facility=facility_a)
    return user


@pytest.fixture
def editor(db, editor_role, facility_a):
    user = User.objects.create_user("manager@example.test", "Bola Manager", PASSWORD)
    RoleAssignment.objects.create(user=user, role=editor_role, facility=facility_a)
    return user


@pytest.fixture
def api():
    return APIClient()


def _client_for(user):
    client = APIClient()
    client.force_login(user, backend=BACKEND)
    return client


@pytest.fixture
def as_viewer(viewer):
    return _client_for(viewer)


@pytest.fixture
def as_editor(editor):
    return _client_for(editor)


@pytest.fixture
def hospital_numbers(db):
    return NumberSequence.objects.create(
        key="hospital_number", prefix="ILS", include_year=True, width=5
    )


def _role(name, *qualified):
    role = Role.objects.create(name=name)
    role.permissions.add(*[perm(*entry.split(".")) for entry in qualified])
    return role


@pytest.fixture
def receptionist(db, facility_a, hospital_numbers):
    """Can register and search, cannot merge or override a suspected duplicate."""
    user = User.objects.create_user("front@example.test", "Chidi Front", PASSWORD)
    role = _role(
        "Receptionist",
        "patients.view_patient",
        "patients.add_patient",
        "patients.change_patient",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def records_officer(db, facility_a, hospital_numbers):
    user = User.objects.create_user("records@example.test", "Sade Records", PASSWORD)
    role = _role(
        "Medical Records Officer",
        "patients.view_patient",
        "patients.add_patient",
        "patients.change_patient",
        "patients.merge_patient",
        "patients.register_duplicate_patient",
        "patients.view_patient_access_log",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def as_reception(receptionist):
    return _client_for(receptionist)


@pytest.fixture
def as_records(records_officer):
    return _client_for(records_officer)


@pytest.fixture
def patient_payload(facility_a):
    def build(**overrides):
        payload = {
            "given_name": "Amina",
            "family_name": "Yusuf",
            "other_names": "",
            "date_of_birth": "1991-04-17",
            "sex": "female",
            "phone_primary": "08031234567",
            "address_line": "12 Adeola Street",
            "city": "Ilesa",
            "state": "Osun",
            "blood_group": "O+",
            "genotype": "AS",
            "facility": facility_a.pk,
        }
        payload.update(overrides)
        return payload

    return build
