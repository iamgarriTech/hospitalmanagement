from rest_framework import serializers

from .models import Diagnosis, Encounter, EncounterVersion, VitalSigns


class DiagnosisSerializer(serializers.ModelSerializer):
    class Meta:
        model = Diagnosis
        fields = ["id", "description", "certainty", "is_primary",
                  "code_system", "code", "code_display", "code_version"]
        read_only_fields = ["id"]


class EncounterVersionSerializer(serializers.ModelSerializer):
    authored_by = serializers.CharField(source="authored_by.email", read_only=True)
    diagnoses = DiagnosisSerializer(many=True, read_only=True)

    class Meta:
        model = EncounterVersion
        fields = [
            "id", "version_number", "is_current", "authored_by", "authored_at",
            "amendment_reason", "amends", "diagnoses", *EncounterVersion.NARRATIVE,
        ]
        read_only_fields = fields


class EncounterSerializer(serializers.ModelSerializer):
    """The encounter plus whichever version is current."""

    current = EncounterVersionSerializer(source="current_version", read_only=True)
    version_count = serializers.IntegerField(read_only=True)
    clinician_email = serializers.CharField(source="clinician.email", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)

    # Write-only initial content, so creating a consultation is one request.
    diagnoses = DiagnosisSerializer(many=True, required=False, write_only=True)
    presenting_complaint = serializers.CharField(required=False, allow_blank=True,
                                                 write_only=True)
    history_of_presenting_complaint = serializers.CharField(required=False,
                                                           allow_blank=True, write_only=True)
    past_medical_history = serializers.CharField(required=False, allow_blank=True,
                                                 write_only=True)
    surgical_history = serializers.CharField(required=False, allow_blank=True,
                                             write_only=True)
    family_history = serializers.CharField(required=False, allow_blank=True, write_only=True)
    social_history = serializers.CharField(required=False, allow_blank=True, write_only=True)
    medication_history = serializers.CharField(required=False, allow_blank=True,
                                               write_only=True)
    examination_findings = serializers.CharField(required=False, allow_blank=True,
                                                 write_only=True)
    clinical_notes = serializers.CharField(required=False, allow_blank=True, write_only=True)
    treatment_plan = serializers.CharField(required=False, allow_blank=True, write_only=True)
    follow_up_plan = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Encounter
        fields = [
            "id", "visit", "admission", "patient", "patient_name", "facility",
            "encounter_type", "status", "clinician", "clinician_email", "started_at",
            "finalised_at", "current", "version_count", "diagnoses",
            *EncounterVersion.NARRATIVE,
        ]
        read_only_fields = ["id", "patient", "facility", "status", "clinician",
                            "finalised_at"]

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


class AmendSerializer(serializers.Serializer):
    reason = serializers.CharField()
    diagnoses = DiagnosisSerializer(many=True, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in EncounterVersion.NARRATIVE:
            self.fields[field] = serializers.CharField(required=False, allow_blank=True)


class VitalSignsSerializer(serializers.ModelSerializer):
    bmi = serializers.FloatField(read_only=True)
    blood_pressure = serializers.CharField(read_only=True)
    recorded_by_email = serializers.CharField(source="recorded_by.email", read_only=True)

    class Meta:
        model = VitalSigns
        fields = [
            "id", "patient", "visit", "admission", "facility",
            "temperature_c", "systolic_bp", "diastolic_bp", "blood_pressure",
            "pulse_bpm", "respiratory_rate", "oxygen_saturation",
            "weight_kg", "height_cm", "bmi", "blood_glucose_mmol", "pain_score",
            "is_erroneous", "error_reason",
            "recorded_by", "recorded_by_email", "recorded_at",
        ]
        read_only_fields = ["id", "bmi", "blood_pressure", "recorded_by",
                            "is_erroneous", "error_reason"]

    def validate(self, attrs):
        if self.instance is None and (
            attrs.get("visit") is None and attrs.get("admission") is None
        ):
            raise serializers.ValidationError(
                "An observation belongs to an attendance or to an admission."
            )
        # BMI is derived; rejecting it explicitly is clearer than ignoring it silently.
        if "bmi" in self.initial_data:
            raise serializers.ValidationError(
                {"bmi": "BMI is calculated from height and weight and cannot be set."}
            )
        systolic = attrs.get("systolic_bp")
        diastolic = attrs.get("diastolic_bp")
        if systolic and diastolic and systolic <= diastolic:
            raise serializers.ValidationError(
                {"systolic_bp": "Systolic pressure must be above diastolic."}
            )
        return attrs


class MarkErroneousSerializer(serializers.Serializer):
    reason = serializers.CharField()
