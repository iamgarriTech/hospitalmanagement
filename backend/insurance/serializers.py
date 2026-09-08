from rest_framework import serializers

from patients.serializers import PatientSummarySerializer

from .models import (
    ChargeCoverage,
    ClaimBatch,
    ClaimLine,
    CoverageRule,
    EligibilityCheck,
    InsuranceProvider,
    PatientPolicy,
    Plan,
    Preauthorisation,
    ProviderPayment,
)


class InsuranceProviderSerializer(serializers.ModelSerializer):
    provider_type_display = serializers.CharField(
        source="get_provider_type_display", read_only=True
    )
    claim_channel_display = serializers.CharField(
        source="get_claim_channel_display", read_only=True
    )
    plan_count = serializers.SerializerMethodField()

    class Meta:
        model = InsuranceProvider
        fields = [
            "id", "name", "code", "provider_type", "provider_type_display",
            "contact_name", "contact_phone", "contact_email", "address",
            "claim_channel", "claim_channel_display", "claim_submission_note",
            "settlement_days", "is_accepting_claims", "is_active", "plan_count",
        ]

    def get_plan_count(self, provider) -> int:
        return provider.plans.count()


class CoverageRuleSerializer(serializers.ModelSerializer):
    basis_display = serializers.CharField(source="get_basis_display", read_only=True)
    service_name = serializers.CharField(
        source="service.name", read_only=True, default=None
    )
    category_name = serializers.CharField(
        source="category.name", read_only=True, default=None
    )

    class Meta:
        model = CoverageRule
        fields = [
            "id", "plan", "service", "service_name", "category", "category_name",
            "basis", "basis_display", "scheme_percent", "patient_copay",
            "requires_preauthorisation", "exclusion_reason", "note",
        ]

    def validate(self, attrs):
        """The shapes the database refuses, refused earlier and in words.

        A constraint violation reaching the client as a 500 tells a billing
        officer nothing they can act on.
        """
        service = attrs.get("service", getattr(self.instance, "service", None))
        category = attrs.get("category", getattr(self.instance, "category", None))
        if bool(service) == bool(category):
            raise serializers.ValidationError(
                "A rule names a service or a category, not both and not neither — "
                "otherwise there is no order in which to apply it."
            )
        basis = attrs.get("basis", getattr(self.instance, "basis", None))
        if basis == CoverageRule.PERCENTAGE and attrs.get("scheme_percent") is None:
            raise serializers.ValidationError(
                {"scheme_percent": "Say what percentage the scheme pays."}
            )
        if basis == CoverageRule.FIXED_COPAY and attrs.get("patient_copay") is None:
            raise serializers.ValidationError(
                {"patient_copay": "Say what the patient pays."}
            )
        if basis == CoverageRule.EXCLUDED and not (
            attrs.get("exclusion_reason") or ""
        ).strip():
            raise serializers.ValidationError({
                "exclusion_reason": "An exclusion is printed on the invoice line. An "
                                    "unexplained amount is a dispute."
            })
        return attrs


class PlanSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source="provider.name", read_only=True)
    provider_code = serializers.CharField(source="provider.code", read_only=True)
    rules = CoverageRuleSerializer(many=True, read_only=True)
    unruled_display = serializers.CharField(
        source="get_unruled_services_display", read_only=True
    )

    class Meta:
        model = Plan
        fields = [
            "id", "provider", "provider_name", "provider_code", "name", "code",
            "unruled_services", "unruled_display", "default_scheme_percent",
            "annual_limit", "per_visit_limit", "requires_preauthorisation_above",
            "is_active", "rules",
        ]


class EligibilityCheckSerializer(serializers.ModelSerializer):
    outcome_display = serializers.CharField(source="get_outcome_display", read_only=True)
    checked_by_name = serializers.CharField(source="checked_by.full_name", read_only=True)
    is_current = serializers.BooleanField(read_only=True)

    class Meta:
        model = EligibilityCheck
        fields = [
            "id", "policy", "outcome", "outcome_display", "checked_by",
            "checked_by_name", "checked_at", "reference", "valid_until", "note",
            "is_current",
        ]
        read_only_fields = ["id", "checked_by", "checked_at"]

    def validate(self, attrs):
        if attrs.get("outcome") == EligibilityCheck.DECLINED and not (
            attrs.get("note") or ""
        ).strip():
            raise serializers.ValidationError(
                {"note": "A decline with no reason cannot be argued with."}
            )
        return attrs


class PatientPolicySerializer(serializers.ModelSerializer):
    plan_detail = PlanSerializer(source="plan", read_only=True)
    provider_name = serializers.CharField(source="plan.provider.name", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    is_current = serializers.BooleanField(read_only=True)
    eligibility = serializers.SerializerMethodField()

    class Meta:
        model = PatientPolicy
        fields = [
            "id", "patient", "patient_name", "plan", "plan_detail", "provider_name",
            "policy_number", "member_name", "is_dependant", "relationship",
            "starts_on", "ends_on", "precedence", "is_active", "is_current",
            "eligibility", "recorded_by", "recorded_at",
        ]
        read_only_fields = ["id", "recorded_by", "recorded_at"]

    def get_eligibility(self, policy) -> dict | None:
        """The latest check, and whether it still stands.

        Surfaced on the policy because the point-of-service screens need to know
        "has anyone rung them, and what did they say" without a second request —
        and an unverified policy is still usable, so this is information rather
        than a gate.
        """
        check = policy.latest_eligibility
        if check is None:
            return None
        return {
            "outcome": check.outcome,
            "outcome_display": check.get_outcome_display(),
            "checked_at": check.checked_at,
            "checked_by": check.checked_by.full_name,
            "reference": check.reference,
            "valid_until": check.valid_until,
            "is_current": check.is_current,
        }

    def validate(self, attrs):
        if attrs.get("is_dependant") and not (attrs.get("relationship") or "").strip():
            raise serializers.ValidationError(
                {"relationship": "Say how the patient relates to the principal member."}
            )
        ends = attrs.get("ends_on")
        starts = attrs.get("starts_on")
        if ends and starts and ends < starts:
            raise serializers.ValidationError(
                {"ends_on": "A policy cannot end before it starts."}
            )
        return attrs


class PreauthorisationSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    provider_name = serializers.CharField(
        source="policy.plan.provider.name", read_only=True
    )
    policy_number = serializers.CharField(source="policy.policy_number", read_only=True)
    requested_by_name = serializers.CharField(
        source="requested_by.full_name", read_only=True
    )
    service_names = serializers.SerializerMethodField()

    class Meta:
        model = Preauthorisation
        fields = [
            "id", "policy", "policy_number", "provider_name", "patient",
            "patient_name", "visit", "admission", "requested_for", "services",
            "service_names", "estimated_amount", "status", "status_display",
            "reference", "approved_amount", "valid_from", "valid_until",
            "decline_reason", "requested_by", "requested_by_name", "requested_at",
            "decided_at",
        ]
        read_only_fields = [
            "id", "patient", "status", "reference", "approved_amount",
            "valid_from", "valid_until", "decline_reason", "requested_by",
            "requested_at", "decided_at",
        ]

    def get_service_names(self, authorisation) -> list[str]:
        return [service.name for service in authorisation.services.all()]


class DecidePreauthorisationSerializer(serializers.Serializer):
    """Recording what the provider said.

    An approval needs a reference because a claim needs one; a decline needs a
    reason because somebody has to explain it to the patient.
    """

    outcome = serializers.ChoiceField(choices=["approved", "declined"])
    reference = serializers.CharField(required=False, allow_blank=True, default="")
    approved_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True
    )
    valid_from = serializers.DateField(required=False, allow_null=True)
    valid_until = serializers.DateField(required=False, allow_null=True)
    decline_reason = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if attrs["outcome"] == "approved" and not attrs.get("reference", "").strip():
            raise serializers.ValidationError({
                "reference": "A claim cannot be made without the provider's "
                             "authorisation reference."
            })
        if attrs["outcome"] == "declined" and not attrs.get("decline_reason", "").strip():
            raise serializers.ValidationError(
                {"decline_reason": "Say why it was declined."}
            )
        return attrs


class ChargeCoverageSerializer(serializers.ModelSerializer):
    """How one charge was split, and why.

    Every field here is read-only on purpose. The split is decided once, when
    the charge is raised, and this is a record of that decision — an endpoint
    that could edit it would be an endpoint that rewrites what a patient owed.
    """

    patient_name = serializers.CharField(
        source="invoice_item.invoice.patient.full_name", read_only=True
    )
    description = serializers.CharField(
        source="invoice_item.description", read_only=True
    )
    invoice_number = serializers.CharField(
        source="invoice_item.invoice.invoice_number", read_only=True
    )
    provider_code = serializers.CharField(
        source="policy.plan.provider.code", read_only=True, default=None
    )
    policy_number = serializers.CharField(
        source="policy.policy_number", read_only=True, default=None
    )
    basis_display = serializers.CharField(source="get_basis_display", read_only=True)
    hold_display = serializers.CharField(
        source="get_hold_reason_display", read_only=True, default=""
    )
    is_claimable = serializers.BooleanField(read_only=True)
    authorisation_reference = serializers.CharField(
        source="preauthorisation.reference", read_only=True, default=""
    )

    class Meta:
        model = ChargeCoverage
        fields = [
            "id", "invoice_item", "invoice_number", "patient_name", "description",
            "policy", "policy_number", "provider_code", "scheme_amount",
            "patient_amount", "basis", "basis_display", "applied_percent",
            "applied_copay", "rule_description", "hold_reason", "hold_display",
            "is_claimable", "authorisation_reference", "service_date", "resolved_at",
        ]
        read_only_fields = fields


class InvoiceSplitSerializer(serializers.Serializer):
    """What the patient owes and what the schemes owe, on one invoice."""

    scheme_share = serializers.DecimalField(max_digits=12, decimal_places=2)
    patient_share = serializers.DecimalField(max_digits=12, decimal_places=2)
    unresolved = serializers.DecimalField(max_digits=12, decimal_places=2)


class ClaimLineSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    unsettled = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = ClaimLine
        fields = [
            "id", "claim", "coverage", "patient_name", "policy_number",
            "service_description", "service_code", "service_date",
            "diagnosis_codes", "clinician", "authorisation_reference",
            "claimed_amount", "paid_amount", "written_off_amount",
            "moved_to_patient_amount", "unsettled", "status", "status_display",
            "rejection_reason", "shortfall_reason",
        ]
        read_only_fields = fields


class ClaimBatchSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source="provider.name", read_only=True)
    provider_code = serializers.CharField(source="provider.code", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    lines = ClaimLineSerializer(many=True, read_only=True)
    claimed_total = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    paid_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    written_off_total = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    outstanding = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    days_outstanding = serializers.IntegerField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    allowed_transitions = serializers.SerializerMethodField()
    resubmits_number = serializers.CharField(
        source="resubmits.claim_number", read_only=True, default=None
    )

    class Meta:
        model = ClaimBatch
        fields = [
            "id", "claim_number", "provider", "provider_name", "provider_code",
            "facility", "period_start", "period_end", "status", "status_display",
            "allowed_transitions", "resubmits", "resubmits_number",
            "resubmission_reason", "submitted_by", "submitted_at",
            "provider_reference", "acknowledged_at", "rejection_reason",
            "claimed_total", "paid_total", "written_off_total", "outstanding",
            "days_outstanding", "is_overdue", "lines", "created_at",
        ]
        read_only_fields = fields

    def get_allowed_transitions(self, claim) -> list[str]:
        """Sent from the server so the client offers only legal moves. A second
        copy of the state machine in the browser is the one that drifts."""
        return sorted(claim.TRANSITIONS.get(claim.status, set()))


class AssembleClaimSerializer(serializers.Serializer):
    provider = serializers.IntegerField()
    facility = serializers.IntegerField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    resubmits = serializers.IntegerField(required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if attrs["period_end"] < attrs["period_start"]:
            raise serializers.ValidationError(
                {"period_end": "The period ends before it starts."}
            )
        return attrs


class SubmitClaimSerializer(serializers.Serializer):
    provider_reference = serializers.CharField(
        required=False, allow_blank=True, default=""
    )


class RejectClaimSerializer(serializers.Serializer):
    reason = serializers.CharField()
    line_reasons = serializers.DictField(
        child=serializers.CharField(), required=False, default=dict,
        help_text="Line id to reason. Lines not named here stay accepted.",
    )


class AllocationSerializer(serializers.Serializer):
    line = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)


class RecordProviderPaymentSerializer(serializers.Serializer):
    provider = serializers.IntegerField()
    facility = serializers.IntegerField()
    reference = serializers.CharField(max_length=120)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    received_on = serializers.DateField()
    method = serializers.IntegerField()
    note = serializers.CharField(required=False, allow_blank=True, default="")
    allocations = AllocationSerializer(many=True)


class ResolveShortfallSerializer(serializers.Serializer):
    write_off = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=0
    )
    move_to_patient = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=0
    )
    reason = serializers.CharField()


class ProviderPaymentSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source="provider.name", read_only=True)
    method_name = serializers.CharField(source="method.name", read_only=True)
    recorded_by_name = serializers.CharField(
        source="recorded_by.full_name", read_only=True
    )
    allocated = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    unallocated = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    is_frozen = serializers.BooleanField(read_only=True)

    class Meta:
        model = ProviderPayment
        fields = [
            "id", "provider", "provider_name", "facility", "reference", "amount",
            "received_on", "method", "method_name", "recorded_by",
            "recorded_by_name", "recorded_at", "note", "allocated", "unallocated",
            "reconciled_at", "is_frozen",
        ]
        read_only_fields = fields


class PatientCoverageSerializer(serializers.Serializer):
    """What cover a patient has, for the point-of-service screens."""

    patient = PatientSummarySerializer()
    policies = PatientPolicySerializer(many=True)
    has_cover = serializers.BooleanField()
