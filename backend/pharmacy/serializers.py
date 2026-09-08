from rest_framework import serializers

from .models import (
    ContraindicationRule,
    Dispense,
    DoseRange,
    Medication,
    MedicationCategory,
    Prescription,
    PrescriptionItem,
    StockBatch,
)


class DoseRangeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DoseRange
        fields = ["id", "route", "min_age_years", "max_age_years", "min_single_dose",
                  "max_single_dose", "dose_unit", "max_daily_dose"]
        read_only_fields = ["id"]


class ContraindicationRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContraindicationRule
        fields = ["id", "medication", "condition_keyword", "severity", "note", "is_active"]
        read_only_fields = ["id"]


class MedicationCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = MedicationCategory
        fields = ["id", "name", "display_order"]
        read_only_fields = ["id"]


class MedicationSerializer(serializers.ModelSerializer):
    dose_ranges = DoseRangeSerializer(many=True, required=False)
    contraindications = ContraindicationRuleSerializer(many=True, read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    label = serializers.CharField(source="__str__", read_only=True)
    stock_on_hand = serializers.SerializerMethodField()

    class Meta:
        model = Medication
        fields = ["id", "category", "category_name", "generic_name", "brand_name",
                  "strength", "dosage_form", "default_route", "dispensing_unit",
                  "ingredients_csv", "atc_class", "avoid_in_pregnancy",
                  "avoid_in_renal_impairment", "paediatric_caution", "caution_note",
                  "reorder_level", "is_active", "label", "dose_ranges",
                  "contraindications", "stock_on_hand",
                  "code_system", "code", "code_display", "code_version"]
        read_only_fields = ["id", "label"]

    def get_stock_on_hand(self, medication) -> int:
        """Availability is a prescribing consideration, so it travels with the drug."""
        return sum(
            batch.quantity_on_hand
            for batch in medication.batches.all()
            if not batch.is_expired
        )

    def create(self, validated_data):
        ranges = validated_data.pop("dose_ranges", [])
        medication = Medication.objects.create(**validated_data)
        for entry in ranges:
            DoseRange.objects.create(medication=medication, **entry)
        return medication


class StockBatchSerializer(serializers.ModelSerializer):
    medication_label = serializers.CharField(source="medication.__str__", read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = StockBatch
        fields = ["id", "medication", "medication_label", "facility", "batch_number",
                  "expiry_date", "quantity_on_hand", "unit_cost", "is_expired",
                  "received_at"]
        read_only_fields = ["id", "is_expired", "quantity_on_hand"]


class DispenseSerializer(serializers.ModelSerializer):
    batch_number = serializers.CharField(source="batch.batch_number", read_only=True)
    expiry_date = serializers.DateField(source="batch.expiry_date", read_only=True)
    dispensed_by_email = serializers.CharField(source="dispensed_by.email", read_only=True)
    medication_label = serializers.CharField(
        source="batch.medication.__str__", read_only=True
    )

    class Meta:
        model = Dispense
        fields = ["id", "quantity", "batch_number", "expiry_date", "medication_label",
                  "dispensed_by_email", "dispensed_at", "note"]
        read_only_fields = fields


class PrescriptionItemSerializer(serializers.ModelSerializer):
    medication_label = serializers.CharField(source="medication.__str__", read_only=True)
    quantity_outstanding = serializers.IntegerField(read_only=True)
    dispenses = DispenseSerializer(many=True, read_only=True)
    overrides = serializers.SerializerMethodField()

    class Meta:
        model = PrescriptionItem
        fields = ["id", "medication", "medication_label", "dose", "dose_unit", "route",
                  "frequency_per_day", "duration_days", "quantity_prescribed",
                  "quantity_dispensed", "quantity_outstanding", "instructions",
                  "status", "cancelled_reason", "dispenses", "overrides"]
        read_only_fields = ["id", "quantity_dispensed", "quantity_outstanding", "status"]

    def get_overrides(self, item) -> list[dict]:
        return [
            {
                "kind": override.warning_kind,
                "detail": override.warning_detail,
                "reason": override.reason,
                "by": override.overridden_by.email,
                "at": override.overridden_at.isoformat(),
            }
            for override in item.safety_overrides.all()
        ]


class PrescriptionSerializer(serializers.ModelSerializer):
    items = PrescriptionItemSerializer(many=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    hospital_number = serializers.CharField(
        source="patient.hospital_number", read_only=True
    )
    prescribed_by_email = serializers.CharField(
        source="prescribed_by.email", read_only=True
    )

    class Meta:
        model = Prescription
        fields = ["id", "prescription_number", "visit", "admission", "encounter",
                  "patient", "patient_name", "hospital_number", "facility",
                  "prescribed_by", "prescribed_by_email", "prescribed_at", "status",
                  "notes", "is_discharge_medication", "items"]
        read_only_fields = ["id", "prescription_number", "patient", "facility",
                            "prescribed_by", "prescribed_at", "status"]

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


class ScreenSerializer(serializers.Serializer):
    patient = serializers.IntegerField()
    medication = serializers.IntegerField()
    dose = serializers.DecimalField(max_digits=10, decimal_places=3, required=False,
                                    allow_null=True)
    route = serializers.CharField(required=False, allow_blank=True)
    frequency_per_day = serializers.IntegerField(required=False, allow_null=True)


class DispenseRequestSerializer(serializers.Serializer):
    batch = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)
    note = serializers.CharField(required=False, allow_blank=True, default="")
