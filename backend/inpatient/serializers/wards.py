from rest_framework import serializers

from ..models import Bed, BedOccupancy, EscalationThreshold, Room, Ward


class BedSerializer(serializers.ModelSerializer):
    state = serializers.CharField(read_only=True)
    state_display = serializers.SerializerMethodField()
    ward = serializers.IntegerField(source="room.ward_id", read_only=True)
    ward_name = serializers.CharField(source="room.ward.name", read_only=True)
    room_code = serializers.CharField(source="room.code", read_only=True)
    label = serializers.CharField(source="__str__", read_only=True)
    occupant = serializers.SerializerMethodField()

    class Meta:
        model = Bed
        fields = [
            "id", "room", "room_code", "ward", "ward_name", "code", "label",
            "service_state", "state", "state_display", "state_note", "is_active",
            "occupant",
        ]

    def get_state_display(self, bed) -> str:
        """The state in words, so a colour is never the only cue."""
        if bed.state == Bed.OCCUPIED:
            return "Occupied"
        return bed.get_service_state_display()

    def get_occupant(self, bed) -> dict | None:
        occupancy = bed.current_occupancy
        if occupancy is None:
            return None
        return {
            "patient": occupancy.patient_id,
            "patient_name": occupancy.patient.full_name,
            "hospital_number": occupancy.patient.hospital_number,
            "admission": occupancy.admission_id,
            "admission_number": occupancy.admission.admission_number,
            "since": occupancy.period.lower,
            "nights": occupancy.nights,
        }


class RoomSerializer(serializers.ModelSerializer):
    beds = BedSerializer(many=True, read_only=True)
    ward_name = serializers.CharField(source="ward.name", read_only=True)

    class Meta:
        model = Room
        fields = ["id", "ward", "ward_name", "name", "code", "is_active", "beds"]


class EscalationThresholdSerializer(serializers.ModelSerializer):
    measurement_display = serializers.CharField(
        source="get_measurement_display", read_only=True
    )

    class Meta:
        model = EscalationThreshold
        fields = [
            "id", "ward", "measurement", "measurement_display", "low", "high",
            "instruction", "is_active",
        ]

    def validate(self, attrs):
        low = attrs.get("low", getattr(self.instance, "low", None))
        high = attrs.get("high", getattr(self.instance, "high", None))
        if low is None and high is None:
            raise serializers.ValidationError(
                "A threshold needs a low bound, a high bound, or both."
            )
        if low is not None and high is not None and low > high:
            raise serializers.ValidationError("The low bound is above the high bound.")
        return attrs


class WardSerializer(serializers.ModelSerializer):
    ward_type_display = serializers.CharField(source="get_ward_type_display", read_only=True)
    facility_name = serializers.CharField(source="facility.name", read_only=True)
    nightly_rate = serializers.SerializerMethodField()
    occupancy = serializers.SerializerMethodField()

    class Meta:
        model = Ward
        fields = [
            "id", "facility", "facility_name", "department", "name", "code",
            "ward_type", "ward_type_display", "nightly_service", "nightly_rate",
            "is_active", "occupancy",
        ]

    def get_nightly_rate(self, ward) -> str | None:
        """Per facility, like every other price — a branch clinic does not
        charge a teaching hospital's bed rate."""
        service = ward.nightly_service
        if service is None:
            return None
        amount = service.price_at(ward.facility)
        return str(amount) if amount is not None else None

    def get_occupancy(self, ward) -> dict:
        """Counted from live occupancies on every read.

        Not cached and not stored: a bed census that can be stale is a bed
        census that will hand out an occupied bed.
        """
        return ward.occupancy()


class BedOccupancySerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    hospital_number = serializers.CharField(source="patient.hospital_number", read_only=True)
    admission_number = serializers.CharField(
        source="admission.admission_number", read_only=True
    )
    bed_label = serializers.CharField(source="bed.__str__", read_only=True)
    started_at = serializers.DateTimeField(read_only=True)
    ended_at = serializers.DateTimeField(read_only=True)
    nights = serializers.IntegerField(read_only=True)
    allocated_by_name = serializers.CharField(
        source="allocated_by.full_name", read_only=True, default=None
    )
    ended_by_name = serializers.CharField(
        source="ended_by.full_name", read_only=True, default=None
    )

    class Meta:
        model = BedOccupancy
        fields = [
            "id", "bed", "bed_label", "admission", "admission_number", "patient",
            "patient_name", "hospital_number", "started_at", "ended_at", "nights",
            "allocated_by_name", "ended_by_name", "reason_ended",
        ]


class BedStateSerializer(serializers.Serializer):
    service_state = serializers.ChoiceField(
        choices=[state for state, _ in Bed.SERVICE_STATES]
    )
    note = serializers.CharField(required=False, allow_blank=True, default="")
