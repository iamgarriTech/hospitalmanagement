from rest_framework import serializers

from .models import (
    Consent,
    OperationNote,
    OperationNoteVersion,
    PerformedProcedure,
    Procedure,
    ProcedureCategory,
    ProcedureConsumable,
    ProcedureConsumableUsed,
    ProcedureMedication,
    ProcedureRequest,
    ProcedureTeamMember,
    Theatre,
    TheatreBooking,
)


class ProcedureCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProcedureCategory
        fields = ["id", "name", "display_order"]
        read_only_fields = ["id"]


class ProcedureConsumableSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.name", read_only=True)
    unit_of_issue = serializers.CharField(source="item.unit_of_issue", read_only=True)

    class Meta:
        model = ProcedureConsumable
        fields = ["id", "item", "item_name", "unit_of_issue", "quantity"]
        read_only_fields = ["id"]


class ProcedureSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    consumables = ProcedureConsumableSerializer(many=True, read_only=True)
    service_code = serializers.CharField(
        source="billing_service.code", read_only=True, default=None
    )

    class Meta:
        model = Procedure
        fields = ["id", "category", "category_name", "name", "code",
                  "typical_duration_minutes", "requires_theatre", "requires_consent",
                  "requires_anaesthesia", "billing_service", "service_code",
                  "preparation", "is_active", "consumables"]
        read_only_fields = ["id", "consumables"]


class TheatreSerializer(serializers.ModelSerializer):
    facility_name = serializers.CharField(source="facility.name", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True, default=None)

    class Meta:
        model = Theatre
        fields = ["id", "facility", "facility_name", "name", "code", "store",
                  "store_name", "is_active", "out_of_service_note"]
        read_only_fields = ["id"]


class ConsentSerializer(serializers.ModelSerializer):
    taken_by_email = serializers.CharField(source="taken_by.email", read_only=True)
    given_by_display = serializers.CharField(
        source="get_given_by_display", read_only=True
    )
    is_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = Consent
        fields = ["id", "request", "given_by", "given_by_display", "given_by_name",
                  "relationship", "risks_discussed", "interpreter_used",
                  "interpreter_name", "taken_by", "taken_by_email", "taken_at",
                  "withdrawn_at", "withdrawal_reason", "is_valid"]
        read_only_fields = ["id", "request", "taken_by", "taken_at", "withdrawn_at",
                            "withdrawal_reason", "is_valid"]


class RecordConsentSerializer(serializers.Serializer):
    risks_discussed = serializers.CharField()
    given_by = serializers.ChoiceField(
        choices=Consent.GIVEN_BY_CHOICES, default=Consent.PATIENT
    )
    given_by_name = serializers.CharField(max_length=200, required=False,
                                          allow_blank=True, default="")
    relationship = serializers.CharField(max_length=80, required=False,
                                         allow_blank=True, default="")
    interpreter_used = serializers.BooleanField(default=False)
    interpreter_name = serializers.CharField(max_length=200, required=False,
                                             allow_blank=True, default="")


class OperationNoteVersionSerializer(serializers.ModelSerializer):
    author_email = serializers.CharField(source="author.email", read_only=True)
    author_name = serializers.CharField(source="author.full_name", read_only=True)

    class Meta:
        model = OperationNoteVersion
        fields = ["id", "version_number", "is_current", "findings",
                  "procedure_performed", "closure", "estimated_blood_loss_ml",
                  "specimens_taken", "complications", "post_operative_instructions",
                  "author", "author_email", "author_name", "created_at",
                  "amendment_reason"]
        read_only_fields = fields


class OperationNoteSerializer(serializers.ModelSerializer):
    versions = OperationNoteVersionSerializer(many=True, read_only=True)
    current = OperationNoteVersionSerializer(read_only=True)

    class Meta:
        model = OperationNote
        fields = ["id", "performed", "created_at", "current", "versions"]
        read_only_fields = fields


class AmendNoteSerializer(serializers.Serializer):
    reason = serializers.CharField()
    findings = serializers.CharField(required=False, allow_null=True, default=None)
    procedure_performed = serializers.CharField(required=False, allow_null=True,
                                                default=None)
    closure = serializers.CharField(required=False, allow_null=True, default=None,
                                    allow_blank=True)
    estimated_blood_loss_ml = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=0
    )
    specimens_taken = serializers.CharField(required=False, allow_null=True,
                                            default=None, allow_blank=True)
    complications = serializers.CharField(required=False, allow_null=True,
                                          default=None, allow_blank=True)
    post_operative_instructions = serializers.CharField(
        required=False, allow_null=True, default=None, allow_blank=True
    )


class TeamMemberSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source="member.full_name", read_only=True)
    role_display = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = ProcedureTeamMember
        fields = ["id", "member", "member_name", "role", "role_display"]
        read_only_fields = ["id"]


class ConsumableUsedSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.name", read_only=True)
    store_name = serializers.CharField(
        source="movement.lot.record.store.name", read_only=True
    )

    class Meta:
        model = ProcedureConsumableUsed
        fields = ["id", "item", "item_name", "quantity", "movement", "store_name"]
        read_only_fields = fields


class ProcedureMedicationSerializer(serializers.ModelSerializer):
    medication_name = serializers.CharField(
        source="medication.generic_name", read_only=True
    )
    given_by_name = serializers.CharField(source="given_by.full_name", read_only=True)

    class Meta:
        model = ProcedureMedication
        fields = ["id", "medication", "medication_name", "dose", "route",
                  "given_at", "given_by", "given_by_name"]
        read_only_fields = ["id"]


class PerformedProcedureSerializer(serializers.ModelSerializer):
    procedure_name = serializers.CharField(
        source="request.procedure.name", read_only=True
    )
    patient_name = serializers.CharField(
        source="request.patient.full_name", read_only=True
    )
    reference = serializers.CharField(source="request.reference", read_only=True)
    lead_clinician_name = serializers.CharField(
        source="lead_clinician.full_name", read_only=True
    )
    outcome_display = serializers.CharField(source="get_outcome_display", read_only=True)
    duration_minutes = serializers.IntegerField(read_only=True)
    team = TeamMemberSerializer(many=True, read_only=True)
    consumables_used = ConsumableUsedSerializer(many=True, read_only=True)
    medications = ProcedureMedicationSerializer(many=True, read_only=True)
    note = OperationNoteSerializer(read_only=True)

    class Meta:
        model = PerformedProcedure
        fields = ["id", "request", "reference", "procedure_name", "patient_name",
                  "booking", "started_at", "finished_at", "duration_minutes",
                  "outcome", "outcome_display", "lead_clinician",
                  "lead_clinician_name", "recorded_by", "recorded_at", "is_billed",
                  "team", "consumables_used", "medications", "note"]
        read_only_fields = fields


class TheatreBookingSerializer(serializers.ModelSerializer):
    theatre_name = serializers.CharField(source="theatre.name", read_only=True)
    reference = serializers.CharField(source="request.reference", read_only=True)
    procedure_name = serializers.CharField(
        source="request.procedure.name", read_only=True
    )
    patient_name = serializers.CharField(
        source="request.patient.full_name", read_only=True
    )
    hospital_number = serializers.CharField(
        source="request.patient.hospital_number", read_only=True
    )
    lead_surgeon_name = serializers.CharField(
        source="lead_surgeon.full_name", read_only=True
    )
    anaesthetist_name = serializers.CharField(
        source="anaesthetist.full_name", read_only=True, default=None
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    starts_at = serializers.SerializerMethodField()
    ends_at = serializers.SerializerMethodField()

    class Meta:
        model = TheatreBooking
        fields = ["id", "theatre", "theatre_name", "request", "reference",
                  "procedure_name", "patient_name", "hospital_number", "starts_at",
                  "ends_at", "status", "status_display", "lead_surgeon",
                  "lead_surgeon_name", "anaesthetist", "anaesthetist_name",
                  "booked_by", "booked_at", "cancelled_at", "cancellation_reason"]
        read_only_fields = fields

    def get_starts_at(self, booking) -> str:
        return booking.period.lower.isoformat()

    def get_ends_at(self, booking) -> str:
        return booking.period.upper.isoformat()


class BookTheatreSerializer(serializers.Serializer):
    theatre = serializers.PrimaryKeyRelatedField(queryset=Theatre.objects.all())
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    lead_surgeon = serializers.IntegerField()
    anaesthetist = serializers.IntegerField(required=False, allow_null=True,
                                            default=None)


class ProcedureRequestSerializer(serializers.ModelSerializer):
    procedure_name = serializers.CharField(source="procedure.name", read_only=True)
    requires_consent = serializers.BooleanField(
        source="procedure.requires_consent", read_only=True
    )
    requires_theatre = serializers.BooleanField(
        source="procedure.requires_theatre", read_only=True
    )
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    hospital_number = serializers.CharField(
        source="patient.hospital_number", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    urgency_display = serializers.CharField(source="get_urgency_display", read_only=True)
    requested_by_email = serializers.CharField(
        source="requested_by.email", read_only=True
    )
    consent = ConsentSerializer(read_only=True)
    bookings = TheatreBookingSerializer(many=True, read_only=True)
    performed = PerformedProcedureSerializer(read_only=True)
    consent_blocking = serializers.SerializerMethodField()

    class Meta:
        model = ProcedureRequest
        fields = ["id", "reference", "procedure", "procedure_name", "requires_consent",
                  "requires_theatre", "patient", "patient_name", "hospital_number",
                  "facility", "visit", "admission", "indication", "urgency",
                  "urgency_display", "status", "status_display", "requested_by",
                  "requested_by_email", "requested_at", "cancelled_at",
                  "cancellation_reason", "consent", "bookings", "performed",
                  "consent_blocking"]
        # `facility` and `patient` are derived from the episode rather than
        # supplied: a procedure belongs to an attendance or an admission, and
        # letting a client name a different patient or branch from the one the
        # episode belongs to is a way to get a procedure onto the wrong record.
        read_only_fields = ["id", "reference", "status", "status_display",
                            "facility", "patient", "requested_by", "requested_at",
                            "cancelled_at", "cancellation_reason", "consent",
                            "bookings", "performed", "consent_blocking"]

    def get_consent_blocking(self, request) -> str | None:
        from .services import consent_blocking

        return consent_blocking(request)


class TeamEntrySerializer(serializers.Serializer):
    member = serializers.IntegerField()
    role = serializers.ChoiceField(choices=ProcedureTeamMember.ROLE_CHOICES)


class ConsumableEntrySerializer(serializers.Serializer):
    item = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)
    store = serializers.IntegerField(required=False, allow_null=True, default=None)


class MedicationEntrySerializer(serializers.Serializer):
    medication = serializers.IntegerField()
    dose = serializers.CharField(max_length=80)
    route = serializers.CharField(max_length=30)


class PerformSerializer(serializers.Serializer):
    started_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField()
    lead_clinician = serializers.IntegerField()
    outcome = serializers.ChoiceField(
        choices=PerformedProcedure.OUTCOME_CHOICES,
        default=PerformedProcedure.COMPLETED,
    )
    booking = serializers.IntegerField(required=False, allow_null=True, default=None)
    store = serializers.IntegerField(required=False, allow_null=True, default=None)

    findings = serializers.CharField()
    procedure_performed = serializers.CharField()
    closure = serializers.CharField(required=False, allow_blank=True, default="")
    blood_loss_ml = serializers.IntegerField(required=False, allow_null=True,
                                             default=None, min_value=0)
    specimens = serializers.CharField(max_length=255, required=False,
                                      allow_blank=True, default="")
    complications = serializers.CharField(required=False, allow_blank=True, default="")
    post_operative_instructions = serializers.CharField(
        required=False, allow_blank=True, default=""
    )

    team = TeamEntrySerializer(many=True, required=False, default=list)
    consumables = ConsumableEntrySerializer(many=True, required=False, default=list)
    medications = MedicationEntrySerializer(many=True, required=False, default=list)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)
