"""The insurance endpoints, and the boundaries they refuse at.

The permission boundaries are the point of this file. Insurance is where a
hospital's money is, so every verb here has a negative test: a cashier cannot
change a plan, a billing officer cannot edit a split that has already been
decided, and nobody can reach another facility's claims.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from audit.models import AuditEvent
from billing.models import charge
from insurance.models import (
    ChargeCoverage,
    ClaimBatch,
    ClaimLine,
    CoverageRule,
    PatientPolicy,
)

# --- configuration ------------------------------------------------------------

@pytest.mark.django_db
def test_a_provider_and_plan_are_administrable(as_billing_officer, tariff):
    """AC-119, AC-120."""
    created = as_billing_officer.post(
        reverse("insuranceprovider-list"),
        {"name": "Reliance HMO", "code": "REL", "provider_type": "hmo",
         "claim_channel": "portal", "settlement_days": 45,
         "claim_submission_note": "provider.reliancehmo.com/claims"},
        format="json",
    )
    assert created.status_code == 201, created.data
    assert created.data["provider_type_display"] == "HMO"
    assert created.data["plan_count"] == 0

    plan = as_billing_officer.post(
        reverse("plan-list"),
        {"provider": created.data["id"], "name": "Silver", "code": "SLV",
         "unruled_services": "excluded", "default_scheme_percent": "80.00",
         "annual_limit": "500000.00"},
        format="json",
    )
    assert plan.status_code == 201, plan.data
    assert plan.data["unruled_display"] == "Not covered — the patient pays"

    rule = as_billing_officer.post(
        reverse("coveragerule-list"),
        {"plan": plan.data["id"], "category": tariff["consult"].category_id,
         "basis": "percentage", "scheme_percent": "70.00"},
        format="json",
    )
    assert rule.status_code == 201, rule.data
    assert rule.data["basis_display"] == "Scheme pays a percentage"

    assert AuditEvent.objects.filter(action="insurance.provider_added").exists()
    assert AuditEvent.objects.filter(action="insurance.rule_added").exists()


@pytest.mark.django_db
def test_a_rule_naming_both_a_service_and_a_category_is_refused(
    as_billing_officer, scheme, tariff
):
    """AC-120 (negative). There would be no order in which to apply it."""
    response = as_billing_officer.post(
        reverse("coveragerule-list"),
        {"plan": scheme["plan"].pk, "service": tariff["consult"].pk,
         "category": tariff["consult"].category_id, "basis": "full"},
        format="json",
    )
    assert response.status_code == 400
    assert "not both" in str(response.data)


@pytest.mark.django_db
def test_an_exclusion_without_a_reason_is_refused(as_billing_officer, scheme, tariff):
    """AC-125 (negative). An unexplained amount on a bill is a dispute."""
    response = as_billing_officer.post(
        reverse("coveragerule-list"),
        {"plan": scheme["plan"].pk, "service": tariff["fbc_service"].pk,
         "basis": "excluded", "exclusion_reason": ""},
        format="json",
    )
    assert response.status_code == 400
    assert "invoice line" in str(response.data)


@pytest.mark.django_db
def test_a_percentage_rule_without_a_percentage_is_refused(
    as_billing_officer, scheme, tariff
):
    response = as_billing_officer.post(
        reverse("coveragerule-list"),
        {"plan": scheme["plan"].pk, "service": tariff["fbc_service"].pk,
         "basis": "percentage"},
        format="json",
    )
    assert response.status_code == 400
    assert "percentage" in str(response.data).lower()


@pytest.mark.django_db
def test_a_cashier_cannot_change_what_a_scheme_covers(as_cashier, scheme, tariff):
    """(negative). Taking money and deciding what a scheme owes are different
    jobs, and the second one moves the hospital's revenue."""
    response = as_cashier.post(
        reverse("coveragerule-list"),
        {"plan": scheme["plan"].pk, "service": tariff["consult"].pk, "basis": "full"},
        format="json",
    )
    assert response.status_code == 403
    denial = AuditEvent.objects.filter(action="permission.denied").last()
    assert denial.changes["after"]["permission"] == "insurance.manage_coverage"


@pytest.mark.django_db
def test_editing_a_plan_is_audited(as_billing_officer, scheme):
    """The audit row is what lets somebody prove afterwards that past charges
    did not move when the plan did."""
    response = as_billing_officer.patch(
        reverse("plan-detail", args=[scheme["plan"].pk]),
        {"default_scheme_percent": "60.00"}, format="json",
    )
    assert response.status_code == 200, response.data
    event = AuditEvent.objects.get(action="insurance.plan_changed")
    assert event.changes["before"]["default_scheme_percent"] == "100.00"
    assert event.changes["after"]["default_scheme_percent"] == "60.00"


# --- policies -----------------------------------------------------------------

@pytest.mark.django_db
def test_a_policy_is_recorded_and_shows_on_the_patient(
    as_billing_officer, patient, scheme
):
    """AC-121."""
    created = as_billing_officer.post(
        reverse("patientpolicy-list"),
        {"patient": patient.pk, "plan": scheme["plan"].pk,
         "policy_number": "HYG/55501", "starts_on": str(date.today()),
         "ends_on": str(date.today() + timedelta(days=365)), "precedence": 1},
        format="json",
    )
    assert created.status_code == 201, created.data
    assert created.data["is_current"] is True
    assert created.data["provider_name"] == "Hygeia HMO"
    assert created.data["eligibility"] is None

    at_desk = as_billing_officer.get(
        reverse("patientpolicy-for-patient"), {"patient": patient.pk}
    )
    assert at_desk.status_code == 200
    assert at_desk.data["has_cover"] is True
    assert len(at_desk.data["policies"]) == 1


@pytest.mark.django_db
def test_a_self_paying_patient_is_a_normal_answer(as_billing_officer, patient):
    """Most patients here pay for themselves, so "no cover" is information
    rather than an error."""
    response = as_billing_officer.get(
        reverse("patientpolicy-for-patient"), {"patient": patient.pk}
    )
    assert response.status_code == 200
    assert response.data["has_cover"] is False
    assert response.data["policies"] == []


@pytest.mark.django_db
def test_a_dependant_must_state_the_relationship(as_billing_officer, patient, scheme):
    response = as_billing_officer.post(
        reverse("patientpolicy-list"),
        {"patient": patient.pk, "plan": scheme["plan"].pk, "policy_number": "D/1",
         "starts_on": str(date.today()), "is_dependant": True, "relationship": ""},
        format="json",
    )
    assert response.status_code == 400
    assert "principal member" in str(response.data)


@pytest.mark.django_db
def test_a_policy_ending_before_it_starts_is_refused(
    as_billing_officer, patient, scheme
):
    response = as_billing_officer.post(
        reverse("patientpolicy-list"),
        {"patient": patient.pk, "plan": scheme["plan"].pk, "policy_number": "B/1",
         "starts_on": str(date.today()),
         "ends_on": str(date.today() - timedelta(days=1))},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_an_eligibility_check_is_recorded_against_the_policy(
    as_billing_officer, insured_patient, billing_officer
):
    """AC-128."""
    policy = PatientPolicy.objects.get(patient=insured_patient)
    response = as_billing_officer.post(
        reverse("patientpolicy-eligibility", args=[policy.pk]),
        {"outcome": "confirmed", "reference": "HYG-EL-77",
         "valid_until": str(date.today() + timedelta(days=30))},
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["eligibility"]["outcome"] == "confirmed"
    assert response.data["eligibility"]["is_current"] is True
    assert response.data["eligibility"]["checked_by"] == "Tolu Billing"

    event = AuditEvent.objects.get(action="insurance.eligibility_checked")
    assert event.changes["after"]["reference"] == "HYG-EL-77"


@pytest.mark.django_db
def test_a_declined_check_must_say_why(as_billing_officer, insured_patient):
    policy = PatientPolicy.objects.get(patient=insured_patient)
    response = as_billing_officer.post(
        reverse("patientpolicy-eligibility", args=[policy.pk]),
        {"outcome": "declined", "note": ""}, format="json",
    )
    assert response.status_code == 400
    assert "argued with" in str(response.data)


# --- preauthorisation ---------------------------------------------------------

@pytest.mark.django_db
def test_an_authorisation_is_requested_and_decided(
    as_billing_officer, insured_patient, open_visit, tariff
):
    """AC-130."""
    policy = PatientPolicy.objects.get(patient=insured_patient)
    requested = as_billing_officer.post(
        reverse("preauthorisation-list"),
        {"policy": policy.pk, "visit": open_visit.pk,
         "requested_for": "CT abdomen for query perforation",
         "services": [tariff["fbc_service"].pk],
         "estimated_amount": "95000.00"},
        format="json",
    )
    assert requested.status_code == 201, requested.data
    assert requested.data["status"] == "requested"
    assert requested.data["patient"] == insured_patient.pk
    assert requested.data["service_names"] == ["Full blood count"]

    outstanding = as_billing_officer.get(reverse("preauthorisation-outstanding"))
    assert [row["id"] for row in outstanding.data] == [requested.data["id"]]

    approved = as_billing_officer.post(
        reverse("preauthorisation-decide", args=[requested.data["id"]]),
        {"outcome": "approved", "reference": "HYG-AUTH-9001",
         "approved_amount": "95000.00",
         "valid_from": str(date.today()),
         "valid_until": str(date.today() + timedelta(days=14))},
        format="json",
    )
    assert approved.status_code == 200, approved.data
    assert approved.data["status"] == "approved"
    assert approved.data["reference"] == "HYG-AUTH-9001"

    assert as_billing_officer.get(
        reverse("preauthorisation-outstanding")
    ).data == []
    event = AuditEvent.objects.get(action="insurance.preauthorisation_decided")
    assert event.changes["after"]["reference"] == "HYG-AUTH-9001"


@pytest.mark.django_db
def test_an_approval_without_a_reference_is_refused(
    as_billing_officer, insured_patient, open_visit
):
    """AC-129 (negative). A claim cannot be made without one."""
    policy = PatientPolicy.objects.get(patient=insured_patient)
    requested = as_billing_officer.post(
        reverse("preauthorisation-list"),
        {"policy": policy.pk, "visit": open_visit.pk, "requested_for": "Something"},
        format="json",
    )
    response = as_billing_officer.post(
        reverse("preauthorisation-decide", args=[requested.data["id"]]),
        {"outcome": "approved", "reference": ""}, format="json",
    )
    assert response.status_code == 400
    assert "authorisation reference" in str(response.data)


@pytest.mark.django_db
def test_a_decline_without_a_reason_is_refused(
    as_billing_officer, insured_patient, open_visit
):
    policy = PatientPolicy.objects.get(patient=insured_patient)
    requested = as_billing_officer.post(
        reverse("preauthorisation-list"),
        {"policy": policy.pk, "visit": open_visit.pk, "requested_for": "Something"},
        format="json",
    )
    response = as_billing_officer.post(
        reverse("preauthorisation-decide", args=[requested.data["id"]]),
        {"outcome": "declined", "decline_reason": ""}, format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_a_decided_authorisation_cannot_be_decided_again(
    as_billing_officer, insured_patient, open_visit
):
    policy = PatientPolicy.objects.get(patient=insured_patient)
    requested = as_billing_officer.post(
        reverse("preauthorisation-list"),
        {"policy": policy.pk, "visit": open_visit.pk, "requested_for": "Something"},
        format="json",
    )
    as_billing_officer.post(
        reverse("preauthorisation-decide", args=[requested.data["id"]]),
        {"outcome": "approved", "reference": "REF-1"}, format="json",
    )
    again = as_billing_officer.post(
        reverse("preauthorisation-decide", args=[requested.data["id"]]),
        {"outcome": "declined", "decline_reason": "changed our mind"}, format="json",
    )
    assert again.status_code == 409


# --- the split ----------------------------------------------------------------

@pytest.fixture
def split_visit(insured_patient, open_visit, scheme):
    for code, source in [("LAB-FBC", "a1"), ("COSM", "a2")]:
        charge(
            visit=open_visit, service_code=code, description=code,
            source_type="test", source_id=source,
        )
    from billing.models import Invoice

    return Invoice.objects.get(visit=open_visit)


@pytest.mark.django_db
def test_the_invoice_split_is_readable(as_billing_officer, split_visit):
    """AC-127. A cashier never asks a patient for the scheme's money."""
    response = as_billing_officer.get(
        reverse("chargecoverage-invoice-split"), {"invoice": split_visit.pk}
    )
    assert response.status_code == 200, response.data
    assert response.data["scheme_share"] == "3000.00"
    assert response.data["patient_share"] == "40500.00"
    assert response.data["unresolved"] == "0.00"
    assert len(response.data["lines"]) == 2
    excluded = next(
        row for row in response.data["lines"] if row["basis"] == "excluded"
    )
    assert "not a scheme benefit" in excluded["rule_description"]


@pytest.mark.django_db
def test_the_coverage_record_has_no_write_verb(as_billing_officer, split_visit):
    """AC-124 (negative), at the API surface.

    The split is decided when the charge is raised. An endpoint that could edit
    it would be an endpoint that rewrites what a patient owed, so there is not
    one — every verb but GET is refused.
    """
    coverage = ChargeCoverage.objects.first()
    url = reverse("chargecoverage-detail", args=[coverage.pk])
    for refused in (
        as_billing_officer.patch(url, {"scheme_amount": "0.00"}, format="json"),
        as_billing_officer.put(url, {"scheme_amount": "0.00"}, format="json"),
        as_billing_officer.delete(url),
    ):
        assert refused.status_code in (403, 405), refused.status_code

    coverage.refresh_from_db()
    assert coverage.scheme_amount == Decimal("3000.00")


@pytest.mark.django_db
def test_held_lines_are_on_a_work_list(
    as_billing_officer, insured_patient, open_visit, scheme, tariff
):
    """AC-131. A held line that dropped off every list would be money the
    hospital never asks for."""
    rule = CoverageRule.objects.get(plan=scheme["plan"], service=tariff["consult"])
    rule.requires_preauthorisation = True
    rule.save(update_fields=["requires_preauthorisation"])
    charge(
        visit=open_visit, service_code="CONSULT", description="Consultation",
        source_type="test", source_id="h1",
    )
    response = as_billing_officer.get(reverse("chargecoverage-held"))
    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]["hold_reason"] == "no_preauthorisation"
    assert response.data[0]["is_claimable"] is False


# --- claims -------------------------------------------------------------------

@pytest.fixture
def claim_ready(insured_patient, open_visit, scheme, finalised_encounter):
    for code, source in [("LAB-FBC", "cl1")]:
        charge(
            visit=open_visit, service_code=code, description=code,
            source_type="test", source_id=source,
        )
    return open_visit


def assemble_payload(scheme, facility):
    return {
        "provider": scheme["provider"].pk,
        "facility": facility.pk,
        "period_start": str(date.today() - timedelta(days=1)),
        "period_end": str(date.today() + timedelta(days=1)),
    }


@pytest.mark.django_db
def test_a_claim_is_previewed_then_assembled(
    as_billing_officer, claim_ready, scheme, facility_a
):
    """AC-132. The preview is so a billing officer sees what they are about to
    send."""
    preview = as_billing_officer.get(
        reverse("claimbatch-claimable"),
        {"provider": scheme["provider"].pk, "facility": facility_a.pk,
         "period_start": str(date.today() - timedelta(days=1)),
         "period_end": str(date.today() + timedelta(days=1))},
    )
    assert preview.status_code == 200, preview.data
    assert preview.data["total"] == "8000.00"
    assert len(preview.data["lines"]) == 2

    created = as_billing_officer.post(
        reverse("claimbatch-assemble"), assemble_payload(scheme, facility_a),
        format="json",
    )
    assert created.status_code == 201, created.data
    assert created.data["claimed_total"] == "8000.00"
    assert created.data["status"] == "draft"
    assert created.data["allowed_transitions"] == ["submitted"]
    assert created.data["skipped"] == 0


@pytest.mark.django_db
def test_the_full_claim_lifecycle_over_http(
    as_billing_officer, claim_ready, scheme, facility_a, tariff
):
    """AC-133, AC-137. Assemble, submit, acknowledge, part-pay."""
    claim = as_billing_officer.post(
        reverse("claimbatch-assemble"), assemble_payload(scheme, facility_a),
        format="json",
    ).data

    submitted = as_billing_officer.post(
        reverse("claimbatch-submit", args=[claim["id"]]),
        {"provider_reference": "HYG-BATCH-77"}, format="json",
    )
    assert submitted.status_code == 200, submitted.data
    assert submitted.data["status"] == "submitted"
    assert submitted.data["days_outstanding"] == 0

    acknowledged = as_billing_officer.post(
        reverse("claimbatch-acknowledge", args=[claim["id"]]), {}, format="json"
    )
    assert acknowledged.status_code == 200
    assert acknowledged.data["status"] == "acknowledged"

    lines = acknowledged.data["lines"]
    paid = as_billing_officer.post(
        reverse("providerpayment-record"),
        {"provider": scheme["provider"].pk, "facility": facility_a.pk,
         "reference": "HYG/RTGS/7", "amount": "7000.00",
         "received_on": str(date.today()), "method": tariff["cash"].pk,
         "allocations": [
             {"line": lines[0]["id"], "amount": str(lines[0]["claimed_amount"])},
             {"line": lines[1]["id"], "amount": "2000.00"},
         ]},
        format="json",
    )
    assert paid.status_code == 201, paid.data
    assert paid.data["allocated"] == "7000.00"
    assert paid.data["unallocated"] == "0.00"

    after = as_billing_officer.get(reverse("claimbatch-detail", args=[claim["id"]]))
    assert after.data["status"] == "part_paid"
    assert after.data["outstanding"] == "1000.00"


@pytest.mark.django_db
def test_a_rejected_claim_resubmits_over_http(
    as_billing_officer, claim_ready, scheme, facility_a
):
    """AC-135 — the gate, through the API."""
    claim = as_billing_officer.post(
        reverse("claimbatch-assemble"), assemble_payload(scheme, facility_a),
        format="json",
    ).data
    as_billing_officer.post(reverse("claimbatch-submit", args=[claim["id"]]), {},
                            format="json")

    rejected = as_billing_officer.post(
        reverse("claimbatch-reject", args=[claim["id"]]),
        {"reason": "Policy numbers transposed."}, format="json",
    )
    assert rejected.status_code == 200, rejected.data
    assert rejected.data["status"] == "rejected"

    resubmitted = as_billing_officer.post(
        reverse("claimbatch-resubmit", args=[claim["id"]]),
        {"reason": "Policy numbers corrected."}, format="json",
    )
    assert resubmitted.status_code == 201, resubmitted.data
    assert resubmitted.data["resubmits"] == claim["id"]
    assert resubmitted.data["claimed_total"] == "8000.00"

    # One live claim's worth of money is being asked for, not two.
    live = ClaimLine.objects.exclude(status=ClaimLine.REJECTED)
    assert sum(line.claimed_amount for line in live) == Decimal("8000.00")

    again = as_billing_officer.post(
        reverse("claimbatch-resubmit", args=[claim["id"]]),
        {"reason": "Again."}, format="json",
    )
    assert again.status_code == 400
    assert "already been resubmitted" in str(again.data)


@pytest.mark.django_db
def test_a_partial_rejection_names_the_lines(
    as_billing_officer, claim_ready, scheme, facility_a
):
    """AC-136."""
    claim = as_billing_officer.post(
        reverse("claimbatch-assemble"), assemble_payload(scheme, facility_a),
        format="json",
    ).data
    as_billing_officer.post(reverse("claimbatch-submit", args=[claim["id"]]), {},
                            format="json")
    line = claim["lines"][0]

    rejected = as_billing_officer.post(
        reverse("claimbatch-reject", args=[claim["id"]]),
        {"reason": "One line queried.",
         "line_reasons": {str(line["id"]): "Service not on this plan."}},
        format="json",
    )
    assert rejected.status_code == 200
    by_id = {row["id"]: row for row in rejected.data["lines"]}
    assert by_id[line["id"]]["status"] == "rejected"
    assert "not on this plan" in by_id[line["id"]]["rejection_reason"]
    other = next(row for row in rejected.data["lines"] if row["id"] != line["id"])
    assert other["status"] == "pending"


@pytest.mark.django_db
def test_a_shortfall_is_resolved_with_a_reason(
    as_billing_officer, as_accountant, claim_ready, scheme, facility_a, tariff
):
    """AC-137 (negative).

    Resolved by the accountant, not the billing desk that raised the claim:
    writing off money is the same class of decision as approving a discount.
    """
    claim = as_billing_officer.post(
        reverse("claimbatch-assemble"), assemble_payload(scheme, facility_a),
        format="json",
    ).data
    as_billing_officer.post(reverse("claimbatch-submit", args=[claim["id"]]), {},
                            format="json")
    as_billing_officer.post(reverse("claimbatch-acknowledge", args=[claim["id"]]), {},
                            format="json")
    line = claim["lines"][0]
    as_billing_officer.post(
        reverse("providerpayment-record"),
        {"provider": scheme["provider"].pk, "facility": facility_a.pk,
         "reference": "HYG/SHORT/9", "amount": "1000.00",
         "received_on": str(date.today()), "method": tariff["cash"].pk,
         "allocations": [{"line": line["id"], "amount": "1000.00"}]},
        format="json",
    )

    # The billing desk cannot write money off, however small.
    refused = as_billing_officer.post(
        reverse("claimline-shortfall", args=[line["id"]]),
        {"write_off": "500.00", "reason": "Agreed by telephone."}, format="json",
    )
    assert refused.status_code == 403

    blank = as_accountant.post(
        reverse("claimline-shortfall", args=[line["id"]]),
        {"write_off": "500.00", "reason": "  "}, format="json",
    )
    assert blank.status_code == 400

    resolved = as_accountant.post(
        reverse("claimline-shortfall", args=[line["id"]]),
        {"write_off": "500.00", "reason": "Agreed with the provider by telephone."},
        format="json",
    )
    assert resolved.status_code == 200, resolved.data
    assert resolved.data["written_off_amount"] == "500.00"
    assert "telephone" in resolved.data["shortfall_reason"]


@pytest.mark.django_db
def test_the_ageing_report_is_reachable(
    as_billing_officer, claim_ready, scheme, facility_a
):
    """AC-139."""
    claim = as_billing_officer.post(
        reverse("claimbatch-assemble"), assemble_payload(scheme, facility_a),
        format="json",
    ).data
    as_billing_officer.post(reverse("claimbatch-submit", args=[claim["id"]]), {},
                            format="json")

    response = as_billing_officer.get(
        reverse("insuranceprovider-ageing"), {"facility": facility_a.pk}
    )
    assert response.status_code == 200, response.data
    assert len(response.data) == 1
    assert response.data[0]["code"] == "HYG"
    assert response.data[0]["total"] == Decimal("8000.00")


# --- boundaries ---------------------------------------------------------------

@pytest.mark.django_db
def test_a_cashier_cannot_submit_a_claim(
    as_cashier, as_billing_officer, claim_ready, scheme, facility_a
):
    """(negative). Submitting a claim commits the hospital to a figure."""
    claim = as_billing_officer.post(
        reverse("claimbatch-assemble"), assemble_payload(scheme, facility_a),
        format="json",
    ).data
    response = as_cashier.post(
        reverse("claimbatch-submit", args=[claim["id"]]), {}, format="json"
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_a_claim_at_another_facility_is_not_found(
    as_billing_officer, facility_b, scheme, organization
):
    """404, not 403 — "no such claim" and "a claim you may not see" have to be
    indistinguishable across facilities."""
    from accounts.models import User

    claim = ClaimBatch.objects.create(
        provider=scheme["provider"], facility=facility_b,
        period_start=date.today(), period_end=date.today(),
        created_by=User.objects.get(email="insurance@example.test"),
    )
    response = as_billing_officer.get(reverse("claimbatch-detail", args=[claim.pk]))
    assert response.status_code == 404

    listed = as_billing_officer.get(reverse("claimbatch-list"))
    assert claim.pk not in [row["id"] for row in listed.data["results"]]


@pytest.mark.django_db
def test_the_ageing_report_refuses_another_facility(
    as_billing_officer, facility_b
):
    """AC-139. A report is the classic way facility isolation leaks."""
    response = as_billing_officer.get(
        reverse("insuranceprovider-ageing"), {"facility": facility_b.pk}
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_a_nurse_cannot_read_what_a_scheme_pays(as_nurse, split_visit):
    """A nurse has no business in the hospital's contracts with its insurers."""
    response = as_nurse.get(
        reverse("chargecoverage-invoice-split"), {"invoice": split_visit.pk}
    )
    assert response.status_code == 403
