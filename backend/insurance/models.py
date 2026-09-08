"""Insurance and HMO: who covers a patient, for what, and what the scheme owes.

One decision shapes this whole app, and it is AC-124.

**Coverage is resolved once, at the time of service, and the answer is stored on
the charge.** Not recomputed when an invoice is displayed, not looked up through
a live foreign key to the plan. A scheme renegotiates its rates in March; a
patient treated in February owed what February's rules said they owed, and a
system that recomputes will quietly tell them otherwise — usually while they are
standing at the cash desk holding a receipt that disagrees.

So `ChargeCoverage` carries the split *and* a copy of the rule that produced it.
The plan can be edited, superseded or deleted afterwards and the February answer
does not move.

The second decision is smaller but load-bearing: **care is never blocked by
insurance**. A missing authorisation, an unverified policy, an unreachable HMO —
each of these holds the *claim*, never the treatment. A hospital cannot refuse a
sick patient while waiting for someone to answer a telephone, and a system that
makes that easy to do is a system that will be used to do it.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from patients.models import NumberSequence

ZERO = Decimal("0.00")


class InsuranceProvider(models.Model):
    """An insurer or HMO.

    `is_accepting_claims` exists because Nigerian HMOs go quiet — a provider can
    be switched off without deleting a history of policies and claims that still
    has to be readable and chased.
    """

    HMO = "hmo"
    INSURER = "insurer"
    GOVERNMENT = "government"
    CORPORATE = "corporate"
    TYPE_CHOICES = [
        (HMO, "HMO"),
        (INSURER, "Private insurer"),
        (GOVERNMENT, "Government scheme"),
        (CORPORATE, "Corporate account"),
    ]

    # How claims physically reach them. Deliberately not an integration: most
    # Nigerian HMOs take a portal upload or an emailed spreadsheet, and
    # pretending otherwise would build the wrong thing.
    PORTAL = "portal"
    EMAIL = "email"
    PAPER = "paper"
    API = "api"
    CHANNEL_CHOICES = [
        (PORTAL, "Provider portal"), (EMAIL, "Email"),
        (PAPER, "Paper / hand delivered"), (API, "API"),
    ]

    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=20, unique=True)
    provider_type = models.CharField(max_length=12, choices=TYPE_CHOICES, default=HMO)

    contact_name = models.CharField(max_length=200, blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    contact_email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)

    claim_channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES, default=PORTAL)
    claim_submission_note = models.CharField(
        max_length=255, blank=True,
        help_text="Where claims actually go. A portal URL, an address, a person.",
    )
    # How long they say they take, so the ageing report can show what is late
    # rather than only what is outstanding.
    settlement_days = models.PositiveSmallIntegerField(
        default=30, help_text="Days they undertake to settle in."
    )

    is_accepting_claims = models.BooleanField(
        default=True,
        help_text="Turn off a provider that has stopped paying. History stays readable.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        permissions = [
            ("manage_coverage", "Can configure providers, plans and coverage rules"),
            ("verify_eligibility", "Can record an eligibility check"),
            ("request_preauthorisation", "Can request and record a preauthorisation"),
            ("submit_claim", "Can submit a claim to a provider"),
            ("record_claim_outcome", "Can record an acknowledgement, rejection or payment"),
            ("write_off_claim_shortfall", "Can write off an unpaid claim balance"),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Plan(models.Model):
    """One product a provider sells, and the shape of what it covers.

    The default is stated on the plan rather than assumed, because schemes
    differ on the important question: whether a service nobody wrote a rule for
    is covered or not. Guessing "covered" bills the scheme for things it will
    reject; guessing "not covered" surprises the patient. So the hospital says
    which, per plan, and AC-126 makes the unruled case visible either way.
    """

    provider = models.ForeignKey(
        InsuranceProvider, on_delete=models.PROTECT, related_name="plans"
    )
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=30)

    # What happens to a service with no rule. Both are real scheme behaviours.
    COVERED = "covered"
    EXCLUDED = "excluded"
    DEFAULT_CHOICES = [
        (COVERED, "Covered at the plan's default rate"),
        (EXCLUDED, "Not covered — the patient pays"),
    ]
    unruled_services = models.CharField(
        max_length=10, choices=DEFAULT_CHOICES, default=EXCLUDED,
        help_text="What this plan does with a service no rule mentions.",
    )
    default_scheme_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("100.00"),
        help_text="Percentage the scheme pays where a rule does not say otherwise.",
    )

    # Limits, which are what actually catches a hospital out at year end.
    annual_limit = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Total the scheme will pay per patient per year. Blank for none.",
    )
    per_visit_limit = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    requires_preauthorisation_above = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Any single charge above this needs an authorisation reference.",
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["provider__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "code"], name="plan_code_unique_per_provider"
            ),
            models.CheckConstraint(
                condition=models.Q(default_scheme_percent__gte=0)
                & models.Q(default_scheme_percent__lte=100),
                name="plan_default_percent_is_a_percentage",
            ),
        ]

    def __str__(self):
        return f"{self.provider.code} {self.name}"


class CoverageRule(models.Model):
    """What a plan does with one service, or one whole category of them.

    A rule on a category is the common case — "consultations at 90%, laboratory
    at 100%, cosmetic excluded" — with a service-level rule overriding it. Both
    live in one table because the resolution order is the interesting part and
    splitting them across two would put that order in two places.
    """

    FIXED_COPAY = "fixed_copay"
    PERCENTAGE = "percentage"
    EXCLUDED = "excluded"
    FULL = "full"
    BASIS_CHOICES = [
        (FULL, "Scheme pays in full"),
        (PERCENTAGE, "Scheme pays a percentage"),
        (FIXED_COPAY, "Patient pays a fixed co-pay, scheme pays the rest"),
        (EXCLUDED, "Not covered — the patient pays"),
    ]

    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="rules")
    # Exactly one of these. A service rule beats a category rule.
    service = models.ForeignKey(
        "billing.Service", on_delete=models.CASCADE, null=True, blank=True,
        related_name="coverage_rules",
    )
    category = models.ForeignKey(
        "billing.ServiceCategory", on_delete=models.CASCADE, null=True, blank=True,
        related_name="coverage_rules",
    )

    basis = models.CharField(max_length=12, choices=BASIS_CHOICES, default=FULL)
    scheme_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    patient_copay = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    requires_preauthorisation = models.BooleanField(default=False)
    exclusion_reason = models.CharField(
        max_length=255, blank=True,
        help_text="Shown on the invoice line. An unexplained amount is a dispute.",
    )
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["plan", "category__display_order", "service__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "service"],
                condition=models.Q(service__isnull=False),
                name="one_rule_per_plan_and_service",
            ),
            models.UniqueConstraint(
                fields=["plan", "category"],
                condition=models.Q(category__isnull=False),
                name="one_rule_per_plan_and_category",
            ),
            # A rule about nothing, or about both at once, has no resolution
            # order. Refused rather than resolved arbitrarily.
            models.CheckConstraint(
                condition=(
                    models.Q(service__isnull=False, category__isnull=True)
                    | models.Q(service__isnull=True, category__isnull=False)
                ),
                name="rule_names_a_service_or_a_category_not_both",
            ),
            models.CheckConstraint(
                condition=~models.Q(basis="percentage")
                | models.Q(scheme_percent__isnull=False),
                name="percentage_rule_states_a_percentage",
            ),
            models.CheckConstraint(
                condition=~models.Q(basis="fixed_copay")
                | models.Q(patient_copay__isnull=False),
                name="copay_rule_states_a_copay",
            ),
            models.CheckConstraint(
                condition=~models.Q(basis="excluded") | ~models.Q(exclusion_reason=""),
                name="exclusion_states_a_reason",
            ),
        ]

    def __str__(self):
        target = self.service or self.category
        return f"{self.plan}: {target} — {self.get_basis_display()}"


class PatientPolicy(models.Model):
    """A patient's membership of a plan.

    Two active policies are allowed, because a patient can hold an employer HMO
    and a private top-up, and `precedence` says which pays first. Storing the
    order rather than inferring it means the billing office can change it for
    one patient without a rule change.
    """

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="policies"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="policies")
    policy_number = models.CharField(max_length=60)
    member_name = models.CharField(
        max_length=200, blank=True,
        help_text="The principal member, where the patient is a dependant.",
    )
    is_dependant = models.BooleanField(default=False)
    relationship = models.CharField(max_length=60, blank=True)

    starts_on = models.DateField()
    ends_on = models.DateField(
        null=True, blank=True, help_text="Blank for an open-ended policy."
    )
    precedence = models.PositiveSmallIntegerField(
        default=1, help_text="1 pays first. Only matters where a patient holds two."
    )

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="policies_recorded"
    )
    recorded_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "patient policies"
        ordering = ["patient", "precedence"]
        indexes = [models.Index(fields=["patient", "is_active"])]
        constraints = [
            models.UniqueConstraint(
                fields=["patient", "plan", "policy_number"],
                name="one_policy_per_patient_plan_and_number",
            ),
            models.CheckConstraint(
                condition=models.Q(ends_on__isnull=True)
                | models.Q(ends_on__gte=models.F("starts_on")),
                name="policy_ends_after_it_starts",
            ),
            models.CheckConstraint(
                condition=models.Q(is_dependant=False) | ~models.Q(relationship=""),
                name="dependant_states_a_relationship",
            ),
        ]

    def __str__(self):
        return f"{self.plan} — {self.policy_number}"

    def covers(self, on=None):
        """Whether this policy is in force on a date.

        Takes the date of *service*, never today: a claim assembled in April for
        a February attendance is judged against February.
        """
        day = on or timezone.localdate()
        if not self.is_active:
            return False
        if self.starts_on > day:
            return False
        return self.ends_on is None or self.ends_on >= day

    @property
    def is_current(self):
        return self.covers()

    @property
    def latest_eligibility(self):
        for check in self.eligibility_checks.all():
            return check
        return None


class EligibilityCheck(models.Model):
    """Somebody rang the HMO. This is what they said.

    A record rather than a flag, because "we checked and they said yes on the
    3rd" is a different fact from "this policy is valid", and it is the first
    one a provider disputes. AC-128: an unverified policy stays usable — a
    hospital cannot refuse care while waiting for a scheme to answer.
    """

    CONFIRMED = "confirmed"
    DECLINED = "declined"
    UNREACHABLE = "unreachable"
    OUTCOME_CHOICES = [
        (CONFIRMED, "Confirmed eligible"),
        (DECLINED, "Declined by the provider"),
        (UNREACHABLE, "Provider could not be reached"),
    ]

    policy = models.ForeignKey(
        PatientPolicy, on_delete=models.CASCADE, related_name="eligibility_checks"
    )
    outcome = models.CharField(max_length=12, choices=OUTCOME_CHOICES)
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="eligibility_checks",
    )
    checked_at = models.DateTimeField(default=timezone.now)
    reference = models.CharField(max_length=120, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-checked_at"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(outcome="declined") | ~models.Q(note=""),
                name="declined_eligibility_states_why",
            )
        ]

    def __str__(self):
        return f"{self.policy} — {self.get_outcome_display()} {self.checked_at:%d %b}"

    @property
    def is_current(self):
        if self.outcome != self.CONFIRMED:
            return False
        return self.valid_until is None or self.valid_until >= timezone.localdate()


class Preauthorisation(models.Model):
    """A scheme's agreement, in advance, to pay for something specific.

    AC-131: this never gates the treatment. `is_valid_for` gates the *claim*.
    """

    REQUESTED = "requested"
    APPROVED = "approved"
    DECLINED = "declined"
    EXPIRED = "expired"
    STATUS_CHOICES = [
        (REQUESTED, "Requested"), (APPROVED, "Approved"),
        (DECLINED, "Declined"), (EXPIRED, "Expired"),
    ]

    policy = models.ForeignKey(
        PatientPolicy, on_delete=models.PROTECT, related_name="preauthorisations"
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="preauthorisations"
    )
    visit = models.ForeignKey(
        "visits.Visit", on_delete=models.PROTECT, null=True, blank=True,
        related_name="preauthorisations",
    )
    admission = models.ForeignKey(
        "inpatient.Admission", on_delete=models.PROTECT, null=True, blank=True,
        related_name="preauthorisations",
    )

    requested_for = models.TextField(help_text="What is being asked for, in words.")
    services = models.ManyToManyField(
        "billing.Service", blank=True, related_name="preauthorisations",
        help_text="The services this authorisation covers.",
    )
    estimated_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=REQUESTED)
    reference = models.CharField(
        max_length=120, blank=True,
        help_text="The provider's authorisation code. A claim needs this.",
    )
    approved_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    decline_reason = models.CharField(max_length=255, blank=True)

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="preauthorisations_requested",
    )
    requested_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]
        indexes = [models.Index(fields=["patient", "-requested_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["reference"],
                condition=~models.Q(reference=""),
                name="preauthorisation_reference_unique",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="approved") | ~models.Q(reference=""),
                name="approved_preauthorisation_has_a_reference",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="declined") | ~models.Q(decline_reason=""),
                name="declined_preauthorisation_states_why",
            ),
        ]

    def __str__(self):
        return f"{self.reference or 'unreferenced'} ({self.status})"

    def is_valid_for(self, service, on=None):
        """Whether this authorisation actually satisfies a claim for a service.

        Approved is not enough: it has to be approved, in date, and for this
        service. An expired authorisation satisfying a claim is AC-130's
        negative case.
        """
        if self.status != self.APPROVED:
            return False
        day = on or timezone.localdate()
        if self.valid_from and self.valid_from > day:
            return False
        if self.valid_until and self.valid_until < day:
            return False
        # An authorisation with no services listed is a blanket one for the
        # episode, which is how schemes often issue them.
        return not self.services.exists() or self.services.filter(pk=service.pk).exists()


class ChargeCoverage(models.Model):
    """How one charge was split between the scheme and the patient.

    **The whole point of this table is that it is a copy.** The rule that
    produced the split is written down here in full — the basis, the percentage,
    the co-pay, the exclusion reason — so the answer survives the plan being
    edited, superseded or deleted. AC-124.

    One row per invoice line. A line with no row is a line nobody has resolved
    yet, which is different from a line the patient pays in full.
    """

    SCHEME = "scheme"
    PATIENT = "patient"

    invoice_item = models.OneToOneField(
        "billing.InvoiceItem", on_delete=models.CASCADE, related_name="coverage"
    )
    policy = models.ForeignKey(
        PatientPolicy, on_delete=models.PROTECT, null=True, blank=True,
        related_name="charge_coverages",
    )

    scheme_amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    patient_amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)

    # --- the rule, copied ----------------------------------------------------
    basis = models.CharField(max_length=12, choices=CoverageRule.BASIS_CHOICES)
    applied_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    applied_copay = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    rule_description = models.CharField(
        max_length=255,
        help_text="How this split was arrived at, in words, for the patient.",
    )
    # Kept for traceability but nullable and SET_NULL: the copy above is the
    # authority, and configuration must stay deletable.
    rule = models.ForeignKey(
        CoverageRule, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="applied_to",
    )
    preauthorisation = models.ForeignKey(
        Preauthorisation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="charge_coverages",
    )

    # Why this line is not claimable yet, if it is not. Never blocks the
    # treatment — only the claim. AC-131.
    HELD_NO_PREAUTH = "no_preauthorisation"
    HELD_EXPIRED_PREAUTH = "expired_preauthorisation"
    HELD_NO_RULE = "no_rule"
    HELD_LIMIT = "limit_reached"
    HOLD_CHOICES = [
        (HELD_NO_PREAUTH, "Awaiting preauthorisation"),
        (HELD_EXPIRED_PREAUTH, "Preauthorisation expired"),
        (HELD_NO_RULE, "No coverage rule for this service"),
        (HELD_LIMIT, "Scheme limit reached"),
    ]
    hold_reason = models.CharField(max_length=30, choices=HOLD_CHOICES, blank=True)

    resolved_at = models.DateTimeField(default=timezone.now)
    service_date = models.DateField(
        help_text="The date the rules were judged against. Not the invoice date.",
    )

    class Meta:
        verbose_name_plural = "charge coverages"
        ordering = ["invoice_item"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(scheme_amount__gte=0) & models.Q(patient_amount__gte=0),
                name="coverage_amounts_not_negative",
            ),
            models.CheckConstraint(
                condition=~models.Q(rule_description=""),
                name="coverage_explains_itself",
            ),
        ]

    def __str__(self):
        return f"scheme {self.scheme_amount}, patient {self.patient_amount}"

    @property
    def is_claimable(self):
        """Whether this line can go on a claim.

        Held lines are not claimable and are not lost either: they sit on the
        billing office's list until the authorisation arrives.

        Wrapped in `bool` deliberately: `and` yields its last operand, so this
        returned the policy's primary key rather than True — a field named
        `is_claimable` serialising as `27` is the kind of thing a client reads
        once and gets wrong forever.
        """
        return bool(
            self.scheme_amount > ZERO and not self.hold_reason and self.policy_id
        )


class ClaimBatch(models.Model):
    """A claim: lines for one provider, submitted together.

    Named a batch because that is what it is in practice — a hospital sends a
    provider a month of lines, not one claim per patient. The state machine is
    on the batch, and rejection is per line, because that is how providers
    actually respond.
    """

    DRAFT = "draft"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    PART_PAID = "part_paid"
    PAID = "paid"
    REJECTED = "rejected"
    STATUS_CHOICES = [
        (DRAFT, "Draft"),
        (SUBMITTED, "Submitted"),
        (ACKNOWLEDGED, "Acknowledged by the provider"),
        (PART_PAID, "Part paid"),
        (PAID, "Settled"),
        (REJECTED, "Rejected"),
    ]
    TRANSITIONS = {
        DRAFT: {SUBMITTED},
        SUBMITTED: {ACKNOWLEDGED, REJECTED},
        ACKNOWLEDGED: {PART_PAID, PAID, REJECTED},
        PART_PAID: {PAID, REJECTED},
        REJECTED: set(),
        PAID: set(),
    }

    claim_number = models.CharField(max_length=40, unique=True, editable=False)
    provider = models.ForeignKey(
        InsuranceProvider, on_delete=models.PROTECT, related_name="claims"
    )
    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT, related_name="claims"
    )
    period_start = models.DateField()
    period_end = models.DateField()

    status = models.CharField(max_length=14, choices=STATUS_CHOICES, default=DRAFT)

    # A resubmission points at what it replaces. AC-135: the partial unique
    # constraint below is what stops one rejected claim spawning two.
    resubmits = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True,
        related_name="resubmitted_as",
    )
    resubmission_reason = models.CharField(max_length=255, blank=True)

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="claims_submitted",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    provider_reference = models.CharField(max_length=120, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="claims_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "claim batches"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["provider", "status", "-created_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(period_end__gte=models.F("period_start")),
                name="claim_period_ends_after_it_starts",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="rejected") | ~models.Q(rejection_reason=""),
                name="rejected_claim_states_why",
            ),
            models.CheckConstraint(
                condition=models.Q(resubmits__isnull=True)
                | ~models.Q(resubmission_reason=""),
                name="resubmission_states_why",
            ),
            models.CheckConstraint(
                condition=~models.Q(status__in=["submitted", "acknowledged", "part_paid",
                                                "paid"])
                | models.Q(submitted_at__isnull=False),
                name="submitted_claim_records_when",
            ),
        ]

    def __str__(self):
        return f"{self.claim_number} — {self.provider.code} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.claim_number:
            self.claim_number = NumberSequence.allocate("claim_number")
        return super().save(*args, **kwargs)

    def advance_to(self, status):
        if status not in self.TRANSITIONS.get(self.status, set()):
            raise ValidationError(
                f"A {self.get_status_display().lower()} claim cannot become "
                f"{dict(self.STATUS_CHOICES)[status].lower()}."
            )
        self.status = status

    @property
    def claimed_total(self):
        return sum((line.claimed_amount for line in self.lines.all()), ZERO)

    @property
    def paid_total(self):
        return sum((line.paid_amount for line in self.lines.all()), ZERO)

    @property
    def outstanding(self):
        return self.claimed_total - self.paid_total - self.written_off_total

    @property
    def written_off_total(self):
        return sum((line.written_off_amount for line in self.lines.all()), ZERO)

    @property
    def days_outstanding(self):
        if self.submitted_at is None:
            return None
        return (timezone.now().date() - self.submitted_at.date()).days

    @property
    def is_overdue(self):
        days = self.days_outstanding
        return (
            days is not None
            and self.status not in (self.PAID, self.REJECTED)
            and days > self.provider.settlement_days
        )


class ClaimLine(models.Model):
    """One charge on one claim.

    AC-134's constraint is the partial unique below: a charge can be on one
    *live* claim only. A charge on a rejected claim is free to go onto its
    resubmission, which is what makes AC-135 work without special-casing.
    """

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PENDING = "pending"
    LINE_STATUS = [
        (PENDING, "Awaiting the provider"),
        (ACCEPTED, "Accepted"),
        (REJECTED, "Rejected"),
    ]

    claim = models.ForeignKey(ClaimBatch, on_delete=models.CASCADE, related_name="lines")
    coverage = models.ForeignKey(
        ChargeCoverage, on_delete=models.PROTECT, related_name="claim_lines"
    )
    # Denormalised on purpose: a claim is a statement made on a date, and it has
    # to print the same way years later even if the service was renamed.
    patient_name = models.CharField(max_length=200)
    policy_number = models.CharField(max_length=60)
    service_description = models.CharField(max_length=255)
    service_code = models.CharField(max_length=30, blank=True)
    service_date = models.DateField()
    diagnosis_codes = models.CharField(max_length=255, blank=True)
    clinician = models.CharField(max_length=200, blank=True)
    authorisation_reference = models.CharField(max_length=120, blank=True)

    claimed_amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    written_off_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO
    )
    moved_to_patient_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO
    )

    status = models.CharField(max_length=10, choices=LINE_STATUS, default=PENDING)
    rejection_reason = models.CharField(max_length=255, blank=True)
    shortfall_reason = models.CharField(
        max_length=255, blank=True,
        help_text="Why the scheme paid less than claimed. Required to write off.",
    )

    class Meta:
        ordering = ["claim", "service_date", "id"]
        constraints = [
            # AC-134. A coverage row belongs to at most one claim that is still
            # alive; a rejected claim releases its lines for resubmission.
            models.UniqueConstraint(
                fields=["coverage"],
                condition=~models.Q(status="rejected"),
                name="one_live_claim_line_per_charge",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="rejected") | ~models.Q(rejection_reason=""),
                name="rejected_line_states_why",
            ),
            models.CheckConstraint(
                condition=models.Q(written_off_amount=0) | ~models.Q(shortfall_reason=""),
                name="write_off_states_why",
            ),
            models.CheckConstraint(
                condition=models.Q(paid_amount__gte=0)
                & models.Q(written_off_amount__gte=0)
                & models.Q(moved_to_patient_amount__gte=0),
                name="claim_line_amounts_not_negative",
            ),
        ]

    def __str__(self):
        return f"{self.service_description} {self.claimed_amount}"

    @property
    def unsettled(self):
        return (
            self.claimed_amount
            - self.paid_amount
            - self.written_off_amount
            - self.moved_to_patient_amount
        )


class ProviderPayment(models.Model):
    """Money actually received from a provider.

    Separate from the claim because one payment settles many claims and one
    claim is often settled by several payments, which is exactly the shape that
    gets reconciled wrongly when it is modelled as a field on the claim.
    """

    provider = models.ForeignKey(
        InsuranceProvider, on_delete=models.PROTECT, related_name="payments"
    )
    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT, related_name="provider_payments"
    )
    reference = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    received_on = models.DateField()
    method = models.ForeignKey(
        "billing.PaymentMethod", on_delete=models.PROTECT, related_name="provider_payments"
    )

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="provider_payments_recorded",
    )
    recorded_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True)

    # Reconciled money does not change. AC-138, the same guarantee as cash.
    reconciled_at = models.DateTimeField(null=True, blank=True)
    reconciled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="provider_payments_reconciled",
    )

    class Meta:
        ordering = ["-received_on", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "reference"],
                name="one_payment_per_provider_reference",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="provider_payment_is_positive"
            ),
        ]

    def __str__(self):
        return f"{self.provider.code} {self.reference} {self.amount}"

    @property
    def allocated(self):
        return sum((entry.amount for entry in self.allocations.all()), ZERO)

    @property
    def unallocated(self):
        return self.amount - self.allocated

    @property
    def is_frozen(self):
        return self.reconciled_at is not None


class PaymentAllocation(models.Model):
    """Which claim line a provider's money was applied to.

    The join that makes reconciliation possible per line, which is what AC-137
    needs: a short payment has to be visible against the line it short-paid, not
    as a lump difference on a claim.
    """

    payment = models.ForeignKey(
        ProviderPayment, on_delete=models.PROTECT, related_name="allocations"
    )
    line = models.ForeignKey(
        ClaimLine, on_delete=models.PROTECT, related_name="allocations"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    allocated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["payment", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["payment", "line"], name="one_allocation_per_payment_and_line"
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="allocation_is_positive"
            ),
        ]

    def __str__(self):
        return f"{self.amount} → {self.line}"
