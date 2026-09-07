from rest_framework import viewsets

from audit.models import AuditEvent
from core.permissions import HasPermission
from core.snapshots import snapshot

from .models import Facility
from .serializers import FacilitySerializer

AUDITED_FIELDS = ["name", "code", "timezone", "is_active", "organization"]


class FacilityViewSet(viewsets.ModelViewSet):
    """Configuration endpoint for facilities.

    No destroy: facilities are deactivated, not deleted — clinical and financial history
    references them.
    """

    serializer_class = FacilitySerializer
    # Scoping happens in get_queryset; this exists so schema generation can introspect
    # the model without a request.
    queryset = Facility.objects.none()
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "put", "head", "options"]

    required_permissions = {
        "list": "facilities.view_facility",
        "retrieve": "facilities.view_facility",
        "create": "facilities.add_facility",
        "update": "facilities.change_facility",
        "partial_update": "facilities.change_facility",
    }

    def get_queryset(self):
        """Scope to the facilities where the user holds the permission this action needs.

        Two layers, doing two different jobs: the permission class answers "may this
        user do this at all" (403), and this queryset answers "which facilities are
        theirs" (404). Out-of-scope reads must not confirm that a facility exists.
        """
        user = self.request.user
        if user.is_superuser:
            return Facility.objects.all()
        required = self.required_permissions.get(
            self.action, "facilities.view_facility"
        )
        granted = set(user.facilities_for(required))
        if None in granted:  # organization-wide grant
            return Facility.objects.all()
        return Facility.objects.filter(id__in=[fid for fid in granted if fid is not None])

    def perform_create(self, serializer):
        facility = serializer.save()
        AuditEvent.record(
            action="facility.created",
            actor=self.request.user,
            resource=facility,
            facility=facility,
            after=snapshot(facility, AUDITED_FIELDS),
            request=self.request,
        )

    def perform_update(self, serializer):
        before = snapshot(serializer.instance, AUDITED_FIELDS)
        facility = serializer.save()
        after = snapshot(facility, AUDITED_FIELDS)
        changed = {key: value for key, value in after.items() if before.get(key) != value}
        AuditEvent.record(
            action="facility.updated",
            actor=self.request.user,
            resource=facility,
            facility=facility,
            before={key: before[key] for key in changed},
            after=changed,
            request=self.request,
        )
