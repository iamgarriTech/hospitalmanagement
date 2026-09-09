"""The till at depth: counting per method, correcting, handing over.

AC-140 to AC-142. The theme is that a cashier's drawer is the one place in a
hospital where money exists as an object somebody can miscount, and a system
that accepts a single number for it cannot tell an honest slip from a theft.
"""

from decimal import Decimal

import pytest
from django.urls import reverse

from audit.models import AuditEvent
from billing.models import CashierSession, SessionAdjustment, TillHandover

PAYMENTS = reverse("payment-list")


def _client_for_user(user):
    """A fresh authenticated client. The concurrency test needs one per thread."""
    from conftest import _client_for

    return _client_for(user)


def _wait_for_a_blocked_backend(future, timeout=5.0):
    """True once some connection is waiting on a row lock.

    Asked of Postgres rather than inferred from timing: a test that concludes
    "it must have blocked" because it did not finish quickly enough proves
    nothing on a loaded machine.
    """
    import time

    from django.db import connection

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if future.done():
            return False
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE wait_event_type = 'Lock' AND datname = current_database()"
            )
            if cursor.fetchone()[0] > 0:
                return True
        time.sleep(0.05)
    return False


def _pay(client, invoice, method, amount, key, reference=""):
    response = client.post(
        PAYMENTS,
        {"invoice": invoice.pk, "method": method.pk, "amount": amount,
         "idempotency_key": key, "reference": reference},
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data


def _close(client, session_id):
    return client.post(reverse("cashiersession-close", args=[session_id]))


def _reconcile(client, session_id, counts, note=""):
    return client.post(
        reverse("cashiersession-reconcile", args=[session_id]),
        {"counts": counts, "variance_note": note}, format="json",
    )


# --- AC-140: a count per payment method -------------------------------------

@pytest.mark.django_db
def test_offsetting_errors_do_not_cancel_out(
    as_cashier, as_accountant, billed_visit, tariff, cashier_session
):
    """AC-140. The whole reason a lump-sum count is not good enough.

    ₦500 short on cash and ₦500 over on transfers nets to zero. Under a single
    counted figure this session reconciles clean and two real mistakes — money
    missing from a drawer, and money in the wrong one — never surface.
    """
    _pay(as_cashier, billed_visit, tariff["cash"], "3000.00", "cash-part")
    _pay(as_cashier, billed_visit, tariff["transfer"], "2000.00", "xfer-part",
         reference="TRF-99001")
    session_id = cashier_session["id"]
    _close(as_cashier, session_id)

    refused = _reconcile(as_cashier and as_accountant, session_id, [
        {"method": tariff["cash"].pk, "counted": "2500.00"},
        {"method": tariff["transfer"].pk, "counted": "2500.00"},
    ])
    assert refused.status_code == 400
    problems = " | ".join(refused.data["unexplained"])
    assert "Cash is 500.00 short" in problems
    assert "Bank transfer is 500.00 over" in problems

    session = CashierSession.objects.get(pk=session_id)
    assert session.status == CashierSession.CLOSED
    # And the net figure that would have hidden it:
    assert session.net_variance == Decimal("0.00")


@pytest.mark.django_db
def test_each_method_is_explained_on_its_own_row(
    as_cashier, as_accountant, billed_visit, tariff, cashier_session
):
    """One note for the drawer does not say which drawer was wrong."""
    _pay(as_cashier, billed_visit, tariff["cash"], "3000.00", "c1")
    _pay(as_cashier, billed_visit, tariff["transfer"], "2000.00", "t1",
         reference="TRF-99002")
    session_id = cashier_session["id"]
    _close(as_cashier, session_id)

    # A session-level note is not an explanation of a per-method variance.
    vague = _reconcile(as_accountant, session_id, [
        {"method": tariff["cash"].pk, "counted": "2900.00"},
        {"method": tariff["transfer"].pk, "counted": "2000.00"},
    ], note="something is off somewhere")
    assert vague.status_code == 400
    assert "Cash is 100.00 short" in vague.data["unexplained"][0]

    named = _reconcile(as_accountant, session_id, [
        {"method": tariff["cash"].pk, "counted": "2900.00",
         "note": "₦100 change given twice at 14:20, patient gone"},
        {"method": tariff["transfer"].pk, "counted": "2000.00"},
    ])
    assert named.status_code == 200
    rows = {row["method_name"]: row for row in named.data["variance_by_method"]}
    assert rows["Cash"]["variance"] == "-100.00"
    assert "change given twice" in rows["Cash"]["note"]
    assert rows["Bank transfer"]["variance"] == "0.00"
    assert named.data["counted_total"] == "4900.00"


@pytest.mark.django_db
def test_a_method_that_took_money_and_was_never_counted_is_refused(
    as_cashier, as_accountant, billed_visit, tariff, cashier_session
):
    """Uncounted is not zero. AC-140.

    The likeliest real mistake is a cashier counting the cash box, forgetting
    the transfers went through the same session, and closing. Treating the
    missing row as a zero count would report the entire transfer total as a
    shortage; treating it as reconciled would report nothing at all.
    """
    _pay(as_cashier, billed_visit, tariff["cash"], "3000.00", "c2")
    _pay(as_cashier, billed_visit, tariff["transfer"], "2000.00", "t2",
         reference="TRF-99003")
    session_id = cashier_session["id"]
    _close(as_cashier, session_id)

    refused = _reconcile(as_accountant, session_id, [
        {"method": tariff["cash"].pk, "counted": "3000.00"},
    ])
    assert refused.status_code == 400
    assert "Bank transfer took 2000.00 and has not been counted." in (
        refused.data["unexplained"]
    )


@pytest.mark.django_db
def test_money_counted_under_a_method_that_took_nothing_is_shown(
    as_cashier, as_accountant, billed_visit, tariff, cashier_session
):
    """A count with no matching payments is a real event, not a rounding error."""
    _pay(as_cashier, billed_visit, tariff["cash"], "5000.00", "c3")
    session_id = cashier_session["id"]
    _close(as_cashier, session_id)

    surprise = _reconcile(as_accountant, session_id, [
        {"method": tariff["cash"].pk, "counted": "5000.00"},
        {"method": tariff["transfer"].pk, "counted": "1500.00"},
    ])
    assert surprise.status_code == 400
    assert "Bank transfer is 1500.00 over" in surprise.data["unexplained"][0]


@pytest.mark.django_db
def test_recounting_replaces_the_earlier_count(
    as_cashier, as_accountant, billed_visit, tariff, cashier_session
):
    """A refused close is a recount, not a second count."""
    _pay(as_cashier, billed_visit, tariff["cash"], "5000.00", "c4")
    session_id = cashier_session["id"]
    _close(as_cashier, session_id)

    _reconcile(as_accountant, session_id, [
        {"method": tariff["cash"].pk, "counted": "4000.00"},
    ])
    good = _reconcile(as_accountant, session_id, [
        {"method": tariff["cash"].pk, "counted": "5000.00"},
    ])
    assert good.status_code == 200

    session = CashierSession.objects.get(pk=session_id)
    assert session.counts.count() == 1
    assert session.counts.get().counted == Decimal("5000.00")
    assert session.counted_total == Decimal("5000.00")


@pytest.mark.django_db
def test_the_audit_row_keeps_the_per_method_figures(
    as_cashier, as_accountant, billed_visit, tariff, cashier_session
):
    """Guarantee 2. A net variance in the log hides what produced it."""
    _pay(as_cashier, billed_visit, tariff["cash"], "3000.00", "c5")
    _pay(as_cashier, billed_visit, tariff["transfer"], "2000.00", "t5",
         reference="TRF-99004")
    session_id = cashier_session["id"]
    _close(as_cashier, session_id)
    assert _reconcile(as_accountant, session_id, [
        {"method": tariff["cash"].pk, "counted": "2500.00", "note": "short, reported"},
        {"method": tariff["transfer"].pk, "counted": "2500.00",
         "note": "a transfer posted to the wrong session"},
    ]).status_code == 200

    event = AuditEvent.objects.get(action="cashier_session.reconciled")
    by_method = event.changes["after"]["by_method"]
    assert by_method["Cash"] == {
        "expected": "3000.00", "counted": "2500.00", "variance": "-500.00",
        "note": "short, reported",
    }
    assert by_method["Bank transfer"]["variance"] == "500.00"
    assert event.changes["after"]["net_variance"] == "0.00"


@pytest.mark.django_db
def test_one_method_cannot_be_counted_twice(
    as_cashier, as_accountant, billed_visit, tariff, cashier_session
):
    _pay(as_cashier, billed_visit, tariff["cash"], "5000.00", "c6")
    session_id = cashier_session["id"]
    _close(as_cashier, session_id)
    response = _reconcile(as_accountant, session_id, [
        {"method": tariff["cash"].pk, "counted": "3000.00"},
        {"method": tariff["cash"].pk, "counted": "2000.00"},
    ])
    assert response.status_code == 400
    assert "counted twice" in str(response.data)


@pytest.mark.django_db
def test_a_cashier_cannot_reconcile_their_own_till(
    as_cashier, billed_visit, tariff, cashier_session
):
    """The count is the cashier's; signing it off is not."""
    _pay(as_cashier, billed_visit, tariff["cash"], "5000.00", "c7")
    session_id = cashier_session["id"]
    _close(as_cashier, session_id)
    response = _reconcile(as_cashier, session_id, [
        {"method": tariff["cash"].pk, "counted": "5000.00"},
    ])
    assert response.status_code == 403


# --- AC-141: corrections are new entries ------------------------------------

@pytest.mark.django_db
def test_a_reconciled_session_is_corrected_by_adjustment_not_by_editing(
    as_cashier, as_accountant, billed_visit, tariff, cashier_session
):
    """AC-141 and guarantee 6."""
    _pay(as_cashier, billed_visit, tariff["cash"], "5000.00", "c8")
    session_id = cashier_session["id"]
    _close(as_cashier, session_id)
    assert _reconcile(as_accountant, session_id, [
        {"method": tariff["cash"].pk, "counted": "5000.00"},
    ]).status_code == 200

    # Recounting a reconciled session is refused outright, and the refusal
    # points at the correction rather than at a button that does not exist.
    again = _reconcile(as_accountant, session_id, [
        {"method": tariff["cash"].pk, "counted": "4700.00"},
    ])
    assert again.status_code == 409
    assert "already signed off" in again.data["detail"]
    assert "correction" in again.data["detail"]

    correction = as_accountant.post(
        reverse("cashiersession-adjust", args=[session_id]),
        {"kind": SessionAdjustment.SHORTAGE, "method": tariff["cash"].pk,
         "amount": "-300.00",
         "reason": "₦300 found missing at the second count next morning"},
        format="json",
    )
    assert correction.status_code == 201, correction.data

    session = CashierSession.objects.get(pk=session_id)
    # The reconciled figures are exactly as they were signed off.
    assert session.counted_total == Decimal("5000.00")
    assert session.counts.get().counted == Decimal("5000.00")
    assert session.adjustments.count() == 1
    assert session.adjustments.get().amount == Decimal("-300.00")

    event = AuditEvent.objects.get(action="cashier_session.adjusted")
    assert "found missing" in event.reason


@pytest.mark.django_db
def test_an_adjustment_must_carry_a_reason_and_a_non_zero_amount(
    as_cashier, as_accountant, billed_visit, tariff, cashier_session
):
    _pay(as_cashier, billed_visit, tariff["cash"], "5000.00", "c9")
    session_id = cashier_session["id"]
    _close(as_cashier, session_id)
    _reconcile(as_accountant, session_id,
               [{"method": tariff["cash"].pk, "counted": "5000.00"}])
    url = reverse("cashiersession-adjust", args=[session_id])

    no_reason = as_accountant.post(
        url, {"kind": SessionAdjustment.OVERAGE, "amount": "100.00", "reason": ""},
        format="json",
    )
    assert no_reason.status_code == 400

    nothing_to_correct = as_accountant.post(
        url, {"kind": SessionAdjustment.OVERAGE, "amount": "0.00",
              "reason": "no idea"}, format="json",
    )
    assert nothing_to_correct.status_code == 400


@pytest.mark.django_db
def test_a_cashier_cannot_adjust_the_session_they_counted(
    as_cashier, as_accountant, billed_visit, tariff, cashier_session
):
    """The person who counted it wrong does not get to restate it."""
    _pay(as_cashier, billed_visit, tariff["cash"], "5000.00", "c10")
    session_id = cashier_session["id"]
    _close(as_cashier, session_id)
    _reconcile(as_accountant, session_id,
               [{"method": tariff["cash"].pk, "counted": "5000.00"}])

    response = as_cashier.post(
        reverse("cashiersession-adjust", args=[session_id]),
        {"kind": SessionAdjustment.SHORTAGE, "amount": "-300.00",
         "reason": "let me just fix that"}, format="json",
    )
    assert response.status_code == 403
    assert not SessionAdjustment.objects.exists()


@pytest.mark.django_db
def test_an_open_session_is_reconciled_rather_than_adjusted(
    as_accountant, cashier_session
):
    """An adjustment against unreconciled money would be an untracked edit."""
    response = as_accountant.post(
        reverse("cashiersession-adjust", args=[cashier_session["id"]]),
        {"kind": SessionAdjustment.SHORTAGE, "amount": "-100.00",
         "reason": "premature"}, format="json",
    )
    assert response.status_code == 409
    assert "reconciled session" in response.data["detail"]


# --- AC-142: the shift handover ---------------------------------------------

@pytest.mark.django_db
def test_the_incoming_cashier_takes_the_till_with_both_names_recorded(
    as_cashier, as_relief_cashier, cashier, relief_cashier, billed_visit, tariff,
    cashier_session, facility_a
):
    """AC-142. Two signatures, one continuous float, no gap."""
    _pay(as_cashier, billed_visit, tariff["cash"], "5000.00", "c11")
    session_id = cashier_session["id"]

    handover = as_relief_cashier.post(
        reverse("cashiersession-handover", args=[session_id]),
        {"counts": [{"method": tariff["cash"].pk, "counted": "5000.00"}],
         "float_handed": "7000.00", "note": "afternoon shift"},
        format="json",
    )
    assert handover.status_code == 201, handover.data

    record = TillHandover.objects.get()
    assert record.handed_by == cashier
    assert record.received_by == relief_cashier
    assert record.float_handed == Decimal("7000.00")

    outgoing = CashierSession.objects.get(pk=session_id)
    assert outgoing.status == CashierSession.CLOSED
    assert outgoing.counted_total == Decimal("5000.00")

    incoming = record.to_session
    assert incoming.cashier == relief_cashier
    assert incoming.facility == facility_a
    assert incoming.status == CashierSession.OPEN
    # ₦2,000 opening float plus the ₦5,000 taken: the drawer's contents move
    # across whole, which is what makes the next count meaningful.
    assert incoming.opening_float == Decimal("7000.00")

    event = AuditEvent.objects.get(action="cashier_session.handed_over")
    assert event.changes["after"]["handed_by"] == cashier.email
    assert event.changes["after"]["received_by"] == relief_cashier.email


@pytest.mark.django_db
def test_a_cashier_cannot_hand_a_till_to_themselves(
    as_cashier, billed_visit, tariff, cashier_session
):
    """A signature one person supplies for two people is one signature."""
    response = as_cashier.post(
        reverse("cashiersession-handover", args=[cashier_session["id"]]),
        {"counts": [], "float_handed": "2000.00"}, format="json",
    )
    assert response.status_code == 400
    assert "handed to somebody else" in response.data["detail"]
    assert not TillHandover.objects.exists()


@pytest.mark.django_db
def test_a_handover_refuses_an_unexplained_variance_too(
    as_cashier, as_relief_cashier, billed_visit, tariff, cashier_session
):
    """Money does not become somebody else's problem by changing hands."""
    _pay(as_cashier, billed_visit, tariff["cash"], "5000.00", "c12")
    response = as_relief_cashier.post(
        reverse("cashiersession-handover", args=[cashier_session["id"]]),
        {"counts": [{"method": tariff["cash"].pk, "counted": "4000.00"}],
         "float_handed": "6000.00"}, format="json",
    )
    assert response.status_code == 400
    assert "Cash is 1000.00 short" in response.data["unexplained"][0]
    assert not TillHandover.objects.exists()
    assert CashierSession.objects.get(
        pk=cashier_session["id"]
    ).status == CashierSession.OPEN


@pytest.mark.django_db
def test_more_cannot_be_handed_over_than_was_counted(
    as_cashier, as_relief_cashier, billed_visit, tariff, cashier_session
):
    _pay(as_cashier, billed_visit, tariff["cash"], "5000.00", "c13")
    response = as_relief_cashier.post(
        reverse("cashiersession-handover", args=[cashier_session["id"]]),
        {"counts": [{"method": tariff["cash"].pk, "counted": "5000.00"}],
         "float_handed": "9000.00"}, format="json",
    )
    assert response.status_code == 400
    assert "Handing over 9000.00" in str(response.data)
    assert not TillHandover.objects.exists()


@pytest.mark.django_db
def test_a_cashier_with_an_open_till_cannot_receive_another(
    as_cashier, as_relief_cashier, relief_cashier, facility_a, tariff,
    cashier_session, billing_numbers
):
    """Two open sessions for one person means money in an ambiguous place."""
    own = as_relief_cashier.post(
        reverse("cashiersession-list"),
        {"facility": facility_a.pk, "opening_float": "1000.00"}, format="json",
    )
    assert own.status_code == 201

    response = as_relief_cashier.post(
        reverse("cashiersession-handover", args=[cashier_session["id"]]),
        {"counts": [], "float_handed": "2000.00"}, format="json",
    )
    assert response.status_code == 409
    assert "already have an open session" in response.data["detail"]


@pytest.mark.django_db
def test_a_closed_till_cannot_be_handed_over(
    as_cashier, as_relief_cashier, tariff, cashier_session
):
    session_id = cashier_session["id"]
    _close(as_cashier, session_id)
    response = as_relief_cashier.post(
        reverse("cashiersession-handover", args=[session_id]),
        {"counts": [], "float_handed": "2000.00"}, format="json",
    )
    assert response.status_code == 409
    assert "already closed" in response.data["detail"]


@pytest.mark.django_db
def test_a_relief_cashier_at_another_facility_sees_no_till_to_take(
    as_cashier, relief_cashier, facility_b, cashier_session, tariff
):
    """Facility isolation still applies to a handover. Guarantee 1.

    404 rather than 403, like every other out-of-scope record: "no such till"
    and "a till you may not touch" have to be indistinguishable.
    """
    from accounts.models import RoleAssignment

    assignment = RoleAssignment.objects.get(user=relief_cashier)
    assignment.facility = facility_b
    assignment.save(update_fields=["facility"])

    from conftest import _client_for  # noqa: PLC0415 — fixture helper

    response = _client_for(relief_cashier).post(
        reverse("cashiersession-handover", args=[cashier_session["id"]]),
        {"counts": [], "float_handed": "2000.00"}, format="json",
    )
    assert response.status_code == 404
    assert not TillHandover.objects.exists()


# --- guarantee 5: the race between taking money and counting it -------------

@pytest.mark.django_db(transaction=True)
def test_a_payment_cannot_land_in_a_session_being_closed(
    cashier, facility_a, tariff, billing_numbers, billed_visit
):
    """Guarantee 5, and the reason the payment path holds a row lock.

    Two threads racing on wall-clock time proved nothing here: closing a till
    is a cheaper request than taking a payment, so the close always committed
    first and the interleaving that matters never happened. So the close is
    made to hold its lock instead, which is the state a real close occupies for
    however long its transaction takes.

    The cashier taps Take payment while that close is mid-flight. What must not
    happen is ₦5,000 landing inside a session whose closing figure was written
    without it — money reconciled as absent and sitting in the drawer.
    """
    import threading

    from django.db import connections, transaction

    from billing.models import Invoice, Payment

    opened = _client_for_user(cashier).post(
        reverse("cashiersession-list"),
        {"facility": facility_a.pk, "opening_float": "2000.00"}, format="json",
    )
    assert opened.status_code == 201
    session_id = opened.data["id"]

    locked = threading.Event()
    released = threading.Event()

    def close_slowly():
        """Hold the session row the way a close in progress does."""
        try:
            with transaction.atomic():
                held = CashierSession.objects.select_for_update().get(pk=session_id)
                locked.set()
                # Long enough that the payment request definitely arrives
                # while the row is held.
                released.wait(timeout=5)
                held.status = CashierSession.CLOSED
                held.save(update_fields=["status"])
        finally:
            connections.close_all()

    closer = threading.Thread(target=close_slowly)
    closer.start()
    assert locked.wait(timeout=5), "the closing thread never took the lock"

    def take_payment():
        try:
            return _client_for_user(cashier).post(
                PAYMENTS,
                {"invoice": billed_visit.pk, "method": tariff["cash"].pk,
                 "amount": "5000.00", "idempotency_key": "race-1"},
                format="json",
            ).status_code
        finally:
            connections.close_all()

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as pool:
        payment = pool.submit(take_payment)

        # Proof the payment is waiting on the close rather than finishing
        # around it. Postgres reports the wait directly, so this asserts the
        # mechanism instead of hoping two threads interleave the right way —
        # they do not, since closing a till is the cheaper request and always
        # won the race outright.
        assert _wait_for_a_blocked_backend(payment), (
            "the payment did not wait for the close holding the session row; "
            "it either landed in a closing session or was refused by luck"
        )

        released.set()
        payment_status = payment.result(timeout=15)
    closer.join(timeout=5)

    session = CashierSession.objects.get(pk=session_id)
    assert session.status == CashierSession.CLOSED

    # Refused, because by the time the lock was released the till was shut. The
    # cashier sees a clear 409 and takes the money into the next session.
    assert payment_status == 409, payment_status
    assert session.payments.count() == 0
    assert not Payment.objects.filter(idempotency_key="race-1").exists()

    Invoice.objects.filter(pk=billed_visit.pk).update(status=Invoice.FINALISED)


@pytest.mark.django_db
def test_an_open_till_is_not_reported_as_failing_to_balance(
    as_cashier, billed_visit, tariff, cashier_session
):
    """A drawer still taking money has nothing to explain yet.

    Without this, every open till in the building reports its own takings as
    uncounted, and a warning that is always on is a warning nobody reads.
    """
    _pay(as_cashier, billed_visit, tariff["cash"], "5000.00", "open-till")
    listed = as_cashier.get(reverse("cashiersession-detail",
                                    args=[cashier_session["id"]]))
    assert listed.status_code == 200
    assert listed.data["status"] == "open"
    assert listed.data["unexplained"] == []

    # Once closed, the same uncounted method is exactly what blocks sign-off.
    _close(as_cashier, cashier_session["id"])
    closed = as_cashier.get(reverse("cashiersession-detail",
                                    args=[cashier_session["id"]]))
    assert closed.data["unexplained"] == [
        "Cash took 5000.00 and has not been counted."
    ]
