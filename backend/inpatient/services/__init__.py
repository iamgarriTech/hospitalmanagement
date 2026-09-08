"""Inpatient rules that are the substance rather than plumbing.

Admitting, transferring, charging the stay, building a drug chart and recording
what happened to a dose all live here rather than in views: they are the rules a
hospital depends on, and a view is the wrong place to be able to read them.
"""
from .admissions import (
    BED_NIGHT_RULE,
    admit,
    charge_bed_nights,
    discharge,
    discharge_summary,
    outstanding_before_discharge,
    plan_discharge,
    transfer,
)
from .mar import (
    DEFAULT_OVERDUE_LOOKBACK_HOURS,
    bedside_warnings,
    board_overdue,
    chart,
    current_admission_ids,
    discontinue,
    older_overdue_count,
    overdue_doses,
    record_administration,
    schedule_doses,
)
from .nursing import (
    board_escalations,
    fluid_balance,
    outstanding_escalations,
    record_observation_escalations,
)

__all__ = [
    "BED_NIGHT_RULE", "admit", "charge_bed_nights", "discharge", "discharge_summary",
    "outstanding_before_discharge", "plan_discharge", "transfer",
    "DEFAULT_OVERDUE_LOOKBACK_HOURS", "bedside_warnings", "board_overdue", "chart",
    "current_admission_ids", "discontinue", "older_overdue_count", "overdue_doses",
    "record_administration", "schedule_doses",
    "board_escalations", "fluid_balance", "outstanding_escalations",
    "record_observation_escalations",
]
