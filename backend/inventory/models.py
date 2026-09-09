"""Stores, items and stock.

One app for the hospital's supply chain: what it stocks, where the stock sits,
and every movement in and out. Procurement builds on these tables rather than
on tables of its own — a purchase order that cannot say which store the goods
land in is a form that does nothing.

Deliberately separate from `pharmacy`. A medication carries a formulary entry,
a route, an ATC class and allergy matching; a box of gloves carries none of
that, and forcing both through one table would mean a medication table full of
columns that are meaningless for consumables and vice versa. What the two share
is the *discipline* — a conditional UPDATE guarding the quantity, a CHECK
constraint behind it, and a movement row for every change — and that is copied
deliberately rather than abstracted, because there is no third caller.
"""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import F
from django.utils import timezone

ZERO = "0.00"


class ItemCategory(models.Model):
    """How the stores list is grouped. Administrable. AC-143."""

    name = models.CharField(max_length=80, unique=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "name"]
        verbose_name_plural = "item categories"

    def __str__(self):
        return self.name


class InventoryItem(models.Model):
    """Something the hospital stocks that is not a medication. AC-143."""

    category = models.ForeignKey(
        ItemCategory, on_delete=models.PROTECT, related_name="items"
    )
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=40, unique=True)
    unit_of_issue = models.CharField(
        max_length=40,
        help_text="What one of these is when it leaves the store: box, pair, litre.",
    )
    # A default rather than the rule. What a ward store should hold and what the
    # main store should hold are different numbers for the same item, so the
    # operative figure lives on StockRecord.
    default_reorder_level = models.IntegerField(default=0)

    # Controlled items need a named recipient on every issue and appear in their
    # own register. Not the same thing as a controlled drug, which the pharmacy
    # handles: this covers sharps, spirits, and anything a hospital counts.
    is_controlled = models.BooleanField(default=False)

    # A bed pan does not expire. Asking a storekeeper for an expiry date on one
    # teaches them to type any date that gets past the form.
    tracks_expiry = models.BooleanField(default=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category__display_order", "name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(default_reorder_level__gte=0),
                name="item_reorder_level_not_negative",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.unit_of_issue})"


class Store(models.Model):
    """A place stock physically sits. AC-144.

    Per facility, and more than one per facility: the main store, the theatre
    store and a ward cupboard are different places, and stock in one is not
    available in another. Treating a facility as a single pool is how a theatre
    runs out while the main store has forty boxes.

    Also where the two configurable numbers from AC-147 and AC-149 live — a
    linen store and a store of surgical implants do not deserve the same
    tolerance for an unauthorised write-off, and putting the figure on the
    store means whoever runs it sets it.
    """

    MAIN = "main"
    PHARMACY = "pharmacy"
    WARD = "ward"
    THEATRE = "theatre"
    LABORATORY = "laboratory"
    IMAGING = "imaging"
    KIND_CHOICES = [
        (MAIN, "Main store"), (PHARMACY, "Pharmacy store"), (WARD, "Ward store"),
        (THEATRE, "Theatre store"), (LABORATORY, "Laboratory store"),
        (IMAGING, "Imaging store"),
    ]

    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT, related_name="stores"
    )
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20)
    kind = models.CharField(max_length=15, choices=KIND_CHOICES, default=MAIN)

    # The ward or department this store serves, where it serves one. Optional
    # because the main store serves the whole facility.
    ward = models.ForeignKey(
        "inpatient.Ward", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="stores",
    )

    # AC-147. Above this value an adjustment needs a second person. Zero means
    # every adjustment needs one, which is a reasonable setting for a store of
    # expensive implants and a miserable one for linen.
    adjustment_authorisation_limit = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO,
        help_text="Adjustments valued above this need a second person's "
                  "authorisation. Zero means all of them do.",
    )

    # AC-149. How far ahead this store wants to be warned.
    expiry_horizon_days = models.PositiveSmallIntegerField(
        default=90,
        help_text="Stock expiring within this many days is reported as expiring.",
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["facility", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "code"], name="store_code_unique_per_facility"
            ),
            models.CheckConstraint(
                condition=models.Q(adjustment_authorisation_limit__gte=0),
                name="store_authorisation_limit_not_negative",
            ),
        ]
        permissions = [
            ("issue_stock", "Can issue stock out of a store"),
            ("receive_stock", "Can receive stock into a store"),
            ("transfer_stock", "Can move stock between stores"),
            ("adjust_stock", "Can adjust stock on hand"),
            # Deliberately separate from adjust_stock: the second signature on a
            # write-off is worth nothing if the same person holds both verbs.
            ("authorise_stock_adjustment", "Can authorise another's adjustment"),
        ]

    def __str__(self):
        return f"{self.name} — {self.facility.code}"


class StockRecord(models.Model):
    """This store carries this item, and holds this much of it. AC-144.

    The row exists as soon as a store is asked to carry the item, before any
    stock arrives — that is what makes "we are out of gloves" different from
    "we do not stock gloves", and the two need different actions.
    """

    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="records")
    item = models.ForeignKey(
        InventoryItem, on_delete=models.PROTECT, related_name="records"
    )
    reorder_level = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["store", "item__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["store", "item"], name="one_record_per_store_and_item"
            ),
            models.CheckConstraint(
                condition=models.Q(reorder_level__gte=0),
                name="record_reorder_level_not_negative",
            ),
        ]

    def __str__(self):
        return f"{self.item.name} @ {self.store.name}"

    @property
    def facility_id(self):
        return self.store.facility_id

    def on_hand(self):
        """Summed from the lots. Not stored, so it cannot disagree with them."""
        return self.lots.aggregate(total=models.Sum("quantity_on_hand"))["total"] or 0

    def usable_on_hand(self, *, on=None):
        """What could actually be issued today: expired stock is not stock."""
        today = on or timezone.localdate()
        return self.lots.filter(
            models.Q(expiry_date__isnull=True) | models.Q(expiry_date__gte=today)
        ).aggregate(total=models.Sum("quantity_on_hand"))["total"] or 0

    @property
    def is_low(self):
        return self.usable_on_hand() <= self.reorder_level


class StockLot(models.Model):
    """A delivery of one item into one store, with its own expiry.

    Stock is held per lot rather than as a single number per item because an
    expiry date belongs to a delivery, not to an item, and issuing oldest-first
    is only possible if the deliveries are still distinguishable.
    """

    record = models.ForeignKey(StockRecord, on_delete=models.PROTECT, related_name="lots")
    lot_number = models.CharField(max_length=60)
    expiry_date = models.DateField(null=True, blank=True)
    quantity_on_hand = models.IntegerField(default=0)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    received_at = models.DateTimeField(default=timezone.now)

    class Meta:
        # Oldest expiry first, then oldest delivery: the order stock should
        # leave in, so a queryset that forgets to sort still picks correctly.
        ordering = [F("expiry_date").asc(nulls_last=True), "received_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["record", "lot_number"], name="one_lot_per_record_and_number"
            ),
            # The invariant, in the database. AC-146. A race that got past the
            # application would still fail here.
            models.CheckConstraint(
                condition=models.Q(quantity_on_hand__gte=0),
                name="inventory_stock_never_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_cost__gte=0), name="lot_unit_cost_not_negative"
            ),
        ]
        indexes = [models.Index(fields=["record", "expiry_date"])]

    def __str__(self):
        return f"{self.record.item.name} lot {self.lot_number}"

    @property
    def is_expired(self):
        return self.expiry_date is not None and self.expiry_date < timezone.localdate()

    def expires_within(self, days):
        if self.expiry_date is None:
            return False
        return self.expiry_date <= timezone.localdate() + timedelta(days=days)


class StockTransfer(models.Model):
    """Stock moving between two stores. AC-145.

    Two movements, not one: the sending store's ledger and the receiving
    store's ledger each have to balance on their own, and a single row with a
    from and a to leaves neither able to prove it.
    """

    from_store = models.ForeignKey(
        Store, on_delete=models.PROTECT, related_name="transfers_out"
    )
    to_store = models.ForeignKey(
        Store, on_delete=models.PROTECT, related_name="transfers_in"
    )
    item = models.ForeignKey(
        InventoryItem, on_delete=models.PROTECT, related_name="transfers"
    )
    quantity = models.IntegerField()
    reason = models.CharField(max_length=255, blank=True)
    moved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="stock_transfers"
    )
    moved_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-moved_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="transfer_quantity_positive"
            ),
            models.CheckConstraint(
                condition=~models.Q(from_store=models.F("to_store")),
                name="transfer_between_two_stores",
            ),
        ]

    def __str__(self):
        return (
            f"{self.quantity} {self.item.name}: "
            f"{self.from_store.code} → {self.to_store.code}"
        )


class StockAdjustment(models.Model):
    """A correction to what a store is recorded as holding. AC-147.

    Every other movement records something that happened to the stock. An
    adjustment records that the record was wrong, which is why it needs a
    reason and, above a value the store sets, a second person.
    """

    COUNT_CORRECTION = "count"
    DAMAGE = "damage"
    LOSS = "loss"
    EXPIRY = "expiry"
    RETURN_TO_SUPPLIER = "return_to_supplier"
    KIND_CHOICES = [
        (COUNT_CORRECTION, "Count correction"), (DAMAGE, "Damaged"),
        (LOSS, "Lost or unaccounted"), (EXPIRY, "Written off, expired"),
        (RETURN_TO_SUPPLIER, "Returned to supplier"),
    ]

    lot = models.ForeignKey(StockLot, on_delete=models.PROTECT, related_name="adjustments")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    quantity_delta = models.IntegerField(
        help_text="Negative to write stock off, positive to add it back."
    )
    # Frozen at the time of the adjustment. The lot's unit cost can change with
    # the next delivery, and the value that needed authorising must not.
    value = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    reason = models.TextField()

    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="stock_adjustments_raised",
    )
    authorised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="stock_adjustments_authorised",
    )
    raised_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-raised_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(quantity_delta=0),
                name="adjustment_changes_something",
            ),
            models.CheckConstraint(
                condition=~models.Q(reason=""), name="stock_adjustment_states_a_reason"
            ),
            # The second signature is the control; one person cannot be both
            # halves of it.
            models.CheckConstraint(
                condition=models.Q(authorised_by__isnull=True)
                | ~models.Q(authorised_by=models.F("raised_by")),
                name="adjustment_authorised_by_a_second_person",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.quantity_delta:+d} on {self.lot}"


class StockMovement(models.Model):
    """Every change in stock, so a discrepancy can be traced to an act. AC-145.

    What, how much, from where, to where, why and who — and the balance
    afterwards, so AC-150's reconstruction has something to check against
    rather than having to trust the sum.
    """

    RECEIPT = "receipt"
    ISSUE = "issue"
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"
    ADJUSTMENT = "adjustment"
    RETURN = "return"
    KIND_CHOICES = [
        (RECEIPT, "Goods received"), (ISSUE, "Issued"),
        (TRANSFER_OUT, "Transferred out"), (TRANSFER_IN, "Transferred in"),
        (ADJUSTMENT, "Adjustment"), (RETURN, "Returned to store"),
    ]

    lot = models.ForeignKey(StockLot, on_delete=models.PROTECT, related_name="movements")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    quantity_delta = models.IntegerField(help_text="Negative for stock leaving.")
    quantity_after = models.IntegerField()

    # Where it went, or came from. A ward, a department, a named person for a
    # controlled item, or the other half of a transfer.
    transfer = models.ForeignKey(
        StockTransfer, on_delete=models.PROTECT, null=True, blank=True,
        related_name="movements",
    )
    adjustment = models.ForeignKey(
        StockAdjustment, on_delete=models.PROTECT, null=True, blank=True,
        related_name="movements",
    )
    issued_to = models.CharField(
        max_length=160, blank=True,
        help_text="Ward, department or named recipient. Required for a controlled item.",
    )

    reason = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="inventory_movements",
    )
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-recorded_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(quantity_delta=0), name="movement_moves_something"
            ),
            models.CheckConstraint(
                condition=models.Q(quantity_after__gte=0),
                name="movement_balance_not_negative",
            ),
        ]
        indexes = [models.Index(fields=["lot", "recorded_at"])]

    def __str__(self):
        return f"{self.kind} {self.quantity_delta:+d} → {self.quantity_after}"


# --- procurement ------------------------------------------------------------
#
# In this app rather than one of its own, because every step of it ends at a
# shelf: a purchase order that cannot name the store the goods land in is a
# form that does nothing, and a goods receipt that does not create a stock
# movement is a lie about what the hospital holds.


class Supplier(models.Model):
    """Who the hospital buys from. AC-151."""

    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=20, unique=True)
    contact_name = models.CharField(max_length=160, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    payment_terms_days = models.PositiveSmallIntegerField(
        default=30, help_text="Days from invoice to payment, as agreed."
    )

    # Approval is a state, not a deletion. A supplier who supplied for three
    # years and is now suspended still has to appear on the orders they
    # fulfilled, so this switches off new orders rather than removing them.
    is_approved = models.BooleanField(
        default=True,
        help_text="Whether new orders may be placed. Past orders are unaffected.",
    )
    approval_note = models.CharField(
        max_length=255, blank=True,
        help_text="Why they are not approved, where they are not.",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class PurchaseRequest(models.Model):
    """Somebody asking for goods to be bought. AC-152, AC-153.

    Separate from the order because asking and committing money are different
    acts by different people. A storekeeper knows the shelf is empty; only
    somebody with a budget decides to spend against it.
    """

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    ORDERED = "ordered"
    STATUS_CHOICES = [
        (DRAFT, "Draft"), (SUBMITTED, "Awaiting approval"), (APPROVED, "Approved"),
        (REJECTED, "Rejected"), (ORDERED, "Ordered"),
    ]

    reference = models.CharField(max_length=30, unique=True)
    store = models.ForeignKey(
        Store, on_delete=models.PROTECT, related_name="purchase_requests",
        help_text="Where the goods are to land.",
    )
    justification = models.TextField()
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=DRAFT)

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="purchase_requests",
    )
    requested_at = models.DateTimeField(default=timezone.now)
    submitted_at = models.DateTimeField(null=True, blank=True)

    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="purchase_requests_decided",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-requested_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(justification=""),
                name="purchase_request_states_why",
            ),
            # AC-153, in the database as well as in the service. An approver
            # who is also the requester is not an approval.
            models.CheckConstraint(
                condition=models.Q(decided_by__isnull=True)
                | ~models.Q(decided_by=models.F("requested_by")),
                name="request_not_approved_by_its_own_requester",
            ),
            # Approved and rejected are decisions and need a decider. "Ordered"
            # is not a decision but a consequence — a request small enough to
            # need no approval reaches it with nobody having decided anything,
            # and that is correct rather than a gap.
            models.CheckConstraint(
                condition=~models.Q(status__in=["approved", "rejected"])
                | models.Q(decided_by__isnull=False),
                name="decided_request_names_who_decided",
            ),
        ]

    def __str__(self):
        return f"{self.reference} — {self.store.name}"

    @property
    def facility_id(self):
        return self.store.facility_id

    def estimated_value(self):
        total = self.lines.aggregate(
            total=models.Sum(
                models.F("quantity") * models.F("estimated_unit_cost"),
                output_field=models.DecimalField(max_digits=14, decimal_places=2),
            )
        )["total"]
        return total or Decimal("0.00")

    def needs_approval(self):
        """AC-152. Above the store's own threshold.

        The same figure that governs stock adjustments: a store trusted to
        write off ₦50,000 without a second signature is trusted to ask for
        ₦50,000 of stock without one. One number per store rather than two
        means one thing to keep in step.
        """
        return self.estimated_value() > self.store.adjustment_authorisation_limit


class PurchaseRequestLine(models.Model):
    request = models.ForeignKey(
        PurchaseRequest, on_delete=models.CASCADE, related_name="lines"
    )
    item = models.ForeignKey(
        InventoryItem, on_delete=models.PROTECT, related_name="request_lines"
    )
    quantity = models.IntegerField()
    estimated_unit_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO
    )
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["request", "item__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["request", "item"], name="one_request_line_per_item"
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="request_line_quantity_positive",
            ),
        ]

    def __str__(self):
        return f"{self.quantity} × {self.item.name}"


class PurchaseOrder(models.Model):
    """The commitment to buy, at agreed prices. AC-154."""

    OPEN = "open"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (OPEN, "Open"), (PARTIALLY_RECEIVED, "Partially received"),
        (RECEIVED, "Received in full"), (CANCELLED, "Cancelled"),
    ]

    reference = models.CharField(max_length=30, unique=True)
    request = models.ForeignKey(
        PurchaseRequest, on_delete=models.PROTECT, related_name="orders"
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="orders"
    )
    store = models.ForeignKey(
        Store, on_delete=models.PROTECT, related_name="purchase_orders"
    )
    expected_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=OPEN)
    note = models.TextField(blank=True)

    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="purchase_orders",
    )
    raised_at = models.DateTimeField(default=timezone.now)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-raised_at", "-id"]

    def __str__(self):
        return f"{self.reference} — {self.supplier.name}"

    @property
    def facility_id(self):
        return self.store.facility_id

    def total_ordered(self):
        total = self.lines.aggregate(
            total=models.Sum(
                models.F("quantity_ordered") * models.F("unit_cost"),
                output_field=models.DecimalField(max_digits=14, decimal_places=2),
            )
        )["total"]
        return total or Decimal("0.00")

    def total_received_value(self):
        total = self.lines.aggregate(
            total=models.Sum(
                models.F("quantity_received") * models.F("unit_cost"),
                output_field=models.DecimalField(max_digits=14, decimal_places=2),
            )
        )["total"]
        return total or Decimal("0.00")

    def is_complete(self):
        return all(line.is_complete for line in self.lines.all())


class PurchaseOrderLine(models.Model):
    """One item on an order, and how much of it has arrived. AC-155."""

    order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name="lines"
    )
    item = models.ForeignKey(
        InventoryItem, on_delete=models.PROTECT, related_name="order_lines"
    )
    quantity_ordered = models.IntegerField()
    # Derived from the receipts, kept here so a short delivery is visible on the
    # line rather than requiring a sum across receipts to notice.
    quantity_received = models.IntegerField(default=0)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["order", "item__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "item"], name="one_order_line_per_item"
            ),
            models.CheckConstraint(
                condition=models.Q(quantity_ordered__gt=0),
                name="order_line_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity_received__gte=0),
                name="order_line_received_not_negative",
            ),
            # Over-delivery is a real event and needs a decision, not a silent
            # acceptance: it changes what the hospital owes.
            models.CheckConstraint(
                condition=models.Q(quantity_received__lte=models.F("quantity_ordered")),
                name="order_line_not_over_received",
            ),
        ]

    def __str__(self):
        return f"{self.quantity_received}/{self.quantity_ordered} × {self.item.name}"

    @property
    def outstanding(self):
        return self.quantity_ordered - self.quantity_received

    @property
    def is_complete(self):
        return self.quantity_received >= self.quantity_ordered


class GoodsReceipt(models.Model):
    """A delivery arriving against an order. AC-155, AC-156."""

    reference = models.CharField(max_length=30, unique=True)
    order = models.ForeignKey(
        PurchaseOrder, on_delete=models.PROTECT, related_name="receipts"
    )
    delivery_note = models.CharField(max_length=60, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="goods_receipts",
    )
    received_at = models.DateTimeField(default=timezone.now)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-received_at", "-id"]

    def __str__(self):
        return f"{self.reference} against {self.order.reference}"

    @property
    def facility_id(self):
        return self.order.store.facility_id

    def total_value(self):
        total = self.lines.aggregate(
            total=models.Sum(
                models.F("quantity") * models.F("order_line__unit_cost"),
                output_field=models.DecimalField(max_digits=14, decimal_places=2),
            )
        )["total"]
        return total or Decimal("0.00")


class GoodsReceiptLine(models.Model):
    """What arrived, on which lot, and the movement that shelved it. AC-156.

    `movement` is not nullable. A receipt line without a stock movement would
    be a delivery the hospital believes it has and cannot find, and a movement
    without a receipt line would be stock with no paperwork — the constraint
    makes both unrepresentable rather than merely discouraged.
    """

    receipt = models.ForeignKey(
        GoodsReceipt, on_delete=models.CASCADE, related_name="lines"
    )
    order_line = models.ForeignKey(
        PurchaseOrderLine, on_delete=models.PROTECT, related_name="receipt_lines"
    )
    quantity = models.IntegerField()
    lot_number = models.CharField(max_length=60)
    expiry_date = models.DateField(null=True, blank=True)
    movement = models.OneToOneField(
        StockMovement, on_delete=models.PROTECT, related_name="receipt_line"
    )

    class Meta:
        ordering = ["receipt", "order_line__item__name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="receipt_line_quantity_positive",
            ),
        ]

    def __str__(self):
        return f"{self.quantity} × {self.order_line.item.name}"


class SupplierInvoice(models.Model):
    """What the supplier says is owed, against what was ordered and arrived.

    AC-157. A mismatch is surfaced rather than paid: three-way matching is the
    only thing standing between a hospital and paying for goods that never
    came, and a system that quietly accepts the invoice figure provides none.
    """

    RECEIVED = "received"
    MATCHED = "matched"
    QUERIED = "queried"
    APPROVED = "approved"
    PAID = "paid"
    STATUS_CHOICES = [
        (RECEIVED, "Received"), (MATCHED, "Matched"), (QUERIED, "Queried"),
        (APPROVED, "Approved for payment"), (PAID, "Paid"),
    ]

    order = models.ForeignKey(
        PurchaseOrder, on_delete=models.PROTECT, related_name="invoices"
    )
    supplier_reference = models.CharField(
        max_length=60, help_text="The number on the supplier's own invoice."
    )
    invoice_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=RECEIVED)

    # Frozen when the match is run. The order and the receipts can carry on
    # changing afterwards, and what was queried has to stay what was queried.
    matched_at = models.DateTimeField(null=True, blank=True)
    matched_value = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        help_text="Value of what actually arrived, at ordered prices, when matched.",
    )
    discrepancies = models.JSONField(
        default=list, blank=True,
        help_text="What did not match, in words, as at the time of matching.",
    )

    query_note = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="supplier_invoices_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="supplier_invoices",
    )
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-invoice_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "supplier_reference"],
                name="one_invoice_per_order_and_supplier_reference",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="supplier_invoice_amount_positive"
            ),
            # An invoice cannot be approved for payment while it is queried, and
            # cannot be approved without somebody's name on it.
            models.CheckConstraint(
                condition=~models.Q(status__in=["approved", "paid"])
                | models.Q(approved_by__isnull=False),
                name="approved_invoice_names_its_approver",
            ),
        ]
        permissions = [
            ("approve_purchase_request", "Can approve a purchase request"),
            ("raise_purchase_order", "Can raise a purchase order"),
            ("receive_goods", "Can record goods received against an order"),
            # Paying is not the same act as matching: whoever checks the invoice
            # against the delivery is not automatically the person who releases
            # the money.
            ("approve_supplier_invoice", "Can approve a supplier invoice for payment"),
        ]

    def __str__(self):
        return f"{self.supplier_reference} — {self.amount}"

    @property
    def facility_id(self):
        return self.order.store.facility_id
