from rest_framework import serializers

from patients.serializers import PatientSummarySerializer

from ..models import Admission, AdmissionRequest, Bed, BedTransfer
from .wards import BedOccupancySerializer


class AdmissionRequestSerializer(serializers.ModelSerializer):
    patient_detail = PatientSummarySerializer(source="patient", read_only=True)
    ward_name = serializers.CharField(source="ward.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    consultant_name = serializers.CharField(
        source="responsible_consultant.full_name", read_only=True
    )
    requested_by_name = serializers.CharField(source="requested_by.full_name", read_only=True)
    waiting_minutes = serializers.IntegerField(read_only=True)
    admission = serializers.IntegerField(source="admission.pk", read_only=True, default=None)
    allergies = serializers.SerializerMethodField()

    class Meta:
        model = AdmissionRequest
        fields = [
            "id", "patient", "patient_detail", "visit", "facility", "ward", "ward_name",
            "reason", "working_diagnosis", "responsible_consultant", "consultant_name",
            "priority", "requested_by", "requested_by_name", "requested_at", "status",
            "status_display", "decided_by", "decided_at", "decline_reason",
            "waiting_minutes", "admission", "allergies",
        ]
        read_only_fields = [
            "id", "requested_by", "requested_at", "status", "decided_by", "decided_at",
            "decline_reason",
        ]

    def get_allergies(self, request) -> list[str]:
        """On the request itself, for the same reason the queue row carries them:
        a ward clerk should not have to open a chart to learn that the patient
        they are allocating a bed to is allergic to something."""
        return [
            allergy.substance
            for allergy in request.patient.allergies.all()
            if allergy.is_active
        ]

    def validate(self, attrs):
        ward = attrs.get("ward")
        facility = attrs.get("facility")
        if ward is not None and facility is not None and ward.facility_id != facility.pk:
            raise serializers.ValidationError(
                {"ward": f"{ward.name} is at {ward.facility.code}, not {facility.code}."}
            )
        patient = attrs.get("patient")
        if patient is not None and facility is not None:
            open_admission = Admission.objects.filter(patient=patient).exclude(
                status=Admission.DISCHARGED
            ).first()
            if open_admission is not None:
                raise serializers.ValidationError(
                    {"patient": f"{patient.full_name} is already an inpatient under "
                                f"{open_admission.admission_number}."}
                )
        return attrs


class BedTransferSerializer(serializers.ModelSerializer):
    from_bed = serializers.CharField(source="from_occupancy.bed.__str__", read_only=True)
    to_bed = serializers.CharField(source="to_occupancy.bed.__str__", read_only=True)
    from_ward = serializers.CharField(
        source="from_occupancy.bed.room.ward.name", read_only=True
    )
    to_ward = serializers.CharField(source="to_occupancy.bed.room.ward.name", read_only=True)
    authorised_by_name = serializers.CharField(
        source="authorised_by.full_name", read_only=True
    )
    changed_ward = serializers.BooleanField(read_only=True)

    class Meta:
        model = BedTransfer
        fields = [
            "id", "admission", "from_bed", "from_ward", "to_bed", "to_ward",
            "changed_ward", "reason", "authorised_by", "authorised_by_name", "moved_at",
        ]


class AdmissionSerializer(serializers.ModelSerializer):
    patient_detail = PatientSummarySerializer(source="patient", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    consultant_name = serializers.CharField(
        source="responsible_consultant.full_name", read_only=True
    )
    admitted_by_name = serializers.CharField(source="admitted_by.full_name", read_only=True)
    discharged_by_name = serializers.CharField(
        source="discharged_by.full_name", read_only=True, default=None
    )
    destination_display = serializers.CharField(
        source="get_discharge_destination_display", read_only=True
    )
    length_of_stay_nights = serializers.IntegerField(read_only=True)
    bed = serializers.SerializerMethodField()
    movement = serializers.SerializerMethodField()
    occupancies = BedOccupancySerializer(many=True, read_only=True)
    transfers = BedTransferSerializer(many=True, read_only=True)
    allergies = serializers.SerializerMethodField()

    class Meta:
        model = Admission
        fields = [
            "id", "admission_number", "request", "patient", "patient_detail", "visit",
            "facility", "admission_reason", "admission_diagnosis",
            "responsible_consultant", "consultant_name", "admitted_by",
            "admitted_by_name", "admitted_at", "status", "status_display",
            "expected_discharge_date", "discharge_destination", "destination_display",
            "discharge_plan_notes", "discharged_at", "discharged_by",
            "discharged_by_name", "discharge_diagnosis", "follow_up_instructions",
            "billing_override_reason", "length_of_stay_nights", "bed", "movement",
            "occupancies", "transfers", "allergies", "created_at",
        ]
        read_only_fields = fields

    def get_bed(self, admission) -> dict | None:
        occupancy = admission.current_occupancy
        if occupancy is None:
            return None
        bed = occupancy.bed
        return {
            "id": bed.pk,
            "label": str(bed),
            "room": bed.room.code,
            "ward": bed.room.ward_id,
            "ward_name": bed.room.ward.name,
            "since": occupancy.period.lower,
        }

    def get_movement(self, admission) -> list:
        """AC-77 — every bed and ward, in order, from the admission alone."""
        return admission.movement

    def get_allergies(self, admission) -> list[str]:
        return [
            allergy.substance
            for allergy in admission.patient.allergies.all()
            if allergy.is_active
        ]


class AdmitSerializer(serializers.Serializer):
    """Admitting from a request, or directly.

    Everything except the bed is optional because admitting from a request
    carries the clinical detail forward — a ward clerk retyping a diagnosis
    produces a second, worse diagnosis.
    """

    bed = serializers.PrimaryKeyRelatedField(queryset=Bed.objects.all())
    request = serializers.PrimaryKeyRelatedField(
        queryset=AdmissionRequest.objects.all(), required=False, allow_null=True
    )
    patient = serializers.IntegerField(required=False)
    facility = serializers.IntegerField(required=False)
    visit = serializers.IntegerField(required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    diagnosis = serializers.CharField(required=False, allow_blank=True, default="")
    responsible_consultant = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        if attrs.get("request") is None and not attrs.get("patient"):
            raise serializers.ValidationError(
                "Admit from a request, or say which patient and facility."
            )
        return attrs


class DeclineSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class TransferSerializer(serializers.Serializer):
    to_bed = serializers.PrimaryKeyRelatedField(queryset=Bed.objects.all())
    reason = serializers.CharField(max_length=255)


class PlanDischargeSerializer(serializers.Serializer):
    expected_date = serializers.DateField(required=False, allow_null=True)
    destination = serializers.ChoiceField(
        choices=[value for value, _ in Admission.DESTINATION_CHOICES],
        required=False, allow_blank=True, default="",
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class DischargeSerializer(serializers.Serializer):
    diagnosis = serializers.CharField(max_length=255)
    destination = serializers.ChoiceField(
        choices=[value for value, _ in Admission.DESTINATION_CHOICES]
    )
    instructions = serializers.CharField(required=False, allow_blank=True, default="")
    override_reason = serializers.CharField(
        required=False, allow_blank=True, default="",
        help_text="Required to discharge with an unsettled bill, and audited.",
    )
