"""Ward, room and bed administration, and the bed board.

The bed board is the screen a ward actually keeps open, so it is assembled
server-side in one query set rather than left to the client to stitch together
from four endpoints — a handover screen that arrives in pieces is a handover
screen that shows a patient in the wrong bed for a moment.
"""
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from audit.models import AuditEvent
from core.permissions import FacilityScopedMixin, HasPermission
from facilities.models import Facility

from ..models import Bed, BedOccupancy, EscalationThreshold, Room, Ward
from ..serializers import (
    BedOccupancySerializer,
    BedSerializer,
    BedStateSerializer,
    EscalationThresholdSerializer,
    RoomSerializer,
    WardSerializer,
)

# How many outstanding items to put on a bed card. Beyond a handful the board
# stops being readable and starts being a data dump; the counts carry the rest.
PER_PATIENT_LIMIT = 4


class WardViewSet(FacilityScopedMixin, viewsets.ModelViewSet):
    """Wards, their bed census, and the board."""

    queryset = Ward.objects.none()
    serializer_class = WardSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]

    required_permissions = {
        "list": "inpatient.view_ward",
        "retrieve": "inpatient.view_ward",
        "board": "inpatient.view_ward",
        "snapshot": "inpatient.view_ward",
        "create": "inpatient.add_ward",
        "partial_update": "inpatient.change_ward",
    }

    def get_queryset(self):
        queryset = self._scope(
            Ward.objects.select_related("facility", "department", "nightly_service")
        )
        params = self.request.query_params
        if params.get("facility"):
            queryset = queryset.filter(facility_id=params["facility"])
        if params.get("include_inactive") != "true":
            queryset = queryset.filter(is_active=True)
        return queryset

    def facility_for_permission(self, request):
        if self.action == "create":
            facility_id = request.data.get("facility")
            return Facility.objects.filter(pk=facility_id).first() if facility_id else None
        return None

    def perform_create(self, serializer):
        ward = serializer.save()
        AuditEvent.record(
            action="ward.created",
            actor=self.request.user,
            resource=ward,
            facility=ward.facility,
            after={"name": ward.name, "code": ward.code, "type": ward.ward_type},
            request=self.request,
        )

    @extend_schema(summary="The bed board for one ward")
    @action(detail=True, methods=["get"])
    def board(self, request, pk=None):
        """Every bed, who is in it, and what is outstanding for them.

        AC-110: enough to hand over a shift from one screen — the patient, their
        allergies, overdue doses and unacknowledged escalations. AC-112: what
        comes back is filtered by what the caller may see, so a nurse and a ward
        manager get different work from the same URL.
        """
        from ..services import (
            DEFAULT_OVERDUE_LOOKBACK_HOURS,
            board_escalations,
            board_overdue,
            older_overdue_count,
        )

        ward = self.get_object()
        beds = list(
            Bed.objects.filter(room__ward=ward, is_active=True)
            .select_related("room__ward")
            .prefetch_related(
                Prefetch(
                    "occupancies",
                    queryset=BedOccupancy.objects.filter(
                        period__endswith__isnull=True
                    ).select_related(
                        "patient", "admission__responsible_consultant"
                    ).prefetch_related("patient__allergies"),
                    to_attr="open_occupancies",
                )
            )
            .order_by("room__code", "code")
        )

        # Resolved once. The overdue list, the older count and the escalation
        # query each re-derived this as a subquery over occupancies → rooms →
        # beds; the beds are already in hand, and there are forty of them.
        admission_ids = [
            bed.open_occupancies[0].admission_id
            for bed in beds if bed.open_occupancies
        ]

        shown_doses, overdue_totals = board_overdue(
            admission_ids=admission_ids, limit=PER_PATIENT_LIMIT
        )
        overdue_by_admission = {
            admission_id: [
                {
                    "dose_id": dose.pk,
                    "medication": str(dose.prescription_item.medication),
                    "due_at": dose.due_at,
                    "minutes_late": dose.minutes_overdue,
                }
                for dose in doses
            ]
            for admission_id, doses in shown_doses.items()
        }

        shown_escalations, escalation_totals = board_escalations(
            admission_ids=admission_ids, limit=PER_PATIENT_LIMIT
        )
        escalations_by_admission = {
            admission_id: [
                {
                    "id": escalation.pk,
                    "measurement": escalation.get_measurement_display(),
                    "value": str(escalation.value),
                    "direction": escalation.direction,
                    "instruction": escalation.instruction,
                    "raised_at": escalation.raised_at,
                    "minutes_waiting": escalation.minutes_waiting,
                }
                for escalation in escalations
            ]
            for admission_id, escalations in shown_escalations.items()
        }

        rows = []
        for bed in beds:
            occupancy = bed.open_occupancies[0] if bed.open_occupancies else None
            row = {
                "bed": bed.pk,
                "bed_label": str(bed),
                "room": bed.room.code,
                "state": bed.OCCUPIED if occupancy else bed.service_state,
                "state_display": (
                    "Occupied" if occupancy else bed.get_service_state_display()
                ),
                "state_note": bed.state_note,
                "patient": None,
            }
            if occupancy is not None:
                admission = occupancy.admission
                row["patient"] = {
                    "id": occupancy.patient_id,
                    "name": occupancy.patient.full_name,
                    "hospital_number": occupancy.patient.hospital_number,
                    "sex": occupancy.patient.sex,
                    "age_years": occupancy.patient.age_years,
                    "admission": admission.pk,
                    "admission_number": admission.admission_number,
                    "admitted_at": admission.admitted_at,
                    "nights": occupancy.nights,
                    "diagnosis": admission.admission_diagnosis,
                    "consultant": admission.responsible_consultant.full_name,
                    "discharge_planned": admission.status == admission.DISCHARGE_PLANNED,
                    "expected_discharge_date": admission.expected_discharge_date,
                    "allergies": [
                        allergy.substance
                        for allergy in occupancy.patient.allergies.all()
                        if allergy.is_active
                    ],
                    # Capped per patient, with the totals alongside. A ward
                    # that has not been acknowledging escalations produced a
                    # 185 KiB board — twenty-four rows for one patient, on a
                    # screen a nurse reads at a glance. The counts are what a
                    # handover needs; the rows are on the patient's own page.
                    "overdue_doses": overdue_by_admission.get(admission.pk, []),
                    "overdue_count": overdue_totals.get(admission.pk, 0),
                    "escalations": escalations_by_admission.get(admission.pk, []),
                    "escalation_count": escalation_totals.get(admission.pk, 0),
                }
            rows.append(row)

        # Counted from the rows above rather than asking again: both read the
        # same beds, and `Ward.occupancy()` costs two more queries for a census
        # this method has already assembled.
        census = {"beds": len(rows), "occupied": 0, "available": 0, "reserved": 0,
                  "cleaning": 0, "maintenance": 0}
        for row in rows:
            census[row["state"]] = census.get(row["state"], 0) + 1

        return Response({
            "ward": {"id": ward.pk, "name": ward.name, "code": ward.code},
            "occupancy": census,
            "beds": rows,
            # The board shows this shift's overdue doses. Anything older is
            # counted rather than hidden — a dose that stops appearing after a
            # day is a dose nobody will ever account for — and the full list is
            # at /api/scheduled-doses/overdue/?lookback=all.
            "overdue": {
                "window_hours": DEFAULT_OVERDUE_LOOKBACK_HOURS,
                "in_window": sum(overdue_totals.values()),
                "older": older_overdue_count(admission_ids=admission_ids),
            },
            # What this caller may act on, so the board offers only the buttons
            # that will work. AC-112.
            "can": {
                "admit": request.user.has_permission(
                    "inpatient.admit_patient", ward.facility
                ),
                "transfer": request.user.has_permission(
                    "inpatient.transfer_patient", ward.facility
                ),
                "plan_discharge": request.user.has_permission(
                    "inpatient.plan_discharge", ward.facility
                ),
                "discharge": request.user.has_permission(
                    "inpatient.discharge_patient", ward.facility
                ),
                "administer": request.user.has_permission(
                    "inpatient.add_medicationadministration", ward.facility
                ),
                "observe": request.user.has_permission(
                    "clinical.add_vitalsigns", ward.facility
                ),
                "manage_beds": request.user.has_permission(
                    "inpatient.manage_beds", ward.facility
                ),
            },
        })

    @extend_schema(summary="Regenerate this ward's emergency snapshot")
    @action(detail=True, methods=["post"])
    def snapshot(self, request, pk=None):
        """AC-111.

        The snapshot is a **file**, written on a schedule by the
        `ward_snapshot` command — that is what makes it readable when the
        application is not running, which is the whole point of it. This
        endpoint only forces a fresh write, for the ward manager who wants a
        current one before a planned shutdown.
        """
        from ..snapshot import ward_snapshot_data, write_ward_snapshot

        ward = self.get_object()
        path = write_ward_snapshot(ward)
        data = ward_snapshot_data(ward)
        AuditEvent.record(
            action="ward.snapshot_written",
            actor=request.user,
            resource=ward,
            facility=ward.facility,
            after={"path": str(path), "patients": len(data["patients"])},
            request=request,
        )
        return Response({
            "path": str(path),
            "generated_at": data["generated_at"],
            "patients": len(data["patients"]),
            "beds_total": data["beds_total"],
            "snapshot": data,
        })


class RoomViewSet(viewsets.ModelViewSet):
    """Rooms within a ward."""

    queryset = Room.objects.select_related("ward").prefetch_related("beds__room__ward")
    serializer_class = RoomSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]

    required_permissions = {
        "list": "inpatient.view_room",
        "retrieve": "inpatient.view_room",
        "create": "inpatient.add_room",
        "partial_update": "inpatient.change_room",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("ward"):
            queryset = queryset.filter(ward_id=self.request.query_params["ward"])
        return queryset


class BedViewSet(viewsets.ModelViewSet):
    """Beds, and what each is available for."""

    queryset = Bed.objects.select_related("room__ward")
    serializer_class = BedSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]

    required_permissions = {
        "list": "inpatient.view_bed",
        "retrieve": "inpatient.view_bed",
        "create": "inpatient.add_bed",
        "partial_update": "inpatient.change_bed",
        "set_state": "inpatient.manage_beds",
        "history": "inpatient.view_bedoccupancy",
    }

    def get_queryset(self):
        queryset = super().get_queryset().prefetch_related(
            Prefetch(
                "occupancies",
                queryset=BedOccupancy.objects.select_related("patient", "admission"),
            )
        )
        params = self.request.query_params
        if params.get("ward"):
            queryset = queryset.filter(room__ward_id=params["ward"])
        if params.get("room"):
            queryset = queryset.filter(room_id=params["room"])
        if params.get("state") == "available":
            queryset = queryset.filter(pk__in=Bed.allocatable().values("pk"))
        return queryset

    @extend_schema(
        request=BedStateSerializer,
        responses={200: BedSerializer},
        summary="Take a bed out of service, or put it back",
    )
    @action(detail=True, methods=["post"], url_path="state", url_name="state")
    def set_state(self, request, pk=None):
        """AC-70, AC-72. Refuses to call an occupied bed available."""
        bed = self.get_object()
        serializer = BedStateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        before = bed.service_state
        try:
            bed.set_service_state(
                serializer.validated_data["service_state"],
                note=serializer.validated_data["note"],
            )
        except ValidationError as error:
            AuditEvent.record(
                action="bed.state_change_refused",
                actor=request.user,
                outcome=AuditEvent.DENIED,
                resource=bed,
                facility=bed.room.ward.facility,
                after={
                    "attempted": serializer.validated_data["service_state"],
                    "detail": "; ".join(error.messages),
                },
                request=request,
            )
            return Response(
                {"detail": error.messages}, status=http.HTTP_409_CONFLICT
            )

        AuditEvent.record(
            action="bed.state_changed",
            actor=request.user,
            resource=bed,
            facility=bed.room.ward.facility,
            before={"service_state": before},
            after={"service_state": bed.service_state, "note": bed.state_note},
            reason=bed.state_note,
            request=request,
        )
        return Response(self.get_serializer(bed).data)

    @extend_schema(
        responses={200: BedOccupancySerializer(many=True)},
        summary="Everyone who has occupied this bed, in order",
    )
    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        """AC-71. In order, with the gaps visible as gaps rather than absent."""
        bed = self.get_object()
        occupancies = bed.occupancies.select_related(
            "patient", "admission", "allocated_by", "ended_by"
        ).order_by("period")
        return Response(BedOccupancySerializer(occupancies, many=True).data)


class BedOccupancyViewSet(viewsets.ReadOnlyModelViewSet):
    """Occupancy history. Read-only: occupancies are opened and closed by
    admitting, transferring and discharging, never edited directly."""

    queryset = BedOccupancy.objects.select_related(
        "bed__room__ward", "patient", "admission", "allocated_by", "ended_by"
    )
    serializer_class = BedOccupancySerializer
    permission_classes = [HasPermission]
    required_permissions = {
        "list": "inpatient.view_bedoccupancy",
        "retrieve": "inpatient.view_bedoccupancy",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params
        if params.get("bed"):
            queryset = queryset.filter(bed_id=params["bed"])
        if params.get("admission"):
            queryset = queryset.filter(admission_id=params["admission"])
        if params.get("patient"):
            queryset = queryset.filter(patient_id=params["patient"])
        if params.get("open") == "true":
            queryset = queryset.filter(period__endswith__isnull=True)
        return queryset.order_by("period")


class EscalationThresholdViewSet(viewsets.ModelViewSet):
    """Configuration: when an observation on this ward has to be escalated."""

    queryset = EscalationThreshold.objects.select_related("ward")
    serializer_class = EscalationThresholdSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    required_permissions = {
        "list": "inpatient.view_escalationthreshold",
        "retrieve": "inpatient.view_escalationthreshold",
        "create": "inpatient.add_escalationthreshold",
        "partial_update": "inpatient.change_escalationthreshold",
        "destroy": "inpatient.delete_escalationthreshold",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("ward"):
            queryset = queryset.filter(ward_id=self.request.query_params["ward"])
        return queryset

    def perform_create(self, serializer):
        threshold = serializer.save()
        AuditEvent.record(
            action="ward.escalation_threshold_set",
            actor=self.request.user,
            resource=threshold,
            facility=threshold.ward.facility,
            after={
                "ward": threshold.ward.code,
                "measurement": threshold.measurement,
                "low": str(threshold.low or ""),
                "high": str(threshold.high or ""),
            },
            request=self.request,
        )
