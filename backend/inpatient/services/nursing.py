"""Fluid balance and observation escalation.

Both are derivations rather than stored state: the balance is summed from the
entries on every read, and an escalation is raised by comparing an observation
against the ward's thresholds at the moment it is recorded.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from audit.models import AuditEvent

from ..models import Escalation, EscalationThreshold, FluidBalanceEntry

# What each threshold measurement is called on a VitalSigns row. The threshold
# choices and the observation fields are named the same on purpose, so this is a
# check that they have not drifted rather than a translation table.
MEASUREMENT_FIELDS = [measurement for measurement, _ in EscalationThreshold.MEASUREMENTS]


def fluid_balance(*, admission, since=None, until=None, hours=24):
    """Intake, output and the balance over a period.

    The period is a parameter because 24 hours is a convention, not a rule — a
    post-operative patient is watched hourly and a medical patient by the shift.
    """
    end = until or timezone.now()
    start = since or (end - timedelta(hours=hours))
    entries = FluidBalanceEntry.objects.filter(
        admission=admission, recorded_at__gte=start, recorded_at__lte=end
    )
    totals = entries.values("direction").annotate(total=Sum("volume_ml"))
    intake = next(
        (row["total"] for row in totals if row["direction"] == FluidBalanceEntry.INTAKE), 0
    )
    output = next(
        (row["total"] for row in totals if row["direction"] == FluidBalanceEntry.OUTPUT), 0
    )
    by_route = {
        row["route"]: row["total"]
        for row in entries.values("route").annotate(total=Sum("volume_ml"))
    }
    return {
        "from": start,
        "to": end,
        "hours": round((end - start).total_seconds() / 3600, 1),
        "intake_ml": intake,
        "output_ml": output,
        # Derived on every read. Never stored — see FluidBalanceEntry.
        "balance_ml": intake - output,
        "by_route": by_route,
        "entries": entries.count(),
    }


def record_observation_escalations(*, observations, admission, actor, ward=None):
    """Compare one set of observations against the ward's thresholds.

    Runs where the observation is recorded rather than on a schedule: a
    deterioration that is only noticed by a nightly job has been missed for a
    night. Returns the escalations raised, which the caller shows to the nurse
    immediately — an alert nobody sees is not an alert.
    """
    ward = ward or admission.current_ward
    if ward is None:
        return []

    thresholds = EscalationThreshold.objects.filter(ward=ward, is_active=True)
    raised = []
    for threshold in thresholds:
        value = getattr(observations, threshold.measurement, None)
        if value is None:
            continue
        direction = threshold.breached_by(Decimal(str(value)))
        if direction is None:
            continue
        bound = threshold.low if direction == Escalation.LOW else threshold.high
        escalation = Escalation.objects.create(
            admission=admission,
            patient=admission.patient,
            observations=observations,
            threshold=threshold,
            measurement=threshold.measurement,
            value=Decimal(str(value)),
            direction=direction,
            breached_bound=bound,
            # Copied, not read through the FK — the threshold is configuration
            # and may be edited tomorrow.
            instruction=threshold.instruction,
            raised_by=actor,
        )
        raised.append(escalation)
        AuditEvent.record(
            action="nursing.escalation_raised",
            actor=actor,
            resource=escalation,
            patient=admission.patient,
            facility=admission.facility,
            after={
                "measurement": threshold.measurement,
                "value": str(value),
                "direction": direction,
                "bound": str(bound),
                "ward": ward.code,
                "instruction": threshold.instruction,
            },
        )
    return raised


def outstanding_escalations(*, facility=None, ward=None, admission=None):
    """Everything raised and not yet acknowledged.

    AC-82's negative half: an escalation nobody has answered stays on a list
    until someone says what was done about it.
    """
    queryset = Escalation.objects.filter(acknowledged_at__isnull=True).select_related(
        "patient", "admission", "raised_by"
    )
    if admission is not None:
        return queryset.filter(admission=admission)
    if facility is not None:
        queryset = queryset.filter(admission__facility=facility)
    if ward is not None:
        queryset = queryset.filter(
            admission__occupancies__bed__room__ward=ward,
            admission__occupancies__period__endswith__isnull=True,
        )
    return queryset


def board_escalations(*, admission_ids, limit):
    """The most recent outstanding escalations per patient, plus the counts.

    Capped in SQL with a window function rather than in Python. Slicing after
    the fact still builds every row: a ward that had not been acknowledging its
    escalations made the board instantiate 948 model objects to display 160 of
    them, and that instantiation — not the query — was most of the request.

    Returns `(shown_by_admission, count_by_admission)`.
    """
    from django.db.models import Count, F, Window
    from django.db.models.functions import RowNumber

    from ..models import Escalation

    outstanding = Escalation.objects.filter(
        acknowledged_at__isnull=True, admission_id__in=admission_ids
    )
    counts = dict(
        outstanding.values_list("admission_id").annotate(total=Count("pk"))
    )

    ranked = outstanding.annotate(
        position=Window(
            expression=RowNumber(),
            partition_by=[F("admission_id")],
            order_by=F("raised_at").desc(),
        )
    ).values("pk", "position")
    keep = [row["pk"] for row in ranked if row["position"] <= limit]

    shown = {}
    for escalation in Escalation.objects.filter(pk__in=keep).order_by("-raised_at"):
        shown.setdefault(escalation.admission_id, []).append(escalation)
    return shown, counts
