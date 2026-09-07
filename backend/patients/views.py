from django.core.exceptions import ValidationError
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from audit.models import AuditEvent
from core.permissions import HasPermission
from core.snapshots import snapshot
from facilities.models import Facility

from .duplicates import find_possible_duplicates
from .merging import merge_patients
from .models import Patient
from .search import search_patients
from .serializers import (
    DuplicateCandidateSerializer,
    DuplicateCheckSerializer,
    MergeSerializer,
    PatientSerializer,
    PatientSummarySerializer,
)

AUDITED_FIELDS = [
    "family_name", "given_name", "other_names", "date_of_birth", "sex",
    "phone_primary", "phone_alternate", "email", "address_line", "city", "state",
    "blood_group", "genotype", "status",
]


class PatientViewSet(viewsets.ModelViewSet):
    """Patient registration, identity and search.

    No destroy: patient records are deactivated or merged, never deleted.
    """

    queryset = Patient.objects.none()
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "put", "head", "options"]

    required_permissions = {
        "list": "patients.view_patient",
        "retrieve": "patients.view_patient",
        "create": "patients.add_patient",
        "update": "patients.change_patient",
        "partial_update": "patients.change_patient",
        "check_duplicates": "patients.view_patient",
        "merge": "patients.merge_patient",
        "access_log": "patients.view_patient_access_log",
    }

    def get_serializer_class(self):
        return PatientSummarySerializer if self.action == "list" else PatientSerializer

    def get_queryset(self):
        user = self.request.user
        required = self.required_permissions.get(self.action, "patients.view_patient")
        queryset = Patient.objects.all()
        if not user.is_superuser:
            granted = set(user.facilities_for(required))
            if None not in granted:
                queryset = queryset.filter(
                    facility_id__in=[fid for fid in granted if fid is not None]
                )
        if self.action == "list":
            if self.request.query_params.get("include_merged") != "true":
                queryset = queryset.exclude(status=Patient.MERGED)
            queryset = search_patients(
                queryset, self.request.query_params.get("search", "")
            )
        return queryset

    def facility_for_permission(self, request):
        if self.action == "create":
            facility_id = request.data.get("facility")
            return Facility.objects.filter(pk=facility_id).first() if facility_id else None
        return None

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "search",
                description="Hospital number, name, phone number, or ISO date of birth.",
            ),
            OpenApiParameter("include_merged", bool),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        patient = self.get_object()
        AuditEvent.record(
            action="patient.viewed",
            actor=request.user,
            resource=patient,
            patient=patient,
            facility=patient.facility,
            request=request,
        )
        return Response(self.get_serializer(patient).data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        candidates = find_possible_duplicates(
            given_name=data["given_name"],
            family_name=data["family_name"],
            other_names=data.get("other_names", ""),
            date_of_birth=data.get("date_of_birth"),
            phone=data.get("phone_primary", ""),
            facility=data.get("facility"),
        )

        acknowledged = str(request.data.get("acknowledge_duplicate", "")).lower() in {
            "true", "1", "yes"
        }
        reason = (request.data.get("duplicate_reason") or "").strip()

        if candidates and not acknowledged:
            # A warning, not a block: real near-duplicates exist. The caller must look
            # at these and then either open one of them or say why this is different.
            return Response(
                {
                    "detail": "Possible duplicate records found. Review them, then either "
                              "open the existing patient or resubmit with "
                              "acknowledge_duplicate and duplicate_reason.",
                    "duplicates": DuplicateCandidateSerializer(candidates, many=True).data,
                },
                status=status.HTTP_409_CONFLICT,
            )

        if candidates and acknowledged:
            if not request.user.has_permission(
                "patients.register_duplicate_patient", data.get("facility")
            ):
                AuditEvent.record(
                    action="patient.duplicate_override_denied",
                    actor=request.user,
                    outcome=AuditEvent.DENIED,
                    facility=data.get("facility"),
                    after={"candidates": [c.patient.hospital_number for c in candidates]},
                    request=request,
                )
                raise PermissionDenied(
                    "Registering a patient despite a suspected duplicate needs the "
                    "patients.register_duplicate_patient permission."
                )
            if not reason:
                return Response(
                    {"duplicate_reason": ["A reason is required to override a suspected "
                                          "duplicate."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        patient = serializer.save(registered_by=request.user)
        AuditEvent.record(
            action="patient.registered",
            actor=request.user,
            resource=patient,
            patient=patient,
            facility=patient.facility,
            after=snapshot(patient, AUDITED_FIELDS),
            reason=reason,
            request=request,
        )
        if candidates:
            AuditEvent.record(
                action="patient.duplicate_override",
                actor=request.user,
                resource=patient,
                patient=patient,
                facility=patient.facility,
                after={
                    "registered": patient.hospital_number,
                    "despite": [c.patient.hospital_number for c in candidates],
                },
                reason=reason,
                request=request,
            )
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_update(self, serializer):
        before = snapshot(serializer.instance, AUDITED_FIELDS)
        patient = serializer.save()
        after = snapshot(patient, AUDITED_FIELDS)
        changed = {key: value for key, value in after.items() if before.get(key) != value}
        AuditEvent.record(
            action="patient.updated",
            actor=self.request.user,
            resource=patient,
            patient=patient,
            facility=patient.facility,
            before={key: before[key] for key in changed},
            after=changed,
            reason=(self.request.data.get("reason") or "").strip(),
            request=self.request,
        )

    @extend_schema(
        request=DuplicateCheckSerializer,
        responses={200: DuplicateCandidateSerializer(many=True)},
        summary="Check for suspected duplicates before registering",
    )
    @action(detail=False, methods=["post"], url_path="check-duplicates")
    def check_duplicates(self, request):
        serializer = DuplicateCheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        candidates = find_possible_duplicates(**serializer.validated_data)
        return Response(DuplicateCandidateSerializer(candidates, many=True).data)

    @extend_schema(
        request=MergeSerializer,
        responses={200: PatientSerializer},
        summary="Merge this record into another",
    )
    @action(detail=True, methods=["post"])
    def merge(self, request, pk=None):
        source = self.get_object()
        serializer = MergeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = Patient.objects.filter(pk=serializer.validated_data["into"]).first()
        if target is None:
            return Response(
                {"into": ["No such patient."]}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            survivor, moved = merge_patients(
                source=source,
                target=target,
                actor=request.user,
                reason=serializer.validated_data["reason"],
                request=request,
            )
        except ValidationError as error:
            return Response(
                {"detail": error.messages[0]}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(
            {"survivor": PatientSerializer(survivor).data, "records_moved": moved}
        )

    @extend_schema(summary="Who has accessed this patient record")
    @action(detail=True, methods=["get"], url_path="access-log")
    def access_log(self, request, pk=None):
        patient = self.get_object()
        events = AuditEvent.objects.filter(patient=patient).order_by("-id")[:200]
        return Response(
            [
                {
                    "id": event.id,
                    "occurred_at": event.occurred_at,
                    "action": event.action,
                    "outcome": event.outcome,
                    "actor": event.actor_email,
                    "ip_address": event.ip_address,
                    "reason": event.reason,
                }
                for event in events
            ]
        )
