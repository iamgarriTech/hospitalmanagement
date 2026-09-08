"""AC-78 to AC-82 — the nursing record.

The two claims worth testing hardest are that a note cannot be rewritten and
that an escalation nobody answers stays visible. Both are the kind of thing that
holds until the day it matters.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.db.utils import InternalError
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from clinical.models import VitalSigns
from inpatient.models import (
    Escalation,
    EscalationThreshold,
    FluidBalanceEntry,
    NursingAssessment,
    NursingNote,
)
from inpatient.services import fluid_balance


# --- assessments --------------------------------------------------------------

@pytest.mark.django_db
def test_an_assessment_names_its_author_shift_and_observations(
    as_ward_nurse, admission, ward_nurse
):
    """AC-78. Attached to the admission, not to a visit — a stay on day nine has
    nothing to do with that morning's outpatient queue."""
    observations = as_ward_nurse.post(
        reverse("vitals-list"),
        {"patient": admission.patient_id, "admission": admission.pk,
         "facility": admission.facility_id, "temperature_c": "37.2",
         "systolic_bp": 128, "diastolic_bp": 78, "pulse_bpm": 82},
        format="json",
    )
    assert observations.status_code == 201, observations.data

    response = as_ward_nurse.post(
        reverse("nursingassessment-list"),
        {"admission": admission.pk, "shift": "night",
         "observations": observations.data["id"],
         "consciousness": "alert", "mobility": "assisted", "falls_risk": True,
         "eating_and_drinking": "Taking oral fluids well",
         "summary": "Settled overnight, no chest pain"},
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["recorded_by_name"] == "Amaka Nurse"
    assert response.data["shift_display"] == "Night"
    assert response.data["mobility_display"] == "Needs assistance"
    assert response.data["falls_risk"] is True
    assert response.data["patient"] == admission.patient_id
    # The observations are the same row a clinic would have recorded, not a copy.
    assert response.data["observations_detail"]["temperature_c"] == "37.2"

    event = AuditEvent.objects.get(action="nursing.assessment_recorded")
    assert event.changes["after"]["shift"] == "night"
    assert event.changes["after"]["falls_risk"] is True


@pytest.mark.django_db
def test_inpatient_observations_join_the_same_trend_as_outpatient_ones(
    as_ward_nurse, as_nurse, admission, open_visit
):
    """AC-81. A patient's temperature chart does not restart at admission."""
    clinic = as_nurse.post(
        reverse("vitals-list"),
        {"patient": admission.patient_id, "visit": open_visit.pk,
         "facility": admission.facility_id, "temperature_c": "38.9"},
        format="json",
    )
    assert clinic.status_code == 201, clinic.data

    ward = as_ward_nurse.post(
        reverse("vitals-list"),
        {"patient": admission.patient_id, "admission": admission.pk,
         "facility": admission.facility_id, "temperature_c": "37.1"},
        format="json",
    )
    assert ward.status_code == 201, ward.data

    trend = as_ward_nurse.get(
        reverse("vitals-trend"), {"patient": admission.patient_id}
    )
    assert trend.status_code == 200
    # One series, both readings, oldest first.
    assert [point["value"] for point in trend.data["temperature_c"]] == [38.9, 37.1]


@pytest.mark.django_db
def test_an_observation_needs_a_visit_or_an_admission(as_ward_nurse, admission):
    """A reading attached to neither belongs to no episode of care."""
    response = as_ward_nurse.post(
        reverse("vitals-list"),
        {"patient": admission.patient_id, "facility": admission.facility_id,
         "temperature_c": "37.0"},
        format="json",
    )
    assert response.status_code == 400
    assert "attendance or to an admission" in str(response.data)


# --- notes --------------------------------------------------------------------

@pytest.mark.django_db
def test_a_correction_adds_a_note_and_the_original_stays_legible(
    as_ward_nurse, admission
):
    """AC-79."""
    first = as_ward_nurse.post(
        reverse("nursingnote-list"),
        {"admission": admission.pk, "shift": "early",
         "note": "Refused breakfast. Complained of nausea."},
        format="json",
    )
    assert first.status_code == 201, first.data

    correction = as_ward_nurse.post(
        reverse("nursingnote-list"),
        {"admission": admission.pk, "shift": "early",
         "note": "Refused breakfast but took tea. Nausea settled after "
                 "metoclopramide.",
         "supersedes": first.data["id"],
         "correction_reason": "Recorded on the wrong patient's round; nausea "
                              "was treated"},
        format="json",
    )
    assert correction.status_code == 201, correction.data
    assert correction.data["supersedes"] == first.data["id"]

    original = as_ward_nurse.get(reverse("nursingnote-detail", args=[first.data["id"]]))
    # Word for word as written.
    assert original.data["note"] == "Refused breakfast. Complained of nausea."
    assert original.data["is_superseded"] is True
    assert original.data["corrected_by"] == correction.data["id"]

    # The current reading is the correction alone.
    current = as_ward_nurse.get(
        reverse("nursingnote-list"), {"admission": admission.pk, "current": "true"}
    )
    assert [row["id"] for row in current.data["results"]] == [correction.data["id"]]

    assert AuditEvent.objects.filter(action="nursing.note_written").count() == 1
    assert AuditEvent.objects.filter(action="nursing.note_corrected").count() == 1


@pytest.mark.django_db
def test_a_correction_has_to_say_why(as_ward_nurse, admission):
    """AC-79 (negative). A silent rewrite is what this model exists to prevent."""
    first = as_ward_nurse.post(
        reverse("nursingnote-list"),
        {"admission": admission.pk, "shift": "late", "note": "Passed urine 300 mL"},
        format="json",
    )
    response = as_ward_nurse.post(
        reverse("nursingnote-list"),
        {"admission": admission.pk, "shift": "late", "note": "Passed urine 400 mL",
         "supersedes": first.data["id"]},
        format="json",
    )
    assert response.status_code == 400
    assert "why" in str(response.data).lower()
    assert NursingNote.objects.count() == 1


@pytest.mark.django_db
def test_the_api_offers_no_way_to_edit_or_delete_a_note(as_ward_nurse, admission):
    """AC-79 (negative)."""
    note = as_ward_nurse.post(
        reverse("nursingnote-list"),
        {"admission": admission.pk, "shift": "early", "note": "Slept well"},
        format="json",
    )
    url = reverse("nursingnote-detail", args=[note.data["id"]])
    # 403 rather than 405: DRF checks permissions before it looks up a handler,
    # and no permission is declared for these verbs because the viewset has no
    # handler for them. Failing closed here is the right order — it does not
    # reveal which methods exist before authorising the caller.
    for refused in (
        as_ward_nurse.patch(url, {"note": "rewritten"}, format="json"),
        as_ward_nurse.put(url, {"note": "rewritten"}, format="json"),
        as_ward_nurse.delete(url),
    ):
        assert refused.status_code in (403, 405), refused.status_code

    unchanged = as_ward_nurse.get(url)
    assert unchanged.data["note"] == "Slept well"


@pytest.mark.django_db(transaction=True)
def test_the_database_refuses_to_update_a_note_at_all(admission, ward_nurse):
    """AC-79 (negative), below the API.

    The trigger is the reason this is a guarantee rather than a convention: it
    holds against a bug, a console and a future endpoint nobody has written yet.
    """
    note = NursingNote.objects.create(
        admission=admission, patient=admission.patient, shift="early",
        note="Ate all of lunch", author=ward_nurse,
    )
    with pytest.raises((InternalError, IntegrityError)) as raised:
        with transaction.atomic():
            NursingNote.objects.filter(pk=note.pk).update(note="Ate nothing")
    assert "append-only" in str(raised.value)

    with pytest.raises((InternalError, IntegrityError)):
        with transaction.atomic():
            NursingNote.objects.filter(pk=note.pk).delete()

    note.refresh_from_db()
    assert note.note == "Ate all of lunch"


@pytest.mark.django_db
def test_a_note_cannot_be_corrected_twice_in_parallel(as_ward_nurse, admission):
    """AC-79. Corrections form a chain, not a tree — two notes both claiming to
    correct the same one leaves no readable answer to "what does the record say"."""
    first = as_ward_nurse.post(
        reverse("nursingnote-list"),
        {"admission": admission.pk, "shift": "early", "note": "BP 140/90"},
        format="json",
    )
    payload = {
        "admission": admission.pk, "shift": "early", "note": "BP 150/95",
        "supersedes": first.data["id"], "correction_reason": "misread the monitor",
    }
    assert as_ward_nurse.post(
        reverse("nursingnote-list"), payload, format="json"
    ).status_code == 201
    second = as_ward_nurse.post(
        reverse("nursingnote-list"), payload, format="json"
    )
    assert second.status_code == 400
    assert "already been corrected" in str(second.data)


# --- fluid balance ------------------------------------------------------------

@pytest.mark.django_db
def test_the_fluid_balance_is_derived_from_the_entries(as_ward_nurse, admission):
    """AC-80. Never stored: a balance column goes wrong the first time an entry
    is added out of order, and a wrong balance is a clinical decision on bad
    numbers."""
    for direction, route, volume in [
        ("intake", "oral", 400), ("intake", "iv", 1000),
        ("output", "urine", 750), ("output", "vomit", 150),
    ]:
        response = as_ward_nurse.post(
            reverse("fluidbalanceentry-list"),
            {"admission": admission.pk, "direction": direction, "route": route,
             "volume_ml": volume},
            format="json",
        )
        assert response.status_code == 201, response.data

    balance = as_ward_nurse.get(
        reverse("fluidbalanceentry-balance"), {"admission": admission.pk}
    )
    assert balance.status_code == 200, balance.data
    assert balance.data["intake_ml"] == 1400
    assert balance.data["output_ml"] == 900
    assert balance.data["balance_ml"] == 500
    assert balance.data["by_route"]["urine"] == 750
    assert balance.data["entries"] == 4

    # AC-80: the period is configurable, and an entry outside it is excluded.
    old = FluidBalanceEntry.objects.first()
    old.recorded_at = timezone.now() - timedelta(hours=40)
    old.save(update_fields=["recorded_at"])
    narrower = fluid_balance(admission=admission, hours=24)
    assert narrower["entries"] == 3
    wider = fluid_balance(admission=admission, hours=72)
    assert wider["entries"] == 4


@pytest.mark.django_db
def test_an_output_route_cannot_be_recorded_as_intake(as_ward_nurse, admission):
    """AC-80 (negative). An intake row with an output route still adds up, which
    is the worst kind of wrong."""
    response = as_ward_nurse.post(
        reverse("fluidbalanceentry-list"),
        {"admission": admission.pk, "direction": "intake", "route": "urine",
         "volume_ml": 500},
        format="json",
    )
    assert response.status_code == 400
    assert "output route" in str(response.data)
    assert not FluidBalanceEntry.objects.exists()


@pytest.mark.django_db
def test_a_zero_volume_is_refused(as_ward_nurse, admission):
    response = as_ward_nurse.post(
        reverse("fluidbalanceentry-list"),
        {"admission": admission.pk, "direction": "output", "route": "urine",
         "volume_ml": 0},
        format="json",
    )
    assert response.status_code == 400


# --- escalation ---------------------------------------------------------------

@pytest.fixture
def thresholds(ward):
    """What this ward escalates on. Per ward, because the same figure means
    different things in intensive care and on a general ward."""
    EscalationThreshold.objects.create(
        ward=ward, measurement="systolic_bp", low=90, high=180,
        instruction="Tell the registrar and repeat in 15 minutes",
    )
    EscalationThreshold.objects.create(
        ward=ward, measurement="oxygen_saturation", low=92,
        instruction="Start oxygen and call the doctor",
    )
    EscalationThreshold.objects.create(
        ward=ward, measurement="temperature_c", high=Decimal("38.5"),
        instruction="Take blood cultures before antibiotics",
    )
    return ward


@pytest.mark.django_db
def test_an_observation_outside_the_thresholds_is_flagged_for_escalation(
    as_ward_nurse, admission, thresholds
):
    """AC-82. Raised where the observation is recorded, and shown to the nurse
    immediately — an alert nobody sees is not an alert."""
    response = as_ward_nurse.post(
        reverse("vitals-list"),
        {"patient": admission.patient_id, "admission": admission.pk,
         "facility": admission.facility_id, "systolic_bp": 196, "diastolic_bp": 110,
         "oxygen_saturation": 88, "temperature_c": "37.4"},
        format="json",
    )
    assert response.status_code == 201, response.data

    raised = {row["measurement"]: row for row in response.data["escalations"]}
    # Two breaches, and the in-range temperature does not raise one.
    assert set(raised) == {"systolic_bp", "oxygen_saturation"}
    assert raised["systolic_bp"]["direction"] == "high"
    assert raised["systolic_bp"]["breached_bound"] == "180.00"
    assert raised["oxygen_saturation"]["direction"] == "low"
    # The instruction travels with the alert.
    assert raised["oxygen_saturation"]["instruction"] == "Start oxygen and call the doctor"
    assert raised["systolic_bp"]["is_outstanding"] is True
    assert "above the ward bound of 180" in raised["systolic_bp"]["summary"]

    event = AuditEvent.objects.filter(action="nursing.escalation_raised").first()
    assert event is not None
    assert event.changes["after"]["ward"] == "MMW"


@pytest.mark.django_db
def test_an_escalation_keeps_the_bound_it_breached_when_the_ward_changes_it(
    as_ward_nurse, as_ward_manager, admission, thresholds, ward
):
    """AC-82. Thresholds are configuration; an escalation raised last week must
    still say what the instruction was last week."""
    recorded = as_ward_nurse.post(
        reverse("vitals-list"),
        {"patient": admission.patient_id, "admission": admission.pk,
         "facility": admission.facility_id, "systolic_bp": 196, "diastolic_bp": 100},
        format="json",
    )
    escalation_id = recorded.data["escalations"][0]["id"]

    threshold = EscalationThreshold.objects.get(ward=ward, measurement="systolic_bp")
    changed = as_ward_manager.patch(
        reverse("escalationthreshold-detail", args=[threshold.pk]),
        {"high": 200, "instruction": "Repeat in 30 minutes"}, format="json",
    )
    assert changed.status_code == 200, changed.data

    after = as_ward_nurse.get(reverse("escalation-detail", args=[escalation_id]))
    assert after.data["breached_bound"] == "180.00"
    assert after.data["instruction"] == "Tell the registrar and repeat in 15 minutes"


@pytest.mark.django_db
def test_an_unacknowledged_escalation_stays_on_a_list(
    as_ward_nurse, as_ward_manager, admission, thresholds, ward, ward_doctor
):
    """AC-82 (negative), then closing it properly."""
    recorded = as_ward_nurse.post(
        reverse("vitals-list"),
        {"patient": admission.patient_id, "admission": admission.pk,
         "facility": admission.facility_id, "oxygen_saturation": 86},
        format="json",
    )
    escalation_id = recorded.data["escalations"][0]["id"]

    outstanding = as_ward_manager.get(
        reverse("escalation-outstanding"), {"ward": ward.pk}
    )
    assert [row["id"] for row in outstanding.data] == [escalation_id]

    # A recipient who does not exist is refused rather than silently dropped.
    missing = as_ward_manager.post(
        reverse("escalation-notify", args=[escalation_id]),
        {"escalated_to": 999_999}, format="json",
    )
    assert missing.status_code == 400

    # Who was told, and when — recorded separately from the response to it.
    notified = as_ward_manager.post(
        reverse("escalation-notify", args=[escalation_id]),
        {"escalated_to": ward_doctor.pk, "note": "Called from the bedside"},
        format="json",
    )
    assert notified.status_code == 200, notified.data
    assert notified.data["escalated_to_name"] == "Kola Ward"
    assert notified.data["escalated_at"] is not None
    # Telling someone is not the same as it being dealt with.
    assert notified.data["is_outstanding"] is True

    blank = as_ward_manager.post(
        reverse("escalation-acknowledge", args=[escalation_id]),
        {"action_taken": "   "}, format="json",
    )
    assert blank.status_code == 400

    closed = as_ward_manager.post(
        reverse("escalation-acknowledge", args=[escalation_id]),
        {"action_taken": "Oxygen at 4 L/min, saturations back to 96%. "
                         "Registrar reviewed."},
        format="json",
    )
    assert closed.status_code == 200, closed.data
    assert closed.data["is_outstanding"] is False
    assert closed.data["acknowledged_by_name"] == "Ngozi Manager"
    assert closed.data["minutes_waiting"] >= 0

    empty = as_ward_manager.get(reverse("escalation-outstanding"), {"ward": ward.pk})
    assert empty.data == []

    event = AuditEvent.objects.get(action="nursing.escalation_acknowledged")
    assert "Registrar reviewed" in event.reason


@pytest.mark.django_db
def test_an_acknowledgement_cannot_be_a_tick_box(admission, ward_nurse, thresholds):
    """AC-82 (negative), at the model. The constraint refuses an acknowledgement
    with no action recorded even if the API is bypassed."""
    observations = VitalSigns.objects.create(
        patient=admission.patient, admission=admission, facility=admission.facility,
        systolic_bp=200, diastolic_bp=110, recorded_by=ward_nurse,
    )
    escalation = Escalation.objects.create(
        admission=admission, patient=admission.patient, observations=observations,
        measurement="systolic_bp", value=200, direction="high", breached_bound=180,
        raised_by=ward_nurse,
    )
    with pytest.raises(IntegrityError):
        Escalation.objects.filter(pk=escalation.pk).update(
            acknowledged_at=timezone.now(), acknowledged_by=ward_nurse, action_taken=""
        )


@pytest.mark.django_db
def test_a_ward_with_no_thresholds_raises_nothing(as_ward_nurse, admission):
    """A hospital may leave escalation configuration unused, and an observation
    still records. "Modular" means a module can be left out, not that it fails
    quietly when it is."""
    response = as_ward_nurse.post(
        reverse("vitals-list"),
        {"patient": admission.patient_id, "admission": admission.pk,
         "facility": admission.facility_id, "systolic_bp": 210, "diastolic_bp": 130},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["escalations"] == []
    assert not Escalation.objects.exists()
