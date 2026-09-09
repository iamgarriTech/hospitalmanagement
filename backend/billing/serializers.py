from decimal import Decimal

from django.db.models import Sum
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import (
    CashierSession,
    Invoice,
    InvoiceItem,
    Payment,
    PaymentMethod,
    Refund,
    Service,
    ServiceCategory,
    ServicePrice,
    SessionAdjustment,
    SessionCount,
    TillHandover,
)


class ServiceCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceCategory
        fields = ["id", "name", "display_order"]
        read_only_fields = ["id"]


class ServicePriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServicePrice
        fields = ["id", "service", "facility", "amount", "is_active", "updated_at"]
        read_only_fields = ["id", "updated_at"]


class ServiceSerializer(serializers.ModelSerializer):
    prices = ServicePriceSerializer(many=True, read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = Service
        fields = ["id", "category", "category_name", "name", "code", "is_active", "prices"]
        read_only_fields = ["id"]


class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentMethod
        fields = ["id", "name", "code", "requires_reference", "is_active"]
        read_only_fields = ["id"]


class InvoiceItemSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = InvoiceItem
        fields = ["id", "service", "description", "quantity", "unit_price", "amount",
                  "source_type", "source_id", "is_cancelled", "cancelled_reason",
                  "created_at"]
        read_only_fields = fields


class RefundSerializer(serializers.ModelSerializer):
    issued_by_email = serializers.CharField(source="issued_by.email", read_only=True)

    class Meta:
        model = Refund
        fields = ["id", "reference", "amount", "reason", "issued_by_email", "issued_at"]
        read_only_fields = fields


class PaymentSerializer(serializers.ModelSerializer):
    method_name = serializers.CharField(source="method.name", read_only=True)
    received_by_email = serializers.CharField(source="received_by.email", read_only=True)
    refunds = RefundSerializer(many=True, read_only=True)
    amount_refunded = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = Payment
        fields = ["id", "invoice", "receipt_number", "cashier_session", "method",
                  "method_name", "amount", "reference", "received_by_email",
                  "received_at", "reprint_count", "refunds", "amount_refunded"]
        read_only_fields = fields


class InvoiceSerializer(serializers.ModelSerializer):
    items = InvoiceItemSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    hospital_number = serializers.CharField(
        source="patient.hospital_number", read_only=True
    )
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    amount_paid = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    amount_refunded = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    balance = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    is_frozen = serializers.BooleanField(read_only=True)

    class Meta:
        model = Invoice
        fields = ["id", "invoice_number", "patient", "patient_name", "hospital_number",
                  "visit", "facility", "status", "discount_amount", "discount_reason",
                  "tax_amount", "subtotal", "total", "amount_paid", "amount_refunded",
                  "balance", "is_frozen", "items", "payments", "created_at",
                  "finalised_at", "voided_at", "void_reason"]
        read_only_fields = fields


class MethodVarianceSerializer(serializers.Serializer):
    """One row of the count sheet. Read-only; derived, never stored as such."""

    method = serializers.IntegerField()
    method_name = serializers.CharField()
    expected = serializers.DecimalField(max_digits=12, decimal_places=2)
    counted = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True
    )
    variance = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True
    )
    note = serializers.CharField(allow_blank=True)
    counted_at_all = serializers.BooleanField()


class SessionAdjustmentSerializer(serializers.ModelSerializer):
    raised_by_email = serializers.CharField(source="raised_by.email", read_only=True)
    method_name = serializers.CharField(source="method.name", read_only=True)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = SessionAdjustment
        fields = ["id", "session", "method", "method_name", "kind", "kind_display",
                  "amount", "reason", "raised_by", "raised_by_email", "raised_at"]
        read_only_fields = ["id", "session", "raised_by", "raised_at"]

    def validate_amount(self, amount):
        # The database refuses this too, but reaching it produces a 500 on what
        # is really a user putting nothing in the box.
        if amount == 0:
            raise serializers.ValidationError(
                "An adjustment of zero corrects nothing. State the amount the "
                "session was out by, negative for a shortage."
            )
        return amount

    def validate(self, data):
        amount, kind = data.get("amount"), data.get("kind")
        if kind == SessionAdjustment.SHORTAGE and amount > 0:
            raise serializers.ValidationError(
                {"amount": "A shortage is negative — money that is not there."}
            )
        if kind == SessionAdjustment.OVERAGE and amount < 0:
            raise serializers.ValidationError(
                {"amount": "An overage is positive — money that should not be there."}
            )
        return data


class TillHandoverSerializer(serializers.ModelSerializer):
    handed_by_email = serializers.CharField(source="handed_by.email", read_only=True)
    received_by_email = serializers.CharField(
        source="received_by.email", read_only=True
    )

    class Meta:
        model = TillHandover
        fields = ["id", "from_session", "to_session", "float_handed", "handed_by",
                  "handed_by_email", "received_by", "received_by_email", "handed_at",
                  "note"]
        read_only_fields = fields


class CashierSessionSerializer(serializers.ModelSerializer):
    cashier_email = serializers.CharField(source="cashier.email", read_only=True)
    expected_total = serializers.SerializerMethodField()
    is_frozen = serializers.BooleanField(read_only=True)
    variance_by_method = serializers.SerializerMethodField()
    unexplained = serializers.SerializerMethodField()
    net_variance = serializers.SerializerMethodField()
    adjustments = SessionAdjustmentSerializer(many=True, read_only=True)
    adjustment_total = serializers.SerializerMethodField()

    class Meta:
        model = CashierSession
        fields = ["id", "cashier", "cashier_email", "facility", "status", "opened_at",
                  "closed_at", "reconciled_at", "opening_float", "counted_total",
                  "variance_note", "expected_total", "is_frozen",
                  "variance_by_method", "unexplained", "net_variance",
                  "adjustments", "adjustment_total"]
        read_only_fields = ["id", "cashier", "status", "closed_at", "reconciled_at",
                            "counted_total", "expected_total", "is_frozen",
                            "variance_by_method", "unexplained", "net_variance",
                            "adjustments", "adjustment_total"]

    def get_expected_total(self, session) -> str:
        return str(session.expected_total())

    @extend_schema_field(MethodVarianceSerializer(many=True))
    def get_variance_by_method(self, session):
        return MethodVarianceSerializer(session.variance_by_method(), many=True).data

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_unexplained(self, session):
        """What stands between this session and a signature.

        Empty while the till is open: an uncounted method is not a problem on a
        drawer still taking money, and reporting one would put a warning on
        every open till in the building. The handover flow, which does count an
        open till, reads its refusal from the POST response rather than here.
        """
        if session.status == CashierSession.OPEN:
            return []
        return session.unexplained_variances()

    def get_net_variance(self, session) -> str:
        return str(session.net_variance)

    def get_adjustment_total(self, session) -> str:
        return str(
            session.adjustments.aggregate(total=Sum("amount"))["total"] or Decimal("0")
        )


class DiscountSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    reason = serializers.CharField()


class RecordPaymentSerializer(serializers.Serializer):
    invoice = serializers.IntegerField()
    method = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    reference = serializers.CharField(required=False, allow_blank=True, default="")
    idempotency_key = serializers.CharField(max_length=100)


class RefundRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    reason = serializers.CharField()


class CountEntrySerializer(serializers.Serializer):
    method = serializers.PrimaryKeyRelatedField(queryset=PaymentMethod.objects.all())
    counted = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    note = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )


class ReconcileSerializer(serializers.Serializer):
    """AC-140. A count per payment method, not one figure for the drawer."""

    counts = CountEntrySerializer(many=True, allow_empty=True)
    variance_note = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_counts(self, counts):
        seen = set()
        for entry in counts:
            if entry["method"].pk in seen:
                raise serializers.ValidationError(
                    f"{entry['method'].name} is counted twice."
                )
            seen.add(entry["method"].pk)
        return counts


class SessionCountSerializer(serializers.ModelSerializer):
    method_name = serializers.CharField(source="method.name", read_only=True)

    class Meta:
        model = SessionCount
        fields = ["id", "session", "method", "method_name", "counted", "note",
                  "counted_at"]
        read_only_fields = fields


class HandoverSerializer(serializers.Serializer):
    """AC-142. The incoming cashier is named by whoever is receiving the till."""

    counts = CountEntrySerializer(many=True, allow_empty=True)
    float_handed = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0
    )
    note = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )


class VoidSerializer(serializers.Serializer):
    reason = serializers.CharField()
