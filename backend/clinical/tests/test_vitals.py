"""AC-24, AC-25 — observations, trends, and a BMI nobody can type."""
import pytest
from django.urls import reverse

from audit.models import AuditEvent
from clinical.models import VitalSigns

VITALS = reverse("vitals-list")


@pytest.mark.django_db
def test_vitals_are_recorded_with_units_and_audited(as_nurse, open_visit, patient):
    response = as_nurse.post(
        VITALS,
        {"patient": patient.pk, "visit": open_visit.pk, "facility": open_visit.facility_id,
         "temperature_c": "38.9", "systolic_bp": 130, "diastolic_bp": 85,
         "pulse_bpm": 96, "respiratory_rate": 20, "oxygen_saturation": 97,
         "weight_kg": "68.50", "height_cm": "165.0", "pain_score": 4},
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["blood_pressure"] == "130/85"
    assert response.data["recorded_by_email"] == "nurse@example.test"

    event = AuditEvent.objects.get(action="vitals.recorded")
    assert event.changes["after"]["blood_pressure"] == "130/85"
    assert event.patient_id == patient.pk


@pytest.mark.django_db
def test_bmi_is_derived_and_recalculates(as_nurse, open_visit, patient):
    """AC-25."""
    created = as_nurse.post(
        VITALS,
        {"patient": patient.pk, "visit": open_visit.pk, "facility": open_visit.facility_id,
         "weight_kg": "68.50", "height_cm": "165.0"},
        format="json",
    ).data
    assert created["bmi"] == pytest.approx(25.2, abs=0.05)

    vitals = VitalSigns.objects.get(pk=created["id"])
    vitals.weight_kg = 80
    vitals.save(update_fields=["weight_kg"])
    assert vitals.bmi == pytest.approx(29.4, abs=0.05)


@pytest.mark.django_db
def test_bmi_cannot_be_typed_in(as_nurse, open_visit, patient):
    """AC-25 (negative)."""
    response = as_nurse.post(
        VITALS,
        {"patient": patient.pk, "visit": open_visit.pk, "facility": open_visit.facility_id,
         "weight_kg": "68.5", "height_cm": "165.0", "bmi": 18},
        format="json",
    )
    assert response.status_code == 400
    assert "bmi" in response.data


@pytest.mark.django_db
def test_bmi_is_absent_rather_than_wrong_when_height_is_missing(as_nurse, open_visit, patient):
    created = as_nurse.post(
        VITALS,
        {"patient": patient.pk, "visit": open_visit.pk, "facility": open_visit.facility_id,
         "weight_kg": "68.5"},
        format="json",
    ).data
    assert created["bmi"] is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field,value",
    [
        ("temperature_c", "389.0"),   # decimal point slipped
        ("pulse_bpm", 900),
        ("oxygen_saturation", 150),   # impossible percentage
        ("weight_kg", "0.05"),
        ("height_cm", "1650.0"),      # metres entered as centimetres
    ],
)
def test_implausible_readings_are_refused(as_nurse, open_visit, patient, field, value):
    """A slipped decimal point in a vital sign is a clinical safety problem, not a typo."""
    response = as_nurse.post(
        VITALS,
        {"patient": patient.pk, "visit": open_visit.pk,
         "facility": open_visit.facility_id, field: value},
        format="json",
    )
    assert response.status_code == 400, f"{field}={value} was accepted"
    assert VitalSigns.objects.count() == 0


@pytest.mark.django_db
def test_diastolic_above_systolic_is_refused(as_nurse, open_visit, patient):
    response = as_nurse.post(
        VITALS,
        {"patient": patient.pk, "visit": open_visit.pk, "facility": open_visit.facility_id,
         "systolic_bp": 70, "diastolic_bp": 120},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_a_trend_series_is_returned_for_charting(as_nurse, open_visit, patient):
    """AC-24: vital trends viewable over time."""
    for day, (temp, systolic) in enumerate([("38.9", 130), ("38.1", 128), ("37.2", 122)]):
        as_nurse.post(
            VITALS,
            {"patient": patient.pk, "visit": open_visit.pk,
             "facility": open_visit.facility_id, "temperature_c": temp,
             "systolic_bp": systolic, "diastolic_bp": 80},
            format="json",
        )

    series = as_nurse.get(reverse("vitals-trend"), {"patient": patient.pk}).data
    assert [point["value"] for point in series["temperature_c"]] == [38.9, 38.1, 37.2]
    assert [point["value"] for point in series["systolic_bp"]] == [130.0, 128.0, 122.0]
    assert all("at" in point for point in series["temperature_c"])
    assert "pain_score" not in series  # nothing recorded, so no empty series


@pytest.mark.django_db
def test_an_erroneous_reading_is_marked_not_deleted(as_nurse, open_visit, patient):
    created = as_nurse.post(
        VITALS,
        {"patient": patient.pk, "visit": open_visit.pk,
         "facility": open_visit.facility_id, "temperature_c": "41.5"},
        format="json",
    ).data
    marked = as_nurse.post(
        reverse("vitals-mark-erroneous", args=[created["id"]]),
        {"reason": "Thermometer faulty, re-taken"},
        format="json",
    )
    assert marked.status_code == 200
    assert VitalSigns.objects.filter(pk=created["id"]).exists()

    assert as_nurse.get(VITALS, {"patient": patient.pk}).data["count"] == 0
    assert as_nurse.get(
        VITALS, {"patient": patient.pk, "include_erroneous": "true"}
    ).data["count"] == 1
    assert AuditEvent.objects.filter(action="vitals.marked_erroneous").exists()
