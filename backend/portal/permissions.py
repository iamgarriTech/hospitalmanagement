"""The portal's only permission rule.

There is exactly one: the request carries a live portal session. There is no
scope, no role and no codename, because a portal account may read precisely
one patient's records — its own — and that is decided by the session rather
than by anything the client can send.
"""

from rest_framework.permissions import BasePermission


class IsPortalPatient(BasePermission):
    """A live portal session, and nothing else.

    Checks the *type* rather than a flag: a staff `User` arriving here — say
    through a mounting mistake — is refused, because it is not a `PortalUser`.
    Fail closed, in the direction that matters.
    """

    message = "Sign in to your patient account to see this."

    def has_permission(self, request, view):
        return getattr(request.user, "is_portal", False) is True
