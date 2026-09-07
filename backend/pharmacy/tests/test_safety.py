"""AC-33 to AC-36 — the medication safety checks, and honesty about what is not checked."""
import pytest
from django.urls import reverse

from audit.models import AuditEvent
from patients.models import PatientAllergy, PatientChronicCondition
from pharmacy.models import Prescription, SafetyOverride
from pharmacy.safety import ALLERGY, DOSE_RANGE, DUPLICATE_THERAPY, INTERACTION

PRESCRIPTIONS = reverse("prescription-list")
SCREEN = reverse("prescription-screen")
CAPABILITIES = reverse("prescription-safety-capabilities")


def line(medication, **overrides):
    payload = {
        "medication": medication.pk, "dose": "500", "dose_unit": "mg", "route": "oral",
        "frequency_per_day": 3, "duration_days": 5, "quantity_prescribed": 15,
        "instructions": "After food",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_the_api_states_that_interaction_checking_is_not_running(as_prescriber):
    """AC-36 — the criterion that keeps the system honest.

    No interaction database ships, so the prescribing screen must say so rather than
    let a clinician assume the check happened.
    """
    capabilities = as_prescriber.get(CAPABILITIES).data
    assert capabilities[INTERACTION]["active"] is False
    assert capabilities[INTERACTION]["provider"] is None
    assert "NOT ACTIVE" in capabilities[INTERACTION]["detail"]
    assert "licensed" in capabilities[INTERACTION]["detail"]

    for check in (ALLERGY, DUPLICATE_THERAPY, DOSE_RANGE):
        assert capabilities[check]["active"] is True


@pytest.mark.django_db
def test_prescribing_an_allergen_raises_an_interruptive_warning(
    as_prescriber, open_visit, patient, formulary
):
    """AC-33: the warning names the allergy and the reaction, and blocks by default."""
    PatientAllergy.objects.create(
        patient=patient, substance="Amoxicillin", reaction="Anaphylaxis", severity="severe"
    )
    response = as_prescriber.post(
        PRESCRIPTIONS,
        {"visit": open_visit.pk, "items": [line(formulary["amoxicillin"])]},
        format="json",
    )
    assert response.status_code == 409
    warning = next(w for w in response.data["warnings"] if w["kind"] == ALLERGY)
    assert warning["severity"] == "critical"
    assert "Anaphylaxis" in warning["detail"]
    assert warning["requires_reason"] is True
    assert Prescription.objects.count() == 0


@pytest.mark.django_db
def test_proceeding_past_an_allergy_warning_records_the_reason(
    as_prescriber, open_visit, patient, formulary
):
    """AC-33: a warning that can be dismissed without trace is not a safety control."""
    PatientAllergy.objects.create(
        patient=patient, substance="Amoxicillin", reaction="Rash", severity="mild"
    )
    response = as_prescriber.post(
        PRESCRIPTIONS,
        {"visit": open_visit.pk, "items": [line(formulary["amoxicillin"])],
         "acknowledge_warnings": True,
         "override_reason": "Documented rash was non-urticarial; benefit outweighs risk"},
        format="json",
    )
    assert response.status_code == 201, response.data

    override = SafetyOverride.objects.get(warning_kind=ALLERGY)
    assert override.reason.startswith("Documented rash")
    assert override.overridden_by.email == "prescriber@example.test"
    assert response.data["items"][0]["overrides"][0]["kind"] == ALLERGY

    event = AuditEvent.objects.get(action="prescription.written")
    assert ALLERGY in event.changes["after"]["warnings_overridden"]
    assert event.reason.startswith("Documented rash")


@pytest.mark.django_db
def test_overriding_needs_the_override_permission(
    as_junior, open_visit, patient, formulary
):
    """AC-33 (negative): a house officer cannot wave an allergy warning away."""
    PatientAllergy.objects.create(patient=patient, substance="Amoxicillin")
    response = as_junior.post(
        PRESCRIPTIONS,
        {"visit": open_visit.pk, "items": [line(formulary["amoxicillin"])],
         "acknowledge_warnings": True, "override_reason": "it will be fine"},
        format="json",
    )
    assert response.status_code == 403
    assert Prescription.objects.count() == 0
    assert AuditEvent.objects.filter(action="prescription.override_denied").exists()


@pytest.mark.django_db
def test_overriding_without_a_reason_is_refused(
    as_prescriber, open_visit, patient, formulary
):
    """AC-33 (negative)."""
    PatientAllergy.objects.create(patient=patient, substance="Amoxicillin")
    response = as_prescriber.post(
        PRESCRIPTIONS,
        {"visit": open_visit.pk, "items": [line(formulary["amoxicillin"])],
         "acknowledge_warnings": True},
        format="json",
    )
    assert response.status_code == 400
    assert "override_reason" in response.data
    assert Prescription.objects.count() == 0


@pytest.mark.django_db
def test_duplicate_therapy_is_detected_by_ingredient_and_by_class(
    as_prescriber, open_visit, patient, formulary
):
    """AC-34."""
    as_prescriber.post(
        PRESCRIPTIONS,
        {"visit": open_visit.pk, "items": [line(formulary["amoxicillin"])]},
        format="json",
    )

    same_drug = as_prescriber.post(
        SCREEN,
        {"patient": patient.pk, "medication": formulary["amoxicillin"].pk,
         "dose": "500", "route": "oral", "frequency_per_day": 3},
        format="json",
    ).data["warnings"]
    duplicate = next(w for w in same_drug if w["kind"] == DUPLICATE_THERAPY)
    assert duplicate["severity"] == "warning"
    assert duplicate["requires_reason"] is True

    same_class = as_prescriber.post(
        SCREEN,
        {"patient": patient.pk, "medication": formulary["ampicillin"].pk},
        format="json",
    ).data["warnings"]
    classed = next(w for w in same_class if w["kind"] == DUPLICATE_THERAPY)
    assert classed["severity"] == "advisory"
    assert classed["evidence"]["class"] == "J01CA"


@pytest.mark.django_db
def test_a_dose_above_the_maximum_is_flagged_critical(
    as_prescriber, patient, formulary
):
    """AC-35."""
    warnings = as_prescriber.post(
        SCREEN,
        {"patient": patient.pk, "medication": formulary["paracetamol"].pk,
         "dose": "2000", "route": "oral", "frequency_per_day": 3},
        format="json",
    ).data["warnings"]
    dose_warnings = [w for w in warnings if w["kind"] == DOSE_RANGE]
    assert any("exceeds the maximum single dose" in w["detail"] for w in dose_warnings)
    assert all(w["severity"] == "critical" for w in dose_warnings)


@pytest.mark.django_db
def test_a_daily_total_above_the_ceiling_is_flagged_even_when_each_dose_is_fine(
    as_prescriber, patient, formulary
):
    """AC-35 — the case a per-dose check alone misses."""
    warnings = as_prescriber.post(
        SCREEN,
        {"patient": patient.pk, "medication": formulary["paracetamol"].pk,
         "dose": "1000", "route": "oral", "frequency_per_day": 6},
        format="json",
    ).data["warnings"]
    daily = next(w for w in warnings if "maximum daily dose" in w["detail"])
    assert daily["severity"] == "critical"
    assert daily["evidence"]["daily"] == "6000"


@pytest.mark.django_db
def test_a_dose_below_the_usual_range_is_flagged(as_prescriber, patient, formulary):
    warnings = as_prescriber.post(
        SCREEN,
        {"patient": patient.pk, "medication": formulary["paracetamol"].pk,
         "dose": "100", "route": "oral", "frequency_per_day": 3},
        format="json",
    ).data["warnings"]
    assert any("below the usual single dose" in w["detail"] for w in warnings)


@pytest.mark.django_db
def test_an_unconfigured_dose_range_says_so_rather_than_staying_silent(
    as_prescriber, patient, formulary
):
    """"No warning" must not be mistaken for "checked and fine"."""
    warnings = as_prescriber.post(
        SCREEN,
        {"patient": patient.pk, "medication": formulary["ampicillin"].pk,
         "dose": "500", "route": "oral", "frequency_per_day": 3},
        format="json",
    ).data["warnings"]
    unchecked = next(w for w in warnings if w["kind"] == DOSE_RANGE)
    assert "was not checked" in unchecked["detail"]
    assert unchecked["requires_reason"] is False


@pytest.mark.django_db
def test_paediatric_and_renal_cautions_fire_from_the_catalogue(
    as_prescriber, facility_a, hospital_numbers, formulary
):
    from patients.models import Patient

    child = Patient.objects.create(
        given_name="Zainab", family_name="Musa", sex="female",
        date_of_birth="2018-06-01", facility=facility_a,
    )
    PatientChronicCondition.objects.create(patient=child, condition="Chronic renal disease")

    warnings = as_prescriber.post(
        SCREEN,
        {"patient": child.pk, "medication": formulary["diclofenac"].pk,
         "dose": "50", "route": "oral", "frequency_per_day": 2},
        format="json",
    ).data["warnings"]
    details = " ".join(w["detail"] for w in warnings)
    assert "paediatric caution" in details
    assert "Not recommended under 14" in details
    assert "renal impairment" in details


@pytest.mark.django_db
def test_a_pharmacist_maintained_contraindication_fires(
    as_prescriber, patient, formulary
):
    PatientChronicCondition.objects.create(patient=patient, condition="Peptic ulcer disease")
    warnings = as_prescriber.post(
        SCREEN,
        {"patient": patient.pk, "medication": formulary["diclofenac"].pk,
         "dose": "50", "route": "oral", "frequency_per_day": 2},
        format="json",
    ).data["warnings"]
    rule = next(w for w in warnings if w["kind"] == "contraindication")
    assert "contraindicated in active peptic ulcer" in rule["detail"]


@pytest.mark.django_db
def test_a_clean_prescription_raises_nothing_blocking(
    as_prescriber, open_visit, formulary
):
    response = as_prescriber.post(
        PRESCRIPTIONS,
        {"visit": open_visit.pk,
         "items": [line(formulary["paracetamol"], quantity_prescribed=15)]},
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["items"][0]["overrides"] == []


@pytest.mark.django_db
def test_a_registered_interaction_provider_is_reported_as_active(
    as_prescriber, patient, formulary
):
    """The pluggable seam a deployment with a licence would use."""
    from pharmacy import safety

    class StubProvider:
        name = "Stub Interactions 1.0"

        def check(self, *, medication, concurrent_medications, patient):
            return [
                safety.SafetyWarning(
                    kind=safety.INTERACTION, severity=safety.WARNING,
                    detail="Stub interaction", requires_reason=True,
                )
            ]

    safety.register_interaction_provider(StubProvider())
    try:
        capabilities = as_prescriber.get(CAPABILITIES).data
        assert capabilities[INTERACTION]["active"] is True
        assert capabilities[INTERACTION]["provider"] == "Stub Interactions 1.0"

        warnings = as_prescriber.post(
            SCREEN, {"patient": patient.pk, "medication": formulary["paracetamol"].pk},
            format="json",
        ).data["warnings"]
        assert any(w["kind"] == INTERACTION for w in warnings)
    finally:
        safety.register_interaction_provider(None)
