"""Till operations: counting, reconciling, correcting, handing over.

Plain functions rather than a service class. They live here instead of on
`CashierSession` because each one spans several rows — counts, the session, and
in the handover case a second session — and a model method that creates other
objects reads worse than a function that says so in its name.
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import CashierSession, SessionCount, TillHandover


class UnexplainedVariance(Exception):
    """A close was refused because the count sheet does not add up. AC-140."""

    def __init__(self, problems):
        self.problems = problems
        super().__init__("; ".join(problems))


def record_counts(session, entries):
    """Write the cashier's count sheet, replacing any earlier attempt.

    Replacing rather than appending because a refused close is a recount, not a
    second count — and two rows for one method at one close would be a lie
    about what was in the drawer.
    """
    if session.is_frozen:
        raise UnexplainedVariance(
            ["That session is reconciled. Corrections are adjustments now."]
        )
    with transaction.atomic():
        session.counts.all().delete()
        SessionCount.objects.bulk_create([
            SessionCount(
                session=session,
                method=entry["method"],
                counted=entry["counted"],
                note=entry.get("note", ""),
            )
            for entry in entries
        ])
    # bulk_create leaves a stale prefetch behind, and every caller asks the
    # session for its variances immediately afterwards.
    session.refresh_from_db()
    if hasattr(session, "_prefetched_objects_cache"):
        session._prefetched_objects_cache.pop("counts", None)
    return session.counts.all()


def _counted_sum(session):
    return sum(
        (count.counted for count in session.counts.all()), Decimal("0")
    )


def reconcile_session(session, *, by, note=""):
    """Freeze the session. Nothing about its money changes after this.

    The caller records the counts and checks `unexplained_variances()` first;
    this refuses again anyway, because a function that freezes money should not
    depend on its caller having remembered to check.
    """
    if session.status != CashierSession.CLOSED:
        raise UnexplainedVariance(["Close the session before reconciling it."])
    problems = session.unexplained_variances()
    if problems:
        raise UnexplainedVariance(problems)

    session.status = CashierSession.RECONCILED
    session.reconciled_at = timezone.now()
    session.reconciled_by = by
    session.counted_total = _counted_sum(session)
    session.variance_note = note
    session.save(update_fields=["status", "reconciled_at", "reconciled_by",
                                "counted_total", "variance_note"])
    return session


def hand_over_till(session, *, to_user, float_handed, note=""):
    """Close one cashier's session and open the next on the same drawer.

    Both in one transaction, so the money is never counted in two open sessions
    and never in none. The outgoing session closes rather than reconciles: the
    day's reconciliation is a separate act by whoever holds that permission,
    and a handover mid-shift is not it.
    """
    counted = _counted_sum(session)
    if float_handed > counted + session.opening_float:
        raise UnexplainedVariance([
            f"Handing over {float_handed} when {counted + session.opening_float} "
            f"has been counted, float included."
        ])

    with transaction.atomic():
        session.status = CashierSession.CLOSED
        session.closed_at = timezone.now()
        session.counted_total = counted
        session.save(update_fields=["status", "closed_at", "counted_total"])

        incoming = CashierSession.objects.create(
            cashier=to_user,
            facility=session.facility,
            opening_float=float_handed,
        )
        return TillHandover.objects.create(
            from_session=session,
            to_session=incoming,
            float_handed=float_handed,
            handed_by=session.cashier,
            received_by=to_user,
            note=note,
        )
