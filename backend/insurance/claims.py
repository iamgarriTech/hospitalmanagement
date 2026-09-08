"""Assembling, submitting and settling claims.

Two rules carry this module.

**A claim is assembled, never typed.** Its lines come from coverage rows that
already exist, and each line carries a copy of what it is claiming for — the
patient's name, the policy number, the service description, the date, the
authorisation reference. A claim is a statement made on a date; it has to print
the same way in two years even if the service has since been renamed.

**A rejected claim resubmits once.** AC-135. The partial unique constraint on
`ClaimLine.coverage` is what enforces it: a charge can sit on one *live* claim,
and a rejected claim's lines are released so the correction can pick them up.
No flags, no bookkeeping — the database refuses the second live line.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.models import AuditEvent

from .models import ChargeCoverage, ClaimBatch, ClaimLine, PaymentAllocation

ZERO = Decimal("0.00")


def claimable_coverages(*, provider, facility, period_start, period_end):
    """Charges ready to claim from one provider, for a period.

    Excludes anything already on a live claim, anything held for an
    authorisation, and anything the scheme owes nothing on. A held line is not
    filtered away and forgotten — `held_coverages` below is the list somebody
    has to work through.
    """
    return ChargeCoverage.objects.filter(
        policy__plan__provider=provider,
        invoice_item__invoice__facility=facility,
        service_date__gte=period_start,
        service_date__lte=period_end,
        scheme_amount__gt=ZERO,
        hold_reason="",
        invoice_item__is_cancelled=False,
    ).exclude(
        claim_lines__status__in=[ClaimLine.PENDING, ClaimLine.ACCEPTED]
    ).select_related(
        "invoice_item__invoice__patient",
        "invoice_item__service",
        "policy__plan__provider",
        "preauthorisation",
    ).order_by("service_date", "pk")


def held_coverages(*, facility=None, provider=None):
    """Charges the scheme would pay for, that nobody can claim yet.

    The billing office's work list. A held line that dropped off every list
    would be money the hospital never asks for.
    """
    queryset = ChargeCoverage.objects.exclude(hold_reason="").filter(
        policy__isnull=False, invoice_item__is_cancelled=False
    ).select_related(
        "invoice_item__invoice__patient", "invoice_item__service",
        "policy__plan__provider",
    )
    if facility is not None:
        queryset = queryset.filter(invoice_item__invoice__facility=facility)
    if provider is not None:
        queryset = queryset.filter(policy__plan__provider=provider)
    return queryset.order_by("service_date")


def _diagnosis_codes(coverage):
    """The coded diagnoses for the episode this charge came from.

    Providers reject lines with no diagnosis, so they are assembled from the
    clinical record rather than asked for again. Coded first, description as a
    fallback — a claim with the words is better than a claim with nothing.
    """
    from clinical.models import Encounter

    invoice = coverage.invoice_item.invoice
    encounters = Encounter.objects.filter(patient=invoice.patient)
    if invoice.admission_id:
        encounters = encounters.filter(admission_id=invoice.admission_id)
    elif invoice.visit_id:
        encounters = encounters.filter(visit_id=invoice.visit_id)
    codes = []
    for encounter in encounters.prefetch_related("versions__diagnoses"):
        version = encounter.current_version
        if version is None:
            continue
        for diagnosis in version.diagnoses.all():
            codes.append(diagnosis.code or diagnosis.description)
    # De-duplicated, order preserved: a claim listing the same code four times
    # invites a query from the provider.
    return ", ".join(dict.fromkeys(code for code in codes if code))[:255]


@transaction.atomic
def assemble(*, provider, facility, period_start, period_end, actor,
             resubmits=None, reason="", request=None):
    """Build a draft claim from charges already raised. AC-132.

    Returns `(claim, skipped)` — `skipped` being the coverages that could not
    be added because another live claim already holds them, which is worth
    reporting rather than swallowing.
    """
    if resubmits is not None:
        if resubmits.status != ClaimBatch.REJECTED:
            raise ValidationError(
                f"Only a rejected claim can be resubmitted "
                f"({resubmits.claim_number} is {resubmits.status})."
            )
        if not reason.strip():
            raise ValidationError("Say what was corrected before resubmitting.")
        if hasattr(resubmits, "resubmitted_as"):
            # AC-135. The OneToOne would refuse this anyway; saying so plainly
            # is better than an integrity error reaching the view.
            raise ValidationError(
                f"{resubmits.claim_number} has already been resubmitted as "
                f"{resubmits.resubmitted_as.claim_number}."
            )

    claim = ClaimBatch.objects.create(
        provider=provider, facility=facility,
        period_start=period_start, period_end=period_end,
        created_by=actor, resubmits=resubmits,
        resubmission_reason=reason.strip() if resubmits else "",
    )

    skipped = []
    for coverage in claimable_coverages(
        provider=provider, facility=facility,
        period_start=period_start, period_end=period_end,
    ):
        item = coverage.invoice_item
        invoice = item.invoice
        try:
            with transaction.atomic():
                ClaimLine.objects.create(
                    claim=claim,
                    coverage=coverage,
                    patient_name=invoice.patient.full_name,
                    policy_number=coverage.policy.policy_number,
                    service_description=item.description[:255],
                    service_code=item.service.code if item.service_id else "",
                    service_date=coverage.service_date,
                    diagnosis_codes=_diagnosis_codes(coverage),
                    clinician=_clinician_for(invoice),
                    authorisation_reference=(
                        coverage.preauthorisation.reference
                        if coverage.preauthorisation_id else ""
                    ),
                    claimed_amount=coverage.scheme_amount,
                )
        except IntegrityError:
            # Another claim took this charge between the query and the write.
            # The constraint is the authority; this reports rather than retries.
            skipped.append(coverage)

    AuditEvent.record(
        action="claim.assembled",
        actor=actor,
        resource=claim,
        facility=facility,
        after={
            "claim_number": claim.claim_number,
            "provider": provider.code,
            "lines": claim.lines.count(),
            "total": str(claim.claimed_total),
            "resubmits": resubmits.claim_number if resubmits else None,
            "skipped": len(skipped),
        },
        reason=reason,
        request=request,
    )
    return claim, skipped


def _clinician_for(invoice):
    from clinical.models import Encounter

    encounter = Encounter.objects.filter(
        patient=invoice.patient,
        **({"admission_id": invoice.admission_id} if invoice.admission_id
           else {"visit_id": invoice.visit_id}),
    ).select_related("clinician").order_by("started_at").first()
    return encounter.clinician.full_name if encounter else ""


@transaction.atomic
def submit(*, claim, actor, provider_reference="", request=None):
    """Send a claim. AC-133."""
    if not claim.lines.exists():
        raise ValidationError("A claim with no lines cannot be submitted.")
    if not claim.provider.is_accepting_claims:
        raise ValidationError(
            f"{claim.provider.name} is marked as not accepting claims."
        )
    claim.advance_to(ClaimBatch.SUBMITTED)
    claim.submitted_by = actor
    claim.submitted_at = timezone.now()
    claim.provider_reference = provider_reference
    claim.save(
        update_fields=["status", "submitted_by", "submitted_at", "provider_reference"]
    )
    AuditEvent.record(
        action="claim.submitted",
        actor=actor,
        resource=claim,
        facility=claim.facility,
        after={"claim_number": claim.claim_number, "lines": claim.lines.count(),
               "total": str(claim.claimed_total),
               "channel": claim.provider.claim_channel},
        request=request,
    )
    return claim


@transaction.atomic
def acknowledge(*, claim, actor, provider_reference="", request=None):
    claim.advance_to(ClaimBatch.ACKNOWLEDGED)
    claim.acknowledged_at = timezone.now()
    if provider_reference:
        claim.provider_reference = provider_reference
    claim.save(update_fields=["status", "acknowledged_at", "provider_reference"])
    AuditEvent.record(
        action="claim.acknowledged", actor=actor, resource=claim,
        facility=claim.facility,
        after={"claim_number": claim.claim_number,
               "provider_reference": claim.provider_reference},
        request=request,
    )
    return claim


@transaction.atomic
def reject(*, claim, actor, reason, line_reasons=None, request=None):
    """Record a rejection. AC-136.

    `line_reasons` maps a line id to its reason, because providers reject some
    lines and pay others. Lines nobody named are left accepted, so a partial
    rejection does not throw away the accepted half.
    """
    if not reason.strip():
        raise ValidationError("A rejection has to say why.")
    claim.advance_to(ClaimBatch.REJECTED)
    claim.rejection_reason = reason.strip()
    claim.save(update_fields=["status", "rejection_reason"])

    named = line_reasons or {}
    rejected = 0
    for line in claim.lines.all():
        line_reason = named.get(line.pk) or named.get(str(line.pk))
        if named and not line_reason:
            continue  # this line was accepted; only the named ones are rejected
        line.status = ClaimLine.REJECTED
        line.rejection_reason = (line_reason or reason).strip()[:255]
        line.save(update_fields=["status", "rejection_reason"])
        rejected += 1

    AuditEvent.record(
        action="claim.rejected",
        actor=actor,
        outcome=AuditEvent.DENIED,
        resource=claim,
        facility=claim.facility,
        after={"claim_number": claim.claim_number, "lines_rejected": rejected,
               "lines_total": claim.lines.count()},
        reason=reason.strip(),
        request=request,
    )
    return claim


@transaction.atomic
def record_payment(*, provider, facility, reference, amount, received_on, method,
                   actor, allocations, note="", request=None):
    """Money in from a provider, applied line by line. AC-137.

    `allocations` maps a `ClaimLine` to an amount. Applied per line rather than
    per claim because a short payment has to be visible against the line it
    short-paid — a lump difference on a claim tells nobody which service the
    scheme declined to pay for.
    """
    from .models import ProviderPayment

    payment = ProviderPayment.objects.create(
        provider=provider, facility=facility, reference=reference, amount=amount,
        received_on=received_on, method=method, recorded_by=actor, note=note,
    )

    applied = ZERO
    for line, share in allocations.items():
        share = Decimal(share)
        if share <= ZERO:
            continue
        if line.claim.provider_id != provider.pk:
            raise ValidationError(
                f"{line.claim.claim_number} is not a {provider.code} claim."
            )
        PaymentAllocation.objects.create(payment=payment, line=line, amount=share)
        line.paid_amount = line.paid_amount + share
        line.status = ClaimLine.ACCEPTED
        line.save(update_fields=["paid_amount", "status"])
        applied += share

    if applied > amount:
        raise ValidationError(
            f"Allocated {applied} of a {amount} payment. Reduce the allocations."
        )

    for claim in {line.claim for line in allocations}:
        _settle(claim)

    AuditEvent.record(
        action="claim.payment_received",
        actor=actor,
        resource=payment,
        facility=facility,
        after={
            "provider": provider.code, "reference": reference, "amount": str(amount),
            "allocated": str(applied), "unallocated": str(payment.unallocated),
            "lines": len(allocations),
        },
        reason=note,
        request=request,
    )
    return payment


def _settle(claim):
    """Move a claim to part paid or paid, from its lines."""
    claim.refresh_from_db()
    outstanding = claim.outstanding
    target = ClaimBatch.PAID if outstanding <= ZERO else ClaimBatch.PART_PAID
    if claim.status == target:
        return claim
    if target in ClaimBatch.TRANSITIONS.get(claim.status, set()):
        claim.status = target
        claim.save(update_fields=["status"])
    return claim


@transaction.atomic
def resolve_shortfall(*, line, actor, write_off=ZERO, move_to_patient=ZERO,
                      reason, request=None):
    """Decide what happens to money a scheme did not pay. AC-137 (negative).

    A shortfall has to go somewhere explicit: written off with a reason, or
    moved to the patient with a reason. Leaving it as an unexplained gap is how
    a hospital loses money quietly, and moving it to a patient without saying
    why is how a hospital loses a patient's trust loudly.
    """
    if not reason.strip():
        raise ValidationError("A shortfall has to say why before it can be resolved.")
    write_off = Decimal(write_off)
    move_to_patient = Decimal(move_to_patient)
    total = write_off + move_to_patient
    if total <= ZERO:
        raise ValidationError("Nothing to resolve.")
    if total > line.unsettled:
        raise ValidationError(
            f"{total} exceeds the {line.unsettled} still unsettled on this line."
        )

    line.written_off_amount = line.written_off_amount + write_off
    line.moved_to_patient_amount = line.moved_to_patient_amount + move_to_patient
    line.shortfall_reason = reason.strip()[:255]
    line.save(
        update_fields=["written_off_amount", "moved_to_patient_amount",
                       "shortfall_reason"]
    )

    if move_to_patient > ZERO:
        # The patient now owes it, so the coverage row has to say so — the
        # invoice reads the split from there, and a shortfall the invoice does
        # not know about is a bill nobody will ever collect.
        coverage = line.coverage
        coverage.scheme_amount = coverage.scheme_amount - move_to_patient
        coverage.patient_amount = coverage.patient_amount + move_to_patient
        coverage.rule_description = (
            f"{coverage.rule_description} — {move_to_patient} moved to the patient: "
            f"{reason.strip()}"
        )[:255]
        coverage.save(
            update_fields=["scheme_amount", "patient_amount", "rule_description"]
        )

    _settle(line.claim)
    AuditEvent.record(
        action="claim.shortfall_resolved",
        actor=actor,
        resource=line.claim,
        facility=line.claim.facility,
        after={
            "line": line.service_description, "written_off": str(write_off),
            "moved_to_patient": str(move_to_patient),
        },
        reason=reason.strip(),
        request=request,
    )
    return line


def ageing(*, facility=None, provider=None, now=None):
    """What each provider owes and for how long. AC-139.

    Bucketed the way a finance office chases: current, then the bands after the
    provider's own undertaking has lapsed.
    """
    moment = now or timezone.now()
    claims = ClaimBatch.objects.exclude(
        status__in=[ClaimBatch.DRAFT, ClaimBatch.PAID, ClaimBatch.REJECTED]
    ).select_related("provider", "facility").prefetch_related("lines")
    if facility is not None:
        claims = claims.filter(facility=facility)
    if provider is not None:
        claims = claims.filter(provider=provider)

    buckets = {}
    for claim in claims:
        outstanding = claim.outstanding
        if outstanding <= ZERO:
            continue
        days = (moment.date() - claim.submitted_at.date()).days if claim.submitted_at else 0
        band = (
            "current" if days <= claim.provider.settlement_days
            else "31-60" if days <= 60
            else "61-90" if days <= 90
            else "over 90"
        )
        entry = buckets.setdefault(
            claim.provider.code,
            {"provider": claim.provider.name, "code": claim.provider.code,
             "current": ZERO, "31-60": ZERO, "61-90": ZERO, "over 90": ZERO,
             "total": ZERO, "claims": 0, "oldest_days": 0},
        )
        entry[band] += outstanding
        entry["total"] += outstanding
        entry["claims"] += 1
        entry["oldest_days"] = max(entry["oldest_days"], days)
    return sorted(buckets.values(), key=lambda row: -row["total"])
