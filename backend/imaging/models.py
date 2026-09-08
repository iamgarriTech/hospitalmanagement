"""Radiology: the catalogue, the request, and the report.

Its own app rather than part of `laboratory` because a radiology department is a
different department — different staff, different equipment, no specimen, and a
report that is prose rather than a set of numbers against reference ranges. The
two are parallel, not the same thing wearing different labels.

Two shapes are borrowed from the laboratory deliberately, because the clinical
requirement is identical and a second way of doing it would be a second thing to
keep correct:

**A report is versioned, never overwritten.** An amendment after verification
appends a version carrying its author and reason; the superseded text stays on
the record and prints as amended. A radiologist correcting "no fracture" to
"undisplaced fracture" must not erase what the first report said, because
somebody made a decision on it.

**A critical finding is not released until someone acknowledges it.** The
acknowledgement is a record in its own right — who was told, when, and what they
did — rather than a flag on the report. A critical finding nobody acted on is
the classic radiology harm.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import Coding
from patients.models import NumberSequence


class ImagingModality(models.Model):
    """X-ray, ultrasound, CT, MRI — and what a hospital actually has.

    A table rather than a choices list because "modular" means a hospital that
    owns an X-ray machine and nothing else should not see MRI on a request form.
    """

    name = models.CharField(max_length=60, unique=True)
    code = models.CharField(max_length=12, unique=True, help_text="DICOM-style, e.g. CR, US, CT")
    display_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "imaging modalities"
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name


class ImagingProcedure(Coding):
    """One examination a hospital offers. AC-94.

    Preparation instructions live here rather than in a leaflet: "nil by mouth
    for six hours" reaching the ward late is a cancelled slot and a patient who
    fasted for nothing.
    """

    modality = models.ForeignKey(
        ImagingModality, on_delete=models.PROTECT, related_name="procedures"
    )
    name = models.CharField(max_length=200)
    code_short = models.CharField(
        max_length=20, unique=True, help_text="What the department calls it, e.g. CXR"
    )
    body_part = models.CharField(max_length=100)
    preparation_instructions = models.TextField(
        blank=True, help_text="Shown to the ward and to the patient when the order is placed."
    )
    # Priced through the ordinary service machinery, so a change is audited like
    # any other price and is per facility.
    service = models.ForeignKey(
        "billing.Service", on_delete=models.PROTECT, null=True, blank=True,
        related_name="imaging_procedures",
    )
    typical_minutes = models.PositiveSmallIntegerField(
        default=15, help_text="Used for scheduling, not for billing."
    )
    requires_contrast = models.BooleanField(default=False)
    contraindications = models.CharField(
        max_length=255, blank=True,
        help_text="Shown at ordering. Pregnancy, pacemaker, renal impairment.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["modality__display_order", "name"]
        permissions = [
            ("verify_imagingreport", "Can verify and release an imaging report"),
            ("amend_imagingreport", "Can amend a verified imaging report"),
            ("acknowledge_critical_finding", "Can acknowledge a critical imaging finding"),
            ("perform_imaging", "Can record an examination as performed"),
            ("schedule_imaging", "Can schedule an imaging examination"),
        ]

    def __str__(self):
        return f"{self.name} ({self.code_short})"

    def price_at(self, facility):
        return self.service.price_at(facility) if self.service_id else None


class ImagingOrder(models.Model):
    """A request for imaging. AC-95.

    The clinical question is mandatory. A radiologist reporting "CT abdomen" with
    no idea what is being looked for produces a description rather than an
    answer, and the request form is where that goes wrong.
    """

    ROUTINE = "routine"
    URGENT = "urgent"
    PRIORITY_CHOICES = [(ROUTINE, "Routine"), (URGENT, "Urgent")]

    order_number = models.CharField(max_length=40, unique=True, editable=False)
    visit = models.ForeignKey(
        "visits.Visit", on_delete=models.PROTECT, null=True, blank=True,
        related_name="imaging_orders",
    )
    admission = models.ForeignKey(
        "inpatient.Admission", on_delete=models.PROTECT, null=True, blank=True,
        related_name="imaging_orders",
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="imaging_orders"
    )
    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT, related_name="imaging_orders"
    )
    ordered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="imaging_orders"
    )
    ordered_at = models.DateTimeField(default=timezone.now)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=ROUTINE)

    clinical_question = models.TextField(
        help_text="What the requesting clinician needs answered. The radiologist reads this."
    )
    relevant_history = models.TextField(blank=True)
    is_pregnant = models.BooleanField(
        default=False, help_text="Declared at ordering; the department needs it before ionising radiation."
    )

    class Meta:
        ordering = ["-ordered_at"]
        indexes = [models.Index(fields=["patient", "-ordered_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(visit__isnull=False) | models.Q(admission__isnull=False),
                name="imaging_order_belongs_to_a_visit_or_an_admission",
            ),
            models.CheckConstraint(
                condition=~models.Q(clinical_question=""),
                name="imaging_order_states_a_clinical_question",
            ),
        ]

    def __str__(self):
        return f"{self.order_number} — {self.patient.full_name}"

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = NumberSequence.allocate("imaging_order_number")
        return super().save(*args, **kwargs)


class ImagingOrderItem(models.Model):
    """One examination on a request, and where it has got to.

    AC-95: the states advance in sequence and do not skip. A study cannot be
    reported before it was performed, and "performed" is what the department
    bills and what the patient was exposed to.
    """

    REQUESTED = "requested"
    SCHEDULED = "scheduled"
    PERFORMED = "performed"
    REPORTED = "reported"
    VERIFIED = "verified"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (REQUESTED, "Requested"),
        (SCHEDULED, "Scheduled"),
        (PERFORMED, "Performed, awaiting a report"),
        (REPORTED, "Reported, awaiting verification"),
        (VERIFIED, "Verified"),
        (CANCELLED, "Cancelled"),
    ]
    TRANSITIONS = {
        REQUESTED: {SCHEDULED, PERFORMED, CANCELLED},
        SCHEDULED: {PERFORMED, CANCELLED},
        PERFORMED: {REPORTED, CANCELLED},
        # A report can go back for correction before it is signed off.
        REPORTED: {VERIFIED, PERFORMED},
        VERIFIED: set(),
        CANCELLED: set(),
    }

    order = models.ForeignKey(ImagingOrder, on_delete=models.CASCADE, related_name="items")
    procedure = models.ForeignKey(
        ImagingProcedure, on_delete=models.PROTECT, related_name="order_items"
    )
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=REQUESTED)
    cancelled_reason = models.CharField(max_length=255, blank=True)

    scheduled_for = models.DateTimeField(null=True, blank=True)
    scheduled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="imaging_scheduled",
    )

    performed_at = models.DateTimeField(null=True, blank=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="imaging_performed",
    )
    # What the patient was actually exposed to, recorded at the machine.
    accession_number = models.CharField(
        max_length=60, blank=True, help_text="The department's own study identifier."
    )
    views_taken = models.CharField(max_length=255, blank=True)
    technique_note = models.CharField(max_length=255, blank=True)
    contrast_given = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "procedure"], name="procedure_once_per_imaging_order"
            ),
            models.UniqueConstraint(
                fields=["accession_number"],
                condition=~models.Q(accession_number=""),
                name="accession_number_unique",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="cancelled") | ~models.Q(cancelled_reason=""),
                name="cancelled_imaging_states_a_reason",
            ),
            models.CheckConstraint(
                condition=~models.Q(status__in=["performed", "reported", "verified"])
                | models.Q(performed_at__isnull=False),
                name="performed_imaging_records_when",
            ),
        ]

    def __str__(self):
        return f"{self.procedure.code_short} ({self.status})"

    @property
    def current_report(self):
        """Walks the prefetched versions rather than filtering them.

        A filtered manager cannot use the prefetch cache, so `.filter(
        is_current=True)` re-queries per item — the mistake that cost the
        encounter list 158 queries in Phase 1 and the ward board 305 in Phase 2.
        """
        for report in self.reports.all():
            if report.is_current:
                return report
        return None

    @property
    def report_count(self):
        return len(self.reports.all())

    def advance_to(self, status):
        if status not in self.TRANSITIONS.get(self.status, set()):
            raise ValidationError(
                f"{self.procedure.name} cannot go from "
                f"{self.get_status_display().lower()} to "
                f"{dict(self.STATUS_CHOICES)[status].lower()}."
            )
        self.status = status


class ImagingReport(models.Model):
    """The radiologist's answer, versioned.

    Findings and conclusion are separate fields, not one blob: the conclusion is
    what a clinician acts on and what belongs in a discharge summary, and
    burying it at the end of a paragraph of findings is how it gets missed.
    """

    order_item = models.ForeignKey(
        ImagingOrderItem, on_delete=models.CASCADE, related_name="reports"
    )
    findings = models.TextField()
    conclusion = models.TextField()
    comparison = models.CharField(
        max_length=255, blank=True, help_text="Previous studies compared against."
    )
    # A critical finding is one that has to reach someone now — a
    # pneumothorax, a bleed. Flagged by the reporter, because no rule can
    # infer it from prose.
    is_critical = models.BooleanField(default=False)
    critical_finding = models.CharField(
        max_length=255, blank=True,
        help_text="What has to be acted on, in one line.",
    )

    version = models.PositiveIntegerField(default=1)
    is_current = models.BooleanField(default=True)
    amends = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="amended_by"
    )
    amendment_reason = models.TextField(blank=True)

    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="imaging_reports"
    )
    reported_at = models.DateTimeField(default=timezone.now)

    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="imaging_reports_verified",
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["order_item", "version"]
        constraints = [
            models.UniqueConstraint(
                fields=["order_item", "version"], name="imaging_report_version_unique"
            ),
            models.UniqueConstraint(
                fields=["order_item"],
                condition=models.Q(is_current=True),
                name="one_current_imaging_report",
            ),
            models.CheckConstraint(
                condition=models.Q(version=1) | ~models.Q(amendment_reason=""),
                name="imaging_amendment_states_a_reason",
            ),
            models.CheckConstraint(
                condition=models.Q(is_critical=False) | ~models.Q(critical_finding=""),
                name="critical_finding_says_what",
            ),
            models.CheckConstraint(
                condition=~models.Q(findings="") & ~models.Q(conclusion=""),
                name="imaging_report_has_findings_and_a_conclusion",
            ),
        ]

    def __str__(self):
        verb = "amended" if self.version > 1 else "reported"
        return f"{self.order_item.procedure.code_short} {verb} v{self.version}"

    @property
    def is_verified(self):
        return self.verified_at is not None

    @property
    def is_amended(self):
        return self.version > 1

    @property
    def status_label(self):
        """In words. AC-96 and AC-97 both turn on the reader being able to tell
        an unverified report from a signed one, and an amended one from the
        original — and colour is not available on paper."""
        if not self.is_verified:
            return "PROVISIONAL — not yet verified"
        if self.is_amended:
            return f"AMENDED (version {self.version})"
        return "Verified"

    @property
    def needs_acknowledgement(self):
        """A verified critical finding nobody has answered for."""
        return (
            self.is_critical
            and self.is_verified
            and not self.acknowledgements.exists()
        )


class CriticalFindingAcknowledgement(models.Model):
    """Proof that someone was told about a critical finding, and what they did.

    A parallel model to the laboratory's rather than one generic table: a direct
    foreign key keeps referential integrity and makes the audit trail readable,
    and a `GenericForeignKey` shared between two callers buys nothing but a
    lookup nobody can follow in SQL.
    """

    report = models.ForeignKey(
        ImagingReport, on_delete=models.PROTECT, related_name="acknowledgements"
    )
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="critical_findings_acknowledged",
    )
    acknowledged_at = models.DateTimeField(default=timezone.now)
    action_taken = models.TextField()

    class Meta:
        ordering = ["-acknowledged_at"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(action_taken=""),
                name="critical_finding_acknowledgement_says_what_was_done",
            )
        ]

    def __str__(self):
        return f"{self.report} acknowledged by {self.acknowledged_by.email}"

    @property
    def minutes_to_acknowledge(self):
        reported = self.report.verified_at or self.report.reported_at
        return int((self.acknowledged_at - reported).total_seconds() // 60)
