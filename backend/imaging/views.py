"""Radiology over HTTP: the catalogue, the worklist, and the report.

AC-96's negative half is enforced here rather than in the client: whether the
caller may see an unreleased report is decided server-side and passed into the
serializer. A client that decided for itself would be one refresh away from
showing a clinician a provisional conclusion.
"""
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status as http, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from audit.models import AuditEvent
from core.episodes import episode_owner, facility_from_request
from core.permissions import FacilityScopedMixin, HasPermission

from .models import (
    ImagingModality,
    ImagingOrder,
    ImagingOrderItem,
    ImagingProcedure,
    ImagingReport,
)
from .reporting import (
    acknowledge_critical,
    amend_report,
    perform,
    schedule,
    unacknowledged_critical_findings,
    verify,
    write_report,
)
from .serializers import (
    AcknowledgeFindingSerializer,
    AmendReportSerializer,
    CancelItemSerializer,
    ImagingModalitySerializer,
    ImagingOrderItemSerializer,
    ImagingOrderSerializer,
    ImagingProcedureSerializer,
    ImagingReportSerializer,
    PerformSerializer,
    ReportSerializer,
    ScheduleSerializer,
)


def _validation_response(error):
    detail = error.message_dict if hasattr(error, "message_dict") else error.messages
    return Response({"detail": detail}, status=http.HTTP_400_BAD_REQUEST)


class ImagingModalityViewSet(viewsets.ModelViewSet):
    """Configuration: which modalities this hospital actually has."""

    queryset = ImagingModality.objects.all()
    serializer_class = ImagingModalitySerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "imaging.view_imagingmodality",
        "retrieve": "imaging.view_imagingmodality",
        "create": "imaging.add_imagingmodality",
        "partial_update": "imaging.change_imagingmodality",
    }


class ImagingProcedureViewSet(viewsets.ModelViewSet):
    """Configuration: the examination catalogue. AC-94."""

    queryset = ImagingProcedure.objects.select_related("modality", "service")
    serializer_class = ImagingProcedureSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "imaging.view_imagingprocedure",
        "retrieve": "imaging.view_imagingprocedure",
        "create": "imaging.add_imagingprocedure",
        "partial_update": "imaging.change_imagingprocedure",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params
        if params.get("modality"):
            queryset = queryset.filter(modality_id=params["modality"])
        if params.get("include_inactive") != "true":
            queryset = queryset.filter(is_active=True)
        return queryset

    def get_serializer_context(self):
        """Prices are per facility, so the catalogue needs to know which one."""
        from facilities.models import Facility

        context = super().get_serializer_context()
        facility_id = self.request.query_params.get("facility")
        context["facility"] = (
            Facility.objects.filter(pk=facility_id).first() if facility_id else None
        )
        return context

    def perform_create(self, serializer):
        procedure = serializer.save()
        AuditEvent.record(
            action="imaging.procedure_added",
            actor=self.request.user,
            resource=procedure,
            after={"name": procedure.name, "code": procedure.code_short,
                   "modality": procedure.modality.code},
            request=self.request,
        )


class ImagingOrderViewSet(FacilityScopedMixin, viewsets.ModelViewSet):
    """Requesting imaging, and the report the clinician reads."""

    queryset = ImagingOrder.objects.none()
    serializer_class = ImagingOrderSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "head", "options"]

    required_permissions = {
        "list": "imaging.view_imagingorder",
        "retrieve": "imaging.view_imagingorder",
        "worklist": "imaging.view_imagingorder",
        "critical": "imaging.view_imagingorder",
        "create": "imaging.add_imagingorder",
    }

    def get_queryset(self):
        queryset = ImagingOrder.objects.select_related(
            "patient", "facility", "ordered_by", "visit", "admission"
        ).prefetch_related(
            Prefetch(
                "items",
                queryset=ImagingOrderItem.objects.select_related(
                    "procedure__modality", "performed_by", "scheduled_by"
                ).prefetch_related(
                    Prefetch(
                        "reports",
                        queryset=ImagingReport.objects.select_related(
                            "reported_by", "verified_by"
                        ).prefetch_related("acknowledgements__acknowledged_by"),
                    )
                ),
            )
        )
        queryset = self._scope(queryset)
        params = self.request.query_params
        if params.get("patient"):
            queryset = queryset.filter(patient_id=params["patient"])
        if params.get("visit"):
            queryset = queryset.filter(visit_id=params["visit"])
        if params.get("admission"):
            queryset = queryset.filter(admission_id=params["admission"])
        if params.get("status"):
            queryset = queryset.filter(
                items__status__in=params["status"].split(",")
            ).distinct()
        return queryset

    def get_serializer_context(self):
        """Whether this caller may read an unreleased report. AC-96.

        Decided here, once, from the permission table — anyone who could verify
        or write a report is already inside the department, and hiding a draft
        from the person about to sign it off would be theatre.
        """
        context = super().get_serializer_context()
        user = self.request.user
        context["may_see_drafts"] = (
            user.is_superuser
            or bool(user.facilities_for("imaging.verify_imagingreport"))
            or bool(user.facilities_for("imaging.add_imagingreport"))
        )
        return context

    def facility_for_permission(self, request):
        if self.action == "create":
            return facility_from_request(request)
        return None

    def create(self, request, *args, **kwargs):
        """AC-95. Records the requesting clinician and the clinical question."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        visit = data.pop("visit", None)
        admission = data.pop("admission", None)
        procedures = data.pop("procedures")
        patient, facility = episode_owner(visit=visit, admission=admission)

        order = ImagingOrder.objects.create(
            visit=visit,
            admission=admission,
            patient=patient,
            facility=facility,
            ordered_by=request.user,
            priority=data.get("priority", ImagingOrder.ROUTINE),
            clinical_question=data["clinical_question"].strip(),
            relevant_history=data.get("relevant_history", ""),
            is_pregnant=data.get("is_pregnant", False),
        )
        for procedure in dict.fromkeys(procedures):
            ImagingOrderItem.objects.create(order=order, procedure=procedure)

        AuditEvent.record(
            action="imaging.ordered",
            actor=request.user,
            resource=order,
            patient=patient,
            facility=facility,
            after={
                "order_number": order.order_number,
                "procedures": [procedure.code_short for procedure in procedures],
                "priority": order.priority,
                "clinical_question": order.clinical_question[:200],
                "pregnant": order.is_pregnant,
            },
            request=request,
        )
        return Response(
            self.get_serializer(self.get_queryset().get(pk=order.pk)).data,
            status=http.HTTP_201_CREATED,
        )

    @extend_schema(
        parameters=[OpenApiParameter("status", description="Comma-separated states.")],
        summary="The department's worklist",
    )
    @action(detail=False, methods=["get"])
    def worklist(self, request):
        """What radiology has to do, oldest first, urgent ahead of routine."""
        states = (
            request.query_params.get("status")
            or "requested,scheduled,performed,reported"
        ).split(",")
        items = ImagingOrderItem.objects.filter(
            status__in=states, order__in=self.get_queryset()
        ).select_related(
            "procedure__modality", "order__patient", "order__ordered_by"
        ).prefetch_related("reports").order_by("-order__priority", "order__ordered_at")[:300]
        return Response([
            {
                "item": item.pk,
                "order": item.order_id,
                "order_number": item.order.order_number,
                "patient": item.order.patient.full_name,
                "hospital_number": item.order.patient.hospital_number,
                "procedure": item.procedure.name,
                "modality": item.procedure.modality.name,
                "body_part": item.procedure.body_part,
                "priority": item.order.priority,
                "status": item.status,
                "status_display": item.get_status_display(),
                "allowed_transitions": sorted(item.TRANSITIONS.get(item.status, set())),
                "ordered_at": item.order.ordered_at,
                "scheduled_for": item.scheduled_for,
                "clinical_question": item.order.clinical_question,
                "is_pregnant": item.order.is_pregnant,
                "requires_contrast": item.procedure.requires_contrast,
                "contraindications": item.procedure.contraindications,
            }
            for item in items
        ])

    @extend_schema(summary="Critical findings nobody has answered for")
    @action(detail=False, methods=["get"])
    def critical(self, request):
        """AC-98. The same list the laboratory keeps, for the same reason."""
        facility_ids = set(
            self.get_queryset().values_list("facility_id", flat=True).distinct()
        )
        reports = [
            report for report in unacknowledged_critical_findings()
            if report.order_item.order.facility_id in facility_ids
        ]
        return Response([
            {
                "report": report.pk,
                "order": report.order_item.order_id,
                "patient": report.order_item.order.patient.full_name,
                "hospital_number": report.order_item.order.patient.hospital_number,
                "procedure": report.order_item.procedure.name,
                "finding": report.critical_finding,
                "conclusion": report.conclusion,
                "reported_by": report.reported_by.full_name,
                "verified_at": report.verified_at,
                "requesting_clinician": report.order_item.order.ordered_by.full_name,
            }
            for report in reports
        ])


class ImagingOrderItemViewSet(FacilityScopedMixin, viewsets.GenericViewSet):
    """One examination through its states. AC-95, AC-96, AC-97."""

    queryset = ImagingOrderItem.objects.none()
    serializer_class = ImagingOrderItemSerializer
    permission_classes = [HasPermission]

    required_permissions = {
        "retrieve": "imaging.view_imagingorder",
        "schedule": "imaging.schedule_imaging",
        "perform": "imaging.perform_imaging",
        "report": "imaging.add_imagingreport",
        "cancel": "imaging.change_imagingorderitem",
    }

    def get_queryset(self):
        queryset = ImagingOrderItem.objects.select_related(
            "procedure__modality", "order__patient", "order__facility",
            "performed_by", "scheduled_by",
        ).prefetch_related("reports__reported_by", "reports__verified_by")
        return self._scope(queryset, field="order__facility_id")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        user = self.request.user
        context["may_see_drafts"] = (
            user.is_superuser
            or bool(user.facilities_for("imaging.verify_imagingreport"))
            or bool(user.facilities_for("imaging.add_imagingreport"))
        )
        return context

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)

    def _refuse(self, item, attempted, error, request):
        AuditEvent.record(
            action="imaging.transition_refused",
            actor=request.user,
            outcome=AuditEvent.DENIED,
            resource=item.order,
            patient=item.order.patient,
            facility=item.order.facility,
            after={"procedure": item.procedure.code_short, "from": item.status,
                   "attempted": attempted, "detail": error.messages},
            request=request,
        )
        return Response({"detail": error.messages}, status=http.HTTP_409_CONFLICT)

    @extend_schema(request=ScheduleSerializer, responses={200: ImagingOrderItemSerializer})
    @action(detail=True, methods=["post"])
    def schedule(self, request, pk=None):
        item = self.get_object()
        serializer = ScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            schedule(
                order_item=item, actor=request.user,
                when=serializer.validated_data["scheduled_for"],
                note=serializer.validated_data["note"], request=request,
            )
        except ValidationError as error:
            return self._refuse(item, "scheduled", error, request)
        return Response(self.get_serializer(self.get_object()).data)

    @extend_schema(request=PerformSerializer, responses={200: ImagingOrderItemSerializer})
    @action(detail=True, methods=["post"])
    def perform(self, request, pk=None):
        item = self.get_object()
        serializer = PerformSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            perform(
                order_item=item, actor=request.user,
                at=serializer.validated_data.get("performed_at"),
                accession_number=serializer.validated_data["accession_number"],
                views_taken=serializer.validated_data["views_taken"],
                technique_note=serializer.validated_data["technique_note"],
                contrast_given=serializer.validated_data["contrast_given"],
                request=request,
            )
        except ValidationError as error:
            return self._refuse(item, "performed", error, request)
        return Response(self.get_serializer(self.get_object()).data)

    @extend_schema(request=ReportSerializer, responses={201: ImagingReportSerializer})
    @action(detail=True, methods=["post"])
    def report(self, request, pk=None):
        """Write the report. Unverified until someone signs it off."""
        item = self.get_object()
        serializer = ReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            report = write_report(
                order_item=item, actor=request.user, request=request,
                **serializer.validated_data,
            )
        except ValidationError as error:
            if "cannot go from" in " ".join(error.messages):
                return self._refuse(item, "reported", error, request)
            return _validation_response(error)
        return Response(
            ImagingReportSerializer(report).data, status=http.HTTP_201_CREATED
        )

    @extend_schema(request=CancelItemSerializer, responses={200: ImagingOrderItemSerializer})
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        item = self.get_object()
        serializer = CancelItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            item.advance_to(ImagingOrderItem.CANCELLED)
        except ValidationError as error:
            return self._refuse(item, "cancelled", error, request)
        item.cancelled_reason = serializer.validated_data["reason"]
        item.save(update_fields=["status", "cancelled_reason"])
        AuditEvent.record(
            action="imaging.cancelled",
            actor=request.user,
            resource=item.order,
            patient=item.order.patient,
            facility=item.order.facility,
            after={"procedure": item.procedure.code_short},
            reason=item.cancelled_reason,
            request=request,
        )
        return Response(self.get_serializer(self.get_object()).data)


class ImagingReportViewSet(FacilityScopedMixin, viewsets.GenericViewSet):
    """Verifying, amending and acknowledging a report."""

    queryset = ImagingReport.objects.none()
    serializer_class = ImagingReportSerializer
    permission_classes = [HasPermission]

    required_permissions = {
        "retrieve": "imaging.view_imagingorder",
        "verify": "imaging.verify_imagingreport",
        "amend": "imaging.amend_imagingreport",
        "acknowledge": "imaging.acknowledge_critical_finding",
    }

    def get_queryset(self):
        queryset = ImagingReport.objects.select_related(
            "order_item__procedure", "order_item__order__patient",
            "order_item__order__facility", "reported_by", "verified_by",
        ).prefetch_related("acknowledgements__acknowledged_by")
        return self._scope(queryset, field="order_item__order__facility_id")

    def retrieve(self, request, pk=None):
        report = self.get_object()
        if not report.is_verified and not (
            request.user.is_superuser
            or request.user.facilities_for("imaging.verify_imagingreport")
            or request.user.facilities_for("imaging.add_imagingreport")
        ):
            # AC-96 (negative). Not 403: whether a draft exists is the
            # department's business, and the requesting clinician's answer is
            # "nothing released yet", which is the truth.
            return Response(
                {"detail": "That report has not been verified yet.",
                 "awaiting_verification": True},
                status=http.HTTP_404_NOT_FOUND,
            )
        return Response(self.get_serializer(report).data)

    @extend_schema(responses={200: ImagingReportSerializer},
                   summary="Release a report to the requesting clinician")
    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        report = self.get_object()
        try:
            verify(report=report, actor=request.user, request=request)
        except ValidationError as error:
            return Response({"detail": error.messages}, status=http.HTTP_409_CONFLICT)
        return Response(self.get_serializer(self.get_object()).data)

    @extend_schema(request=AmendReportSerializer, responses={201: ImagingReportSerializer},
                   summary="Append an amended version")
    @action(detail=True, methods=["post"])
    def amend(self, request, pk=None):
        report = self.get_object()
        serializer = AmendReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            replacement = amend_report(
                report=report, actor=request.user, request=request,
                **serializer.validated_data,
            )
        except ValidationError as error:
            return _validation_response(error)
        return Response(
            ImagingReportSerializer(replacement).data, status=http.HTTP_201_CREATED
        )

    @extend_schema(request=AcknowledgeFindingSerializer,
                   responses={201: ImagingReportSerializer},
                   summary="Record that a critical finding was acted on")
    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        """AC-98."""
        report = self.get_object()
        serializer = AcknowledgeFindingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            acknowledge_critical(
                report=report, actor=request.user, request=request,
                action_taken=serializer.validated_data["action_taken"],
            )
        except ValidationError as error:
            return _validation_response(error)
        return Response(
            self.get_serializer(self.get_object()).data, status=http.HTTP_201_CREATED
        )
