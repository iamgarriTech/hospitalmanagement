"""Medication catalogue, prescriptions, stock and dispensing.

Two things drive this design.

**Stock cannot go negative.** Dispensing decrements a specific batch with a conditional
UPDATE, so two pharmacists reaching for the last packet cannot both succeed. A check
constraint backs it up, because an invariant enforced only in Python is one bug away
from being no invariant at all.

**Safety checks are honest about their limits.** The checks here need no licensed data:
allergy matching, therapeutic duplication, dose ranges, special-population flags, and
contraindications the hospital's own pharmacist maintains. Drug–drug interaction
checking needs a licensed database and is *not* bundled, so the API states plainly that
it is not running. A clinician who assumes a check exists prescribes as though it does.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone

from core.models import Coding
from patients.models import NumberSequence


class MedicationCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name_plural = "medication categories"
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name


class Medication(Coding):
    """A formulary entry. `code` carries ATC where one applies.

    The catalogue is the hospital's own — what the pharmacy actually stocks — rather
        than an imported national drug list, so prescribers cannot write for something
    that cannot be filled.
    """

    ORAL = "oral"
    IV = "iv"
    IM = "im"
    SC = "sc"
    TOPICAL = "topical"
    RECTAL = "rectal"
    INHALED = "inhaled"
    OPHTHALMIC = "ophthalmic"
    ROUTE_CHOICES = [
        (ORAL, "Oral"), (IV, "Intravenous"), (IM, "Intramuscular"),
        (SC, "Subcutaneous"), (TOPICAL, "Topical"), (RECTAL, "Rectal"),
        (INHALED, "Inhaled"), (OPHTHALMIC, "Ophthalmic"),
    ]

    category = models.ForeignKey(
        MedicationCategory, on_delete=models.PROTECT, related_name="medications"
    )
    generic_name = models.CharField(max_length=200)
    brand_name = models.CharField(max_length=200, blank=True)
    strength = models.CharField(max_length=60, help_text="e.g. 500 mg, 125 mg/5 mL")
    dosage_form = models.CharField(max_length=60, help_text="e.g. tablet, suspension")
    default_route = models.CharField(max_length=15, choices=ROUTE_CHOICES, default=ORAL)
    dispensing_unit = models.CharField(max_length=30, default="tablet")

    # Ingredients drive allergy matching, so a combination product is matched on each.
    ingredients_csv = models.CharField(
        max_length=400,
        blank=True,
        help_text="Active ingredients, comma separated. Used for allergy matching.",
    )
    atc_class = models.CharField(
        max_length=20, blank=True,
        help_text="ATC class prefix used for therapeutic-duplication checks.",
    )

    avoid_in_pregnancy = models.BooleanField(default=False)
    avoid_in_renal_impairment = models.BooleanField(default=False)
    paediatric_caution = models.BooleanField(default=False)
    caution_note = models.CharField(max_length=255, blank=True)

    selling_price = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Price per dispensing unit, charged when medication is issued.",
    )
    reorder_level = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["generic_name", "strength"]
        constraints = [
            models.UniqueConstraint(
                fields=["generic_name", "strength", "dosage_form", "brand_name"],
                name="medication_unique_presentation",
            )
        ]

    def __str__(self):
        label = f"{self.generic_name} {self.strength} {self.dosage_form}"
        return f"{label} ({self.brand_name})" if self.brand_name else label

    @property
    def ingredients(self):
        listed = [part.strip() for part in self.ingredients_csv.split(",") if part.strip()]
        return listed or [self.generic_name]


class DoseRange(models.Model):
    """Acceptable dose for a route and age band. Drives the dose-range check."""

    medication = models.ForeignKey(
        Medication, on_delete=models.CASCADE, related_name="dose_ranges"
    )
    route = models.CharField(max_length=15, choices=Medication.ROUTE_CHOICES)
    min_age_years = models.PositiveSmallIntegerField(null=True, blank=True)
    max_age_years = models.PositiveSmallIntegerField(null=True, blank=True)
    min_single_dose = models.DecimalField(max_digits=10, decimal_places=3)
    max_single_dose = models.DecimalField(max_digits=10, decimal_places=3)
    dose_unit = models.CharField(max_length=20, default="mg")
    max_daily_dose = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True
    )

    class Meta:
        ordering = ["medication", "route", "min_age_years"]

    def __str__(self):
        return (
            f"{self.medication.generic_name} {self.route}: "
            f"{self.min_single_dose:g}–{self.max_single_dose:g} {self.dose_unit}"
        )

    def applies_to(self, *, route, age_years=None):
        if self.route != route:
            return False
        if age_years is None:
            return self.min_age_years is None and self.max_age_years is None
        if self.min_age_years is not None and age_years < self.min_age_years:
            return False
        if self.max_age_years is not None and age_years > self.max_age_years:
            return False
        return True


class ContraindicationRule(models.Model):
    """Maintained by the hospital's own pharmacy department.

    Deliberately simple and hospital-owned: rules a pharmacist writes and tunes produce
    far fewer false positives than a maximal external feed at default sensitivity, and
    alert fatigue is itself a safety failure.
    """

    ADVISORY = "advisory"
    WARNING = "warning"
    SEVERITY_CHOICES = [(ADVISORY, "Advisory"), (WARNING, "Warning")]

    medication = models.ForeignKey(
        Medication, on_delete=models.CASCADE, related_name="contraindications"
    )
    condition_keyword = models.CharField(
        max_length=100,
        help_text="Matched against the patient's recorded chronic conditions.",
    )
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default=WARNING)
    note = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    maintained_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True
    )

    def __str__(self):
        return f"{self.medication.generic_name} ⚠ {self.condition_keyword}"


class StockBatch(models.Model):
    """Physical stock, per facility, per batch, with an expiry date."""

    medication = models.ForeignKey(
        Medication, on_delete=models.PROTECT, related_name="batches"
    )
    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT, related_name="stock_batches"
    )
    batch_number = models.CharField(max_length=60)
    expiry_date = models.DateField()
    quantity_on_hand = models.IntegerField(default=0)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    received_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name_plural = "stock batches"
        ordering = ["expiry_date", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["medication", "facility", "batch_number"],
                name="batch_unique_per_medication_and_facility",
            ),
            # The invariant, in the database. A race that got past the application
            # would still fail here.
            models.CheckConstraint(
                condition=models.Q(quantity_on_hand__gte=0),
                name="stock_never_negative",
            ),
        ]
        indexes = [models.Index(fields=["medication", "facility", "expiry_date"])]

    def __str__(self):
        return f"{self.medication.generic_name} batch {self.batch_number}"

    @property
    def is_expired(self):
        return self.expiry_date < timezone.localdate()


class Prescription(models.Model):
    ACTIVE = "active"
    PARTIALLY_DISPENSED = "partially_dispensed"
    DISPENSED = "dispensed"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (ACTIVE, "Active"), (PARTIALLY_DISPENSED, "Partially dispensed"),
        (DISPENSED, "Dispensed"), (CANCELLED, "Cancelled"),
    ]

    prescription_number = models.CharField(max_length=40, unique=True, editable=False)
    encounter = models.ForeignKey(
        "clinical.Encounter", on_delete=models.PROTECT, null=True, blank=True,
        related_name="prescriptions",
    )
    visit = models.ForeignKey(
        "visits.Visit", on_delete=models.PROTECT, related_name="prescriptions"
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="prescriptions"
    )
    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT, related_name="prescriptions"
    )
    prescribed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="prescriptions"
    )
    prescribed_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=ACTIVE)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-prescribed_at"]
        indexes = [models.Index(fields=["patient", "-prescribed_at"])]
        permissions = [
            ("dispense_medication", "Can dispense medication"),
            ("override_safety_warning", "Can prescribe despite a safety warning"),
        ]

    def __str__(self):
        return f"{self.prescription_number} — {self.patient.full_name}"

    def save(self, *args, **kwargs):
        if not self.prescription_number:
            self.prescription_number = NumberSequence.allocate("prescription_number")
        return super().save(*args, **kwargs)

    def refresh_status(self):
        items = list(self.items.exclude(status=PrescriptionItem.CANCELLED))
        if not items:
            status = self.CANCELLED
        elif all(item.is_fully_dispensed for item in items):
            status = self.DISPENSED
        elif any(item.quantity_dispensed > 0 for item in items):
            status = self.PARTIALLY_DISPENSED
        else:
            status = self.ACTIVE
        if status != self.status:
            self.status = status
            self.save(update_fields=["status"])
        return status


class PrescriptionItem(models.Model):
    PRESCRIBED = "prescribed"
    PARTIALLY_DISPENSED = "partially_dispensed"
    DISPENSED = "dispensed"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (PRESCRIBED, "Prescribed"), (PARTIALLY_DISPENSED, "Partially dispensed"),
        (DISPENSED, "Dispensed"), (CANCELLED, "Cancelled"),
    ]

    prescription = models.ForeignKey(
        Prescription, on_delete=models.CASCADE, related_name="items"
    )
    medication = models.ForeignKey(
        Medication, on_delete=models.PROTECT, related_name="prescription_items"
    )
    dose = models.DecimalField(max_digits=10, decimal_places=3)
    dose_unit = models.CharField(max_length=20, default="mg")
    route = models.CharField(max_length=15, choices=Medication.ROUTE_CHOICES)
    frequency_per_day = models.PositiveSmallIntegerField(default=3)
    duration_days = models.PositiveSmallIntegerField(default=5)
    quantity_prescribed = models.PositiveIntegerField()
    quantity_dispensed = models.PositiveIntegerField(default=0)
    instructions = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PRESCRIBED)
    cancelled_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["prescription", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity_dispensed__lte=models.F("quantity_prescribed")),
                name="never_dispense_more_than_prescribed",
            )
        ]

    def __str__(self):
        return f"{self.medication.generic_name} {self.dose:g}{self.dose_unit}"

    @property
    def quantity_outstanding(self):
        return self.quantity_prescribed - self.quantity_dispensed

    @property
    def is_fully_dispensed(self):
        return self.quantity_dispensed >= self.quantity_prescribed

    @property
    def daily_dose(self):
        return self.dose * self.frequency_per_day


class SafetyOverride(models.Model):
    """A clinician proceeding past a warning, with their stated reason.

    The record is the point: a warning that can be clicked away without trace is not a
    safety control.
    """

    prescription_item = models.ForeignKey(
        PrescriptionItem, on_delete=models.CASCADE, related_name="safety_overrides"
    )
    warning_kind = models.CharField(max_length=40)
    warning_detail = models.CharField(max_length=400)
    reason = models.TextField()
    overridden_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="safety_overrides"
    )
    overridden_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.warning_kind} overridden by {self.overridden_by.email}"


class Dispense(models.Model):
    """One issue of stock against one prescription line."""

    prescription_item = models.ForeignKey(
        PrescriptionItem, on_delete=models.PROTECT, related_name="dispenses"
    )
    batch = models.ForeignKey(
        StockBatch, on_delete=models.PROTECT, related_name="dispenses"
    )
    quantity = models.PositiveIntegerField()
    dispensed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="dispenses"
    )
    dispensed_at = models.DateTimeField(default=timezone.now)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-dispensed_at"]

    def __str__(self):
        return f"{self.quantity} × {self.batch.medication.generic_name}"


class StockMovement(models.Model):
    """Every change in stock, so a discrepancy can be traced to an act."""

    RECEIPT = "receipt"
    DISPENSE = "dispense"
    ADJUSTMENT = "adjustment"
    RETURN = "return"
    EXPIRY_WRITE_OFF = "expiry_write_off"
    KIND_CHOICES = [
        (RECEIPT, "Goods received"), (DISPENSE, "Dispensed"),
        (ADJUSTMENT, "Adjustment"), (RETURN, "Returned"),
        (EXPIRY_WRITE_OFF, "Written off, expired"),
    ]

    batch = models.ForeignKey(
        StockBatch, on_delete=models.PROTECT, related_name="movements"
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    quantity_delta = models.IntegerField(help_text="Negative for stock leaving.")
    quantity_after = models.IntegerField()
    dispense = models.ForeignKey(
        Dispense, on_delete=models.PROTECT, null=True, blank=True,
        related_name="movements",
    )
    reason = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="stock_movements"
    )
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-recorded_at", "-id"]

    def __str__(self):
        return f"{self.kind} {self.quantity_delta:+d} → {self.quantity_after}"


@transaction.atomic
def take_from_batch(*, batch, quantity, actor, kind=StockMovement.DISPENSE,
                    dispense=None, reason=""):
    """Remove stock from a batch, or fail.

    A conditional UPDATE rather than read-then-write: two pharmacists dispensing the
    last packet at the same instant cannot both succeed, without holding a lock.
    """
    if quantity <= 0:
        raise ValidationError("Quantity must be positive.")
    updated = StockBatch.objects.filter(
        pk=batch.pk, quantity_on_hand__gte=quantity
    ).update(quantity_on_hand=F("quantity_on_hand") - quantity)
    if not updated:
        current = StockBatch.objects.get(pk=batch.pk).quantity_on_hand
        raise ValidationError(
            f"Only {current} left in batch {batch.batch_number}; "
            f"{quantity} was requested."
        )
    batch.refresh_from_db(fields=["quantity_on_hand"])
    return StockMovement.objects.create(
        batch=batch,
        kind=kind,
        quantity_delta=-quantity,
        quantity_after=batch.quantity_on_hand,
        dispense=dispense,
        reason=reason,
        recorded_by=actor,
    )
