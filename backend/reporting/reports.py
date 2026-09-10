"""The reports themselves.

Every one is a live query. AC-178 forbids serving a report from a stored
aggregate that could drift from the records it summarises — a dashboard that
disagrees with the ledger is worse than no dashboard, because somebody acts on
it. If one is ever introduced for measured performance reasons, it needs a
test asserting it agrees with the query below.

Each takes `facilities` and passes it through `scoped()`. That is AC-174, and
`check_reports_are_scoped()` refuses to start if a report forgets the
argument.
"""

from decimal import Decimal

from django.db.models import (
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    Q,
    Sum,
)
from django.db.models.functions import TruncDate
from django.utils import timezone

from .registry import Column, day_range, register, scoped


def _money(value):
    return Decimal(value or 0).quantize(Decimal("0.01"))


# --- clinical ---------------------------------------------------------------

@register(
    key="attendances_by_day", title="Attendances by day", group="Clinical",
    description="How many patients came through the door, and how many were new.",
    permission="visits.view_visit",
    columns=[
        Column("day", "Day"),
        Column("attendances", "Attendances", numeric=True),
        Column("completed", "Completed", numeric=True),
        Column("admitted", "Admitted", numeric=True),
    ],
)
def attendances_by_day(*, facilities, date_from, date_to):
    from visits.models import Visit

    start, end = day_range(date_from, date_to)
    rows = scoped(
        Visit.objects.filter(arrived_at__gte=start, arrived_at__lt=end), facilities
    ).annotate(day=TruncDate("arrived_at")).values("day").annotate(
        attendances=Count("id"),
        completed=Count("id", filter=Q(status="completed")),
        admitted=Count("id", filter=Q(status="admitted")),
    ).order_by("day")
    return [
        {"day": row["day"], "attendances": row["attendances"],
         "completed": row["completed"], "admitted": row["admitted"]}
        for row in rows
    ]


@register(
    key="diagnoses", title="Diagnoses recorded", group="Clinical",
    description="What the hospital is actually seeing, most common first.",
    permission="clinical.view_encounter",
    columns=[
        Column("description", "Diagnosis"),
        Column("code", "Code"),
        Column("count", "Times recorded", numeric=True),
    ],
)
def diagnoses(*, facilities, date_from, date_to):
    from clinical.models import Diagnosis

    start, end = day_range(date_from, date_to)
    # Through the version: a diagnosis belongs to a *revision* of a
    # consultation, which is what lets an amendment change it without
    # rewriting history. Only current versions count, or an amended
    # consultation would contribute its old diagnosis as well as its new one.
    rows = scoped(
        Diagnosis.objects.filter(
            version__is_current=True,
            version__encounter__created_at__gte=start,
            version__encounter__created_at__lt=end,
        ),
        facilities, field="version__encounter__facility_id",
    ).values("description", "code").annotate(count=Count("id")).order_by("-count")
    return [
        {"description": row["description"], "code": row["code"] or "—",
         "count": row["count"]}
        for row in rows
    ]


@register(
    key="clinician_workload", title="Consultations by clinician", group="Clinical",
    description="Who saw how many patients.",
    permission="clinical.view_encounter",
    columns=[
        Column("clinician", "Clinician"),
        Column("consultations", "Consultations", numeric=True),
    ],
)
def clinician_workload(*, facilities, date_from, date_to):
    from clinical.models import Encounter

    start, end = day_range(date_from, date_to)
    rows = scoped(
        Encounter.objects.filter(created_at__gte=start, created_at__lt=end),
        facilities,
    ).values("clinician__full_name").annotate(
        consultations=Count("id")
    ).order_by("-consultations")
    return [
        {"clinician": row["clinician__full_name"] or "—",
         "consultations": row["consultations"]}
        for row in rows
    ]


# --- financial --------------------------------------------------------------

@register(
    key="revenue_by_category", title="Revenue by service category",
    group="Financial",
    description="What was charged, by what kind of service. Charged, not collected.",
    permission="billing.view_invoice",
    columns=[
        Column("category", "Category"),
        Column("lines", "Lines", numeric=True),
        Column("charged", "Charged", numeric=True, money=True),
    ],
    notes="Charged, which is not the same as collected. See 'Payments taken'.",
)
def revenue_by_category(*, facilities, date_from, date_to):
    from billing.models import InvoiceItem

    start, end = day_range(date_from, date_to)
    rows = scoped(
        InvoiceItem.objects.filter(
            created_at__gte=start, created_at__lt=end
        ).exclude(invoice__status="void"),
        facilities, field="invoice__facility_id",
    ).values("service__category__name").annotate(
        lines=Count("id"),
        charged=Sum(
            ExpressionWrapper(
                F("unit_price") * F("quantity"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        ),
    ).order_by("-charged")
    return [
        {"category": row["service__category__name"] or "Uncategorised",
         "lines": row["lines"], "charged": _money(row["charged"])}
        for row in rows
    ]


@register(
    key="payments_by_method", title="Payments taken", group="Financial",
    description="What was actually collected, by how it was paid.",
    permission="billing.view_payment",
    columns=[
        Column("method", "Method"),
        Column("payments", "Payments", numeric=True),
        Column("collected", "Collected", numeric=True, money=True),
        Column("refunded", "Refunded", numeric=True, money=True),
    ],
)
def payments_by_method(*, facilities, date_from, date_to):
    from billing.models import Payment, Refund

    start, end = day_range(date_from, date_to)
    taken = scoped(
        Payment.objects.filter(received_at__gte=start, received_at__lt=end),
        facilities, field="invoice__facility_id",
    ).values("method__name").annotate(
        payments=Count("id"), collected=Sum("amount")
    ).order_by("-collected")

    refunds = dict(
        scoped(
            Refund.objects.filter(issued_at__gte=start, issued_at__lt=end),
            facilities, field="payment__invoice__facility_id",
        ).values_list("payment__method__name").annotate(total=Sum("amount"))
    )
    return [
        {"method": row["method__name"], "payments": row["payments"],
         "collected": _money(row["collected"]),
         "refunded": _money(refunds.get(row["method__name"], 0))}
        for row in taken
    ]


@register(
    key="outstanding_debt", title="Outstanding bills", group="Financial",
    description="What patients still owe, oldest first.",
    permission="billing.view_invoice",
    is_snapshot=True,
    columns=[
        Column("invoice", "Invoice"),
        Column("patient", "Patient"),
        Column("raised", "Raised"),
        Column("days", "Days old", numeric=True),
        Column("total", "Total", numeric=True, money=True),
        Column("balance", "Outstanding", numeric=True, money=True),
    ],
)
def outstanding_debt(*, facilities, date_from, date_to):
    from billing.models import Invoice

    today = timezone.localdate()
    # Finalised and not yet fully paid. A part-paid invoice stays FINALISED
    # until the balance reaches zero, so the balance is what decides, not the
    # status.
    invoices = scoped(
        Invoice.objects.filter(status=Invoice.FINALISED),
        facilities,
    ).select_related("patient").prefetch_related("items", "payments__refunds").order_by(
        "created_at"
    )
    rows = []
    for invoice in invoices:
        if invoice.balance <= 0:
            continue
        rows.append({
            "invoice": invoice.invoice_number,
            "patient": invoice.patient.full_name,
            "raised": invoice.created_at.date(),
            "days": (today - invoice.created_at.date()).days,
            "total": _money(invoice.total),
            "balance": _money(invoice.balance),
        })
    return rows


@register(
    key="claims_ageing", title="Insurance claims outstanding", group="Financial",
    description="What each scheme owes, and for how long.",
    permission="insurance.view_claimbatch",
    is_snapshot=True,
    columns=[
        Column("provider", "Provider"),
        Column("batches", "Batches", numeric=True),
        Column("submitted", "Submitted", numeric=True, money=True),
        Column("paid", "Paid", numeric=True, money=True),
        Column("outstanding", "Outstanding", numeric=True, money=True),
        Column("oldest_days", "Oldest, days", numeric=True),
    ],
)
def claims_ageing(*, facilities, date_from, date_to):
    from insurance.models import ClaimBatch

    today = timezone.localdate()
    batches = scoped(
        ClaimBatch.objects.exclude(status__in=["draft", "paid"]),
        facilities,
    ).select_related("provider").prefetch_related("lines")

    by_provider = {}
    for batch in batches:
        entry = by_provider.setdefault(
            batch.provider.name,
            {"provider": batch.provider.name, "batches": 0,
             "submitted": Decimal("0.00"), "paid": Decimal("0.00"),
             "oldest_days": 0},
        )
        entry["batches"] += 1
        entry["submitted"] += batch.claimed_total
        entry["paid"] += batch.paid_total
        if batch.submitted_at:
            age = (today - batch.submitted_at.date()).days
            entry["oldest_days"] = max(entry["oldest_days"], age)

    rows = []
    for entry in by_provider.values():
        entry["outstanding"] = _money(entry["submitted"] - entry["paid"])
        entry["submitted"] = _money(entry["submitted"])
        entry["paid"] = _money(entry["paid"])
        rows.append(entry)
    return sorted(rows, key=lambda row: row["outstanding"], reverse=True)


# --- laboratory -------------------------------------------------------------

@register(
    key="lab_volume", title="Tests performed", group="Laboratory",
    description="What the bench actually processed.",
    permission="laboratory.view_laborder",
    columns=[
        Column("test", "Test"),
        Column("ordered", "Ordered", numeric=True),
        Column("verified", "Verified", numeric=True),
    ],
)
def lab_volume(*, facilities, date_from, date_to):
    from laboratory.models import LabOrderItem

    start, end = day_range(date_from, date_to)
    rows = scoped(
        LabOrderItem.objects.filter(
            order__ordered_at__gte=start, order__ordered_at__lt=end
        ),
        facilities, field="order__facility_id",
    ).values("test__name").annotate(
        ordered=Count("id"),
        verified=Count("id", filter=Q(status="verified")),
    ).order_by("-ordered")
    return [
        {"test": row["test__name"], "ordered": row["ordered"],
         "verified": row["verified"]}
        for row in rows
    ]


@register(
    key="lab_turnaround", title="Laboratory turnaround", group="Laboratory",
    description="Hours from the order being placed to the result being verified.",
    permission="laboratory.view_laborder",
    columns=[
        Column("test", "Test"),
        Column("verified", "Verified results", numeric=True),
        Column("average_hours", "Average hours", numeric=True),
    ],
    notes="Only counts results that were verified inside the period.",
)
def lab_turnaround(*, facilities, date_from, date_to):
    from laboratory.models import LabOrderItem

    start, end = day_range(date_from, date_to)
    # Verification is recorded on the order item rather than on each result
    # value — one signature covers the whole test, which is how a scientist
    # actually verifies one.
    items = scoped(
        LabOrderItem.objects.filter(
            verified_at__isnull=False, verified_at__gte=start, verified_at__lt=end
        ),
        facilities, field="order__facility_id",
    ).select_related("test", "order")

    buckets = {}
    for item in items:
        name = item.test.name
        hours = (item.verified_at - item.order.ordered_at).total_seconds() / 3600
        buckets.setdefault(name, []).append(hours)
    return sorted(
        [
            {"test": name, "verified": len(hours),
             "average_hours": round(sum(hours) / len(hours), 1)}
            for name, hours in buckets.items()
        ],
        key=lambda row: row["average_hours"], reverse=True,
    )


# --- pharmacy ---------------------------------------------------------------

@register(
    key="dispensing", title="Medication dispensed", group="Pharmacy",
    description="What went out of the pharmacy.",
    permission="pharmacy.view_prescription",
    columns=[
        Column("medication", "Medication"),
        Column("dispenses", "Dispenses", numeric=True),
        Column("quantity", "Total quantity", numeric=True),
    ],
)
def dispensing(*, facilities, date_from, date_to):
    from pharmacy.models import Dispense

    start, end = day_range(date_from, date_to)
    rows = scoped(
        Dispense.objects.filter(dispensed_at__gte=start, dispensed_at__lt=end),
        facilities, field="prescription_item__prescription__facility_id",
    ).values("prescription_item__medication__generic_name").annotate(
        dispenses=Count("id"), quantity=Sum("quantity")
    ).order_by("-quantity")
    return [
        {"medication": row["prescription_item__medication__generic_name"],
         "dispenses": row["dispenses"], "quantity": row["quantity"] or 0}
        for row in rows
    ]


@register(
    key="stock_on_hand", title="Stock on hand", group="Pharmacy & stores",
    description="What every store holds now, and what is below its level.",
    permission="inventory.view_stockrecord",
    is_snapshot=True,
    columns=[
        Column("store", "Store"),
        Column("item", "Item"),
        Column("in_date", "In date", numeric=True),
        Column("on_shelf", "On shelf", numeric=True),
        Column("level", "Reorder level", numeric=True),
        Column("status", "Status"),
    ],
)
def stock_on_hand(*, facilities, date_from, date_to):
    from inventory.models import StockRecord

    records = scoped(
        StockRecord.objects.filter(is_active=True),
        facilities, field="store__facility_id",
    ).select_related("store", "item").prefetch_related("lots")
    rows = []
    for record in records:
        usable = record.usable_on_hand()
        rows.append({
            "store": record.store.name,
            "item": record.item.name,
            "in_date": usable,
            "on_shelf": record.on_hand(),
            "level": record.reorder_level,
            "status": "BELOW LEVEL" if usable <= record.reorder_level else "ok",
        })
    return sorted(rows, key=lambda row: (row["status"] != "BELOW LEVEL",
                                         row["store"], row["item"]))


# --- inpatient --------------------------------------------------------------

@register(
    key="admissions", title="Admissions and discharges", group="Inpatient",
    description="Movement through the wards.",
    permission="inpatient.view_admission",
    columns=[
        Column("ward", "Ward"),
        Column("admitted", "Admitted", numeric=True),
        Column("discharged", "Discharged", numeric=True),
        Column("average_stay_days", "Average stay, days", numeric=True),
    ],
)
def admissions(*, facilities, date_from, date_to):
    from inpatient.models import Admission

    start, end = day_range(date_from, date_to)
    admitted = scoped(
        Admission.objects.filter(admitted_at__gte=start, admitted_at__lt=end),
        facilities,
    ).select_related("request")
    discharged = scoped(
        Admission.objects.filter(
            discharged_at__isnull=False, discharged_at__gte=start,
            discharged_at__lt=end,
        ),
        facilities,
    )

    buckets = {}
    for admission in admitted:
        bed = admission.current_bed
        ward = bed.room.ward.name if bed else "—"
        buckets.setdefault(ward, {"ward": ward, "admitted": 0, "discharged": 0,
                                  "stays": []})["admitted"] += 1
    for admission in discharged:
        bed = admission.current_bed
        ward = bed.room.ward.name if bed else "—"
        entry = buckets.setdefault(
            ward, {"ward": ward, "admitted": 0, "discharged": 0, "stays": []}
        )
        entry["discharged"] += 1
        entry["stays"].append(
            (admission.discharged_at - admission.admitted_at).total_seconds() / 86400
        )
    rows = []
    for entry in buckets.values():
        stays = entry.pop("stays")
        entry["average_stay_days"] = (
            round(sum(stays) / len(stays), 1) if stays else 0
        )
        rows.append(entry)
    return sorted(rows, key=lambda row: row["ward"])


@register(
    key="bed_occupancy", title="Bed occupancy", group="Inpatient",
    description="How full each ward is right now.",
    permission="inpatient.view_ward",
    is_snapshot=True,
    columns=[
        Column("ward", "Ward"),
        Column("beds", "Beds", numeric=True),
        Column("occupied", "Occupied", numeric=True),
        Column("available", "Available", numeric=True),
        Column("occupancy_percent", "Occupancy %", numeric=True),
    ],
)
def bed_occupancy(*, facilities, date_from, date_to):
    from inpatient.models import Ward

    wards = scoped(Ward.objects.filter(is_active=True), facilities)
    rows = []
    for ward in wards:
        counts = ward.occupancy()
        total = ward.bed_count
        occupied = counts.get("occupied", 0)
        rows.append({
            "ward": ward.name,
            "beds": total,
            "occupied": occupied,
            "available": counts.get("available", 0),
            "occupancy_percent": round(occupied * 100 / total) if total else 0,
        })
    return sorted(rows, key=lambda row: row["ward"])


# --- emergency --------------------------------------------------------------

@register(
    key="emergency_activity", title="Emergency attendances", group="Emergency",
    description="Arrivals by severity, and how many waited past their target.",
    permission="visits.view_emergencyepisode",
    columns=[
        Column("level", "Triage level"),
        Column("attendances", "Attendances", numeric=True),
        Column("admitted", "Admitted", numeric=True),
        Column("left_without_being_seen", "Left unseen", numeric=True),
    ],
)
def emergency_activity(*, facilities, date_from, date_to):
    from visits.models import EmergencyEpisode

    start, end = day_range(date_from, date_to)
    episodes = scoped(
        EmergencyEpisode.objects.filter(opened_at__gte=start, opened_at__lt=end),
        facilities, field="visit__facility_id",
    ).prefetch_related("triage_assessments__level")

    buckets = {}
    for episode in episodes:
        current = episode.current_triage()
        label = current.level.name if current else "Not triaged"
        entry = buckets.setdefault(
            label,
            {"level": label, "attendances": 0, "admitted": 0,
             "left_without_being_seen": 0,
             "_rank": current.level.rank if current else 0},
        )
        entry["attendances"] += 1
        if episode.outcome == EmergencyEpisode.ADMITTED:
            entry["admitted"] += 1
        if episode.outcome == EmergencyEpisode.LEFT_WITHOUT_BEING_SEEN:
            entry["left_without_being_seen"] += 1

    rows = sorted(buckets.values(), key=lambda row: row["_rank"])
    for row in rows:
        row.pop("_rank")
    return rows


# --- theatre ----------------------------------------------------------------

@register(
    key="theatre_activity", title="Theatre cases", group="Theatre",
    description="What was done, and how long it took.",
    permission="procedures.view_performedprocedure",
    columns=[
        Column("procedure", "Procedure"),
        Column("cases", "Cases", numeric=True),
        Column("average_minutes", "Average minutes", numeric=True),
        Column("abandoned", "Abandoned", numeric=True),
    ],
)
def theatre_activity(*, facilities, date_from, date_to):
    from procedures.models import PerformedProcedure

    start, end = day_range(date_from, date_to)
    performed = scoped(
        PerformedProcedure.objects.filter(
            started_at__gte=start, started_at__lt=end
        ),
        facilities, field="request__facility_id",
    ).select_related("request__procedure")

    buckets = {}
    for case in performed:
        name = case.request.procedure.name
        entry = buckets.setdefault(
            name, {"procedure": name, "cases": 0, "_minutes": [], "abandoned": 0}
        )
        entry["cases"] += 1
        entry["_minutes"].append(case.duration_minutes)
        if case.outcome == PerformedProcedure.ABANDONED:
            entry["abandoned"] += 1
    rows = []
    for entry in buckets.values():
        minutes = entry.pop("_minutes")
        entry["average_minutes"] = round(sum(minutes) / len(minutes)) if minutes else 0
        rows.append(entry)
    return sorted(rows, key=lambda row: row["cases"], reverse=True)


# --- maternity --------------------------------------------------------------

@register(
    key="deliveries", title="Deliveries", group="Maternity",
    description="Births by mode, and their outcomes.",
    permission="maternity.view_delivery",
    columns=[
        Column("mode", "Mode of delivery"),
        Column("deliveries", "Deliveries", numeric=True),
        Column("babies", "Babies", numeric=True),
        Column("live_births", "Live births", numeric=True),
        Column("stillbirths", "Stillbirths", numeric=True),
    ],
)
def deliveries(*, facilities, date_from, date_to):
    from maternity.models import Baby, Delivery

    start, end = day_range(date_from, date_to)
    records = scoped(
        Delivery.objects.filter(delivered_at__gte=start, delivered_at__lt=end),
        facilities, field="pregnancy__facility_id",
    ).prefetch_related("babies")

    buckets = {}
    for delivery in records:
        label = delivery.get_mode_display()
        entry = buckets.setdefault(
            label,
            {"mode": label, "deliveries": 0, "babies": 0, "live_births": 0,
             "stillbirths": 0},
        )
        entry["deliveries"] += 1
        for baby in delivery.babies.all():
            entry["babies"] += 1
            if baby.outcome == Baby.LIVE_BIRTH:
                entry["live_births"] += 1
            else:
                entry["stillbirths"] += 1
    return sorted(buckets.values(), key=lambda row: row["deliveries"], reverse=True)


# --- imaging ----------------------------------------------------------------

@register(
    key="imaging_activity", title="Imaging examinations", group="Imaging",
    description="What was requested and what has been reported.",
    permission="imaging.view_imagingorder",
    columns=[
        Column("procedure", "Examination"),
        Column("requested", "Requested", numeric=True),
        Column("reported", "Reported", numeric=True),
    ],
)
def imaging_activity(*, facilities, date_from, date_to):
    from imaging.models import ImagingOrderItem

    start, end = day_range(date_from, date_to)
    rows = scoped(
        ImagingOrderItem.objects.filter(
            order__ordered_at__gte=start, order__ordered_at__lt=end
        ),
        facilities, field="order__facility_id",
    ).values("procedure__name").annotate(
        requested=Count("id"),
        reported=Count("id", filter=Q(status__in=["reported", "verified"])),
    ).order_by("-requested")
    return [
        {"procedure": row["procedure__name"], "requested": row["requested"],
         "reported": row["reported"]}
        for row in rows
    ]
