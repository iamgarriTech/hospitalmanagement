"""AC-67 to AC-73 — beds, and the one thing that must never happen.

The exclusion constraint is the substance of this file. Two patients in one bed
is not a tidiness problem: it means a drug chart, an observation and a bed
number that all disagree about who is in front of you.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connections, transaction
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.utils import timezone

from inpatient.models import Admission, Bed, BedOccupancy, Room, Ward
from patients.models import Patient


@pytest.mark.django_db
def test_a_ward_can_be_built_without_touching_the_database(facility_a):
    """AC-67."""
    ward = Ward.objects.create(
        facility=facility_a, name="Paediatric Ward", code="PW",
        ward_type=Ward.PAEDIATRIC,
    )
    room = Room.objects.create(ward=ward, name="Cubicle 1", code="C1")
    Bed.objects.create(room=room, code="1")
    Bed.objects.create(room=room, code="2")

    assert ward.bed_count == 2
    assert ward.occupancy()["available"] == 2


@pytest.mark.django_db
def test_a_bed_reports_occupancy_rather_than_storing_it(admission, beds):
    """AC-68, AC-73.

    "Occupied" is derived from an open occupancy. A stored flag would be a
    second source of truth, and the way you discover it has drifted is by
    putting someone in an occupied bed.
    """
    occupied, empty = beds[0], beds[1]
    assert occupied.is_occupied is True
    assert occupied.state == Bed.OCCUPIED
    # The service state underneath is untouched — the bed is still "available"
    # for service purposes; it is a patient that makes it occupied.
    assert occupied.service_state == Bed.AVAILABLE
    assert empty.state == Bed.AVAILABLE

    counts = admission.facility.wards.first().occupancy()
    assert counts["beds"] == 4
    assert counts["occupied"] == 1


@pytest.mark.django_db(transaction=True)
def test_two_patients_cannot_occupy_one_bed_under_concurrency(
    facility_a, ward, beds, ward_doctor, hospital_numbers, inpatient_numbers
):
    """AC-69 — the gate for this phase.

    Twelve threads admit different patients to the same bed at the same instant.
    The database allows exactly one. This is not checked in Python anywhere: a
    read-then-write check would let two through under precisely this load.
    """
    bed = beds[0]
    patients = [
        Patient.objects.create(
            given_name=f"Patient{index}", family_name="Race", sex="male",
            facility=facility_a,
        )
        for index in range(12)
    ]
    admissions = [
        Admission.objects.create(
            patient=patient, facility=facility_a, admission_reason="race",
            admission_diagnosis="race", responsible_consultant=ward_doctor,
            admitted_by=ward_doctor,
        )
        for patient in patients
    ]

    def admit(record):
        try:
            with transaction.atomic():
                BedOccupancy.allocate(bed=bed, admission=record, actor=ward_doctor)
            return "allocated"
        except IntegrityError:
            return "refused"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=12) as pool:
        outcomes = list(pool.map(admit, admissions))

    assert outcomes.count("allocated") == 1, outcomes
    assert outcomes.count("refused") == 11
    assert BedOccupancy.objects.filter(bed=bed, period__endswith__isnull=True).count() == 1


@pytest.mark.django_db
def test_the_database_refuses_an_overlapping_occupancy_directly(admission, beds):
    """AC-69 (negative) — the guarantee does not depend on going through the
    application."""
    other = Patient.objects.create(
        given_name="Second", family_name="Patient", sex="male",
        facility=admission.facility,
    )
    second = Admission.objects.create(
        patient=other, facility=admission.facility, admission_reason="x",
        admission_diagnosis="x", responsible_consultant=admission.admitted_by,
        admitted_by=admission.admitted_by,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            BedOccupancy.objects.create(
                bed=beds[0], admission=second, patient=other,
                period=DateTimeTZRange(timezone.now(), None),
            )


@pytest.mark.django_db
def test_one_patient_cannot_be_in_two_beds(admission, beds):
    """(negative) The mirror of AC-69, and the reason a transfer must close the
    old occupancy in the same transaction as it opens the new one."""
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            BedOccupancy.objects.create(
                bed=beds[1], admission=admission, patient=admission.patient,
                period=DateTimeTZRange(timezone.now(), None),
            )


@pytest.mark.django_db
def test_a_bed_being_cleaned_or_repaired_cannot_take_a_patient(
    admission, beds, ward_doctor
):
    """AC-70 (negative). The refusal names the state, because "no" without a
    reason sends a nurse to find a different bed for the wrong reason."""
    for state, expected in [
        (Bed.CLEANING, "being cleaned"),
        (Bed.MAINTENANCE, "unavailable for maintenance"),
    ]:
        beds[1].set_service_state(state, note="mattress replaced")
        with pytest.raises(ValidationError) as error:
            BedOccupancy.allocate(bed=beds[1], admission=admission, actor=ward_doctor)
        assert expected in str(error.value).lower()
        assert "mattress replaced" in str(error.value)


@pytest.mark.django_db
def test_an_occupied_bed_cannot_be_marked_available(admission, beds):
    """AC-72 (negative). The patient in the bed is the authority on whether it
    is free."""
    with pytest.raises(ValidationError) as error:
        beds[0].set_service_state(Bed.AVAILABLE)
    assert "occupied" in str(error.value).lower()


@pytest.mark.django_db
def test_a_released_bed_goes_for_cleaning_not_straight_to_available(
    admission, beds, ward_doctor
):
    """AC-101. A bed someone has just left is not ready for the next patient."""
    occupancy = admission.current_occupancy
    occupancy.close(actor=ward_doctor, reason="discharged")

    beds[0].refresh_from_db()
    assert beds[0].is_occupied is False
    assert beds[0].service_state == Bed.CLEANING
    assert beds[0].state == Bed.CLEANING


@pytest.mark.django_db
def test_bed_movement_history_is_traceable(admission, beds, ward_doctor):
    """AC-71. For any bed: who was in it and when, in order, with no gaps."""
    first = admission.current_occupancy
    started = first.period.lower
    first.close(actor=ward_doctor, at=started + timedelta(days=2), reason="transferred")

    other = Patient.objects.create(
        given_name="Next", family_name="Patient", sex="male", facility=admission.facility
    )
    second_admission = Admission.objects.create(
        patient=other, facility=admission.facility, admission_reason="x",
        admission_diagnosis="x", responsible_consultant=ward_doctor,
        admitted_by=ward_doctor,
    )
    beds[0].refresh_from_db()
    beds[0].set_service_state(Bed.AVAILABLE)
    BedOccupancy.allocate(
        bed=beds[0], admission=second_admission, actor=ward_doctor,
        at=started + timedelta(days=2, hours=3),
    )

    history = list(
        BedOccupancy.objects.filter(bed=beds[0]).select_related("patient").order_by("period")
    )
    assert [entry.patient.full_name for entry in history] == [
        admission.patient.full_name,
        other.full_name,
    ]
    assert history[0].period.upper is not None
    assert history[1].period.upper is None
    assert history[0].period.upper <= history[1].period.lower


@pytest.mark.django_db
def test_an_occupancy_cannot_end_before_it_began(admission, ward_doctor):
    """(negative)"""
    occupancy = admission.current_occupancy
    with pytest.raises(ValidationError):
        occupancy.close(actor=ward_doctor, at=occupancy.period.lower - timedelta(hours=1))


@pytest.mark.django_db
def test_ward_occupancy_always_equals_the_number_of_open_occupancies(
    facility_a, ward, beds, ward_doctor, hospital_numbers, inpatient_numbers
):
    """AC-73, over generated admissions and discharges rather than one example."""
    from itertools import cycle

    live = []
    pattern = cycle([True, True, False, True, False, False])
    for index in range(10):
        admit = next(pattern)
        if admit and len(live) < len(beds):
            free = next(
                bed for bed in beds
                if not bed.occupancies.filter(period__endswith__isnull=True).exists()
            )
            free.refresh_from_db()
            if free.service_state != Bed.AVAILABLE:
                free.service_state = Bed.AVAILABLE
                free.save(update_fields=["service_state"])
            patient = Patient.objects.create(
                given_name=f"Gen{index}", family_name="Occupancy", sex="male",
                facility=facility_a,
            )
            record = Admission.objects.create(
                patient=patient, facility=facility_a, admission_reason="x",
                admission_diagnosis="x", responsible_consultant=ward_doctor,
                admitted_by=ward_doctor,
            )
            live.append(BedOccupancy.allocate(bed=free, admission=record, actor=ward_doctor))
        elif live:
            live.pop(0).close(actor=ward_doctor, reason="discharged")

        counts = ward.occupancy()
        assert counts["occupied"] == len(live), f"step {index}: counter disagrees"
        assert counts["occupied"] == BedOccupancy.objects.filter(
            bed__room__ward=ward, period__endswith__isnull=True
        ).count()
