"""Configuration endpoints that have no better home than their own module:
departments, clinics and identifier formats.
"""
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import AuditEvent
from core.permissions import HasPermission
from facilities.models import Clinic, Department, Organization
from patients.models import NumberSequence


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "name", "created_at"]
        read_only_fields = ["id", "created_at"]


class DepartmentSerializer(serializers.ModelSerializer):
    facility_code = serializers.CharField(source="facility.code", read_only=True)
    clinic_count = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = ["id", "facility", "facility_code", "name", "code", "is_active",
                  "clinic_count"]
        read_only_fields = ["id"]

    def get_clinic_count(self, department) -> int:
        return department.clinics.count()


class ClinicSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = Clinic
        fields = ["id", "department", "department_name", "name", "code", "is_active"]
        read_only_fields = ["id"]


class NumberSequenceSerializer(serializers.ModelSerializer):
    preview = serializers.SerializerMethodField()

    class Meta:
        model = NumberSequence
        fields = ["id", "key", "prefix", "include_year", "width", "separator",
                  "next_value", "preview"]
        read_only_fields = ["id", "key", "next_value", "preview"]

    def get_preview(self, sequence) -> str:
        """What the next identifier will look like. A format is hard to reason
        about in the abstract and easy to get wrong."""
        return sequence.format(sequence.next_value)


class OrganizationViewSet(viewsets.ModelViewSet):
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "patch", "head", "options"]
    required_permissions = {
        "list": "facilities.view_organization",
        "retrieve": "facilities.view_organization",
        "partial_update": "facilities.change_organization",
    }


class DepartmentViewSet(viewsets.ModelViewSet):
    queryset = Department.objects.none()
    serializer_class = DepartmentSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "facilities.view_department",
        "retrieve": "facilities.view_department",
        "create": "facilities.add_department",
        "partial_update": "facilities.change_department",
    }

    def get_queryset(self):
        queryset = Department.objects.select_related("facility").prefetch_related("clinics")
        user = self.request.user
        if not user.is_superuser:
            required = self.required_permissions.get(self.action, "facilities.view_department")
            granted = set(user.facilities_for(required))
            if None not in granted:
                queryset = queryset.filter(
                    facility_id__in=[f for f in granted if f is not None]
                )
        if self.request.query_params.get("facility"):
            queryset = queryset.filter(facility_id=self.request.query_params["facility"])
        return queryset


class ClinicViewSet(viewsets.ModelViewSet):
    queryset = Clinic.objects.none()
    serializer_class = ClinicSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "facilities.view_clinic",
        "retrieve": "facilities.view_clinic",
        "create": "facilities.add_clinic",
        "partial_update": "facilities.change_clinic",
    }

    def get_queryset(self):
        queryset = Clinic.objects.select_related("department__facility")
        if self.request.query_params.get("department"):
            queryset = queryset.filter(department_id=self.request.query_params["department"])
        return queryset


@extend_schema(tags=["configuration"])
class NumberSequenceViewSet(viewsets.ModelViewSet):
    """Identifier formats.

    `next_value` is deliberately read-only: rewinding a sequence would reissue a
    hospital number that is already on a chart.
    """

    queryset = NumberSequence.objects.all().order_by("key")
    serializer_class = NumberSequenceSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "patch", "head", "options"]
    pagination_class = None
    required_permissions = {
        "list": "patients.view_numbersequence",
        "retrieve": "patients.view_numbersequence",
        "partial_update": "patients.change_numbersequence",
    }

    def perform_update(self, serializer):
        before = {
            "prefix": serializer.instance.prefix,
            "include_year": serializer.instance.include_year,
            "width": serializer.instance.width,
            "separator": serializer.instance.separator,
        }
        sequence = serializer.save()
        AuditEvent.record(
            action="numbering.changed",
            actor=self.request.user,
            resource=sequence,
            before=before,
            after={"prefix": sequence.prefix, "include_year": sequence.include_year,
                   "width": sequence.width, "separator": sequence.separator,
                   "next_preview": sequence.format(sequence.next_value)},
            request=self.request,
        )


class LimitationsView(APIView):
    """What this software does not check. AC-189.

    Available to anybody signed in, with no permission of its own. A clinician
    must be able to find out what is *not* running without an administrator
    granting them something first — and there is nothing sensitive here, only
    an honest account of the software's limits.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: OpenApiTypes.OBJECT},
        summary="Every check that is absent, unlicensed or unreviewed",
    )
    def get(self, request):
        from core.limitations import report

        return Response(report())
