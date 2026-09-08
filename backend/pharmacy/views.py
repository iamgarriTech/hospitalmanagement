from django.core.exceptions import ValidationError
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from audit.models import AuditEvent
from billing.models import charge
from core.episodes import episode_owner, facility_from_request
from core.formatting import trim_decimal
from core.permissions import HasPermission
from patients.models import Patient

from . import safety
from .models import (
    Dispense,
    Medication,
    MedicationCategory,
    Prescription,
    PrescriptionItem,
    SafetyOverride,
    StockBatch,
    StockMovement,
    take_from_batch,
)
from .serializers import (
    DispenseRequestSerializer,
    MedicationCategorySerializer,
    MedicationSerializer,
    PrescriptionItemSerializer,
    PrescriptionSerializer,
    ScreenSerializer,
    StockBatchSerializer,
)


class MedicationCategoryViewSet(viewsets.ModelViewSet):
    queryset = MedicationCategory.objects.all()
    serializer_class = MedicationCategorySerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "pharmacy.view_medicationcategory",
        "retrieve": "pharmacy.view_medicationcategory",
        "create": "pharmacy.add_medicationcategory",
        "partial_update": "pharmacy.change_medicationcategory",
    }


class MedicationViewSet(viewsets.ModelViewSet):
    """Configuration: the hospital formulary."""

    queryset = Medication.objects.select_related("category").prefetch_related(
        "dose_ranges", "contraindications", "batches"
    )
    serializer_class = MedicationSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "pharmacy.view_medication",
        "retrieve": "pharmacy.view_medication",
        "create": "pharmacy.add_medication",
        "partial_update": "pharmacy.change_medication",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("include_inactive") != "true":
            queryset = queryset.filter(is_active=True)
        search = self.request.query_params.get("search")
        if search:
            from django.db.models import Q

            queryset = queryset.filter(
                Q(generic_name__icontains=search) | Q(brand_name__icontains=search)
            )
        return queryset


class StockBatchViewSet(viewsets.ModelViewSet):
    """Stock on hand, per batch. Quantities change through dispensing, not by editing."""

    queryset = StockBatch.objects.none()
    serializer_class = StockBatchSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "head", "options"]
    required_permissions = {
        "list": "pharmacy.view_stockbatch",
        "retrieve": "pharmacy.view_stockbatch",
        "create": "pharmacy.add_stockbatch",
    }

    def get_queryset(self):
        user = self.request.user
        required = self.required_permissions.get(self.action, "pharmacy.view_stockbatch")
        queryset = StockBatch.objects.select_related("medication", "facility")
        if not user.is_superuser:
            granted = set(user.facilities_for(required))
            if None not in granted:
                queryset = queryset.filter(
                    facility_id__in=[f for f in granted if f is not None]
                )
        params = self.request.query_params
        if params.get("medication"):
            queryset = queryset.filter(medication_id=params["medication"])
        if params.get("available") == "true":
            from django.utils import timezone

            queryset = queryset.filter(
                quantity_on_hand__gt=0, expiry_date__gte=timezone.localdate()
            )
        return queryset

    def facility_for_permission(self, request):
        if self.action == "create":
            from facilities.models import Facility

            return Facility.objects.filter(pk=request.data.get("facility")).first()
        return None

    def perform_create(self, serializer):
        """Goods received. Recorded as a movement so the balance is always explained."""
        quantity = int(self.request.data.get("quantity_on_hand") or 0)
        batch = serializer.save(quantity_on_hand=quantity)
        StockMovement.objects.create(
            batch=batch,
            kind=StockMovement.RECEIPT,
            quantity_delta=quantity,
            quantity_after=batch.quantity_on_hand,
            reason=self.request.data.get("reason", "") or "Goods received",
            recorded_by=self.request.user,
        )
        AuditEvent.record(
            action="stock.received",
            actor=self.request.user,
            resource=batch,
            facility=batch.facility,
            after={"medication": str(batch.medication), "batch": batch.batch_number,
                   "quantity": quantity, "expiry": str(batch.expiry_date)},
            request=self.request,
        )


class PrescriptionViewSet(viewsets.ModelViewSet):
    """Prescribing, with the safety screen in front of it."""

    queryset = Prescription.objects.none()
    serializer_class = PrescriptionSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "head", "options"]

    required_permissions = {
        "list": "pharmacy.view_prescription",
        "retrieve": "pharmacy.view_prescription",
        "queue": "pharmacy.view_prescription",
        "history": "pharmacy.view_prescription",
        "create": "pharmacy.add_prescription",
        "screen": "pharmacy.add_prescription",
    }

    def get_queryset(self):
        user = self.request.user
        required = self.required_permissions.get(self.action, "pharmacy.view_prescription")
        queryset = Prescription.objects.select_related(
            "patient", "facility", "prescribed_by"
        ).prefetch_related(
            "items__medication", "items__dispenses__batch__medication",
            "items__safety_overrides__overridden_by",
        )
        if not user.is_superuser:
            granted = set(user.facilities_for(required))
            if None not in granted:
                queryset = queryset.filter(
                    facility_id__in=[f for f in granted if f is not None]
                )
        params = self.request.query_params
        if params.get("patient"):
            queryset = queryset.filter(patient_id=params["patient"])
        if params.get("visit"):
            queryset = queryset.filter(visit_id=params["visit"])
        if params.get("status"):
            queryset = queryset.filter(status__in=params["status"].split(","))
        return queryset

    def facility_for_permission(self, request):
        if self.action == "create":
            return facility_from_request(request)
        return None

    @extend_schema(summary="Which safety checks are running, and which are not")
    @action(detail=False, methods=["get"], permission_classes=[],
            url_path="safety-capabilities")
    def safety_capabilities(self, request):
        """Deliberately open to any authenticated user.

        The prescribing screen must be able to state that interaction checking is not
        active (AC-36), and that statement must never be the thing a permission error
        hides.
        """
        return Response(safety.capabilities())

    @extend_schema(request=ScreenSerializer, summary="Screen a drug before prescribing")
    @action(detail=False, methods=["post"])
    def screen(self, request):
        serializer = ScreenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        patient = Patient.objects.filter(pk=data["patient"]).first()
        medication = Medication.objects.filter(pk=data["medication"]).first()
        if patient is None or medication is None:
            return Response({"detail": "Unknown patient or medication."},
                            status=http.HTTP_400_BAD_REQUEST)
        warnings = safety.screen(
            patient=patient,
            medication=medication,
            dose=data.get("dose"),
            route=data.get("route") or None,
            frequency_per_day=data.get("frequency_per_day"),
        )
        return Response({
            "warnings": [warning.as_dict() for warning in warnings],
            "capabilities": safety.capabilities(),
        })

    def create(self, request, *args, **kwargs):
        """Write a prescription, refusing to proceed past a serious warning unsigned."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        visit = data.pop("visit", None)
        admission = data.pop("admission", None)
        patient, facility = episode_owner(visit=visit, admission=admission)
        items = data.pop("items")

        acknowledged = str(request.data.get("acknowledge_warnings", "")).lower() in {
            "true", "1", "yes"
        }
        override_reason = (request.data.get("override_reason") or "").strip()

        screened = []
        blocking = []
        for entry in items:
            warnings = safety.screen(
                patient=patient,
                medication=entry["medication"],
                dose=entry.get("dose"),
                route=entry.get("route"),
                frequency_per_day=entry.get("frequency_per_day"),
            )
            screened.append((entry, warnings))
            blocking.extend(
                (entry, warning) for warning in warnings if warning.requires_reason
            )

        if blocking and not acknowledged:
            return Response(
                {
                    "detail": "Safety warnings must be reviewed before this prescription "
                              "can be written.",
                    "warnings": [
                        {"medication": str(entry["medication"]), **warning.as_dict()}
                        for entry, warning in blocking
                    ],
                    "capabilities": safety.capabilities(),
                },
                status=http.HTTP_409_CONFLICT,
            )
        if blocking and acknowledged:
            if not request.user.has_permission(
                "pharmacy.override_safety_warning", facility
            ):
                AuditEvent.record(
                    action="prescription.override_denied",
                    actor=request.user,
                    outcome=AuditEvent.DENIED,
                    patient=patient,
                    facility=facility,
                    after={"warnings": [w.kind for _, w in blocking]},
                    request=request,
                )
                raise PermissionDenied(
                    "Prescribing past a safety warning needs the "
                    "pharmacy.override_safety_warning permission."
                )
            if not override_reason:
                return Response(
                    {"override_reason": ["A reason is required to prescribe past a "
                                         "safety warning."]},
                    status=http.HTTP_400_BAD_REQUEST,
                )

        with transaction.atomic():
            prescription = Prescription.objects.create(
                visit=visit,
                admission=admission,
                encounter=data.get("encounter"),
                patient=patient,
                facility=facility,
                is_discharge_medication=data.get("is_discharge_medication", False),
                prescribed_by=request.user,
                notes=data.get("notes", ""),
            )
            for entry, warnings in screened:
                item = PrescriptionItem.objects.create(prescription=prescription, **entry)
                for warning in warnings:
                    if warning.requires_reason:
                        SafetyOverride.objects.create(
                            prescription_item=item,
                            warning_kind=warning.kind,
                            warning_detail=warning.detail[:400],
                            reason=override_reason,
                            overridden_by=request.user,
                        )

        AuditEvent.record(
            action="prescription.written",
            actor=request.user,
            resource=prescription,
            patient=prescription.patient,
            facility=prescription.facility,
            after={
                "prescription_number": prescription.prescription_number,
                "items": [
                    f"{item.medication.generic_name} {trim_decimal(item.dose)}{item.dose_unit} "
                    f"× {item.frequency_per_day}/day × {item.duration_days}d"
                    for item in prescription.items.all()
                ],
                "warnings_overridden": [w.kind for _, w in blocking],
            },
            reason=override_reason,
            request=request,
        )
        return Response(
            self.get_serializer(self.get_queryset().get(pk=prescription.pk)).data,
            status=http.HTTP_201_CREATED,
        )

    @extend_schema(summary="Pharmacy queue: prescriptions waiting to be dispensed")
    @action(detail=False, methods=["get"])
    def queue(self, request):
        waiting = self.get_queryset().filter(
            status__in=[Prescription.ACTIVE, Prescription.PARTIALLY_DISPENSED]
        ).order_by("prescribed_at")[:200]
        return Response([
            {
                "id": prescription.id,
                "prescription_number": prescription.prescription_number,
                "patient_name": prescription.patient.full_name,
                "hospital_number": prescription.patient.hospital_number,
                "prescribed_at": prescription.prescribed_at,
                "prescribed_by": prescription.prescribed_by.email,
                "status": prescription.status,
                "allergies": [
                    allergy.substance for allergy in prescription.patient.allergies.all()
                    if allergy.is_active
                ],
                "items": [
                    {
                        "item_id": item.id,
                        # The id as well as the label: the dispensing screen has to
                        # match batches to this exact presentation, and matching on
                        # a display string is how the wrong strength gets issued.
                        "medication_id": item.medication_id,
                        "medication": str(item.medication),
                        "dispensing_unit": item.medication.dispensing_unit,
                        "outstanding": item.quantity_outstanding,
                        "instructions": item.instructions,
                        "overridden_warnings": [
                            override.warning_kind
                            for override in item.safety_overrides.all()
                        ],
                    }
                    for item in prescription.items.all()
                    if item.status != PrescriptionItem.CANCELLED
                ],
            }
            for prescription in waiting
        ])

    @extend_schema(summary="Everything dispensed to a patient, most recent first")
    @action(detail=False, methods=["get"])
    def history(self, request):
        dispenses = Dispense.objects.filter(
            prescription_item__prescription__in=self.get_queryset()
        ).select_related(
            "batch__medication", "dispensed_by",
            "prescription_item__prescription__patient",
        ).order_by("-dispensed_at")[:300]
        return Response([
            {
                "dispensed_at": dispense.dispensed_at,
                "medication": str(dispense.batch.medication),
                "quantity": dispense.quantity,
                "batch_number": dispense.batch.batch_number,
                "expiry_date": dispense.batch.expiry_date,
                "dispensed_by": dispense.dispensed_by.email,
                "prescription_number":
                    dispense.prescription_item.prescription.prescription_number,
            }
            for dispense in dispenses
        ])


class PrescriptionItemViewSet(viewsets.GenericViewSet):
    """Dispensing against a prescription line."""

    queryset = PrescriptionItem.objects.none()
    serializer_class = PrescriptionItemSerializer
    permission_classes = [HasPermission]
    required_permissions = {
        "retrieve": "pharmacy.view_prescription",
        "dispense": "pharmacy.dispense_medication",
    }

    def get_queryset(self):
        user = self.request.user
        required = self.required_permissions.get(self.action, "pharmacy.view_prescription")
        queryset = PrescriptionItem.objects.select_related(
            "medication", "prescription__patient", "prescription__facility"
        ).prefetch_related("dispenses__batch__medication", "safety_overrides")
        if not user.is_superuser:
            granted = set(user.facilities_for(required))
            if None not in granted:
                queryset = queryset.filter(
                    prescription__facility_id__in=[f for f in granted if f is not None]
                )
        return queryset

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)

    @extend_schema(request=DispenseRequestSerializer,
                   responses={200: PrescriptionItemSerializer},
                   summary="Dispense from a specific batch")
    @action(detail=True, methods=["post"])
    def dispense(self, request, pk=None):
        item = self.get_object()
        serializer = DispenseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quantity = serializer.validated_data["quantity"]
        batch = StockBatch.objects.filter(
            pk=serializer.validated_data["batch"],
            facility=item.prescription.facility,
        ).select_related("medication").first()

        if batch is None:
            return Response({"batch": ["No such batch at this facility."]},
                            status=http.HTTP_400_BAD_REQUEST)
        if batch.medication_id != item.medication_id:
            return Response(
                {"batch": [f"Batch {batch.batch_number} is "
                           f"{batch.medication.generic_name}, not "
                           f"{item.medication.generic_name}."]},
                status=http.HTTP_400_BAD_REQUEST,
            )
        if batch.is_expired:
            AuditEvent.record(
                action="dispense.expired_batch_refused",
                actor=request.user,
                outcome=AuditEvent.DENIED,
                patient=item.prescription.patient,
                facility=item.prescription.facility,
                after={"batch": batch.batch_number, "expiry": str(batch.expiry_date)},
                request=request,
            )
            return Response(
                {"batch": [f"Batch {batch.batch_number} expired on "
                           f"{batch.expiry_date}."]},
                status=http.HTTP_400_BAD_REQUEST,
            )
        if item.status == PrescriptionItem.CANCELLED:
            return Response({"detail": "That prescription line was cancelled."},
                            status=http.HTTP_409_CONFLICT)
        if quantity > item.quantity_outstanding:
            return Response(
                {"quantity": [f"Only {item.quantity_outstanding} outstanding on this "
                              f"line."]},
                status=http.HTTP_409_CONFLICT,
            )

        try:
            with transaction.atomic():
                locked = PrescriptionItem.objects.select_for_update().get(pk=item.pk)
                if quantity > locked.quantity_prescribed - locked.quantity_dispensed:
                    raise ValidationError(
                        f"Only {locked.quantity_prescribed - locked.quantity_dispensed} "
                        f"outstanding on this line."
                    )
                dispense = Dispense.objects.create(
                    prescription_item=locked,
                    batch=batch,
                    quantity=quantity,
                    dispensed_by=request.user,
                    note=serializer.validated_data["note"],
                )
                take_from_batch(
                    batch=batch, quantity=quantity, actor=request.user,
                    dispense=dispense,
                    reason=f"Dispensed on "
                           f"{locked.prescription.prescription_number}",
                )
                locked.quantity_dispensed += quantity
                locked.status = (
                    PrescriptionItem.DISPENSED if locked.is_fully_dispensed
                    else PrescriptionItem.PARTIALLY_DISPENSED
                )
                locked.save(update_fields=["quantity_dispensed", "status"])
                locked.prescription.refresh_status()
        except ValidationError as error:
            return Response({"detail": error.messages[0]}, status=http.HTTP_409_CONFLICT)

        # One charge per dispense, keyed on the dispense: a partial issue today and
        # another tomorrow are two charges, but a retry of either is not.
        if batch.medication.selling_price:
            charge(
                visit=item.prescription.visit,
                service_code="",
                description=f"{batch.medication} × {quantity}",
                source_type="pharmacy.Dispense",
                source_id=dispense.pk,
                quantity=quantity,
                unit_price=batch.medication.selling_price,
                actor=request.user,
            )

        AuditEvent.record(
            action="medication.dispensed",
            actor=request.user,
            resource=item.prescription,
            patient=item.prescription.patient,
            facility=item.prescription.facility,
            after={
                "medication": str(batch.medication),
                "quantity": quantity,
                "batch": batch.batch_number,
                "expiry": str(batch.expiry_date),
                "stock_after": StockBatch.objects.get(pk=batch.pk).quantity_on_hand,
            },
            request=request,
        )
        return Response(self.get_serializer(self.get_queryset().get(pk=item.pk)).data)
