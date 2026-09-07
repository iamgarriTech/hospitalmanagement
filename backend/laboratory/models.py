"""Laboratory catalogue, orders, specimens and results.

The shape here is driven by one fact that a naive model gets wrong: **a test is not a
value**. A full blood count is one order line with a dozen measurements, each with its
own unit and its own reference range, and each independently normal, abnormal or
critical. So results hang off parameters, not off tests.

Reference ranges vary by sex and age, results are verified by someone other than
whoever typed them, and a correction after verification is an amendment that leaves the
superseded value on the record.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from core.formatting import trim_decimal
from core.models import Coding
from patients.models import NumberSequence


class LabTestCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name_plural = "lab test categories"
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name


class LabTest(Coding):
    """A catalogue entry. `code` carries LOINC where one applies."""

    BLOOD = "blood"
    URINE = "urine"
    STOOL = "stool"
    SWAB = "swab"
    SPUTUM = "sputum"
    CSF = "csf"
    OTHER = "other"
    SPECIMEN_CHOICES = [
        (BLOOD, "Blood"), (URINE, "Urine"), (STOOL, "Stool"), (SWAB, "Swab"),
        (SPUTUM, "Sputum"), (CSF, "Cerebrospinal fluid"), (OTHER, "Other"),
    ]

    category = models.ForeignKey(
        LabTestCategory, on_delete=models.PROTECT, related_name="tests"
    )
    name = models.CharField(max_length=200)
    short_code = models.CharField(max_length=20, unique=True)
    specimen_type = models.CharField(max_length=15, choices=SPECIMEN_CHOICES, default=BLOOD)
    specimen_requirements = models.CharField(
        max_length=255, blank=True, help_text="e.g. Fasting 8 hours; EDTA bottle"
    )
    turnaround_hours = models.PositiveSmallIntegerField(default=24)
    service = models.ForeignKey(
        "billing.Service", on_delete=models.PROTECT, null=True, blank=True,
        related_name="lab_tests", help_text="Billed through this service.",
    )
    is_active = models.BooleanField(default=True)
    is_panel = models.BooleanField(
        default=False, help_text="A panel is ordered as one line and expands into members."
    )
    panel_members = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="panels"
    )

    class Meta:
        ordering = ["category__display_order", "name"]

    def __str__(self):
        return f"{self.name} ({self.short_code})"


class LabTestParameter(Coding):
    """One measurement within a test. This is the row results attach to."""

    NUMERIC = "numeric"
    TEXT = "text"
    CHOICE = "choice"
    VALUE_TYPES = [(NUMERIC, "Numeric"), (TEXT, "Text"), (CHOICE, "Choice")]

    test = models.ForeignKey(LabTest, on_delete=models.CASCADE, related_name="parameters")
    name = models.CharField(max_length=120)
    unit = models.CharField(max_length=30, blank=True)
    value_type = models.CharField(max_length=10, choices=VALUE_TYPES, default=NUMERIC)
    choices_csv = models.CharField(
        max_length=255, blank=True, help_text="For choice parameters, e.g. 'Positive,Negative'"
    )
    decimal_places = models.PositiveSmallIntegerField(default=1)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["test", "display_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["test", "name"], name="parameter_unique_per_test")
        ]

    def __str__(self):
        return f"{self.test.short_code}:{self.name}"

    def range_for(self, *, sex=None, age_years=None):
        """The most specific range that applies to this patient.

        Sex-specific beats any-sex, and a narrower age band beats a wider one, because
        a haemoglobin range for an adult woman is not the range for a newborn.
        """
        candidates = [
            reference for reference in self.reference_ranges.all()
            if reference.applies_to(sex=sex, age_years=age_years)
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda reference: reference.specificity, reverse=True)[0]


class ReferenceRange(models.Model):
    ANY = "any"
    SEX_CHOICES = [(ANY, "Any"), ("female", "Female"), ("male", "Male")]

    parameter = models.ForeignKey(
        LabTestParameter, on_delete=models.CASCADE, related_name="reference_ranges"
    )
    sex = models.CharField(max_length=10, choices=SEX_CHOICES, default=ANY)
    min_age_years = models.PositiveSmallIntegerField(null=True, blank=True)
    max_age_years = models.PositiveSmallIntegerField(null=True, blank=True)

    low = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    high = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    # Outside these, someone has to be told now rather than when the report is read.
    critical_low = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    critical_high = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["parameter", "sex", "min_age_years"]

    def __str__(self):
        bounds = f"{self.low or '—'}–{self.high or '—'}"
        return f"{self.parameter.name} {bounds} ({self.sex})"

    @property
    def specificity(self):
        score = 0
        if self.sex != self.ANY:
            score += 2
        if self.min_age_years is not None or self.max_age_years is not None:
            score += 1
        return score

    def applies_to(self, *, sex=None, age_years=None):
        if self.sex != self.ANY and sex is not None and self.sex != sex:
            return False
        if age_years is not None:
            if self.min_age_years is not None and age_years < self.min_age_years:
                return False
            if self.max_age_years is not None and age_years > self.max_age_years:
                return False
        elif self.min_age_years is not None or self.max_age_years is not None:
            # An age-banded range cannot be claimed for a patient of unknown age.
            return False
        return True

    def classify(self, value):
        """Return one of LabResult's flags for a numeric value."""
        if value is None:
            return LabResult.NORMAL
        if self.critical_low is not None and value <= self.critical_low:
            return LabResult.CRITICAL_LOW
        if self.critical_high is not None and value >= self.critical_high:
            return LabResult.CRITICAL_HIGH
        if self.low is not None and value < self.low:
            return LabResult.LOW
        if self.high is not None and value > self.high:
            return LabResult.HIGH
        return LabResult.NORMAL


class LabOrder(models.Model):
    ROUTINE = "routine"
    URGENT = "urgent"
    PRIORITY_CHOICES = [(ROUTINE, "Routine"), (URGENT, "Urgent")]

    order_number = models.CharField(max_length=40, unique=True, editable=False)
    visit = models.ForeignKey(
        "visits.Visit", on_delete=models.PROTECT, related_name="lab_orders"
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="lab_orders"
    )
    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT, related_name="lab_orders"
    )
    ordered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="lab_orders"
    )
    ordered_at = models.DateTimeField(default=timezone.now)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=ROUTINE)
    clinical_details = models.TextField(
        blank=True, help_text="Why the test was requested; the laboratory reads this."
    )

    class Meta:
        ordering = ["-ordered_at"]
        indexes = [models.Index(fields=["patient", "-ordered_at"])]

    def __str__(self):
        return f"{self.order_number} — {self.patient.full_name}"

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = NumberSequence.allocate("lab_order_number")
        return super().save(*args, **kwargs)


class LabOrderItem(models.Model):
    """One test on an order. Statuses advance in sequence and do not skip (AC-32)."""

    ORDERED = "ordered"
    COLLECTED = "collected"
    PROCESSING = "processing"
    RESULTED = "resulted"
    VERIFIED = "verified"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (ORDERED, "Ordered"), (COLLECTED, "Specimen collected"),
        (PROCESSING, "Processing"), (RESULTED, "Resulted, awaiting verification"),
        (VERIFIED, "Verified"), (CANCELLED, "Cancelled"),
    ]
    TRANSITIONS = {
        ORDERED: {COLLECTED, CANCELLED},
        COLLECTED: {PROCESSING, CANCELLED},
        PROCESSING: {RESULTED, CANCELLED},
        RESULTED: {VERIFIED, PROCESSING},
        VERIFIED: set(),
        CANCELLED: set(),
    }

    order = models.ForeignKey(LabOrder, on_delete=models.CASCADE, related_name="items")
    test = models.ForeignKey(LabTest, on_delete=models.PROTECT, related_name="order_items")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=ORDERED)
    cancelled_reason = models.CharField(max_length=255, blank=True)

    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="lab_items_verified",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    laboratory_comment = models.TextField(blank=True)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["order", "test"], name="test_once_per_order")
        ]
        permissions = [
            ("collect_specimen", "Can collect and label specimens"),
            # Deliberately separate from entering a result: signing a value off is a
            # different act from typing it in.
            ("verify_labresult", "Can verify and release laboratory results"),
        ]

    def __str__(self):
        return f"{self.test.short_code} ({self.status})"

    def advance_to(self, status):
        if status not in self.TRANSITIONS.get(self.status, set()):
            raise ValidationError(
                f"{self.test.name} cannot go from "
                f"{self.get_status_display().lower()} to "
                f"{dict(self.STATUS_CHOICES)[status].lower()}."
            )
        self.status = status


class Specimen(models.Model):
    """A physical sample, with the identifier that goes on the label."""

    ACCEPTABLE = "acceptable"
    HAEMOLYSED = "haemolysed"
    INSUFFICIENT = "insufficient"
    CLOTTED = "clotted"
    CONDITION_CHOICES = [
        (ACCEPTABLE, "Acceptable"), (HAEMOLYSED, "Haemolysed"),
        (INSUFFICIENT, "Insufficient volume"), (CLOTTED, "Clotted"),
    ]

    specimen_id = models.CharField(max_length=40, unique=True, editable=False)
    order_item = models.OneToOneField(
        LabOrderItem, on_delete=models.CASCADE, related_name="specimen"
    )
    specimen_type = models.CharField(max_length=15, choices=LabTest.SPECIMEN_CHOICES)
    collected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="specimens_collected"
    )
    collected_at = models.DateTimeField(default=timezone.now)
    condition = models.CharField(max_length=15, choices=CONDITION_CHOICES, default=ACCEPTABLE)
    note = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.specimen_id

    def save(self, *args, **kwargs):
        if not self.specimen_id:
            self.specimen_id = NumberSequence.allocate("specimen_id")
        return super().save(*args, **kwargs)


class LabResult(models.Model):
    """One value for one parameter, versioned.

    An amendment after verification never overwrites: the superseded row stays and the
    report shows the value as amended.
    """

    NORMAL = "normal"
    LOW = "low"
    HIGH = "high"
    CRITICAL_LOW = "critical_low"
    CRITICAL_HIGH = "critical_high"
    FLAG_CHOICES = [
        (NORMAL, "Normal"), (LOW, "Low"), (HIGH, "High"),
        (CRITICAL_LOW, "Critically low"), (CRITICAL_HIGH, "Critically high"),
    ]
    CRITICAL_FLAGS = {CRITICAL_LOW, CRITICAL_HIGH}
    ABNORMAL_FLAGS = {LOW, HIGH, CRITICAL_LOW, CRITICAL_HIGH}

    order_item = models.ForeignKey(
        LabOrderItem, on_delete=models.CASCADE, related_name="results"
    )
    parameter = models.ForeignKey(
        LabTestParameter, on_delete=models.PROTECT, related_name="results"
    )

    value_numeric = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True
    )
    value_text = models.CharField(max_length=255, blank=True)
    unit = models.CharField(max_length=30, blank=True)
    flag = models.CharField(max_length=15, choices=FLAG_CHOICES, default=NORMAL)

    # The range actually applied, copied so a later catalogue change cannot silently
    # re-interpret a historical result.
    range_low = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    range_high = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    range_note = models.CharField(max_length=255, blank=True)

    version = models.PositiveIntegerField(default=1)
    is_current = models.BooleanField(default=True)
    amends = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="amended_by"
    )
    amendment_reason = models.TextField(blank=True)

    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="lab_results_entered"
    )
    entered_at = models.DateTimeField(default=timezone.now)
    comment = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["order_item", "parameter__display_order", "version"]
        constraints = [
            models.UniqueConstraint(
                fields=["order_item", "parameter", "version"], name="result_version_unique"
            ),
            models.UniqueConstraint(
                fields=["order_item", "parameter"],
                condition=models.Q(is_current=True),
                name="one_current_result_per_parameter",
            ),
            models.CheckConstraint(
                condition=models.Q(version=1) | ~models.Q(amendment_reason=""),
                name="result_amendment_states_a_reason",
            ),
        ]
        permissions = [
            ("amend_labresult", "Can amend a verified laboratory result"),
            ("acknowledge_critical_result", "Can acknowledge a critical result"),
        ]

    def __str__(self):
        return f"{self.parameter.name} = {self.display_value} {self.unit}".strip()

    @property
    def display_value(self):
        if self.value_numeric is not None:
            places = self.parameter.decimal_places
            return f"{self.value_numeric:.{places}f}"
        return self.value_text

    @property
    def is_abnormal(self):
        return self.flag in self.ABNORMAL_FLAGS

    @property
    def is_critical(self):
        return self.flag in self.CRITICAL_FLAGS

    @property
    def flag_label(self):
        """Text, not colour. Colour alone fails accessibility and print."""
        return {
            self.NORMAL: "",
            self.LOW: "Low",
            self.HIGH: "High",
            self.CRITICAL_LOW: "CRITICAL LOW",
            self.CRITICAL_HIGH: "CRITICAL HIGH",
        }[self.flag]

    @property
    def reference_text(self):
        low, high = trim_decimal(self.range_low), trim_decimal(self.range_high)
        if low and high:
            return f"{low}–{high}"
        if low:
            return f"≥ {low}"
        if high:
            return f"≤ {high}"
        return self.range_note or ""


class CriticalResultAcknowledgement(models.Model):
    """Proof that someone was told, and what they did about it.

    A critical result that nobody acted on is the classic laboratory harm, so the
    acknowledgement is a record in its own right rather than a flag on the result.
    """

    result = models.ForeignKey(
        LabResult, on_delete=models.PROTECT, related_name="acknowledgements"
    )
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="critical_results_acknowledged",
    )
    acknowledged_at = models.DateTimeField(default=timezone.now)
    action_taken = models.TextField()

    class Meta:
        ordering = ["-acknowledged_at"]

    def __str__(self):
        return f"{self.result} acknowledged by {self.acknowledged_by.email}"

