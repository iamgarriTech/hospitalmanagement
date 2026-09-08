from rest_framework import serializers

from ..models import MedicationAdministration, ScheduledDose


class ScheduledDoseSerializer(serializers.ModelSerializer):
    medication = serializers.CharField(
        source="prescription_item.medication.__str__", read_only=True
    )
    medication_id = serializers.IntegerField(
        source="prescription_item.medication_id", read_only=True
    )
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    status = serializers.SerializerMethodField()
    minutes_overdue = serializers.IntegerField(read_only=True)
    outcome = serializers.SerializerMethodField()

    class Meta:
        model = ScheduledDose
        fields = [
            "id", "prescription_item", "admission", "patient", "patient_name",
            "medication", "medication_id", "due_at", "sequence", "dose", "dose_unit",
            "route", "cancelled_at", "cancelled_reason", "status", "minutes_overdue",
            "outcome",
        ]
        read_only_fields = fields

    def get_status(self, dose) -> str:
        return dose.status()

    def get_outcome(self, dose) -> dict | None:
        outcome = dose.outcome
        if outcome is None:
            return None
        return {
            "id": outcome.pk,
            "state": outcome.state,
            "state_label": outcome.get_state_display(),
            "by": outcome.administered_by.full_name,
            "at": outcome.administered_at,
            "recorded_at": outcome.recorded_at,
            "dose_given": str(outcome.dose_given) if outcome.dose_given else None,
            "minutes_late": outcome.minutes_late,
            "reason": outcome.reason,
        }


class MedicationAdministrationSerializer(serializers.ModelSerializer):
    state_label = serializers.CharField(source="get_state_display", read_only=True)
    administered_by_name = serializers.CharField(
        source="administered_by.full_name", read_only=True
    )
    batch_number = serializers.CharField(
        source="batch.batch_number", read_only=True, default=None
    )
    medication = serializers.CharField(
        source="scheduled_dose.prescription_item.medication.__str__", read_only=True
    )
    due_at = serializers.DateTimeField(source="scheduled_dose.due_at", read_only=True)
    minutes_late = serializers.IntegerField(read_only=True)

    class Meta:
        model = MedicationAdministration
        fields = [
            "id", "scheduled_dose", "admission", "patient", "medication", "due_at",
            "state", "state_label", "administered_by", "administered_by_name",
            "recorded_at", "administered_at", "dose_given", "dose_unit", "batch",
            "batch_number", "reason", "note", "override_reason", "minutes_late",
        ]
        read_only_fields = fields


class RecordAdministrationSerializer(serializers.Serializer):
    """What happened to one due dose.

    `batch` is only required for the states where stock actually left the
    trolley — a missed dose came from nowhere, and demanding a batch for it
    would make the honest answer harder to record than the flattering one.
    """

    state = serializers.ChoiceField(
        choices=[state for state, _ in MedicationAdministration.STATE_CHOICES]
    )
    batch = serializers.IntegerField(required=False, allow_null=True)
    dose_given = serializers.DecimalField(
        max_digits=10, decimal_places=3, required=False, allow_null=True
    )
    administered_at = serializers.DateTimeField(required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    note = serializers.CharField(required=False, allow_blank=True, default="")
    override_reason = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        state = attrs["state"]
        if state in MedicationAdministration.REQUIRE_REASON and not (
            attrs.get("reason") or ""
        ).strip():
            raise serializers.ValidationError(
                {"reason": f"A dose recorded as {state} has to say why. A gap with no "
                           f"explanation is not a record."}
            )
        if state in MedicationAdministration.CONSUMES_STOCK and not attrs.get("batch"):
            raise serializers.ValidationError(
                {"batch": "Say which batch the dose came from."}
            )
        return attrs


class DiscontinueSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)
