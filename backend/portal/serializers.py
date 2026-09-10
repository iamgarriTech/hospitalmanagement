"""What the portal sends a patient.

Every serializer here is a narrowed view, not a reuse of the internal one.
That is deliberate: the internal `LabResultSerializer` grows fields as the
laboratory module grows, and reusing it would eventually expose whichever one
somebody adds next. These are written out, so adding a field internally
cannot leak it outward.
"""

from rest_framework import serializers

from .models import PortalAccount


class PortalLoginSerializer(serializers.Serializer):
    login_identifier = serializers.CharField(max_length=120)
    password = serializers.CharField(style={"input_type": "password"})


class PortalPasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(style={"input_type": "password"})
    new_password = serializers.CharField(
        min_length=12, style={"input_type": "password"}
    )

    def validate_new_password(self, value):
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError

        try:
            validate_password(value)
        except DjangoValidationError as problem:
            raise serializers.ValidationError(list(problem.messages))
        return value


class PortalVisitSerializer(serializers.Serializer):
    """An attendance, as the patient's own record of it."""

    id = serializers.IntegerField()
    arrived_at = serializers.DateTimeField()
    facility = serializers.CharField(source="facility.name")
    clinic = serializers.CharField(source="clinic.name", default=None)
    reason = serializers.CharField()
    status = serializers.CharField()
    closed_at = serializers.DateTimeField()


class PortalResultSerializer(serializers.Serializer):
    """A verified result. AC-185 — an unverified one never reaches here.

    The reference range travels with it, because a number without one is a
    number a patient will search for and misread. The interpretation flag is
    included for the same reason: "high" beside a figure is more use than the
    figure alone.

    Deliberately no clinician's comment intended for another clinician. The
    laboratory's own note is included; the ordering doctor's private notes are
    not the portal's business.
    """

    id = serializers.IntegerField()
    test = serializers.CharField(source="order_item.test.name")
    parameter = serializers.CharField(source="parameter.name")
    value = serializers.SerializerMethodField()
    unit = serializers.CharField()
    flag = serializers.CharField()
    reference_range = serializers.SerializerMethodField()
    verified_at = serializers.DateTimeField(source="order_item.verified_at")
    laboratory_comment = serializers.CharField(
        source="order_item.laboratory_comment", default=""
    )

    def get_value(self, result) -> str:
        from core.formatting import trim_decimal

        if result.value_numeric is not None:
            return trim_decimal(result.value_numeric)
        return result.value_text or ""

    def get_reference_range(self, result) -> str:
        from core.formatting import trim_decimal

        low, high = result.range_low, result.range_high
        if low is not None and high is not None:
            return f"{trim_decimal(low)}–{trim_decimal(high)}"
        if low is not None:
            return f"above {trim_decimal(low)}"
        if high is not None:
            return f"below {trim_decimal(high)}"
        return result.range_note or ""


class PortalMedicationSerializer(serializers.Serializer):
    """Current medication, in the words on the label."""

    id = serializers.IntegerField()
    medication = serializers.SerializerMethodField()
    dose = serializers.SerializerMethodField()
    route = serializers.CharField()
    times_a_day = serializers.IntegerField(source="frequency_per_day")
    days = serializers.IntegerField(source="duration_days")
    instructions = serializers.CharField()
    prescribed_at = serializers.DateTimeField(source="prescription.prescribed_at")
    status = serializers.CharField()

    def get_medication(self, item) -> str:
        return (
            f"{item.medication.generic_name} {item.medication.strength} "
            f"{item.medication.dosage_form}"
        ).strip()

    def get_dose(self, item) -> str:
        from core.formatting import trim_decimal

        return f"{trim_decimal(item.dose)} {item.dose_unit}".strip()


class PortalBillSerializer(serializers.Serializer):
    """A bill, and what is still owed on it."""

    id = serializers.IntegerField()
    invoice_number = serializers.CharField()
    facility = serializers.CharField(source="facility.name")
    created_at = serializers.DateTimeField()
    status = serializers.CharField()
    total = serializers.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = serializers.DecimalField(max_digits=12, decimal_places=2)
    balance = serializers.DecimalField(max_digits=12, decimal_places=2)
    items = serializers.SerializerMethodField()

    def get_items(self, invoice):
        return [
            {"description": item.description,
             "quantity": item.quantity,
             "unit_price": str(item.unit_price)}
            for item in invoice.items.all() if not item.is_cancelled
        ]


class PortalAccountSerializer(serializers.ModelSerializer):
    """Staff-facing. Note what is absent: there is no password field out."""

    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    hospital_number = serializers.CharField(
        source="patient.hospital_number", read_only=True
    )
    created_by_email = serializers.CharField(
        source="created_by.email", read_only=True, default=None
    )
    initial_password = serializers.CharField(
        write_only=True, required=False, min_length=12,
        help_text="A temporary password to hand to the patient. Generated if omitted.",
    )

    class Meta:
        model = PortalAccount
        fields = ["id", "patient", "patient_name", "hospital_number",
                  "login_identifier", "is_active", "deactivated_reason",
                  "must_change_password", "last_login_at", "created_at",
                  "created_by", "created_by_email", "initial_password"]
        read_only_fields = ["id", "must_change_password", "last_login_at",
                            "created_at", "created_by"]

    def create(self, validated_data):
        import secrets

        raw = validated_data.pop("initial_password", None) or secrets.token_urlsafe(9)
        account = PortalAccount(**validated_data)
        account.set_password(raw)
        account.must_change_password = True
        account.save()
        # Handed back once so staff can give it to the patient; never stored
        # in clear and never written to the audit row.
        account._initial_password = raw
        return account

    def to_representation(self, instance):
        data = super().to_representation(instance)
        raw = getattr(instance, "_initial_password", None)
        if raw:
            data["temporary_password"] = raw
            data["note"] = (
                "Give this to the patient. It is not stored and cannot be shown "
                "again."
            )
        return data
