"""Admission request, admit, transfer, plan, discharge.

Every action here delegates to `inpatient.services` — the rules about what
carries forward from a request, which nights are charged and what must be
settled before a patient can leave are the substance of the phase, and a view is
the wrong place to be able to read them.
"""
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from audit.models import AuditEvent
from core.permissions import FacilityScopedMixin, HasPermission
from facilities.models import Facility
from patients.models import Patient

from ..models import (
    Admission,
    AdmissionRequest,
    BedOccupancy,
    BedTaken,
    BedTransfer,
)
from ..serializers import (
    AdmissionRequestSerializer,
    AdmissionSerializer,
    AdmitSerializer,
    BedTransferSerializer,
    DeclineSerializer,
    DischargeSerializer,
    PlanDischargeSerializer,
    TransferSerializer,
)
from ..services import (
    admit,
    charge_bed_nights,
    discharge,
    discharge_summary,
    outstanding_before_discharge,
    plan_discharge,
    transfer,
)


def _validation_response(error):
    """A ValidationError from the service layer, as the API shape.

    Service errors carry a list of problems (the discharge gate returns one per
    unsettled invoice), so the message list is preserved rather than flattened
    into one string a cashier cannot act on.
    """
    detail = error.message_dict if hasattr(error, "message_dict") else error.messages
    # A bed taken by somebody else is a conflict the ward resolves by choosing
    # another bed. Answering 400 would tell them they sent something wrong.
    status = (http.HTTP_409_CONFLICT if isinstance(error, BedTaken)
              else http.HTTP_400_BAD_REQUEST)
    return Response({"detail": detail}, status=status)


class AdmissionRequestViewSet(FacilityScopedMixin, viewsets.ModelViewSet):
    """A clinician asking for a bed, before anyone knows which bed.

    Separate from admitting on purpose: a doctor must be able to request a bed
    without knowing whether one is free, which is how a hospital works.
    """

    queryset = AdmissionRequest.objects.none()
    serializer_class = AdmissionRequestSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "head", "options"]

    required_permissions = {
        "list": "inpatient.view_admissionrequest",
        "retrieve": "inpatient.view_admissionrequest",
        "pending": "inpatient.view_admissionrequest",
        "create": "inpatient.add_admissionrequest",
        "decline": "inpatient.decide_admissionrequest",
        "cancel": "inpatient.decide_admissionrequest",
    }

    def get_queryset(self):
        queryset = self._scope(
            AdmissionRequest.objects.select_related(
                "patient", "facility", "ward", "responsible_consultant",
                "requested_by", "decided_by", "admission",
            ).prefetch_related("patient__allergies")
        )
        params = self.request.query_params
        if params.get("ward"):
            queryset = queryset.filter(ward_id=params["ward"])
        if params.get("status"):
            queryset = queryset.filter(status__in=params["status"].split(","))
        if params.get("patient"):
            queryset = queryset.filter(patient_id=params["patient"])
        return queryset

    def facility_for_permission(self, request):
        if self.action == "create":
            facility_id = request.data.get("facility")
            return Facility.objects.filter(pk=facility_id).first() if facility_id else None
        return None

    def create(self, request, *args, **kwargs):
        """AC-61. Records who asked, why, the working diagnosis and the
        consultant who will carry the patient — and allocates no bed."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        admission_request = serializer.save(requested_by=request.user)

        AuditEvent.record(
            action="admission.requested",
            actor=request.user,
            resource=admission_request,
            patient=admission_request.patient,
            facility=admission_request.facility,
            after={
                "ward": admission_request.ward.name,
                "priority": admission_request.priority,
                "working_diagnosis": admission_request.working_diagnosis,
                "consultant": admission_request.responsible_consultant.email,
            },
            reason=admission_request.reason,
            request=request,
        )
        return Response(
            self.get_serializer(admission_request).data, status=http.HTTP_201_CREATED
        )

    @extend_schema(
        parameters=[OpenApiParameter("ward", int)],
        responses={200: AdmissionRequestSerializer(many=True)},
        summary="Requests still waiting for a bed",
    )
    @action(detail=False, methods=["get"])
    def pending(self, request):
        """AC-61. Urgent first, then longest waiting — the order a bed manager
        works in."""
        queryset = self.get_queryset().filter(status=AdmissionRequest.PENDING)
        return Response(self.get_serializer(queryset, many=True).data)

    @extend_schema(request=DeclineSerializer, responses={200: AdmissionRequestSerializer})
    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        """A declined request states why. The constraint requires it."""
        admission_request = self.get_object()
        serializer = DeclineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if admission_request.status != AdmissionRequest.PENDING:
            return Response(
                {"detail": f"That request is already "
                           f"{admission_request.get_status_display().lower()}."},
                status=http.HTTP_409_CONFLICT,
            )
        admission_request.status = AdmissionRequest.DECLINED
        admission_request.decline_reason = serializer.validated_data["reason"]
        admission_request.decided_by = request.user
        admission_request.decided_at = timezone.now()
        admission_request.save(
            update_fields=["status", "decline_reason", "decided_by", "decided_at"]
        )
        AuditEvent.record(
            action="admission.request_declined",
            actor=request.user,
            resource=admission_request,
            patient=admission_request.patient,
            facility=admission_request.facility,
            after={"status": admission_request.status},
            reason=admission_request.decline_reason,
            request=request,
        )
        return Response(self.get_serializer(admission_request).data)


class AdmissionViewSet(FacilityScopedMixin, viewsets.ReadOnlyModelViewSet):
    """The stay.

    Read-only as a resource: an admission is opened by admitting and closed by
    discharging, both of which have rules. There is no PATCH that could set
    `discharged_at` and skip them.
    """

    queryset = Admission.objects.none()
    serializer_class = AdmissionSerializer
    permission_classes = [HasPermission]

    required_permissions = {
        "list": "inpatient.view_admission",
        "retrieve": "inpatient.view_admission",
        "summary": "inpatient.view_admission",
        "billing": "billing.view_invoice",
        "admit": "inpatient.admit_patient",
        "transfer": "inpatient.transfer_patient",
        "plan_discharge": "inpatient.plan_discharge",
        "discharge": "inpatient.discharge_patient",
    }

    def get_queryset(self):
        queryset = self._scope(
            Admission.objects.select_related(
                "patient", "facility", "responsible_consultant", "admitted_by",
                "discharged_by", "request",
            ).prefetch_related(
                "patient__allergies",
                Prefetch(
                    "occupancies",
                    queryset=BedOccupancy.objects.select_related(
                        "bed__room__ward", "patient", "admission",
                        "allocated_by", "ended_by",
                    ).order_by("period"),
                ),
                Prefetch(
                    "transfers",
                    queryset=BedTransfer.objects.select_related(
                        "from_occupancy__bed__room__ward",
                        "to_occupancy__bed__room__ward",
                        "authorised_by",
                    ),
                ),
            )
        )
        params = self.request.query_params
        if params.get("patient"):
            queryset = queryset.filter(patient_id=params["patient"])
        if params.get("status"):
            queryset = queryset.filter(status__in=params["status"].split(","))
        if params.get("ward"):
            queryset = queryset.filter(
                occupancies__bed__room__ward_id=params["ward"],
                occupancies__period__endswith__isnull=True,
            )
        if params.get("open") == "true":
            queryset = queryset.exclude(status=Admission.DISCHARGED)
        if params.get("discharge_planned") == "true":
            # AC-99: the ward's discharge list.
            queryset = queryset.filter(status=Admission.DISCHARGE_PLANNED)
        return queryset

    def facility_for_permission(self, request):
        if self.action == "admit":
            facility_id = request.data.get("facility")
            if facility_id:
                return Facility.objects.filter(pk=facility_id).first()
            request_id = request.data.get("request")
            if request_id:
                admission_request = AdmissionRequest.objects.filter(
                    pk=request_id
                ).select_related("facility").first()
                return admission_request.facility if admission_request else None
        return None

    # --- admitting ------------------------------------------------------------

    @extend_schema(
        request=AdmitSerializer,
        responses={201: AdmissionSerializer},
        summary="Admit a patient into a bed",
    )
    @action(detail=False, methods=["post"])
    def admit(self, request):
        """AC-62 to AC-66.

        The bed allocation is what can fail here, and it fails in the database:
        the exclusion constraint on occupancy is why two nurses pressing Admit
        on the same bed at the same instant produce one occupancy rather than
        two patients in one bed.
        """
        serializer = AdmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        kwargs = {"bed": data["bed"], "actor": request.user}
        if data.get("request") is not None:
            kwargs["request"] = data["request"]
        else:
            patient = Patient.objects.filter(pk=data.get("patient")).first()
            facility = Facility.objects.filter(pk=data.get("facility")).first()
            if patient is None or facility is None:
                return Response(
                    {"detail": "That patient or facility does not exist."},
                    status=http.HTTP_400_BAD_REQUEST,
                )
            consultant = None
            if data.get("responsible_consultant"):
                from accounts.models import User

                consultant = User.objects.filter(
                    pk=data["responsible_consultant"]
                ).first()
            kwargs.update({
                "patient": patient, "facility": facility, "consultant": consultant,
                "reason": data.get("reason", ""), "diagnosis": data.get("diagnosis", ""),
            })
            if data.get("visit"):
                from visits.models import Visit

                kwargs["visit"] = Visit.objects.filter(pk=data["visit"]).first()

        try:
            admission, _ = admit(**kwargs)
        except ValidationError as error:
            AuditEvent.record(
                action="admission.refused",
                actor=request.user,
                outcome=AuditEvent.DENIED,
                resource_type="Admission",
                facility=data["bed"].room.ward.facility,
                after={"bed": str(data["bed"]), "detail": error.messages},
                request=request,
            )
            return _validation_response(error)

        # AC-65: an admitted patient is no longer waiting in the outpatient
        # queue, so the queue reflects it rather than showing them twice.
        if admission.visit_id is not None:
            from visits.models import Visit

            visit = admission.visit
            if visit.closed_at is None and visit.can_move_to(Visit.ADMITTED):
                visit.move_to(
                    Visit.ADMITTED, actor=request.user,
                    note=f"Admitted as {admission.admission_number}",
                )

        return Response(
            self.get_serializer(self.get_queryset().get(pk=admission.pk)).data,
            status=http.HTTP_201_CREATED,
        )

    # --- moving ---------------------------------------------------------------

    @extend_schema(
        request=TransferSerializer,
        responses={200: BedTransferSerializer},
        summary="Move an inpatient to another bed",
    )
    @action(detail=True, methods=["post"])
    def transfer(self, request, pk=None):
        """AC-74 to AC-76. One transaction, so the patient is never in two beds
        and never in none."""
        admission = self.get_object()
        serializer = TransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            moved = transfer(
                admission=admission,
                to_bed=serializer.validated_data["to_bed"],
                reason=serializer.validated_data["reason"],
                actor=request.user,
            )
        except ValidationError as error:
            AuditEvent.record(
                action="admission.transfer_refused",
                actor=request.user,
                outcome=AuditEvent.DENIED,
                resource=admission,
                patient=admission.patient,
                facility=admission.facility,
                after={
                    "to_bed": str(serializer.validated_data["to_bed"]),
                    "detail": error.messages,
                },
                request=request,
            )
            return _validation_response(error)

        AuditEvent.record(
            action="admission.transferred",
            actor=request.user,
            resource=admission,
            patient=admission.patient,
            facility=admission.facility,
            before={"bed": str(moved.from_occupancy.bed),
                    "ward": moved.from_occupancy.bed.room.ward.name},
            after={"bed": str(moved.to_occupancy.bed),
                   "ward": moved.to_occupancy.bed.room.ward.name,
                   "changed_ward": moved.changed_ward},
            reason=moved.reason,
            request=request,
        )
        return Response(BedTransferSerializer(moved).data)

    # --- leaving --------------------------------------------------------------

    @extend_schema(
        request=PlanDischargeSerializer,
        responses={200: AdmissionSerializer},
        summary="Record a discharge plan",
    )
    @action(detail=True, methods=["post"], url_path="plan-discharge")
    def plan_discharge(self, request, pk=None):
        """AC-99. Recorded before the discharge, because the plan is what the
        ward, pharmacy and cash desk work towards."""
        admission = self.get_object()
        serializer = PlanDischargeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            plan_discharge(
                admission=admission,
                actor=request.user,
                expected_date=serializer.validated_data.get("expected_date"),
                destination=serializer.validated_data.get("destination", ""),
                notes=serializer.validated_data.get("notes", ""),
            )
        except ValidationError as error:
            return _validation_response(error)
        return Response(self.get_serializer(self.get_queryset().get(pk=pk)).data)

    @extend_schema(
        responses={200: None},
        summary="What still has to be settled before this patient can leave",
    )
    @action(detail=True, methods=["get"])
    def billing(self, request, pk=None):
        """AC-100's readable half.

        The bed nights are charged as part of the check, not after it — a check
        that ran first and charged afterwards would pass, and then bill a
        patient who had already gone home.
        """
        admission = self.get_object()
        nights = charge_bed_nights(admission=admission, actor=request.user)
        from billing.models import Invoice

        invoices = Invoice.objects.filter(admission=admission).prefetch_related("items")
        return Response({
            "admission": admission.pk,
            "nights_occupied": admission.length_of_stay_nights,
            "nights_charged_now": [
                {"ward": ward, "date": night} for ward, night in nights
            ],
            "invoices": [
                {
                    "id": invoice.pk,
                    "invoice_number": invoice.invoice_number,
                    "status": invoice.status,
                    "total": str(invoice.total),
                    "balance": str(invoice.balance),
                    "items": invoice.items.count(),
                }
                for invoice in invoices
            ],
            "outstanding": outstanding_before_discharge(admission),
            "can_override": request.user.has_permission(
                "inpatient.override_discharge_billing", admission.facility
            ),
        })

    @extend_schema(
        request=DischargeSerializer,
        responses={200: AdmissionSerializer},
        summary="Complete a discharge",
    )
    @action(detail=True, methods=["post"])
    def discharge(self, request, pk=None):
        """AC-100 (the gate), AC-101, AC-105.

        Refuses while the stay is unbilled or unpaid. An override needs the
        override permission as well as a reason — a required text box that
        anyone can fill in is not a control.
        """
        admission = self.get_object()
        serializer = DischargeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        override = data.get("override_reason", "").strip()

        if override and not request.user.has_permission(
            "inpatient.override_discharge_billing", admission.facility
        ):
            AuditEvent.record(
                action="admission.discharge_override_denied",
                actor=request.user,
                outcome=AuditEvent.DENIED,
                resource=admission,
                patient=admission.patient,
                facility=admission.facility,
                after={"outstanding": outstanding_before_discharge(admission)},
                reason=override,
                request=request,
            )
            return Response(
                {"detail": "Discharging with an unsettled bill needs the billing "
                           "override permission."},
                status=http.HTTP_403_FORBIDDEN,
            )

        try:
            discharge(
                admission=admission,
                actor=request.user,
                diagnosis=data["diagnosis"],
                destination=data["destination"],
                instructions=data.get("instructions", ""),
                override_reason=override,
            )
        except ValidationError as error:
            AuditEvent.record(
                action="admission.discharge_refused",
                actor=request.user,
                outcome=AuditEvent.DENIED,
                resource=admission,
                patient=admission.patient,
                facility=admission.facility,
                after={"detail": error.messages},
                request=request,
            )
            return Response(
                {"detail": error.messages, "outstanding": error.messages},
                status=http.HTTP_409_CONFLICT,
            )

        return Response(self.get_serializer(self.get_queryset().get(pk=pk)).data)

    @extend_schema(responses={200: None}, summary="The discharge summary")
    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        """AC-102, AC-104.

        Assembled from the record on every read, so a reprint is identical by
        construction rather than by a stored copy that could drift from the
        notes it came from. The read is logged, which is what makes AC-104's
        "reprints logged" true of reprints and not only of the first print.
        """
        admission = self.get_object()
        AuditEvent.record(
            action="admission.discharge_summary_printed",
            actor=request.user,
            resource=admission,
            patient=admission.patient,
            facility=admission.facility,
            after={"admission_number": admission.admission_number},
            request=request,
        )
        return Response(discharge_summary(admission))
