from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from audit.models import AuditEvent
from core.permissions import FacilityScopedMixin, HasPermission
from facilities.models import Facility
from patients.models import Patient

from . import emergency
from .models import (
    EmergencyEpisode,
    InvalidTransition,
    TriageLevel,
    TriageScale,
    Visit,
)
from .serializers import (
    CloseEpisodeSerializer,
    EmergencyEpisodeSerializer,
    EmergencyQueueRowSerializer,
    MoveSerializer,
    QueueRowSerializer,
    RegisterArrivalSerializer,
    TriageScaleSerializer,
    TriageSerializer,
    VisitSerializer,
)


class VisitViewSet(viewsets.ModelViewSet):
    """Check-in and the patient queue."""

    queryset = Visit.objects.none()
    serializer_class = VisitSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]

    required_permissions = {
        "list": "visits.view_visit",
        "retrieve": "visits.view_visit",
        "queue": "visits.view_visit",
        "create": "visits.check_in_patient",
        "partial_update": "visits.change_visit",
        "move": "visits.move_queue",
    }

    def get_queryset(self):
        user = self.request.user
        required = self.required_permissions.get(self.action, "visits.view_visit")
        queryset = Visit.objects.select_related(
            "patient", "facility", "clinic"
        ).prefetch_related("patient__allergies", "state_changes")
        if not user.is_superuser:
            granted = set(user.facilities_for(required))
            if None not in granted:
                queryset = queryset.filter(
                    facility_id__in=[fid for fid in granted if fid is not None]
                )
        params = self.request.query_params
        if params.get("status"):
            queryset = queryset.filter(status__in=params["status"].split(","))
        if params.get("clinic"):
            queryset = queryset.filter(clinic_id=params["clinic"])
        if params.get("patient"):
            queryset = queryset.filter(patient_id=params["patient"])
        return queryset

    def facility_for_permission(self, request):
        if self.action == "create":
            facility_id = request.data.get("facility")
            return Facility.objects.filter(pk=facility_id).first() if facility_id else None
        return None

    def create(self, request, *args, **kwargs):
        """Check a patient in. Refuses a second open visit for the same patient."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            # A savepoint, so the constraint violation does not poison the transaction
            # and leave the handler below unable to query.
            with transaction.atomic():
                visit = serializer.save(checked_in_by=request.user, status=Visit.WAITING)
        except IntegrityError:
            open_visit = Visit.objects.filter(
                patient_id=request.data.get("patient"), closed_at__isnull=True
            ).first()
            return Response(
                {
                    "detail": "This patient already has an open visit.",
                    "open_visit": {
                        "id": open_visit.id,
                        "visit_number": open_visit.visit_number,
                        "status": open_visit.status,
                    } if open_visit else None,
                },
                status=http.HTTP_409_CONFLICT,
            )

        AuditEvent.record(
            action="visit.checked_in",
            actor=request.user,
            resource=visit,
            patient=visit.patient,
            facility=visit.facility,
            after={
                "visit_number": visit.visit_number,
                "visit_type": visit.visit_type,
                "status": visit.status,
            },
            request=request,
        )
        return Response(
            self.get_serializer(visit).data, status=http.HTTP_201_CREATED
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("status", description="Comma-separated queue states."),
            OpenApiParameter("clinic", int),
        ],
        responses={200: QueueRowSerializer(many=True)},
        summary="The live queue",
    )
    @action(detail=False, methods=["get"])
    def queue(self, request):
        """Everyone currently in the building, longest wait first.

        Deliberately unpaginated and lean: this is a wall-board view that staff keep
        open, and it is refreshed constantly.
        """
        queryset = self.get_queryset()
        if not request.query_params.get("status"):
            queryset = queryset.filter(status__in=Visit.ACTIVE_STATUSES)
        rows = queryset.order_by("arrived_at")[:300]
        return Response(QueueRowSerializer(rows, many=True).data)

    @extend_schema(
        request=MoveSerializer,
        responses={200: VisitSerializer},
        summary="Move a patient through the queue",
    )
    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        visit = self.get_object()
        serializer = MoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = serializer.validated_data["to"]
        note = serializer.validated_data["note"]

        try:
            visit.move_to(target, actor=request.user, note=note)
        except InvalidTransition as error:
            AuditEvent.record(
                action="visit.move_refused",
                actor=request.user,
                outcome=AuditEvent.DENIED,
                resource=visit,
                patient=visit.patient,
                facility=visit.facility,
                after={"attempted": target, "from": visit.status, "detail": str(error)},
                request=request,
            )
            return Response({"detail": str(error)}, status=http.HTTP_409_CONFLICT)

        visit.refresh_from_db()
        AuditEvent.record(
            action="visit.moved",
            actor=request.user,
            resource=visit,
            patient=visit.patient,
            facility=visit.facility,
            after={"status": visit.status},
            reason=note,
            request=request,
        )
        return Response(self.get_serializer(visit).data)


class TriageScaleViewSet(FacilityScopedMixin, viewsets.ModelViewSet):
    """AC-168. The scale is configuration, not code."""

    queryset = TriageScale.objects.none()
    serializer_class = TriageScaleSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "visits.view_triagescale",
        "retrieve": "visits.view_triagescale",
        "create": "visits.add_triagescale",
        "partial_update": "visits.change_triagescale",
        "seed_default": "visits.add_triagescale",
    }

    def get_queryset(self):
        return self._scope(
            TriageScale.objects.select_related("facility").prefetch_related("levels")
        )

    def facility_for_permission(self, request):
        if self.action in ("create", "seed_default"):
            return Facility.objects.filter(
                pk=request.data.get("facility")
            ).first()
        return None

    @extend_schema(request=None, responses={201: TriageScaleSerializer},
                   summary="Create a starting four-level scale")
    @action(detail=False, methods=["post"], url_path="seed-default",
            url_name="seed-default")
    def seed_default(self, request):
        """A hospital with no scale cannot triage at all.

        The four levels this creates are **not clinically approved** — they
        are a starting point for a hospital's own clinicians to replace, and
        the screen says so.
        """
        facility = Facility.objects.filter(pk=request.data.get("facility")).first()
        if facility is None:
            return Response({"facility": ["Name a facility."]},
                            status=http.HTTP_400_BAD_REQUEST)
        scale = emergency.seed_default_scale(facility=facility)
        AuditEvent.record(
            action="triage_scale.seeded", actor=request.user, resource=scale,
            facility=facility,
            after={"scale": scale.name, "levels": scale.levels.count()},
            request=request,
        )
        return Response(TriageScaleSerializer(scale).data,
                        status=http.HTTP_201_CREATED)


class EmergencyEpisodeViewSet(FacilityScopedMixin, viewsets.ModelViewSet):
    """AC-167 to AC-170. The emergency department."""

    queryset = EmergencyEpisode.objects.none()
    serializer_class = EmergencyEpisodeSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "head", "options"]
    required_permissions = {
        "list": "visits.view_emergencyepisode",
        "retrieve": "visits.view_emergencyepisode",
        "create": "visits.add_emergencyepisode",
        "triage": "visits.triage_patient",
        "close": "visits.close_emergency_episode",
        "board": "visits.view_emergencyepisode",
        "unidentified": "visits.view_emergencyepisode",
    }

    def get_queryset(self):
        queryset = self._scope(
            EmergencyEpisode.objects.select_related(
                "visit__patient", "visit__facility", "outcome_recorded_by",
            ).prefetch_related("triage_assessments__level", "triage_assessments__assessed_by"),
            field="visit__facility_id",
        )
        params = self.request.query_params
        if params.get("open") == "true":
            queryset = queryset.filter(outcome="")
        if params.get("outcome"):
            queryset = queryset.filter(outcome__in=params["outcome"].split(","))
        return queryset

    def facility_for_permission(self, request):
        if self.action == "create":
            return Facility.objects.filter(pk=request.data.get("facility")).first()
        return None

    @extend_schema(request=RegisterArrivalSerializer,
                   responses={201: EmergencyEpisodeSerializer},
                   summary="Register an arrival in as few fields as possible")
    def create(self, request, *args, **kwargs):
        serializer = RegisterArrivalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        facility = Facility.objects.filter(pk=data["facility"]).first()
        if facility is None:
            return Response({"facility": ["No such facility."]},
                            status=http.HTTP_400_BAD_REQUEST)
        patient = None
        if data["patient"]:
            patient = Patient.objects.filter(pk=data["patient"]).first()
            if patient is None:
                return Response({"patient": ["No such patient."]},
                                status=http.HTTP_400_BAD_REQUEST)

        try:
            episode = emergency.register_arrival(
                facility=facility,
                presenting_complaint=data["presenting_complaint"],
                actor=request.user, patient=patient,
                unidentified=data["unidentified"], sex=data["sex"],
                estimated_age_years=data["estimated_age_years"],
                arrival_mode=data["arrival_mode"],
                brought_in_by=data["brought_in_by"],
                circumstances=data["circumstances"],
            )
        except ValidationError as refusal:
            return Response({"detail": refusal.messages},
                            status=http.HTTP_400_BAD_REQUEST)

        AuditEvent.record(
            action="emergency.arrival_registered", actor=request.user,
            resource=episode, patient=episode.patient, facility=facility,
            after={"arrival_mode": episode.arrival_mode,
                   "unidentified": episode.patient.is_unidentified,
                   "hospital_number": episode.patient.hospital_number},
            reason=episode.presenting_complaint, request=request,
        )
        return Response(self.get_serializer(episode).data,
                        status=http.HTTP_201_CREATED)

    @extend_schema(request=TriageSerializer,
                   responses={201: EmergencyEpisodeSerializer},
                   summary="Triage, or re-triage — this appends, never edits")
    @action(detail=True, methods=["post"])
    def triage(self, request, pk=None):
        episode = self.get_object()
        serializer = TriageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        level = TriageLevel.objects.filter(
            pk=data["level"]
        ).select_related("scale").first()
        if level is None:
            return Response({"level": ["No such triage level."]},
                            status=http.HTTP_400_BAD_REQUEST)

        before = episode.current_triage()
        try:
            assessment = emergency.triage(
                episode=episode, level=level, actor=request.user,
                complaint=data["complaint"], observations=data["observations"],
                reason_for_retriage=data["reason_for_retriage"],
            )
        except ValidationError as refusal:
            return Response({"detail": refusal.messages},
                            status=http.HTTP_400_BAD_REQUEST)

        AuditEvent.record(
            action="emergency.triaged", actor=request.user, resource=assessment,
            patient=episode.patient, facility=episode.visit.facility,
            before={"level": before.level.name,
                    "rank": before.level.rank} if before else None,
            after={"level": level.name, "rank": level.rank,
                   "sequence": assessment.sequence},
            reason=assessment.reason_for_retriage or assessment.complaint,
            request=request,
        )
        episode.refresh_from_db()
        return Response(self.get_serializer(episode).data,
                        status=http.HTTP_201_CREATED)

    @extend_schema(request=CloseEpisodeSerializer,
                   responses={200: EmergencyEpisodeSerializer},
                   summary="Record how it ended — exactly once")
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        episode = self.get_object()
        serializer = CloseEpisodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            emergency.close(
                episode=episode, outcome=serializer.validated_data["outcome"],
                actor=request.user, note=serializer.validated_data["note"],
            )
        except ValidationError as refusal:
            return Response({"detail": refusal.messages},
                            status=http.HTTP_409_CONFLICT)

        AuditEvent.record(
            action="emergency.closed", actor=request.user, resource=episode,
            patient=episode.patient, facility=episode.visit.facility,
            after={"outcome": episode.outcome,
                   "waited_minutes": episode.waiting_minutes()},
            reason=episode.outcome_note, request=request,
        )
        return Response(self.get_serializer(episode).data)

    @extend_schema(
        parameters=[OpenApiParameter("facility", int)],
        responses={200: EmergencyQueueRowSerializer(many=True)},
        summary="The board: sickest first, then longest waiting",
    )
    @action(detail=False, methods=["get"])
    def board(self, request):
        facility = Facility.objects.filter(
            pk=request.query_params.get("facility")
        ).first()
        if facility is None:
            return Response({"facility": ["Name a facility."]},
                            status=http.HTTP_400_BAD_REQUEST)
        permitted = set(request.user.facilities_for("visits.view_emergencyepisode"))
        if not request.user.is_superuser and None not in permitted:
            if facility.pk not in permitted:
                return Response({"detail": "Not found."},
                                status=http.HTTP_404_NOT_FOUND)

        rows = emergency.queue(facility=facility)
        return Response(EmergencyQueueRowSerializer(rows, many=True).data)

    @extend_schema(
        parameters=[OpenApiParameter("facility", int)],
        responses={200: OpenApiTypes.OBJECT},
        summary="Patients still registered without a name",
    )
    @action(detail=False, methods=["get"])
    def unidentified(self, request):
        """AC-167. A temporary identity nobody merges becomes a permanent one."""
        facility = Facility.objects.filter(
            pk=request.query_params.get("facility")
        ).first()
        if facility is None:
            return Response({"facility": ["Name a facility."]},
                            status=http.HTTP_400_BAD_REQUEST)
        permitted = set(request.user.facilities_for("visits.view_emergencyepisode"))
        if not request.user.is_superuser and None not in permitted:
            if facility.pk not in permitted:
                return Response({"detail": "Not found."},
                                status=http.HTTP_404_NOT_FOUND)

        patients = emergency.unidentified_patients(facility=facility)
        return Response([
            {
                "id": patient.pk,
                "hospital_number": patient.hospital_number,
                "name": patient.full_name,
                "sex": patient.get_sex_display(),
                "registered_at": patient.created_at,
            }
            for patient in patients
        ])
