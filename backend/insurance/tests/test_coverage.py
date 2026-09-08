"""AC-119 to AC-127 — coverage, and the one thing that must not move.

AC-124 is the gate: a plan edited today cannot change what a patient owed
yesterday. Everything in this file exists to make that true and to prove it.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from billing.models import Invoice, Service, charge, open_invoice_for
from insurance.coverage import invoice_split, policies_for, resolve
from insurance.models import (
    ChargeCoverage,
    CoverageRule,
    PatientPolicy,
    Plan,
)


def charge_for(visit, code, **extra):
    item, _ = charge(
        visit=visit, service_code=code, description=code,
        source_type="test", source_id=f"{code}-{extra.get('n', 1)}", **extra,
    )
    return item


# --- the split ----------------------------------------------------------------

@pytest.mark.django_db
def test_a_service_rule_beats_the_category_rule(insured_patient, open_visit, scheme):
    """AC-120, AC-123.

    Consultations are 90% for the category, but this consultation is covered in
    full by its own rule. A category rule silently overriding the exception
    somebody wrote for one service is the failure this ordering prevents.
    """
    item, _ = charge(
        visit=open_visit, service_code="CONSULT", description="Consultation",
        source_type="test", source_id="c1",
    )
    coverage = item.coverage
    assert coverage.scheme_amount == Decimal("5000.00")
    assert coverage.patient_amount == Decimal("0.00")
    assert coverage.basis == CoverageRule.FULL
    assert "pays in full" in coverage.rule_description
    assert coverage.policy.policy_number == "HYG/12345"


@pytest.mark.django_db
def test_a_percentage_rule_splits_the_charge(insured_patient, open_visit, scheme, tariff):
    """AC-120. The category rule applies to a consultation with no rule of its own."""
    other = Service.objects.create(
        category=tariff["consult"].category, name="Follow-up review", code="REVIEW"
    )
    from billing.models import ServicePrice

    ServicePrice.objects.create(
        service=other, facility=open_visit.facility, amount="10000.00"
    )
    item, _ = charge(
        visit=open_visit, service_code="REVIEW", description="Review",
        source_type="test", source_id="r1",
    )
    coverage = item.coverage
    assert coverage.scheme_amount == Decimal("9000.00")
    assert coverage.patient_amount == Decimal("1000.00")
    assert coverage.applied_percent == Decimal("90.00")
    assert "90%" in coverage.rule_description


@pytest.mark.django_db
def test_a_fixed_copay_leaves_the_patient_the_copay(insured_patient, open_visit, scheme):
    """AC-120. The laboratory rule is a flat ₦500 to the patient."""
    item, _ = charge(
        visit=open_visit, service_code="LAB-FBC", description="Full blood count",
        source_type="test", source_id="l1",
    )
    coverage = item.coverage
    assert coverage.patient_amount == Decimal("500.00")
    assert coverage.scheme_amount == Decimal("3000.00")  # 3500 − 500
    assert coverage.applied_copay == Decimal("500.00")


@pytest.mark.django_db
def test_a_copay_never_exceeds_the_charge(insured_patient, open_visit, scheme, tariff,
                                          facility_a):
    """A ₦500 co-pay on a ₦200 test must not bill the patient ₦500.

    Capped, or a small charge under a large co-pay hands the patient a bill
    bigger than the service they received.
    """
    from billing.models import ServicePrice

    cheap = Service.objects.create(
        category=tariff["fbc_service"].category, name="Urine dipstick", code="DIP"
    )
    ServicePrice.objects.create(service=cheap, facility=facility_a, amount="200.00")
    item, _ = charge(
        visit=open_visit, service_code="DIP", description="Dipstick",
        source_type="test", source_id="d1",
    )
    assert item.coverage.patient_amount == Decimal("200.00")
    assert item.coverage.scheme_amount == Decimal("0.00")


@pytest.mark.django_db
def test_an_excluded_service_names_the_exclusion(insured_patient, open_visit, scheme):
    """AC-125. An unexplained amount on a bill is a dispute waiting to happen."""
    item, _ = charge(
        visit=open_visit, service_code="COSM", description="Cosmetic procedure",
        source_type="test", source_id="x1",
    )
    coverage = item.coverage
    assert coverage.scheme_amount == Decimal("0.00")
    assert coverage.patient_amount == Decimal("40000.00")
    assert coverage.basis == CoverageRule.EXCLUDED
    assert "not a scheme benefit" in coverage.rule_description


@pytest.mark.django_db
def test_a_service_with_no_rule_is_flagged_rather_than_assumed_covered(
    insured_patient, open_visit, scheme
):
    """AC-126 (negative).

    The plan says unruled services are the patient's, and the row records that
    no rule existed — so the billing office can see it rather than discovering
    it when the provider rejects the line.
    """
    item, _ = charge(
        visit=open_visit, service_code="PHYSIO", description="Physiotherapy",
        source_type="test", source_id="p1",
    )
    coverage = item.coverage
    assert coverage.scheme_amount == Decimal("0.00")
    assert coverage.patient_amount == Decimal("7000.00")
    assert coverage.hold_reason == ChargeCoverage.HELD_NO_RULE
    assert coverage.is_claimable is False
    assert "No coverage rule" in coverage.rule_description


@pytest.mark.django_db
def test_a_plan_that_covers_unruled_services_says_so(
    insured_patient, open_visit, scheme
):
    """AC-126, the other real scheme behaviour. Both exist; the plan decides."""
    plan = scheme["plan"]
    plan.unruled_services = Plan.COVERED
    plan.default_scheme_percent = Decimal("80.00")
    plan.save(update_fields=["unruled_services", "default_scheme_percent"])

    item, _ = charge(
        visit=open_visit, service_code="PHYSIO", description="Physiotherapy",
        source_type="test", source_id="p2",
    )
    coverage = item.coverage
    assert coverage.scheme_amount == Decimal("5600.00")
    assert coverage.patient_amount == Decimal("1400.00")
    assert "80% by default" in coverage.rule_description


@pytest.mark.django_db
def test_a_self_paying_patient_is_recorded_as_such(patient, open_visit, tariff):
    """A line with no coverage row and a line for an uninsured patient are
    different states, and the invoice has to be able to tell them apart."""
    item, _ = charge(
        visit=open_visit, service_code="CONSULT", description="Consultation",
        source_type="test", source_id="s1",
    )
    coverage = item.coverage
    assert coverage.policy is None
    assert coverage.scheme_amount == Decimal("0.00")
    assert coverage.patient_amount == Decimal("5000.00")
    assert "No insurance policy in force" in coverage.rule_description


# --- AC-124, the gate ---------------------------------------------------------

@pytest.mark.django_db
def test_editing_a_plan_does_not_change_a_charge_already_raised(
    insured_patient, open_visit, scheme
):
    """AC-124 — the gate.

    A scheme renegotiates in March; a patient treated in February owed what
    February's rules said. A system that recomputes tells them otherwise while
    they are standing at the cash desk holding a receipt that disagrees.
    """
    item, _ = charge(
        visit=open_visit, service_code="LAB-FBC", description="Full blood count",
        source_type="test", source_id="gate1",
    )
    before = {
        "scheme": item.coverage.scheme_amount,
        "patient": item.coverage.patient_amount,
        "basis": item.coverage.basis,
        "copay": item.coverage.applied_copay,
        "description": item.coverage.rule_description,
    }

    # The scheme renegotiates: the co-pay quadruples and the rule changes shape.
    rule = CoverageRule.objects.get(plan=scheme["plan"], category__name="Laboratory")
    rule.basis = CoverageRule.PERCENTAGE
    rule.scheme_percent = Decimal("40.00")
    rule.patient_copay = None
    rule.save()
    scheme["plan"].default_scheme_percent = Decimal("10.00")
    scheme["plan"].save(update_fields=["default_scheme_percent"])

    item.coverage.refresh_from_db()
    assert item.coverage.scheme_amount == before["scheme"]
    assert item.coverage.patient_amount == before["patient"]
    assert item.coverage.basis == before["basis"]
    assert item.coverage.applied_copay == before["copay"]
    assert item.coverage.rule_description == before["description"]


@pytest.mark.django_db
def test_the_answer_survives_the_rule_being_deleted(insured_patient, open_visit, scheme):
    """AC-124. The stored copy is the authority, so configuration stays
    deletable without rewriting history."""
    item, _ = charge(
        visit=open_visit, service_code="COSM", description="Cosmetic",
        source_type="test", source_id="gate2",
    )
    assert item.coverage.rule is not None
    CoverageRule.objects.get(plan=scheme["plan"], category__name="Cosmetic").delete()

    item.coverage.refresh_from_db()
    assert item.coverage.rule is None          # the link went
    assert item.coverage.basis == CoverageRule.EXCLUDED   # the answer did not
    assert item.coverage.patient_amount == Decimal("40000.00")
    assert "not a scheme benefit" in item.coverage.rule_description


@pytest.mark.django_db
@pytest.mark.parametrize("code,expected_patient", [
    ("CONSULT", "0.00"), ("LAB-FBC", "500.00"), ("COSM", "40000.00"),
    ("PHYSIO", "7000.00"),
])
def test_every_split_is_stable_across_a_repricing(
    insured_patient, open_visit, scheme, code, expected_patient
):
    """AC-124 as a property, over each rule shape.

    Re-pricing the *service* is the other way this could move: the coverage row
    holds amounts, not a percentage applied to a live price.
    """
    from billing.models import ServicePrice

    item, _ = charge(
        visit=open_visit, service_code=code, description=code,
        source_type="test", source_id=f"prop-{code}",
    )
    assert item.coverage.patient_amount == Decimal(expected_patient)

    price = ServicePrice.objects.get(
        service__code=code, facility=open_visit.facility
    )
    price.amount = price.amount * 3
    price.save(update_fields=["amount"])

    item.coverage.refresh_from_db()
    assert item.coverage.patient_amount == Decimal(expected_patient)


@pytest.mark.django_db
def test_resolving_twice_keeps_the_first_answer(insured_patient, open_visit, scheme):
    """A retried request must not re-split a charge."""
    item, _ = charge(
        visit=open_visit, service_code="LAB-FBC", description="FBC",
        source_type="test", source_id="idem",
    )
    first = item.coverage.pk
    again = resolve(
        invoice_item=item, service=item.service, amount=item.amount,
        patient=insured_patient, visit=open_visit,
    )
    assert again.pk == first
    assert ChargeCoverage.objects.filter(invoice_item=item).count() == 1


# --- policies -----------------------------------------------------------------

@pytest.mark.django_db
def test_an_expired_policy_is_not_used(patient, open_visit, scheme, records_officer):
    """AC-122 (negative). Judged on the date of service, not today."""
    PatientPolicy.objects.create(
        patient=patient, plan=scheme["plan"], policy_number="OLD/1",
        starts_on=date.today() - timedelta(days=800),
        ends_on=date.today() - timedelta(days=30),
        recorded_by=records_officer,
    )
    assert policies_for(patient) == []

    item, _ = charge(
        visit=open_visit, service_code="CONSULT", description="Consultation",
        source_type="test", source_id="exp1",
    )
    assert item.coverage.policy is None
    assert item.coverage.patient_amount == Decimal("5000.00")


@pytest.mark.django_db
def test_a_policy_not_yet_started_is_not_used(patient, scheme, records_officer):
    """AC-122 (negative), the other end."""
    PatientPolicy.objects.create(
        patient=patient, plan=scheme["plan"], policy_number="FUTURE/1",
        starts_on=date.today() + timedelta(days=10),
        recorded_by=records_officer,
    )
    assert policies_for(patient) == []


@pytest.mark.django_db
def test_two_policies_pay_in_the_stated_order(
    patient, open_visit, scheme, records_officer, facility_a
):
    """AC-121. A patient can hold an employer HMO and a private top-up, and
    which pays first is the billing office's decision rather than an accident
    of insertion order."""
    from insurance.models import InsuranceProvider

    second_provider = InsuranceProvider.objects.create(name="AXA Mansard", code="AXA")
    second_plan = Plan.objects.create(
        provider=second_provider, name="Basic", code="BASIC",
        unruled_services=Plan.COVERED, default_scheme_percent="50.00",
    )
    PatientPolicy.objects.create(
        patient=patient, plan=second_plan, policy_number="AXA/9",
        starts_on=date.today() - timedelta(days=10), precedence=1,
        recorded_by=records_officer,
    )
    PatientPolicy.objects.create(
        patient=patient, plan=scheme["plan"], policy_number="HYG/9",
        starts_on=date.today() - timedelta(days=10), precedence=2,
        recorded_by=records_officer,
    )
    assert [p.plan.code for p in policies_for(patient)] == ["BASIC", "GOLD"]

    item, _ = charge(
        visit=open_visit, service_code="CONSULT", description="Consultation",
        source_type="test", source_id="prec1",
    )
    # The precedence-1 plan resolved it: 50% by default, not GOLD's full cover.
    assert item.coverage.policy.plan.code == "BASIC"
    assert item.coverage.scheme_amount == Decimal("2500.00")


# --- the invoice --------------------------------------------------------------

@pytest.mark.django_db
def test_the_invoice_shows_the_patient_share_separately(
    insured_patient, open_visit, scheme
):
    """AC-127. A cashier never asks a patient for the scheme's money."""
    for code, source in [("CONSULT", "i1"), ("LAB-FBC", "i2"), ("COSM", "i3")]:
        charge(
            visit=open_visit, service_code=code, description=code,
            source_type="test", source_id=source,
        )
    invoice = Invoice.objects.get(visit=open_visit)
    split = invoice_split(invoice)

    # 5000 consult (full) + 3500 lab (500 co-pay) + 40000 cosmetic (excluded)
    assert invoice.total == Decimal("48500.00")
    assert split["scheme_share"] == Decimal("8000.00")   # 5000 + 3000
    assert split["patient_share"] == Decimal("40500.00")  # 500 + 40000
    assert split["scheme_share"] + split["patient_share"] == invoice.total
    assert split["unresolved"] == Decimal("0.00")


@pytest.mark.django_db
def test_an_unresolved_line_counts_as_the_patients(insured_patient, open_visit, scheme):
    """An unresolved line shown as covered would understate the bill, which is
    the wrong way round to be wrong."""
    from billing.models import InvoiceItem

    invoice = open_invoice_for(open_visit)
    InvoiceItem.objects.create(
        invoice=invoice, description="Raised without resolution", quantity=1,
        unit_price=Decimal("1000.00"), source_type="direct", source_id="u1",
    )
    split = invoice_split(invoice)
    assert split["unresolved"] == Decimal("1000.00")
    assert split["patient_share"] == Decimal("1000.00")
