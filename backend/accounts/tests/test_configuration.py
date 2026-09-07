"""AC-58 and AC-59 — configuration is administrable, gated and audited.

The PRD's requirement that permissions are not hard-coded is only true if a
hospital can actually create a role and have it take effect. These check that,
and that changing configuration is a security-relevant event rather than a
quiet edit.
"""
import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from accounts.models import Role, RoleAssignment, User
from audit.models import AuditEvent
from conftest import PASSWORD, perm
from patients.models import NumberSequence


@pytest.fixture
def administrator(db, facility_a):
    user = User.objects.create_user("config@example.test", "Ada Config", PASSWORD)
    role = Role.objects.create(name="Configurator")
    role.permissions.add(
        perm("accounts", "view_role"), perm("accounts", "add_role"),
        perm("accounts", "change_role"), perm("accounts", "view_user"),
        perm("accounts", "change_roleassignment"),
        perm("accounts", "delete_roleassignment"),
        perm("patients", "view_numbersequence"), perm("patients", "change_numbersequence"),
        perm("facilities", "view_facility"), perm("facilities", "add_department"),
        perm("facilities", "view_department"),
        perm("audit", "view_auditevent"),
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return user


@pytest.fixture
def as_admin(administrator):
    from conftest import _client_for

    return _client_for(administrator)


@pytest.mark.django_db
def test_a_hospital_can_create_a_role_and_it_takes_effect_immediately(
    as_admin, api, facility_a, hospital_numbers
):
    """AC-59, and the whole point of permissions-as-data.

    No deploy, no migration: the role is created, granted, and the API honours
    it on the next request.
    """
    created = as_admin.post(
        reverse("role-list"),
        {"name": "Ward Clerk", "description": "Reads patients only", "permissions": []},
        format="json",
    )
    assert created.status_code == 201, created.data
    role_id = created.data["id"]

    view_patient = Permission.objects.get(
        content_type__app_label="patients", codename="view_patient"
    )
    granted = as_admin.patch(
        reverse("role-detail", args=[role_id]),
        {"permissions": [view_patient.id]},
        format="json",
    )
    assert granted.status_code == 200
    assert granted.data["permission_codes"] == ["patients.view_patient"]

    clerk = User.objects.create_user("clerk2@example.test", "New Clerk", PASSWORD)
    assigned = as_admin.post(
        reverse("role-assign", args=[role_id]),
        {"user": clerk.pk, "facility": facility_a.pk},
        format="json",
    )
    assert assigned.status_code == 201

    # The new role works on the very next request, with no restart.
    api.force_login(clerk, backend="accounts.backends.EmailBackend")
    assert api.get(reverse("patient-list")).status_code == 200
    assert api.post(reverse("patient-list"), {}, format="json").status_code == 403


@pytest.mark.django_db
def test_permission_changes_are_audited_with_before_and_after(as_admin, viewer_role):
    """AC-58: a role change is a security event, not a quiet edit."""
    change = Permission.objects.get(
        content_type__app_label="facilities", codename="change_facility"
    )
    as_admin.patch(
        reverse("role-detail", args=[viewer_role.pk]),
        {"permissions": [change.id]},
        format="json",
    )
    event = AuditEvent.objects.get(action="role.permissions_changed")
    assert event.changes["before"]["permissions"] == ["facilities.view_facility"]
    assert event.changes["after"]["permissions"] == ["facilities.change_facility"]
    assert event.actor_email == "config@example.test"


@pytest.mark.django_db
def test_granting_and_revoking_a_role_are_both_audited(as_admin, viewer_role, facility_a):
    user = User.objects.create_user("grantee@example.test", "Grantee", PASSWORD)
    assigned = as_admin.post(
        reverse("role-assign", args=[viewer_role.pk]),
        {"user": user.pk, "facility": facility_a.pk},
        format="json",
    )
    assert AuditEvent.objects.filter(action="role.assigned").exists()

    revoked = as_admin.post(
        reverse("role-revoke", args=[viewer_role.pk]),
        {"assignment": assigned.data["id"]},
        format="json",
    )
    assert revoked.status_code == 204
    event = AuditEvent.objects.get(action="role.revoked")
    assert event.changes["before"]["user"] == "grantee@example.test"
    assert not RoleAssignment.objects.filter(pk=assigned.data["id"]).exists()


@pytest.mark.django_db
def test_role_administration_is_refused_without_the_permission(as_viewer, viewer_role):
    """AC-58 (negative): being able to read patients is not being able to grant
    yourself permission to change them."""
    assert as_viewer.get(reverse("role-list")).status_code == 403
    assert (
        as_viewer.patch(
            reverse("role-detail", args=[viewer_role.pk]), {"permissions": []}, format="json"
        ).status_code
        == 403
    )


@pytest.mark.django_db
def test_numbering_formats_are_configurable_and_audited(as_admin, hospital_numbers):
    """AC-59."""
    listed = as_admin.get(reverse("numbersequence-list"))
    assert listed.status_code == 200
    entry = next(row for row in listed.data if row["key"] == "hospital_number")
    assert entry["preview"].startswith("ILS/")

    changed = as_admin.patch(
        reverse("numbersequence-detail", args=[entry["id"]]),
        {"prefix": "IGH", "width": 6, "include_year": False},
        format="json",
    )
    assert changed.status_code == 200
    assert changed.data["preview"] == "IGH/000001"

    event = AuditEvent.objects.get(action="numbering.changed")
    assert event.changes["before"]["prefix"] == "ILS"
    assert event.changes["after"]["prefix"] == "IGH"


@pytest.mark.django_db
def test_the_next_number_cannot_be_rewound(as_admin, hospital_numbers, receptionist,
                                           facility_a):
    """(negative) Rewinding a sequence would reissue a hospital number that is
    already written on a chart."""
    from patients.models import Patient

    Patient.objects.create(
        given_name="First", family_name="Patient", sex="female", facility=facility_a
    )
    sequence = NumberSequence.objects.get(key="hospital_number")
    assert sequence.next_value == 2

    as_admin.patch(
        reverse("numbersequence-detail", args=[sequence.pk]),
        {"next_value": 1},
        format="json",
    )
    sequence.refresh_from_db()
    assert sequence.next_value == 2, "next_value must be read-only"


@pytest.mark.django_db
def test_departments_can_be_added_to_a_facility(as_admin, facility_a):
    """AC-59."""
    created = as_admin.post(
        reverse("department-list"),
        {"facility": facility_a.pk, "name": "Physiotherapy", "code": "PHYSIO"},
        format="json",
    )
    assert created.status_code == 201, created.data
    assert created.data["facility_code"] == "MAIN"

    listed = as_admin.get(reverse("department-list"), {"facility": facility_a.pk})
    assert any(row["code"] == "PHYSIO" for row in listed.data["results"])
