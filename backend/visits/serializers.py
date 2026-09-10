from rest_framework import serializers

from patients.serializers import PatientSummarySerializer

from .models import (
    EmergencyEpisode,
    TriageAssessment,
    TriageLevel,
    TriageScale,
    Visit,
    VisitStateChange,
)


class VisitStateChangeSerializer(serializers.ModelSerializer):
    changed_by = serializers.CharField(source="changed_by.email", read_only=True, default=None)

    class Meta:
        model = VisitStateChange
        fields = ["id", "from_status", "to_status", "changed_by", "changed_at", "note"]


class VisitSerializer(serializers.ModelSerializer):
    patient_detail = PatientSummarySerializer(source="patient", read_only=True)
    state_changes = VisitStateChangeSerializer(many=True, read_only=True)
    waiting_minutes = serializers.IntegerField(read_only=True)
    allowed_transitions = serializers.SerializerMethodField()

    class Meta:
        model = Visit
        fields = [
            "id", "visit_number", "patient", "patient_detail", "facility", "clinic",
            "visit_type", "status", "reason", "scheduled_for", "arrived_at", "called_at",
            "consultation_started_at", "closed_at", "waiting_minutes",
            "allowed_transitions", "state_changes", "created_at",
        ]
        read_only_fields = [
            "id", "visit_number", "status", "called_at", "consultation_started_at",
            "closed_at", "created_at",
        ]

    def get_allowed_transitions(self, visit) -> list[str]:
        """The UI shows only the moves that are actually legal from here."""
        return sorted(visit.TRANSITIONS.get(visit.status, set()))


class QueueRowSerializer(serializers.ModelSerializer):
    """A queue row: who, where, how long they have been waiting."""

    patient = PatientSummarySerializer(read_only=True)
    waiting_minutes = serializers.IntegerField(read_only=True)
    clinic_name = serializers.CharField(source="clinic.name", read_only=True, default=None)
    allergies = serializers.SerializerMethodField()
    allowed_transitions = serializers.SerializerMethodField()

    class Meta:
        model = Visit
        fields = [
            "id", "visit_number", "patient", "status", "visit_type", "clinic_name",
            "arrived_at", "waiting_minutes", "reason", "allergies",
            "allowed_transitions",
        ]

    def get_allergies(self, visit) -> list[str]:
        # Surfaced on the queue itself: staff should not have to open a chart to learn
        # that the next patient is allergic to something.
        return [
            allergy.substance
            for allergy in visit.patient.allergies.all()
            if allergy.is_active
        ]

    def get_allowed_transitions(self, visit) -> list[str]:
        """So the board can offer only legal moves.

        Sent from here rather than reproduced in the client: a second copy of the
        state machine is a second thing to keep correct, and the one in the
        browser would be the one that drifts.
        """
        return sorted(visit.TRANSITIONS.get(visit.status, set()))


class MoveSerializer(serializers.Serializer):
    to = serializers.ChoiceField(choices=[status for status, _ in Visit.STATUS_CHOICES])
    note = serializers.CharField(required=False, allow_blank=True, default="")


class TriageLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = TriageLevel
        fields = ["id", "scale", "rank", "name", "colour", "target_minutes",
                  "description"]
        read_only_fields = ["id"]


class TriageScaleSerializer(serializers.ModelSerializer):
    levels = TriageLevelSerializer(many=True, read_only=True)
    facility_name = serializers.CharField(source="facility.name", read_only=True)

    class Meta:
        model = TriageScale
        fields = ["id", "facility", "facility_name", "name", "is_active", "levels"]
        read_only_fields = ["id", "levels"]


class TriageAssessmentSerializer(serializers.ModelSerializer):
    level_name = serializers.CharField(source="level.name", read_only=True)
    level_rank = serializers.IntegerField(source="level.rank", read_only=True)
    level_colour = serializers.CharField(source="level.colour", read_only=True)
    target_minutes = serializers.IntegerField(
        source="level.target_minutes", read_only=True
    )
    assessed_by_name = serializers.CharField(
        source="assessed_by.full_name", read_only=True
    )

    class Meta:
        model = TriageAssessment
        fields = ["id", "episode", "level", "level_name", "level_rank",
                  "level_colour", "target_minutes", "sequence", "complaint",
                  "observations", "reason_for_retriage", "assessed_by",
                  "assessed_by_name", "assessed_at"]
        read_only_fields = fields


class EmergencyEpisodeSerializer(serializers.ModelSerializer):
    patient = serializers.IntegerField(source="visit.patient_id", read_only=True)
    patient_name = serializers.CharField(
        source="visit.patient.full_name", read_only=True
    )
    hospital_number = serializers.CharField(
        source="visit.patient.hospital_number", read_only=True
    )
    is_unidentified = serializers.BooleanField(
        source="visit.patient.is_unidentified", read_only=True
    )
    facility = serializers.IntegerField(source="visit.facility_id", read_only=True)
    arrived_at = serializers.DateTimeField(source="visit.arrived_at", read_only=True)
    visit_status = serializers.CharField(source="visit.status", read_only=True)
    arrival_mode_display = serializers.CharField(
        source="get_arrival_mode_display", read_only=True
    )
    outcome_display = serializers.CharField(
        source="get_outcome_display", read_only=True, default=""
    )
    outcome_recorded_by_email = serializers.CharField(
        source="outcome_recorded_by.email", read_only=True, default=None
    )
    triage_assessments = TriageAssessmentSerializer(many=True, read_only=True)
    current_triage = serializers.SerializerMethodField()
    waiting_minutes = serializers.SerializerMethodField()
    is_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = EmergencyEpisode
        fields = ["id", "visit", "patient", "patient_name", "hospital_number",
                  "is_unidentified", "facility", "arrived_at", "visit_status",
                  "arrival_mode", "arrival_mode_display", "presenting_complaint",
                  "brought_in_by", "circumstances", "outcome", "outcome_display",
                  "outcome_at", "outcome_note", "outcome_recorded_by",
                  "outcome_recorded_by_email", "opened_at", "triage_assessments",
                  "current_triage", "waiting_minutes", "is_open"]
        read_only_fields = fields

    def get_current_triage(self, episode):
        current = episode.current_triage()
        return TriageAssessmentSerializer(current).data if current else None

    def get_waiting_minutes(self, episode) -> int:
        return episode.waiting_minutes()


class RegisterArrivalSerializer(serializers.Serializer):
    """AC-167. Deliberately short — a nurse fills this in beside a trolley."""

    presenting_complaint = serializers.CharField(max_length=255)
    patient = serializers.IntegerField(required=False, allow_null=True, default=None)
    unidentified = serializers.BooleanField(default=False)
    sex = serializers.ChoiceField(
        choices=[("male", "Male"), ("female", "Female"), ("other", "Other"),
                 ("unknown", "Unknown")],
        default="unknown",
    )
    estimated_age_years = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=0, max_value=130
    )
    arrival_mode = serializers.ChoiceField(
        choices=EmergencyEpisode.ARRIVAL_CHOICES, default=EmergencyEpisode.WALK_IN
    )
    brought_in_by = serializers.CharField(max_length=200, required=False,
                                          allow_blank=True, default="")
    circumstances = serializers.CharField(required=False, allow_blank=True, default="")
    facility = serializers.IntegerField()


class TriageSerializer(serializers.Serializer):
    level = serializers.IntegerField()
    complaint = serializers.CharField(max_length=255, required=False,
                                      allow_blank=True, default="")
    observations = serializers.CharField(required=False, allow_blank=True, default="")
    reason_for_retriage = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )


class CloseEpisodeSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=EmergencyEpisode.OUTCOME_CHOICES)
    note = serializers.CharField(required=False, allow_blank=True, default="")


class EmergencyQueueRowSerializer(serializers.Serializer):
    episode = EmergencyEpisodeSerializer()
    rank = serializers.IntegerField()
    level = TriageLevelSerializer(allow_null=True)
    waited = serializers.IntegerField()
    breaching = serializers.BooleanField()
