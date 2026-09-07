import pytest
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient

from accounts.models import Role, RoleAssignment, User
from facilities.models import Organization, Facility

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


@pytest.fixture
def as_viewer(api, viewer):
    api.force_login(viewer, backend=BACKEND)
    return api


@pytest.fixture
def as_editor(api, editor):
    api.force_login(editor, backend=BACKEND)
    return api
