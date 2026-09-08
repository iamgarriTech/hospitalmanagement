"""AC-94 to AC-98 — radiology.

Two claims carry this file. An unverified report must not reach the requesting
clinician as a finding (AC-96) — a clinician acting on a draft is acting on
something the radiologist has not stood behind. And amending a verified report
appends rather than overwrites (AC-97): correcting "no fracture" to "undisplaced
fracture" must not erase what the first report said, because somebody made a
decision on it.
"""
from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from billing.models import Invoice
from imaging.models import ImagingOrder, ImagingOrderItem, ImagingProcedure, ImagingReport
from imaging.reporting import perform, unacknowledged_critical_findings
from notifications.models import Notification

# --- the catalogue ------------------------------------------------------------

@pytest.mark.django_db
def test_the_catalogue_is_administrable(as_imaging_admin, imaging_catalogue, facility_a):
    """AC-94. Modality, body part, preparation instructions and price."""
    response = as_imaging_admin.post(
        reverse("imagingprocedure-list"),
        {"modality": imaging_catalogue["xray"].pk,
         "name": "Pelvis X-ray, AP", "code_short": "XR-PELVIS",
         "body_part": "Pelvis",
         "preparation_instructions": "Remove metal from pockets.",
         "typical_minutes": 10},
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["modality_name"] == "X-ray"
    assert response.data["body_part"] == "Pelvis"

    listed = as_imaging_admin.get(
        reverse("imagingprocedure-list"), {"facility": facility_a.pk}
    )
    by_code = {row["code_short"]: row for row in listed.data["results"]}
    # Priced through the ordinary service machinery, per facility.
    assert by_code["CXR"]["price"] == "8000.00"
    assert by_code["CTAP"]["price"] == "95000.00"
    # A procedure with no service configured says so rather than showing zero.
    assert by_code["USG-ABD"]["price"] is None
    assert by_code["CTAP"]["requires_contrast"] is True
    assert "Nil by mouth" in by_code["CTAP"]["preparation_instructions"]
    assert "Renal impairment" in by_code["CTAP"]["contraindications"]

    assert AuditEvent.objects.filter(action="imaging.procedure_added").exists()


@pytest.mark.django_db
def test_a_clinician_cannot_edit_the_catalogue(as_doctor, imaging_catalogue):
    """Ordering a scan and defining what scans exist are different jobs."""
    response = as_doctor.post(
        reverse("imagingprocedure-list"),
        {"modality": imaging_catalogue["xray"].pk, "name": "Made up",
         "code_short": "FAKE", "body_part": "Nowhere"},
        format="json",
    )
    assert response.status_code == 403
    assert not ImagingProcedure.objects.filter(code_short="FAKE").exists()


# --- ordering -----------------------------------------------------------------

@pytest.mark.django_db
def test_an_order_records_the_clinician_and_the_clinical_question(
    cxr_order, doctor, open_visit
):
    """AC-95."""
    assert cxr_order["order_number"].startswith("IMG")
    assert cxr_order["ordered_by"] == doctor.pk
    assert cxr_order["ordered_by_name"] == "Chukwuma Nwosu"
    assert cxr_order["clinical_question"] == (
        "Pneumothorax after central line insertion?"
    )
    assert cxr_order["priority"] == "urgent"
    assert cxr_order["items"][0]["status"] == "requested"
    assert cxr_order["items"][0]["procedure_code"] == "CXR"

    event = AuditEvent.objects.get(action="imaging.ordered")
    assert event.changes["after"]["procedures"] == ["CXR"]
    assert "Pneumothorax" in event.changes["after"]["clinical_question"]


@pytest.mark.django_db
def test_an_order_with_no_clinical_question_is_refused(
    as_doctor, open_visit, imaging_catalogue
):
    """AC-95 (negative).

    A radiologist reporting "CT abdomen" with no idea what is being looked for
    produces a description rather than an answer.
    """
    response = as_doctor.post(
        reverse("imagingorder-list"),
        {"visit": open_visit.pk, "clinical_question": "   ",
         "procedures": [imaging_catalogue["cxr"].pk]},
        format="json",
    )
    assert response.status_code == 400
    assert "answering" in str(response.data) or "question" in str(response.data)
    assert not ImagingOrder.objects.exists()


@pytest.mark.django_db
def test_the_preparation_instructions_reach_the_ward_with_the_order(
    as_ward_doctor, admission, imaging_catalogue
):
    """AC-94. "Nil by mouth for six hours" arriving late is a cancelled slot and
    a patient who fasted for nothing."""
    response = as_ward_doctor.post(
        reverse("imagingorder-list"),
        {"admission": admission.pk,
         "clinical_question": "Source of sepsis?",
         "procedures": [imaging_catalogue["ct_abdomen"].pk]},
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["admission"] == admission.pk
    assert response.data["visit"] is None
    assert "Nil by mouth for 6 hours" in response.data["preparation"][0]["instructions"]
    assert "Nil by mouth" in response.data["items"][0]["preparation_instructions"]


@pytest.mark.django_db
def test_the_same_procedure_cannot_be_ordered_twice_on_one_request(
    as_doctor, open_visit, imaging_catalogue
):
    """One line per examination: two identical lines would be billed twice and
    reported once."""
    response = as_doctor.post(
        reverse("imagingorder-list"),
        {"visit": open_visit.pk, "clinical_question": "Consolidation?",
         "procedures": [imaging_catalogue["cxr"].pk, imaging_catalogue["cxr"].pk]},
        format="json",
    )
    assert response.status_code == 201, response.data
    assert len(response.data["items"]) == 1


# --- the state machine --------------------------------------------------------

@pytest.mark.django_db
def test_the_states_advance_in_sequence(
    as_radiographer, as_radiologist, cxr_order, imaging_catalogue
):
    """AC-95. requested → scheduled → performed → reported → verified."""
    item = cxr_order["items"][0]["id"]

    when = timezone.now() + timedelta(hours=1)
    scheduled = as_radiographer.post(
        reverse("imagingorderitem-schedule", args=[item]),
        {"scheduled_for": when.isoformat()}, format="json",
    )
    assert scheduled.status_code == 200, scheduled.data
    assert scheduled.data["status"] == "scheduled"
    assert scheduled.data["allowed_transitions"] == ["cancelled", "performed"]

    performed = as_radiographer.post(
        reverse("imagingorderitem-perform", args=[item]),
        {"accession_number": "ACC-000123", "views_taken": "PA erect"},
        format="json",
    )
    assert performed.status_code == 200, performed.data
    assert performed.data["status"] == "performed"
    assert performed.data["performed_by_name"] == "Yemi Radiographer"
    assert performed.data["accession_number"] == "ACC-000123"
    assert performed.data["performed_at"] is not None

    reported = as_radiologist.post(
        reverse("imagingorderitem-report", args=[item]),
        {"findings": "Lung fields clear. No pneumothorax. Line tip in SVC.",
         "conclusion": "No pneumothorax. Central line correctly sited."},
        format="json",
    )
    assert reported.status_code == 201, reported.data
    assert reported.data["is_verified"] is False
    assert reported.data["status_label"] == "PROVISIONAL — not yet verified"

    verified = as_radiologist.post(
        reverse("imagingreport-verify", args=[reported.data["id"]])
    )
    assert verified.status_code == 200, verified.data
    assert verified.data["is_verified"] is True
    assert verified.data["verified_by_name"] == "Tayo Radiologist"
    assert verified.data["status_label"] == "Verified"

    assert ImagingOrderItem.objects.get(pk=item).status == "verified"
    assert [
        event.action for event in AuditEvent.objects.filter(
            action__startswith="imaging."
        ).order_by("id")
    ] == ["imaging.ordered", "imaging.scheduled", "imaging.performed",
          "imaging.reported", "imaging.verified"]


@pytest.mark.django_db
def test_a_state_cannot_be_skipped(as_radiologist, cxr_order):
    """AC-95 (negative).

    A study cannot be reported before it was performed — "performed" is what the
    department bills and what the patient was exposed to.
    """
    item = cxr_order["items"][0]["id"]
    response = as_radiologist.post(
        reverse("imagingorderitem-report", args=[item]),
        {"findings": "Clear", "conclusion": "Normal"}, format="json",
    )
    assert response.status_code == 409
    assert "cannot go from" in str(response.data)
    assert not ImagingReport.objects.exists()
    assert AuditEvent.objects.filter(
        action="imaging.transition_refused", outcome=AuditEvent.DENIED
    ).exists()


@pytest.mark.django_db
def test_a_radiographer_cannot_report_and_a_radiologist_can(
    as_radiographer, as_radiologist, cxr_order
):
    """Taking the picture and reading it are different jobs."""
    item = cxr_order["items"][0]["id"]
    as_radiographer.post(
        reverse("imagingorderitem-perform", args=[item]),
        {"accession_number": "ACC-1"}, format="json",
    )
    refused = as_radiographer.post(
        reverse("imagingorderitem-report", args=[item]),
        {"findings": "Looks fine to me", "conclusion": "Normal"}, format="json",
    )
    assert refused.status_code == 403
    assert not ImagingReport.objects.exists()


@pytest.mark.django_db
def test_performing_an_examination_charges_for_it(
    as_radiographer, cxr_order, imaging_catalogue, facility_a, open_visit
):
    """The charge is raised at performing, not at ordering: a request that is
    never performed must not appear on a bill."""
    item = cxr_order["items"][0]["id"]
    as_radiographer.post(
        reverse("imagingorderitem-perform", args=[item]),
        {"accession_number": "ACC-2"}, format="json",
    )
    invoice = Invoice.objects.get(visit=open_visit)
    line = invoice.items.get(source_type="imaging.ImagingOrderItem")
    assert line.unit_price == imaging_catalogue["cxr"].price_at(facility_a)
    assert "Chest X-ray" in line.description

    # Idempotent, like every other charge.
    as_radiographer.post(
        reverse("imagingorderitem-perform", args=[item]),
        {"accession_number": "ACC-2"}, format="json",
    )
    assert invoice.items.filter(source_type="imaging.ImagingOrderItem").count() == 1


@pytest.mark.django_db
def test_a_cancelled_examination_says_why(as_radiographer, cxr_order):
    item = cxr_order["items"][0]["id"]
    blank = as_radiographer.post(
        reverse("imagingorderitem-cancel", args=[item]), {"reason": ""}, format="json"
    )
    assert blank.status_code == 400

    cancelled = as_radiographer.post(
        reverse("imagingorderitem-cancel", args=[item]),
        {"reason": "Patient discharged before the slot"}, format="json",
    )
    assert cancelled.status_code == 200
    assert cancelled.data["status"] == "cancelled"
    assert cancelled.data["allowed_transitions"] == []


# --- AC-96: an unverified report reaches nobody --------------------------------

@pytest.fixture
def unverified_report(as_radiographer, as_imaging_registrar, cxr_order):
    """A written but unsigned report, by someone who cannot sign it."""
    item = cxr_order["items"][0]["id"]
    as_radiographer.post(
        reverse("imagingorderitem-perform", args=[item]),
        {"accession_number": "ACC-U1"}, format="json",
    )
    written = as_imaging_registrar.post(
        reverse("imagingorderitem-report", args=[item]),
        {"findings": "Small apical pneumothorax, approximately 15%.",
         "conclusion": "Small right apical pneumothorax."},
        format="json",
    )
    assert written.status_code == 201, written.data
    return {"item": item, "report": written.data["id"], "order": cxr_order["id"]}


@pytest.mark.django_db
def test_a_registrar_can_write_a_report_but_not_release_it(
    as_imaging_registrar, unverified_report
):
    """AC-96 (negative). Typing a report and standing behind it are different
    acts — the same separation the laboratory makes."""
    response = as_imaging_registrar.post(
        reverse("imagingreport-verify", args=[unverified_report["report"]])
    )
    assert response.status_code == 403
    assert ImagingReport.objects.get(pk=unverified_report["report"]).is_verified is False


@pytest.mark.django_db
def test_an_unverified_report_does_not_reach_the_requesting_clinician(
    as_doctor, unverified_report
):
    """AC-96 (negative) — the criterion itself.

    The clinician is told a report exists and has not been released. They are
    not shown a provisional conclusion, because a clinician who reads
    "pneumothorax" acts on it.
    """
    order = as_doctor.get(
        reverse("imagingorder-detail", args=[unverified_report["order"]])
    )
    assert order.status_code == 200
    report = order.data["items"][0]["report"]
    assert report is not None
    assert report["awaiting_verification"] is True
    assert report["is_verified"] is False
    # The report's own text is not there at all. Asserted on the radiologist's
    # words rather than on "pneumothorax", which is in the clinical question the
    # requesting clinician wrote themselves and should of course still see.
    assert "conclusion" not in report
    assert "findings" not in report
    assert "apical" not in str(order.data).lower()
    assert "15%" not in str(order.data)

    direct = as_doctor.get(
        reverse("imagingreport-detail", args=[unverified_report["report"]])
    )
    assert direct.status_code == 404
    assert direct.data["awaiting_verification"] is True

    # And nothing has been sent to them.
    assert not Notification.objects.filter(
        resource_type="imaging.ImagingReport"
    ).exists()


@pytest.mark.django_db
def test_the_department_can_read_its_own_draft(as_radiologist, unverified_report):
    """The person about to sign it off has to be able to read it. Hiding a draft
    from the department would be theatre."""
    order = as_radiologist.get(
        reverse("imagingorder-detail", args=[unverified_report["order"]])
    )
    report = order.data["items"][0]["report"]
    assert report["conclusion"] == "Small right apical pneumothorax."
    assert report["status_label"] == "PROVISIONAL — not yet verified"


@pytest.mark.django_db
def test_verifying_releases_the_report_and_notifies_the_requester(
    as_radiologist, as_doctor, unverified_report, doctor
):
    """AC-96."""
    verified = as_radiologist.post(
        reverse("imagingreport-verify", args=[unverified_report["report"]])
    )
    assert verified.status_code == 200, verified.data

    order = as_doctor.get(
        reverse("imagingorder-detail", args=[unverified_report["order"]])
    )
    report = order.data["items"][0]["report"]
    assert report["conclusion"] == "Small right apical pneumothorax."
    assert report["is_verified"] is True

    notification = Notification.objects.get(resource_type="imaging.ImagingReport")
    assert notification.recipient == doctor
    assert "Chest X-ray" in notification.subject


@pytest.mark.django_db
def test_a_report_needs_both_findings_and_a_conclusion(as_radiologist, cxr_order):
    """AC-96. The conclusion is what a clinician acts on; burying it in a
    paragraph of findings is how it gets missed."""
    item = cxr_order["items"][0]["id"]
    perform(
        order_item=ImagingOrderItem.objects.get(pk=item),
        actor=ImagingOrderItem.objects.get(pk=item).order.ordered_by,
    )
    for payload in (
        {"findings": "Clear", "conclusion": "  "},
        {"findings": "  ", "conclusion": "Normal"},
    ):
        response = as_radiologist.post(
            reverse("imagingorderitem-report", args=[item]), payload, format="json"
        )
        assert response.status_code == 400, payload
    assert not ImagingReport.objects.exists()


# --- AC-97: amendment ---------------------------------------------------------

@pytest.fixture
def verified_report(as_radiographer, as_radiologist, cxr_order):
    item = cxr_order["items"][0]["id"]
    as_radiographer.post(
        reverse("imagingorderitem-perform", args=[item]),
        {"accession_number": "ACC-V1", "views_taken": "PA erect"}, format="json",
    )
    written = as_radiologist.post(
        reverse("imagingorderitem-report", args=[item]),
        {"findings": "No fracture identified. Soft tissues normal.",
         "conclusion": "No fracture."},
        format="json",
    )
    as_radiologist.post(reverse("imagingreport-verify", args=[written.data["id"]]))
    return {"item": item, "report": written.data["id"], "order": cxr_order["id"]}


@pytest.mark.django_db
def test_amending_appends_a_version_and_the_original_stays(
    as_radiologist, as_doctor, verified_report
):
    """AC-97.

    Correcting "no fracture" to "undisplaced fracture" must not erase the first
    report: somebody made a decision on it, and that decision is only
    explicable against what it said.
    """
    amended = as_radiologist.post(
        reverse("imagingreport-amend", args=[verified_report["report"]]),
        {"reason": "Undisplaced fracture visible on review with the prior film",
         "findings": "Undisplaced fracture of the distal radius. Soft tissues normal.",
         "conclusion": "Undisplaced distal radial fracture."},
        format="json",
    )
    assert amended.status_code == 201, amended.data
    assert amended.data["version"] == 2
    assert amended.data["is_amended"] is True
    assert amended.data["status_label"] == "AMENDED (version 2)"
    assert amended.data["amends"] == verified_report["report"]
    # Released in the same act: leaving it provisional would mean the clinician
    # keeps reading the version now known to be wrong.
    assert amended.data["is_verified"] is True

    # The original, word for word.
    original = ImagingReport.objects.get(pk=verified_report["report"])
    assert original.conclusion == "No fracture."
    assert original.is_current is False

    order = as_doctor.get(
        reverse("imagingorder-detail", args=[verified_report["order"]])
    )
    item = order.data["items"][0]
    assert item["report"]["conclusion"] == "Undisplaced distal radial fracture."
    assert len(item["report_history"]) == 1
    assert item["report_history"][0]["conclusion"] == "No fracture."
    assert item["report_history"][0]["version"] == 1

    event = AuditEvent.objects.get(action="imaging.report_amended")
    assert event.changes["before"]["conclusion"] == "No fracture."
    assert "Undisplaced" in event.changes["after"]["conclusion"]
    assert "prior film" in event.reason

    # The requester is told, urgently, that what they read has changed.
    amendment_notice = Notification.objects.filter(
        subject__startswith="AMENDED report"
    ).get()
    assert amendment_notice.urgency == Notification.URGENT
    assert "prior film" in amendment_notice.body


@pytest.mark.django_db
def test_an_amendment_without_a_reason_is_refused(as_radiologist, verified_report):
    """AC-97 (negative)."""
    response = as_radiologist.post(
        reverse("imagingreport-amend", args=[verified_report["report"]]),
        {"reason": "   ", "conclusion": "Something else"}, format="json",
    )
    assert response.status_code == 400
    assert ImagingReport.objects.count() == 1
    assert ImagingReport.objects.get().conclusion == "No fracture."


@pytest.mark.django_db
def test_an_unverified_report_is_corrected_not_amended(
    as_radiologist, unverified_report
):
    """AC-97. There is nothing to amend until it has been released — an
    amendment trail on a draft would be noise."""
    response = as_radiologist.post(
        reverse("imagingreport-amend", args=[unverified_report["report"]]),
        {"reason": "typo", "conclusion": "Fixed"}, format="json",
    )
    assert response.status_code == 400
    assert "not verified" in str(response.data)


@pytest.mark.django_db
def test_a_superseded_report_cannot_be_amended_again(as_radiologist, verified_report):
    """Corrections form a chain: the current version is the one to amend."""
    first = as_radiologist.post(
        reverse("imagingreport-amend", args=[verified_report["report"]]),
        {"reason": "first correction", "conclusion": "Version two"}, format="json",
    )
    assert first.status_code == 201
    again = as_radiologist.post(
        reverse("imagingreport-amend", args=[verified_report["report"]]),
        {"reason": "second attempt on the old one", "conclusion": "Version three"},
        format="json",
    )
    assert again.status_code == 400
    assert "superseded" in str(again.data)


@pytest.mark.django_db
def test_only_one_report_is_current_at_a_time(verified_report):
    """Enforced by a partial unique constraint, not by convention."""
    current = ImagingReport.objects.get(pk=verified_report["report"])
    with pytest.raises(IntegrityError):
        ImagingReport.objects.create(
            order_item=current.order_item, findings="x", conclusion="y",
            version=99, is_current=True, amendment_reason="second current",
            reported_by=current.reported_by,
        )


# --- AC-98: critical findings --------------------------------------------------

@pytest.fixture
def critical_report(as_radiographer, as_radiologist, cxr_order):
    item = cxr_order["items"][0]["id"]
    as_radiographer.post(
        reverse("imagingorderitem-perform", args=[item]),
        {"accession_number": "ACC-C1"}, format="json",
    )
    written = as_radiologist.post(
        reverse("imagingorderitem-report", args=[item]),
        {"findings": "Large right tension pneumothorax with mediastinal shift.",
         "conclusion": "Tension pneumothorax. Requires immediate decompression.",
         "is_critical": True,
         "critical_finding": "Tension pneumothorax — decompress now"},
        format="json",
    )
    assert written.status_code == 201, written.data
    verified = as_radiologist.post(
        reverse("imagingreport-verify", args=[written.data["id"]])
    )
    assert verified.status_code == 200, verified.data
    return {"item": item, "report": written.data["id"], "order": cxr_order["id"]}


@pytest.mark.django_db
def test_a_critical_finding_must_say_what_has_to_be_acted_on(
    as_radiographer, as_radiologist, cxr_order
):
    """AC-98 (negative). "Critical" with no line saying why is a flag, not a
    finding somebody can act on."""
    item = cxr_order["items"][0]["id"]
    as_radiographer.post(
        reverse("imagingorderitem-perform", args=[item]),
        {"accession_number": "ACC-C0"}, format="json",
    )
    response = as_radiologist.post(
        reverse("imagingorderitem-report", args=[item]),
        {"findings": "Something alarming", "conclusion": "Alarming",
         "is_critical": True, "critical_finding": ""},
        format="json",
    )
    assert response.status_code == 400
    assert "one line" in str(response.data)
    assert not ImagingReport.objects.exists()


@pytest.mark.django_db
def test_a_critical_finding_stays_on_a_list_until_someone_answers_for_it(
    as_radiologist, as_doctor, critical_report, doctor
):
    """AC-98 — the same acknowledgement requirement as a critical laboratory
    result. A critical finding nobody acted on is the classic radiology harm."""
    outstanding = as_radiologist.get(reverse("imagingorder-critical"))
    assert outstanding.status_code == 200, outstanding.data
    assert [row["report"] for row in outstanding.data] == [critical_report["report"]]
    assert outstanding.data[0]["finding"] == "Tension pneumothorax — decompress now"
    assert outstanding.data[0]["requesting_clinician"] == "Chukwuma Nwosu"

    report = ImagingReport.objects.get(pk=critical_report["report"])
    assert report.needs_acknowledgement is True

    # The requesting clinician was told, as a critical notification.
    notification = Notification.objects.get(resource_type="imaging.ImagingReport")
    assert notification.kind == Notification.CRITICAL_RESULT
    assert notification.urgency == Notification.URGENT
    assert "Tension pneumothorax" in notification.body

    # An acknowledgement with no action recorded is a tick box, not a record.
    blank = as_doctor.post(
        reverse("imagingreport-acknowledge", args=[critical_report["report"]]),
        {"action_taken": "   "}, format="json",
    )
    assert blank.status_code == 400

    acknowledged = as_doctor.post(
        reverse("imagingreport-acknowledge", args=[critical_report["report"]]),
        {"action_taken": "Needle decompression at the bedside, chest drain sited, "
                         "repeat film requested."},
        format="json",
    )
    assert acknowledged.status_code == 201, acknowledged.data
    assert acknowledged.data["needs_acknowledgement"] is False
    assert acknowledged.data["acknowledgements"][0]["acknowledged_by_name"] == (
        "Chukwuma Nwosu"
    )
    assert acknowledged.data["acknowledgements"][0]["minutes_to_acknowledge"] >= 0

    assert list(unacknowledged_critical_findings()) == []
    cleared = as_radiologist.get(reverse("imagingorder-critical"))
    assert cleared.data == []

    event = AuditEvent.objects.get(action="imaging.critical_finding_acknowledged")
    assert "chest drain" in event.reason
    assert AuditEvent.objects.filter(
        action="imaging.critical_finding_flagged"
    ).exists()


@pytest.mark.django_db
def test_an_unverified_critical_report_is_not_on_the_chase_list(
    as_radiologist, unverified_report
):
    """A draft is not a finding. Chasing an unreleased report would have the
    department chasing itself."""
    report = ImagingReport.objects.get(pk=unverified_report["report"])
    report.is_critical = True
    report.critical_finding = "Not released yet"
    report.save(update_fields=["is_critical", "critical_finding"])
    assert report.needs_acknowledgement is False
    assert list(unacknowledged_critical_findings()) == []


@pytest.mark.django_db
def test_a_nurse_cannot_acknowledge_a_critical_finding(as_nurse, critical_report):
    """AC-98 (negative). Acknowledging means "I have acted on this", which needs
    someone who can."""
    response = as_nurse.post(
        reverse("imagingreport-acknowledge", args=[critical_report["report"]]),
        {"action_taken": "Told the doctor"}, format="json",
    )
    assert response.status_code == 403
    assert ImagingReport.objects.get(
        pk=critical_report["report"]
    ).needs_acknowledgement is True


# --- facility isolation -------------------------------------------------------

@pytest.mark.django_db
def test_an_order_at_another_facility_is_not_found(
    as_radiologist, facility_b, organization, hospital_numbers, imaging_catalogue,
    visit_numbers
):
    """404, not 403 — "no such order" and "an order you may not see" have to be
    indistinguishable across facilities."""
    from accounts.models import User
    from patients.models import Patient
    from visits.models import Visit

    patient = Patient.objects.create(
        given_name="Elsewhere", family_name="Patient", sex="male", facility=facility_b
    )
    visit = Visit.objects.create(patient=patient, facility=facility_b)
    order = ImagingOrder.objects.create(
        visit=visit, patient=patient, facility=facility_b,
        ordered_by=User.objects.get(email="radiol@example.test"),
        clinical_question="Not yours",
    )
    ImagingOrderItem.objects.create(order=order, procedure=imaging_catalogue["cxr"])

    response = as_radiologist.get(reverse("imagingorder-detail", args=[order.pk]))
    assert response.status_code == 404
    listed = as_radiologist.get(reverse("imagingorder-list"))
    assert order.pk not in [row["id"] for row in listed.data["results"]]


# --- AC-93: on the patient's record alongside outpatient work -----------------

@pytest.mark.django_db
def test_inpatient_imaging_sits_beside_outpatient_imaging_on_the_record(
    as_ward_doctor, as_doctor, admission, open_visit, imaging_catalogue
):
    """AC-93.

    A patient's imaging history is one list. Splitting it by whether they
    happened to be an inpatient at the time would mean a clinician missing the
    scan from last month's admission.
    """
    outpatient = as_doctor.post(
        reverse("imagingorder-list"),
        {"visit": open_visit.pk, "clinical_question": "Cough for six weeks?",
         "procedures": [imaging_catalogue["cxr"].pk]},
        format="json",
    )
    assert outpatient.status_code == 201, outpatient.data

    inpatient = as_ward_doctor.post(
        reverse("imagingorder-list"),
        {"admission": admission.pk, "clinical_question": "Source of sepsis?",
         "procedures": [imaging_catalogue["usg"].pk]},
        format="json",
    )
    assert inpatient.status_code == 201, inpatient.data

    both = as_ward_doctor.get(
        reverse("imagingorder-list"), {"patient": admission.patient_id}
    )
    assert both.status_code == 200
    rows = {row["id"]: row for row in both.data["results"]}
    assert set(rows) == {outpatient.data["id"], inpatient.data["id"]}
    assert rows[inpatient.data["id"]]["admission"] == admission.pk
    assert rows[outpatient.data["id"]]["visit"] == open_visit.pk

    # And each is still reachable by its own episode.
    by_admission = as_ward_doctor.get(
        reverse("imagingorder-list"), {"admission": admission.pk}
    )
    assert [row["id"] for row in by_admission.data["results"]] == [
        inpatient.data["id"]
    ]


@pytest.mark.django_db
def test_a_verified_report_reaches_the_discharge_summary(
    as_ward_doctor, as_radiographer, as_radiologist, as_cashier, cashier_session,
    finalise_invoice, admission, imaging_catalogue, ward_doctor, tariff
):
    """AC-93 and AC-102. Assembled from the record, not retyped — and only what
    the radiologist has stood behind."""
    from inpatient.services import discharge, discharge_summary

    ordered = as_ward_doctor.post(
        reverse("imagingorder-list"),
        {"admission": admission.pk, "clinical_question": "Free air?",
         "procedures": [imaging_catalogue["cxr"].pk, imaging_catalogue["usg"].pk]},
        format="json",
    )
    assert ordered.status_code == 201, ordered.data
    released, draft = ordered.data["items"][0]["id"], ordered.data["items"][1]["id"]

    for item in (released, draft):
        as_radiographer.post(
            reverse("imagingorderitem-perform", args=[item]),
            {"accession_number": f"ACC-DS-{item}"}, format="json",
        )
    signed = as_radiologist.post(
        reverse("imagingorderitem-report", args=[released]),
        {"findings": "No free subdiaphragmatic air.", "conclusion": "No perforation."},
        format="json",
    )
    as_radiologist.post(reverse("imagingreport-verify", args=[signed.data["id"]]))
    # The second is written but never released.
    as_radiologist.post(
        reverse("imagingorderitem-report", args=[draft]),
        {"findings": "Possible free fluid.", "conclusion": "Query free fluid."},
        format="json",
    )

    # The examination is charged to the admission, and the discharge gate holds
    # until it is settled — which is worth showing here rather than working
    # around, because it is the imaging charge that lands on the stay's bill.
    invoice = Invoice.objects.get(admission=admission, status=Invoice.DRAFT)
    assert invoice.items.filter(source_type="imaging.ImagingOrderItem").count() == 1
    finalise_invoice(invoice)
    paid = as_cashier.post(
        reverse("payment-list"),
        {"invoice": invoice.pk, "amount": str(invoice.total),
         "method": tariff["cash"].pk, "session": cashier_session["id"],
         "idempotency_key": f"imaging-summary-{invoice.pk}"},
        format="json",
    )
    assert paid.status_code == 201, paid.data

    discharge(admission=admission, actor=ward_doctor, diagnosis="Resolved",
              destination="home")
    summary = discharge_summary(admission)

    conclusions = [entry["conclusion"] for entry in summary["imaging"]]
    assert conclusions == ["No perforation."]
    # The unreleased one is absent, not shown as provisional.
    assert "free fluid" not in str(summary).lower()
    assert summary["imaging"][0]["amended"] is False
