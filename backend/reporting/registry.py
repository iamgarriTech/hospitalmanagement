"""What a report is, and the one thing every report must do.

AC-174 is the gate: no report may show a row, a total or a count from a
facility the person running it cannot see. Rather than trusting eleven report
functions to each remember that, the shape below makes it structural —

- a report is a function that **must** accept `facilities`, a list of ids the
  runner resolved from the caller's permissions;
- `run()` is the only thing that calls it, and it is the only thing that
  resolves that list;
- `check_reports_are_scoped()` fails at import time if a registered report
  does not take the argument, so a new report cannot quietly skip it.

That last check is deliberately crude. It cannot prove a report *uses* the
list — only a test running each report as a single-facility user can do that,
which is what AC-174 asks for — but it does stop the commonest version of the
mistake, which is forgetting the parameter exists.
"""

import inspect
from dataclasses import dataclass
from datetime import date

from django.utils import timezone


@dataclass(frozen=True)
class Column:
    """One column. `numeric` drives alignment and CSV formatting, nothing else."""

    key: str
    label: str
    numeric: bool = False
    money: bool = False


@dataclass(frozen=True)
class Report:
    key: str
    title: str
    group: str
    description: str
    permission: str
    columns: list[Column]
    fn: object
    # Some reports are a point-in-time picture (stock on hand) rather than a
    # period (payments taken). Saying which stops somebody comparing a
    # snapshot against a range and wondering why the totals move.
    is_snapshot: bool = False
    notes: str = ""


REPORTS: dict[str, Report] = {}


def register(*, key, title, group, description, permission, columns,
             is_snapshot=False, notes=""):
    def wrap(fn):
        REPORTS[key] = Report(
            key=key, title=title, group=group, description=description,
            permission=permission, columns=columns, fn=fn,
            is_snapshot=is_snapshot, notes=notes,
        )
        return fn
    return wrap


def check_reports_are_scoped():
    """Every report takes `facilities`. AC-174, enforced at import."""
    offenders = [
        key for key, report in REPORTS.items()
        if "facilities" not in inspect.signature(report.fn).parameters
    ]
    if offenders:
        raise RuntimeError(
            "These reports do not accept a `facilities` argument and would show "
            "every facility's data to anybody who ran them: "
            + ", ".join(sorted(offenders))
        )


def permitted_facilities(user, permission):
    """The facility ids this user may see, or None for all of them.

    None means "every facility" — a group-wide role. Callers must treat that
    as unfiltered rather than as an empty list, which is the other way this
    goes wrong.
    """
    if user.is_superuser:
        return None
    granted = set(user.facilities_for(permission))
    if None in granted:
        return None
    return sorted(f for f in granted if f is not None)


def run(key, *, user, date_from=None, date_to=None, facility=None):
    """Run a report for this user. The only path to a report's rows.

    Returns the rows and the metadata AC-176 asks for: when it ran, and every
    filter that produced it, so two people comparing printouts can see why
    they differ.
    """
    report = REPORTS.get(key)
    if report is None:
        raise KeyError(key)

    facilities = permitted_facilities(user, report.permission)
    if facility is not None:
        # Narrowing to one facility, but never widening: a caller asking for a
        # facility they cannot see gets an empty list rather than that
        # facility's data.
        facility = int(facility)
        if facilities is None or facility in facilities:
            facilities = [facility]
        else:
            facilities = []

    today = timezone.localdate()
    if date_to is None:
        date_to = today
    if date_from is None:
        date_from = date_to.replace(day=1)

    rows = list(report.fn(
        facilities=facilities, date_from=date_from, date_to=date_to
    ))
    return {
        "key": report.key,
        "title": report.title,
        "group": report.group,
        "description": report.description,
        "notes": report.notes,
        "is_snapshot": report.is_snapshot,
        "columns": [
            {"key": c.key, "label": c.label, "numeric": c.numeric, "money": c.money}
            for c in report.columns
        ],
        "rows": rows,
        "row_count": len(rows),
        # AC-176. Everything that could make two printouts disagree.
        "run_at": timezone.now(),
        "run_by": user.email,
        "filters": {
            "date_from": None if report.is_snapshot else date_from,
            "date_to": None if report.is_snapshot else date_to,
            "facilities": facilities,
            "facility_scope": (
                "every facility you may see" if facilities is None
                else f"{len(facilities)} facility/facilities"
            ),
        },
    }


def available(user):
    """The reports this user may run, grouped as the screen shows them."""
    return [
        report for report in REPORTS.values()
        if user.is_superuser or user.facilities_for(report.permission)
    ]


def scoped(queryset, facilities, field="facility_id"):
    """Apply the facility scope. AC-174.

    `None` means every facility; a list narrows; an empty list shows nothing.
    That last case matters: a caller who asked for a facility they cannot see
    must get no rows, not all of them.
    """
    if facilities is None:
        return queryset
    return queryset.filter(**{f"{field}__in": facilities})


def day_range(date_from: date, date_to: date):
    """A local date range as timezone-aware bounds, end inclusive."""
    from datetime import datetime, time, timedelta

    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(date_from, time.min), tz)
    end = timezone.make_aware(
        datetime.combine(date_to + timedelta(days=1), time.min), tz
    )
    return start, end
