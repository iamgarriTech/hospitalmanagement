"""AC-83 to AC-91 — the drug chart.

The gate for this phase is AC-84: every administration names who gave it and
when. The rest of the file is about the states where nothing reached the
patient, which is where a drug chart earns its keep.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.models import AuditEvent
from inpatient.models import MedicationAdministration, ScheduledDose, times_for
from inpatient.services import (
    chart,
    discontinue,
    older_overdue_count,
    overdue_doses,
    record_administration,
    schedule_doses,
)
from patients.models import PatientAllergy
from pharmacy.models import StockBatch


@pytest.mark.django_db
def test_a_prescription_generates_a_schedule_of_due_doses(drug_chart, inpatient_prescription):
    """AC-83. Three times a day for five days is fifteen doses, at the rounds the
    ward actually runs."""
    # Three a day for five days, from a fixed start: exactly fifteen.
    assert len(drug_chart) == 15

    hours = {dose.due_at.astimezone(timezone.get_current_timezone()).hour for dose in drug_chart}
    assert hours <= {8, 14, 20}
    # Dose and unit are copied, not read through the prescription.
    assert all(Decimal(dose.dose) == Decimal(inpatient_prescription.dose) for dose in drug_chart)
    assert all(dose.dose_unit == "mg" for dose in drug_chart)


@pytest.mark.django_db
def test_the_round_times_follow_the_frequency(inpatient_prescription):
    assert times_for(1) == [8]
    assert times_for(2) == [8, 20]
    assert times_for(3) == [8, 14, 20]
    assert times_for(4) == [6, 12, 18, 22]
    # Anything unusual is still spread across the day rather than refused.
    assert len(times_for(8)) == 8


@pytest.mark.django_db
def test_scheduling_twice_does_not_double_the_chart(
    inpatient_prescription, admission, ward_doctor
):
    """AC-83. A retry must not put two of every dose on the chart."""
    first = schedule_doses(
        prescription_item=inpatient_prescription, admission=admission, actor=ward_doctor
    )
    second = schedule_doses(
        prescription_item=inpatient_prescription, admission=admission, actor=ward_doctor
    )
    assert len(second) == 0
    assert ScheduledDose.objects.filter(
        prescription_item=inpatient_prescription
    ).count() == len(first)


@pytest.mark.django_db
def test_an_administration_names_who_gave_it_and_when(
    drug_chart, ward_nurse, formulary, admission
):
    """AC-84 — the gate."""
    dose = drug_chart[0]
    batch = formulary["batches"]["amoxicillin"]

    administration, created = record_administration(
        scheduled_dose=dose,
        state=MedicationAdministration.ADMINISTERED,
        actor=ward_nurse,
        batch=batch,
    )
    assert created is True
    assert administration.administered_by == ward_nurse
    assert administration.administered_at is not None
    assert administration.dose_given == Decimal(dose.dose)
    assert administration.batch == batch

    event = AuditEvent.objects.get(action="mar.administered")
    assert event.actor_email == "wardnurse@example.test"
    assert event.changes["after"]["batch"] == batch.batch_number
    assert event.patient_id == admission.patient_id


@pytest.mark.django_db(transaction=True)
def test_an_administration_without_a_nurse_cannot_exist(drug_chart, admission):
    """AC-84 (negative). Enforced by the column, not by a check that could be
    skipped: a dose with no named nurse is not an auditable record."""
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            MedicationAdministration.objects.create(
                scheduled_dose=drug_chart[0],
                admission=admission,
                patient=admission.patient,
                state=MedicationAdministration.ADMINISTERED,
                administered_at=timezone.now(),
                administered_by=None,
            )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "state",
    [
        MedicationAdministration.ADMINISTERED,
        MedicationAdministration.DELAYED,
        MedicationAdministration.MISSED,
        MedicationAdministration.REFUSED,
        MedicationAdministration.WITHHELD,
    ],
)
def test_the_full_state_set_is_supported(drug_chart, ward_nurse, formulary, state):
    """AC-85. Four of these mean the drug never reached the patient, and those
    are the entries a ward round actually asks about."""
    dose = drug_chart[0]
    needs_reason = state in MedicationAdministration.REQUIRE_REASON
    administration, _ = record_administration(
        scheduled_dose=dose,
        state=state,
        actor=ward_nurse,
        batch=formulary["batches"]["amoxicillin"]
        if state in MedicationAdministration.CONSUMES_STOCK else None,
        reason="Patient nil by mouth for theatre" if needs_reason else "",
    )
    assert administration.state == state
    if needs_reason:
        assert administration.reason
        assert administration.batch is None
        assert administration.administered_at is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "state",
    [
        MedicationAdministration.MISSED,
        MedicationAdministration.REFUSED,
        MedicationAdministration.WITHHELD,
    ],
)
def test_a_dose_that_did_not_reach_the_patient_must_say_why(drug_chart, ward_nurse, state):
    """AC-85 (negative). "Missed" with no explanation is a gap someone will
    later have to guess about."""
    with pytest.raises(ValidationError) as error:
        record_administration(
            scheduled_dose=drug_chart[0], state=state, actor=ward_nurse, reason="  "
        )
    assert "reason" in str(error.value).lower()
    assert not MedicationAdministration.objects.exists()


@pytest.mark.django_db
def test_a_dose_cannot_be_given_twice(drug_chart, ward_nurse, formulary):
    """AC-86 (negative). A double-tap or a retried request produces one
    administration — a duplicate dose is the error this model exists to stop."""
    dose = drug_chart[0]
    batch = formulary["batches"]["amoxicillin"]
    before = StockBatch.objects.get(pk=batch.pk).quantity_on_hand

    first, created_first = record_administration(
        scheduled_dose=dose, state=MedicationAdministration.ADMINISTERED,
        actor=ward_nurse, batch=batch,
    )
    second, created_second = record_administration(
        scheduled_dose=dose, state=MedicationAdministration.ADMINISTERED,
        actor=ward_nurse, batch=batch,
    )
    assert created_first is True
    assert created_second is False
    assert first.pk == second.pk
    assert MedicationAdministration.objects.filter(scheduled_dose=dose).count() == 1
    # And stock left the trolley exactly once.
    assert StockBatch.objects.get(pk=batch.pk).quantity_on_hand == before - 1


@pytest.mark.django_db(transaction=True)
def test_the_database_refuses_a_second_outcome_for_one_dose(
    drug_chart, ward_nurse, admission
):
    """AC-86 (negative), without going through the service."""
    dose = drug_chart[0]
    MedicationAdministration.objects.create(
        scheduled_dose=dose, admission=admission, patient=admission.patient,
        state=MedicationAdministration.MISSED, administered_by=ward_nurse,
        reason="ward busy",
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            MedicationAdministration.objects.create(
                scheduled_dose=dose, admission=admission, patient=admission.patient,
                state=MedicationAdministration.MISSED, administered_by=ward_nurse,
                reason="again",
            )


@pytest.mark.django_db
def test_giving_a_dose_takes_it_from_the_named_batch(drug_chart, ward_nurse, formulary):
    """AC-87."""
    batch = formulary["batches"]["amoxicillin"]
    before = batch.quantity_on_hand

    record_administration(
        scheduled_dose=drug_chart[0], state=MedicationAdministration.ADMINISTERED,
        actor=ward_nurse, batch=batch,
    )
    batch.refresh_from_db()
    assert batch.quantity_on_hand == before - 1

    from pharmacy.models import StockMovement

    movement = StockMovement.objects.filter(batch=batch).order_by("-id").first()
    assert movement.quantity_delta == -1
    assert "ADM/" in movement.reason


@pytest.mark.django_db
def test_an_expired_batch_is_refused_at_the_bedside(drug_chart, ward_nurse, formulary):
    """AC-87 (negative). Refused and recorded — it is a near miss, not a typo."""
    expired = formulary["batches"]["amoxicillin_expired"]
    with pytest.raises(ValidationError) as error:
        record_administration(
            scheduled_dose=drug_chart[0], state=MedicationAdministration.ADMINISTERED,
            actor=ward_nurse, batch=expired,
        )
    assert "expired" in str(error.value).lower()
    assert not MedicationAdministration.objects.exists()
    assert AuditEvent.objects.filter(action="mar.expired_batch_refused").exists()


@pytest.mark.django_db
def test_a_batch_of_the_wrong_drug_is_refused(drug_chart, ward_nurse, formulary):
    """(negative) The nurse is the last check, and the trolley holds more than
    one drug."""
    with pytest.raises(ValidationError) as error:
        record_administration(
            scheduled_dose=drug_chart[0], state=MedicationAdministration.ADMINISTERED,
            actor=ward_nurse, batch=formulary["batches"]["paracetamol"],
        )
    assert "Paracetamol" in str(error.value)


@pytest.mark.django_db
def test_the_allergy_check_runs_again_at_the_bedside(
    drug_chart, ward_nurse, formulary, admission
):
    """AC-88 (negative).

    The prescriber may have overridden it, the allergy may have been recorded
    since, or this may be the wrong patient's trolley. The nurse is the last
    check before the drug reaches the patient.
    """
    PatientAllergy.objects.create(
        patient=admission.patient, substance="Amoxicillin",
        reaction="Anaphylaxis", severity="severe",
    )
    batch = formulary["batches"]["amoxicillin"]

    with pytest.raises(ValidationError) as error:
        record_administration(
            scheduled_dose=drug_chart[0], state=MedicationAdministration.ADMINISTERED,
            actor=ward_nurse, batch=batch,
        )
    assert "allergic" in str(error.value).lower()
    assert not MedicationAdministration.objects.exists()

    administration, _ = record_administration(
        scheduled_dose=drug_chart[0], state=MedicationAdministration.ADMINISTERED,
        actor=ward_nurse, batch=batch,
        override_reason="Prescriber reviewed; documented reaction was a mild rash",
    )
    assert administration.override_reason.startswith("Prescriber reviewed")
    event = AuditEvent.objects.get(action="mar.administered")
    assert event.changes["after"]["overridden"] is True


@pytest.mark.django_db
def test_discontinuing_stops_future_doses_and_keeps_the_given_ones(
    drug_chart, ward_nurse, ward_doctor, formulary, inpatient_prescription
):
    """AC-89."""
    given, _ = record_administration(
        scheduled_dose=drug_chart[0], state=MedicationAdministration.ADMINISTERED,
        actor=ward_nurse, batch=formulary["batches"]["amoxicillin"],
    )
    remaining_before = ScheduledDose.objects.filter(
        prescription_item=inpatient_prescription, cancelled_at__isnull=True
    ).count()

    cancelled = discontinue(
        prescription_item=inpatient_prescription, actor=ward_doctor,
        reason="Rash developed; switching to a macrolide",
    )
    assert cancelled == remaining_before - 1  # the given dose is in the past

    # Nothing further is due. The dose already given is still future-dated and
    # deliberately not cancelled — it has an outcome, and the chart must keep
    # saying it reached the patient.
    assert not ScheduledDose.objects.filter(
        prescription_item=inpatient_prescription,
        due_at__gte=timezone.now(),
        cancelled_at__isnull=True,
        administrations__isnull=True,
    ).exists()
    assert given.scheduled_dose.status() == MedicationAdministration.ADMINISTERED
    # …and what was given is untouched.
    given.refresh_from_db()
    assert given.state == MedicationAdministration.ADMINISTERED
    assert MedicationAdministration.objects.filter(pk=given.pk).exists()

    event = AuditEvent.objects.get(action="mar.medication_discontinued")
    assert event.changes["after"]["doses_already_given"] == 1
    assert event.reason.startswith("Rash developed")


@pytest.mark.django_db
def test_a_discontinued_dose_cannot_then_be_given(
    drug_chart, ward_nurse, ward_doctor, inpatient_prescription, formulary
):
    """AC-89 (negative)."""
    discontinue(
        prescription_item=inpatient_prescription, actor=ward_doctor, reason="stopped",
    )
    future = ScheduledDose.objects.filter(
        prescription_item=inpatient_prescription, cancelled_at__isnull=False
    ).first()
    with pytest.raises(ValidationError) as error:
        record_administration(
            scheduled_dose=future, state=MedicationAdministration.ADMINISTERED,
            actor=ward_nurse, batch=formulary["batches"]["amoxicillin"],
        )
    assert "discontinued" in str(error.value).lower()


@pytest.mark.django_db
def test_the_chart_reads_as_a_chart(drug_chart, ward_nurse, formulary, admission):
    """AC-90. Rows are medications, columns are due times, and each cell says
    its state in words."""
    record_administration(
        scheduled_dose=drug_chart[0], state=MedicationAdministration.ADMINISTERED,
        actor=ward_nurse, batch=formulary["batches"]["amoxicillin"],
    )
    record_administration(
        scheduled_dose=drug_chart[1], state=MedicationAdministration.REFUSED,
        actor=ward_nurse, reason="Patient declined",
    )

    board = chart(admission=admission)
    assert len(board["rows"]) == 1
    row = board["rows"][0]
    assert row["medication"].startswith("Amoxicillin")
    assert "3 times a day" in row["directions"]
    assert len(board["columns"]) == len(drug_chart)

    cells = [row["cells"][dose.due_at.isoformat()] for dose in drug_chart[:3]]
    assert cells[0]["status"] == MedicationAdministration.ADMINISTERED
    assert cells[0]["state_label"] == "Administered"
    assert cells[0]["by"] == "Amaka Nurse"
    assert cells[1]["status"] == MedicationAdministration.REFUSED
    assert cells[1]["reason"] == "Patient declined"
    # Every cell carries words, not only a colour.
    assert all(cell["state_label"] for cell in cells)


@pytest.mark.django_db
def test_a_dose_nobody_recorded_shows_as_overdue_and_appears_on_a_list(
    admission, inpatient_prescription, ward_doctor, ward
):
    """AC-91. A dose with no outcome is indistinguishable from a dose nobody
    gave, so it has to be surfaced rather than sit quietly on a chart."""
    def missed(hours_ago, sequence):
        return ScheduledDose.objects.create(
            prescription_item=inpatient_prescription, admission=admission,
            patient=admission.patient,
            due_at=timezone.now() - timedelta(hours=hours_ago), sequence=sequence,
            dose=inpatient_prescription.dose, dose_unit="mg", route="oral",
        )

    this_shift = missed(4, 1)
    last_week = missed(24 * 6, 2)
    assert this_shift.status() == "overdue"
    assert last_week.status() == "overdue"

    # The ward list is this shift's work, not a week of it.
    listed = list(overdue_doses(ward=ward))
    assert this_shift in listed
    assert last_week not in listed
    assert list(overdue_doses(facility=admission.facility)) == [this_shift]

    # The older one is counted, never dropped: a dose that stops appearing is a
    # dose nobody will account for.
    assert older_overdue_count(ward=ward) == 1

    # And the whole backlog is still reachable for reconciliation.
    everything = list(overdue_doses(ward=ward, lookback_hours=None))
    assert set(everything) == {this_shift, last_week}


@pytest.mark.django_db
def test_a_dose_not_yet_due_is_not_overdue(drug_chart):
    future = [dose for dose in drug_chart if dose.due_at > timezone.now()]
    assert future, "expected at least one future dose on a five-day course"
    assert future[-1].status() == "scheduled"


# --- the chart over HTTP ------------------------------------------------------

@pytest.mark.django_db
def test_the_chart_endpoint_returns_a_grid_with_words_in_every_cell(
    as_ward_nurse, drug_chart, admission, formulary, ward_nurse
):
    """AC-90 over the API. A colour is never the only cue."""
    from django.urls import reverse

    batch = formulary["batches"]["amoxicillin"]
    given = as_ward_nurse.post(
        reverse("scheduleddose-record", args=[drug_chart[0].pk]),
        {"state": "administered", "batch": batch.pk}, format="json",
    )
    assert given.status_code == 201, given.data
    assert given.data["administered_by_name"] == "Amaka Nurse"
    assert given.data["batch_number"] == batch.batch_number

    refused = as_ward_nurse.post(
        reverse("scheduleddose-record", args=[drug_chart[1].pk]),
        {"state": "refused", "reason": "Patient declined, felt nauseated"},
        format="json",
    )
    assert refused.status_code == 201, refused.data

    board = as_ward_nurse.get(
        reverse("scheduleddose-chart"), {"admission": admission.pk, "days": 7}
    )
    assert board.status_code == 200, board.data
    assert len(board.data["rows"]) == 1
    row = board.data["rows"][0]
    assert "500 mg oral, 3 times a day" in row["directions"]

    cells = [row["cells"][dose.due_at.isoformat()] for dose in drug_chart[:3]]
    assert [cell["status"] for cell in cells] == ["administered", "refused", "scheduled"]
    assert [cell["state_label"] for cell in cells] == [
        "Administered", "Refused by patient", "Not yet due"
    ]
    assert cells[0]["by"] == "Amaka Nurse"
    assert cells[1]["reason"] == "Patient declined, felt nauseated"


@pytest.mark.django_db
def test_a_repeated_record_request_returns_the_first_outcome(
    as_ward_nurse, drug_chart, formulary
):
    """AC-86 over the API. A double-tapped button is one dose, not two."""
    from django.urls import reverse

    url = reverse("scheduleddose-record", args=[drug_chart[0].pk])
    payload = {"state": "administered", "batch": formulary["batches"]["amoxicillin"].pk}

    first = as_ward_nurse.post(url, payload, format="json")
    second = as_ward_nurse.post(url, payload, format="json")

    assert first.status_code == 201
    # 200, not 201: nothing new was created, and the caller gets the outcome
    # that stands rather than an error it has to interpret.
    assert second.status_code == 200
    assert second.data["id"] == first.data["id"]
    assert MedicationAdministration.objects.filter(
        scheduled_dose=drug_chart[0]
    ).count() == 1


@pytest.mark.django_db
def test_the_api_refuses_a_state_change_with_no_reason(as_ward_nurse, drug_chart):
    """AC-85 over the API, before the request reaches the service."""
    from django.urls import reverse

    for state in ["missed", "refused", "withheld", "discontinued"]:
        response = as_ward_nurse.post(
            reverse("scheduleddose-record", args=[drug_chart[0].pk]),
            {"state": state}, format="json",
        )
        assert response.status_code == 400, state
        assert "why" in str(response.data).lower()
    assert not MedicationAdministration.objects.exists()


@pytest.mark.django_db
def test_the_bedside_warning_endpoint_reports_an_allergy(
    as_ward_nurse, drug_chart, admission, formulary
):
    """AC-88. Checked again at the bedside — this may be the wrong trolley."""
    from django.urls import reverse

    PatientAllergy.objects.create(
        patient=admission.patient, substance="Amoxicillin",
        reaction="Rash", severity="moderate", recorded_by=admission.admitted_by,
    )
    response = as_ward_nurse.get(
        reverse("scheduleddose-warnings", args=[drug_chart[0].pk])
    )
    assert response.status_code == 200, response.data
    assert response.data["warnings"], "expected an allergy warning at the bedside"
    assert "Amoxicillin" in str(response.data["warnings"])

    blocked = as_ward_nurse.post(
        reverse("scheduleddose-record", args=[drug_chart[0].pk]),
        {"state": "administered", "batch": formulary["batches"]["amoxicillin"].pk},
        format="json",
    )
    assert blocked.status_code == 400
    assert "override_reason" in str(blocked.data)

    proceeded = as_ward_nurse.post(
        reverse("scheduleddose-record", args=[drug_chart[0].pk]),
        {"state": "administered", "batch": formulary["batches"]["amoxicillin"].pk,
         "override_reason": "Documented mild rash only; prescriber aware, "
                            "first dose tolerated"},
        format="json",
    )
    assert proceeded.status_code == 201, proceeded.data
    assert "prescriber aware" in proceeded.data["override_reason"]
    assert AuditEvent.objects.filter(action="mar.administered").exists()


@pytest.mark.django_db
def test_a_nurse_cannot_stop_a_course(as_ward_nurse, inpatient_prescription, drug_chart):
    """AC-89 (negative). Giving a drug and deciding to stop it are different
    jobs, and the nurse who gives it does not hold the second."""
    from django.urls import reverse

    response = as_ward_nurse.post(
        reverse("scheduleddose-discontinue"),
        {"prescription_item": inpatient_prescription.pk,
         "reason": "Rash developed"},
        format="json",
    )
    assert response.status_code == 403
    assert ScheduledDose.objects.filter(cancelled_at__isnull=False).count() == 0


@pytest.mark.django_db
def test_a_doctor_stops_a_course_and_the_given_doses_remain(
    as_ward_doctor, as_ward_nurse, inpatient_prescription, drug_chart, formulary
):
    """AC-89. A discontinuation that erased the history would hide the fact that
    the drug ever reached the patient."""
    from django.urls import reverse

    given = as_ward_nurse.post(
        reverse("scheduleddose-record", args=[drug_chart[0].pk]),
        {"state": "administered", "batch": formulary["batches"]["amoxicillin"].pk},
        format="json",
    )
    assert given.status_code == 201, given.data

    stopped = as_ward_doctor.post(
        reverse("scheduleddose-discontinue"),
        {"prescription_item": inpatient_prescription.pk,
         "reason": "Widespread rash, switching to azithromycin"},
        format="json",
    )
    assert stopped.status_code == 200, stopped.data
    assert stopped.data["doses_already_given"] == 1
    assert stopped.data["future_doses_cancelled"] == len(drug_chart) - 1

    # The dose that reached the patient still reads as given, not discontinued.
    drug_chart[0].refresh_from_db()
    assert drug_chart[0].status() == "administered"
    assert drug_chart[0].cancelled_at is None


@pytest.mark.django_db
def test_the_overdue_list_is_scoped_to_what_the_caller_may_see(
    as_ward_nurse, admission, inpatient_prescription, ward
):
    """AC-91 over the API."""
    from django.urls import reverse

    ScheduledDose.objects.create(
        prescription_item=inpatient_prescription, admission=admission,
        patient=admission.patient, due_at=timezone.now() - timedelta(hours=3),
        sequence=1, dose=inpatient_prescription.dose, dose_unit="mg", route="oral",
    )
    response = as_ward_nurse.get(reverse("scheduleddose-overdue"), {"ward": ward.pk})
    assert response.status_code == 200, response.data
    assert len(response.data) == 1
    assert response.data[0]["status"] == "overdue"
    assert response.data[0]["minutes_overdue"] >= 180
    assert response.data[0]["patient_name"] == admission.patient.full_name
