from rest_framework import serializers

from .models import (
    LabOrder,
    LabOrderItem,
    LabResult,
    LabTest,
    LabTestCategory,
    LabTestParameter,
    ReferenceRange,
    Specimen,
)


class ReferenceRangeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReferenceRange
        fields = ["id", "sex", "min_age_years", "max_age_years", "low", "high",
                  "critical_low", "critical_high", "note"]
        read_only_fields = ["id"]


class LabTestParameterSerializer(serializers.ModelSerializer):
    reference_ranges = ReferenceRangeSerializer(many=True, required=False)

    class Meta:
        model = LabTestParameter
        fields = ["id", "name", "unit", "value_type", "choices_csv", "decimal_places",
                  "display_order", "code_system", "code", "code_display", "code_version",
                  "reference_ranges"]
        read_only_fields = ["id"]


class LabTestSerializer(serializers.ModelSerializer):
    parameters = LabTestParameterSerializer(many=True, required=False)
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = LabTest
        fields = ["id", "category", "category_name", "name", "short_code",
                  "specimen_type", "specimen_requirements", "turnaround_hours",
                  "is_active", "is_panel", "panel_members", "parameters",
                  "code_system", "code", "code_display", "code_version"]
        read_only_fields = ["id"]

    def create(self, validated_data):
        parameters = validated_data.pop("parameters", [])
        members = validated_data.pop("panel_members", [])
        test = LabTest.objects.create(**validated_data)
        test.panel_members.set(members)
        for entry in parameters:
            ranges = entry.pop("reference_ranges", [])
            parameter = LabTestParameter.objects.create(test=test, **entry)
            for reference in ranges:
                ReferenceRange.objects.create(parameter=parameter, **reference)
        return test


class LabTestCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = LabTestCategory
        fields = ["id", "name", "display_order"]
        read_only_fields = ["id"]


class SpecimenSerializer(serializers.ModelSerializer):
    collected_by_email = serializers.CharField(source="collected_by.email", read_only=True)

    class Meta:
        model = Specimen
        fields = ["id", "specimen_id", "specimen_type", "collected_by_email",
                  "collected_at", "condition", "note"]
        read_only_fields = ["id", "specimen_id", "collected_by_email"]


class LabResultSerializer(serializers.ModelSerializer):
    parameter_name = serializers.CharField(source="parameter.name", read_only=True)
    display_value = serializers.CharField(read_only=True)
    flag_label = serializers.CharField(read_only=True)
    reference_text = serializers.CharField(read_only=True)
    is_abnormal = serializers.BooleanField(read_only=True)
    is_critical = serializers.BooleanField(read_only=True)
    entered_by_email = serializers.CharField(source="entered_by.email", read_only=True)
    acknowledgements = serializers.SerializerMethodField()

    class Meta:
        model = LabResult
        fields = [
            "id", "parameter", "parameter_name", "value_numeric", "value_text",
            "display_value", "unit", "flag", "flag_label", "is_abnormal", "is_critical",
            "range_low", "range_high", "reference_text", "version", "is_current",
            "amends", "amendment_reason", "entered_by_email", "entered_at", "comment",
            "acknowledgements",
        ]
        read_only_fields = fields

    def get_acknowledgements(self, result) -> list[dict]:
        return [
            {
                "by": acknowledgement.acknowledged_by.email,
                "at": acknowledgement.acknowledged_at.isoformat(),
                "action_taken": acknowledgement.action_taken,
            }
            for acknowledgement in result.acknowledgements.all()
        ]


class LabOrderItemSerializer(serializers.ModelSerializer):
    test_name = serializers.CharField(source="test.name", read_only=True)
    test_code = serializers.CharField(source="test.short_code", read_only=True)
    specimen = SpecimenSerializer(read_only=True)
    results = serializers.SerializerMethodField()
    superseded_results = serializers.SerializerMethodField()
    verified_by_email = serializers.CharField(
        source="verified_by.email", read_only=True, default=None
    )
    allowed_transitions = serializers.SerializerMethodField()

    class Meta:
        model = LabOrderItem
        fields = ["id", "test", "test_name", "test_code", "status", "specimen",
                  "results", "superseded_results", "verified_by_email", "verified_at",
                  "laboratory_comment", "cancelled_reason", "allowed_transitions"]
        read_only_fields = fields

    def get_results(self, item) -> list[dict]:
        current = [result for result in item.results.all() if result.is_current]
        return LabResultSerializer(
            sorted(current, key=lambda r: r.parameter.display_order), many=True
        ).data

    def get_superseded_results(self, item) -> list[dict]:
        """Amended values stay visible; a report that hides them is not a record."""
        old = [result for result in item.results.all() if not result.is_current]
        return LabResultSerializer(old, many=True).data

    def get_allowed_transitions(self, item) -> list[str]:
        return sorted(item.TRANSITIONS.get(item.status, set()))


class LabOrderSerializer(serializers.ModelSerializer):
    items = LabOrderItemSerializer(many=True, read_only=True)
    tests = serializers.PrimaryKeyRelatedField(
        queryset=LabTest.objects.filter(is_active=True), many=True, write_only=True
    )
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    hospital_number = serializers.CharField(
        source="patient.hospital_number", read_only=True
    )
    ordered_by_email = serializers.CharField(source="ordered_by.email", read_only=True)

    class Meta:
        model = LabOrder
        fields = ["id", "order_number", "visit", "admission", "patient",
                  "patient_name", "hospital_number", "facility", "ordered_by",
                  "ordered_by_email", "ordered_at", "priority", "clinical_details",
                  "items", "tests"]
        read_only_fields = ["id", "order_number", "patient", "facility", "ordered_by",
                            "ordered_at"]

    def validate(self, attrs):
        """One episode or the other, on create.

        A record filed against neither belongs to no episode of care and would
        appear on nobody's list. Only on create, though: an update never resends
        the episode — it is already set and read-only — and requiring it here
        made every edit to a draft fail.
        """
        if self.instance is None and (
            attrs.get("visit") is None and attrs.get("admission") is None
        ):
            raise serializers.ValidationError(
                "This belongs to an attendance or to an admission. Give one."
            )
        return attrs


class CollectSerializer(serializers.Serializer):
    condition = serializers.ChoiceField(
        choices=[value for value, _ in Specimen.CONDITION_CHOICES],
        default=Specimen.ACCEPTABLE,
    )
    note = serializers.CharField(required=False, allow_blank=True, default="")


class ResultEntrySerializer(serializers.Serializer):
    parameter = serializers.IntegerField()
    value_numeric = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    value_text = serializers.CharField(required=False, allow_blank=True, default="")
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class EnterResultsSerializer(serializers.Serializer):
    entries = ResultEntrySerializer(many=True)


class VerifySerializer(serializers.Serializer):
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class AmendResultSerializer(serializers.Serializer):
    reason = serializers.CharField()
    value_numeric = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    value_text = serializers.CharField(required=False, allow_blank=True)
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class AcknowledgeSerializer(serializers.Serializer):
    action_taken = serializers.CharField()
