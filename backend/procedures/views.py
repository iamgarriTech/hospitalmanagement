"""Procedures and theatre over HTTP.

Requesting, consenting, booking and performing are separate actions rather
than a writable `status`, because each is a different clinical act with a
different permission behind it — and a writable status would let a client set
`performed` on a procedure nobody did, which is the one thing AC-163 forbids.

`OperationNoteViewSet` has no update verb. Amending appends a version through
its own action, so there is no route by which the superseded text can be lost.
"""
from datetime import datetime

from django.core.exceptions import ValidationError
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import User
from audit.models import AuditEvent
from core.episodes import episode_owner, facility_from_request
from core.permissions import FacilityScopedMixin, HasPermission
from facilities.models import Facility
from inventory.models import InventoryItem, Store
from pharmacy.models import Medication

from . import services
from .models import (
    OperationNote,
    PerformedProcedure,
    Procedure,
    ProcedureCategory,
    ProcedureRequest,
    Theatre,
    TheatreBooking,
)
from .serializers import (
    AmendNoteSerializer,
    BookTheatreSerializer,
    ConsentSerializer,
    OperationNoteSerializer,
    PerformedProcedureSerializer,
    PerformSerializer,
    ProcedureCategorySerializer,
    ProcedureRequestSerializer,
    ProcedureSerializer,
    ReasonSerializer,
    RecordConsentSerializer,
    TheatreBookingSerializer,
    TheatreSerializer,
)


def _refusal(error, status=http.HTTP_400_BAD_REQUEST):
    detail = error.message_dict if hasattr(error, "message_dict") else error.messages
    return Response({"detail": detail}, status=status)


class ProcedureCategoryViewSet(viewsets.ModelViewSet):
    queryset = ProcedureCategory.objects.all()
    serializer_class = ProcedureCategorySerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "procedures.view_procedurecategory",
        "retrieve": "procedures.view_procedurecategory",
        "create": "procedures.add_procedurecategory",
        "partial_update": "procedures.change_procedurecategory",
    }


class ProcedureViewSet(viewsets.ModelViewSet):
    """AC-158. The catalogue."""

    queryset = Procedure.objects.select_related("category", "billing_service")
    serializer_class = ProcedureSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "procedures.view_procedure",
        "retrieve": "procedures.view_procedure",
        "create": "procedures.add_procedure",
        "partial_update": "procedures.change_procedure",
    }

    def get_queryset(self):
        queryset = super().get_queryset().prefetch_related("consumables__item")
        params = self.request.query_params
        if params.get("active") == "true":
            queryset = queryset.filter(is_active=True)
        if params.get("theatre") == "true":
            queryset = queryset.filter(requires_theatre=True)
        if term := params.get("q"):
            queryset = queryset.filter(name__icontains=term)
        return queryset


class TheatreViewSet(FacilityScopedMixin, viewsets.ModelViewSet):
    queryset = Theatre.objects.none()
    serializer_class = TheatreSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "procedures.view_theatre",
        "retrieve": "procedures.view_theatre",
        "create": "procedures.add_theatre",
        "partial_update": "procedures.change_theatre",
    }

    def get_queryset(self):
        return self._scope(Theatre.objects.select_related("facility", "store"))

    def facility_for_permission(self, request):
        if self.action == "create":
            return Facility.objects.filter(pk=request.data.get("facility")).first()
        return None


class ProcedureRequestViewSet(FacilityScopedMixin, viewsets.ModelViewSet):
    """AC-159 to AC-163. Every step of a procedure's life."""

    queryset = ProcedureRequest.objects.none()
    serializer_class = ProcedureRequestSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "head", "options"]
    required_permissions = {
        "list": "procedures.view_procedurerequest",
        "retrieve": "procedures.view_procedurerequest",
        "create": "procedures.request_procedure",
        "consent": "procedures.record_consent",
        "withdraw_consent": "procedures.record_consent",
        "book": "procedures.schedule_procedure",
        "perform": "procedures.perform_procedure",
        "cancel": "procedures.request_procedure",
    }

    def get_queryset(self):
        queryset = self._scope(
            ProcedureRequest.objects.select_related(
                "procedure", "patient", "facility", "requested_by", "consent",
                "performed__lead_clinician",
            ).prefetch_related(
                "bookings__theatre", "bookings__lead_surgeon",
                "performed__team__member", "performed__consumables_used__item",
                "performed__medications__medication", "performed__note__versions",
            )
        )
        params = self.request.query_params
        if params.get("status"):
            queryset = queryset.filter(status__in=params["status"].split(","))
        if params.get("patient"):
            queryset = queryset.filter(patient_id=params["patient"])
        if params.get("open") == "true":
            queryset = queryset.filter(
                status__in=[ProcedureRequest.REQUESTED, ProcedureRequest.SCHEDULED]
            )
        return queryset

    def facility_for_permission(self, request):
        if self.action == "create":
            return facility_from_request(request)
        return None

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            patient, facility = episode_owner(
                visit=data.get("visit"), admission=data.get("admission")
            )
        except ValidationError as refusal:
            return _refusal(refusal)

        try:
            record = services.request_procedure(
                procedure=data["procedure"],
                patient=patient,
                facility=facility,
                indication=data["indication"],
                urgency=data.get("urgency", ProcedureRequest.ROUTINE),
                visit=data.get("visit"), admission=data.get("admission"),
                actor=request.user,
            )
        except ValidationError as refusal:
            return _refusal(refusal)

        AuditEvent.record(
            action="procedure.requested", actor=request.user, resource=record,
            patient=record.patient, facility=record.facility,
            after={"reference": record.reference, "procedure": record.procedure.code,
                   "urgency": record.urgency},
            reason=record.indication, request=request,
        )
        return Response(self.get_serializer(record).data, status=http.HTTP_201_CREATED)

    @extend_schema(request=RecordConsentSerializer, responses={201: ConsentSerializer},
                   summary="Record the consent conversation")
    @action(detail=True, methods=["post"])
    def consent(self, request, pk=None):
        record = self.get_object()
        serializer = RecordConsentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            consent = services.record_consent(
                request=record, actor=request.user, **serializer.validated_data
            )
        except ValidationError as refusal:
            return _refusal(refusal)

        AuditEvent.record(
            action="procedure.consent_recorded", actor=request.user, resource=consent,
            patient=record.patient, facility=record.facility,
            after={"reference": record.reference, "given_by": consent.given_by,
                   "given_by_name": consent.given_by_name,
                   "interpreter_used": consent.interpreter_used},
            reason=consent.risks_discussed, request=request,
        )
        return Response(ConsentSerializer(consent).data, status=http.HTTP_201_CREATED)

    @extend_schema(request=ReasonSerializer, responses={200: ConsentSerializer},
                   summary="Record that consent was withdrawn")
    @action(detail=True, methods=["post"], url_path="withdraw-consent",
            url_name="withdraw-consent")
    def withdraw_consent(self, request, pk=None):
        record = self.get_object()
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            consent = services.withdraw_consent(
                request=record, actor=request.user,
                reason=serializer.validated_data["reason"],
            )
        except ValidationError as refusal:
            return _refusal(refusal)

        AuditEvent.record(
            action="procedure.consent_withdrawn", actor=request.user, resource=consent,
            patient=record.patient, facility=record.facility,
            after={"reference": record.reference},
            reason=consent.withdrawal_reason, request=request,
        )
        return Response(ConsentSerializer(consent).data)

    @extend_schema(request=BookTheatreSerializer,
                   responses={201: TheatreBookingSerializer},
                   summary="Hold a theatre slot")
    @action(detail=True, methods=["post"])
    def book(self, request, pk=None):
        record = self.get_object()
        serializer = BookTheatreSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        surgeon = User.objects.filter(pk=data["lead_surgeon"]).first()
        if surgeon is None:
            return Response({"lead_surgeon": ["No such user."]},
                            status=http.HTTP_400_BAD_REQUEST)
        anaesthetist = (
            User.objects.filter(pk=data["anaesthetist"]).first()
            if data["anaesthetist"] else None
        )

        try:
            booking = services.book_theatre(
                request=record, theatre=data["theatre"],
                starts_at=data["starts_at"], ends_at=data["ends_at"],
                lead_surgeon=surgeon, anaesthetist=anaesthetist, actor=request.user,
            )
        except services.TheatreTaken as clash:
            return _refusal(clash, status=http.HTTP_409_CONFLICT)
        except ValidationError as refusal:
            return _refusal(refusal)

        AuditEvent.record(
            action="theatre.booked", actor=request.user, resource=booking,
            patient=record.patient, facility=record.facility,
            after={"reference": record.reference, "theatre": booking.theatre.code,
                   "from": booking.period.lower.isoformat(),
                   "to": booking.period.upper.isoformat(),
                   "surgeon": surgeon.email},
            request=request,
        )
        return Response(TheatreBookingSerializer(booking).data,
                        status=http.HTTP_201_CREATED)

    @extend_schema(request=PerformSerializer,
                   responses={201: PerformedProcedureSerializer},
                   summary="Record that it happened, take the stock, bill it")
    @action(detail=True, methods=["post"])
    def perform(self, request, pk=None):
        record = self.get_object()
        serializer = PerformSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        lead = User.objects.filter(pk=data["lead_clinician"]).first()
        if lead is None:
            return Response({"lead_clinician": ["No such user."]},
                            status=http.HTTP_400_BAD_REQUEST)

        booking = None
        if data["booking"]:
            booking = TheatreBooking.objects.filter(
                pk=data["booking"], request=record
            ).select_related("theatre__store").first()
            if booking is None:
                return Response({"booking": ["That booking is not for this request."]},
                                status=http.HTTP_400_BAD_REQUEST)

        store = Store.objects.filter(pk=data["store"]).first() if data["store"] else None

        team, consumables, medications = [], [], []
        for entry in data["team"]:
            member = User.objects.filter(pk=entry["member"]).first()
            if member is None:
                return Response({"team": [f"No such user: {entry['member']}."]},
                                status=http.HTTP_400_BAD_REQUEST)
            team.append({"member": member, "role": entry["role"]})
        for entry in data["consumables"]:
            item = InventoryItem.objects.filter(pk=entry["item"]).first()
            if item is None:
                return Response({"consumables": [f"No such item: {entry['item']}."]},
                                status=http.HTTP_400_BAD_REQUEST)
            consumables.append({
                "item": item, "quantity": entry["quantity"],
                "store": Store.objects.filter(pk=entry["store"]).first()
                if entry["store"] else None,
            })
        for entry in data["medications"]:
            drug = Medication.objects.filter(pk=entry["medication"]).first()
            if drug is None:
                return Response(
                    {"medications": [f"No such medication: {entry['medication']}."]},
                    status=http.HTTP_400_BAD_REQUEST,
                )
            medications.append({
                "medication": drug, "dose": entry["dose"], "route": entry["route"],
                "given_by": request.user,
            })

        try:
            performed = services.perform(
                request=record, actor=request.user,
                started_at=data["started_at"], finished_at=data["finished_at"],
                lead_clinician=lead, outcome=data["outcome"], booking=booking,
                store=store, findings=data["findings"],
                procedure_performed=data["procedure_performed"],
                closure=data["closure"], blood_loss_ml=data["blood_loss_ml"],
                specimens=data["specimens"], complications=data["complications"],
                post_operative_instructions=data["post_operative_instructions"],
                team=team, consumables=consumables, medications=medications,
            )
        except ValidationError as refusal:
            return _refusal(refusal)

        AuditEvent.record(
            action="procedure.performed", actor=request.user, resource=performed,
            patient=record.patient, facility=record.facility,
            after={"reference": record.reference,
                   "procedure": record.procedure.code,
                   "outcome": performed.outcome,
                   "lead": lead.email,
                   "duration_minutes": performed.duration_minutes,
                   "team": [f"{m['member'].email} ({m['role']})" for m in team],
                   "consumables": [f"{c['quantity']} × {c['item'].code}"
                                   for c in consumables],
                   "billed": performed.is_billed},
            request=request,
        )
        return Response(PerformedProcedureSerializer(performed).data,
                        status=http.HTTP_201_CREATED)

    @extend_schema(request=ReasonSerializer, responses={200: ProcedureRequestSerializer},
                   summary="Cancel the request — a cancelled procedure never bills")
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        record = self.get_object()
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.cancel_request(
                request=record, actor=request.user,
                reason=serializer.validated_data["reason"],
            )
        except ValidationError as refusal:
            return _refusal(refusal, status=http.HTTP_409_CONFLICT)

        AuditEvent.record(
            action="procedure.cancelled", actor=request.user, resource=record,
            patient=record.patient, facility=record.facility,
            after={"reference": record.reference},
            reason=record.cancellation_reason, request=request,
        )
        return Response(self.get_serializer(record).data)


class TheatreBookingViewSet(FacilityScopedMixin, viewsets.ReadOnlyModelViewSet):
    """The operating list. Bookings are made through a procedure request."""

    queryset = TheatreBooking.objects.none()
    serializer_class = TheatreBookingSerializer
    permission_classes = [HasPermission]
    required_permissions = {
        "list": "procedures.view_theatrebooking",
        "retrieve": "procedures.view_theatrebooking",
        "cancel": "procedures.schedule_procedure",
    }

    def get_queryset(self):
        queryset = self._scope(
            TheatreBooking.objects.select_related(
                "theatre", "request__patient", "request__procedure", "lead_surgeon",
                "anaesthetist",
            ),
            field="theatre__facility_id",
        )
        params = self.request.query_params
        if params.get("theatre"):
            queryset = queryset.filter(theatre_id=params["theatre"])
        if params.get("upcoming") == "true":
            queryset = queryset.filter(
                period__endswith__gte=timezone.now(),
            ).exclude(status=TheatreBooking.CANCELLED)
        if params.get("status"):
            queryset = queryset.filter(status__in=params["status"].split(","))
        return queryset.order_by("period")

    @extend_schema(request=ReasonSerializer, responses={200: TheatreBookingSerializer},
                   summary="Give the slot back")
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        booking = self.get_object()
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.cancel_booking(
                booking=booking, actor=request.user,
                reason=serializer.validated_data["reason"],
            )
        except ValidationError as refusal:
            return _refusal(refusal, status=http.HTTP_409_CONFLICT)

        AuditEvent.record(
            action="theatre.booking_cancelled", actor=request.user, resource=booking,
            patient=booking.request.patient, facility=booking.theatre.facility,
            after={"theatre": booking.theatre.code,
                   "reference": booking.request.reference},
            reason=booking.cancellation_reason, request=request,
        )
        return Response(self.get_serializer(booking).data)


class PerformedProcedureViewSet(FacilityScopedMixin, viewsets.ReadOnlyModelViewSet):
    """Read-only. A procedure is recorded through its request, once."""

    queryset = PerformedProcedure.objects.none()
    serializer_class = PerformedProcedureSerializer
    permission_classes = [HasPermission]
    required_permissions = {
        "list": "procedures.view_performedprocedure",
        "retrieve": "procedures.view_performedprocedure",
    }

    def get_queryset(self):
        queryset = self._scope(
            PerformedProcedure.objects.select_related(
                "request__patient", "request__procedure", "lead_clinician",
            ).prefetch_related(
                "team__member", "consumables_used__item", "medications__medication",
                "note__versions__author",
            ),
            field="request__facility_id",
        )
        if patient := self.request.query_params.get("patient"):
            queryset = queryset.filter(request__patient_id=patient)
        return queryset


class OperationNoteViewSet(FacilityScopedMixin, viewsets.ReadOnlyModelViewSet):
    """AC-162. No update verb — amending appends a version."""

    queryset = OperationNote.objects.none()
    serializer_class = OperationNoteSerializer
    permission_classes = [HasPermission]
    required_permissions = {
        "list": "procedures.view_operationnote",
        "retrieve": "procedures.view_operationnote",
        "amend": "procedures.amend_operation_note",
    }

    def get_queryset(self):
        return self._scope(
            OperationNote.objects.select_related(
                "performed__request__patient", "performed__request__procedure",
            ).prefetch_related("versions__author"),
            field="performed__request__facility_id",
        )

    @extend_schema(request=AmendNoteSerializer, responses={201: OperationNoteSerializer},
                   summary="Append a version — the superseded text stays")
    @action(detail=True, methods=["post"])
    def amend(self, request, pk=None):
        note = self.get_object()
        serializer = AmendNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        reason = data.pop("reason")
        before = note.current

        try:
            version = services.amend_note(
                note=note, actor=request.user, reason=reason, **data
            )
        except ValidationError as refusal:
            return _refusal(refusal)

        AuditEvent.record(
            action="operation_note.amended", actor=request.user, resource=note,
            patient=note.performed.request.patient,
            facility=note.performed.request.facility,
            before={"version": before.version_number,
                    "findings": before.findings} if before else None,
            after={"version": version.version_number,
                   "findings": version.findings},
            reason=reason, request=request,
        )
        note.refresh_from_db()
        return Response(self.get_serializer(note).data, status=http.HTTP_201_CREATED)


class TheatreListView(FacilityScopedMixin, viewsets.ViewSet):
    """The day's operating list, in the order it runs."""

    permission_classes = [HasPermission]
    required_permissions = {"list": "procedures.view_theatrebooking"}

    @extend_schema(
        parameters=[
            OpenApiParameter("theatre", int),
            OpenApiParameter("date", str, description="YYYY-MM-DD. Defaults to today."),
        ],
        responses={200: TheatreBookingSerializer(many=True)},
        summary="One theatre's list for one day",
    )
    def list(self, request):
        permitted = set(request.user.facilities_for("procedures.view_theatrebooking"))
        theatres = Theatre.objects.filter(is_active=True)
        if None not in permitted and not request.user.is_superuser:
            theatres = theatres.filter(
                facility_id__in=[f for f in permitted if f is not None]
            )
        if request.query_params.get("theatre"):
            theatres = theatres.filter(pk=request.query_params["theatre"])

        on = timezone.localdate()
        if raw := request.query_params.get("date"):
            try:
                on = datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                return Response({"date": ["Use YYYY-MM-DD."]},
                                status=http.HTTP_400_BAD_REQUEST)

        bookings = services.theatre_list(on=on).filter(theatre__in=theatres)
        return Response(TheatreBookingSerializer(bookings, many=True).data)
