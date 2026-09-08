"""Services, invoices, payments and cashier reconciliation.

Three rules shape this module.

**Charges come from clinical events, not from typing.** Every invoice line records the
thing that caused it, and (invoice, source) is unique — so a retried request, a
double-clicked button or a re-run job produces one charge, not two.

**Payments are idempotent.** The client sends a key; the same key always returns the
same payment rather than taking the money twice.

**Reconciled money does not change.** Once a cashier session is reconciled, its
invoices and payments are frozen and corrections happen as new adjusting entries. This
is enforced in the database, not only in the views.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from patients.models import NumberSequence

ZERO = Decimal("0.00")


class ServiceCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name_plural = "service categories"
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name


class Service(models.Model):
    """Anything a hospital charges for."""

    category = models.ForeignKey(
        ServiceCategory, on_delete=models.PROTECT, related_name="services"
    )
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=30, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category__display_order", "name"]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def price_at(self, facility):
        price = self.prices.filter(facility=facility, is_active=True).first()
        return price.amount if price else None


class ServicePrice(models.Model):
    """Prices are per facility: a branch clinic does not charge a teaching hospital's
    rates."""

    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="prices")
    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.CASCADE, related_name="service_prices"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["service", "facility"],
                condition=models.Q(is_active=True),
                name="one_active_price_per_service_and_facility",
            )
        ]

    def __str__(self):
        return f"{self.service.code} @ {self.facility.code}: {self.amount}"


class PaymentMethod(models.Model):
    name = models.CharField(max_length=60, unique=True)
    code = models.CharField(max_length=20, unique=True)
    requires_reference = models.BooleanField(
        default=False, help_text="Transfers and card payments need a reference."
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CashierSession(models.Model):
    """A cashier's shift. Reconciliation freezes everything taken during it."""

    OPEN = "open"
    CLOSED = "closed"
    RECONCILED = "reconciled"
    STATUS_CHOICES = [
        (OPEN, "Open"), (CLOSED, "Closed"), (RECONCILED, "Reconciled"),
    ]

    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cashier_sessions"
    )
    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT, related_name="cashier_sessions"
    )
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    reconciled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="sessions_reconciled",
    )
    opening_float = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    counted_total = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    variance_note = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=OPEN)

    class Meta:
        ordering = ["-opened_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["cashier", "facility"],
                condition=models.Q(status="open"),
                name="one_open_session_per_cashier_and_facility",
            )
        ]
        permissions = [
            ("reconcile_cashiersession", "Can reconcile a cashier session"),
        ]

    def __str__(self):
        return f"{self.cashier.email} @ {self.facility.code} ({self.status})"

    @property
    def is_frozen(self):
        return self.status == self.RECONCILED

    def expected_total(self):
        return self.payments.aggregate(
            total=models.Sum("amount")
        )["total"] or ZERO


class Invoice(models.Model):
    DRAFT = "draft"
    FINALISED = "finalised"
    PAID = "paid"
    VOID = "void"
    STATUS_CHOICES = [
        (DRAFT, "Draft"), (FINALISED, "Finalised"), (PAID, "Paid"), (VOID, "Void"),
    ]

    invoice_number = models.CharField(max_length=40, unique=True, editable=False)
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="invoices"
    )
    visit = models.ForeignKey(
        "visits.Visit", on_delete=models.PROTECT, null=True, blank=True,
        related_name="invoices",
    )
    # An inpatient stay bills to the admission, not to the attendance that
    # started it: bed nights, ward medication and inpatient investigations
    # accrue for weeks after the outpatient visit closed.
    admission = models.ForeignKey(
        "inpatient.Admission", on_delete=models.PROTECT, null=True, blank=True,
        related_name="invoices",
    )
    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT, related_name="invoices"
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)

    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    discount_reason = models.CharField(max_length=255, blank=True)
    discount_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="discounts_approved",
    )
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)

    created_at = models.DateTimeField(auto_now_add=True)
    finalised_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["patient", "-created_at"])]
        constraints = [
            # One open invoice per visit, so charges accumulate in one place rather
            # than being split across several bills at the cash desk.
            models.UniqueConstraint(
                fields=["visit"],
                condition=models.Q(status="draft", admission__isnull=True),
                name="one_draft_invoice_per_visit",
            ),
            models.UniqueConstraint(
                fields=["admission"],
                condition=models.Q(status="draft"),
                name="one_draft_invoice_per_admission",
            ),
            models.CheckConstraint(
                condition=models.Q(discount_amount__gte=0), name="discount_not_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(status="void") | models.Q(void_reason=""),
                name="void_reason_only_on_void",
            ),
        ]
        permissions = [
            ("approve_discount", "Can approve a discount above their own limit"),
            ("void_invoice", "Can void an invoice"),
            ("issue_refund", "Can issue a refund"),
        ]

    def __str__(self):
        return f"{self.invoice_number} — {self.patient.full_name}"

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = NumberSequence.allocate("invoice_number")
        return super().save(*args, **kwargs)

    # --- money ---------------------------------------------------------------
    # Computed from the lines every time rather than cached in a column: a stored
    # total that disagrees with its items is the classic billing bug.

    @property
    def subtotal(self):
        return sum(
            (item.amount for item in self.items.all() if not item.is_cancelled), ZERO
        )

    @property
    def total(self):
        return self.subtotal - self.discount_amount + self.tax_amount

    @property
    def amount_paid(self):
        return sum((payment.amount for payment in self.payments.all()), ZERO)

    @property
    def amount_refunded(self):
        return sum(
            (refund.amount for payment in self.payments.all()
             for refund in payment.refunds.all()),
            ZERO,
        )

    @property
    def balance(self):
        return self.total - self.amount_paid + self.amount_refunded

    @property
    def is_frozen(self):
        """Reconciled money is not editable. Corrections are new entries.

        Reads the prefetched payments rather than filtering them, for the same
        reason as Encounter.current_version — a filtered manager cannot use the
        prefetch cache, so this would be one extra query per invoice in a list.
        """
        return any(
            payment.cashier_session.status == CashierSession.RECONCILED
            for payment in self.payments.all()
        )


class InvoiceItem(models.Model):
    """One charge, and the clinical event that produced it."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    service = models.ForeignKey(
        Service, on_delete=models.PROTECT, null=True, blank=True, related_name="invoice_items"
    )
    description = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    # The event this charge came from. Unique per invoice, which is what makes charge
    # generation idempotent.
    source_type = models.CharField(max_length=60, blank=True)
    source_id = models.CharField(max_length=64, blank=True)

    is_cancelled = models.BooleanField(default=False)
    cancelled_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["invoice", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["invoice", "source_type", "source_id"],
                condition=~models.Q(source_type=""),
                name="one_charge_per_source_event",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0), name="unit_price_not_negative"
            ),
        ]

    def __str__(self):
        return f"{self.description} × {self.quantity}"

    @property
    def amount(self):
        return self.unit_price * self.quantity


class Payment(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    cashier_session = models.ForeignKey(
        CashierSession, on_delete=models.PROTECT, related_name="payments"
    )
    method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=100, blank=True)
    receipt_number = models.CharField(max_length=40, unique=True, editable=False)

    # The client's key. Same key, same payment — a retry never takes money twice.
    idempotency_key = models.CharField(max_length=100, unique=True)

    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments_received"
    )
    received_at = models.DateTimeField(default=timezone.now)
    reprint_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-received_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="payment_amount_positive"
            )
        ]

    def __str__(self):
        return f"{self.receipt_number} — {self.amount}"

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            self.receipt_number = NumberSequence.allocate("receipt_number")
        return super().save(*args, **kwargs)

    @property
    def amount_refunded(self):
        return sum((refund.amount for refund in self.refunds.all()), ZERO)

    @property
    def is_frozen(self):
        return self.cashier_session.status == CashierSession.RECONCILED


class Refund(models.Model):
    """Always references the payment it reverses. Never edits it."""

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.TextField()
    cashier_session = models.ForeignKey(
        CashierSession, on_delete=models.PROTECT, related_name="refunds"
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="refunds_issued"
    )
    issued_at = models.DateTimeField(default=timezone.now)
    reference = models.CharField(max_length=40, unique=True, editable=False)

    class Meta:
        ordering = ["-issued_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="refund_amount_positive"
            )
        ]

    def __str__(self):
        return f"{self.reference} — {self.amount} against {self.payment.receipt_number}"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = NumberSequence.allocate("refund_reference")
        return super().save(*args, **kwargs)


@transaction.atomic
def open_invoice_for(visit=None, *, admission=None, created_by=None):
    """The draft invoice for a visit or an admission, created on first need.

    An admission gets its own. A stay accrues bed nights, ward medication and
    investigations for weeks after the outpatient attendance that started it
    closed — and that attendance's bill may well have been paid and reconciled,
    at which point it is frozen and cannot take another charge.
    """
    if admission is not None:
        invoice = Invoice.objects.filter(
            admission=admission, status=Invoice.DRAFT
        ).first()
        if invoice is not None:
            return invoice
        return Invoice.objects.create(
            patient=admission.patient, admission=admission, visit=admission.visit,
            facility=admission.facility,
        )
    if visit is None:
        raise ValidationError("A charge needs either a visit or an admission.")
    invoice = Invoice.objects.filter(
        visit=visit, admission__isnull=True, status=Invoice.DRAFT
    ).first()
    if invoice is not None:
        return invoice
    return Invoice.objects.create(
        patient=visit.patient, visit=visit, facility=visit.facility
    )


def _already_charged(*, source_type, source_id, visit=None, admission=None):
    """Whether this clinical event has been billed on any live invoice.

    A voided invoice is excluded on purpose: voiding an invoice is how a
    mis-billed stay is corrected, and the charges on it have to be raisable
    again afterwards or the correction loses them.
    """
    invoices = (
        Invoice.objects.filter(admission=admission)
        if admission is not None
        else Invoice.objects.filter(visit=visit, admission__isnull=True)
    )
    return InvoiceItem.objects.filter(
        invoice__in=invoices.exclude(status=Invoice.VOID),
        source_type=source_type,
        source_id=str(source_id),
    ).first()


@transaction.atomic
def charge(*, service_code, description, source_type, source_id, visit=None,
           admission=None, quantity=1, unit_price=None, actor=None,
           service_date=None):
    """Add a charge for a clinical event, at most once.

    Called by the module that performed the act — the laboratory when an order
    is placed, the pharmacy when medication is issued, the ward when a night is
    slept — so every line can be traced back to something that actually
    happened.

    "At most once" is per *stay or attendance*, not per invoice. The unique
    constraint on `(invoice, source_type, source_id)` stops a retry landing
    twice on one invoice, but it says nothing across two: a long admission is
    billed in stages, and once the first invoice is finalised the next charge
    opens a fresh draft. Keyed only on the invoice, every bed night already
    settled would be charged again on that new draft — the patient pays twice
    for the same night, and the ward has no way to tell which line is the
    duplicate. So the search below spans every invoice for the target.
    """
    existing = _already_charged(
        source_type=source_type, source_id=source_id, visit=visit, admission=admission
    )
    if existing is not None:
        return existing, False

    invoice = open_invoice_for(visit, admission=admission)
    facility = invoice.facility
    if invoice.status != Invoice.DRAFT:
        raise ValidationError(
            f"{invoice.invoice_number} is {invoice.status} and cannot take new charges."
        )

    service = Service.objects.filter(code=service_code, is_active=True).first()
    if unit_price is None:
        if service is None:
            raise ValidationError(f"No service configured with code {service_code!r}.")
        unit_price = service.price_at(facility)
        if unit_price is None:
            raise ValidationError(
                f"{service.name} has no price configured for {facility.code}."
            )

    item, created = InvoiceItem.objects.get_or_create(
        invoice=invoice,
        source_type=source_type,
        source_id=str(source_id),
        defaults={
            "service": service,
            "description": description,
            "quantity": quantity,
            "unit_price": unit_price,
        },
    )
    if created:
        # Coverage is resolved here, as the charge is raised, because this is
        # the moment the rules were true. Resolving at invoice time would judge
        # February's treatment by March's plan. `resolve` never refuses: a
        # missing authorisation holds the claim, not the charge.
        from insurance.coverage import resolve

        resolve(
            invoice_item=item,
            service=service,
            amount=item.amount,
            patient=invoice.patient,
            service_date=service_date,
            visit=visit,
            admission=admission,
        )
    return item, created
