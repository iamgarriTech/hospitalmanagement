"""Resolving what a scheme pays, and recording the answer.

The rule that makes this app worth having is one sentence: **the split is
computed once, at the time of service, and stored.** Everything else here
follows from it.

`resolve()` is called from `billing.charge()` as each charge is raised. It picks
the patient's policy, finds the most specific rule, works out the two amounts,
and writes a `ChargeCoverage` row carrying a *copy* of the rule. Nothing later
recomputes it. A plan renegotiated in March cannot change what a patient owed in
February, and the row explains itself in words so a cashier can defend it
without re-running anything.

The second rule: **nothing here refuses a charge.** A missing authorisation, an
unruled service, an exhausted limit — each produces a coverage row with a hold
reason. The treatment happened; the money is a separate problem.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from core.formatting import trim_decimal

from .models import ChargeCoverage, CoverageRule, PatientPolicy, Preauthorisation

ZERO = Decimal("0.00")
PENNY = Decimal("0.01")


def _money(value):
    """Round half up, which is what a cashier does and what a receipt shows.

    Python's default is banker's rounding, which would make a hospital's totals
    disagree with a hand-added column by a naira now and again — and a naira is
    enough for somebody to lose confidence in the whole bill.
    """
    return Decimal(value).quantize(PENNY, rounding=ROUND_HALF_UP)


def policies_for(patient, on=None):
    """The patient's policies in force on a date, in the order they pay.

    Ordered by `precedence` because a patient can hold an employer HMO and a
    private top-up, and which pays first is the billing office's decision, not
    an accident of insertion order.
    """
    day = on or timezone.localdate()
    return [
        policy
        for policy in PatientPolicy.objects.filter(
            patient=patient, is_active=True
        ).select_related("plan__provider").order_by("precedence", "id")
        if policy.covers(day)
    ]


def find_rule(plan, service):
    """The rule that applies, most specific first.

    A rule naming the service beats one naming its category. Anything else
    would mean a category rule silently overriding the exception somebody wrote
    for one service inside it.
    """
    if service is None:
        return None
    rule = CoverageRule.objects.filter(plan=plan, service=service).first()
    if rule is not None:
        return rule
    if service.category_id is None:
        return None
    return CoverageRule.objects.filter(plan=plan, category=service.category_id).first()


def _split(amount, rule, plan):
    """The two amounts, and how to describe them.

    Returns `(scheme, patient, basis, percent, copay, description)`.
    """
    if rule is None:
        # No rule at all. The plan says what it does with this case, and either
        # way the coverage row records that no rule existed — AC-126.
        if plan.unruled_services == plan.COVERED:
            percent = plan.default_scheme_percent
            scheme = _money(amount * percent / 100)
            return (
                scheme, _money(amount - scheme), CoverageRule.PERCENTAGE, percent, None,
                f"No specific rule; {plan.name} pays {trim_decimal(percent)}% by default",
            )
        return (
            ZERO, _money(amount), CoverageRule.EXCLUDED, None, None,
            f"No coverage rule for this service under {plan.name}; patient pays",
        )

    if rule.basis == CoverageRule.EXCLUDED:
        return (
            ZERO, _money(amount), rule.basis, None, None,
            f"Excluded by {plan.name}: {rule.exclusion_reason}",
        )

    if rule.basis == CoverageRule.FULL:
        return (
            _money(amount), ZERO, rule.basis, Decimal("100.00"), None,
            f"{plan.name} pays in full",
        )

    if rule.basis == CoverageRule.PERCENTAGE:
        percent = rule.scheme_percent or ZERO
        scheme = _money(amount * percent / 100)
        return (
            scheme, _money(amount - scheme), rule.basis, percent, None,
            f"{plan.name} pays {trim_decimal(percent)}%, patient pays the balance",
        )

    # A fixed co-pay. Capped at the charge, or a small charge under a large
    # co-pay would hand the patient a bill bigger than the service.
    copay = min(rule.patient_copay or ZERO, _money(amount))
    return (
        _money(amount - copay), _money(copay), rule.basis, None, rule.patient_copay,
        f"{plan.name}: patient co-pay of {trim_decimal(rule.patient_copay)}",
    )


def _authorisation_for(policy, service, day, episode):
    """An approved, in-date authorisation covering this service, if there is one."""
    candidates = Preauthorisation.objects.filter(
        policy=policy, status=Preauthorisation.APPROVED
    ).prefetch_related("services")
    if episode.get("visit") is not None:
        candidates = candidates.filter(visit=episode["visit"])
    elif episode.get("admission") is not None:
        candidates = candidates.filter(admission=episode["admission"])
    for candidate in candidates:
        if candidate.is_valid_for(service, on=day):
            return candidate
    return None


def _needs_authorisation(rule, plan, amount):
    """Whether this charge cannot be claimed without an authorisation reference."""
    if rule is not None and rule.requires_preauthorisation:
        return True
    threshold = plan.requires_preauthorisation_above
    return threshold is not None and amount > threshold


def spent_this_year(policy, on=None):
    """What the scheme has already been asked for on this policy this year.

    Counted from the stored coverage rows, not from claims: a charge is a claim
    on the scheme's limit from the moment it is raised, whether or not anyone
    has got round to submitting it.
    """
    day = on or timezone.localdate()
    total = ChargeCoverage.objects.filter(
        policy=policy, service_date__year=day.year
    ).aggregate(total=Sum("scheme_amount"))["total"]
    return total or ZERO


@transaction.atomic
def resolve(*, invoice_item, service, amount, patient, service_date=None,
            visit=None, admission=None):
    """Work out and record how one charge is split. Returns the coverage row.

    Idempotent: a charge already resolved keeps its original answer rather than
    being recomputed, which is the same guarantee stated at the top of this
    module applied to a retried request.
    """
    existing = ChargeCoverage.objects.filter(invoice_item=invoice_item).first()
    if existing is not None:
        return existing

    day = service_date or timezone.localdate()
    episode = {"visit": visit, "admission": admission}
    amount = _money(amount)

    policies = policies_for(patient, day)
    if not policies:
        # A self-paying patient. Recorded rather than left absent, so "nobody
        # resolved this line" and "this patient has no cover" are different
        # states on the invoice.
        return ChargeCoverage.objects.create(
            invoice_item=invoice_item,
            policy=None,
            scheme_amount=ZERO,
            patient_amount=amount,
            basis=CoverageRule.EXCLUDED,
            rule_description="No insurance policy in force on the date of service",
            service_date=day,
        )

    # The first policy that pays anything wins. Real coordination of benefits
    # across two schemes is a Phase 5 problem if a hospital ever asks for it;
    # pretending to do it now would produce splits nobody could explain.
    for policy in policies:
        plan = policy.plan
        rule = find_rule(plan, service)
        scheme, patient_share, basis, percent, copay, description = _split(
            amount, rule, plan
        )

        hold = ""
        authorisation = None
        if scheme > ZERO:
            if _needs_authorisation(rule, plan, amount):
                authorisation = _authorisation_for(policy, service, day, episode)
                if authorisation is None:
                    # Held, not refused. The charge stands and the patient is
                    # treated; the claim waits. AC-131.
                    hold = ChargeCoverage.HELD_NO_PREAUTH
                    description += " — awaiting preauthorisation"
            if not hold and plan.annual_limit is not None:
                already = spent_this_year(policy, day)
                if already + scheme > plan.annual_limit:
                    remaining = max(plan.annual_limit - already, ZERO)
                    if remaining <= ZERO:
                        scheme, patient_share = ZERO, amount
                        hold = ChargeCoverage.HELD_LIMIT
                        description = (
                            f"{plan.name} annual limit of {trim_decimal(plan.annual_limit)} "
                            f"already reached; patient pays"
                        )
                    else:
                        scheme = _money(remaining)
                        patient_share = _money(amount - scheme)
                        description += (
                            f" — reduced to the {trim_decimal(plan.annual_limit)} annual limit"
                        )
        if rule is None and plan.unruled_services != plan.COVERED:
            hold = hold or ChargeCoverage.HELD_NO_RULE

        return ChargeCoverage.objects.create(
            invoice_item=invoice_item,
            policy=policy,
            scheme_amount=scheme,
            patient_amount=patient_share,
            basis=basis,
            applied_percent=percent,
            applied_copay=copay,
            rule_description=description,
            rule=rule,
            preauthorisation=authorisation,
            hold_reason=hold,
            service_date=day,
        )
    return None


def invoice_split(invoice):
    """What the patient owes and what the schemes owe, on one invoice.

    Read from the stored rows. A line with no coverage row counts as the
    patient's, because an unresolved line is not the scheme's problem until
    somebody says it is — and showing it as covered would understate the bill.
    """
    scheme = ZERO
    patient = ZERO
    unresolved = ZERO
    for item in invoice.items.all():
        if item.is_cancelled:
            continue
        coverage = getattr(item, "coverage", None)
        if coverage is None:
            unresolved += item.amount
            patient += item.amount
            continue
        scheme += coverage.scheme_amount
        patient += coverage.patient_amount
    return {
        "scheme_share": scheme,
        "patient_share": patient - invoice.discount_amount + invoice.tax_amount,
        "unresolved": unresolved,
    }
