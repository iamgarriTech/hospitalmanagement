"""AC-20, AC-21, AC-22 — clinical history that survives correction."""
import pytest
from django.urls import reverse

from audit.models import AuditEvent
from clinical.models import Encounter, EncounterVersion


@pytest.mark.django_db
def test_a_draft_is_edited_in_place_without_accumulating_versions(as_doctor, open_visit):
    """A consultation being typed should not create a version per save."""
    encounter = as_doctor.post(
        reverse("encounter-list"),
        {"visit": open_visit.pk, "presenting_complaint": "Fever"},
        format="json",
    ).data
    detail = reverse("encounter-detail", args=[encounter["id"]])

    as_doctor.patch(detail, {"presenting_complaint": "Fever and headache"}, format="json")
    as_doctor.patch(detail, {"examination_findings": "Temp 38.9"}, format="json")

    current = as_doctor.get(detail).data
    assert current["version_count"] == 1
    assert current["current"]["presenting_complaint"] == "Fever and headache"
    assert current["current"]["examination_findings"] == "Temp 38.9"
    assert current["status"] == Encounter.DRAFT


@pytest.mark.django_db
def test_amending_a_finalised_record_creates_a_version_and_keeps_the_old_one(
    as_doctor, finalised_encounter
):
    """AC-20."""
    detail = reverse("encounter-detail", args=[finalised_encounter["id"]])
    response = as_doctor.post(
        reverse("encounter-amend", args=[finalised_encounter["id"]]),
        {"clinical_notes": "Revised: malaria confirmed on RDT",
         "reason": "Rapid test result arrived after the consultation"},
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["status"] == Encounter.AMENDED
    assert response.data["version_count"] == 2

    versions = as_doctor.get(
        reverse("encounter-versions", args=[finalised_encounter["id"]])
    ).data
    first, second = versions
    assert first["version_number"] == 1
    assert first["clinical_notes"] == "Suspected malaria, awaiting RDT"
    assert first["is_current"] is False
    assert first["amendment_reason"] == ""
    assert second["clinical_notes"] == "Revised: malaria confirmed on RDT"
    assert second["is_current"] is True
    assert second["amends"] == first["id"]


@pytest.mark.django_db
def test_an_amendment_requires_a_reason(as_doctor, finalised_encounter):
    """AC-22 (negative)."""
    response = as_doctor.post(
        reverse("encounter-amend", args=[finalised_encounter["id"]]),
        {"clinical_notes": "changed my mind"},
        format="json",
    )
    assert response.status_code == 400
    assert "reason" in response.data
    assert EncounterVersion.objects.filter(
        encounter_id=finalised_encounter["id"]
    ).count() == 1


@pytest.mark.django_db
def test_the_reason_is_stored_on_the_version_and_audited(as_doctor, finalised_encounter):
    """AC-22."""
    as_doctor.post(
        reverse("encounter-amend", args=[finalised_encounter["id"]]),
        {"clinical_notes": "Corrected", "reason": "Transcription error in the notes"},
        format="json",
    )
    version = EncounterVersion.objects.get(
        encounter_id=finalised_encounter["id"], version_number=2
    )
    assert version.amendment_reason == "Transcription error in the notes"

    event = AuditEvent.objects.get(action="encounter.amended")
    assert event.reason == "Transcription error in the notes"
    assert event.changes["before"]["clinical_notes"] == "Suspected malaria, awaiting RDT"
    assert event.changes["after"]["clinical_notes"] == "Corrected"


@pytest.mark.django_db
def test_amending_today_does_not_touch_an_earlier_consultation(
    as_doctor, patient, facility_a, visit_numbers, open_visit
):
    """AC-21 — the one that matters most.

    An earlier encounter's recorded diagnosis must be byte-identical after a later
    encounter is amended.
    """
    from visits.models import Visit

    older = as_doctor.post(
        reverse("encounter-list"),
        {"visit": open_visit.pk, "clinical_notes": "January review: stable",
         "diagnoses": [{"description": "Hypertension", "certainty": "confirmed",
                        "is_primary": True}]},
        format="json",
    ).data
    as_doctor.post(reverse("encounter-finalise", args=[older["id"]]))

    older_before = as_doctor.get(reverse("encounter-detail", args=[older["id"]])).data
    snapshot = older_before["current"]

    # A later encounter, on a second visit, amended.
    open_visit.move_to(Visit.CALLED, actor=None)
    open_visit.move_to(Visit.IN_CONSULTATION, actor=None)
    open_visit.move_to(Visit.COMPLETED, actor=None)
    second_visit = Visit.objects.create(patient=patient, facility=facility_a)
    newer = as_doctor.post(
        reverse("encounter-list"),
        {"visit": second_visit.pk, "clinical_notes": "March review",
         "diagnoses": [{"description": "Hypertension", "certainty": "confirmed"}]},
        format="json",
    ).data
    as_doctor.post(reverse("encounter-finalise", args=[newer["id"]]))
    as_doctor.post(
        reverse("encounter-amend", args=[newer["id"]]),
        {"clinical_notes": "March review: BP now uncontrolled",
         "diagnoses": [{"description": "Hypertension, poorly controlled",
                        "certainty": "confirmed", "is_primary": True}],
         "reason": "Diagnosis refined after review of readings"},
        format="json",
    )

    older_after = as_doctor.get(reverse("encounter-detail", args=[older["id"]])).data
    assert older_after["current"] == snapshot
    assert older_after["current"]["diagnoses"][0]["description"] == "Hypertension"
    assert older_after["version_count"] == 1
    assert older_after["status"] == Encounter.FINAL


@pytest.mark.django_db
def test_diagnoses_from_the_previous_version_survive_an_amendment(
    as_doctor, finalised_encounter
):
    """AC-21: the earlier diagnosis set stays attached to the earlier version."""
    as_doctor.post(
        reverse("encounter-amend", args=[finalised_encounter["id"]]),
        {"diagnoses": [{"description": "Typhoid fever", "certainty": "confirmed"}],
         "reason": "Widal and culture results"},
        format="json",
    )
    versions = as_doctor.get(
        reverse("encounter-versions", args=[finalised_encounter["id"]])
    ).data
    assert [d["description"] for d in versions[0]["diagnoses"]] == ["Malaria"]
    assert [d["description"] for d in versions[1]["diagnoses"]] == ["Typhoid fever"]


@pytest.mark.django_db
def test_carried_fields_are_preserved_when_only_one_field_is_amended(
    as_doctor, finalised_encounter
):
    as_doctor.post(
        reverse("encounter-amend", args=[finalised_encounter["id"]]),
        {"clinical_notes": "Updated", "reason": "correction"},
        format="json",
    )
    version = EncounterVersion.objects.get(
        encounter_id=finalised_encounter["id"], version_number=2
    )
    assert version.presenting_complaint == "Fever for three days"
    assert version.clinical_notes == "Updated"


@pytest.mark.django_db
def test_a_finalised_record_cannot_be_edited_through_the_draft_route(
    as_doctor, finalised_encounter
):
    """AC-20 (negative): the only way to change a final record is an amendment."""
    response = as_doctor.patch(
        reverse("encounter-detail", args=[finalised_encounter["id"]]),
        {"clinical_notes": "sneaky edit"},
        format="json",
    )
    assert response.status_code == 409
    assert "amend" in response.data["detail"]
    version = EncounterVersion.objects.get(encounter_id=finalised_encounter["id"])
    assert version.clinical_notes == "Suspected malaria, awaiting RDT"


@pytest.mark.django_db
def test_amending_requires_the_amend_permission(as_nurse, finalised_encounter):
    """AC-20 (negative): reading a record is not permission to rewrite it."""
    response = as_nurse.post(
        reverse("encounter-amend", args=[finalised_encounter["id"]]),
        {"clinical_notes": "x", "reason": "y"},
        format="json",
    )
    assert response.status_code == 403
    assert EncounterVersion.objects.filter(
        encounter_id=finalised_encounter["id"]
    ).count() == 1
