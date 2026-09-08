from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from audit.models import AuditEvent
from billing.models import Service, charge
from core.episodes import episode_owner, facility_from_request
from core.permissions import HasPermission
from visits.models import Visit

from .models import Diagnosis, Encounter, EncounterVersion, VitalSigns
from .serializers import (
    AmendSerializer,
    EncounterSerializer,
    EncounterVersionSerializer,
    MarkErroneousSerializer,
    VitalSignsSerializer,
)


class EncounterViewSet(viewsets.ModelViewSet):
    """Consultation records and their version history."""

    queryset = Encounter.objects.none()
    serializer_class = EncounterSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]

    required_permissions = {
        "list": "clinical.view_encounter",
        "retrieve": "clinical.view_encounter",
        "versions": "clinical.view_encounter",
        "create": "clinical.add_encounter",
        "partial_update": "clinical.change_encounter",
        "finalise": "clinical.finalise_encounter",
        "amend": "clinical.amend_encounter",
    }

    def get_queryset(self):
        user = self.request.user
        required = self.required_permissions.get(self.action, "clinical.view_encounter")
        # The version's author is read for every version, so it is joined
        # inside the prefetch. `versions__diagnoses` alone leaves authored_by
        # unfetched, which is one query per version — invisible on one record
        # and 50 queries on a list.
        queryset = Encounter.objects.select_related(
            "patient", "clinician", "facility"
        ).prefetch_related(
            Prefetch(
                "versions",
                queryset=EncounterVersion.objects.select_related(
                    "authored_by"
                ).prefetch_related("diagnoses"),
            )
        )
        if not user.is_superuser:
            granted = set(user.facilities_for(required))
            if None not in granted:
                queryset = queryset.filter(
                    facility_id__in=[fid for fid in granted if fid is not None]
                )
        params = self.request.query_params
        if params.get("patient"):
            queryset = queryset.filter(patient_id=params["patient"])
        if params.get("visit"):
            queryset = queryset.filter(visit_id=params["visit"])
        if params.get("admission"):
            queryset = queryset.filter(admission_id=params["admission"])
        return queryset

    def facility_for_permission(self, request):
        if self.action == "create":
            return facility_from_request(request)
        return None

    def create(self, request, *args, **kwargs):
        """Open a consultation or a ward review.

        Patient and facility come from the episode, not the caller — a client
        that could name them could file a record against the wrong patient.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        visit = data.pop("visit", None)
        admission = data.pop("admission", None)
        patient, facility = episode_owner(visit=visit, admission=admission)
        diagnoses = data.pop("diagnoses", [])
        narrative = {
            field: data.pop(field, "") for field in EncounterVersion.NARRATIVE
        }

        encounter = Encounter.objects.create(
            visit=visit,
            admission=admission,
            patient=patient,
            facility=facility,
            clinician=request.user,
            encounter_type=data.get("encounter_type", Encounter.CONSULTATION),
            started_at=data.get("started_at") or timezone.now(),
        )
        version = EncounterVersion.objects.create(
            encounter=encounter, version_number=1, authored_by=request.user,
            is_current=True, **narrative,
        )
        for entry in diagnoses:
            Diagnosis.objects.create(version=version, **entry)

        AuditEvent.record(
            action="encounter.opened",
            actor=request.user,
            resource=encounter,
            patient=encounter.patient,
            facility=encounter.facility,
            after={
                "encounter_type": encounter.encounter_type,
                # One or the other. A ward review has no visit number.
                "visit": visit.visit_number if visit else None,
                "admission": admission.admission_number if admission else None,
            },
            request=request,
        )
        return Response(
            self.get_serializer(encounter).data, status=http.HTTP_201_CREATED
        )

    def partial_update(self, request, *args, **kwargs):
        """Edit a draft in place.

        Drafts do not accumulate a version per keystroke; the first version becomes
        immutable when the record is finalised.
        """
        encounter = self.get_object()
        if encounter.status != Encounter.DRAFT:
            return Response(
                {"detail": "This record is finalised. Use amend, which records a reason."},
                status=http.HTTP_409_CONFLICT,
            )
        version = encounter.current_version
        serializer = self.get_serializer(encounter, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("visit", None)
        diagnoses = data.pop("diagnoses", None)

        for field in EncounterVersion.NARRATIVE:
            if field in data:
                setattr(version, field, data.pop(field))
        version.save()

        if diagnoses is not None:
            version.diagnoses.all().delete()
            for entry in diagnoses:
                Diagnosis.objects.create(version=version, **entry)

        AuditEvent.record(
            action="encounter.draft_updated",
            actor=request.user,
            resource=encounter,
            patient=encounter.patient,
            facility=encounter.facility,
            request=request,
        )
        return Response(self.get_serializer(encounter).data)

    @extend_schema(request=None, responses={200: EncounterSerializer},
                   summary="Finalise the record")
    @action(detail=True, methods=["post"])
    def finalise(self, request, pk=None):
        encounter = self.get_object()
        try:
            encounter.finalise(actor=request.user)
        except ValidationError as error:
            return Response({"detail": error.messages[0]}, status=http.HTTP_409_CONFLICT)
        # The consultation fee falls due when the record is finalised, not when the
        # patient walks in, so an abandoned draft is never billed.
        consultation = Service.objects.filter(code="CONSULT", is_active=True).first()
        if consultation and consultation.price_at(encounter.facility) is not None:
            charge(
                # Both are passed; `open_invoice_for` prefers the admission
                # where there is one, so a ward review bills to the stay and a
                # clinic consultation to the attendance that started it.
                visit=encounter.visit,
                admission=encounter.admission,
                service_code="CONSULT",
                description=f"{encounter.get_encounter_type_display()} — "
                            f"{encounter.clinician.full_name}",
                source_type="clinical.Encounter",
                source_id=encounter.pk,
                actor=request.user,
            )

        AuditEvent.record(
            action="encounter.finalised",
            actor=request.user,
            resource=encounter,
            patient=encounter.patient,
            facility=encounter.facility,
            after={"version": encounter.current_version.version_number},
            request=request,
        )
        return Response(self.get_serializer(self.get_queryset().get(pk=encounter.pk)).data)

    @extend_schema(request=AmendSerializer, responses={200: EncounterSerializer},
                   summary="Amend a finalised record (reason required)")
    @action(detail=True, methods=["post"])
    def amend(self, request, pk=None):
        encounter = self.get_object()
        serializer = AmendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        reason = data.pop("reason")
        diagnoses = data.pop("diagnoses", None)

        previous = encounter.current_version
        before = {field: getattr(previous, field) for field in EncounterVersion.NARRATIVE
                  if field in data}
        try:
            version = encounter.amend(
                actor=request.user, reason=reason, changes=data, diagnoses=diagnoses
            )
        except ValidationError as error:
            return Response({"detail": error.messages[0]}, status=http.HTTP_409_CONFLICT)

        AuditEvent.record(
            action="encounter.amended",
            actor=request.user,
            resource=encounter,
            patient=encounter.patient,
            facility=encounter.facility,
            before=before,
            after={
                "version": version.version_number,
                **{field: getattr(version, field) for field in before},
            },
            reason=reason,
            request=request,
        )
        # Re-read: get_object() prefetched the versions, so the cached relation would
        # report the pre-amendment count.
        return Response(self.get_serializer(self.get_queryset().get(pk=encounter.pk)).data)

    @extend_schema(responses={200: EncounterVersionSerializer(many=True)},
                   summary="Every version of this record, oldest first")
    @action(detail=True, methods=["get"])
    def versions(self, request, pk=None):
        encounter = self.get_object()
        versions = encounter.versions.order_by("version_number").prefetch_related("diagnoses")
        return Response(EncounterVersionSerializer(versions, many=True).data)


class VitalSignsViewSet(viewsets.ModelViewSet):
    """Observations, and their trend over time."""

    queryset = VitalSigns.objects.none()
    serializer_class = VitalSignsSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "head", "options"]

    required_permissions = {
        "list": "clinical.view_vitalsigns",
        "retrieve": "clinical.view_vitalsigns",
        "trend": "clinical.view_vitalsigns",
        "create": "clinical.add_vitalsigns",
        "mark_erroneous": "clinical.change_vitalsigns",
    }

    def get_queryset(self):
        user = self.request.user
        required = self.required_permissions.get(self.action, "clinical.view_vitalsigns")
        queryset = VitalSigns.objects.select_related("patient", "recorded_by")
        if not user.is_superuser:
            granted = set(user.facilities_for(required))
            if None not in granted:
                queryset = queryset.filter(
                    facility_id__in=[fid for fid in granted if fid is not None]
                )
        params = self.request.query_params
        if params.get("patient"):
            queryset = queryset.filter(patient_id=params["patient"])
        if params.get("visit"):
            queryset = queryset.filter(visit_id=params["visit"])
        if params.get("admission"):
            queryset = queryset.filter(admission_id=params["admission"])
        if params.get("include_erroneous") != "true":
            queryset = queryset.filter(is_erroneous=False)
        return queryset

    def facility_for_permission(self, request):
        if self.action == "create":
            # A ward observation has no visit — an inpatient on day nine is not
            # in that morning's outpatient queue.
            return facility_from_request(request)
        return None

    def create(self, request, *args, **kwargs):
        """Record observations, and escalate them if the ward says so.

        The escalation check runs here rather than on a schedule: a
        deterioration only a nightly job notices has been missed for a night.
        The escalations raised come back in the response so the nurse sees them
        at the bedside — an alert nobody sees is not an alert.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vitals = serializer.save(recorded_by=request.user)

        AuditEvent.record(
            action="vitals.recorded",
            actor=request.user,
            resource=vitals,
            patient=vitals.patient,
            facility=vitals.facility,
            after={
                "temperature_c": str(vitals.temperature_c) if vitals.temperature_c else None,
                "blood_pressure": vitals.blood_pressure,
                "pulse_bpm": vitals.pulse_bpm,
                "oxygen_saturation": vitals.oxygen_saturation,
                "bmi": vitals.bmi,
                "admission": vitals.admission_id,
            },
            request=request,
        )

        escalations = []
        if vitals.admission_id is not None:
            from inpatient.serializers import EscalationSerializer
            from inpatient.services import record_observation_escalations

            raised = record_observation_escalations(
                observations=vitals, admission=vitals.admission, actor=request.user
            )
            escalations = EscalationSerializer(raised, many=True).data

        data = self.get_serializer(vitals).data
        data["escalations"] = escalations
        return Response(data, status=http.HTTP_201_CREATED)

    @extend_schema(
        parameters=[OpenApiParameter("patient", int, required=True)],
        summary="Vital sign series for charting",
    )
    @action(detail=False, methods=["get"])
    def trend(self, request):
        """A series per measurement, oldest first, for plotting over time."""
        readings = self.get_queryset().order_by("recorded_at")
        measurements = [
            "temperature_c", "systolic_bp", "diastolic_bp", "pulse_bpm",
            "respiratory_rate", "oxygen_saturation", "weight_kg", "blood_glucose_mmol",
            "pain_score",
        ]
        series = {name: [] for name in measurements}
        series["bmi"] = []
        for reading in readings:
            stamp = reading.recorded_at.isoformat()
            for name in measurements:
                value = getattr(reading, name)
                if value is not None:
                    series[name].append({"at": stamp, "value": float(value)})
            if reading.bmi is not None:
                series["bmi"].append({"at": stamp, "value": reading.bmi})
        return Response({name: points for name, points in series.items() if points})

    @extend_schema(request=MarkErroneousSerializer, responses={200: VitalSignsSerializer},
                   summary="Mark a reading as recorded in error (it is kept)")
    @action(detail=True, methods=["post"], url_path="mark-erroneous")
    def mark_erroneous(self, request, pk=None):
        vitals = self.get_object()
        serializer = MarkErroneousSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vitals.is_erroneous = True
        vitals.error_reason = serializer.validated_data["reason"]
        vitals.save(update_fields=["is_erroneous", "error_reason"])
        AuditEvent.record(
            action="vitals.marked_erroneous",
            actor=request.user,
            resource=vitals,
            patient=vitals.patient,
            facility=vitals.facility,
            reason=vitals.error_reason,
            request=request,
        )
        return Response(self.get_serializer(vitals).data)
