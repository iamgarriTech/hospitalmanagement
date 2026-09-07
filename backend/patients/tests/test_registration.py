"""AC-8 to AC-12: hospital numbers, duplicate detection, merging, header data."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connections
from django.urls import reverse

from audit.models import AuditEvent
from patients.models import NumberSequence, Patient

LIST = reverse("patient-list")


@pytest.mark.django_db
def test_registration_issues_a_hospital_number_in_the_configured_format(
    as_reception, patient_payload
):
    """AC-8."""
    response = as_reception.post(LIST, patient_payload(), format="json")
    assert response.status_code == 201, response.data
    number = response.data["hospital_number"]
    prefix, year, serial = number.split("/")
    assert prefix == "ILS"
    assert len(serial) == 5 and serial.isdigit()
    assert year.isdigit() and len(year) == 4


@pytest.mark.django_db(transaction=True)
def test_concurrent_registrations_never_collide(receptionist, facility_a, hospital_numbers):
    """AC-8: allocation is serialized, so simultaneous registrations get distinct numbers."""

    def register(index):
        try:
            return Patient.objects.create(
                given_name=f"Test{index}",
                family_name="Concurrent",
                sex="unknown",
                facility=facility_a,
            ).hospital_number
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=8) as pool:
        numbers = list(pool.map(register, range(24)))

    assert len(set(numbers)) == 24, "duplicate hospital numbers were issued"
    assert NumberSequence.objects.get(key="hospital_number").next_value == 25


@pytest.mark.django_db
def test_a_suspected_duplicate_is_surfaced_before_the_record_is_created(
    as_reception, patient_payload
):
    """AC-9: the second attempt is refused with the candidates, and nothing is created."""
    assert as_reception.post(LIST, patient_payload(), format="json").status_code == 201

    response = as_reception.post(LIST, patient_payload(), format="json")
    assert response.status_code == 409
    assert Patient.objects.count() == 1

    candidate = response.data["duplicates"][0]
    assert candidate["patient"]["hospital_number"]
    assert candidate["score"] > 0.9
    assert any("same phone number" in reason for reason in candidate["reasons"])
    assert any("same date of birth" in reason for reason in candidate["reasons"])


@pytest.mark.django_db
def test_a_near_miss_on_name_alone_is_still_surfaced(as_reception, patient_payload):
    """A misspelling is the common way duplicates get created."""
    as_reception.post(LIST, patient_payload(), format="json")
    response = as_reception.post(
        LIST,
        patient_payload(given_name="Aminat", phone_primary="08099998888",
                        date_of_birth="1991-04-18"),
        format="json",
    )
    assert response.status_code == 409
    assert "name" in response.data["duplicates"][0]["reasons"][0]


@pytest.mark.django_db
def test_duplicate_detection_warns_but_does_not_block_an_authorized_override(
    as_records, patient_payload
):
    """AC-10: genuine near-duplicates exist, so an authorized user can proceed."""
    as_records.post(LIST, patient_payload(), format="json")

    response = as_records.post(
        LIST,
        patient_payload(acknowledge_duplicate=True, duplicate_reason="Twin sister, seen together"),
        format="json",
    )
    assert response.status_code == 201, response.data
    assert Patient.objects.count() == 2

    override = AuditEvent.objects.get(action="patient.duplicate_override")
    assert override.reason == "Twin sister, seen together"
    assert override.actor_email == "records@example.test"
    assert len(override.changes["after"]["despite"]) == 1


@pytest.mark.django_db
def test_override_is_refused_without_the_override_permission(as_reception, patient_payload):
    """AC-10 (negative): reception cannot wave the warning away."""
    as_reception.post(LIST, patient_payload(), format="json")
    response = as_reception.post(
        LIST, patient_payload(acknowledge_duplicate=True, duplicate_reason="whatever"),
        format="json",
    )
    assert response.status_code == 403
    assert Patient.objects.count() == 1
    assert AuditEvent.objects.filter(action="patient.duplicate_override_denied").exists()


@pytest.mark.django_db
def test_override_is_refused_without_a_reason(as_records, patient_payload):
    """AC-10 (negative)."""
    as_records.post(LIST, patient_payload(), format="json")
    response = as_records.post(
        LIST, patient_payload(acknowledge_duplicate=True), format="json"
    )
    assert response.status_code == 400
    assert "duplicate_reason" in response.data
    assert Patient.objects.count() == 1


@pytest.mark.django_db
def test_registration_is_audited_with_the_values_recorded(as_reception, patient_payload):
    as_reception.post(LIST, patient_payload(), format="json")
    event = AuditEvent.objects.get(action="patient.registered")
    assert event.patient is not None
    assert event.changes["after"]["family_name"] == "Yusuf"
    assert event.changes["after"]["genotype"] == "AS"
    assert event.facility is not None


@pytest.mark.django_db
def test_the_profile_carries_the_safety_information_a_header_needs(
    as_reception, patient_payload
):
    """AC-12: allergies, blood group and genotype arrive with the patient, not on a
    second request."""
    created = as_reception.post(
        LIST,
        patient_payload(
            allergies=[
                {"substance": "Penicillin", "reaction": "Anaphylaxis", "severity": "severe"}
            ],
            chronic_conditions=[{"condition": "Sickle cell trait"}],
            next_of_kin=[{"full_name": "Musa Yusuf", "relationship": "Brother",
                          "phone": "08034445555"}],
        ),
        format="json",
    )
    assert created.status_code == 201, created.data

    detail = as_reception.get(reverse("patient-detail", args=[created.data["id"]]))
    assert detail.data["blood_group"] == "O+"
    assert detail.data["genotype"] == "AS"
    assert detail.data["allergies"][0]["substance"] == "Penicillin"
    assert detail.data["allergies"][0]["severity"] == "severe"
    assert detail.data["chronic_conditions"][0]["condition"] == "Sickle cell trait"
    assert detail.data["next_of_kin"][0]["relationship"] == "Brother"
    assert detail.data["age_years"] >= 34


@pytest.mark.django_db
def test_a_patient_who_does_not_know_their_date_of_birth_can_still_register(
    as_reception, patient_payload
):
    response = as_reception.post(
        LIST,
        patient_payload(date_of_birth=None, date_of_birth_is_estimated=True),
        format="json",
    )
    assert response.status_code == 201
    assert response.data["age_years"] is None
    assert response.data["date_of_birth_is_estimated"] is True
