"""AC-184 — portal authentication is separate from staff authentication, with
no shared session and no staff permission reachable from a portal account.

The design puts the separation in the shape rather than in a check: a portal
account is a different model, read from a different cookie, by an
authentication class that returns a subject with no permission API. These
tests hold that shape in place — each one fails if somebody later makes portal
and staff sessions two flavours of the same thing.

Session lifetime, lockout and the staff endpoint that administers these
accounts are here too, because they are all part of "can a stranger get in".
"""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import FailedLoginAttempt, RoleAssignment, User
from audit.models import AuditEvent
from portal.authentication import COOKIE_NAME, PortalUser
from portal.models import PortalAccount, PortalLoginAttempt, PortalSession
from portal.permissions import IsPortalPatient

from .conftest import PORTAL_PASSWORD, sign_in

LOGIN = reverse("portal-login")
LOGOUT = reverse("portal-logout")
ME = reverse("portal-me")
VISITS = reverse("portal-record-visits")


@pytest.fixture
def portal_admin(db, facility_a):
    """A records officer who may issue portal logins, and nothing more."""
    from conftest import PASSWORD, _client_for, _role

    user = User.objects.create_user("portaladmin@example.test", "Ngozi Admin", PASSWORD)
    role = _role(
        "Portal Administrator",
        "patients.view_patient",
        "portal.view_portalaccount",
        "portal.manage_portal_accounts",
    )
    RoleAssignment.objects.create(user=user, role=role, facility=facility_a)
    return _client_for(user)


# --- the two authentications do not meet --------------------------------------

@pytest.mark.django_db
def test_the_portal_sets_its_own_cookie_and_not_the_staff_one(api, portal_account):
    """AC-184. Its own name, HttpOnly (guarantee 9), and no staff session
    anywhere in the response."""
    response = api.post(
        LOGIN,
        {"login_identifier": portal_account.login_identifier,
         "password": PORTAL_PASSWORD},
        format="json",
    )

    assert response.status_code == 200, response.data
    cookie = response.cookies[COOKIE_NAME]
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"
    assert "sessionid" not in response.cookies
    assert COOKIE_NAME != "sessionid"


@pytest.mark.django_db
def test_a_staff_session_cannot_read_the_portal(as_doctor, open_visit):
    """AC-184 (negative). A doctor's live staff session carries no weight on a
    portal endpoint: the portal reads a different cookie and knows nothing
    about `sessionid`."""
    response = as_doctor.get(VISITS)

    assert response.status_code in (401, 403)
    assert "Amina" not in str(response.data)


@pytest.mark.django_db
def test_a_portal_session_cannot_read_a_staff_endpoint(as_patient):
    """AC-184 (negative). The portal cookie is not a staff session, so the
    patient list refuses it — the failure is authentication, before any
    permission is consulted."""
    response = as_patient.get(reverse("patient-list"))

    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_a_portal_session_cannot_reach_the_portal_admin_endpoint(as_patient):
    """AC-184 (negative). The endpoint that creates portal logins is a staff
    endpoint. A patient holding a live portal session must not be able to
    issue themselves another patient's account."""
    response = as_patient.get(reverse("portalaccount-list"))

    assert response.status_code in (401, 403)


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint_name", [
    "patient-list", "visit-list", "encounter-list", "invoice-list",
    "prescription-list", "auditevent-list", "role-list", "staff-list",
    "report-list", "admission-list",
])
def test_no_staff_endpoint_answers_a_portal_session(as_patient, endpoint_name):
    """AC-184 (negative), swept across the endpoints a portal account would be
    most valuable on. None of them is reachable, and the reason is structural:
    `HasPermission` asks for a codename and a `PortalUser` has no way to hold
    one."""
    response = as_patient.get(reverse(endpoint_name))

    assert response.status_code in (401, 403), endpoint_name


@pytest.mark.django_db
def test_a_portal_user_holds_no_permission_at_all(portal_account):
    """AC-184, at the type level. Whatever a caller asks for, the answer is
    no, and no facility grants anything."""
    session, _ = PortalSession.start(portal_account)
    subject = PortalUser(session)

    assert subject.has_permission("patients.view_patient") is False
    assert subject.has_permission("portal.manage_portal_accounts", facility=None) is False
    assert subject.facilities_for("patients.view_patient") == []
    assert subject.pk is None
    assert subject.is_superuser is False
    assert not hasattr(subject, "role_assignments")


@pytest.mark.django_db
def test_the_staff_permission_class_refuses_a_portal_subject(portal_account, rf):
    """AC-184 (negative). `IsPortalPatient` is checked by type, so a staff
    user arriving on a portal view through a mounting mistake is refused in
    the direction that matters."""
    from accounts.models import User as StaffUser

    request = rf.get("/api/portal/record/visits/")
    request.user = StaffUser(email="doctor@example.test")

    assert IsPortalPatient().has_permission(request, None) is False


# --- the session ---------------------------------------------------------------

@pytest.mark.django_db
def test_the_session_token_is_never_stored_in_clear(portal_account):
    """A stolen database backup must not hand somebody a live session."""
    session, token = PortalSession.start(portal_account)

    assert token not in session.token_hash
    assert session.token_hash == PortalSession.hash_token(token)
    assert not PortalSession.objects.filter(token_hash=token).exists()
    assert PortalSession.resolve(token) == session


@pytest.mark.django_db
def test_an_expired_session_is_refused(as_patient, portal_account):
    """(negative) Two hours, not a shift. A patient on a shared phone does not
    leave a live session behind them."""
    PortalSession.objects.filter(account=portal_account).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )

    response = as_patient.get(VISITS)

    assert response.status_code == 401
    assert "sign in" in str(response.data).lower()


@pytest.mark.django_db
def test_an_ended_session_is_refused(as_patient, portal_account):
    """(negative) Signing out, a password change elsewhere, or a staff reset
    all end a session; none of them may leave it usable."""
    PortalSession.objects.filter(account=portal_account).update(
        ended_at=timezone.now()
    )

    assert as_patient.get(VISITS).status_code == 401


@pytest.mark.django_db
def test_suspending_the_account_ends_access_immediately(as_patient, portal_account):
    """(negative) A hospital suspending an account expects the patient out
    now, not in two hours when the token expires."""
    portal_account.is_active = False
    portal_account.deactivated_reason = "Identity not confirmed at the desk"
    portal_account.save(update_fields=["is_active", "deactivated_reason"])

    assert as_patient.get(VISITS).status_code == 401


@pytest.mark.django_db
def test_a_suspended_account_cannot_sign_in(api, portal_account):
    """(negative)"""
    portal_account.is_active = False
    portal_account.save(update_fields=["is_active"])

    response = api.post(
        LOGIN,
        {"login_identifier": portal_account.login_identifier,
         "password": PORTAL_PASSWORD},
        format="json",
    )

    assert response.status_code == 401
    assert COOKIE_NAME not in response.cookies or not response.cookies[COOKIE_NAME].value


@pytest.mark.django_db
def test_logging_out_ends_the_session_and_clears_the_cookie(as_patient, portal_account):
    response = as_patient.post(LOGOUT)

    assert response.status_code == 204
    assert response.cookies[COOKIE_NAME].value == ""
    assert not PortalSession.objects.filter(
        account=portal_account, ended_at__isnull=True
    ).exists()


# --- guessing at the door ------------------------------------------------------

@pytest.mark.django_db
def test_five_failures_lock_the_identifier_out(api, portal_account):
    """(negative) The sixth attempt is refused even with the right password."""
    wrong = {"login_identifier": portal_account.login_identifier,
             "password": "not-the-password"}
    for _ in range(5):
        assert api.post(LOGIN, wrong, format="json").status_code == 401

    right = api.post(
        LOGIN,
        {"login_identifier": portal_account.login_identifier,
         "password": PORTAL_PASSWORD},
        format="json",
    )

    assert right.status_code == 429
    assert PortalLoginAttempt.is_locked(portal_account.login_identifier)


@pytest.mark.django_db
def test_the_failure_says_the_same_thing_for_an_unknown_identifier(api, portal_account):
    """(negative) A different answer for "no such account" tells anybody who
    asks which phone numbers belong to patients of this hospital, which is
    itself a disclosure."""
    unknown = api.post(
        LOGIN,
        {"login_identifier": "08000000000", "password": PORTAL_PASSWORD},
        format="json",
    )
    wrong_password = api.post(
        LOGIN,
        {"login_identifier": portal_account.login_identifier, "password": "wrong"},
        format="json",
    )

    assert unknown.status_code == wrong_password.status_code == 401
    assert unknown.data == wrong_password.data


@pytest.mark.django_db
def test_a_portal_lockout_does_not_lock_the_staff_account(api, doctor, portal_account):
    """AC-184 (negative). The counters are separate tables on purpose: an
    attacker guessing at a patient's password must not be able to lock a
    clinician out of the hospital mid-shift by using their email."""
    from conftest import PASSWORD

    for _ in range(6):
        api.post(
            LOGIN,
            {"login_identifier": doctor.email, "password": "guessing"},
            format="json",
        )

    assert PortalLoginAttempt.is_locked(doctor.email)
    assert not FailedLoginAttempt.is_locked(doctor.email)

    staff = api.post(
        reverse("login"), {"email": doctor.email, "password": PASSWORD}, format="json"
    )
    assert staff.status_code == 200, staff.data


@pytest.mark.django_db
def test_a_failed_portal_login_is_audited_as_a_denial(api, portal_account):
    api.post(
        LOGIN,
        {"login_identifier": portal_account.login_identifier, "password": "wrong"},
        format="json",
    )

    event = AuditEvent.objects.filter(action="portal.login_failed").first()
    assert event is not None
    assert event.outcome == AuditEvent.DENIED
    assert "wrong" not in str(event.changes)


# --- the patient's own password ------------------------------------------------

@pytest.mark.django_db
def test_changing_the_password_ends_every_other_session(portal_account):
    """A patient changing their password because somebody else has been in
    their account expects exactly that."""
    first = sign_in(portal_account.login_identifier)
    second = sign_in(portal_account.login_identifier)

    response = second.post(
        ME,
        {"current_password": PORTAL_PASSWORD, "new_password": "a-longer-new-secret"},
        format="json",
    )

    assert response.status_code == 204, response.data
    assert first.get(VISITS).status_code == 401
    assert second.get(VISITS).status_code == 200


@pytest.mark.django_db
def test_changing_the_password_requires_the_current_one(as_patient, portal_account):
    """(negative) An unattended phone is not a licence to take the account."""
    response = as_patient.post(
        ME,
        {"current_password": "not-it", "new_password": "a-longer-new-secret"},
        format="json",
    )

    assert response.status_code == 400
    portal_account.refresh_from_db()
    assert portal_account.check_password(PORTAL_PASSWORD)


@pytest.mark.django_db
def test_me_describes_the_signed_in_patient_only(as_patient, portal_account, male_patient):
    response = as_patient.get(ME)

    assert response.status_code == 200
    assert response.data["hospital_number"] == portal_account.patient.hospital_number
    assert male_patient.family_name not in str(response.data)


# --- staff administering the accounts -----------------------------------------

@pytest.mark.django_db
def test_staff_without_the_permission_cannot_create_an_account(as_doctor, male_patient):
    """(negative) Issuing portal access is a records job, not a clinical one."""
    response = as_doctor.post(
        reverse("portalaccount-list"),
        {"patient": male_patient.pk, "login_identifier": "08055555555"},
        format="json",
    )

    assert response.status_code == 403
    assert not PortalAccount.objects.filter(patient=male_patient).exists()


@pytest.mark.django_db
def test_an_issued_account_returns_its_password_once_and_is_audited(
    portal_admin, male_patient
):
    response = portal_admin.post(
        reverse("portalaccount-list"),
        {"patient": male_patient.pk, "login_identifier": "08055555555"},
        format="json",
    )

    assert response.status_code == 201, response.data
    temporary = response.data["temporary_password"]
    assert temporary
    assert response.data["must_change_password"] is True
    assert "password_hash" not in response.data

    account = PortalAccount.objects.get(patient=male_patient)
    assert account.check_password(temporary)
    assert account.password_hash != temporary

    event = AuditEvent.objects.filter(action="portal_account.created").first()
    assert event is not None
    assert temporary not in str(event.changes)

    # Read back, the password is gone for good.
    again = portal_admin.get(reverse("portalaccount-detail", args=[account.pk]))
    assert "temporary_password" not in again.data
    assert "password_hash" not in again.data


@pytest.mark.django_db
def test_resetting_a_password_ends_every_live_session(portal_admin, portal_account):
    """A reset exists because somebody has lost control of the account."""
    patient_client = sign_in(portal_account.login_identifier)
    assert patient_client.get(VISITS).status_code == 200

    response = portal_admin.post(
        reverse("portalaccount-reset-password", args=[portal_account.pk])
    )

    assert response.status_code == 200, response.data
    assert response.data["temporary_password"]
    assert patient_client.get(VISITS).status_code == 401

    portal_account.refresh_from_db()
    assert portal_account.must_change_password is True
    assert not portal_account.check_password(PORTAL_PASSWORD)


@pytest.mark.django_db
def test_one_account_per_patient(portal_admin, portal_account):
    """(negative) Two logins for one patient is two passwords to lose."""
    response = portal_admin.post(
        reverse("portalaccount-list"),
        {"patient": portal_account.patient.pk, "login_identifier": "08066666666"},
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_an_identifier_cannot_be_reused_by_another_patient(portal_admin, portal_account,
                                                           male_patient):
    """(negative) The identifier is what a patient types. Two accounts sharing
    one is an ambiguous sign-in, and the portal resolves it to whichever row
    comes first — so it must not be creatable."""
    response = portal_admin.post(
        reverse("portalaccount-list"),
        {"patient": male_patient.pk,
         "login_identifier": portal_account.login_identifier},
        format="json",
    )

    assert response.status_code == 400
