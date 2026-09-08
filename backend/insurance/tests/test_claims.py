"""AC-132 to AC-139 — claims, and the resubmission gate.

AC-135 is the gate: a rejected claim corrected and resubmitted must produce one
claim in the provider's hands and one expected payment. Enforced by a partial
unique constraint on the charge, not by a check a race can slip past.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from audit.models import AuditEvent
from billing.models import charge
from insurance.claims import (
    acknowledge,
    ageing,
    assemble,
    claimable_coverages,
    held_coverages,
    record_payment,
    reject,
    resolve_shortfall,
    submit,
)
from insurance.models import ChargeCoverage, ClaimBatch, ClaimLine, CoverageRule


@pytest.fixture
def charged_visit(insured_patient, open_visit, scheme, finalised_encounter):
    """An insured patient's visit with three charges on it.

    The consultation comes from finalising the encounter — that is where the
    fee falls due, and adding a second one here would be a duplicate charge
    rather than a fixture. So this adds the laboratory line (co-pay) and the
    cosmetic one (excluded), and the coded diagnosis rides on the encounter.

    Claimable: 5000 consultation in full + 3000 of the laboratory line = 8000.
    The cosmetic line is excluded, so the scheme owes nothing and it is not
    claimed at all.
    """
    for code, source in [("LAB-FBC", "c2"), ("COSM", "c3")]:
        charge(
            visit=open_visit, service_code=code, description=code,
            source_type="test", source_id=source,
        )
    return open_visit


def build(scheme, facility, actor, **extra):
    return assemble(
        provider=scheme["provider"], facility=facility,
        period_start=date.today() - timedelta(days=1),
        period_end=date.today() + timedelta(days=1),
        actor=actor, **extra,
    )


# --- assembly -----------------------------------------------------------------

@pytest.mark.django_db
def test_a_claim_is_assembled_from_charges_already_raised(
    charged_visit, scheme, facility_a, billing_officer, insured_patient
):
    """AC-132. Nothing is retyped."""
    claim, skipped = build(scheme, facility_a, billing_officer)

    assert skipped == []
    # The consultation and the laboratory line; the cosmetic one is excluded, so
    # the scheme owes nothing and it is not claimed.
    assert claim.lines.count() == 2
    assert claim.claimed_total == Decimal("8000.00")  # 5000 + 3000
    assert claim.status == ClaimBatch.DRAFT
    assert claim.claim_number.startswith("CLM")

    line = claim.lines.get(service_code="CONSULT")
    assert line.patient_name == insured_patient.full_name
    assert line.policy_number == "HYG/12345"
    assert line.service_date == date.today()
    assert line.claimed_amount == Decimal("5000.00")
    assert line.status == ClaimLine.PENDING

    event = AuditEvent.objects.get(action="claim.assembled")
    assert event.changes["after"]["lines"] == 2
    assert event.changes["after"]["provider"] == "HYG"


@pytest.mark.django_db
def test_a_claim_line_carries_the_diagnosis_codes(
    charged_visit, scheme, facility_a, billing_officer
):
    """AC-132. Providers reject lines with no diagnosis, so they are assembled
    from the clinical record rather than asked for again."""
    claim, _ = build(scheme, facility_a, billing_officer)
    line = claim.lines.get(service_code="CONSULT")
    assert "Malaria" in line.diagnosis_codes or line.diagnosis_codes
    assert line.clinician


@pytest.mark.django_db
def test_a_held_line_is_not_claimed_and_is_not_lost(
    insured_patient, open_visit, scheme, facility_a, billing_officer, tariff
):
    """AC-131 meets AC-132: held lines stay on a work list rather than being
    claimed or dropped."""
    rule = CoverageRule.objects.get(plan=scheme["plan"], service=tariff["consult"])
    rule.requires_preauthorisation = True
    rule.save(update_fields=["requires_preauthorisation"])

    charge(
        visit=open_visit, service_code="CONSULT", description="Consultation",
        source_type="test", source_id="held1",
    )
    claim, _ = build(scheme, facility_a, billing_officer)
    assert claim.lines.count() == 0

    held = list(held_coverages(facility=facility_a))
    assert len(held) == 1
    assert held[0].hold_reason == ChargeCoverage.HELD_NO_PREAUTH


@pytest.mark.django_db
def test_a_charge_cannot_be_on_two_live_claims(
    charged_visit, scheme, facility_a, billing_officer
):
    """AC-134 (negative). The second assembly finds nothing left to claim."""
    first, _ = build(scheme, facility_a, billing_officer)
    assert first.lines.count() == 2

    second, skipped = build(scheme, facility_a, billing_officer)
    assert second.lines.count() == 0
    assert skipped == []
    assert claimable_coverages(
        provider=scheme["provider"], facility=facility_a,
        period_start=date.today() - timedelta(days=1),
        period_end=date.today() + timedelta(days=1),
    ).count() == 0


@pytest.mark.django_db(transaction=True)
def test_the_database_refuses_a_second_live_line_for_one_charge(
    charged_visit, scheme, facility_a, billing_officer
):
    """AC-134, below the query. A filter can be raced; the constraint cannot."""
    claim, _ = build(scheme, facility_a, billing_officer)
    line = claim.lines.first()
    second, _ = build(scheme, facility_a, billing_officer)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ClaimLine.objects.create(
                claim=second, coverage=line.coverage,
                patient_name=line.patient_name, policy_number=line.policy_number,
                service_description=line.service_description,
                service_date=line.service_date,
                claimed_amount=line.claimed_amount,
            )


# --- the state machine --------------------------------------------------------

@pytest.mark.django_db
def test_a_claim_advances_in_sequence(
    charged_visit, scheme, facility_a, billing_officer
):
    """AC-133."""
    claim, _ = build(scheme, facility_a, billing_officer)
    submit(claim=claim, actor=billing_officer, provider_reference="HYG-BATCH-1")
    claim.refresh_from_db()
    assert claim.status == ClaimBatch.SUBMITTED
    assert claim.submitted_at is not None
    assert claim.days_outstanding == 0

    acknowledge(claim=claim, actor=billing_officer)
    claim.refresh_from_db()
    assert claim.status == ClaimBatch.ACKNOWLEDGED

    assert [
        event.action for event in AuditEvent.objects.filter(
            action__startswith="claim."
        ).order_by("id")
    ] == ["claim.assembled", "claim.submitted", "claim.acknowledged"]


@pytest.mark.django_db
def test_a_state_cannot_be_skipped(charged_visit, scheme, facility_a, billing_officer):
    """AC-133 (negative). A draft cannot be acknowledged."""
    claim, _ = build(scheme, facility_a, billing_officer)
    with pytest.raises(ValidationError, match="cannot become"):
        acknowledge(claim=claim, actor=billing_officer)


@pytest.mark.django_db
def test_an_empty_claim_cannot_be_submitted(scheme, facility_a, billing_officer):
    """A claim with no lines wastes a provider's time and the hospital's."""
    claim, _ = build(scheme, facility_a, billing_officer)
    assert claim.lines.count() == 0
    with pytest.raises(ValidationError, match="no lines"):
        submit(claim=claim, actor=billing_officer)


@pytest.mark.django_db
def test_a_provider_that_has_stopped_paying_is_not_claimed_to(
    charged_visit, scheme, facility_a, billing_officer
):
    """Nigerian HMOs go quiet. Switching one off stops new claims without
    deleting the history that still has to be chased."""
    provider = scheme["provider"]
    provider.is_accepting_claims = False
    provider.save(update_fields=["is_accepting_claims"])

    claim, _ = build(scheme, facility_a, billing_officer)
    with pytest.raises(ValidationError, match="not accepting claims"):
        submit(claim=claim, actor=billing_officer)


# --- AC-135, the gate ---------------------------------------------------------

@pytest.mark.django_db
def test_a_rejected_claim_resubmits_once(
    charged_visit, scheme, facility_a, billing_officer
):
    """AC-135 — the gate.

    Rejected, corrected, resubmitted: one claim in the provider's hands and one
    expected payment. The charges move to the new claim; they are not on both.
    """
    first, _ = build(scheme, facility_a, billing_officer)
    submit(claim=first, actor=billing_officer)
    reject(
        claim=first, actor=billing_officer,
        reason="Policy number transposed on every line.",
    )
    first.refresh_from_db()
    assert first.status == ClaimBatch.REJECTED
    assert all(line.status == ClaimLine.REJECTED for line in first.lines.all())

    # The charges are free again, because the rejected lines released them.
    assert claimable_coverages(
        provider=scheme["provider"], facility=facility_a,
        period_start=date.today() - timedelta(days=1),
        period_end=date.today() + timedelta(days=1),
    ).count() == 2

    second, skipped = build(
        scheme, facility_a, billing_officer,
        resubmits=first, reason="Policy number corrected.",
    )
    assert skipped == []
    assert second.lines.count() == 2
    assert second.resubmits == first
    assert second.claimed_total == first.claimed_total

    # One live claim per charge: the total the provider is being asked for is
    # 8000, not 16000.
    live = ClaimLine.objects.exclude(status=ClaimLine.REJECTED)
    assert sum(line.claimed_amount for line in live) == Decimal("8000.00")
    assert {line.claim_id for line in live} == {second.pk}


@pytest.mark.django_db
def test_a_claim_cannot_be_resubmitted_twice(
    charged_visit, scheme, facility_a, billing_officer
):
    """AC-135 (negative). One correction, not a family of them."""
    first, _ = build(scheme, facility_a, billing_officer)
    submit(claim=first, actor=billing_officer)
    reject(claim=first, actor=billing_officer, reason="Wrong codes.")
    build(scheme, facility_a, billing_officer, resubmits=first, reason="Fixed.")

    first.refresh_from_db()
    with pytest.raises(ValidationError, match="already been resubmitted"):
        build(scheme, facility_a, billing_officer, resubmits=first, reason="Again.")


@pytest.mark.django_db
def test_only_a_rejected_claim_can_be_resubmitted(
    charged_visit, scheme, facility_a, billing_officer
):
    """AC-135 (negative). Resubmitting a live claim would double-bill."""
    claim, _ = build(scheme, facility_a, billing_officer)
    submit(claim=claim, actor=billing_officer)
    with pytest.raises(ValidationError, match="Only a rejected claim"):
        build(scheme, facility_a, billing_officer, resubmits=claim, reason="No.")


@pytest.mark.django_db
def test_a_resubmission_must_say_what_was_corrected(
    charged_visit, scheme, facility_a, billing_officer
):
    claim, _ = build(scheme, facility_a, billing_officer)
    submit(claim=claim, actor=billing_officer)
    reject(claim=claim, actor=billing_officer, reason="Rejected.")
    with pytest.raises(ValidationError, match="what was corrected"):
        build(scheme, facility_a, billing_officer, resubmits=claim, reason="  ")


@pytest.mark.django_db
def test_a_partial_rejection_leaves_the_accepted_lines_alone(
    charged_visit, scheme, facility_a, billing_officer
):
    """AC-136. Providers reject some lines and pay others; a rejection that
    threw away the accepted half would cost the hospital money."""
    claim, _ = build(scheme, facility_a, billing_officer)
    submit(claim=claim, actor=billing_officer)
    lab_line = claim.lines.get(service_code="LAB-FBC")

    reject(
        claim=claim, actor=billing_officer,
        reason="One line queried.",
        line_reasons={lab_line.pk: "Test not covered under this plan version."},
    )
    lab_line.refresh_from_db()
    consult_line = claim.lines.get(service_code="CONSULT")

    assert lab_line.status == ClaimLine.REJECTED
    assert "not covered" in lab_line.rejection_reason
    assert consult_line.status == ClaimLine.PENDING

    event = AuditEvent.objects.get(action="claim.rejected")
    assert event.outcome == AuditEvent.DENIED
    assert event.changes["after"]["lines_rejected"] == 1
    assert event.changes["after"]["lines_total"] == 2


@pytest.mark.django_db
def test_a_rejection_must_state_a_reason(
    charged_visit, scheme, facility_a, billing_officer
):
    claim, _ = build(scheme, facility_a, billing_officer)
    submit(claim=claim, actor=billing_officer)
    with pytest.raises(ValidationError, match="say why"):
        reject(claim=claim, actor=billing_officer, reason="   ")


# --- money in -----------------------------------------------------------------

@pytest.mark.django_db
def test_a_payment_is_applied_line_by_line(
    charged_visit, scheme, facility_a, billing_officer, tariff
):
    """AC-137. A short payment is visible against the line it short-paid."""
    claim, _ = build(scheme, facility_a, billing_officer)
    submit(claim=claim, actor=billing_officer)
    acknowledge(claim=claim, actor=billing_officer)

    consult = claim.lines.get(service_code="CONSULT")
    lab = claim.lines.get(service_code="LAB-FBC")

    payment = record_payment(
        provider=scheme["provider"], facility=facility_a,
        reference="HYG/RTGS/0091", amount=Decimal("7000.00"),
        received_on=date.today(), method=tariff["cash"], actor=billing_officer,
        allocations={consult: Decimal("5000.00"), lab: Decimal("2000.00")},
    )
    claim.refresh_from_db()
    consult.refresh_from_db()
    lab.refresh_from_db()

    assert payment.allocated == Decimal("7000.00")
    assert payment.unallocated == Decimal("0.00")
    assert consult.paid_amount == Decimal("5000.00")
    assert consult.unsettled == Decimal("0.00")
    # The short-paid line, visible as such.
    assert lab.paid_amount == Decimal("2000.00")
    assert lab.unsettled == Decimal("1000.00")
    assert claim.status == ClaimBatch.PART_PAID
    assert claim.outstanding == Decimal("1000.00")


@pytest.mark.django_db
def test_a_claim_paid_in_full_settles(
    charged_visit, scheme, facility_a, billing_officer, tariff
):
    claim, _ = build(scheme, facility_a, billing_officer)
    submit(claim=claim, actor=billing_officer)
    acknowledge(claim=claim, actor=billing_officer)
    record_payment(
        provider=scheme["provider"], facility=facility_a, reference="HYG/FULL/1",
        amount=Decimal("8000.00"), received_on=date.today(), method=tariff["cash"],
        actor=billing_officer,
        allocations={line: line.claimed_amount for line in claim.lines.all()},
    )
    claim.refresh_from_db()
    assert claim.status == ClaimBatch.PAID
    assert claim.outstanding == Decimal("0.00")


@pytest.mark.django_db
def test_a_payment_cannot_be_over_allocated(
    charged_visit, scheme, facility_a, billing_officer, tariff
):
    """Allocating more than arrived would invent money."""
    claim, _ = build(scheme, facility_a, billing_officer)
    submit(claim=claim, actor=billing_officer)
    acknowledge(claim=claim, actor=billing_officer)
    with pytest.raises(ValidationError, match="Reduce the allocations"):
        record_payment(
            provider=scheme["provider"], facility=facility_a, reference="HYG/OVER/1",
            amount=Decimal("1000.00"), received_on=date.today(),
            method=tariff["cash"], actor=billing_officer,
            allocations={line: line.claimed_amount for line in claim.lines.all()},
        )


@pytest.mark.django_db
def test_one_reference_per_provider(
    charged_visit, scheme, facility_a, billing_officer, tariff
):
    """A provider's payment reference is unique, so the same transfer cannot be
    recorded twice."""
    from insurance.models import ProviderPayment

    ProviderPayment.objects.create(
        provider=scheme["provider"], facility=facility_a, reference="DUP/1",
        amount=Decimal("100.00"), received_on=date.today(), method=tariff["cash"],
        recorded_by=billing_officer,
    )
    with pytest.raises(IntegrityError):
        ProviderPayment.objects.create(
            provider=scheme["provider"], facility=facility_a, reference="DUP/1",
            amount=Decimal("100.00"), received_on=date.today(),
            method=tariff["cash"], recorded_by=billing_officer,
        )


# --- shortfalls ---------------------------------------------------------------

@pytest.mark.django_db
def test_a_shortfall_written_off_must_say_why(
    charged_visit, scheme, facility_a, billing_officer, tariff
):
    """AC-137 (negative). A silent write-off is how a hospital loses money
    quietly."""
    claim, _ = build(scheme, facility_a, billing_officer)
    submit(claim=claim, actor=billing_officer)
    acknowledge(claim=claim, actor=billing_officer)
    lab = claim.lines.get(service_code="LAB-FBC")
    record_payment(
        provider=scheme["provider"], facility=facility_a, reference="HYG/SHORT/1",
        amount=Decimal("2000.00"), received_on=date.today(), method=tariff["cash"],
        actor=billing_officer, allocations={lab: Decimal("2000.00")},
    )
    lab.refresh_from_db()
    assert lab.unsettled == Decimal("1000.00")

    with pytest.raises(ValidationError, match="say why"):
        resolve_shortfall(
            line=lab, actor=billing_officer, write_off=Decimal("1000.00"), reason=" ",
        )

    resolve_shortfall(
        line=lab, actor=billing_officer, write_off=Decimal("1000.00"),
        reason="Below the threshold worth chasing; agreed with the provider.",
    )
    lab.refresh_from_db()
    assert lab.written_off_amount == Decimal("1000.00")
    assert lab.unsettled == Decimal("0.00")
    assert "threshold worth chasing" in lab.shortfall_reason


@pytest.mark.django_db
def test_a_shortfall_moved_to_the_patient_reaches_the_invoice(
    charged_visit, scheme, facility_a, billing_officer, tariff
):
    """AC-137. A shortfall the invoice does not know about is a bill nobody
    will ever collect."""
    from insurance.coverage import invoice_split

    claim, _ = build(scheme, facility_a, billing_officer)
    submit(claim=claim, actor=billing_officer)
    acknowledge(claim=claim, actor=billing_officer)
    lab = claim.lines.get(service_code="LAB-FBC")
    invoice = lab.coverage.invoice_item.invoice
    before = invoice_split(invoice)["patient_share"]

    record_payment(
        provider=scheme["provider"], facility=facility_a, reference="HYG/SHORT/2",
        amount=Decimal("2000.00"), received_on=date.today(), method=tariff["cash"],
        actor=billing_officer, allocations={lab: Decimal("2000.00")},
    )
    lab.refresh_from_db()
    resolve_shortfall(
        line=lab, actor=billing_officer, move_to_patient=Decimal("1000.00"),
        reason="Provider declined; patient billed the difference.",
    )

    invoice.refresh_from_db()
    after = invoice_split(invoice)["patient_share"]
    assert after - before == Decimal("1000.00")
    coverage = lab.coverage
    coverage.refresh_from_db()
    assert "moved to the patient" in coverage.rule_description

    event = AuditEvent.objects.get(action="claim.shortfall_resolved")
    assert event.changes["after"]["moved_to_patient"] == "1000.00"


@pytest.mark.django_db
def test_a_shortfall_cannot_exceed_what_is_unsettled(
    charged_visit, scheme, facility_a, billing_officer, tariff
):
    claim, _ = build(scheme, facility_a, billing_officer)
    submit(claim=claim, actor=billing_officer)
    acknowledge(claim=claim, actor=billing_officer)
    lab = claim.lines.get(service_code="LAB-FBC")
    with pytest.raises(ValidationError, match="exceeds"):
        resolve_shortfall(
            line=lab, actor=billing_officer, write_off=Decimal("999999.00"),
            reason="Too much.",
        )


# --- ageing -------------------------------------------------------------------

@pytest.mark.django_db
def test_the_ageing_report_shows_what_is_late(
    charged_visit, scheme, facility_a, billing_officer
):
    """AC-139. Banded the way a finance office chases, past the provider's own
    undertaking."""
    from django.utils import timezone

    claim, _ = build(scheme, facility_a, billing_officer)
    submit(claim=claim, actor=billing_officer)
    acknowledge(claim=claim, actor=billing_officer)

    claim.submitted_at = timezone.now() - timedelta(days=75)
    claim.save(update_fields=["submitted_at"])
    claim.refresh_from_db()
    assert claim.is_overdue is True

    rows = ageing(facility=facility_a)
    assert len(rows) == 1
    row = rows[0]
    assert row["code"] == "HYG"
    assert row["total"] == Decimal("8000.00")
    assert row["61-90"] == Decimal("8000.00")
    assert row["current"] == Decimal("0.00")
    assert row["oldest_days"] == 75


@pytest.mark.django_db
def test_a_paid_claim_leaves_the_ageing_report(
    charged_visit, scheme, facility_a, billing_officer, tariff
):
    claim, _ = build(scheme, facility_a, billing_officer)
    submit(claim=claim, actor=billing_officer)
    acknowledge(claim=claim, actor=billing_officer)
    record_payment(
        provider=scheme["provider"], facility=facility_a, reference="HYG/CLEAR/1",
        amount=Decimal("8000.00"), received_on=date.today(), method=tariff["cash"],
        actor=billing_officer,
        allocations={line: line.claimed_amount for line in claim.lines.all()},
    )
    assert ageing(facility=facility_a) == []
