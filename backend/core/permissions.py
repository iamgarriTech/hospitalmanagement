from rest_framework.permissions import BasePermission

from audit.models import AuditEvent


class HasPermission(BasePermission):
    """Facility-scoped permission check, recording every refusal.

    The view declares ``required_permissions`` as a mapping of DRF action name to
    ``app_label.codename``, and may implement ``facility_for_permission(request)``.
    A view that declares nothing is refused — fail closed, never open.
    """

    message = "You do not have permission to perform this action."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False

        perm = self._required_permission(view)
        if perm is None:
            self._record_denial(request, view, "view.no_permission_declared")
            return False

        facility = None
        resolver = getattr(view, "facility_for_permission", None)
        if callable(resolver):
            facility = resolver(request)

        if request.user.has_permission(perm, facility):
            return True

        self._record_denial(request, view, perm, facility)
        return False

    @staticmethod
    def _required_permission(view):
        mapping = getattr(view, "required_permissions", None)
        if isinstance(mapping, dict):
            action = getattr(view, "action", None) or view.request.method.lower()
            return mapping.get(action) or mapping.get("default")
        return getattr(view, "required_permission", None)

    @staticmethod
    def _record_denial(request, view, perm, facility=None):
        AuditEvent.record(
            action="permission.denied",
            actor=request.user,
            outcome=AuditEvent.DENIED,
            resource_type=view.__class__.__name__,
            facility=facility,
            after={"permission": perm, "path": request.path, "method": request.method},
            request=request,
        )
