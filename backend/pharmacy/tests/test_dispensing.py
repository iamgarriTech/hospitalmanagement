"""AC-37 to AC-41 — dispensing against real stock."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connections
from django.urls import reverse

from audit.models import AuditEvent
from pharmacy.models import (
    Dispense, PrescriptionItem, StockBatch, StockMovement, take_from_batch,
)


def dispense_url(item_id):
    return reverse("prescriptionitem-dispense", args=[item_id])


@pytest.mark.django_db
def test_dispensing_decrements_the_batch_and_records_which_one(
    as_pharmacist, amoxicillin_prescription, formulary
):
    """AC-37."""
    item_id = amoxicillin_prescription["items"][0]["id"]
    batch = formulary["batches"]["amoxicillin"]

    response = as_pharmacist.post(
        dispense_url(item_id), {"batch": batch.pk, "quantity": 15}, format="json"
    )
    assert response.status_code == 200, response.data
    assert response.data["status"] == PrescriptionItem.DISPENSED
    assert response.data["quantity_dispensed"] == 15
    assert response.data["quantity_outstanding"] == 0

    batch.refresh_from_db()
    assert batch.quantity_on_hand == 25  # 40 − 15

    issued = response.data["dispenses"][0]
    assert issued["batch_number"] == "AMX-2027A"
    assert issued["expiry_date"] == str(batch.expiry_date)
    assert issued["dispensed_by_email"] == "pharm@example.test"

    movement = StockMovement.objects.get(kind=StockMovement.DISPENSE)
    assert movement.quantity_delta == -15
    assert movement.quantity_after == 25
    assert movement.dispense is not None


@pytest.mark.django_db
def test_dispensing_an_expired_batch_is_refused(
    as_pharmacist, amoxicillin_prescription, formulary
):
    """AC-38 (negative). The refusal is audited: it is a near miss, not a typo."""
    item_id = amoxicillin_prescription["items"][0]["id"]
    expired = formulary["batches"]["amoxicillin_expired"]

    response = as_pharmacist.post(
        dispense_url(item_id), {"batch": expired.pk, "quantity": 5}, format="json"
    )
    assert response.status_code == 400
    assert "expired on" in response.data["batch"][0]

    expired.refresh_from_db()
    assert expired.quantity_on_hand == 100
    assert Dispense.objects.count() == 0
    assert AuditEvent.objects.filter(action="dispense.expired_batch_refused").exists()


@pytest.mark.django_db
def test_dispensing_the_wrong_drug_from_a_batch_is_refused(
    as_pharmacist, amoxicillin_prescription, formulary
):
    item_id = amoxicillin_prescription["items"][0]["id"]
    wrong = formulary["batches"]["paracetamol"]
    response = as_pharmacist.post(
        dispense_url(item_id), {"batch": wrong.pk, "quantity": 5}, format="json"
    )
    assert response.status_code == 400
    assert "Paracetamol, not Amoxicillin" in response.data["batch"][0]


@pytest.mark.django_db
def test_partial_dispensing_tracks_the_remainder(
    as_pharmacist, amoxicillin_prescription, formulary
):
    """AC-40."""
    item_id = amoxicillin_prescription["items"][0]["id"]
    batch = formulary["batches"]["amoxicillin"]

    first = as_pharmacist.post(
        dispense_url(item_id), {"batch": batch.pk, "quantity": 6}, format="json"
    )
    assert first.data["status"] == PrescriptionItem.PARTIALLY_DISPENSED
    assert first.data["quantity_outstanding"] == 9

    second = as_pharmacist.post(
        dispense_url(item_id), {"batch": batch.pk, "quantity": 9}, format="json"
    )
    assert second.data["status"] == PrescriptionItem.DISPENSED
    assert second.data["quantity_outstanding"] == 0
    assert len(second.data["dispenses"]) == 2

    batch.refresh_from_db()
    assert batch.quantity_on_hand == 25


@pytest.mark.django_db
def test_a_second_dispense_cannot_exceed_the_remainder(
    as_pharmacist, amoxicillin_prescription, formulary
):
    """AC-40 (negative)."""
    item_id = amoxicillin_prescription["items"][0]["id"]
    batch = formulary["batches"]["amoxicillin"]
    as_pharmacist.post(
        dispense_url(item_id), {"batch": batch.pk, "quantity": 10}, format="json"
    )

    too_many = as_pharmacist.post(
        dispense_url(item_id), {"batch": batch.pk, "quantity": 6}, format="json"
    )
    assert too_many.status_code == 409
    assert "Only 5 outstanding" in str(too_many.data)

    item = PrescriptionItem.objects.get(pk=item_id)
    assert item.quantity_dispensed == 10
    batch.refresh_from_db()
    assert batch.quantity_on_hand == 30


@pytest.mark.django_db(transaction=True)
def test_two_pharmacists_cannot_both_dispense_the_last_packet(
    pharmacist, facility_a, formulary
):
    """AC-39 — the whole reason dispensing uses a conditional UPDATE."""
    batch = StockBatch.objects.create(
        medication=formulary["amoxicillin"], facility=facility_a,
        batch_number="LAST-ONE", expiry_date=formulary["batches"]["amoxicillin"].expiry_date,
        quantity_on_hand=1,
    )

    def take(_):
        from django.core.exceptions import ValidationError

        try:
            take_from_batch(batch=batch, quantity=1, actor=pharmacist)
            return "dispensed"
        except ValidationError:
            return "refused"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(take, range(8)))

    assert outcomes.count("dispensed") == 1, outcomes
    batch.refresh_from_db()
    assert batch.quantity_on_hand == 0
    assert StockMovement.objects.filter(batch=batch).count() == 1


@pytest.mark.django_db
def test_stock_cannot_be_driven_negative_even_bypassing_the_application(
    facility_a, formulary
):
    """AC-39 (negative): the invariant lives in the database, not only in Python."""
    from django.db import IntegrityError, transaction

    batch = formulary["batches"]["amoxicillin"]
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            StockBatch.objects.filter(pk=batch.pk).update(quantity_on_hand=-1)


@pytest.mark.django_db
def test_dispensing_appears_in_the_patients_medication_history_and_audit(
    as_pharmacist, amoxicillin_prescription, formulary, patient
):
    """AC-41."""
    item_id = amoxicillin_prescription["items"][0]["id"]
    batch = formulary["batches"]["amoxicillin"]
    as_pharmacist.post(
        dispense_url(item_id), {"batch": batch.pk, "quantity": 15}, format="json"
    )

    history = as_pharmacist.get(
        reverse("prescription-history"), {"patient": patient.pk}
    ).data
    assert len(history) == 1
    assert history[0]["medication"].startswith("Amoxicillin 500 mg")
    assert history[0]["quantity"] == 15
    assert history[0]["batch_number"] == "AMX-2027A"
    assert history[0]["prescription_number"] == \
        amoxicillin_prescription["prescription_number"]

    event = AuditEvent.objects.get(action="medication.dispensed")
    assert event.patient_id == patient.pk
    assert event.changes["after"]["quantity"] == 15
    assert event.changes["after"]["batch"] == "AMX-2027A"
    assert event.changes["after"]["stock_after"] == 25


@pytest.mark.django_db
def test_dispensing_requires_the_dispense_permission(
    as_prescriber, amoxicillin_prescription, formulary
):
    """AC-37 (negative): prescribing is not dispensing."""
    item_id = amoxicillin_prescription["items"][0]["id"]
    batch = formulary["batches"]["amoxicillin"]
    response = as_prescriber.post(
        dispense_url(item_id), {"batch": batch.pk, "quantity": 5}, format="json"
    )
    assert response.status_code == 403
    batch.refresh_from_db()
    assert batch.quantity_on_hand == 40


@pytest.mark.django_db
def test_the_pharmacy_queue_shows_allergies_and_overridden_warnings(
    as_pharmacist, as_prescriber, open_visit, patient, formulary
):
    """The pharmacist must see that a prescriber overrode an allergy warning."""
    from patients.models import PatientAllergy

    PatientAllergy.objects.create(patient=patient, substance="Amoxicillin",
                                  reaction="Rash", severity="mild")
    as_prescriber.post(
        reverse("prescription-list"),
        {"visit": open_visit.pk, "items": [{
            "medication": formulary["amoxicillin"].pk, "dose": "500", "dose_unit": "mg",
            "route": "oral", "frequency_per_day": 3, "duration_days": 5,
            "quantity_prescribed": 15,
        }], "acknowledge_warnings": True,
         "override_reason": "Mild historical rash, discussed with patient"},
        format="json",
    )

    queue = as_pharmacist.get(reverse("prescription-queue")).data
    assert len(queue) == 1
    assert queue[0]["allergies"] == ["Amoxicillin"]
    assert queue[0]["items"][0]["overridden_warnings"] == ["allergy"]
    assert queue[0]["items"][0]["outstanding"] == 15
