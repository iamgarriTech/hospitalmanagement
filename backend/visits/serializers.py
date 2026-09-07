from rest_framework import serializers

from patients.serializers import PatientSummarySerializer

from .models import Visit, VisitStateChange


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

    class Meta:
        model = Visit
        fields = [
            "id", "visit_number", "patient", "status", "visit_type", "clinic_name",
            "arrived_at", "waiting_minutes", "reason", "allergies",
        ]

    def get_allergies(self, visit) -> list[str]:
        # Surfaced on the queue itself: staff should not have to open a chart to learn
        # that the next patient is allergic to something.
        return [
            allergy.substance
            for allergy in visit.patient.allergies.all()
            if allergy.is_active
        ]


class MoveSerializer(serializers.Serializer):
    to = serializers.ChoiceField(choices=[status for status, _ in Visit.STATUS_CHOICES])
    note = serializers.CharField(required=False, allow_blank=True, default="")
