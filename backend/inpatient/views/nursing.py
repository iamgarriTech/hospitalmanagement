"""Nursing assessments, notes, fluid balance and escalations.

The notes viewset has no PATCH and no DELETE — not as an oversight but as the
point. A correction is a POST that supersedes an earlier note, and the database
refuses an UPDATE even if this view were bypassed.
"""
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import User
from audit.models import AuditEvent
from core.permissions import FacilityScopedMixin, HasPermission

from ..models import Admission, Escalation, FluidBalanceEntry, NursingAssessment, NursingNote
from ..serializers import (
    AcknowledgeEscalationSerializer,
    EscalationSerializer,
    FluidBalanceEntrySerializer,
    NotifySerializer,
    NursingAssessmentSerializer,
    NursingNoteSerializer,
)
from ..services import fluid_balance


class _AdmissionScopedMixin(FacilityScopedMixin):
    """Scoped through the admission, because these records have no facility of
    their own — they belong to a stay, and the stay belongs to a facility."""

    def _scope_by_admission(self, queryset):
        return self._scope(queryset, field="admission__facility_id")

    def facility_for_permission(self, request):
        if request.method == "POST":
            admission = Admission.objects.filter(
                pk=request.data.get("admission")
            ).select_related("facility").first()
            return admission.facility if admission else None
        return None


class NursingAssessmentViewSet(_AdmissionScopedMixin, viewsets.ModelViewSet):
    """AC-78. A shift assessment, attached to the admission."""

    queryset = NursingAssessment.objects.none()
    serializer_class = NursingAssessmentSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "head", "options"]

    required_permissions = {
        "list": "inpatient.view_nursingassessment",
        "retrieve": "inpatient.view_nursingassessment",
        "create": "inpatient.add_nursingassessment",
    }

    def get_queryset(self):
        queryset = self._scope_by_admission(
            NursingAssessment.objects.select_related(
                "admission", "patient", "recorded_by", "observations__recorded_by"
            )
        )
        params = self.request.query_params
        if params.get("admission"):
            queryset = queryset.filter(admission_id=params["admission"])
        if params.get("shift"):
            queryset = queryset.filter(shift=params["shift"])
        return queryset

    def perform_create(self, serializer):
        admission = serializer.validated_data["admission"]
        assessment = serializer.save(
            patient=admission.patient, recorded_by=self.request.user
        )
        AuditEvent.record(
            action="nursing.assessment_recorded",
            actor=self.request.user,
            resource=assessment,
            patient=admission.patient,
            facility=admission.facility,
            after={
                "shift": assessment.shift,
                "consciousness": assessment.consciousness,
                "mobility": assessment.mobility,
                "falls_risk": assessment.falls_risk,
                "pressure_area_concern": assessment.pressure_area_concern,
            },
            request=self.request,
        )


class NursingNoteViewSet(_AdmissionScopedMixin, viewsets.ModelViewSet):
    """AC-79. Append-only: there is no verb here that changes an existing note."""

    queryset = NursingNote.objects.none()
    serializer_class = NursingNoteSerializer
    permission_classes = [HasPermission]
    # No PATCH, no PUT, no DELETE. A note is evidence.
    http_method_names = ["get", "post", "head", "options"]

    required_permissions = {
        "list": "inpatient.view_nursingnote",
        "retrieve": "inpatient.view_nursingnote",
        "create": "inpatient.add_nursingnote",
    }

    def get_queryset(self):
        queryset = self._scope_by_admission(
            NursingNote.objects.select_related(
                "admission", "patient", "author", "supersedes", "correction"
            )
        )
        params = self.request.query_params
        if params.get("admission"):
            queryset = queryset.filter(admission_id=params["admission"])
        if params.get("current") == "true":
            # Only the notes nothing has corrected — the reading as it stands.
            queryset = queryset.filter(correction__isnull=True)
        return queryset

    def create(self, request, *args, **kwargs):
        """Two nurses correcting the same note at once: one wins.

        The serializer checks for an existing correction, but a check cannot
        close a race — the unique constraint on `supersedes` is what actually
        keeps corrections a chain rather than a tree, and this turns losing that
        race into a sentence rather than a 500.
        """
        try:
            with transaction.atomic():
                return super().create(request, *args, **kwargs)
        except IntegrityError:
            return Response(
                {"supersedes": "That note has just been corrected by someone else. "
                               "Read the correction before writing another."},
                status=http.HTTP_409_CONFLICT,
            )

    def perform_create(self, serializer):
        admission = serializer.validated_data["admission"]
        note = serializer.save(patient=admission.patient, author=self.request.user)
        AuditEvent.record(
            action="nursing.note_corrected" if note.supersedes_id
            else "nursing.note_written",
            actor=self.request.user,
            resource=note,
            patient=admission.patient,
            facility=admission.facility,
            after={
                "shift": note.shift,
                "supersedes": note.supersedes_id,
                "characters": len(note.note),
            },
            reason=note.correction_reason,
            request=self.request,
        )


class FluidBalanceViewSet(_AdmissionScopedMixin, viewsets.ModelViewSet):
    """AC-80. Volumes in and out; the balance is derived on read."""

    queryset = FluidBalanceEntry.objects.none()
    serializer_class = FluidBalanceEntrySerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "head", "options"]

    required_permissions = {
        "list": "inpatient.view_fluidbalanceentry",
        "retrieve": "inpatient.view_fluidbalanceentry",
        "create": "inpatient.add_fluidbalanceentry",
        "balance": "inpatient.view_fluidbalanceentry",
    }

    def get_queryset(self):
        queryset = self._scope_by_admission(
            FluidBalanceEntry.objects.select_related(
                "admission", "patient", "recorded_by"
            )
        )
        if self.request.query_params.get("admission"):
            queryset = queryset.filter(
                admission_id=self.request.query_params["admission"]
            )
        return queryset

    def facility_for_permission(self, request):
        if self.action == "balance":
            admission = Admission.objects.filter(
                pk=request.query_params.get("admission")
            ).select_related("facility").first()
            return admission.facility if admission else None
        return super().facility_for_permission(request)

    def perform_create(self, serializer):
        admission = serializer.validated_data["admission"]
        serializer.save(patient=admission.patient, recorded_by=self.request.user)

    @extend_schema(
        parameters=[
            OpenApiParameter("admission", int, required=True),
            OpenApiParameter("hours", int, description="Period, default 24."),
        ],
        summary="Intake, output and the running balance",
    )
    @action(detail=False, methods=["get"])
    def balance(self, request):
        """The period is a parameter: 24 hours is a convention, not a rule. A
        post-operative patient is watched hourly and a medical patient by shift."""
        admission = Admission.objects.filter(
            pk=request.query_params.get("admission")
        ).first()
        if admission is None:
            return Response(
                {"detail": "Say which admission."}, status=http.HTTP_400_BAD_REQUEST
            )
        hours = int(request.query_params.get("hours") or 24)
        return Response(fluid_balance(admission=admission, hours=hours))


class EscalationViewSet(FacilityScopedMixin, viewsets.ReadOnlyModelViewSet):
    """AC-82. Raised by recording an observation, closed by saying what was done.

    Read-only as a resource: an escalation is created by the observation that
    breached a threshold, never by hand. There is nothing here that can raise a
    false one or quietly drop a real one.
    """

    queryset = Escalation.objects.none()
    serializer_class = EscalationSerializer
    permission_classes = [HasPermission]

    required_permissions = {
        "list": "inpatient.view_escalation",
        "retrieve": "inpatient.view_escalation",
        "outstanding": "inpatient.view_escalation",
        "notify": "inpatient.escalate_observation",
        "acknowledge": "inpatient.escalate_observation",
    }

    def get_queryset(self):
        queryset = self._scope(
            Escalation.objects.select_related(
                "admission", "patient", "raised_by", "escalated_to", "acknowledged_by"
            ),
            field="admission__facility_id",
        )
        params = self.request.query_params
        if params.get("admission"):
            queryset = queryset.filter(admission_id=params["admission"])
        if params.get("ward"):
            queryset = queryset.filter(
                admission__occupancies__bed__room__ward_id=params["ward"],
                admission__occupancies__period__endswith__isnull=True,
            )
        if params.get("outstanding") == "true":
            queryset = queryset.filter(acknowledged_at__isnull=True)
        return queryset

    @extend_schema(
        responses={200: EscalationSerializer(many=True)},
        summary="Escalations nobody has answered yet",
    )
    @action(detail=False, methods=["get"])
    def outstanding(self, request):
        """AC-82's negative half. An escalation with no answer stays here until
        someone records what was done about it."""
        queryset = self.get_queryset().filter(acknowledged_at__isnull=True)
        return Response(self.get_serializer(queryset, many=True).data)

    @extend_schema(request=NotifySerializer, responses={200: EscalationSerializer},
                   summary="Record who was told")
    @action(detail=True, methods=["post"])
    def notify(self, request, pk=None):
        """Who was told, and when. Separate from acknowledgement because telling
        someone and their responding are different events, and the gap between
        them is what a review asks about."""
        escalation = self.get_object()
        serializer = NotifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        recipient = User.objects.filter(
            pk=serializer.validated_data["escalated_to"]
        ).first()
        if recipient is None:
            return Response(
                {"escalated_to": "No such member of staff."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        from django.utils import timezone

        escalation.escalated_to = recipient
        escalation.escalated_at = timezone.now()
        escalation.save(update_fields=["escalated_to", "escalated_at"])
        AuditEvent.record(
            action="nursing.escalation_notified",
            actor=request.user,
            resource=escalation,
            patient=escalation.patient,
            facility=escalation.admission.facility,
            after={"escalated_to": recipient.email,
                   "minutes_after_raising": escalation.minutes_waiting},
            reason=serializer.validated_data["note"],
            request=request,
        )
        return Response(self.get_serializer(escalation).data)

    @extend_schema(request=AcknowledgeEscalationSerializer,
                   responses={200: EscalationSerializer},
                   summary="Close an escalation by saying what was done")
    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        escalation = self.get_object()
        serializer = AcknowledgeEscalationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            escalation.acknowledge(
                actor=request.user,
                action_taken=serializer.validated_data["action_taken"],
            )
        except ValidationError as error:
            detail = (
                error.message_dict if hasattr(error, "message_dict") else error.messages
            )
            return Response({"detail": detail}, status=http.HTTP_400_BAD_REQUEST)

        AuditEvent.record(
            action="nursing.escalation_acknowledged",
            actor=request.user,
            resource=escalation,
            patient=escalation.patient,
            facility=escalation.admission.facility,
            after={
                "measurement": escalation.measurement,
                "value": str(escalation.value),
                "minutes_waiting": escalation.minutes_waiting,
            },
            reason=escalation.action_taken,
            request=request,
        )
        return Response(self.get_serializer(escalation).data)
