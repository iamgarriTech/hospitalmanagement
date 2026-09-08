"""The drug chart over HTTP.

The chart itself is assembled server-side because a MAR is read as a grid — a
row per medication, a column per due time — and building that in the browser
from a flat list of doses would put the definition of "overdue" in two places.
"""
from django.core.exceptions import ValidationError
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status as http, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.permissions import FacilityScopedMixin, HasPermission
from pharmacy.models import PrescriptionItem, StockBatch

from ..models import Admission, MedicationAdministration, ScheduledDose
from ..serializers import (
    DiscontinueSerializer,
    MedicationAdministrationSerializer,
    RecordAdministrationSerializer,
    ScheduledDoseSerializer,
)
# Aliased: the viewset actions below are also called `chart` and
# `discontinue`, and a method calling a same-named global reads like recursion.
from ..services import bedside_warnings, overdue_doses, record_administration, schedule_doses
from ..services import chart as build_chart
from ..services import discontinue as discontinue_course

# How late a dose has to be before the ward is told about it. A single number
# hospital-wide would either cry wolf or stay silent; it is a parameter here and
# a ward setting later.
OVERDUE_AFTER_MINUTES = 60


class ScheduledDoseViewSet(FacilityScopedMixin, viewsets.ReadOnlyModelViewSet):
    """Due doses, the chart, and what happened to each.

    Read-only as a resource: a dose falls due because a prescription says so,
    not because somebody added a row.
    """

    queryset = ScheduledDose.objects.none()
    serializer_class = ScheduledDoseSerializer
    permission_classes = [HasPermission]

    required_permissions = {
        "list": "inpatient.view_scheduleddose",
        "retrieve": "inpatient.view_scheduleddose",
        "chart": "inpatient.view_scheduleddose",
        "overdue": "inpatient.view_scheduleddose",
        "warnings": "inpatient.view_scheduleddose",
        "schedule": "inpatient.add_scheduleddose",
        "record": "inpatient.add_medicationadministration",
        "discontinue": "inpatient.change_scheduleddose",
    }

    def get_queryset(self):
        queryset = self._scope(
            ScheduledDose.objects.select_related(
                "prescription_item__medication", "patient", "admission"
            ).prefetch_related("administrations__administered_by"),
            field="admission__facility_id",
        )
        params = self.request.query_params
        if params.get("admission"):
            queryset = queryset.filter(admission_id=params["admission"])
        if params.get("status") == "outstanding":
            queryset = queryset.filter(
                administrations__isnull=True, cancelled_at__isnull=True
            )
        return queryset

    def facility_for_permission(self, request):
        admission_id = request.data.get("admission") or request.query_params.get(
            "admission"
        )
        if admission_id:
            admission = Admission.objects.filter(
                pk=admission_id
            ).select_related("facility").first()
            return admission.facility if admission else None
        if self.action in {"record", "warnings"} and self.kwargs.get("pk"):
            dose = ScheduledDose.objects.filter(
                pk=self.kwargs["pk"]
            ).select_related("admission__facility").first()
            return dose.admission.facility if dose else None
        return None

    # --- building the chart ---------------------------------------------------

    @extend_schema(
        parameters=[
            OpenApiParameter("admission", int, required=True),
            OpenApiParameter("days", int, description="Window, default 7."),
        ],
        summary="The MAR as a chart",
    )
    @action(detail=False, methods=["get"])
    def chart(self, request):
        """AC-90. Rows are medications, columns are due times, and every cell
        states its state in words as well as colour."""
        admission = Admission.objects.filter(
            pk=request.query_params.get("admission")
        ).first()
        if admission is None:
            return Response(
                {"detail": "Say which admission."}, status=http.HTTP_400_BAD_REQUEST
            )
        days = int(request.query_params.get("days") or 7)
        return Response(
            build_chart(
                admission=admission, days=days,
                overdue_after_minutes=OVERDUE_AFTER_MINUTES,
            )
        )

    @extend_schema(
        parameters=[OpenApiParameter("ward", int), OpenApiParameter("facility", int)],
        responses={200: ScheduledDoseSerializer(many=True)},
        summary="Doses nobody has recorded, past their window",
    )
    @action(detail=False, methods=["get"])
    def overdue(self, request):
        """AC-91. A dose with no outcome is indistinguishable from a dose nobody
        gave, so it has to be surfaced rather than sit quietly on a chart."""
        from facilities.models import Facility
        from ..models import Ward

        ward = Ward.objects.filter(pk=request.query_params.get("ward")).first()
        facility = Facility.objects.filter(
            pk=request.query_params.get("facility")
        ).first()
        # `lookback=all` returns the whole backlog, which is what reconciling a
        # week of charts needs. The default window is what a shift needs.
        lookback = request.query_params.get("lookback")
        hours = None if lookback == "all" else int(lookback or 24)
        doses = overdue_doses(
            ward=ward, facility=facility, overdue_after_minutes=OVERDUE_AFTER_MINUTES,
            lookback_hours=hours,
        )
        # Scope to what the caller may see, the same as any other list here.
        allowed = self._scope(
            ScheduledDose.objects.filter(pk__in=[dose.pk for dose in doses]),
            field="admission__facility_id",
        ).select_related("prescription_item__medication", "patient", "admission")
        return Response(self.get_serializer(allowed, many=True).data)

    @extend_schema(
        request=None,
        responses={201: ScheduledDoseSerializer(many=True)},
        summary="Put an inpatient prescription line on the chart",
    )
    @action(detail=False, methods=["post"])
    def schedule(self, request):
        """AC-83. Idempotent: a retry cannot put two of every dose on the chart."""
        item = PrescriptionItem.objects.filter(
            pk=request.data.get("prescription_item")
        ).select_related("prescription__admission").first()
        if item is None:
            return Response(
                {"prescription_item": "No such prescription line."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        admission = item.prescription.admission
        if admission is None:
            return Response(
                {"prescription_item": "That prescription is not against an admission, "
                                      "so it has no ward drug chart."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        try:
            doses = schedule_doses(
                prescription_item=item, admission=admission, actor=request.user
            )
        except ValidationError as error:
            return Response({"detail": error.messages}, status=http.HTTP_400_BAD_REQUEST)
        return Response(
            self.get_serializer(doses, many=True).data, status=http.HTTP_201_CREATED
        )

    # --- giving a dose --------------------------------------------------------

    @extend_schema(summary="Safety warnings for this dose, before giving it")
    @action(detail=True, methods=["get"])
    def warnings(self, request, pk=None):
        """AC-88's readable half.

        Checked again at the bedside rather than trusted from prescribing time:
        the prescriber may have overridden it, the allergy may have been recorded
        since, or this may simply be the wrong patient's trolley.
        """
        dose = self.get_object()
        warnings = bedside_warnings(
            patient=dose.patient, medication=dose.prescription_item.medication
        )
        return Response({
            "dose": dose.pk,
            "medication": str(dose.prescription_item.medication),
            "patient": dose.patient.full_name,
            "warnings": [
                {"kind": warning.kind, "severity": warning.severity,
                 "detail": warning.detail}
                for warning in warnings
            ],
        })

    @extend_schema(
        request=RecordAdministrationSerializer,
        responses={201: MedicationAdministrationSerializer},
        summary="Record what happened to a due dose",
    )
    @action(detail=True, methods=["post"])
    def record(self, request, pk=None):
        """AC-84 to AC-88.

        A repeat of the same request returns the first outcome with 200 rather
        than creating a second: the unique constraint on the dose makes a
        double-tap idempotent instead of a double dose.
        """
        dose = self.get_object()
        serializer = RecordAdministrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        batch = None
        if data.get("batch"):
            batch = StockBatch.objects.filter(pk=data["batch"]).first()
            if batch is None:
                return Response(
                    {"batch": "No such stock batch."}, status=http.HTTP_400_BAD_REQUEST
                )

        try:
            administration, created = record_administration(
                scheduled_dose=dose,
                state=data["state"],
                actor=request.user,
                administered_at=data.get("administered_at"),
                dose_given=data.get("dose_given"),
                batch=batch,
                reason=data.get("reason", ""),
                note=data.get("note", ""),
                override_reason=data.get("override_reason", ""),
                request=request,
            )
        except ValidationError as error:
            detail = (
                error.message_dict if hasattr(error, "message_dict") else error.messages
            )
            return Response({"detail": detail}, status=http.HTTP_400_BAD_REQUEST)

        return Response(
            MedicationAdministrationSerializer(administration).data,
            status=http.HTTP_201_CREATED if created else http.HTTP_200_OK,
        )

    @extend_schema(
        request=DiscontinueSerializer,
        summary="Stop a course",
    )
    @action(detail=False, methods=["post"])
    def discontinue(self, request):
        """AC-89. Future doses go; doses already given stay exactly as they were."""
        item = PrescriptionItem.objects.filter(
            pk=request.data.get("prescription_item")
        ).select_related("prescription__admission").first()
        if item is None:
            return Response(
                {"prescription_item": "No such prescription line."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        serializer = DiscontinueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            cancelled = discontinue_course(
                prescription_item=item,
                actor=request.user,
                reason=serializer.validated_data["reason"],
            )
        except ValidationError as error:
            return Response({"detail": error.messages}, status=http.HTTP_400_BAD_REQUEST)
        return Response({
            "prescription_item": item.pk,
            "future_doses_cancelled": cancelled,
            "doses_already_given": MedicationAdministration.objects.filter(
                scheduled_dose__prescription_item=item,
                state__in=list(MedicationAdministration.CONSUMES_STOCK),
            ).count(),
        })


class MedicationAdministrationViewSet(FacilityScopedMixin, viewsets.ReadOnlyModelViewSet):
    """What was given, by whom, from which batch.

    Read-only everywhere: an administration is recorded through the dose it
    answers, and it is never edited afterwards. A drug chart that could be
    tidied up later is not a drug chart.
    """

    queryset = MedicationAdministration.objects.none()
    serializer_class = MedicationAdministrationSerializer
    permission_classes = [HasPermission]

    required_permissions = {
        "list": "inpatient.view_medicationadministration",
        "retrieve": "inpatient.view_medicationadministration",
    }

    def get_queryset(self):
        queryset = self._scope(
            MedicationAdministration.objects.select_related(
                "scheduled_dose__prescription_item__medication", "administered_by",
                "batch", "patient", "admission",
            ),
            field="admission__facility_id",
        )
        params = self.request.query_params
        if params.get("admission"):
            queryset = queryset.filter(admission_id=params["admission"])
        if params.get("state"):
            queryset = queryset.filter(state__in=params["state"].split(","))
        return queryset
