from rest_framework import serializers

from .models import (
    GoodsReceipt,
    GoodsReceiptLine,
    InventoryItem,
    ItemCategory,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequest,
    PurchaseRequestLine,
    StockAdjustment,
    StockLot,
    StockMovement,
    StockRecord,
    StockTransfer,
    Store,
    Supplier,
    SupplierInvoice,
)


class ItemCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemCategory
        fields = ["id", "name", "display_order"]
        read_only_fields = ["id"]


class InventoryItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = InventoryItem
        fields = ["id", "category", "category_name", "name", "code", "unit_of_issue",
                  "default_reorder_level", "is_controlled", "tracks_expiry",
                  "is_active"]
        read_only_fields = ["id"]


class StoreSerializer(serializers.ModelSerializer):
    facility_name = serializers.CharField(source="facility.name", read_only=True)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    ward_name = serializers.CharField(source="ward.name", read_only=True)

    class Meta:
        model = Store
        fields = ["id", "facility", "facility_name", "name", "code", "kind",
                  "kind_display", "ward", "ward_name",
                  "adjustment_authorisation_limit", "expiry_horizon_days",
                  "is_active"]
        read_only_fields = ["id"]


class StockLotSerializer(serializers.ModelSerializer):
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = StockLot
        fields = ["id", "record", "lot_number", "expiry_date", "quantity_on_hand",
                  "unit_cost", "received_at", "is_expired"]
        read_only_fields = fields


class StockRecordSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.name", read_only=True)
    item_code = serializers.CharField(source="item.code", read_only=True)
    unit_of_issue = serializers.CharField(source="item.unit_of_issue", read_only=True)
    is_controlled = serializers.BooleanField(source="item.is_controlled", read_only=True)
    tracks_expiry = serializers.BooleanField(source="item.tracks_expiry", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    on_hand = serializers.SerializerMethodField()
    usable_on_hand = serializers.SerializerMethodField()
    is_low = serializers.BooleanField(read_only=True)
    lots = StockLotSerializer(many=True, read_only=True)

    class Meta:
        model = StockRecord
        fields = ["id", "store", "store_name", "item", "item_name", "item_code",
                  "unit_of_issue", "is_controlled", "tracks_expiry", "reorder_level",
                  "is_active", "on_hand", "usable_on_hand", "is_low", "lots"]
        read_only_fields = ["id", "on_hand", "usable_on_hand", "is_low", "lots"]

    def get_on_hand(self, record) -> int:
        return record.on_hand()

    def get_usable_on_hand(self, record) -> int:
        return record.usable_on_hand()


class StockMovementSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="lot.record.item.name", read_only=True)
    store_name = serializers.CharField(source="lot.record.store.name", read_only=True)
    lot_number = serializers.CharField(source="lot.lot_number", read_only=True)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    recorded_by_email = serializers.CharField(
        source="recorded_by.email", read_only=True
    )

    class Meta:
        model = StockMovement
        fields = ["id", "lot", "lot_number", "item_name", "store_name", "kind",
                  "kind_display", "quantity_delta", "quantity_after", "issued_to",
                  "reason", "transfer", "adjustment", "recorded_by",
                  "recorded_by_email", "recorded_at"]
        read_only_fields = fields


class ReceiveSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)
    lot_number = serializers.CharField(max_length=60, required=False, allow_blank=True,
                                       default="")
    expiry_date = serializers.DateField(required=False, allow_null=True, default=None)
    unit_cost = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0,
                                         required=False, default=0)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True,
                                   default="")


class IssueSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)
    issued_to = serializers.CharField(max_length=160, required=False, allow_blank=True,
                                      default="")
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True,
                                   default="")


class StockTransferSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.name", read_only=True)
    from_store_name = serializers.CharField(source="from_store.name", read_only=True)
    to_store_name = serializers.CharField(source="to_store.name", read_only=True)
    moved_by_email = serializers.CharField(source="moved_by.email", read_only=True)

    class Meta:
        model = StockTransfer
        fields = ["id", "item", "item_name", "from_store", "from_store_name",
                  "to_store", "to_store_name", "quantity", "reason", "moved_by",
                  "moved_by_email", "moved_at"]
        read_only_fields = ["id", "moved_by", "moved_at"]


class StockAdjustmentSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="lot.record.item.name", read_only=True)
    store_name = serializers.CharField(source="lot.record.store.name", read_only=True)
    lot_number = serializers.CharField(source="lot.lot_number", read_only=True)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    raised_by_email = serializers.CharField(source="raised_by.email", read_only=True)
    authorised_by_email = serializers.CharField(
        source="authorised_by.email", read_only=True
    )

    class Meta:
        model = StockAdjustment
        fields = ["id", "lot", "lot_number", "item_name", "store_name", "kind",
                  "kind_display", "quantity_delta", "value", "reason", "raised_by",
                  "raised_by_email", "authorised_by", "authorised_by_email",
                  "raised_at"]
        read_only_fields = ["id", "value", "raised_by", "raised_at"]

    def validate_quantity_delta(self, delta):
        if delta == 0:
            raise serializers.ValidationError("An adjustment of zero corrects nothing.")
        return delta


class LowStockSerializer(serializers.Serializer):
    """One line of the reorder list. AC-149."""

    record = serializers.IntegerField()
    store = serializers.IntegerField()
    store_name = serializers.CharField()
    item = serializers.IntegerField()
    item_name = serializers.CharField()
    unit_of_issue = serializers.CharField()
    reorder_level = serializers.IntegerField()
    usable_on_hand = serializers.IntegerField()
    on_hand = serializers.IntegerField()


class ExpiringLotSerializer(serializers.Serializer):
    lot = serializers.IntegerField()
    lot_number = serializers.CharField()
    store = serializers.IntegerField()
    store_name = serializers.CharField()
    item_name = serializers.CharField()
    quantity_on_hand = serializers.IntegerField()
    expiry_date = serializers.DateField()
    days_left = serializers.IntegerField()
    is_expired = serializers.BooleanField()


class StockAlertsSerializer(serializers.Serializer):
    low = LowStockSerializer(many=True)
    expiring = ExpiringLotSerializer(many=True)


# --- procurement ------------------------------------------------------------

class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name", "code", "contact_name", "phone", "email", "address",
                  "payment_terms_days", "is_approved", "approval_note"]
        read_only_fields = ["id"]


class PurchaseRequestLineSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.name", read_only=True)
    unit_of_issue = serializers.CharField(source="item.unit_of_issue", read_only=True)

    class Meta:
        model = PurchaseRequestLine
        fields = ["id", "item", "item_name", "unit_of_issue", "quantity",
                  "estimated_unit_cost", "note"]
        read_only_fields = ["id"]


class PurchaseRequestSerializer(serializers.ModelSerializer):
    lines = PurchaseRequestLineSerializer(many=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    requested_by_email = serializers.CharField(
        source="requested_by.email", read_only=True
    )
    decided_by_email = serializers.CharField(source="decided_by.email", read_only=True)
    estimated_value = serializers.SerializerMethodField()
    needs_approval = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseRequest
        fields = ["id", "reference", "store", "store_name", "justification", "status",
                  "status_display", "requested_by", "requested_by_email",
                  "requested_at", "submitted_at", "decided_by", "decided_by_email",
                  "decided_at", "decision_note", "lines", "estimated_value",
                  "needs_approval"]
        read_only_fields = ["id", "reference", "status", "status_display",
                            "requested_by", "requested_at", "submitted_at",
                            "decided_by", "decided_at", "decision_note",
                            "estimated_value", "needs_approval"]

    def get_estimated_value(self, request) -> str:
        return str(request.estimated_value())

    def get_needs_approval(self, request) -> bool:
        return request.needs_approval()


class DecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    note = serializers.CharField(required=False, allow_blank=True, default="")


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.name", read_only=True)
    item_code = serializers.CharField(source="item.code", read_only=True)
    unit_of_issue = serializers.CharField(source="item.unit_of_issue", read_only=True)
    tracks_expiry = serializers.BooleanField(source="item.tracks_expiry", read_only=True)
    outstanding = serializers.IntegerField(read_only=True)
    is_complete = serializers.BooleanField(read_only=True)

    class Meta:
        model = PurchaseOrderLine
        fields = ["id", "item", "item_name", "item_code", "unit_of_issue",
                  "tracks_expiry", "quantity_ordered", "quantity_received",
                  "unit_cost", "outstanding", "is_complete"]
        read_only_fields = fields


class PurchaseOrderSerializer(serializers.ModelSerializer):
    lines = PurchaseOrderLineSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    request_reference = serializers.CharField(source="request.reference", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    raised_by_email = serializers.CharField(source="raised_by.email", read_only=True)
    total_ordered = serializers.SerializerMethodField()
    total_received_value = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = ["id", "reference", "request", "request_reference", "supplier",
                  "supplier_name", "store", "store_name", "expected_date", "status",
                  "status_display", "note", "raised_by", "raised_by_email",
                  "raised_at", "cancelled_at", "cancellation_reason", "lines",
                  "total_ordered", "total_received_value"]
        read_only_fields = fields

    def get_total_ordered(self, order) -> str:
        return str(order.total_ordered())

    def get_total_received_value(self, order) -> str:
        return str(order.total_received_value())


class RaiseOrderSerializer(serializers.Serializer):
    """AC-154. The agreed price per line, not the requester's estimate."""

    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.all())
    expected_date = serializers.DateField(required=False, allow_null=True, default=None)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    prices = serializers.DictField(
        child=serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0),
        help_text="Item id to agreed unit cost.",
    )


class GoodsReceiptLineSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(
        source="order_line.item.name", read_only=True
    )
    movement_balance = serializers.IntegerField(
        source="movement.quantity_after", read_only=True
    )

    class Meta:
        model = GoodsReceiptLine
        fields = ["id", "order_line", "item_name", "quantity", "lot_number",
                  "expiry_date", "movement", "movement_balance"]
        read_only_fields = fields


class GoodsReceiptSerializer(serializers.ModelSerializer):
    lines = GoodsReceiptLineSerializer(many=True, read_only=True)
    order_reference = serializers.CharField(source="order.reference", read_only=True)
    received_by_email = serializers.CharField(
        source="received_by.email", read_only=True
    )
    total_value = serializers.SerializerMethodField()

    class Meta:
        model = GoodsReceipt
        fields = ["id", "reference", "order", "order_reference", "delivery_note",
                  "received_by", "received_by_email", "received_at", "note", "lines",
                  "total_value"]
        read_only_fields = fields

    def get_total_value(self, receipt) -> str:
        return str(receipt.total_value())


class DeliveryLineSerializer(serializers.Serializer):
    order_line = serializers.PrimaryKeyRelatedField(
        queryset=PurchaseOrderLine.objects.all()
    )
    quantity = serializers.IntegerField(min_value=1)
    lot_number = serializers.CharField(max_length=60, required=False, allow_blank=True,
                                       default="")
    expiry_date = serializers.DateField(required=False, allow_null=True, default=None)


class ReceiveGoodsSerializer(serializers.Serializer):
    deliveries = DeliveryLineSerializer(many=True, allow_empty=False)
    delivery_note = serializers.CharField(max_length=60, required=False,
                                          allow_blank=True, default="")
    note = serializers.CharField(required=False, allow_blank=True, default="")


class SupplierInvoiceSerializer(serializers.ModelSerializer):
    order_reference = serializers.CharField(source="order.reference", read_only=True)
    supplier_name = serializers.CharField(source="order.supplier.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    recorded_by_email = serializers.CharField(
        source="recorded_by.email", read_only=True
    )
    approved_by_email = serializers.CharField(
        source="approved_by.email", read_only=True
    )
    total_ordered = serializers.SerializerMethodField()

    class Meta:
        model = SupplierInvoice
        fields = ["id", "order", "order_reference", "supplier_name",
                  "supplier_reference", "invoice_date", "amount", "status",
                  "status_display", "matched_at", "matched_value", "discrepancies",
                  "query_note", "approved_by", "approved_by_email", "approved_at",
                  "recorded_by", "recorded_by_email", "recorded_at", "total_ordered"]
        read_only_fields = ["id", "status", "status_display", "matched_at",
                            "matched_value", "discrepancies", "approved_by",
                            "approved_at", "recorded_by", "recorded_at",
                            "total_ordered"]

    def get_total_ordered(self, invoice) -> str:
        return str(invoice.order.total_ordered())


class ApproveInvoiceSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="")


class CancelOrderSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)
