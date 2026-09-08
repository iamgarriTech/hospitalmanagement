"""AC-128 to AC-131 — eligibility, preauthorisation, and never blocking care.

AC-131 is the one to hold onto: a hospital cannot refuse a sick patient while
waiting for an HMO to answer the telephone, and a system that makes that easy
is a system that will be used to do it. Every case here ends with the charge
raised and the *claim* held.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from billing.models import charge
from insurance.models import (
    ChargeCoverage,
    CoverageRule,
    EligibilityCheck,
    PatientPolicy,
    Preauthorisation,
)

# --- eligibility --------------------------------------------------------------

@pytest.mark.django_db
def test_an_unverified_policy_is_still_usable(insured_patient, open_visit, scheme):
    """AC-128.

    Nobody has rung the HMO. The patient is still treated and the charge is
    still split — the alternative is refusing care over an administrative gap.
    """
    policy = PatientPolicy.objects.get(patient=insured_patient)
    assert policy.latest_eligibility is None

    item, _ = charge(
        visit=open_visit, service_code="CONSULT", description="Consultation",
        source_type="test", source_id="unver",
    )
    assert item.coverage.policy == policy
    assert item.coverage.scheme_amount == Decimal("5000.00")


@pytest.mark.django_db
def test_an_eligibility_check_records_who_asked_and_what_was_said(
    insured_patient, scheme, billing_officer
):
    """AC-128. "We checked on the 3rd and they said yes" is a different fact
    from "this policy is valid", and it is the first one a provider disputes."""
    policy = PatientPolicy.objects.get(patient=insured_patient)
    check = EligibilityCheck.objects.create(
        policy=policy, outcome=EligibilityCheck.CONFIRMED,
        checked_by=billing_officer, reference="HYG-EL-8891",
        valid_until=date.today() + timedelta(days=30),
    )
    assert check.is_current is True
    assert policy.latest_eligibility == check
    assert check.checked_by == billing_officer


@pytest.mark.django_db
def test_a_declined_eligibility_check_must_say_why(insured_patient, billing_officer):
    """AC-128 (negative). A decline with no reason cannot be argued with."""
    from django.db import IntegrityError

    policy = PatientPolicy.objects.get(patient=insured_patient)
    with pytest.raises(IntegrityError):
        EligibilityCheck.objects.create(
            policy=policy, outcome=EligibilityCheck.DECLINED,
            checked_by=billing_officer, note="",
        )


@pytest.mark.django_db
def test_an_expired_eligibility_check_is_not_current(insured_patient, billing_officer):
    policy = PatientPolicy.objects.get(patient=insured_patient)
    check = EligibilityCheck.objects.create(
        policy=policy, outcome=EligibilityCheck.CONFIRMED,
        checked_by=billing_officer, valid_until=date.today() - timedelta(days=1),
    )
    assert check.is_current is False


@pytest.mark.django_db
def test_an_unreachable_provider_is_a_recorded_outcome(insured_patient, billing_officer):
    """"We could not get through" is a real answer and belongs on the record,
    not as an absence of one."""
    policy = PatientPolicy.objects.get(patient=insured_patient)
    check = EligibilityCheck.objects.create(
        policy=policy, outcome=EligibilityCheck.UNREACHABLE,
        checked_by=billing_officer, note="Lines down all afternoon.",
    )
    assert check.is_current is False
    assert policy.latest_eligibility == check


# --- preauthorisation ---------------------------------------------------------

@pytest.fixture
def authorised_service(scheme, tariff):
    """Make the consultation require authorisation."""
    rule = CoverageRule.objects.get(plan=scheme["plan"], service=tariff["consult"])
    rule.requires_preauthorisation = True
    rule.save(update_fields=["requires_preauthorisation"])
    return tariff["consult"]


@pytest.mark.django_db
def test_care_proceeds_and_the_claim_is_held(
    insured_patient, open_visit, scheme, authorised_service
):
    """AC-131 — the criterion.

    No authorisation. The charge is raised, the scheme's share is still worked
    out, and the line is held rather than the treatment being refused.
    """
    item, _ = charge(
        visit=open_visit, service_code="CONSULT", description="Consultation",
        source_type="test", source_id="hold1",
    )
    coverage = item.coverage
    assert coverage.scheme_amount == Decimal("5000.00")
    assert coverage.hold_reason == ChargeCoverage.HELD_NO_PREAUTH
    assert coverage.is_claimable is False
    assert "awaiting preauthorisation" in coverage.rule_description


@pytest.mark.django_db
def test_an_approved_authorisation_makes_the_line_claimable(
    insured_patient, open_visit, scheme, authorised_service, billing_officer
):
    """AC-130."""
    policy = PatientPolicy.objects.get(patient=insured_patient)
    authorisation = Preauthorisation.objects.create(
        policy=policy, patient=insured_patient, visit=open_visit,
        requested_for="Outpatient consultation",
        status=Preauthorisation.APPROVED, reference="HYG-AUTH-4410",
        approved_amount=Decimal("5000.00"),
        valid_from=date.today() - timedelta(days=1),
        valid_until=date.today() + timedelta(days=14),
        requested_by=billing_officer,
    )
    authorisation.services.add(authorised_service)

    item, _ = charge(
        visit=open_visit, service_code="CONSULT", description="Consultation",
        source_type="test", source_id="auth1",
    )
    coverage = item.coverage
    assert coverage.hold_reason == ""
    assert coverage.preauthorisation == authorisation
    assert coverage.is_claimable is True


@pytest.mark.django_db
def test_an_expired_authorisation_does_not_satisfy_the_requirement(
    insured_patient, open_visit, scheme, authorised_service, billing_officer
):
    """AC-130 (negative). Approved is not enough — it has to be in date."""
    policy = PatientPolicy.objects.get(patient=insured_patient)
    authorisation = Preauthorisation.objects.create(
        policy=policy, patient=insured_patient, visit=open_visit,
        requested_for="Consultation", status=Preauthorisation.APPROVED,
        reference="HYG-AUTH-OLD",
        valid_from=date.today() - timedelta(days=60),
        valid_until=date.today() - timedelta(days=1),
        requested_by=billing_officer,
    )
    authorisation.services.add(authorised_service)
    assert authorisation.is_valid_for(authorised_service) is False

    item, _ = charge(
        visit=open_visit, service_code="CONSULT", description="Consultation",
        source_type="test", source_id="expauth",
    )
    assert item.coverage.hold_reason == ChargeCoverage.HELD_NO_PREAUTH
    assert item.coverage.is_claimable is False


@pytest.mark.django_db
def test_an_authorisation_for_a_different_service_does_not_transfer(
    insured_patient, open_visit, scheme, authorised_service, billing_officer, tariff
):
    """AC-130 (negative). An authorisation for a scan does not cover a
    consultation."""
    policy = PatientPolicy.objects.get(patient=insured_patient)
    authorisation = Preauthorisation.objects.create(
        policy=policy, patient=insured_patient, visit=open_visit,
        requested_for="Full blood count", status=Preauthorisation.APPROVED,
        reference="HYG-AUTH-OTHER", requested_by=billing_officer,
    )
    authorisation.services.add(tariff["fbc_service"])
    assert authorisation.is_valid_for(authorised_service) is False


@pytest.mark.django_db
def test_a_blanket_authorisation_covers_the_episode(
    insured_patient, open_visit, scheme, authorised_service, billing_officer
):
    """Schemes often authorise an episode rather than a list of services, and
    an authorisation with no services named is exactly that."""
    policy = PatientPolicy.objects.get(patient=insured_patient)
    Preauthorisation.objects.create(
        policy=policy, patient=insured_patient, visit=open_visit,
        requested_for="Admission and associated care",
        status=Preauthorisation.APPROVED, reference="HYG-AUTH-BLANKET",
        requested_by=billing_officer,
    )
    item, _ = charge(
        visit=open_visit, service_code="CONSULT", description="Consultation",
        source_type="test", source_id="blanket",
    )
    assert item.coverage.hold_reason == ""
    assert item.coverage.is_claimable is True


@pytest.mark.django_db
def test_an_approved_authorisation_must_carry_a_reference(
    insured_patient, open_visit, billing_officer
):
    """AC-129 (negative), at the database. An approval with no reference is
    unclaimable, so it cannot be recorded as an approval."""
    from django.db import IntegrityError

    policy = PatientPolicy.objects.get(patient=insured_patient)
    with pytest.raises(IntegrityError):
        Preauthorisation.objects.create(
            policy=policy, patient=insured_patient, visit=open_visit,
            requested_for="Something", status=Preauthorisation.APPROVED,
            reference="", requested_by=billing_officer,
        )


@pytest.mark.django_db
def test_a_declined_authorisation_states_why(insured_patient, open_visit, billing_officer):
    from django.db import IntegrityError

    policy = PatientPolicy.objects.get(patient=insured_patient)
    with pytest.raises(IntegrityError):
        Preauthorisation.objects.create(
            policy=policy, patient=insured_patient, visit=open_visit,
            requested_for="Something", status=Preauthorisation.DECLINED,
            decline_reason="", requested_by=billing_officer,
        )


@pytest.mark.django_db
def test_a_charge_above_the_plan_threshold_needs_authorisation(
    insured_patient, open_visit, scheme
):
    """AC-129. The threshold is the plan's, not a rule's — schemes set a value
    above which everything needs asking about."""
    plan = scheme["plan"]
    plan.requires_preauthorisation_above = Decimal("1000.00")
    plan.save(update_fields=["requires_preauthorisation_above"])

    item, _ = charge(
        visit=open_visit, service_code="CONSULT", description="Consultation",
        source_type="test", source_id="thresh",
    )
    assert item.coverage.hold_reason == ChargeCoverage.HELD_NO_PREAUTH

    # And a charge below it does not.
    small, _ = charge(
        visit=open_visit, service_code="LAB-FBC", description="FBC",
        source_type="test", source_id="thresh2", unit_price=Decimal("400.00"),
    )
    assert small.coverage.hold_reason == ""


# --- limits -------------------------------------------------------------------

@pytest.mark.django_db
def test_an_annual_limit_reduces_the_last_covered_charge(
    insured_patient, open_visit, scheme
):
    """The limit is what catches a hospital out at year end, so a charge that
    crosses it is split rather than either wholly covered or wholly refused."""
    plan = scheme["plan"]
    plan.annual_limit = Decimal("7000.00")
    plan.save(update_fields=["annual_limit"])

    first, _ = charge(
        visit=open_visit, service_code="CONSULT", description="Consultation",
        source_type="test", source_id="lim1",
    )
    assert first.coverage.scheme_amount == Decimal("5000.00")

    # 5000 used, 2000 left, and this consultation would cost the scheme 5000.
    second, _ = charge(
        visit=open_visit, service_code="CONSULT", description="Consultation 2",
        source_type="test", source_id="lim2",
    )
    assert second.coverage.scheme_amount == Decimal("2000.00")
    assert second.coverage.patient_amount == Decimal("3000.00")
    assert "annual limit" in second.coverage.rule_description

    # Exhausted: the next one is wholly the patient's, and says so.
    third, _ = charge(
        visit=open_visit, service_code="CONSULT", description="Consultation 3",
        source_type="test", source_id="lim3",
    )
    assert third.coverage.scheme_amount == Decimal("0.00")
    assert third.coverage.patient_amount == Decimal("5000.00")
    assert third.coverage.hold_reason == ChargeCoverage.HELD_LIMIT
    assert "already reached" in third.coverage.rule_description
