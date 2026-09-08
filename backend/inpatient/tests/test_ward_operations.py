"""AC-110 to AC-112 — the screens a ward runs on.

The bed board is the one screen that has to be enough to hand over a shift, and
the snapshot is the one artefact that has to work when nothing else does.
"""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from inpatient.models import Bed, EscalationThreshold, ScheduledDose
from inpatient.snapshot import render, ward_snapshot_data
from patients.models import PatientAllergy


@pytest.fixture
def busy_ward(
    admission, ward, beds, ward_doctor, ward_nurse, inpatient_prescription,
    facility_a, hospital_numbers
):
    """One ward with a patient who has everything outstanding at once."""
    from clinical.models import VitalSigns
    from inpatient.models import Escalation

    PatientAllergy.objects.create(
        patient=admission.patient, substance="Penicillin",
        reaction="Anaphylaxis", severity="severe", recorded_by=ward_doctor,
    )
    # A dose nobody recorded, three hours ago.
    ScheduledDose.objects.create(
        prescription_item=inpatient_prescription, admission=admission,
        patient=admission.patient, due_at=timezone.now() - timedelta(hours=3),
        sequence=1, dose=inpatient_prescription.dose, dose_unit="mg", route="oral",
    )
    threshold = EscalationThreshold.objects.create(
        ward=ward, measurement="systolic_bp", high=180,
        instruction="Tell the registrar",
    )
    observations = VitalSigns.objects.create(
        patient=admission.patient, admission=admission, facility=facility_a,
        systolic_bp=198, diastolic_bp=112, recorded_by=ward_nurse,
    )
    Escalation.objects.create(
        admission=admission, patient=admission.patient, observations=observations,
        threshold=threshold, measurement="systolic_bp", value=198, direction="high",
        breached_bound=180, instruction="Tell the registrar", raised_by=ward_nurse,
    )
    # A bed out of service, so the board has something other than patients on it.
    beds[3].set_service_state(Bed.MAINTENANCE, note="Broken side rail")
    return ward


# --- the board ----------------------------------------------------------------

@pytest.mark.django_db
def test_the_board_is_enough_to_hand_over_a_shift(as_ward_nurse, busy_ward, admission):
    """AC-110. Patient, allergies, overdue doses and outstanding escalations —
    from one screen, without opening a chart."""
    response = as_ward_nurse.get(reverse("ward-board", args=[busy_ward.pk]))
    assert response.status_code == 200, response.data

    assert response.data["occupancy"] == {
        "beds": 4, "occupied": 1, "available": 2, "reserved": 0,
        "cleaning": 0, "maintenance": 1,
    }

    by_state = {row["bed_label"]: row for row in response.data["beds"]}
    assert len(by_state) == 4

    occupied = next(row for row in response.data["beds"] if row["patient"])
    patient = occupied["patient"]
    assert occupied["state"] == "occupied"
    assert occupied["state_display"] == "Occupied"
    assert patient["name"] == admission.patient.full_name
    assert patient["hospital_number"] == admission.patient.hospital_number
    assert patient["diagnosis"] == "Hypertensive urgency"
    assert patient["consultant"] == "Kola Ward"
    # What must not be given, on the board itself.
    assert patient["allergies"] == ["Penicillin"]
    # What is outstanding, with enough detail to act on.
    assert len(patient["overdue_doses"]) == 1
    assert patient["overdue_doses"][0]["minutes_late"] >= 180
    assert "Amoxicillin" in patient["overdue_doses"][0]["medication"]
    assert len(patient["escalations"]) == 1
    assert patient["escalations"][0]["instruction"] == "Tell the registrar"
    assert patient["escalations"][0]["value"] == "198.00"

    # A bed out of service says why, in words.
    broken = next(row for row in response.data["beds"] if row["state"] == "maintenance")
    assert broken["state_display"] == "Unavailable for maintenance"
    assert broken["state_note"] == "Broken side rail"
    assert broken["patient"] is None


@pytest.mark.django_db
def test_the_board_offers_only_what_the_caller_can_actually_do(
    as_ward_nurse, as_ward_doctor, as_ward_manager, busy_ward
):
    """AC-112. A nurse, a doctor and a ward manager see different work from the
    same URL — so the board never shows a button that will 403."""
    nurse = as_ward_nurse.get(reverse("ward-board", args=[busy_ward.pk])).data["can"]
    doctor = as_ward_doctor.get(reverse("ward-board", args=[busy_ward.pk])).data["can"]
    manager = as_ward_manager.get(reverse("ward-board", args=[busy_ward.pk])).data["can"]

    # The nurse gives medication and takes observations, and cannot admit or discharge.
    assert nurse["administer"] is True
    assert nurse["observe"] is True
    assert nurse["manage_beds"] is True
    assert nurse["admit"] is False
    assert nurse["discharge"] is False

    # The doctor admits, moves and discharges, and does not give the drugs.
    assert doctor["admit"] is True
    assert doctor["transfer"] is True
    assert doctor["discharge"] is True
    assert doctor["administer"] is False

    # The manager runs the ward.
    assert manager["admit"] is True
    assert manager["discharge"] is True
    assert manager["manage_beds"] is True

    assert nurse != doctor != manager


@pytest.mark.django_db
def test_a_ward_at_another_facility_is_not_found_rather_than_forbidden(
    as_ward_nurse, facility_b, organization
):
    """404, not 403. A 403 confirms the ward exists, and "no such ward" has to
    be indistinguishable from "a ward you may not see"."""
    from inpatient.models import Ward

    elsewhere = Ward.objects.create(
        facility=facility_b, name="Ikeja Medical", code="IKM"
    )
    response = as_ward_nurse.get(reverse("ward-board", args=[elsewhere.pk]))
    assert response.status_code == 404


# --- beds ---------------------------------------------------------------------

@pytest.mark.django_db
def test_a_bed_cannot_be_marked_available_while_someone_is_in_it(
    as_ward_nurse, admission, beds
):
    """AC-72 (negative). The patient in it is the authority on whether it is free."""
    response = as_ward_nurse.post(
        reverse("bed-state", args=[beds[0].pk]),
        {"service_state": "available"}, format="json",
    )
    assert response.status_code == 409
    assert "occupied" in str(response.data)
    beds[0].refresh_from_db()
    assert beds[0].is_occupied is True
    assert AuditEvent.objects.filter(
        action="bed.state_change_refused", outcome=AuditEvent.DENIED
    ).exists()


@pytest.mark.django_db
def test_taking_a_bed_out_of_service_is_audited_with_the_reason(
    as_ward_nurse, beds
):
    """AC-68."""
    response = as_ward_nurse.post(
        reverse("bed-state", args=[beds[1].pk]),
        {"service_state": "maintenance", "note": "Mattress condemned"},
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["state"] == "maintenance"
    assert response.data["state_display"] == "Unavailable for maintenance"

    event = AuditEvent.objects.get(action="bed.state_changed")
    assert event.changes["before"]["service_state"] == "available"
    assert event.changes["after"]["service_state"] == "maintenance"
    assert event.reason == "Mattress condemned"


@pytest.mark.django_db
def test_bed_history_has_no_gaps(as_ward_nurse, admission, beds, ward_doctor):
    """AC-71. For any bed: who occupied it and when, in order."""
    from inpatient.services import transfer

    transfer(admission=admission, to_bed=beds[2], reason="Moved", actor=ward_doctor)

    history = as_ward_nurse.get(reverse("bed-history", args=[beds[0].pk]))
    assert history.status_code == 200, history.data
    assert len(history.data) == 1
    entry = history.data[0]
    assert entry["patient_name"] == admission.patient.full_name
    assert entry["started_at"] is not None
    assert entry["ended_at"] is not None
    assert entry["allocated_by_name"] == "Kola Ward"
    assert entry["ended_by_name"] == "Kola Ward"
    assert entry["reason_ended"] == "transferred"

    # And the bed the patient moved to is still open.
    onward = as_ward_nurse.get(reverse("bed-history", args=[beds[2].pk]))
    assert onward.data[0]["ended_at"] is None


# --- the emergency snapshot ---------------------------------------------------

@pytest.mark.django_db
def test_the_snapshot_is_a_self_contained_file_that_needs_no_server(
    busy_ward, admission, settings, tmp_path
):
    """AC-111.

    The test that matters is that the artefact is a *file* with no external
    dependency: an endpoint that needs the application running answers a
    different question from the one the connectivity decision asked.
    """
    settings.WARD_SNAPSHOT_ROOT = str(tmp_path)
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command("ward_snapshot", "--ward", busy_ward.code, stdout=out)

    written = list(tmp_path.glob("*.html"))
    assert len(written) == 1, written
    page = written[0].read_text(encoding="utf-8")

    # Everything AC-111 names.
    assert admission.patient.full_name in page
    assert admission.patient.hospital_number in page
    assert str(admission.current_bed) in page
    assert "Penicillin" in page
    assert "Hypertensive urgency" in page
    assert "Kola Ward" in page
    assert "Amoxicillin" in page

    # Nothing to fetch: no stylesheet, no script, no image, no font, no network.
    for forbidden in ("<script", "<link", "<img", "src=", "@import", "http://", "https://"):
        assert forbidden not in page, forbidden

    # It says out loud that it is stale, because a snapshot read as live is
    # worse than no snapshot.
    assert "Read-only" in page
    assert "out of date the" in page

    # Patient data on disk is not world-readable.
    assert oct(written[0].stat().st_mode)[-3:] == "640"


@pytest.mark.django_db
def test_the_snapshot_shows_a_bed_that_is_empty_as_empty(ward, settings, tmp_path):
    """A snapshot of an empty ward must say so rather than render blank — a page
    with no rows reads as a failed generation."""
    settings.WARD_SNAPSHOT_ROOT = str(tmp_path)
    page = render(ward_snapshot_data(ward))
    assert "No patients on this ward." in page


@pytest.mark.django_db
def test_regenerating_the_snapshot_is_audited(as_ward_manager, busy_ward, settings,
                                              tmp_path):
    """Writing patient data to disk is an event worth recording."""
    settings.WARD_SNAPSHOT_ROOT = str(tmp_path)
    response = as_ward_manager.post(reverse("ward-snapshot", args=[busy_ward.pk]))
    assert response.status_code == 200, response.data
    assert response.data["patients"] == 1
    assert response.data["beds_total"] == 4

    event = AuditEvent.objects.get(action="ward.snapshot_written")
    assert event.changes["after"]["patients"] == 1
    assert str(tmp_path) in event.changes["after"]["path"]


@pytest.mark.django_db
def test_the_snapshot_is_written_atomically(busy_ward, settings, tmp_path):
    """Written to a staging name and renamed, so a ward opening the file while
    it regenerates never reads half a page."""
    settings.WARD_SNAPSHOT_ROOT = str(tmp_path)
    from inpatient.snapshot import write_ward_snapshot

    write_ward_snapshot(busy_ward)
    write_ward_snapshot(busy_ward)
    assert list(tmp_path.glob("*.partial")) == []
    assert len(list(tmp_path.glob("*.html"))) == 1


# --- which beds are free ------------------------------------------------------

@pytest.mark.django_db
def test_an_empty_ward_reports_all_its_beds_as_free(as_ward_nurse, ward, beds):
    """The regression that mattered most and looked least likely.

    `.exclude(occupancies__period__endswith__isnull=True)` reads correctly and
    is wrong: Django compiles it to `NOT EXISTS(... LEFT OUTER JOIN ...)`, a bed
    with no occupancy rows produces one all-NULL joined row, `upper(period) IS
    NULL` is true of it, and the bed is excluded. Every free bed disappeared —
    the ward clerk was told there were no beds on an empty ward.
    """
    assert Bed.allocatable(ward=ward).count() == 4

    response = as_ward_nurse.get(reverse("bed-list"), {"ward": ward.pk,
                                                       "state": "available"})
    assert response.status_code == 200
    assert len(response.data["results"]) == 4


@pytest.mark.django_db
def test_a_free_bed_list_excludes_the_occupied_the_cleaning_and_the_broken(
    as_ward_nurse, admission, ward, beds
):
    """One occupied, one being cleaned, one out of service: one left."""
    beds[1].set_service_state(Bed.CLEANING, note="terminal clean")
    beds[2].set_service_state(Bed.MAINTENANCE, note="broken rail")

    free = list(Bed.allocatable(ward=ward))
    assert free == [beds[3]]

    response = as_ward_nurse.get(reverse("bed-list"), {"ward": ward.pk,
                                                       "state": "available"})
    assert [row["id"] for row in response.data["results"]] == [beds[3].pk]

    # And the ward census still accounts for every bed.
    counts = ward.occupancy()
    assert counts == {"beds": 4, "occupied": 1, "available": 1, "reserved": 0,
                      "cleaning": 1, "maintenance": 1}
    assert sum(
        value for key, value in counts.items() if key != "beds"
    ) == counts["beds"]
