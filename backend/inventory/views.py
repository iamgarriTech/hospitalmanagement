"""Stores and stock over HTTP.

Stock movement is driven by actions — `receive`, `issue` — rather than by
PATCHing a quantity. A writable `quantity_on_hand` would be a read-then-write
from the client, which is precisely the race AC-146 forbids, and it would
produce a balance nobody could trace to an act.

`StockMovementViewSet` is read-only with no write verb at all. A movement is
the record of something that happened; an endpoint that could edit one would be
an endpoint that rewrites the ledger.
"""

from django.core.exceptions import ValidationError
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from audit.models import AuditEvent
from core.permissions import FacilityScopedMixin, HasPermission
from facilities.models import Facility

from . import procurement
from . import stock as stock_service
from .models import (
    GoodsReceipt,
    InventoryItem,
    ItemCategory,
    PurchaseOrder,
    PurchaseRequest,
    StockAdjustment,
    StockLot,
    StockMovement,
    StockRecord,
    StockTransfer,
    Store,
    Supplier,
    SupplierInvoice,
)
from .serializers import (
    ApproveInvoiceSerializer,
    CancelOrderSerializer,
    DecisionSerializer,
    GoodsReceiptSerializer,
    InventoryItemSerializer,
    IssueSerializer,
    ItemCategorySerializer,
    PurchaseOrderSerializer,
    PurchaseRequestSerializer,
    RaiseOrderSerializer,
    ReceiveGoodsSerializer,
    ReceiveSerializer,
    StockAdjustmentSerializer,
    StockAlertsSerializer,
    StockMovementSerializer,
    StockRecordSerializer,
    StockTransferSerializer,
    StoreSerializer,
    SupplierInvoiceSerializer,
    SupplierSerializer,
)


class ItemCategoryViewSet(viewsets.ModelViewSet):
    queryset = ItemCategory.objects.all()
    serializer_class = ItemCategorySerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "inventory.view_itemcategory",
        "retrieve": "inventory.view_itemcategory",
        "create": "inventory.add_itemcategory",
        "partial_update": "inventory.change_itemcategory",
    }


class InventoryItemViewSet(viewsets.ModelViewSet):
    """AC-143. The catalogue, administrable at runtime."""

    queryset = InventoryItem.objects.select_related("category")
    serializer_class = InventoryItemSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "inventory.view_inventoryitem",
        "retrieve": "inventory.view_inventoryitem",
        "create": "inventory.add_inventoryitem",
        "partial_update": "inventory.change_inventoryitem",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params
        if params.get("category"):
            queryset = queryset.filter(category_id=params["category"])
        if params.get("active") == "true":
            queryset = queryset.filter(is_active=True)
        if term := params.get("q"):
            queryset = queryset.filter(name__icontains=term)
        return queryset


class StoreViewSet(FacilityScopedMixin, viewsets.ModelViewSet):
    """AC-144. Stores are per facility, and so is who may see them."""

    queryset = Store.objects.none()
    serializer_class = StoreSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "inventory.view_store",
        "retrieve": "inventory.view_store",
        "create": "inventory.add_store",
        "partial_update": "inventory.change_store",
    }

    def get_queryset(self):
        queryset = self._scope(
            Store.objects.select_related("facility", "ward")
        )
        params = self.request.query_params
        if params.get("facility"):
            queryset = queryset.filter(facility_id=params["facility"])
        if params.get("kind"):
            queryset = queryset.filter(kind=params["kind"])
        return queryset

    def facility_for_permission(self, request):
        if self.action == "create":
            return Facility.objects.filter(pk=request.data.get("facility")).first()
        return None


class StockRecordViewSet(FacilityScopedMixin, viewsets.ModelViewSet):
    """What a store carries, and the two acts that change it."""

    queryset = StockRecord.objects.none()
    serializer_class = StockRecordSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "inventory.view_stockrecord",
        "retrieve": "inventory.view_stockrecord",
        "create": "inventory.add_stockrecord",
        "partial_update": "inventory.change_stockrecord",
        "receive": "inventory.receive_stock",
        "issue": "inventory.issue_stock",
        "movements": "inventory.view_stockmovement",
    }

    def get_queryset(self):
        queryset = self._scope(
            StockRecord.objects.select_related(
                "store", "store__facility", "item", "item__category"
            ).prefetch_related("lots"),
            field="store__facility_id",
        )
        params = self.request.query_params
        if params.get("store"):
            queryset = queryset.filter(store_id=params["store"])
        if params.get("item"):
            queryset = queryset.filter(item_id=params["item"])
        if params.get("low") == "true":
            # Evaluated in Python because "low" depends on usable stock, which
            # excludes expired lots — expressing that in SQL would need a
            # correlated aggregate for a list a storekeeper reads once a day.
            return [record for record in queryset if record.is_low]
        return queryset

    def facility_for_permission(self, request):
        if self.action == "create":
            store = Store.objects.filter(pk=request.data.get("store")).first()
            return store.facility if store else None
        return None

    @extend_schema(request=ReceiveSerializer, responses={201: StockRecordSerializer},
                   summary="Book a delivery into this store")
    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        record = self.get_object()
        serializer = ReceiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            movement = stock_service.receive(
                record=record, quantity=data["quantity"], actor=request.user,
                lot_number=data["lot_number"], expiry_date=data["expiry_date"],
                unit_cost=data["unit_cost"], reason=data["reason"],
            )
        except ValidationError as refusal:
            return Response({"detail": refusal.messages[0]},
                            status=http.HTTP_400_BAD_REQUEST)

        AuditEvent.record(
            action="stock.received", actor=request.user, resource=movement,
            facility=record.store.facility,
            after={"store": record.store.code, "item": record.item.code,
                   "lot": movement.lot.lot_number,
                   "quantity": str(data["quantity"]),
                   "balance_after": str(movement.quantity_after)},
            reason=data["reason"], request=request,
        )
        return Response(self.get_serializer(record).data, status=http.HTTP_201_CREATED)

    @extend_schema(request=IssueSerializer, responses={200: StockRecordSerializer},
                   summary="Issue stock out of this store, soonest expiry first")
    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        record = self.get_object()
        serializer = IssueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            movements = stock_service.issue(
                record=record, quantity=data["quantity"], actor=request.user,
                issued_to=data["issued_to"], reason=data["reason"],
            )
        except ValidationError as refusal:
            return Response({"detail": refusal.messages[0]},
                            status=http.HTTP_409_CONFLICT)

        AuditEvent.record(
            action="stock.issued", actor=request.user, resource=movements[0],
            facility=record.store.facility,
            after={"store": record.store.code, "item": record.item.code,
                   "quantity": str(data["quantity"]),
                   "issued_to": data["issued_to"],
                   "lots": [m.lot.lot_number for m in movements],
                   "balance_after": str(record.on_hand())},
            reason=data["reason"], request=request,
        )
        return Response(self.get_serializer(record).data)

    @extend_schema(responses={200: StockMovementSerializer(many=True)},
                   summary="This record's ledger, newest first")
    @action(detail=True, methods=["get"])
    def movements(self, request, pk=None):
        record = self.get_object()
        movements = StockMovement.objects.filter(
            lot__record=record
        ).select_related("lot", "lot__record__item", "lot__record__store",
                         "recorded_by")
        return Response(StockMovementSerializer(movements, many=True).data)


class StockMovementViewSet(FacilityScopedMixin, viewsets.ReadOnlyModelViewSet):
    """The ledger. Read-only, with no write verb of any kind. AC-145."""

    queryset = StockMovement.objects.none()
    serializer_class = StockMovementSerializer
    permission_classes = [HasPermission]
    required_permissions = {
        "list": "inventory.view_stockmovement",
        "retrieve": "inventory.view_stockmovement",
    }

    def get_queryset(self):
        queryset = self._scope(
            StockMovement.objects.select_related(
                "lot", "lot__record__item", "lot__record__store", "recorded_by"
            ),
            field="lot__record__store__facility_id",
        )
        params = self.request.query_params
        if params.get("store"):
            queryset = queryset.filter(lot__record__store_id=params["store"])
        if params.get("item"):
            queryset = queryset.filter(lot__record__item_id=params["item"])
        if params.get("kind"):
            queryset = queryset.filter(kind__in=params["kind"].split(","))
        return queryset


class StockTransferViewSet(FacilityScopedMixin, viewsets.ModelViewSet):
    """AC-145. Creating one performs the move; there is nothing to PATCH."""

    queryset = StockTransfer.objects.none()
    serializer_class = StockTransferSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "head", "options"]
    required_permissions = {
        "list": "inventory.view_stocktransfer",
        "retrieve": "inventory.view_stocktransfer",
        "create": "inventory.transfer_stock",
    }

    def get_queryset(self):
        return self._scope(
            StockTransfer.objects.select_related(
                "item", "from_store", "to_store", "moved_by"
            ).prefetch_related("movements"),
            field="from_store__facility_id",
        )

    def facility_for_permission(self, request):
        if self.action == "create":
            store = Store.objects.filter(pk=request.data.get("from_store")).first()
            return store.facility if store else None
        return None

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            record = stock_service.transfer(
                item=data["item"], from_store=data["from_store"],
                to_store=data["to_store"], quantity=data["quantity"],
                actor=request.user, reason=data.get("reason", ""),
            )
        except ValidationError as refusal:
            return Response({"detail": refusal.messages[0]},
                            status=http.HTTP_409_CONFLICT)

        AuditEvent.record(
            action="stock.transferred", actor=request.user, resource=record,
            facility=record.from_store.facility,
            after={"item": record.item.code, "from": record.from_store.code,
                   "to": record.to_store.code, "quantity": str(record.quantity)},
            reason=record.reason, request=request,
        )
        return Response(self.get_serializer(record).data, status=http.HTTP_201_CREATED)


class StockAdjustmentViewSet(FacilityScopedMixin, viewsets.ModelViewSet):
    """AC-147. Created, never edited: a correction to a correction is another one."""

    queryset = StockAdjustment.objects.none()
    serializer_class = StockAdjustmentSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "head", "options"]
    required_permissions = {
        "list": "inventory.view_stockadjustment",
        "retrieve": "inventory.view_stockadjustment",
        "create": "inventory.adjust_stock",
    }

    def get_queryset(self):
        return self._scope(
            StockAdjustment.objects.select_related(
                "lot__record__item", "lot__record__store", "raised_by",
                "authorised_by",
            ),
            field="lot__record__store__facility_id",
        )

    def facility_for_permission(self, request):
        if self.action == "create":
            lot = StockLot.objects.filter(pk=request.data.get("lot")).first()
            return lot.record.store.facility if lot else None
        return None

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        authoriser = data.get("authorised_by")

        # The second signature has to come from somebody who holds the verb,
        # otherwise it is a name in a box rather than an authorisation.
        if authoriser is not None:
            facility = data["lot"].record.store.facility
            permitted = authoriser.facilities_for(
                "inventory.authorise_stock_adjustment"
            )
            if not ({None, facility.pk} & set(permitted)):
                return Response(
                    {"authorised_by": [
                        f"{authoriser.email} cannot authorise stock adjustments at "
                        f"{facility.name}."
                    ]},
                    status=http.HTTP_400_BAD_REQUEST,
                )

        try:
            record = stock_service.adjust(
                lot=data["lot"], quantity_delta=data["quantity_delta"],
                kind=data["kind"], reason=data["reason"], actor=request.user,
                authorised_by=authoriser,
            )
        except ValidationError as refusal:
            return Response({"detail": refusal.messages[0]},
                            status=http.HTTP_400_BAD_REQUEST)

        AuditEvent.record(
            action="stock.adjusted", actor=request.user, resource=record,
            facility=record.lot.record.store.facility,
            after={"store": record.lot.record.store.code,
                   "item": record.lot.record.item.code,
                   "lot": record.lot.lot_number,
                   "delta": str(record.quantity_delta),
                   "value": str(record.value),
                   "authorised_by": (
                       record.authorised_by.email if record.authorised_by else None
                   ),
                   "balance_after": str(record.lot.quantity_on_hand)},
            reason=record.reason, request=request,
        )
        return Response(self.get_serializer(record).data, status=http.HTTP_201_CREATED)


class StockAlertViewSet(FacilityScopedMixin, viewsets.ViewSet):
    """AC-149. What a storekeeper looks at first thing in the morning."""

    permission_classes = [HasPermission]
    required_permissions = {"list": "inventory.view_stockrecord"}

    @extend_schema(
        parameters=[
            OpenApiParameter("store", int, description="One store, rather than all."),
            OpenApiParameter("facility", int),
            OpenApiParameter(
                "horizon_days", int,
                description="Override each store's own expiry horizon.",
            ),
        ],
        responses={200: StockAlertsSerializer},
        summary="Low stock and expiring stock, per store",
    )
    def list(self, request):
        permitted = set(request.user.facilities_for("inventory.view_stockrecord"))
        stores = Store.objects.filter(is_active=True)
        if None not in permitted and not request.user.is_superuser:
            stores = stores.filter(
                facility_id__in=[f for f in permitted if f is not None]
            )
        if request.query_params.get("store"):
            stores = stores.filter(pk=request.query_params["store"])
        if request.query_params.get("facility"):
            stores = stores.filter(facility_id=request.query_params["facility"])

        horizon = request.query_params.get("horizon_days")
        horizon = int(horizon) if horizon else None
        store_ids = list(stores.values_list("pk", flat=True))

        low = [
            {
                "record": record.pk,
                "store": record.store_id,
                "store_name": record.store.name,
                "item": record.item_id,
                "item_name": record.item.name,
                "unit_of_issue": record.item.unit_of_issue,
                "reorder_level": record.reorder_level,
                "usable_on_hand": record.usable_on_hand(),
                "on_hand": record.on_hand(),
            }
            for record in stock_service.low_stock()
            if record.store_id in store_ids
        ]

        today = timezone.localdate()
        expiring = [
            {
                "lot": lot.pk,
                "lot_number": lot.lot_number,
                "store": lot.record.store_id,
                "store_name": lot.record.store.name,
                "item_name": lot.record.item.name,
                "quantity_on_hand": lot.quantity_on_hand,
                "expiry_date": lot.expiry_date,
                "days_left": (lot.expiry_date - today).days,
                "is_expired": lot.is_expired,
            }
            for lot in stock_service.expiring(horizon_days=horizon)
            if lot.record.store_id in store_ids
        ]
        return Response({"low": low, "expiring": expiring})


# --- procurement ------------------------------------------------------------

class SupplierViewSet(viewsets.ModelViewSet):
    """AC-151. Not facility-scoped: a hospital group buys as one buyer."""

    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "inventory.view_supplier",
        "retrieve": "inventory.view_supplier",
        "create": "inventory.add_supplier",
        "partial_update": "inventory.change_supplier",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("approved") == "true":
            queryset = queryset.filter(is_approved=True)
        return queryset

    def perform_update(self, serializer):
        before = {
            "is_approved": serializer.instance.is_approved,
            "note": serializer.instance.approval_note,
        }
        supplier = serializer.save()
        if before["is_approved"] != supplier.is_approved:
            # Worth its own audit row: suspending a supplier stops new orders
            # across every branch, and somebody will ask who did it and why.
            AuditEvent.record(
                action="supplier.approval_changed", actor=self.request.user,
                resource=supplier,
                before=before,
                after={"is_approved": supplier.is_approved,
                       "note": supplier.approval_note},
                reason=supplier.approval_note, request=self.request,
            )


class PurchaseRequestViewSet(FacilityScopedMixin, viewsets.ModelViewSet):
    """AC-152, AC-153. Asking is a create; deciding is its own action.

    A writable `status` would let a client set `approved` on their own request,
    which is the one thing AC-153 forbids.
    """

    queryset = PurchaseRequest.objects.none()
    serializer_class = PurchaseRequestSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "head", "options"]
    required_permissions = {
        "list": "inventory.view_purchaserequest",
        "retrieve": "inventory.view_purchaserequest",
        "create": "inventory.add_purchaserequest",
        "submit": "inventory.change_purchaserequest",
        "decide": "inventory.approve_purchase_request",
    }

    def get_queryset(self):
        queryset = self._scope(
            PurchaseRequest.objects.select_related(
                "store", "store__facility", "requested_by", "decided_by"
            ).prefetch_related("lines__item"),
            field="store__facility_id",
        )
        params = self.request.query_params
        if params.get("status"):
            queryset = queryset.filter(status__in=params["status"].split(","))
        if params.get("store"):
            queryset = queryset.filter(store_id=params["store"])
        return queryset

    def facility_for_permission(self, request):
        if self.action == "create":
            store = Store.objects.filter(pk=request.data.get("store")).first()
            return store.facility if store else None
        return None

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            record = procurement.new_request(
                store=data["store"],
                justification=data["justification"],
                actor=request.user,
                lines=[
                    {"item": line["item"], "quantity": line["quantity"],
                     "cost": line.get("estimated_unit_cost", 0),
                     "note": line.get("note", "")}
                    for line in data["lines"]
                ],
            )
        except ValidationError as refusal:
            return Response({"detail": refusal.messages[0]},
                            status=http.HTTP_400_BAD_REQUEST)

        AuditEvent.record(
            action="purchase_request.raised", actor=request.user, resource=record,
            facility=record.store.facility,
            after={"reference": record.reference, "store": record.store.code,
                   "value": str(record.estimated_value()),
                   "needs_approval": record.needs_approval()},
            reason=record.justification, request=request,
        )
        return Response(self.get_serializer(record).data, status=http.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: PurchaseRequestSerializer},
                   summary="Send the request for a decision")
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        record = self.get_object()
        try:
            procurement.submit_request(record, actor=request.user)
        except ValidationError as refusal:
            return Response({"detail": refusal.messages[0]},
                            status=http.HTTP_409_CONFLICT)
        AuditEvent.record(
            action="purchase_request.submitted", actor=request.user, resource=record,
            facility=record.store.facility,
            after={"reference": record.reference,
                   "value": str(record.estimated_value())},
            request=request,
        )
        return Response(self.get_serializer(record).data)

    @extend_schema(request=DecisionSerializer,
                   responses={200: PurchaseRequestSerializer},
                   summary="Approve or reject the request")
    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        record = self.get_object()
        serializer = DecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            procurement.decide_request(
                record, approve=serializer.validated_data["approve"],
                actor=request.user, note=serializer.validated_data["note"],
            )
        except ValidationError as refusal:
            return Response({"detail": refusal.messages[0]},
                            status=http.HTTP_400_BAD_REQUEST)

        AuditEvent.record(
            action="purchase_request.decided", actor=request.user, resource=record,
            facility=record.store.facility,
            after={"reference": record.reference, "status": record.status,
                   "value": str(record.estimated_value())},
            reason=record.decision_note, request=request,
        )
        return Response(self.get_serializer(record).data)


class PurchaseOrderViewSet(FacilityScopedMixin, viewsets.ReadOnlyModelViewSet):
    """AC-154 to AC-156. Orders are raised from a request, not posted directly.

    Read-only as a collection, with the acts as detail routes: raising one is a
    decision about an approved request, and receiving goods has to create the
    stock movement that shelves them.
    """

    queryset = PurchaseOrder.objects.none()
    serializer_class = PurchaseOrderSerializer
    permission_classes = [HasPermission]
    required_permissions = {
        "list": "inventory.view_purchaseorder",
        "retrieve": "inventory.view_purchaseorder",
        "receive": "inventory.receive_goods",
        "cancel": "inventory.raise_purchase_order",
        "receipts": "inventory.view_goodsreceipt",
    }

    def get_queryset(self):
        queryset = self._scope(
            PurchaseOrder.objects.select_related(
                "supplier", "store", "store__facility", "request", "raised_by"
            ).prefetch_related("lines__item"),
            field="store__facility_id",
        )
        params = self.request.query_params
        if params.get("status"):
            queryset = queryset.filter(status__in=params["status"].split(","))
        if params.get("supplier"):
            queryset = queryset.filter(supplier_id=params["supplier"])
        if params.get("store"):
            queryset = queryset.filter(store_id=params["store"])
        if params.get("outstanding") == "true":
            queryset = queryset.filter(
                status__in=[PurchaseOrder.OPEN, PurchaseOrder.PARTIALLY_RECEIVED]
            )
        return queryset

    @extend_schema(request=ReceiveGoodsSerializer,
                   responses={201: GoodsReceiptSerializer},
                   summary="Record a delivery and shelve it")
    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        order = self.get_object()
        serializer = ReceiveGoodsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            receipt = procurement.receive_goods(
                order=order,
                deliveries=[
                    {"order_line": line["order_line"], "quantity": line["quantity"],
                     "lot_number": line["lot_number"],
                     "expiry_date": line["expiry_date"]}
                    for line in data["deliveries"]
                ],
                actor=request.user,
                delivery_note=data["delivery_note"],
                note=data["note"],
            )
        except ValidationError as refusal:
            return Response({"detail": refusal.messages[0]},
                            status=http.HTTP_400_BAD_REQUEST)

        order.refresh_from_db()
        AuditEvent.record(
            action="goods.received", actor=request.user, resource=receipt,
            facility=order.store.facility,
            after={"receipt": receipt.reference, "order": order.reference,
                   "store": order.store.code,
                   "order_status": order.status,
                   "value": str(receipt.total_value()),
                   "lines": [
                       {"item": line.order_line.item.code,
                        "quantity": str(line.quantity),
                        "lot": line.lot_number}
                       for line in receipt.lines.all()
                   ]},
            reason=receipt.delivery_note, request=request,
        )
        return Response(GoodsReceiptSerializer(receipt).data,
                        status=http.HTTP_201_CREATED)

    @extend_schema(request=CancelOrderSerializer,
                   responses={200: PurchaseOrderSerializer},
                   summary="Cancel an order nothing has arrived against")
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        serializer = CancelOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            procurement.cancel_order(
                order, actor=request.user,
                reason=serializer.validated_data["reason"],
            )
        except ValidationError as refusal:
            return Response({"detail": refusal.messages[0]},
                            status=http.HTTP_409_CONFLICT)
        AuditEvent.record(
            action="purchase_order.cancelled", actor=request.user, resource=order,
            facility=order.store.facility,
            after={"reference": order.reference},
            reason=order.cancellation_reason, request=request,
        )
        return Response(self.get_serializer(order).data)

    @extend_schema(responses={200: GoodsReceiptSerializer(many=True)},
                   summary="Deliveries against this order")
    @action(detail=True, methods=["get"])
    def receipts(self, request, pk=None):
        order = self.get_object()
        receipts = order.receipts.select_related("received_by").prefetch_related(
            "lines__order_line__item", "lines__movement"
        )
        return Response(GoodsReceiptSerializer(receipts, many=True).data)


class RaiseOrderView(viewsets.ViewSet):
    """Raising an order against an approved request.

    A route of its own rather than a POST to /purchase-orders/, because the
    order's shape comes from the request — the client supplies the supplier and
    the agreed prices, not the lines.
    """

    permission_classes = [HasPermission]
    required_permissions = {"create": "inventory.raise_purchase_order"}

    @extend_schema(request=RaiseOrderSerializer,
                   responses={201: PurchaseOrderSerializer},
                   summary="Raise an order from an approved request")
    def create(self, request):
        record = PurchaseRequest.objects.filter(
            pk=request.data.get("request")
        ).select_related("store__facility").first()
        if record is None:
            return Response({"request": ["No such purchase request."]},
                            status=http.HTTP_400_BAD_REQUEST)

        permitted = set(request.user.facilities_for("inventory.raise_purchase_order"))
        if not request.user.is_superuser and None not in permitted:
            if record.store.facility_id not in permitted:
                # 404 rather than 403: an out-of-scope record must not be
                # confirmed to exist. Guarantee 1.
                return Response({"detail": "Not found."},
                                status=http.HTTP_404_NOT_FOUND)

        serializer = RaiseOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            order = procurement.raise_order(
                request=record, supplier=data["supplier"], actor=request.user,
                prices={int(key): value for key, value in data["prices"].items()},
                expected_date=data["expected_date"], note=data["note"],
            )
        except ValidationError as refusal:
            return Response({"detail": refusal.messages[0]},
                            status=http.HTTP_400_BAD_REQUEST)

        AuditEvent.record(
            action="purchase_order.raised", actor=request.user, resource=order,
            facility=order.store.facility,
            after={"reference": order.reference, "request": record.reference,
                   "supplier": order.supplier.name,
                   "store": order.store.code,
                   "total": str(order.total_ordered())},
            reason=order.note, request=request,
        )
        return Response(PurchaseOrderSerializer(order).data,
                        status=http.HTTP_201_CREATED)


class GoodsReceiptViewSet(FacilityScopedMixin, viewsets.ReadOnlyModelViewSet):
    """Read-only. A receipt is created by shelving goods, never on its own."""

    queryset = GoodsReceipt.objects.none()
    serializer_class = GoodsReceiptSerializer
    permission_classes = [HasPermission]
    required_permissions = {
        "list": "inventory.view_goodsreceipt",
        "retrieve": "inventory.view_goodsreceipt",
    }

    def get_queryset(self):
        return self._scope(
            GoodsReceipt.objects.select_related(
                "order__supplier", "order__store", "received_by"
            ).prefetch_related("lines__order_line__item", "lines__movement"),
            field="order__store__facility_id",
        )


class SupplierInvoiceViewSet(FacilityScopedMixin, viewsets.ModelViewSet):
    """AC-157. Entering, matching and approving are three acts by two people."""

    queryset = SupplierInvoice.objects.none()
    serializer_class = SupplierInvoiceSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "head", "options"]
    required_permissions = {
        "list": "inventory.view_supplierinvoice",
        "retrieve": "inventory.view_supplierinvoice",
        "create": "inventory.add_supplierinvoice",
        "match": "inventory.add_supplierinvoice",
        "approve": "inventory.approve_supplier_invoice",
    }

    def get_queryset(self):
        queryset = self._scope(
            SupplierInvoice.objects.select_related(
                "order__supplier", "order__store", "recorded_by", "approved_by"
            ),
            field="order__store__facility_id",
        )
        if status_filter := self.request.query_params.get("status"):
            queryset = queryset.filter(status__in=status_filter.split(","))
        return queryset

    def facility_for_permission(self, request):
        if self.action == "create":
            order = PurchaseOrder.objects.filter(
                pk=request.data.get("order")
            ).select_related("store__facility").first()
            return order.store.facility if order else None
        return None

    def perform_create(self, serializer):
        invoice = serializer.save(recorded_by=self.request.user)
        AuditEvent.record(
            action="supplier_invoice.recorded", actor=self.request.user,
            resource=invoice, facility=invoice.order.store.facility,
            after={"order": invoice.order.reference,
                   "supplier_reference": invoice.supplier_reference,
                   "amount": str(invoice.amount)},
            request=self.request,
        )

    @extend_schema(request=None, responses={200: SupplierInvoiceSerializer},
                   summary="Match against what was ordered and what arrived")
    @action(detail=True, methods=["post"])
    def match(self, request, pk=None):
        invoice = self.get_object()
        try:
            procurement.run_match(invoice, actor=request.user)
        except ValidationError as refusal:
            return Response({"detail": refusal.messages[0]},
                            status=http.HTTP_409_CONFLICT)
        AuditEvent.record(
            action="supplier_invoice.matched", actor=request.user, resource=invoice,
            facility=invoice.order.store.facility,
            after={"status": invoice.status,
                   "invoiced": str(invoice.amount),
                   "received_value": str(invoice.matched_value),
                   "discrepancies": invoice.discrepancies},
            request=request,
        )
        return Response(self.get_serializer(invoice).data)

    @extend_schema(request=ApproveInvoiceSerializer,
                   responses={200: SupplierInvoiceSerializer},
                   summary="Release the invoice for payment")
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        invoice = self.get_object()
        serializer = ApproveInvoiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            procurement.approve_invoice(
                invoice, actor=request.user,
                note=serializer.validated_data["note"],
            )
        except ValidationError as refusal:
            return Response({"detail": refusal.messages[0]},
                            status=http.HTTP_400_BAD_REQUEST)
        AuditEvent.record(
            action="supplier_invoice.approved", actor=request.user, resource=invoice,
            facility=invoice.order.store.facility,
            after={"order": invoice.order.reference,
                   "amount": str(invoice.amount),
                   "received_value": str(invoice.matched_value),
                   "discrepancies": invoice.discrepancies},
            reason=invoice.query_note, request=request,
        )
        return Response(self.get_serializer(invoice).data)
