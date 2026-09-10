"""Maternity over HTTP.

A hospital that does not provide maternity grants none of these permissions,
and every endpoint here refuses — which is what AC-173 asks for. The
navigation follows the same permissions, so the module leaves no trace on a
hospital that does not use it.
"""
from django.core.exceptions import ValidationError
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import User
from audit.models import AuditEvent
from core.permissions import FacilityScopedMixin, HasPermission
from facilities.models import Facility
from inpatient.models import Admission
from patients.models import Patient

from . import services
from .models import Delivery, Pregnancy
from .serializers import (
    AntenatalVisitSerializer,
    BookPregnancySerializer,
    DeliverSerializer,
    DeliverySerializer,
    EndPregnancySerializer,
    PregnancySerializer,
    ReviseEddSerializer,
)


def _refusal(error, status=http.HTTP_400_BAD_REQUEST):
    detail = error.message_dict if hasattr(error, "message_dict") else error.messages
    return Response({"detail": detail}, status=status)


class PregnancyViewSet(FacilityScopedMixin, viewsets.ModelViewSet):
    """AC-171, AC-172."""

    queryset = Pregnancy.objects.none()
    serializer_class = PregnancySerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "head", "options"]
    required_permissions = {
        "list": "maternity.view_pregnancy",
        "retrieve": "maternity.view_pregnancy",
        "create": "maternity.book_pregnancy",
        "revise_edd": "maternity.book_pregnancy",
        "antenatal": "maternity.record_antenatal_visit",
        "deliver": "maternity.record_delivery",
        "end": "maternity.book_pregnancy",
        "due": "maternity.view_pregnancy",
    }

    def get_queryset(self):
        queryset = self._scope(
            Pregnancy.objects.select_related("patient", "facility", "booked_by")
            .prefetch_related(
                "antenatal_visits__seen_by", "delivery__babies__patient",
                "delivery__delivered_by",
            )
        )
        params = self.request.query_params
        if params.get("status"):
            queryset = queryset.filter(status__in=params["status"].split(","))
        if params.get("patient"):
            queryset = queryset.filter(patient_id=params["patient"])
        if params.get("open") == "true":
            queryset = queryset.filter(status=Pregnancy.ONGOING)
        return queryset

    def facility_for_permission(self, request):
        if self.action == "create":
            return Facility.objects.filter(pk=request.data.get("facility")).first()
        return None

    @extend_schema(request=BookPregnancySerializer,
                   responses={201: PregnancySerializer},
                   summary="Book a pregnancy")
    def create(self, request, *args, **kwargs):
        serializer = BookPregnancySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        patient = Patient.objects.filter(pk=data["patient"]).first()
        facility = Facility.objects.filter(pk=data["facility"]).first()
        if patient is None or facility is None:
            return Response({"detail": "No such patient or facility."},
                            status=http.HTTP_400_BAD_REQUEST)
        try:
            pregnancy = services.book(
                patient=patient, facility=facility, actor=request.user,
                estimated_delivery_date=data["estimated_delivery_date"],
                last_menstrual_period=data["last_menstrual_period"],
                edd_basis=data["edd_basis"], edd_basis_note=data["edd_basis_note"],
                gravida=data["gravida"], parity=data["parity"],
                previous_losses=data["previous_losses"],
                risk_factors=data["risk_factors"],
            )
        except ValidationError as refusal:
            return _refusal(refusal)

        AuditEvent.record(
            action="pregnancy.booked", actor=request.user, resource=pregnancy,
            patient=patient, facility=facility,
            after={"edd": str(pregnancy.estimated_delivery_date),
                   "basis": pregnancy.edd_basis,
                   "gravida": pregnancy.gravida, "parity": pregnancy.parity},
            request=request,
        )
        return Response(self.get_serializer(pregnancy).data,
                        status=http.HTTP_201_CREATED)

    @extend_schema(request=ReviseEddSerializer, responses={200: PregnancySerializer},
                   summary="Re-date after a scan")
    @action(detail=True, methods=["post"], url_path="revise-edd",
            url_name="revise-edd")
    def revise_edd(self, request, pk=None):
        pregnancy = self.get_object()
        serializer = ReviseEddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        before = pregnancy.estimated_delivery_date
        try:
            services.revise_edd(
                pregnancy=pregnancy, actor=request.user,
                **serializer.validated_data,
            )
        except ValidationError as refusal:
            return _refusal(refusal)

        AuditEvent.record(
            action="pregnancy.edd_revised", actor=request.user, resource=pregnancy,
            patient=pregnancy.patient, facility=pregnancy.facility,
            before={"edd": str(before)},
            after={"edd": str(pregnancy.estimated_delivery_date),
                   "basis": pregnancy.edd_basis},
            reason=pregnancy.edd_basis_note, request=request,
        )
        return Response(self.get_serializer(pregnancy).data)

    @extend_schema(request=AntenatalVisitSerializer,
                   responses={201: AntenatalVisitSerializer},
                   summary="Record an antenatal contact")
    @action(detail=True, methods=["post"])
    def antenatal(self, request, pk=None):
        pregnancy = self.get_object()
        serializer = AntenatalVisitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        findings = dict(serializer.validated_data)
        findings.pop("pregnancy", None)
        findings.pop("sequence", None)
        findings.pop("seen_by", None)
        visit = findings.pop("visit", None)
        seen_at = findings.pop("seen_at", None)

        try:
            record = services.record_antenatal_visit(
                pregnancy=pregnancy, actor=request.user, seen_at=seen_at,
                visit=visit, **findings,
            )
        except ValidationError as refusal:
            return _refusal(refusal)

        AuditEvent.record(
            action="antenatal.visit_recorded", actor=request.user, resource=record,
            patient=pregnancy.patient, facility=pregnancy.facility,
            after={"sequence": record.sequence,
                   "gestation_weeks": record.gestation_weeks,
                   "bp": f"{record.systolic_bp}/{record.diastolic_bp}"
                   if record.systolic_bp else None},
            request=request,
        )
        return Response(AntenatalVisitSerializer(record).data,
                        status=http.HTTP_201_CREATED)

    @extend_schema(request=DeliverSerializer, responses={201: DeliverySerializer},
                   summary="Record the delivery — every baby gets a record")
    @action(detail=True, methods=["post"])
    def deliver(self, request, pk=None):
        pregnancy = self.get_object()
        serializer = DeliverSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)

        midwife = User.objects.filter(pk=data.pop("delivered_by")).first()
        if midwife is None:
            return Response({"delivered_by": ["No such user."]},
                            status=http.HTTP_400_BAD_REQUEST)
        admission_id = data.pop("admission")
        admission = (
            Admission.objects.filter(pk=admission_id).first() if admission_id else None
        )
        babies = data.pop("babies")

        try:
            delivery = services.deliver(
                pregnancy=pregnancy, actor=request.user, delivered_by=midwife,
                admission=admission, babies=babies, **data,
            )
        except ValidationError as refusal:
            return _refusal(refusal, status=http.HTTP_409_CONFLICT)

        AuditEvent.record(
            action="delivery.recorded", actor=request.user, resource=delivery,
            patient=pregnancy.patient, facility=pregnancy.facility,
            after={"mode": delivery.mode,
                   "delivered_at": delivery.delivered_at.isoformat(),
                   "babies": [
                       {"hospital_number": baby.patient.hospital_number,
                        "outcome": baby.outcome,
                        "weight_grams": baby.birth_weight_grams}
                       for baby in delivery.babies.select_related("patient")
                   ]},
            request=request,
        )
        return Response(DeliverySerializer(delivery).data,
                        status=http.HTTP_201_CREATED)

    @extend_schema(request=EndPregnancySerializer,
                   responses={200: PregnancySerializer},
                   summary="Close a pregnancy that did not end in a delivery here")
    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        pregnancy = self.get_object()
        serializer = EndPregnancySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.end_pregnancy(
                pregnancy=pregnancy, actor=request.user,
                reason=serializer.validated_data["reason"],
                status=serializer.validated_data["status"],
            )
        except ValidationError as refusal:
            return _refusal(refusal, status=http.HTTP_409_CONFLICT)

        AuditEvent.record(
            action="pregnancy.ended", actor=request.user, resource=pregnancy,
            patient=pregnancy.patient, facility=pregnancy.facility,
            after={"status": pregnancy.status},
            reason=pregnancy.ended_reason, request=request,
        )
        return Response(self.get_serializer(pregnancy).data)

    @extend_schema(
        parameters=[OpenApiParameter("facility", int),
                    OpenApiParameter("within_days", int)],
        responses={200: PregnancySerializer(many=True)},
        summary="Who is due, and who is overdue",
    )
    @action(detail=False, methods=["get"])
    def due(self, request):
        facility = Facility.objects.filter(
            pk=request.query_params.get("facility")
        ).first()
        if facility is None:
            return Response({"facility": ["Name a facility."]},
                            status=http.HTTP_400_BAD_REQUEST)
        permitted = set(request.user.facilities_for("maternity.view_pregnancy"))
        if not request.user.is_superuser and None not in permitted:
            if facility.pk not in permitted:
                return Response({"detail": "Not found."},
                                status=http.HTTP_404_NOT_FOUND)

        within = int(request.query_params.get("within_days", 28))
        return Response({
            "due": PregnancySerializer(
                services.due_soon(facility=facility, within_days=within), many=True
            ).data,
            "overdue": PregnancySerializer(
                services.overdue(facility=facility), many=True
            ).data,
            "as_at": timezone.localdate(),
        })


class DeliveryViewSet(FacilityScopedMixin, viewsets.ReadOnlyModelViewSet):
    """Read-only. A delivery is recorded through its pregnancy, once."""

    queryset = Delivery.objects.none()
    serializer_class = DeliverySerializer
    permission_classes = [HasPermission]
    required_permissions = {
        "list": "maternity.view_delivery",
        "retrieve": "maternity.view_delivery",
    }

    def get_queryset(self):
        return self._scope(
            Delivery.objects.select_related(
                "pregnancy__patient", "delivered_by", "recorded_by"
            ).prefetch_related("babies__patient"),
            field="pregnancy__facility_id",
        )
