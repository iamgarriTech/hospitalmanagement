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


class FacilityScopedMixin:
    """Restricts a queryset to the facilities where the caller holds the verb.

    Scoping in the queryset rather than in the permission class is deliberate:
    an out-of-scope record must come back as 404, not 403. A 403 confirms the
    record exists, which is itself a leak — "no such patient" and "a patient you
    may not see" have to be indistinguishable across facilities.

    Lives here rather than in one app because wards, admissions, the MAR and the
    laboratory all need exactly this.
    """

    def _scope(self, queryset, field="facility_id"):
        user = self.request.user
        if user.is_superuser:
            return queryset
        required = self.required_permissions.get(self.action)
        granted = set(user.facilities_for(required)) if required else set()
        if None in granted:
            return queryset
        return queryset.filter(**{f"{field}__in": [f for f in granted if f is not None]})
