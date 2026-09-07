from rest_framework import serializers

from .models import (
    CashierSession, Invoice, InvoiceItem, Payment, PaymentMethod, Refund,
    Service, ServiceCategory, ServicePrice,
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


class CashierSessionSerializer(serializers.ModelSerializer):
    cashier_email = serializers.CharField(source="cashier.email", read_only=True)
    expected_total = serializers.SerializerMethodField()
    is_frozen = serializers.BooleanField(read_only=True)

    class Meta:
        model = CashierSession
        fields = ["id", "cashier", "cashier_email", "facility", "status", "opened_at",
                  "closed_at", "reconciled_at", "opening_float", "counted_total",
                  "variance_note", "expected_total", "is_frozen"]
        read_only_fields = ["id", "cashier", "status", "closed_at", "reconciled_at",
                            "counted_total", "expected_total", "is_frozen"]

    def get_expected_total(self, session) -> str:
        return str(session.expected_total())


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


class ReconcileSerializer(serializers.Serializer):
    counted_total = serializers.DecimalField(max_digits=12, decimal_places=2)
    variance_note = serializers.CharField(required=False, allow_blank=True, default="")


class VoidSerializer(serializers.Serializer):
    reason = serializers.CharField()
