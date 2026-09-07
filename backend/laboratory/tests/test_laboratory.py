"""AC-26 to AC-32 — the laboratory workflow end to end."""
import pytest
from django.urls import reverse

from audit.models import AuditEvent
from laboratory.models import LabOrderItem, LabResult
from notifications.models import Notification

ORDERS = reverse("laborder-list")


def item_url(name, item_id):
    return reverse(f"laborderitem-{name}", args=[item_id])


@pytest.mark.django_db
def test_one_test_carries_many_parameters(as_lab, fbc_order_item, fbc):
    """AC-26 — the criterion a "one test, one value" model cannot satisfy.

    A full blood count is one order line producing four independently flagged values.
    """
    as_lab.post(item_url("collect", fbc_order_item.pk), {}, format="json")
    as_lab.post(item_url("start-processing", fbc_order_item.pk), {}, format="json")

    parameters = {p.name: p.pk for p in fbc.parameters.all()}
    response = as_lab.post(
        item_url("results", fbc_order_item.pk),
        {"entries": [
            {"parameter": parameters["Haemoglobin"], "value_numeric": "8.1"},
            {"parameter": parameters["White cell count"], "value_numeric": "14.2"},
            {"parameter": parameters["Platelets"], "value_numeric": "230"},
            {"parameter": parameters["Haematocrit"], "value_numeric": "26.0"},
        ]},
        format="json",
    )
    assert response.status_code == 201, response.data

    results = {row["parameter_name"]: row for row in response.data["results"]}
    assert len(results) == 4
    assert results["Haemoglobin"]["unit"] == "g/dL"
    assert results["White cell count"]["unit"] == "×10⁹/L"
    assert results["Platelets"]["flag"] == LabResult.NORMAL
    assert results["Haemoglobin"]["flag"] == LabResult.LOW
    assert results["White cell count"]["flag"] == LabResult.HIGH


@pytest.mark.django_db
def test_reference_ranges_resolve_by_sex_and_age(as_lab, fbc, order_for, female_patient,
                                                 male_patient):
    """AC-27: 12.5 g/dL is normal for an adult woman and low for an adult man."""
    outcomes = {}
    for patient in (female_patient, male_patient):
        item = order_for(patient, fbc)
        as_lab.post(item_url("collect", item.pk), {}, format="json")
        as_lab.post(item_url("start-processing", item.pk), {}, format="json")
        haemoglobin = fbc.parameters.get(name="Haemoglobin")
        response = as_lab.post(
            item_url("results", item.pk),
            {"entries": [{"parameter": haemoglobin.pk, "value_numeric": "12.5"}]},
            format="json",
        )
        row = response.data["results"][0]
        outcomes[patient.sex] = (row["flag"], row["reference_text"])

    assert outcomes["female"] == (LabResult.NORMAL, "12–16")
    assert outcomes["male"] == (LabResult.LOW, "13–17")


@pytest.mark.django_db
def test_abnormal_results_are_labelled_in_text_not_only_colour(as_lab, resulted_item):
    """AC-28: the flag arrives as words, so it survives print and screen readers."""
    results = {row["parameter_name"]: row for row in
               as_lab.get(reverse("laborderitem-detail",
                                  args=[resulted_item.pk])).data["results"]}
    assert results["Haemoglobin"]["flag_label"] == "CRITICAL LOW"
    assert results["Haemoglobin"]["is_abnormal"] is True
    assert results["Platelets"]["flag_label"] == ""
    assert results["Haemoglobin"]["reference_text"] == "12–16"


@pytest.mark.django_db
def test_a_critical_result_notifies_the_ordering_clinician(resulted_item, doctor):
    """AC-29: raised on entry, before verification — waiting is how one gets missed."""
    notification = Notification.objects.get(kind=Notification.CRITICAL_RESULT)
    assert notification.recipient == doctor
    assert notification.urgency == Notification.URGENT
    assert "CRITICAL" in notification.subject
    assert "Haemoglobin" in notification.subject
    assert AuditEvent.objects.filter(action="lab.critical_result_flagged").exists()


@pytest.mark.django_db
def test_critical_results_appear_on_an_outstanding_list_until_acknowledged(
    as_doctor, resulted_item
):
    """AC-29: who acknowledged it, when, and what they did."""
    outstanding = as_doctor.get(reverse("labresult-critical")).data
    assert len(outstanding) == 1
    assert outstanding[0]["parameter"] == "Haemoglobin"
    assert outstanding[0]["flag_label"] == "CRITICAL LOW"

    result_id = outstanding[0]["result_id"]
    acknowledged = as_doctor.post(
        reverse("labresult-acknowledge", args=[result_id]),
        {"action_taken": "Patient reviewed, two units cross-matched, admitted"},
        format="json",
    )
    assert acknowledged.status_code == 200
    entry = acknowledged.data["acknowledgements"][0]
    assert entry["by"] == "doctor@example.test"
    assert "cross-matched" in entry["action_taken"]
    assert entry["at"]

    assert as_doctor.get(reverse("labresult-critical")).data == []
    assert AuditEvent.objects.filter(action="lab.critical_result_acknowledged").exists()


@pytest.mark.django_db
def test_an_unverified_result_does_not_reach_the_clinician_as_a_finding(
    as_doctor, resulted_item
):
    """AC-30 (negative). The report shows the test as pending, with no values."""
    report = as_doctor.get(
        reverse("laborder-report", args=[resulted_item.order_id])
    ).data
    entry = report["items"][0]
    assert entry["pending"] is True
    assert entry["status"] == LabOrderItem.RESULTED
    assert entry["results"] == []


@pytest.mark.django_db
def test_verification_is_a_separate_permission_from_entry(as_lab_tech, resulted_item):
    """AC-30 (negative): whoever typed the number cannot necessarily sign it off."""
    response = as_lab_tech.post(item_url("verify", resulted_item.pk), {}, format="json")
    assert response.status_code == 403
    resulted_item.refresh_from_db()
    assert resulted_item.status == LabOrderItem.RESULTED


@pytest.mark.django_db
def test_once_verified_the_result_reaches_the_clinician(as_lab, as_doctor, resulted_item):
    """AC-30."""
    verified = as_lab.post(
        item_url("verify", resulted_item.pk),
        {"comment": "Reviewed against film"}, format="json",
    )
    assert verified.status_code == 200
    assert verified.data["verified_by_email"] == "lab@example.test"

    report = as_doctor.get(
        reverse("laborder-report", args=[resulted_item.order_id])
    ).data
    entry = report["items"][0]
    assert entry.get("pending") is None
    assert {row["parameter_name"] for row in entry["results"]} == {
        "Haemoglobin", "White cell count", "Platelets", "Haematocrit"
    }
    assert entry["laboratory_comment"] == "Reviewed against film"
    assert Notification.objects.filter(kind=Notification.RESULT_READY).exists()


@pytest.mark.django_db
def test_amending_a_verified_result_keeps_the_superseded_value(as_lab, resulted_item):
    """AC-31: the old value stays on the record and shows as amended."""
    as_lab.post(item_url("verify", resulted_item.pk), {}, format="json")
    original = LabResult.objects.get(
        order_item=resulted_item, parameter__name="Haemoglobin", is_current=True
    )

    amended = as_lab.post(
        reverse("labresult-amend", args=[original.pk]),
        {"value_numeric": "10.4", "reason": "Sample re-run; original was haemolysed"},
        format="json",
    )
    assert amended.status_code == 200
    assert amended.data["version"] == 2
    assert amended.data["display_value"] == "10.4"
    assert amended.data["flag"] == LabResult.LOW
    assert amended.data["amendment_reason"].startswith("Sample re-run")

    original.refresh_from_db()
    assert original.is_current is False
    assert original.display_value == "5.9"

    detail = as_lab.get(reverse("laborderitem-detail", args=[resulted_item.pk])).data
    assert [row["display_value"] for row in detail["superseded_results"]] == ["5.9"]
    event = AuditEvent.objects.get(action="lab.result_amended")
    assert event.changes["before"]["value"] == "5.9"
    assert event.changes["after"]["value"] == "10.4"


@pytest.mark.django_db
def test_an_amendment_requires_a_reason(as_lab, resulted_item):
    """AC-31 (negative)."""
    as_lab.post(item_url("verify", resulted_item.pk), {}, format="json")
    result = LabResult.objects.get(
        order_item=resulted_item, parameter__name="Haemoglobin", is_current=True
    )
    response = as_lab.post(
        reverse("labresult-amend", args=[result.pk]),
        {"value_numeric": "10.4"}, format="json",
    )
    assert response.status_code == 400
    assert "reason" in response.data
    assert LabResult.objects.filter(parameter__name="Haemoglobin").count() == 1


@pytest.mark.django_db
def test_the_specimen_workflow_does_not_skip_states(as_lab, fbc_order_item, fbc):
    """AC-32 (negative): results cannot be entered for an uncollected specimen."""
    parameters = fbc.parameters.first()
    premature = as_lab.post(
        item_url("results", fbc_order_item.pk),
        {"entries": [{"parameter": parameters.pk, "value_numeric": "12"}]},
        format="json",
    )
    assert premature.status_code == 400
    assert "processed" in premature.data["detail"]

    skipped = as_lab.post(item_url("start-processing", fbc_order_item.pk), {}, format="json")
    assert skipped.status_code == 409
    assert "cannot go from ordered to processing" in skipped.data["detail"].lower()


@pytest.mark.django_db
def test_collection_issues_a_specimen_identifier_for_the_label(as_lab, fbc_order_item):
    """AC-32."""
    response = as_lab.post(item_url("collect", fbc_order_item.pk), {}, format="json")
    assert response.status_code == 200
    label = response.data["label"]
    assert label["specimen_id"].startswith("SPC/")
    assert label["patient_name"]
    assert label["hospital_number"]
    assert label["test"] == "Full blood count"
    assert response.data["item"]["status"] == LabOrderItem.COLLECTED

    again = as_lab.post(item_url("collect", fbc_order_item.pk), {}, format="json")
    assert again.status_code == 409


@pytest.mark.django_db
def test_ordering_a_panel_expands_it_into_its_member_tests(as_doctor, open_visit,
                                                           lab_catalogue):
    order = as_doctor.post(
        ORDERS,
        {"visit": open_visit.pk, "tests": [lab_catalogue["panel"].pk],
         "clinical_details": "Fever, ?malaria"},
        format="json",
    )
    assert order.status_code == 201, order.data
    codes = {item["test_code"] for item in order.data["items"]}
    assert codes == {"FBC", "MP"}


@pytest.mark.django_db
def test_the_worklist_shows_the_bench_what_to_do_urgent_first(as_lab, fbc_order_item):
    rows = as_lab.get(reverse("laborder-worklist")).data
    assert rows[0]["test"] == "Full blood count"
    assert rows[0]["specimen_type"] == "blood"
    assert rows[0]["specimen_requirements"] == "EDTA bottle, 3 mL"
    assert rows[0]["status"] == LabOrderItem.ORDERED


@pytest.mark.django_db
def test_entering_a_result_twice_is_refused_in_favour_of_amending(as_lab, resulted_item,
                                                                  fbc):
    haemoglobin = fbc.parameters.get(name="Haemoglobin")
    response = as_lab.post(
        item_url("results", resulted_item.pk),
        {"entries": [{"parameter": haemoglobin.pk, "value_numeric": "9.0"}]},
        format="json",
    )
    assert response.status_code == 400
    assert "Amend it" in response.data["detail"]


@pytest.mark.django_db
def test_a_parameter_from_another_test_is_refused(as_lab, fbc_order_item, lab_catalogue):
    as_lab.post(item_url("collect", fbc_order_item.pk), {}, format="json")
    as_lab.post(item_url("start-processing", fbc_order_item.pk), {}, format="json")
    foreign = lab_catalogue["malaria"].parameters.first()
    response = as_lab.post(
        item_url("results", fbc_order_item.pk),
        {"entries": [{"parameter": foreign.pk, "value_text": "Positive"}]},
        format="json",
    )
    assert response.status_code == 400
    assert "does not belong" in response.data["detail"]
