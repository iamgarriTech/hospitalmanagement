from rest_framework import serializers

from .models import AntenatalVisit, Baby, Delivery, Pregnancy


class AntenatalVisitSerializer(serializers.ModelSerializer):
    seen_by_name = serializers.CharField(source="seen_by.full_name", read_only=True)

    class Meta:
        model = AntenatalVisit
        fields = ["id", "pregnancy", "visit", "sequence", "seen_at",
                  "gestation_weeks", "weight_kg", "systolic_bp", "diastolic_bp",
                  "fundal_height_cm", "fetal_heart_rate", "presentation",
                  "urine_protein", "urine_glucose", "haemoglobin", "notes",
                  "next_appointment", "seen_by", "seen_by_name"]
        read_only_fields = ["id", "pregnancy", "sequence", "seen_by"]


class BabySerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="patient.full_name", read_only=True)
    hospital_number = serializers.CharField(
        source="patient.hospital_number", read_only=True
    )
    sex = serializers.CharField(source="patient.get_sex_display", read_only=True)
    outcome_display = serializers.CharField(source="get_outcome_display", read_only=True)

    class Meta:
        model = Baby
        fields = ["id", "delivery", "patient", "name", "hospital_number", "sex",
                  "birth_order", "outcome", "outcome_display", "birth_weight_grams",
                  "apgar_one_minute", "apgar_five_minutes", "resuscitation",
                  "congenital_abnormality"]
        read_only_fields = fields


class DeliverySerializer(serializers.ModelSerializer):
    mother_name = serializers.CharField(
        source="pregnancy.patient.full_name", read_only=True
    )
    mother = serializers.IntegerField(source="pregnancy.patient_id", read_only=True)
    mode_display = serializers.CharField(source="get_mode_display", read_only=True)
    delivered_by_name = serializers.CharField(
        source="delivered_by.full_name", read_only=True
    )
    babies = BabySerializer(many=True, read_only=True)

    class Meta:
        model = Delivery
        fields = ["id", "pregnancy", "mother", "mother_name", "admission",
                  "procedure", "delivered_at", "mode", "mode_display",
                  "onset_of_labour", "duration_of_labour_minutes",
                  "estimated_blood_loss_ml", "perineal_tear", "complications",
                  "placenta_complete", "delivered_by", "delivered_by_name",
                  "recorded_by", "recorded_at", "babies"]
        read_only_fields = fields


class PregnancySerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    hospital_number = serializers.CharField(
        source="patient.hospital_number", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    edd_basis_display = serializers.CharField(
        source="get_edd_basis_display", read_only=True
    )
    booked_by_name = serializers.CharField(source="booked_by.full_name", read_only=True)
    antenatal_visits = AntenatalVisitSerializer(many=True, read_only=True)
    delivery = DeliverySerializer(read_only=True)
    gestation = serializers.SerializerMethodField()
    is_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = Pregnancy
        fields = ["id", "patient", "patient_name", "hospital_number", "facility",
                  "last_menstrual_period", "estimated_delivery_date", "edd_basis",
                  "edd_basis_display", "edd_basis_note", "gravida", "parity",
                  "previous_losses", "risk_factors", "status", "status_display",
                  "ended_at", "ended_reason", "booked_by", "booked_by_name",
                  "booked_at", "antenatal_visits", "delivery", "gestation",
                  "is_open"]
        read_only_fields = ["id", "status", "status_display", "ended_at",
                            "ended_reason", "booked_by", "booked_at",
                            "antenatal_visits", "delivery", "gestation", "is_open"]

    def get_gestation(self, pregnancy):
        return pregnancy.gestation_at()


class BookPregnancySerializer(serializers.Serializer):
    patient = serializers.IntegerField()
    facility = serializers.IntegerField()
    estimated_delivery_date = serializers.DateField(required=False, allow_null=True,
                                                    default=None)
    last_menstrual_period = serializers.DateField(required=False, allow_null=True,
                                                  default=None)
    edd_basis = serializers.ChoiceField(
        choices=Pregnancy.EDD_BASIS_CHOICES, default=Pregnancy.LMP
    )
    edd_basis_note = serializers.CharField(max_length=255, required=False,
                                           allow_blank=True, default="")
    gravida = serializers.IntegerField(min_value=1, default=1)
    parity = serializers.IntegerField(min_value=0, default=0)
    previous_losses = serializers.IntegerField(min_value=0, default=0)
    risk_factors = serializers.CharField(required=False, allow_blank=True, default="")


class ReviseEddSerializer(serializers.Serializer):
    estimated_delivery_date = serializers.DateField()
    basis = serializers.ChoiceField(choices=Pregnancy.EDD_BASIS_CHOICES)
    note = serializers.CharField(max_length=255)


class BabyEntrySerializer(serializers.Serializer):
    family_name = serializers.CharField(max_length=100, required=False,
                                        allow_blank=True, default="")
    given_name = serializers.CharField(max_length=100, required=False,
                                       allow_blank=True, default="")
    sex = serializers.ChoiceField(
        choices=[("male", "Male"), ("female", "Female"), ("other", "Other"),
                 ("unknown", "Unknown")],
        default="unknown",
    )
    outcome = serializers.ChoiceField(choices=Baby.OUTCOME_CHOICES,
                                      default=Baby.LIVE_BIRTH)
    birth_weight_grams = serializers.IntegerField(required=False, allow_null=True,
                                                  default=None, min_value=0)
    apgar_one_minute = serializers.IntegerField(required=False, allow_null=True,
                                                default=None, min_value=0, max_value=10)
    apgar_five_minutes = serializers.IntegerField(required=False, allow_null=True,
                                                  default=None, min_value=0,
                                                  max_value=10)
    resuscitation = serializers.CharField(max_length=255, required=False,
                                          allow_blank=True, default="")
    congenital_abnormality = serializers.CharField(max_length=255, required=False,
                                                   allow_blank=True, default="")


class DeliverSerializer(serializers.Serializer):
    delivered_at = serializers.DateTimeField()
    mode = serializers.ChoiceField(choices=Delivery.MODE_CHOICES)
    delivered_by = serializers.IntegerField()
    admission = serializers.IntegerField(required=False, allow_null=True, default=None)
    onset_of_labour = serializers.CharField(max_length=40, required=False,
                                            allow_blank=True, default="")
    duration_of_labour_minutes = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=0
    )
    estimated_blood_loss_ml = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=0
    )
    perineal_tear = serializers.CharField(max_length=40, required=False,
                                          allow_blank=True, default="")
    complications = serializers.CharField(required=False, allow_blank=True, default="")
    placenta_complete = serializers.BooleanField(required=False, allow_null=True,
                                                 default=None)
    babies = BabyEntrySerializer(many=True, allow_empty=False)


class EndPregnancySerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)
    status = serializers.ChoiceField(
        choices=[(Pregnancy.ENDED, "Ended before delivery"),
                 (Pregnancy.TRANSFERRED, "Care transferred out")],
        default=Pregnancy.ENDED,
    )
