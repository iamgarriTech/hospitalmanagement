"""AC-11 (merging), AC-13 (search), AC-7 (access logging)."""
import pytest
from django.urls import reverse

from audit.models import AuditEvent
from patients.models import NextOfKin, Patient, PatientAllergy

LIST = reverse("patient-list")


@pytest.fixture
def two_patients(as_reception, patient_payload):
    first = as_reception.post(LIST, patient_payload(), format="json").data
    second = as_reception.post(
        LIST,
        patient_payload(
            given_name="Emeka", family_name="Obi", date_of_birth="1978-11-02",
            phone_primary="07066554433", blood_group="B+", genotype="AA",
            acknowledge_duplicate=True,
        ),
        format="json",
    ).data
    return first, second


@pytest.mark.django_db
@pytest.mark.parametrize(
    "term_source,expected_name",
    [
        ("hospital_number", "Amina"),
        ("phone", "Emeka"),
        ("surname", "Obi"),
        ("dob", "Emeka"),
        ("misspelled_name", "Amina"),
    ],
)
def test_one_search_box_finds_a_patient_by_any_identifier(
    as_reception, two_patients, term_source, expected_name
):
    """AC-13: reception types whatever the patient gave them."""
    first, second = two_patients
    terms = {
        "hospital_number": first["hospital_number"],
        "phone": "07066554433",
        "surname": "Obi",
        "dob": "1978-11-02",
        "misspelled_name": "Amena Yusuff",
    }
    results = as_reception.get(LIST, {"search": terms[term_source]}).data["results"]
    assert results, f"no match for {term_source}"
    assert expected_name in results[0]["full_name"]


@pytest.mark.django_db
def test_search_with_no_term_lists_patients(as_reception, two_patients):
    assert as_reception.get(LIST).data["count"] == 2


@pytest.mark.django_db
def test_opening_a_record_is_logged_and_the_log_is_itself_permission_gated(
    as_reception, as_records, two_patients
):
    """AC-7."""
    first, _ = two_patients
    detail = reverse("patient-detail", args=[first["id"]])
    as_reception.get(detail)

    viewed = AuditEvent.objects.filter(action="patient.viewed")
    assert viewed.count() == 1
    assert viewed.first().patient_id == first["id"]

    log_url = reverse("patient-access-log", args=[first["id"]])
    assert as_reception.get(log_url).status_code == 403  # reception lacks the permission
    entries = as_records.get(log_url).data
    assert any(entry["action"] == "patient.viewed" for entry in entries)
    assert any(entry["action"] == "patient.registered" for entry in entries)


@pytest.mark.django_db
def test_merging_preserves_every_record_from_both_charts(as_records, two_patients):
    """AC-11: nothing is deleted, and the merged-away number still resolves."""
    first, second = two_patients
    source = Patient.objects.get(pk=first["id"])
    target = Patient.objects.get(pk=second["id"])
    PatientAllergy.objects.create(patient=source, substance="Sulfa", severity="moderate")
    NextOfKin.objects.create(patient=source, full_name="Musa Yusuf", relationship="Brother")

    response = as_records.post(
        reverse("patient-merge", args=[source.pk]),
        {"into": target.pk, "reason": "Same patient registered twice at front desk"},
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["records_moved"]["patients.PatientAllergy"] == 1

    source.refresh_from_db()
    assert Patient.objects.filter(pk=source.pk).exists()  # kept, not deleted
    assert source.status == Patient.MERGED
    assert source.merged_into_id == target.pk
    assert target.allergies.filter(substance="Sulfa").exists()
    assert target.next_of_kin.filter(full_name="Musa Yusuf").exists()

    merge_event = AuditEvent.objects.get(action="patient.merged_away")
    assert merge_event.reason.startswith("Same patient registered twice")
    assert AuditEvent.objects.filter(action="patient.merge_received").exists()


@pytest.mark.django_db
def test_audit_history_is_not_reassigned_by_a_merge(as_records, two_patients):
    """The log must keep saying which record was actually used at the time — and it is
    append-only, so a merge that tried to rewrite it would fail outright."""
    first, second = two_patients
    before = set(
        AuditEvent.objects.filter(patient_id=first["id"]).values_list("id", flat=True)
    )
    assert before

    as_records.post(
        reverse("patient-merge", args=[first["id"]]),
        {"into": second["id"], "reason": "duplicate"},
        format="json",
    )
    after = set(
        AuditEvent.objects.filter(patient_id=first["id"]).values_list("id", flat=True)
    )
    assert before <= after
    ok, problems = AuditEvent.verify_chain()
    assert ok, problems


@pytest.mark.django_db
def test_merged_records_are_hidden_from_search_but_reachable_on_request(
    as_records, two_patients
):
    first, second = two_patients
    as_records.post(
        reverse("patient-merge", args=[first["id"]]),
        {"into": second["id"], "reason": "duplicate"},
        format="json",
    )
    assert as_records.get(LIST).data["count"] == 1
    assert as_records.get(LIST, {"include_merged": "true"}).data["count"] == 2

    detail = as_records.get(reverse("patient-detail", args=[first["id"]])).data
    assert detail["merged_into_hospital_number"] == second["hospital_number"]


@pytest.mark.django_db
def test_merge_requires_the_merge_permission(as_reception, two_patients):
    """AC-11 (negative)."""
    first, second = two_patients
    response = as_reception.post(
        reverse("patient-merge", args=[first["id"]]),
        {"into": second["id"], "reason": "duplicate"},
        format="json",
    )
    assert response.status_code == 403
    assert Patient.objects.get(pk=first["id"]).status == Patient.ACTIVE


@pytest.mark.django_db
def test_merge_is_refused_without_a_reason_and_onto_itself(as_records, two_patients):
    """AC-11 (negative)."""
    first, second = two_patients
    no_reason = as_records.post(
        reverse("patient-merge", args=[first["id"]]), {"into": second["id"]}, format="json"
    )
    assert no_reason.status_code == 400

    onto_self = as_records.post(
        reverse("patient-merge", args=[first["id"]]),
        {"into": first["id"], "reason": "oops"},
        format="json",
    )
    assert onto_self.status_code == 400
    assert "themselves" in onto_self.data["detail"]


@pytest.mark.django_db
def test_a_patient_registered_at_another_facility_is_not_visible(
    as_reception, patient_payload, facility_b
):
    """Guarantee 1 (negative): registering into a facility you have no grant at fails,
    and other facilities' patients do not appear."""
    other = Patient.objects.create(
        given_name="Hidden", family_name="Elsewhere", sex="male", facility=facility_b
    )
    assert as_reception.get(LIST).data["count"] == 0
    assert as_reception.get(reverse("patient-detail", args=[other.pk])).status_code == 404
    refused = as_reception.post(
        LIST, patient_payload(facility=facility_b.pk), format="json"
    )
    assert refused.status_code == 403
