"""Medication safety screening.

Every check here runs on data the hospital owns, so it can ship in an open repository.
Drug–drug interaction checking cannot: the serious databases are commercially licensed.
Rather than ship an empty table that looks like a feature, interaction checking is a
pluggable provider with **no default**, and `capabilities()` states plainly that it is
not running so the prescribing screen can say so.

A clinician who believes a check is running will prescribe as though it is. That makes a
silently absent check more dangerous than a visibly absent one.
"""
from dataclasses import dataclass, field
from typing import Protocol

from core.formatting import trim_decimal

from .models import DoseRange, PrescriptionItem

ALLERGY = "allergy"
DUPLICATE_THERAPY = "duplicate_therapy"
DOSE_RANGE = "dose_range"
SPECIAL_POPULATION = "special_population"
CONTRAINDICATION = "contraindication"
INTERACTION = "drug_drug_interaction"

CRITICAL = "critical"
WARNING = "warning"
ADVISORY = "advisory"


@dataclass
class SafetyWarning:
    kind: str
    severity: str
    detail: str
    # Only the serious ones interrupt. Advisories are shown but do not demand a reason,
    # because a screen that demands justification for everything trains people to type
    # "ok" — and then the warning that mattered gets "ok" too.
    requires_reason: bool = False
    evidence: dict = field(default_factory=dict)

    def as_dict(self):
        return {
            "kind": self.kind,
            "severity": self.severity,
            "detail": self.detail,
            "requires_reason": self.requires_reason,
            "evidence": self.evidence,
        }


class InteractionProvider(Protocol):
    """Implemented by a deployment that licenses an interaction database."""

    name: str

    def check(self, *, medication, concurrent_medications, patient) -> list[SafetyWarning]:
        ...


_provider: InteractionProvider | None = None


def register_interaction_provider(provider):
    """Called by a deployment that has licensed interaction data."""
    global _provider
    _provider = provider
    return provider


def get_interaction_provider():
    return _provider


def capabilities():
    """What is and is not being checked. Surfaced on the prescribing screen (AC-36)."""
    provider = get_interaction_provider()
    return {
        ALLERGY: {
            "active": True,
            "detail": "Prescribed ingredients are matched against recorded allergies.",
        },
        DUPLICATE_THERAPY: {
            "active": True,
            "detail": "Same ingredient or therapeutic class already active for this patient.",
        },
        DOSE_RANGE: {
            "active": True,
            "detail": "Single and daily dose checked against the catalogue for this "
                      "route and age band.",
        },
        SPECIAL_POPULATION: {
            "active": True,
            "detail": "Paediatric and renal cautions recorded on the catalogue entry.",
        },
        CONTRAINDICATION: {
            "active": True,
            "detail": "Rules maintained by the hospital pharmacy department.",
        },
        INTERACTION: {
            "active": provider is not None,
            "provider": getattr(provider, "name", None),
            "detail": (
                f"Provided by {provider.name}." if provider else
                "NOT ACTIVE. Drug–drug interaction checking requires a licensed "
                "interaction database, which is not bundled with this system. Check "
                "interactions independently."
            ),
        },
    }


def _normalise(value):
    return (value or "").strip().lower()


def _check_allergies(patient, medication):
    warnings = []
    ingredients = [_normalise(name) for name in medication.ingredients]
    for allergy in patient.allergies.all():
        if not allergy.is_active:
            continue
        substance = _normalise(allergy.substance)
        if not substance:
            continue
        hit = next(
            (
                name for name in ingredients
                if substance in name or name in substance
            ),
            None,
        )
        if hit or (medication.atc_class and substance == _normalise(medication.atc_class)):
            warnings.append(
                SafetyWarning(
                    kind=ALLERGY,
                    severity=CRITICAL,
                    detail=(
                        f"{patient.full_name} is recorded as allergic to "
                        f"{allergy.substance}"
                        + (f" — reaction: {allergy.reaction}" if allergy.reaction else "")
                        + f". {medication.generic_name} contains {hit or allergy.substance}."
                    ),
                    requires_reason=True,
                    evidence={
                        "allergy": allergy.substance,
                        "reaction": allergy.reaction,
                        "severity": allergy.severity,
                        "matched_ingredient": hit,
                    },
                )
            )
    return warnings


def _check_duplicate_therapy(patient, medication, exclude_item=None):
    active = PrescriptionItem.objects.filter(
        prescription__patient=patient,
        status__in=[PrescriptionItem.PRESCRIBED, PrescriptionItem.PARTIALLY_DISPENSED],
    ).select_related("medication", "prescription")
    if exclude_item is not None:
        active = active.exclude(pk=exclude_item)

    warnings = []
    for item in active:
        other = item.medication
        if other.pk == medication.pk or _normalise(other.generic_name) == _normalise(
            medication.generic_name
        ):
            warnings.append(
                SafetyWarning(
                    kind=DUPLICATE_THERAPY,
                    severity=WARNING,
                    detail=(
                        f"{medication.generic_name} is already active on prescription "
                        f"{item.prescription.prescription_number} "
                        f"({other.strength} {other.dosage_form})."
                    ),
                    requires_reason=True,
                    evidence={"prescription": item.prescription.prescription_number},
                )
            )
        elif (
            medication.atc_class
            and other.atc_class
            and other.atc_class == medication.atc_class
        ):
            warnings.append(
                SafetyWarning(
                    kind=DUPLICATE_THERAPY,
                    severity=ADVISORY,
                    detail=(
                        f"{other.generic_name} is already active and is in the same "
                        f"therapeutic class ({medication.atc_class})."
                    ),
                    evidence={"class": medication.atc_class,
                              "other": other.generic_name},
                )
            )
    return warnings


def _check_dose(patient, medication, dose, route, frequency_per_day):
    if dose is None:
        return []
    age = patient.age_years
    ranges = [
        candidate for candidate in medication.dose_ranges.all()
        if candidate.applies_to(route=route, age_years=age)
    ]
    if not ranges:
        # Say so rather than staying silent: "no warning" must not be mistaken for
        # "dose checked and fine".
        return [
            SafetyWarning(
                kind=DOSE_RANGE,
                severity=ADVISORY,
                detail=(
                    f"No dose range is configured for {medication.generic_name} by "
                    f"{route}"
                    + (f" at age {age}" if age is not None else " for unknown age")
                    + ". The dose was not checked."
                ),
            )
        ]

    reference = ranges[0]
    warnings = []
    if dose < reference.min_single_dose:
        warnings.append(
            SafetyWarning(
                kind=DOSE_RANGE,
                severity=WARNING,
                detail=(
                    f"{trim_decimal(dose)} {reference.dose_unit} is below the usual single dose of "
                    f"{trim_decimal(reference.min_single_dose)}–"
                    f"{trim_decimal(reference.max_single_dose)} "
                    f"{reference.dose_unit}."
                ),
                requires_reason=True,
                evidence={"min": str(reference.min_single_dose),
                          "max": str(reference.max_single_dose)},
            )
        )
    elif dose > reference.max_single_dose:
        warnings.append(
            SafetyWarning(
                kind=DOSE_RANGE,
                severity=CRITICAL,
                detail=(
                    f"{trim_decimal(dose)} {reference.dose_unit} exceeds the maximum single dose of "
                    f"{trim_decimal(reference.max_single_dose)} {reference.dose_unit}."
                ),
                requires_reason=True,
                evidence={"max": trim_decimal(reference.max_single_dose)},
            )
        )

    if reference.max_daily_dose and frequency_per_day:
        daily = dose * frequency_per_day
        if daily > reference.max_daily_dose:
            warnings.append(
                SafetyWarning(
                    kind=DOSE_RANGE,
                    severity=CRITICAL,
                    detail=(
                        f"{trim_decimal(dose)} {reference.dose_unit} × {frequency_per_day}/day is "
                        f"{trim_decimal(daily)} {reference.dose_unit}, above the maximum daily dose "
                        f"of {trim_decimal(reference.max_daily_dose)} {reference.dose_unit}."
                    ),
                    requires_reason=True,
                    evidence={"daily": trim_decimal(daily),
                              "max_daily": trim_decimal(reference.max_daily_dose)},
                )
            )
    return warnings


def _check_special_population(patient, medication):
    warnings = []
    age = patient.age_years
    if medication.paediatric_caution and age is not None and age < 12:
        warnings.append(
            SafetyWarning(
                kind=SPECIAL_POPULATION,
                severity=WARNING,
                detail=(
                    f"{medication.generic_name} carries a paediatric caution and the "
                    f"patient is {age}."
                    + (f" {medication.caution_note}" if medication.caution_note else "")
                ),
                requires_reason=True,
                evidence={"age_years": age},
            )
        )
    conditions = [
        _normalise(condition.condition)
        for condition in patient.chronic_conditions.all()
        if condition.is_active
    ]
    if medication.avoid_in_renal_impairment and any(
        keyword in condition
        for condition in conditions
        for keyword in ("renal", "kidney", "nephro", "dialysis")
    ):
        warnings.append(
            SafetyWarning(
                kind=SPECIAL_POPULATION,
                severity=WARNING,
                detail=(
                    f"{medication.generic_name} should be avoided or dose-adjusted in "
                    f"renal impairment, which this patient has recorded."
                ),
                requires_reason=True,
            )
        )
    return warnings


def _check_contraindications(patient, medication):
    conditions = [
        _normalise(condition.condition)
        for condition in patient.chronic_conditions.all()
        if condition.is_active
    ]
    warnings = []
    for rule in medication.contraindications.all():
        if not rule.is_active:
            continue
        keyword = _normalise(rule.condition_keyword)
        if any(keyword in condition for condition in conditions):
            warnings.append(
                SafetyWarning(
                    kind=CONTRAINDICATION,
                    severity=CRITICAL if rule.severity == rule.WARNING else ADVISORY,
                    detail=rule.note,
                    requires_reason=rule.severity == rule.WARNING,
                    evidence={"rule": rule.condition_keyword},
                )
            )
    return warnings


def screen(*, patient, medication, dose=None, route=None, frequency_per_day=None,
           exclude_item=None):
    """Run every available check and return the warnings, worst first."""
    route = route or medication.default_route
    warnings = [
        *_check_allergies(patient, medication),
        *_check_duplicate_therapy(patient, medication, exclude_item=exclude_item),
        *_check_dose(patient, medication, dose, route, frequency_per_day),
        *_check_special_population(patient, medication),
        *_check_contraindications(patient, medication),
    ]

    provider = get_interaction_provider()
    if provider is not None:
        concurrent = [
            item.medication
            for item in PrescriptionItem.objects.filter(
                prescription__patient=patient,
                status__in=[PrescriptionItem.PRESCRIBED,
                            PrescriptionItem.PARTIALLY_DISPENSED],
            ).select_related("medication")
        ]
        warnings.extend(
            provider.check(
                medication=medication,
                concurrent_medications=concurrent,
                patient=patient,
            )
        )

    order = {CRITICAL: 0, WARNING: 1, ADVISORY: 2}
    warnings.sort(key=lambda warning: order.get(warning.severity, 3))
    return warnings
