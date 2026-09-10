from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Prefetch
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from audit.models import AuditEvent
from billing.models import Service, charge
from core.episodes import episode_owner, facility_from_request
from core.permissions import FacilityScopedMixin, HasPermission

from . import referrals
from .models import (
    Diagnosis,
    Encounter,
    EncounterVersion,
    Referral,
    VitalSigns,
)
from .serializers import (
    AmendSerializer,
    EncounterSerializer,
    EncounterVersionSerializer,
    MarkErroneousSerializer,
    ReferralOutcomeSerializer,
    ReferralReasonSerializer,
    ReferralSerializer,
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


class ReferralViewSet(FacilityScopedMixin, viewsets.ModelViewSet):
    """AC-164 to AC-166.

    `status` is read-only and moved by actions, because each transition is a
    different act by a different person: the referrer sends, the receiving
    clinician accepts, and whoever saw the patient records the outcome. A
    writable status would let the sender mark their own referral as seen.
    """

    queryset = Referral.objects.none()
    serializer_class = ReferralSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "head", "options"]
    required_permissions = {
        "list": "clinical.view_referral",
        "retrieve": "clinical.view_referral",
        "create": "clinical.make_referral",
        "send": "clinical.make_referral",
        "accept": "clinical.record_referral_outcome",
        "outcome": "clinical.record_referral_outcome",
        "cancel": "clinical.make_referral",
        "letter": "clinical.view_referral",
    }

    def get_queryset(self):
        queryset = self._scope(
            Referral.objects.select_related(
                "patient", "facility", "referred_by", "to_department", "to_clinician",
                "outcome_recorded_by", "visit__clinic__department",
            ).prefetch_related("prints__printed_by")
        )
        params = self.request.query_params
        if params.get("status"):
            queryset = queryset.filter(status__in=params["status"].split(","))
        if params.get("patient"):
            queryset = queryset.filter(patient_id=params["patient"])
        if params.get("open") == "true":
            queryset = queryset.filter(
                status__in=[Referral.DRAFT, Referral.SENT, Referral.ACCEPTED]
            )
        if params.get("to_me") == "true":
            # AC-164 — the receiving clinician's list. Referrals addressed to
            # this clinician by name, plus ones sent to a department with
            # nobody named: those are the pool anyone in the department picks
            # up, and a referral sitting in a queue nobody watches is the
            # failure this list exists to prevent.
            #
            # Departments are not scoped per user — role assignments are per
            # facility — so the department pool is everything in scope. That is
            # the honest behaviour until staff carry a department.
            queryset = queryset.filter(
                models.Q(to_clinician=self.request.user)
                | models.Q(to_clinician__isnull=True, to_department__isnull=False)
            ).exclude(status=Referral.DRAFT)
        if params.get("department"):
            queryset = queryset.filter(to_department_id=params["department"])
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
            return Response({"detail": refusal.messages},
                            status=http.HTTP_400_BAD_REQUEST)

        try:
            record = referrals.refer(
                patient=patient, facility=facility, kind=data["kind"],
                reason=data["reason"], clinical_question=data["clinical_question"],
                actor=request.user,
                to_department=data.get("to_department"),
                to_clinician=data.get("to_clinician"),
                to_organisation=data.get("to_organisation", ""),
                to_external_clinician=data.get("to_external_clinician", ""),
                to_address=data.get("to_address", ""),
                what_was_sent=data.get("what_was_sent", ""),
                urgency=data.get("urgency", Referral.ROUTINE),
                encounter=data.get("encounter"), visit=data.get("visit"),
                admission=data.get("admission"),
            )
        except ValidationError as refusal:
            return Response({"detail": refusal.messages},
                            status=http.HTTP_400_BAD_REQUEST)

        AuditEvent.record(
            action="referral.created", actor=request.user, resource=record,
            patient=record.patient, facility=record.facility,
            after={"reference": record.reference, "kind": record.kind,
                   "to": record.destination, "urgency": record.urgency},
            reason=record.reason, request=request,
        )
        return Response(self.get_serializer(record).data, status=http.HTTP_201_CREATED)

    def _act(self, request, fn, action_name, status_on_error=http.HTTP_409_CONFLICT,
             **kwargs):
        record = self.get_object()
        try:
            fn(record, actor=request.user, **kwargs)
        except ValidationError as refusal:
            return Response({"detail": refusal.messages}, status=status_on_error)
        AuditEvent.record(
            action=action_name, actor=request.user, resource=record,
            patient=record.patient, facility=record.facility,
            after={"reference": record.reference, "status": record.status,
                   "to": record.destination},
            reason=record.outcome or record.reason, request=request,
        )
        return Response(self.get_serializer(record).data)

    @extend_schema(request=None, responses={200: ReferralSerializer},
                   summary="Send it — it then appears on the receiving list")
    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        return self._act(request, referrals.send, "referral.sent")

    @extend_schema(request=None, responses={200: ReferralSerializer},
                   summary="Accept a referral sent to you")
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        return self._act(request, referrals.accept, "referral.accepted")

    @extend_schema(request=ReferralOutcomeSerializer,
                   responses={200: ReferralSerializer},
                   summary="Record what came back")
    @action(detail=True, methods=["post"])
    def outcome(self, request, pk=None):
        serializer = ReferralOutcomeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._act(
            request, referrals.record_outcome, "referral.outcome_recorded",
            status_on_error=http.HTTP_400_BAD_REQUEST,
            outcome=serializer.validated_data["outcome"],
            declined=serializer.validated_data["declined"],
        )

    @extend_schema(request=ReferralReasonSerializer,
                   responses={200: ReferralSerializer}, summary="Cancel it")
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        serializer = ReferralReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._act(
            request, referrals.cancel, "referral.cancelled",
            reason=serializer.validated_data["reason"],
        )

    @extend_schema(
        responses={200: OpenApiTypes.OBJECT},
        summary="The referral letter, assembled from the record",
    )
    @action(detail=True, methods=["get"])
    def letter(self, request, pk=None):
        """AC-166.

        Assembled on every read, so a reprint is identical by construction
        rather than by intention — there is no stored copy to drift. Every
        read is logged, which makes "reprints are logged" true of the reprints
        and not only of the first print.
        """
        record = self.get_object()
        is_reprint = referrals.record_print(record, actor=request.user)
        AuditEvent.record(
            action="referral.letter_printed", actor=request.user, resource=record,
            patient=record.patient, facility=record.facility,
            after={"reference": record.reference, "is_reprint": is_reprint,
                   "print_count": record.print_count},
            request=request,
        )
        return Response({
            "letter": referrals.letter(record),
            "is_reprint": is_reprint,
            "print_count": record.print_count,
        })
