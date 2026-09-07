from rest_framework import serializers

from .models import NextOfKin, Patient, PatientAllergy, PatientChronicCondition


class PatientAllergySerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientAllergy
        fields = ["id", "substance", "reaction", "severity", "is_active",
                  "code_system", "code", "code_display", "code_version", "recorded_at"]
        read_only_fields = ["id", "recorded_at"]


class ChronicConditionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientChronicCondition
        fields = ["id", "condition", "noted_on", "is_active",
                  "code_system", "code", "code_display", "code_version"]
        read_only_fields = ["id"]


class NextOfKinSerializer(serializers.ModelSerializer):
    class Meta:
        model = NextOfKin
        fields = ["id", "full_name", "relationship", "phone", "address",
                  "is_emergency_contact"]
        read_only_fields = ["id"]


class PatientSummarySerializer(serializers.ModelSerializer):
    """List rows. Enough to identify the right person and no more."""

    full_name = serializers.CharField(read_only=True)
    age_years = serializers.IntegerField(read_only=True)

    class Meta:
        model = Patient
        fields = ["id", "hospital_number", "full_name", "sex", "date_of_birth",
                  "date_of_birth_is_estimated", "age_years", "phone_primary", "status"]


class PatientSerializer(serializers.ModelSerializer):
    """Full profile. Allergies are surfaced here because every clinical screen's header
    needs them without a second request (AC-12)."""

    full_name = serializers.CharField(read_only=True)
    age_years = serializers.IntegerField(read_only=True)
    allergies = PatientAllergySerializer(many=True, required=False)
    chronic_conditions = ChronicConditionSerializer(many=True, required=False)
    next_of_kin = NextOfKinSerializer(many=True, required=False)
    merged_into_hospital_number = serializers.CharField(
        source="merged_into.hospital_number", read_only=True, default=None
    )

    class Meta:
        model = Patient
        fields = [
            "id", "hospital_number", "family_name", "given_name", "other_names",
            "full_name", "date_of_birth", "date_of_birth_is_estimated", "age_years",
            "sex", "phone_primary", "phone_alternate", "email",
            "address_line", "city", "state", "country",
            "blood_group", "genotype", "facility", "status",
            "merged_into", "merged_into_hospital_number",
            "allergies", "chronic_conditions", "next_of_kin",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "hospital_number", "status", "merged_into",
                            "created_at", "updated_at"]

    def create(self, validated_data):
        allergies = validated_data.pop("allergies", [])
        conditions = validated_data.pop("chronic_conditions", [])
        kin = validated_data.pop("next_of_kin", [])
        patient = Patient.objects.create(**validated_data)
        recorded_by = validated_data.get("registered_by")
        for allergy in allergies:
            PatientAllergy.objects.create(patient=patient, recorded_by=recorded_by, **allergy)
        for condition in conditions:
            PatientChronicCondition.objects.create(patient=patient, **condition)
        for relative in kin:
            NextOfKin.objects.create(patient=patient, **relative)
        return patient

    def update(self, instance, validated_data):
        for nested in ("allergies", "chronic_conditions", "next_of_kin"):
            validated_data.pop(nested, None)  # managed through their own endpoints
        return super().update(instance, validated_data)


class DuplicateCandidateSerializer(serializers.Serializer):
    patient = PatientSummarySerializer(read_only=True)
    score = serializers.FloatField(read_only=True)
    reasons = serializers.ListField(child=serializers.CharField(), read_only=True)


class DuplicateCheckSerializer(serializers.Serializer):
    given_name = serializers.CharField()
    family_name = serializers.CharField()
    other_names = serializers.CharField(required=False, allow_blank=True, default="")
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    phone = serializers.CharField(required=False, allow_blank=True, default="")


class MergeSerializer(serializers.Serializer):
    into = serializers.IntegerField(help_text="Id of the surviving patient record.")
    reason = serializers.CharField()
