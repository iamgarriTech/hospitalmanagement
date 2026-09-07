from django.core.exceptions import ValidationError
from drf_spectacular.utils import extend_schema
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from audit.models import AuditEvent
from billing.models import charge
from core.permissions import HasPermission
from visits.models import Visit

from .models import (
    CriticalResultAcknowledgement,
    LabOrder,
    LabOrderItem,
    LabResult,
    LabTest,
    LabTestCategory,
    Specimen,
)
from .results import amend_result, enter_results, verify_results
from .serializers import (
    AcknowledgeSerializer,
    AmendResultSerializer,
    CollectSerializer,
    EnterResultsSerializer,
    LabOrderItemSerializer,
    LabOrderSerializer,
    LabResultSerializer,
    LabTestCategorySerializer,
    LabTestSerializer,
    SpecimenSerializer,
    VerifySerializer,
)


class FacilityScopedMixin:
    def _scope(self, queryset, field="facility_id"):
        user = self.request.user
        if user.is_superuser:
            return queryset
        required = self.required_permissions.get(self.action)
        granted = set(user.facilities_for(required)) if required else set()
        if None in granted:
            return queryset
        return queryset.filter(**{f"{field}__in": [f for f in granted if f is not None]})


class LabTestCategoryViewSet(viewsets.ModelViewSet):
    """Configuration: test categories."""

    queryset = LabTestCategory.objects.all()
    serializer_class = LabTestCategorySerializer
    permission_classes = [HasPermission]
    required_permissions = {
        "list": "laboratory.view_labtestcategory",
        "retrieve": "laboratory.view_labtestcategory",
        "create": "laboratory.add_labtestcategory",
        "update": "laboratory.change_labtestcategory",
        "partial_update": "laboratory.change_labtestcategory",
    }
    http_method_names = ["get", "post", "patch", "head", "options"]


class LabTestViewSet(viewsets.ModelViewSet):
    """Configuration: the test catalogue, its parameters and reference ranges."""

    queryset = LabTest.objects.select_related("category").prefetch_related(
        "parameters__reference_ranges", "panel_members"
    )
    serializer_class = LabTestSerializer
    permission_classes = [HasPermission]
    required_permissions = {
        "list": "laboratory.view_labtest",
        "retrieve": "laboratory.view_labtest",
        "create": "laboratory.add_labtest",
        "update": "laboratory.change_labtest",
        "partial_update": "laboratory.change_labtest",
    }
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("include_inactive") != "true":
            queryset = queryset.filter(is_active=True)
        return queryset


class LabOrderViewSet(FacilityScopedMixin, viewsets.ModelViewSet):
    """Requesting investigations, and the report the clinician reads."""

    queryset = LabOrder.objects.none()
    serializer_class = LabOrderSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "head", "options"]

    required_permissions = {
        "list": "laboratory.view_laborder",
        "retrieve": "laboratory.view_laborder",
        "report": "laboratory.view_laborder",
        "worklist": "laboratory.view_laborder",
        "create": "laboratory.add_laborder",
    }

    def get_queryset(self):
        queryset = LabOrder.objects.select_related(
            "patient", "facility", "ordered_by", "visit"
        ).prefetch_related(
            "items__test__parameters", "items__results__parameter",
            "items__results__acknowledgements__acknowledged_by", "items__specimen",
        )
        queryset = self._scope(queryset)
        params = self.request.query_params
        if params.get("patient"):
            queryset = queryset.filter(patient_id=params["patient"])
        if params.get("visit"):
            queryset = queryset.filter(visit_id=params["visit"])
        return queryset

    def facility_for_permission(self, request):
        if self.action == "create":
            visit = Visit.objects.filter(pk=request.data.get("visit")).first()
            return visit.facility if visit else None
        return None

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        visit = data.pop("visit")
        tests = data.pop("tests")

        order = LabOrder.objects.create(
            visit=visit,
            patient=visit.patient,
            facility=visit.facility,
            ordered_by=request.user,
            priority=data.get("priority", LabOrder.ROUTINE),
            clinical_details=data.get("clinical_details", ""),
        )

        # A panel is ordered as one line but worked as its members.
        expanded = []
        for test in tests:
            if test.is_panel:
                expanded.extend(test.panel_members.filter(is_active=True))
            else:
                expanded.append(test)
        for test in dict.fromkeys(expanded):
            LabOrderItem.objects.create(order=order, test=test)

        # Charge at the point of ordering, from the order itself. `charge` is keyed on
        # the order item, so a retried request cannot bill the patient twice.
        for item in order.items.select_related("test__service"):
            if item.test.service_id:
                charge(
                    visit=visit,
                    service_code=item.test.service.code,
                    description=item.test.name,
                    source_type="laboratory.LabOrderItem",
                    source_id=item.pk,
                    actor=request.user,
                )

        AuditEvent.record(
            action="lab.order_placed",
            actor=request.user,
            resource=order,
            patient=order.patient,
            facility=order.facility,
            after={
                "order_number": order.order_number,
                "priority": order.priority,
                "tests": [item.test.short_code for item in order.items.all()],
            },
            request=request,
        )
        return Response(
            self.get_serializer(self.get_queryset().get(pk=order.pk)).data,
            status=http.HTTP_201_CREATED,
        )

    @extend_schema(summary="The clinician's report: verified results only")
    @action(detail=True, methods=["get"])
    def report(self, request, pk=None):
        """Only verified results appear as results.

        An unverified value must not reach the ordering clinician looking like a
        finding — that is how a provisional number gets acted on.
        """
        order = self.get_object()
        items = []
        for item in order.items.all():
            if item.status == LabOrderItem.VERIFIED:
                items.append(LabOrderItemSerializer(item).data)
            else:
                items.append({
                    "id": item.id,
                    "test": item.test_id,
                    "test_name": item.test.name,
                    "test_code": item.test.short_code,
                    "status": item.status,
                    "status_label": item.get_status_display(),
                    "results": [],
                    "pending": True,
                })
        return Response({
            "order_number": order.order_number,
            "patient_name": order.patient.full_name,
            "hospital_number": order.patient.hospital_number,
            "ordered_at": order.ordered_at,
            "ordered_by": order.ordered_by.email,
            "clinical_details": order.clinical_details,
            "items": items,
        })

    @extend_schema(summary="Laboratory worklist: what needs doing")
    @action(detail=False, methods=["get"])
    def worklist(self, request):
        pending = LabOrderItem.objects.filter(
            order__in=self.get_queryset(),
            status__in=[LabOrderItem.ORDERED, LabOrderItem.COLLECTED,
                        LabOrderItem.PROCESSING, LabOrderItem.RESULTED],
        ).select_related("order__patient", "test").order_by(
            "-order__priority", "order__ordered_at"
        )[:300]
        return Response([
            {
                "item_id": item.id,
                "order_number": item.order.order_number,
                "priority": item.order.priority,
                "patient_name": item.order.patient.full_name,
                "hospital_number": item.order.patient.hospital_number,
                "test": item.test.name,
                "specimen_type": item.test.specimen_type,
                "specimen_requirements": item.test.specimen_requirements,
                "status": item.status,
                "ordered_at": item.order.ordered_at,
            }
            for item in pending
        ])


class LabOrderItemViewSet(FacilityScopedMixin, viewsets.GenericViewSet):
    """The bench workflow: collect, process, result, verify."""

    queryset = LabOrderItem.objects.none()
    serializer_class = LabOrderItemSerializer
    permission_classes = [HasPermission]

    required_permissions = {
        "retrieve": "laboratory.view_laborder",
        "collect": "laboratory.collect_specimen",
        "start_processing": "laboratory.collect_specimen",
        "enter_results": "laboratory.add_labresult",
        "verify": "laboratory.verify_labresult",
        "cancel": "laboratory.change_laborderitem",
    }

    def get_queryset(self):
        queryset = LabOrderItem.objects.select_related(
            "order__patient", "order__facility", "test", "verified_by"
        ).prefetch_related("results__parameter", "results__acknowledgements", "specimen")
        return self._scope(queryset, field="order__facility_id")

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)

    @extend_schema(request=CollectSerializer, responses={200: LabOrderItemSerializer},
                   summary="Collect the specimen and issue its label identifier")
    @action(detail=True, methods=["post"])
    def collect(self, request, pk=None):
        item = self.get_object()
        serializer = CollectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if hasattr(item, "specimen"):
            return Response(
                {"detail": f"Specimen {item.specimen.specimen_id} was already collected."},
                status=http.HTTP_409_CONFLICT,
            )
        try:
            item.advance_to(LabOrderItem.COLLECTED)
        except ValidationError as error:
            return Response({"detail": error.messages[0]}, status=http.HTTP_409_CONFLICT)
        item.save(update_fields=["status"])
        specimen = Specimen.objects.create(
            order_item=item,
            specimen_type=item.test.specimen_type,
            collected_by=request.user,
            condition=serializer.validated_data["condition"],
            note=serializer.validated_data["note"],
        )
        AuditEvent.record(
            action="lab.specimen_collected",
            actor=request.user,
            resource=item.order,
            patient=item.order.patient,
            facility=item.order.facility,
            after={"specimen_id": specimen.specimen_id, "test": item.test.short_code,
                   "condition": specimen.condition},
            request=request,
        )
        return Response({
            "item": self.get_serializer(self.get_queryset().get(pk=item.pk)).data,
            "label": {
                "specimen_id": specimen.specimen_id,
                "patient_name": item.order.patient.full_name,
                "hospital_number": item.order.patient.hospital_number,
                "test": item.test.name,
                "collected_at": specimen.collected_at,
            },
        })

    @extend_schema(request=None, responses={200: LabOrderItemSerializer},
                   summary="Start processing the specimen")
    @action(detail=True, methods=["post"], url_path="start-processing",
            url_name="start-processing")
    def start_processing(self, request, pk=None):
        item = self.get_object()
        try:
            item.advance_to(LabOrderItem.PROCESSING)
        except ValidationError as error:
            return Response({"detail": error.messages[0]}, status=http.HTTP_409_CONFLICT)
        item.save(update_fields=["status"])
        return Response(self.get_serializer(self.get_queryset().get(pk=item.pk)).data)

    @extend_schema(request=EnterResultsSerializer, responses={201: LabOrderItemSerializer},
                   summary="Enter values for this test's parameters")
    @action(detail=True, methods=["post"], url_path="results", url_name="results")
    def enter_results(self, request, pk=None):
        item = self.get_object()
        serializer = EnterResultsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            enter_results(
                order_item=item,
                entries=serializer.validated_data["entries"],
                actor=request.user,
                request=request,
            )
        except ValidationError as error:
            return Response({"detail": error.messages[0]}, status=http.HTTP_400_BAD_REQUEST)
        return Response(
            self.get_serializer(self.get_queryset().get(pk=item.pk)).data,
            status=http.HTTP_201_CREATED,
        )

    @extend_schema(request=VerifySerializer, responses={200: LabOrderItemSerializer},
                   summary="Verify and release the result")
    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        item = self.get_object()
        serializer = VerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            verify_results(
                order_item=item,
                actor=request.user,
                comment=serializer.validated_data["comment"],
                request=request,
            )
        except ValidationError as error:
            return Response({"detail": error.messages[0]}, status=http.HTTP_409_CONFLICT)
        return Response(self.get_serializer(self.get_queryset().get(pk=item.pk)).data)


class LabResultViewSet(FacilityScopedMixin, viewsets.GenericViewSet):
    """Amending a released result, and acknowledging a critical one."""

    queryset = LabResult.objects.none()
    serializer_class = LabResultSerializer
    permission_classes = [HasPermission]

    required_permissions = {
        "retrieve": "laboratory.view_laborder",
        "amend": "laboratory.amend_labresult",
        "acknowledge": "laboratory.acknowledge_critical_result",
        "critical": "laboratory.view_laborder",
    }

    def get_queryset(self):
        queryset = LabResult.objects.select_related(
            "parameter", "order_item__order__patient", "order_item__order__facility"
        ).prefetch_related("acknowledgements__acknowledged_by")
        return self._scope(queryset, field="order_item__order__facility_id")

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)

    @extend_schema(request=AmendResultSerializer, responses={200: LabResultSerializer},
                   summary="Amend a result (reason required; the old value is kept)")
    @action(detail=True, methods=["post"])
    def amend(self, request, pk=None):
        result = self.get_object()
        serializer = AmendResultSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            replacement = amend_result(
                result=result,
                actor=request.user,
                reason=data["reason"],
                value_numeric=data.get("value_numeric"),
                value_text=data.get("value_text"),
                comment=data.get("comment", ""),
                request=request,
            )
        except ValidationError as error:
            return Response({"detail": error.messages[0]}, status=http.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(replacement).data)

    @extend_schema(request=AcknowledgeSerializer, responses={200: LabResultSerializer},
                   summary="Acknowledge a critical result and record the action taken")
    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        result = self.get_object()
        if not result.is_critical:
            return Response(
                {"detail": "That result is not flagged critical."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        serializer = AcknowledgeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        acknowledgement = CriticalResultAcknowledgement.objects.create(
            result=result,
            acknowledged_by=request.user,
            action_taken=serializer.validated_data["action_taken"],
        )
        order = result.order_item.order
        AuditEvent.record(
            action="lab.critical_result_acknowledged",
            actor=request.user,
            resource=order,
            patient=order.patient,
            facility=order.facility,
            after={"parameter": result.parameter.name, "value": result.display_value,
                   "action_taken": acknowledgement.action_taken},
            request=request,
        )
        # Re-read: get_object() prefetched the acknowledgements, so the cached relation
        # would not include the one just created.
        return Response(self.get_serializer(self.get_queryset().get(pk=result.pk)).data)

    @extend_schema(summary="Critical results still awaiting acknowledgement")
    @action(detail=False, methods=["get"])
    def critical(self, request):
        """The list that must not be allowed to grow silently."""
        outstanding = self.get_queryset().filter(
            is_current=True,
            flag__in=list(LabResult.CRITICAL_FLAGS),
            acknowledgements__isnull=True,
        ).order_by("entered_at")
        return Response([
            {
                "result_id": result.id,
                "patient_name": result.order_item.order.patient.full_name,
                "hospital_number": result.order_item.order.patient.hospital_number,
                "test": result.order_item.test.name,
                "parameter": result.parameter.name,
                "value": f"{result.display_value} {result.unit}".strip(),
                "flag_label": result.flag_label,
                "reference": result.reference_text,
                "entered_at": result.entered_at,
                "ordered_by": result.order_item.order.ordered_by.email,
            }
            for result in outstanding
        ])
