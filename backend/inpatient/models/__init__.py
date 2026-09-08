"""Inpatient models, grouped by concern.

One app rather than four (wards, admissions, MAR, nursing) because inpatient
care is one domain area: an admission, the bed it occupies, the drug chart and
the nursing record are inseparable, and splitting them would mean a circular
import between apps and four migration graphs to keep in step for what is
really one workflow.

Split across modules inside the app so a file stays the size of one concern.
"""
from .admissions import Admission, AdmissionRequest, BedTransfer
from .mar import STANDARD_TIMES, MedicationAdministration, ScheduledDose, times_for
from .nursing import (
    Escalation,
    FluidBalanceEntry,
    NursingAssessment,
    NursingNote,
)
from .wards import Bed, BedOccupancy, EscalationThreshold, Room, Ward

__all__ = [
    "Admission", "AdmissionRequest", "BedTransfer",
    "Bed", "BedOccupancy", "EscalationThreshold", "Room", "Ward",
    "MedicationAdministration", "ScheduledDose", "STANDARD_TIMES", "times_for",
    "Escalation", "FluidBalanceEntry", "NursingAssessment", "NursingNote",
]
