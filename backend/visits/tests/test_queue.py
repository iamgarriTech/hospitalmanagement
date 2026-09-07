"""AC-15, AC-17, AC-18, AC-19 — the queue as patient movement, not a list."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connections
from django.urls import reverse

from audit.models import AuditEvent
from patients.models import Patient, PatientAllergy
from visits.models import InvalidTransition, Visit

VISITS = reverse("visit-list")
QUEUE = reverse("visit-queue")


@pytest.fixture
def checked_in(as_reception, patient, facility_a, visit_numbers):
    response = as_reception.post(
        VISITS,
        {"patient": patient.pk, "facility": facility_a.pk, "visit_type": "walk_in",
         "reason": "Fever for three days"},
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data


@pytest.mark.django_db
def test_check_in_creates_a_waiting_visit_and_is_audited(checked_in, patient):
    assert checked_in["status"] == Visit.WAITING
    assert checked_in["visit_number"].startswith("V/")
    event = AuditEvent.objects.get(action="visit.checked_in")
    assert event.patient_id == patient.pk
    assert event.changes["after"]["visit_type"] == "walk_in"


@pytest.mark.django_db
def test_a_patient_cannot_be_checked_in_twice(as_reception, checked_in, patient, facility_a):
    """A second open visit is how one attendance ends up split across two charts."""
    again = as_reception.post(
        VISITS, {"patient": patient.pk, "facility": facility_a.pk}, format="json"
    )
    assert again.status_code == 409
    assert again.data["open_visit"]["visit_number"] == checked_in["visit_number"]
    assert Visit.objects.filter(patient=patient).count() == 1


@pytest.mark.django_db
def test_an_invalid_transition_is_refused_by_the_server(as_reception, checked_in):
    """AC-17 (negative): a completed visit is not reopened."""
    move = reverse("visit-move", args=[checked_in["id"]])
    for target in (Visit.CALLED, Visit.IN_CONSULTATION, Visit.COMPLETED):
        assert as_reception.post(move, {"to": target}, format="json").status_code == 200

    reopen = as_reception.post(move, {"to": Visit.IN_CONSULTATION}, format="json")
    assert reopen.status_code == 409
    assert "Cannot move from completed" in reopen.data["detail"]
    assert Visit.objects.get(pk=checked_in["id"]).status == Visit.COMPLETED
    assert AuditEvent.objects.filter(action="visit.move_refused").exists()


@pytest.mark.django_db
def test_skipping_straight_to_consultation_from_waiting_is_refused(as_reception, checked_in):
    """AC-17 (negative): the patient has to be called first."""
    response = as_reception.post(
        reverse("visit-move", args=[checked_in["id"]]),
        {"to": Visit.IN_CONSULTATION},
        format="json",
    )
    assert response.status_code == 409


@pytest.mark.django_db
def test_every_move_records_who_made_it(as_reception, checked_in):
    """AC-18: the patient's movement through the visit is reconstructable."""
    move = reverse("visit-move", args=[checked_in["id"]])
    as_reception.post(move, {"to": Visit.CALLED, "note": "Room 3"}, format="json")
    as_reception.post(move, {"to": Visit.IN_CONSULTATION}, format="json")
    as_reception.post(move, {"to": Visit.SENT_FOR_INVESTIGATION, "note": "FBC"}, format="json")

    detail = as_reception.get(reverse("visit-detail", args=[checked_in["id"]])).data
    trail = [
        (change["from_status"], change["to_status"], change["changed_by"], change["note"])
        for change in detail["state_changes"]
    ]
    assert trail == [
        (Visit.WAITING, Visit.CALLED, "front@example.test", "Room 3"),
        (Visit.CALLED, Visit.IN_CONSULTATION, "front@example.test", ""),
        (Visit.IN_CONSULTATION, Visit.SENT_FOR_INVESTIGATION, "front@example.test", "FBC"),
    ]
    assert detail["called_at"] and detail["consultation_started_at"]


@pytest.mark.django_db
def test_the_visit_advertises_only_legal_next_moves(as_reception, checked_in):
    detail = as_reception.get(reverse("visit-detail", args=[checked_in["id"]])).data
    assert detail["allowed_transitions"] == sorted([Visit.CALLED, Visit.CANCELLED])


@pytest.mark.django_db(transaction=True)
def test_two_staff_calling_the_same_patient_produces_one_call(
    receptionist, patient, facility_a, visit_numbers
):
    """AC-19: the loser sees the current state rather than silently overwriting."""
    visit = Visit.objects.create(patient=patient, facility=facility_a)

    def call(_):
        try:
            visit.move_to(Visit.CALLED, actor=receptionist)
            return "called"
        except InvalidTransition:
            return "refused"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(call, range(6)))

    assert outcomes.count("called") == 1, outcomes
    assert outcomes.count("refused") == 5
    assert visit.state_changes.filter(to_status=Visit.CALLED).count() == 1


@pytest.mark.django_db
def test_the_queue_shows_active_patients_with_waits_and_allergies(
    as_reception, patient, facility_a, visit_numbers
):
    """AC-15: staff should not have to open a chart to see an allergy."""
    PatientAllergy.objects.create(patient=patient, substance="Penicillin", severity="severe")
    other = Patient.objects.create(
        given_name="Emeka", family_name="Obi", sex="male", facility=facility_a
    )
    first = Visit.objects.create(patient=patient, facility=facility_a)
    Visit.objects.create(patient=other, facility=facility_a)

    rows = as_reception.get(QUEUE).data
    assert len(rows) == 2
    assert rows[0]["patient"]["full_name"].startswith("Amina")
    assert rows[0]["allergies"] == ["Penicillin"]
    assert rows[0]["waiting_minutes"] >= 0

    first.move_to(Visit.CALLED, actor=None)
    first.move_to(Visit.IN_CONSULTATION, actor=None)
    first.move_to(Visit.COMPLETED, actor=None)
    assert len(as_reception.get(QUEUE).data) == 1


@pytest.mark.django_db
def test_moving_the_queue_requires_the_permission(as_viewer, patient, facility_a,
                                                  visit_numbers):
    """AC-17 (negative): read access is not permission to move patients."""
    visit = Visit.objects.create(patient=patient, facility=facility_a)
    response = as_viewer.post(
        reverse("visit-move", args=[visit.pk]), {"to": Visit.CALLED}, format="json"
    )
    assert response.status_code == 403
    assert Visit.objects.get(pk=visit.pk).status == Visit.WAITING


@pytest.mark.django_db
def test_a_visit_at_another_facility_is_not_visible(as_reception, facility_b, hospital_numbers,
                                                    visit_numbers):
    """Guarantee 1 (negative)."""
    elsewhere = Patient.objects.create(
        given_name="Hidden", family_name="Elsewhere", sex="male", facility=facility_b
    )
    visit = Visit.objects.create(patient=elsewhere, facility=facility_b)
    assert as_reception.get(QUEUE).data == []
    assert as_reception.get(reverse("visit-detail", args=[visit.pk])).status_code == 404
