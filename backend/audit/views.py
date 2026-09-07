"""Reading the audit log.

Read-only by construction: the model refuses modification, the database refuses
it through a trigger, and there is no write endpoint here to be found. The log
is also a privacy surface in itself — it names which staff opened which
patient's record — so it sits behind its own permission.
"""
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.permissions import HasPermission

from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    facility_code = serializers.CharField(source="facility.code", read_only=True, default=None)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True, default=None)
    hospital_number = serializers.CharField(
        source="patient.hospital_number", read_only=True, default=None
    )

    class Meta:
        model = AuditEvent
        fields = ["id", "occurred_at", "action", "outcome", "actor_email", "facility_code",
                  "patient", "patient_name", "hospital_number", "resource_type",
                  "resource_id", "changes", "reason", "ip_address", "request_id"]
        read_only_fields = fields


class AuditEventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditEventSerializer
    permission_classes = [HasPermission]
    required_permissions = {
        "list": "audit.view_auditevent",
        "retrieve": "audit.view_auditevent",
        "verify": "audit.view_auditevent",
    }

    def get_queryset(self):
        queryset = AuditEvent.objects.select_related("facility", "patient").order_by("-id")
        params = self.request.query_params
        if params.get("action"):
            queryset = queryset.filter(action__icontains=params["action"])
        if params.get("actor"):
            queryset = queryset.filter(actor_email__icontains=params["actor"])
        if params.get("patient"):
            queryset = queryset.filter(patient_id=params["patient"])
        if params.get("outcome"):
            queryset = queryset.filter(outcome=params["outcome"])
        if params.get("since"):
            queryset = queryset.filter(occurred_at__gte=params["since"])
        return queryset

    @extend_schema(
        parameters=[OpenApiParameter("action"), OpenApiParameter("actor"),
                    OpenApiParameter("outcome")],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="Verify the hash chain over the whole log")
    @action(detail=False, methods=["get"])
    def verify(self, request):
        """Recomputes every row's hash. Slow by nature and meant to be run
        deliberately, not polled."""
        ok, problems = AuditEvent.verify_chain()
        return Response({
            "intact": ok,
            "events": AuditEvent.objects.count(),
            "problems": problems,
        })
