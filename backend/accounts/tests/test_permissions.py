"""AC-1, AC-2, AC-3 and facility scoping — the authorization half of the Phase 0 gate."""
import pytest
from conftest import perm
from django.urls import reverse

from accounts.models import Role, RoleAssignment
from audit.models import AuditEvent
from facilities.models import Facility


@pytest.mark.django_db
def test_viewer_can_read_but_not_change_a_facility(as_viewer, facility_a):
    """AC-1 (negative): a runtime-created role with only view permission is refused
    the write it does not hold."""
    detail = reverse("facility-detail", args=[facility_a.pk])
    assert as_viewer.get(detail).status_code == 200

    response = as_viewer.patch(detail, {"name": "Renamed"}, format="json")
    assert response.status_code == 403
    facility_a.refresh_from_db()
    assert facility_a.name == "Main Hospital"


@pytest.mark.django_db
def test_refusal_is_recorded_in_the_audit_log(as_viewer, facility_a):
    """AC-3: the denial itself is auditable, not only successful actions."""
    as_viewer.patch(
        reverse("facility-detail", args=[facility_a.pk]), {"name": "Renamed"}, format="json"
    )
    event = AuditEvent.objects.get(action="permission.denied")
    assert event.outcome == AuditEvent.DENIED
    assert event.changes["after"]["permission"] == "facilities.change_facility"
    assert event.changes["after"]["method"] == "PATCH"
    assert event.actor_email == "clerk@example.test"
    assert event.request_id


@pytest.mark.django_db
def test_permission_is_enforced_server_side(as_viewer, facility_a):
    """AC-2 (negative): calling the endpoint directly, with no UI in the way, still
    fails. PUT is checked as well as PATCH."""
    detail = reverse("facility-detail", args=[facility_a.pk])
    payload = {
        "organization": facility_a.organization_id,
        "name": "Renamed",
        "code": "MAIN",
        "timezone": "Africa/Lagos",
        "is_active": True,
    }
    assert as_viewer.put(detail, payload, format="json").status_code == 403
    assert as_viewer.post(reverse("facility-list"), payload, format="json").status_code == 403


@pytest.mark.django_db
def test_successful_update_records_before_and_after_values(as_editor, facility_a):
    """AC-3: what changed, from what, to what, by whom."""
    response = as_editor.patch(
        reverse("facility-detail", args=[facility_a.pk]),
        {"name": "Main Hospital Annexe"},
        format="json",
    )
    assert response.status_code == 200

    event = AuditEvent.objects.get(action="facility.updated")
    assert event.actor_email == "manager@example.test"
    assert event.changes["before"]["name"] == "Main Hospital"
    assert event.changes["after"]["name"] == "Main Hospital Annexe"
    assert event.resource_type == "facilities.Facility"
    assert event.resource_id == str(facility_a.pk)
    assert event.facility_id == facility_a.pk
    # Unchanged fields are not recorded as changes.
    assert "timezone" not in event.changes["after"]


@pytest.mark.django_db
def test_facility_scoped_role_does_not_leak_another_facility(as_viewer, facility_a, facility_b):
    """Guarantee 1 (negative): a grant at one facility is not a grant at another."""
    listed = as_viewer.get(reverse("facility-list")).data["results"]
    assert [row["code"] for row in listed] == ["MAIN"]
    assert as_viewer.get(reverse("facility-detail", args=[facility_b.pk])).status_code == 404


@pytest.mark.django_db
def test_organization_wide_grant_reaches_every_facility(api, facility_a, facility_b, viewer):
    org_role = Role.objects.create(name="Group Auditor")
    org_role.permissions.add(perm("facilities", "view_facility"))
    RoleAssignment.objects.create(user=viewer, role=org_role, facility=None)

    api.force_login(viewer, backend="accounts.backends.EmailBackend")
    codes = {row["code"] for row in api.get(reverse("facility-list")).data["results"]}
    assert codes == {"MAIN", "IKJ"}


@pytest.mark.django_db
def test_permissions_are_data_and_take_effect_without_a_deploy(as_viewer, viewer_role, facility_a):
    """AC-1: granting the permission at runtime changes the outcome."""
    detail = reverse("facility-detail", args=[facility_a.pk])
    assert as_viewer.patch(detail, {"name": "First try"}, format="json").status_code == 403

    viewer_role.permissions.add(perm("facilities", "change_facility"))

    assert as_viewer.patch(detail, {"name": "Second try"}, format="json").status_code == 200
    assert Facility.objects.get(pk=facility_a.pk).name == "Second try"


@pytest.mark.django_db
def test_a_view_declaring_no_permission_fails_closed(as_editor, facility_a, monkeypatch):
    from facilities.views import FacilityViewSet

    monkeypatch.setattr(FacilityViewSet, "required_permissions", {}, raising=False)
    response = as_editor.get(reverse("facility-list"))
    assert response.status_code == 403
    assert AuditEvent.objects.filter(action="permission.denied").exists()
