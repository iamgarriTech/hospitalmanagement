"""Portal authentication. Deliberately unable to reach a staff permission.

`PortalAuthentication` returns a `PortalUser` — not an `accounts.User`. It has
no `has_permission`, no roles, and no `is_staff`. Any internal view that
somehow received a portal request would fail closed at `HasPermission`, which
declares a codename `PortalUser` cannot satisfy.

That is the whole design of AC-184: the separation is not a check somebody
remembers to write, it is the absence of a code path.
"""

from rest_framework import authentication, exceptions

from .models import PortalSession

COOKIE_NAME = "vitacore_portal"


class PortalUser:
    """The authenticated subject of a portal request.

    Quacks like a user only as far as DRF needs: `is_authenticated`. It has
    deliberately no permission API, so nothing can accidentally grant it
    anything.
    """

    is_authenticated = True
    is_anonymous = False
    is_active = True
    # Named so a stack trace or a log line makes the kind obvious.
    is_portal = True
    is_superuser = False

    def __init__(self, session):
        self.session = session
        self.account = session.account
        self.patient = session.account.patient

    def __str__(self):
        return f"portal:{self.account.login_identifier}"

    @property
    def email(self):
        # Audit rows want something to name the actor by. The identifier is
        # what the patient typed, which is the honest answer.
        return f"portal:{self.account.login_identifier}"

    @property
    def pk(self):
        return None  # never a staff primary key

    def facilities_for(self, permission):
        """No facility grants a portal account anything. AC-184."""
        return []

    def has_permission(self, perm, facility=None):
        """Always false. A portal account holds no staff permission, ever."""
        return False


class PortalAuthentication(authentication.BaseAuthentication):
    """Reads the portal cookie. Ignores the staff session entirely."""

    def authenticate(self, request):
        token = request.COOKIES.get(COOKIE_NAME)
        if not token:
            return None
        session = PortalSession.resolve(token)
        if session is None:
            # An expired or revoked token is a 401 rather than a silent
            # anonymous request, so the portal can send the patient to sign in
            # again instead of showing them an empty page.
            raise exceptions.AuthenticationFailed(
                "Your session has ended. Please sign in again."
            )
        session.touch()
        return (PortalUser(session), None)

    def authenticate_header(self, request):
        return "Cookie"
