"""AC-179 and AC-180 — the versioned external facade, and the boundary it
must enforce identically to the internal API.

Two things are being defended. First, that the facade is read-only and
versioned: an integrator writes a client against `/api/fhir/v1/` and nothing
they send can change a record. Second, and the one that would actually hurt: a
caller permitted at one facility sees one facility, in every resource,
including through a parameter that names a record at another.

The scoping is not reimplemented here — the facade uses the same
`FacilityScopedMixin` and `HasPermission` the internal viewsets use. These
tests prove that it is still wired to them.
"""
import pytest
from django.urls import reverse

from .conftest import (
    CONDITIONS,
    ENCOUNTERS,
    MEDICATION_REQUESTS,
    OBSERVATIONS,
    PATIENTS,
    ROOT,
)

RESOURCE_ENDPOINTS = [PATIENTS, ENCOUNTERS, CONDITIONS, OBSERVATIONS,
                      MEDICATION_REQUESTS]


# --- AC-179: versioned, read-only, honest about itself ------------------------

@pytest.mark.django_db
def test_the_version_is_in_the_path():
    """AC-179. A client pinned to v1 keeps working when v2 appears."""
    assert PATIENTS.startswith("/api/fhir/v1/")
    assert ROOT == "/api/fhir/v1/"


@pytest.mark.django_db
def test_the_root_states_what_is_not_supported_without_credentials(api):
    """AC-179, AC-189. An integrator must be able to read the limitations
    before they have an account — otherwise the honest description is behind
    the door it describes."""
    response = api.get(ROOT)

    assert response.status_code == 200, response.data
    assert response.data["mode"] == "read-only"
    assert "not a conformant FHIR server" in response.data["note"]
    not_supported = " ".join(response.data["notSupported"])
    for absent in ["CapabilityStatement", "Chained", "Subscriptions",
                   "Transactions", "Unverified"]:
        assert absent in not_supported


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", RESOURCE_ENDPOINTS)
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_nothing_here_accepts_a_write(as_integration, endpoint, method):
    """AC-179 (negative). Read-only is a property of the surface, not a
    promise in the documentation. Every resource, every write verb.

    The refusal is 403 rather than 405: the facade declares a required
    permission per action and a write action has none, so `HasPermission`
    refuses before the router's method mapping is consulted. Either code is a
    refusal; what matters is that no write verb reaches a handler, and there
    is no handler to reach.
    """
    response = getattr(as_integration, method)(endpoint, {}, format="json")

    assert response.status_code in (403, 405), (endpoint, method,
                                                response.status_code)


@pytest.mark.django_db
def test_a_posted_patient_is_not_created(as_integration, patient):
    """AC-179 (negative). The refusal is not just a status code — nothing
    lands in the table."""
    from patients.models import Patient

    before = Patient.objects.count()
    as_integration.post(
        PATIENTS,
        {"resourceType": "Patient", "name": [{"family": "Intruder"}]},
        format="json",
    )

    assert Patient.objects.count() == before
    assert not Patient.objects.filter(family_name="Intruder").exists()


@pytest.mark.django_db
def test_a_caller_without_the_api_permission_is_refused(as_doctor, patient):
    """AC-180 (negative). A doctor may read this patient in the internal API.
    The external facade is a separate grant, so their session is not enough."""
    response = as_doctor.get(PATIENTS)

    assert response.status_code == 403
    assert patient.family_name not in str(response.data)


@pytest.mark.django_db
def test_an_unauthenticated_caller_is_refused(api, patient):
    for endpoint in RESOURCE_ENDPOINTS:
        response = api.get(endpoint)
        assert response.status_code in (401, 403), endpoint


# --- AC-180: the facility boundary --------------------------------------------

@pytest.mark.django_db
def test_a_one_facility_token_sees_one_facility(as_integration, patient, patient_at_b):
    """AC-180. The account holds the permission at Main Hospital only."""
    response = as_integration.get(PATIENTS)

    assert response.status_code == 200, response.data
    returned = {entry["resource"]["id"] for entry in response.data["entry"]}
    assert str(patient.pk) in returned
    assert str(patient_at_b.pk) not in returned
    assert response.data["total"] == 1


@pytest.mark.django_db
def test_a_patient_at_another_facility_is_not_found_rather_than_forbidden(
    as_integration, patient_at_b
):
    """AC-180 (negative). 404, not 403: a 403 confirms the record exists, and
    "no such patient" and "a patient you may not see" have to be
    indistinguishable across a facility boundary."""
    response = as_integration.get(
        reverse("facade-patient-detail", args=[patient_at_b.pk])
    )

    assert response.status_code == 404
    assert patient_at_b.family_name not in str(response.data)
    assert response.data["resourceType"] == "OperationOutcome"


@pytest.mark.django_db
def test_searching_by_identifier_cannot_cross_the_boundary(as_integration, patient_at_b):
    """AC-180 (negative). The hospital number is a real identifier for a real
    patient — at a facility this caller may not see. Scoping is applied before
    the search filter, so an exact identifier returns nothing."""
    response = as_integration.get(
        PATIENTS, {"identifier": patient_at_b.hospital_number}
    )

    assert response.status_code == 200
    assert response.data["total"] == 0
    assert response.data["entry"] == []


@pytest.mark.django_db
def test_the_patient_parameter_cannot_cross_the_boundary(
    as_integration, patient_at_b, facility_b, visit_numbers
):
    """AC-180 (negative), on every resource that takes a patient parameter.

    This is the shape of the leak worth testing: the caller knows a primary
    key at another facility and asks each resource about it directly.
    """
    for endpoint in [ENCOUNTERS, CONDITIONS, OBSERVATIONS, MEDICATION_REQUESTS]:
        response = as_integration.get(endpoint, {"patient": patient_at_b.pk})
        assert response.status_code == 200, endpoint
        assert response.data["entry"] == [], endpoint


@pytest.mark.django_db
def test_an_encounter_at_another_facility_is_not_found(
    as_integration, patient_at_b, facility_b, doctor, visit_numbers
):
    """AC-180 (negative), through the detail route."""
    from clinical.models import Encounter
    from visits.models import Visit

    visit = Visit.objects.create(patient=patient_at_b, facility=facility_b)
    encounter = Encounter.objects.create(
        visit=visit, patient=patient_at_b, facility=facility_b, clinician=doctor
    )

    response = as_integration.get(
        reverse("facade-encounter-detail", args=[encounter.pk])
    )

    assert response.status_code == 404


# --- what the resources carry --------------------------------------------------

@pytest.mark.django_db
def test_a_patient_resource_is_fhir_shaped(as_integration, patient):
    """AC-179. Close enough to R4 to map without a translation table."""
    entry = as_integration.get(PATIENTS).data["entry"][0]["resource"]

    assert entry["resourceType"] == "Patient"
    assert entry["id"] == str(patient.pk)
    assert entry["name"][0]["family"] == patient.family_name
    assert entry["gender"] == "female"
    assert any(
        identifier["value"] == patient.hospital_number
        for identifier in entry["identifier"]
    )


@pytest.mark.django_db
def test_a_bundle_is_a_searchset(as_integration, patient):
    bundle = as_integration.get(PATIENTS).data

    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "searchset"
    assert bundle["entry"][0]["resource"]["resourceType"] == "Patient"


@pytest.mark.django_db
def test_a_condition_carries_the_code_system_and_its_version(
    as_integration, as_doctor, open_visit
):
    """AC-176 through the outward surface. A diagnosis recorded under ICD-10
    2019 is emitted as ICD-10 2019, not re-mapped to whatever the hospital
    uses next year."""
    created = as_doctor.post(
        reverse("encounter-list"),
        {"visit": open_visit.pk, "presenting_complaint": "Fever",
         "clinical_notes": "RDT positive",
         "diagnoses": [{"description": "Falciparum malaria", "certainty": "confirmed",
                        "is_primary": True, "code_system": "ICD-10", "code": "B50.9",
                        "code_display": "Plasmodium falciparum malaria, unspecified",
                        "code_version": "2019"}]},
        format="json",
    )
    assert created.status_code == 201, created.data
    as_doctor.post(reverse("encounter-finalise", args=[created.data["id"]]))

    entry = as_integration.get(CONDITIONS).data["entry"][0]["resource"]

    coding = entry["code"]["coding"][0]
    assert coding["code"] == "B50.9"
    assert coding["system"] == "ICD-10"
    assert coding["version"] == "2019"


@pytest.mark.django_db
def test_only_the_current_version_of_a_diagnosis_is_emitted(
    as_integration, as_doctor, finalised_encounter
):
    """A superseded version's diagnosis is not a current condition. Emitting
    both would have an integrator record two diagnoses where the hospital
    records one amendment."""
    amended = as_doctor.post(
        reverse("encounter-amend", args=[finalised_encounter["id"]]),
        {"reason": "RDT came back negative; revised to typhoid",
         "clinical_notes": "Typhoid confirmed on culture",
         "presenting_complaint": "Fever for three days",
         "diagnoses": [{"description": "Typhoid fever", "certainty": "confirmed",
                        "is_primary": True}]},
        format="json",
    )
    assert amended.status_code == 200, amended.data

    descriptions = [
        entry["resource"]["code"]["text"]
        for entry in as_integration.get(CONDITIONS).data["entry"]
    ]

    assert descriptions == ["Typhoid fever"]
    assert "Malaria" not in descriptions


@pytest.mark.django_db
def test_an_unverified_result_is_never_exposed(as_integration, resulted_item):
    """AC-185's reasoning, applied outward. An external system that acts on
    an unsigned number automatically is the worst place for one to appear."""
    response = as_integration.get(OBSERVATIONS, {"category": "laboratory"})

    assert response.status_code == 200, response.data
    assert response.data["entry"] == []


@pytest.mark.django_db
def test_a_verified_result_is_exposed_with_its_units(
    as_integration, resulted_item, as_lab
):
    verified = as_lab.post(
        reverse("laborderitem-verify", args=[resulted_item.pk]), {}, format="json"
    )
    assert verified.status_code == 200, verified.data

    response = as_integration.get(OBSERVATIONS, {"category": "laboratory"})

    resources = [entry["resource"] for entry in response.data["entry"]]
    assert resources
    haemoglobin = next(
        r for r in resources if "Haemoglobin" in str(r["code"])
    )
    assert haemoglobin["status"] == "final"
    assert haemoglobin["valueQuantity"]["value"] == 5.9


@pytest.mark.django_db
def test_vitals_come_back_as_observations(as_integration, as_nurse, open_visit, patient):
    recorded = as_nurse.post(
        reverse("vitals-list"),
        {"visit": open_visit.pk, "patient": patient.pk,
         "facility": open_visit.facility_id,
         "temperature_c": "38.4", "pulse_bpm": 104,
         "systolic_bp": 118, "diastolic_bp": 76, "respiratory_rate": 20,
         "oxygen_saturation": 97},
        format="json",
    )
    assert recorded.status_code == 201, recorded.data

    response = as_integration.get(OBSERVATIONS, {"category": "vital-signs"})

    codes = {
        entry["resource"]["code"]["coding"][0]["code"]
        for entry in response.data["entry"]
    }
    assert codes
    assert all(
        entry["resource"]["subject"]["reference"] == f"Patient/{patient.pk}"
        for entry in response.data["entry"]
    )


@pytest.mark.django_db
def test_a_medication_request_names_the_prescriber(
    as_integration, amoxicillin_prescription, prescriber
):
    entry = as_integration.get(MEDICATION_REQUESTS).data["entry"][0]["resource"]

    assert entry["resourceType"] == "MedicationRequest"
    assert entry["requester"]["reference"] == f"Practitioner/{prescriber.pk}"
    assert entry["status"] == "active"
    assert "Amoxicillin" in entry["medicationCodeableConcept"]["text"]
    # The dose reads as a dose, not as a DecimalField.
    assert "500 mg oral" in entry["dosageInstruction"][0]["text"]


# --- paging --------------------------------------------------------------------

@pytest.mark.django_db
def test_count_is_capped(as_integration, patient):
    """A caller asking for everything gets a page. Two hundred is the cap the
    root document advertises."""
    response = as_integration.get(PATIENTS, {"_count": 5000})

    assert response.status_code == 200
    assert len(response.data["entry"]) <= 200


@pytest.mark.django_db
def test_offset_walks_the_collection(as_integration, patient, facility_a,
                                    hospital_numbers):
    from patients.models import Patient

    second = Patient.objects.create(
        given_name="Tunde", family_name="Alabi", sex="male",
        date_of_birth="1970-01-05", facility=facility_a,
    )

    first_page = as_integration.get(PATIENTS, {"_count": 1})
    second_page = as_integration.get(PATIENTS, {"_count": 1, "_offset": 1})

    assert first_page.data["total"] == 2
    assert len(first_page.data["entry"]) == 1
    ids = {first_page.data["entry"][0]["resource"]["id"],
           second_page.data["entry"][0]["resource"]["id"]}
    assert ids == {str(patient.pk), str(second.pk)}


@pytest.mark.django_db
def test_a_nonsense_count_is_a_bad_request_not_a_crash(as_integration, patient):
    """(negative) An integrator's off-by-one in a query string should not be
    a 500 in a hospital's logs at three in the morning."""
    response = as_integration.get(PATIENTS, {"_count": "all-of-them"})

    assert response.status_code == 400
    assert "whole numbers" in str(response.data)
