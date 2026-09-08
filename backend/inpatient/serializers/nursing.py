from rest_framework import serializers

from clinical.serializers import VitalSignsSerializer

from ..models import Escalation, FluidBalanceEntry, NursingAssessment, NursingNote


class NursingAssessmentSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    recorded_by_name = serializers.CharField(source="recorded_by.full_name", read_only=True)
    shift_display = serializers.CharField(source="get_shift_display", read_only=True)
    consciousness_display = serializers.CharField(
        source="get_consciousness_display", read_only=True
    )
    mobility_display = serializers.CharField(source="get_mobility_display", read_only=True)
    observations_detail = VitalSignsSerializer(source="observations", read_only=True)

    class Meta:
        model = NursingAssessment
        fields = [
            "id", "admission", "patient", "patient_name", "shift", "shift_display",
            "observations", "observations_detail", "consciousness",
            "consciousness_display", "mobility", "mobility_display", "falls_risk",
            "pressure_area_concern", "eating_and_drinking", "continence", "summary",
            "recorded_by", "recorded_by_name", "recorded_at",
        ]
        read_only_fields = ["id", "patient", "recorded_by", "recorded_at"]

    def validate(self, attrs):
        observations = attrs.get("observations")
        admission = attrs.get("admission")
        if observations is not None and admission is not None:
            if observations.admission_id not in (None, admission.pk):
                raise serializers.ValidationError(
                    {"observations": "Those observations belong to a different stay."}
                )
        return attrs


class NursingNoteSerializer(serializers.ModelSerializer):
    # Declared without the implicit uniqueness validator so the refusal below
    # reads like a sentence. DRF's default — "nursing note with this supersedes
    # already exists" — tells a nurse nothing about what to do instead.
    supersedes = serializers.PrimaryKeyRelatedField(
        queryset=NursingNote.objects.all(), required=False, allow_null=True,
        validators=[],
    )
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    author_name = serializers.CharField(source="author.full_name", read_only=True)
    shift_display = serializers.CharField(source="get_shift_display", read_only=True)
    is_superseded = serializers.BooleanField(read_only=True)
    corrected_by = serializers.SerializerMethodField()

    class Meta:
        model = NursingNote
        fields = [
            "id", "admission", "patient", "patient_name", "shift", "shift_display",
            "note", "supersedes", "correction_reason", "is_superseded", "corrected_by",
            "author", "author_name", "recorded_at",
        ]
        read_only_fields = ["id", "patient", "author", "recorded_at"]

    def get_corrected_by(self, note) -> int | None:
        """The note that corrects this one, if any.

        Read from the reverse relation rather than a stored back-link: writing a
        `superseded_by` column would mean touching a note after the fact, which
        is the one thing this model does not do.
        """
        correction = getattr(note, "correction", None)
        return correction.pk if correction is not None else None

    def validate(self, attrs):
        supersedes = attrs.get("supersedes")
        if supersedes is not None:
            if not (attrs.get("correction_reason") or "").strip():
                raise serializers.ValidationError(
                    {"correction_reason": "Say why the earlier note needed correcting."}
                )
            if hasattr(supersedes, "correction"):
                raise serializers.ValidationError(
                    {"supersedes": "That note has already been corrected. Correct the "
                                   "correction, so the chain stays readable."}
                )
            admission = attrs.get("admission")
            if admission is not None and supersedes.admission_id != admission.pk:
                raise serializers.ValidationError(
                    {"supersedes": "A correction has to belong to the same admission."}
                )
        return attrs


class FluidBalanceEntrySerializer(serializers.ModelSerializer):
    # The check constraint refuses zero; saying so here means the caller gets a
    # 400 with a reason rather than a 500 from the database.
    volume_ml = serializers.IntegerField(min_value=1, max_value=20_000)
    direction_display = serializers.CharField(source="get_direction_display", read_only=True)
    route_display = serializers.CharField(source="get_route_display", read_only=True)
    recorded_by_name = serializers.CharField(source="recorded_by.full_name", read_only=True)

    class Meta:
        model = FluidBalanceEntry
        fields = [
            "id", "admission", "patient", "direction", "direction_display", "route",
            "route_display", "volume_ml", "note", "recorded_by", "recorded_by_name",
            "recorded_at",
        ]
        read_only_fields = ["id", "patient", "recorded_by", "recorded_at"]

    def validate(self, attrs):
        direction = attrs.get("direction")
        route = attrs.get("route")
        intake_routes = {"oral", "iv", "ng", "other_in"}
        if direction == FluidBalanceEntry.INTAKE and route not in intake_routes:
            raise serializers.ValidationError(
                {"route": f"{route!r} is an output route. An intake row with an output "
                          f"route still adds up, which is the worst kind of wrong."}
            )
        if direction == FluidBalanceEntry.OUTPUT and route in intake_routes:
            raise serializers.ValidationError(
                {"route": f"{route!r} is an intake route."}
            )
        return attrs


class EscalationSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    measurement_display = serializers.SerializerMethodField()
    direction_display = serializers.CharField(source="get_direction_display", read_only=True)
    raised_by_name = serializers.CharField(source="raised_by.full_name", read_only=True)
    escalated_to_name = serializers.CharField(
        source="escalated_to.full_name", read_only=True, default=None
    )
    acknowledged_by_name = serializers.CharField(
        source="acknowledged_by.full_name", read_only=True, default=None
    )
    is_outstanding = serializers.BooleanField(read_only=True)
    minutes_waiting = serializers.IntegerField(read_only=True)
    summary = serializers.CharField(read_only=True)

    class Meta:
        model = Escalation
        fields = [
            "id", "admission", "patient", "patient_name", "observations",
            "measurement", "measurement_display", "value", "direction",
            "direction_display", "breached_bound", "instruction", "summary",
            "raised_at", "raised_by", "raised_by_name", "escalated_to",
            "escalated_to_name", "escalated_at", "acknowledged_by",
            "acknowledged_by_name", "acknowledged_at", "action_taken",
            "is_outstanding", "minutes_waiting",
        ]
        read_only_fields = fields

    def get_measurement_display(self, escalation) -> str:
        return escalation.get_measurement_display()


class NotifySerializer(serializers.Serializer):
    """Who was told about an escalation."""

    escalated_to = serializers.IntegerField()
    note = serializers.CharField(required=False, allow_blank=True, default="")


class AcknowledgeEscalationSerializer(serializers.Serializer):
    action_taken = serializers.CharField()
