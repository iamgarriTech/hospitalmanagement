from django.db import IntegrityError, transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status as http, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from audit.models import AuditEvent
from core.permissions import HasPermission
from facilities.models import Facility

from .models import InvalidTransition, Visit
from .serializers import MoveSerializer, QueueRowSerializer, VisitSerializer


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
