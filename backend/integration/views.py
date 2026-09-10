"""The external API facade. AC-179, AC-180.

Read-only, versioned in the path, and — the part that matters — running
through exactly the same permission and facility scoping as the internal API.
Not a parallel implementation of it: `FacilityScopedMixin` and
`HasPermission` are the same classes the internal viewsets use, so a facade
endpoint cannot drift from the rule the internal one enforces.

That is deliberate. An integration surface with its own copy of the scoping
logic is one that will eventually disagree with the internal one, and the
version that leaks is always the one nobody was looking at.
"""
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.response import Response

from clinical.models import Diagnosis, Encounter, VitalSigns
from core.permissions import FacilityScopedMixin, HasPermission
from laboratory.models import LabResult
from patients.models import Patient
from pharmacy.models import PrescriptionItem

from . import fhir

VERSION = "v1"

# What the facade is and is not. Served at the root of the facade so an
# integrator reads it before writing a client, and worded the way AC-189 asks
# for: never let somebody infer a capability that is not there.
CAPABILITY_NOTE = (
    "This is a FHIR-shaped read-only facade, not a conformant FHIR server. "
    "Resources follow R4 field names closely enough to map without a "
    "translation table. It does not implement CapabilityStatement, _include, "
    "chained search, transactions, subscriptions or the operation framework, "
    "and nothing here accepts a write. Codes are returned with the system and "
    "version they were recorded under and are never re-mapped."
)


class _Facade(FacilityScopedMixin, viewsets.ViewSet):
    """Shared plumbing: paging, and the scoping that must not be forgotten."""

    permission_classes = [HasPermission]
    MAX_PAGE = 200

    def _page(self, queryset):
        try:
            limit = min(int(self.request.query_params.get("_count", 50)),
                        self.MAX_PAGE)
            offset = int(self.request.query_params.get("_offset", 0))
        except ValueError:
            return None, Response(
                {"detail": "_count and _offset must be whole numbers."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        total = queryset.count()
        return (queryset[offset:offset + limit], total), None


class PatientFacade(_Facade):
    """FHIR Patient."""

    required_permissions = {
        "list": "integration.use_external_api",
        "retrieve": "integration.use_external_api",
    }

    def _queryset(self):
        # The same scoping the internal patient endpoints use. A patient at a
        # facility the caller may not see does not exist as far as this
        # facade is concerned. AC-180.
        queryset = self._scope(Patient.objects.select_related("facility"))
        params = self.request.query_params
        if identifier := params.get("identifier"):
            queryset = queryset.filter(hospital_number=identifier)
        if since := params.get("_lastUpdated"):
            queryset = queryset.filter(updated_at__gte=since)
        return queryset.order_by("pk")

    @extend_schema(
        parameters=[
            OpenApiParameter("identifier", str, description="Hospital number"),
            OpenApiParameter("_count", int), OpenApiParameter("_offset", int),
        ],
        responses={200: OpenApiTypes.OBJECT}, summary="Search Patient",
    )
    def list(self, request):
        page, refusal = self._page(self._queryset())
        if refusal:
            return refusal
        records, total = page
        return Response(fhir.bundle(
            "Patient", [fhir.patient(record) for record in records], total=total
        ))

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, summary="Read Patient")
    def retrieve(self, request, pk=None):
        record = self._queryset().filter(pk=pk).first()
        if record is None:
            return Response({"resourceType": "OperationOutcome",
                             "issue": [{"severity": "error", "code": "not-found"}]},
                            status=http.HTTP_404_NOT_FOUND)
        return Response(fhir.patient(record))


class EncounterFacade(_Facade):
    """FHIR Encounter, and the Conditions recorded on it."""

    required_permissions = {
        "list": "integration.use_external_api",
        "retrieve": "integration.use_external_api",
        "condition": "integration.use_external_api",
    }

    def _queryset(self):
        queryset = self._scope(
            Encounter.objects.select_related("patient", "clinician", "facility")
        )
        params = self.request.query_params
        if patient := params.get("patient"):
            queryset = queryset.filter(patient_id=patient)
        if since := params.get("date"):
            queryset = queryset.filter(started_at__gte=since)
        return queryset.order_by("pk")

    @extend_schema(
        parameters=[OpenApiParameter("patient", int), OpenApiParameter("date", str),
                    OpenApiParameter("_count", int), OpenApiParameter("_offset", int)],
        responses={200: OpenApiTypes.OBJECT}, summary="Search Encounter",
    )
    def list(self, request):
        page, refusal = self._page(self._queryset())
        if refusal:
            return refusal
        records, total = page
        return Response(fhir.bundle(
            "Encounter", [fhir.encounter(record) for record in records], total=total
        ))

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, summary="Read Encounter")
    def retrieve(self, request, pk=None):
        record = self._queryset().filter(pk=pk).first()
        if record is None:
            return Response({"resourceType": "OperationOutcome",
                             "issue": [{"severity": "error", "code": "not-found"}]},
                            status=http.HTTP_404_NOT_FOUND)
        return Response(fhir.encounter(record))


class ConditionFacade(_Facade):
    """FHIR Condition — diagnoses, from current versions only.

    A superseded version's diagnosis is not a current condition. Emitting both
    would have an integrator recording a patient as having two diagnoses where
    the hospital records one amendment.
    """

    required_permissions = {"list": "integration.use_external_api"}

    @extend_schema(
        parameters=[OpenApiParameter("patient", int),
                    OpenApiParameter("_count", int), OpenApiParameter("_offset", int)],
        responses={200: OpenApiTypes.OBJECT}, summary="Search Condition",
    )
    def list(self, request):
        queryset = self._scope(
            Diagnosis.objects.filter(version__is_current=True).select_related(
                "version__encounter__patient"
            ),
            field="version__encounter__facility_id",
        ).order_by("pk")
        if patient := request.query_params.get("patient"):
            queryset = queryset.filter(version__encounter__patient_id=patient)
        page, refusal = self._page(queryset)
        if refusal:
            return refusal
        records, total = page
        return Response(fhir.bundle(
            "Condition", [fhir.condition(record) for record in records], total=total
        ))


class ObservationFacade(_Facade):
    """FHIR Observation — vital signs and verified laboratory results.

    **Only verified results.** An unverified number is a reading nobody has
    signed, and an external system that acts on one automatically is the worst
    place for it to appear. Same reasoning as AC-185, applied outward.
    """

    required_permissions = {"list": "integration.use_external_api"}

    @extend_schema(
        parameters=[
            OpenApiParameter("patient", int),
            OpenApiParameter("category", str,
                             description="vital-signs or laboratory"),
            OpenApiParameter("_count", int), OpenApiParameter("_offset", int),
        ],
        responses={200: OpenApiTypes.OBJECT}, summary="Search Observation",
    )
    def list(self, request):
        params = request.query_params
        category = params.get("category")
        patient = params.get("patient")
        try:
            limit = min(int(params.get("_count", 50)), self.MAX_PAGE)
        except ValueError:
            return Response({"detail": "_count must be a whole number."},
                            status=http.HTTP_400_BAD_REQUEST)

        resources = []
        if category in (None, "vital-signs"):
            vitals = self._scope(
                VitalSigns.objects.select_related("patient")
            ).order_by("-recorded_at")
            if patient:
                vitals = vitals.filter(patient_id=patient)
            for record in vitals[:limit]:
                resources.extend(fhir.observations_from_vitals(record))

        if category in (None, "laboratory"):
            results = self._scope(
                LabResult.objects.filter(
                    is_current=True,
                    order_item__verified_at__isnull=False,
                ).select_related(
                    "order_item__order", "order_item__test", "parameter",
                ),
                field="order_item__order__facility_id",
            ).order_by("-entered_at")
            if patient:
                results = results.filter(order_item__order__patient_id=patient)
            for result in results[:limit]:
                resources.append(fhir.observation_from_result(result))

        return Response(fhir.bundle("Observation", resources[:limit]))


class MedicationRequestFacade(_Facade):
    """FHIR MedicationRequest — prescribed medication."""

    required_permissions = {"list": "integration.use_external_api"}

    @extend_schema(
        parameters=[OpenApiParameter("patient", int),
                    OpenApiParameter("_count", int), OpenApiParameter("_offset", int)],
        responses={200: OpenApiTypes.OBJECT}, summary="Search MedicationRequest",
    )
    def list(self, request):
        queryset = self._scope(
            PrescriptionItem.objects.select_related(
                "prescription__patient", "prescription__prescribed_by", "medication"
            ),
            field="prescription__facility_id",
        ).order_by("pk")
        if patient := request.query_params.get("patient"):
            queryset = queryset.filter(prescription__patient_id=patient)
        page, refusal = self._page(queryset)
        if refusal:
            return refusal
        records, total = page
        return Response(fhir.bundle(
            "MedicationRequest",
            [fhir.medication_request(record) for record in records], total=total,
        ))


class FacadeRootView(viewsets.ViewSet):
    """What this facade is, and what it is not. AC-179, AC-189.

    Deliberately reachable without the API permission: an integrator needs to
    read the limitations before they have credentials, and the honest place
    for that is here rather than in a wiki nobody finds.
    """

    permission_classes = []
    authentication_classes = []

    @extend_schema(responses={200: OpenApiTypes.OBJECT},
                   summary="What this facade supports, and what it does not")
    def list(self, request):
        return Response({
            "name": "VitaCore external API",
            "version": VERSION,
            "fhirVersion": "4.0.1 (shaped, not conformant)",
            "mode": "read-only",
            "note": CAPABILITY_NOTE,
            "resources": [
                {"type": "Patient", "search": ["identifier", "_lastUpdated"]},
                {"type": "Encounter", "search": ["patient", "date"]},
                {"type": "Condition", "search": ["patient"]},
                {"type": "Observation", "search": ["patient", "category"]},
                {"type": "MedicationRequest", "search": ["patient"]},
            ],
            "notSupported": [
                "Any write operation", "CapabilityStatement", "_include and _revinclude",
                "Chained and reverse-chained search", "Transactions and batches",
                "Subscriptions", "The operation framework ($-operations)",
                "Unverified laboratory results — these are never exposed",
            ],
            "paging": {"parameters": ["_count", "_offset"], "maxCount": 200},
            "authentication": (
                "The same session as the rest of the API, plus the "
                "integration.use_external_api permission. Facility scoping is "
                "identical to the internal API: a record at a facility the "
                "caller may not see returns not-found."
            ),
            "generatedAt": timezone.now().isoformat(),
        })
