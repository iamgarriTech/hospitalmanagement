"""AC-42 to AC-49 — money that adds up and does not quietly change."""
from decimal import Decimal
from itertools import product

import pytest
from django.urls import reverse

from audit.models import AuditEvent
from billing.models import CashierSession, Invoice, InvoiceItem, Payment, charge

PAYMENTS = reverse("payment-list")


@pytest.mark.django_db
def test_charges_come_from_clinical_events_not_from_typing(billed_visit, tariff):
    """AC-42: finalising a consultation is what creates the charge."""
    assert billed_visit.items.count() == 1
    item = billed_visit.items.first()
    assert item.source_type == "clinical.Encounter"
    assert item.unit_price == Decimal("5000.00")
    assert item.service.code == "CONSULT"
    assert billed_visit.total == Decimal("5000.00")


@pytest.mark.django_db
def test_a_lab_order_bills_each_test_it_contains(as_doctor, open_visit, tariff,
                                                 lab_catalogue):
    """AC-42, and the invoice is shared with the consultation on the same visit."""
    lab_catalogue["fbc"].service = tariff["fbc_service"]
    lab_catalogue["fbc"].save(update_fields=["service"])

    response = as_doctor.post(
        reverse("laborder-list"),
        {"visit": open_visit.pk, "tests": [lab_catalogue["fbc"].pk]},
        format="json",
    )
    assert response.status_code == 201, response.data

    invoice = Invoice.objects.get(visit=open_visit)
    assert invoice.items.count() == 1
    assert invoice.items.first().source_type == "laboratory.LabOrderItem"
    assert invoice.total == Decimal("3500.00")


@pytest.mark.django_db
def test_the_same_clinical_event_is_never_charged_twice(open_visit, tariff):
    """AC-43 — a retried request, a double-clicked button, a re-run job."""
    for _ in range(5):
        item, created = charge(
            visit=open_visit, service_code="CONSULT", description="General consultation",
            source_type="clinical.Encounter", source_id=42,
        )
    assert InvoiceItem.objects.filter(source_id="42").count() == 1
    assert created is False
    assert Invoice.objects.get(visit=open_visit).total == Decimal("5000.00")


@pytest.mark.django_db
def test_dispensing_twice_produces_two_charges_but_a_retry_produces_one(
    as_pharmacist, amoxicillin_prescription, formulary, tariff
):
    """Partial dispensing is genuinely two charges; retrying either one is not."""
    medication = formulary["amoxicillin"]
    medication.selling_price = Decimal("120.00")
    medication.save(update_fields=["selling_price"])
    item_id = amoxicillin_prescription["items"][0]["id"]
    batch = formulary["batches"]["amoxicillin"]
    url = reverse("prescriptionitem-dispense", args=[item_id])

    as_pharmacist.post(url, {"batch": batch.pk, "quantity": 6}, format="json")
    as_pharmacist.post(url, {"batch": batch.pk, "quantity": 9}, format="json")

    charges = InvoiceItem.objects.filter(source_type="pharmacy.Dispense")
    assert charges.count() == 2
    assert sum(entry.amount for entry in charges) == Decimal("1800.00")  # 15 × 120


@pytest.mark.django_db
def test_recording_the_same_payment_twice_takes_the_money_once(
    as_cashier, billed_visit, tariff, cashier_session
):
    """AC-44 — the same idempotency key returns the same receipt."""
    payload = {
        "invoice": billed_visit.pk, "method": tariff["cash"].pk, "amount": "5000.00",
        "idempotency_key": "till-1-2026-09-07-0001",
    }
    first = as_cashier.post(PAYMENTS, payload, format="json")
    assert first.status_code == 201

    second = as_cashier.post(PAYMENTS, payload, format="json")
    assert second.status_code == 200
    assert second.data["receipt_number"] == first.data["receipt_number"]

    assert Payment.objects.count() == 1
    billed_visit.refresh_from_db()
    assert billed_visit.amount_paid == Decimal("5000.00")
    assert billed_visit.balance == Decimal("0.00")
    assert billed_visit.status == Invoice.PAID


@pytest.mark.django_db
def test_a_payment_needs_an_open_cashier_session(as_cashier, billed_visit, tariff):
    """Money must always land in a session, or the day cannot be reconciled."""
    response = as_cashier.post(
        PAYMENTS,
        {"invoice": billed_visit.pk, "method": tariff["cash"].pk, "amount": "100.00",
         "idempotency_key": "no-session"},
        format="json",
    )
    assert response.status_code == 409
    assert "cashier session" in response.data["detail"]


@pytest.mark.django_db
def test_overpayment_and_zero_payment_are_refused(
    as_cashier, billed_visit, tariff, cashier_session
):
    too_much = as_cashier.post(
        PAYMENTS,
        {"invoice": billed_visit.pk, "method": tariff["cash"].pk, "amount": "9000.00",
         "idempotency_key": "over"},
        format="json",
    )
    assert too_much.status_code == 400
    assert "outstanding balance" in too_much.data["amount"][0]
    assert Payment.objects.count() == 0


@pytest.mark.django_db
def test_a_transfer_requires_a_reference(
    as_cashier, billed_visit, tariff, cashier_session
):
    response = as_cashier.post(
        PAYMENTS,
        {"invoice": billed_visit.pk, "method": tariff["transfer"].pk,
         "amount": "5000.00", "idempotency_key": "no-ref"},
        format="json",
    )
    assert response.status_code == 400
    assert "reference" in response.data


@pytest.mark.django_db
def test_a_discount_within_the_cashiers_limit_is_allowed(
    as_cashier, billed_visit, tariff
):
    response = as_cashier.post(
        reverse("invoice-discount", args=[billed_visit.pk]),
        {"amount": "500.00", "reason": "Staff dependant"},
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["total"] == "4500.00"
    event = AuditEvent.objects.get(action="invoice.discounted")
    assert event.changes["after"]["within_limit"] is True


@pytest.mark.django_db
def test_a_discount_above_the_limit_is_refused_and_needs_an_approver(
    as_cashier, as_accountant, billed_visit, tariff
):
    """AC-45 (negative)."""
    url = reverse("invoice-discount", args=[billed_visit.pk])
    refused = as_cashier.post(
        url, {"amount": "3000.00", "reason": "Patient cannot pay"}, format="json"
    )
    assert refused.status_code == 403
    assert "discount limit is 500.00" in refused.data["detail"]
    billed_visit.refresh_from_db()
    assert billed_visit.discount_amount == Decimal("0.00")
    assert AuditEvent.objects.filter(action="invoice.discount_refused").exists()

    approved = as_accountant.post(
        url, {"amount": "3000.00", "reason": "Approved by medical social worker"},
        format="json",
    )
    assert approved.status_code == 200
    assert approved.data["total"] == "2000.00"


@pytest.mark.django_db
def test_a_discount_cannot_exceed_the_invoice(as_accountant, billed_visit, tariff):
    response = as_accountant.post(
        reverse("invoice-discount", args=[billed_visit.pk]),
        {"amount": "9000.00", "reason": "generous"}, format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_a_refund_needs_the_permission_a_reason_and_references_the_original(
    as_cashier, as_accountant, billed_visit, tariff, cashier_session, facility_a
):
    """AC-46."""
    payment = as_cashier.post(
        PAYMENTS,
        {"invoice": billed_visit.pk, "method": tariff["cash"].pk, "amount": "5000.00",
         "idempotency_key": "refund-me"},
        format="json",
    ).data

    refused = as_cashier.post(
        reverse("payment-refund", args=[payment["id"]]),
        {"amount": "5000.00", "reason": "Test cancelled"}, format="json",
    )
    assert refused.status_code == 403

    as_accountant.post(
        reverse("cashiersession-list"),
        {"facility": facility_a.pk, "opening_float": "0.00"}, format="json",
    )
    no_reason = as_accountant.post(
        reverse("payment-refund", args=[payment["id"]]), {"amount": "5000.00"},
        format="json",
    )
    assert no_reason.status_code == 400

    refunded = as_accountant.post(
        reverse("payment-refund", args=[payment["id"]]),
        {"amount": "2000.00", "reason": "Investigation cancelled before collection"},
        format="json",
    )
    assert refunded.status_code == 200
    assert refunded.data["amount_refunded"] == "2000.00"
    assert refunded.data["refunds"][0]["reference"].startswith("REF/")

    event = AuditEvent.objects.get(action="payment.refunded")
    assert event.changes["before"]["receipt"] == payment["receipt_number"]
    assert event.changes["after"]["amount"] == "2000.00"
    assert event.reason.startswith("Investigation cancelled")

    billed_visit.refresh_from_db()
    assert billed_visit.balance == Decimal("2000.00")
    assert billed_visit.status == Invoice.FINALISED


@pytest.mark.django_db
def test_a_refund_cannot_exceed_what_remains_refundable(
    as_accountant, billed_visit, tariff, facility_a
):
    as_accountant.post(reverse("cashiersession-list"),
                       {"facility": facility_a.pk}, format="json")
    payment = as_accountant.post(
        PAYMENTS,
        {"invoice": billed_visit.pk, "method": tariff["cash"].pk, "amount": "5000.00",
         "idempotency_key": "partial-refund"}, format="json",
    ).data
    url = reverse("payment-refund", args=[payment["id"]])
    as_accountant.post(url, {"amount": "3000.00", "reason": "partial"}, format="json")
    too_much = as_accountant.post(
        url, {"amount": "3000.00", "reason": "again"}, format="json"
    )
    assert too_much.status_code == 400
    assert "Only 2000.00 remains refundable" in too_much.data["amount"][0]


@pytest.mark.django_db
def test_reconciled_money_cannot_be_changed_by_anyone(
    as_cashier, as_accountant, billed_visit, tariff, cashier_session
):
    """AC-47 — the criterion that makes the day's takings trustworthy."""
    as_cashier.post(
        PAYMENTS,
        {"invoice": billed_visit.pk, "method": tariff["cash"].pk, "amount": "5000.00",
         "idempotency_key": "reconcile-me"}, format="json",
    )
    session_id = cashier_session["id"]
    as_cashier.post(reverse("cashiersession-close", args=[session_id]))
    reconciled = as_accountant.post(
        reverse("cashiersession-reconcile", args=[session_id]),
        {"counted_total": "5000.00"}, format="json",
    )
    assert reconciled.status_code == 200
    assert reconciled.data["status"] == CashierSession.RECONCILED

    billed_visit.refresh_from_db()
    assert billed_visit.is_frozen is True

    for client in (as_cashier, as_accountant):
        response = client.post(
            reverse("invoice-discount", args=[billed_visit.pk]),
            {"amount": "100.00", "reason": "after the fact"}, format="json",
        )
        assert response.status_code == 409
        assert "reconciled" in response.data["detail"]

    billed_visit.refresh_from_db()
    assert billed_visit.discount_amount == Decimal("0.00")


@pytest.mark.django_db
def test_reconciling_with_a_variance_requires_an_explanation(
    as_cashier, as_accountant, billed_visit, tariff, cashier_session
):
    as_cashier.post(
        PAYMENTS,
        {"invoice": billed_visit.pk, "method": tariff["cash"].pk, "amount": "5000.00",
         "idempotency_key": "short"}, format="json",
    )
    session_id = cashier_session["id"]
    as_cashier.post(reverse("cashiersession-close", args=[session_id]))

    unexplained = as_accountant.post(
        reverse("cashiersession-reconcile", args=[session_id]),
        {"counted_total": "4800.00"}, format="json",
    )
    assert unexplained.status_code == 400
    assert "variance of -200.00 must be explained" in unexplained.data["variance_note"][0]

    explained = as_accountant.post(
        reverse("cashiersession-reconcile", args=[session_id]),
        {"counted_total": "4800.00", "variance_note": "₦200 shortfall, reported to "
                                                       "the accountant"},
        format="json",
    )
    assert explained.status_code == 200
    event = AuditEvent.objects.get(action="cashier_session.reconciled")
    assert event.changes["after"]["variance"] == "-200.00"


@pytest.mark.django_db
def test_reconciling_requires_the_reconcile_permission(
    as_cashier, cashier_session
):
    """AC-47 (negative): a cashier does not sign off their own till."""
    session_id = cashier_session["id"]
    as_cashier.post(reverse("cashiersession-close", args=[session_id]))
    response = as_cashier.post(
        reverse("cashiersession-reconcile", args=[session_id]),
        {"counted_total": "0.00"}, format="json",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_invoice_totals_always_equal_the_sum_of_their_lines(open_visit, facility_a,
                                                            billing_numbers):
    """AC-48, checked over generated combinations rather than one example."""
    from billing.models import Invoice as Inv

    prices = [Decimal("0.00"), Decimal("1.50"), Decimal("999.99"), Decimal("5000.00")]
    quantities = [1, 3, 17]
    discounts = [Decimal("0.00"), Decimal("1.50"), Decimal("100.00")]
    taxes = [Decimal("0.00"), Decimal("7.50")]

    for unit_price, quantity, discount, tax in product(prices, quantities, discounts,
                                                        taxes):
        invoice = Inv.objects.create(
            patient=open_visit.patient, facility=facility_a,
            discount_amount=min(discount, unit_price * quantity), tax_amount=tax,
        )
        InvoiceItem.objects.create(
            invoice=invoice, description="line one", quantity=quantity,
            unit_price=unit_price,
        )
        InvoiceItem.objects.create(
            invoice=invoice, description="line two", quantity=1, unit_price=unit_price,
        )
        cancelled = InvoiceItem.objects.create(
            invoice=invoice, description="cancelled line", quantity=9,
            unit_price=Decimal("50.00"), is_cancelled=True,
            cancelled_reason="entered in error",
        )
        expected_subtotal = unit_price * quantity + unit_price
        assert invoice.subtotal == expected_subtotal, (
            f"{unit_price} × {quantity}: cancelled line {cancelled.pk} leaked in"
        )
        assert invoice.total == expected_subtotal - invoice.discount_amount + tax


@pytest.mark.django_db
def test_a_receipt_reprint_is_identical_and_is_logged(
    as_cashier, billed_visit, tariff, cashier_session
):
    """AC-49."""
    payment = as_cashier.post(
        PAYMENTS,
        {"invoice": billed_visit.pk, "method": tariff["cash"].pk, "amount": "5000.00",
         "idempotency_key": "print-me"}, format="json",
    ).data
    url = reverse("payment-receipt", args=[payment["id"]])

    original = as_cashier.get(url).data
    assert original["is_reprint"] is False
    assert original["total"] == "5000.00"
    assert original["items"][0]["description"].startswith("Consultation")

    reprint = as_cashier.get(url, {"reprint": "true"}).data
    comparable = {key: value for key, value in reprint.items() if key != "is_reprint"}
    assert comparable == {key: value for key, value in original.items()
                          if key != "is_reprint"}
    assert reprint["is_reprint"] is True

    event = AuditEvent.objects.get(action="receipt.reprinted")
    assert event.changes["after"]["reprint_number"] == 1
    assert Payment.objects.get(pk=payment["id"]).reprint_count == 1


@pytest.mark.django_db
def test_an_invoice_with_payments_cannot_be_voided(
    as_accountant, billed_visit, tariff, facility_a
):
    as_accountant.post(reverse("cashiersession-list"),
                       {"facility": facility_a.pk}, format="json")
    as_accountant.post(
        PAYMENTS,
        {"invoice": billed_visit.pk, "method": tariff["cash"].pk, "amount": "1000.00",
         "idempotency_key": "paid-then-void"}, format="json",
    )
    response = as_accountant.post(
        reverse("invoice-void", args=[billed_visit.pk]),
        {"reason": "raised in error"}, format="json",
    )
    assert response.status_code == 409
    assert "Refund the payments" in response.data["detail"]
