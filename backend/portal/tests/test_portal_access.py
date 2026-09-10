"""AC-183 and AC-185 — what a patient may see of their own record, and what
no portal request can reach however it is phrased.

The rule these tests defend is narrow and absolute: a portal session reads one
patient's records and there is no parameter, path or body field that can name
another. So each positive test has a negative twin in which a second patient's
data exists in the same tables and must not appear.

AC-185 gets its own section. An unverified result is a number nobody has
signed, and a patient who reads one will act on it before anybody can explain
that it is about to be corrected.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from .conftest import sign_in

VISITS = reverse("portal-record-visits")
RESULTS = reverse("portal-record-results")
MEDICATION = reverse("portal-record-medication")
BILLS = reverse("portal-record-bills")


def verify(as_lab, order_item):
    response = as_lab.post(
        reverse("laborderitem-verify", args=[order_item.pk]), {}, format="json"
    )
    assert response.status_code == 200, response.data
    order_item.refresh_from_db()
    return order_item


# --- appointments and attendances ---------------------------------------------

@pytest.mark.django_db
def test_a_patient_sees_their_own_visits(as_patient, open_visit):
    """AC-183. The visit list is the patient's own attendance history."""
    response = as_patient.get(VISITS)

    assert response.status_code == 200, response.data
    assert [row["id"] for row in response.data] == [open_visit.pk]
    assert response.data[0]["facility"] == "Main Hospital"


@pytest.mark.django_db
def test_the_visit_list_never_includes_another_patients(
    as_patient, open_visit, male_patient, facility_a, visit_numbers
):
    """AC-183 (negative).

    Emeka's visit sits in the same table, in the same facility, created the
    same way. A filter written against the visit's facility rather than its
    patient would return it, which is why this test exists rather than a
    reading of the queryset.
    """
    from visits.models import Visit

    theirs = Visit.objects.create(patient=male_patient, facility=facility_a)

    response = as_patient.get(VISITS)

    returned = [row["id"] for row in response.data]
    assert theirs.pk not in returned
    assert returned == [open_visit.pk]


# --- results: AC-185 ----------------------------------------------------------

@pytest.mark.django_db
def test_an_unverified_result_never_appears(as_patient, portal_account, resulted_item):
    """AC-185 (negative). The bench has entered a haemoglobin of 5.9 and
    nobody has signed it off. The patient must not see it."""
    resulted_item.order.patient = portal_account.patient
    resulted_item.order.save(update_fields=["patient"])

    response = as_patient.get(RESULTS)

    assert response.status_code == 200, response.data
    assert response.data == []


@pytest.mark.django_db
def test_a_verified_result_appears(as_patient, portal_account, resulted_item, as_lab):
    """AC-183. Once a scientist has signed it, the same result is the
    patient's to read."""
    resulted_item.order.patient = portal_account.patient
    resulted_item.order.save(update_fields=["patient"])
    verify(as_lab, resulted_item)

    response = as_patient.get(RESULTS)

    assert response.status_code == 200, response.data
    parameters = {row["parameter"] for row in response.data}
    assert "Haemoglobin" in parameters
    assert all(row["verified_at"] is not None for row in response.data)


@pytest.mark.django_db
def test_the_result_list_never_includes_another_patients(
    as_patient, portal_account, resulted_item, as_lab
):
    """AC-183 (negative). The verified result belongs to Amina; the signed-in
    patient is Emeka, whose own record is empty."""
    verify(as_lab, resulted_item)
    assert resulted_item.order.patient != portal_account.patient

    response = as_patient.get(RESULTS)

    assert response.status_code == 200, response.data
    assert response.data == []


# --- medication ---------------------------------------------------------------

@pytest.mark.django_db
def test_a_patient_sees_their_active_medication(
    as_patient, portal_account, amoxicillin_prescription
):
    """AC-183."""
    from pharmacy.models import Prescription

    written = Prescription.objects.get(pk=amoxicillin_prescription["id"])
    assert written.patient == portal_account.patient

    response = as_patient.get(MEDICATION)

    assert response.status_code == 200, response.data
    assert len(response.data) == 1
    assert "Amoxicillin" in response.data[0]["medication"]


@pytest.mark.django_db
def test_the_medication_list_never_includes_another_patients(
    other_portal_account, portal_account, amoxicillin_prescription
):
    """AC-183 (negative). Emeka signs in; Amina's prescription is live."""
    as_other = sign_in(other_portal_account.login_identifier)

    response = as_other.get(MEDICATION)

    assert response.status_code == 200, response.data
    assert response.data == []


# --- bills --------------------------------------------------------------------

@pytest.mark.django_db
def test_a_patient_sees_a_finalised_bill(
    as_patient, portal_account, billed_visit, finalise_invoice
):
    """AC-183."""
    finalise_invoice(billed_visit)

    response = as_patient.get(BILLS)

    assert response.status_code == 200, response.data
    assert len(response.data) == 1
    assert response.data[0]["invoice_number"] == billed_visit.invoice_number
    assert Decimal(response.data[0]["balance"]) > 0


@pytest.mark.django_db
def test_a_draft_bill_is_not_shown(as_patient, portal_account, billed_visit):
    """A draft invoice is a bill the cashier has not finished assembling.
    Showing a patient a figure that is still moving invites an argument at the
    desk about a number nobody quoted them."""
    from billing.models import Invoice

    assert billed_visit.status == Invoice.DRAFT

    response = as_patient.get(BILLS)

    assert response.status_code == 200, response.data
    assert response.data == []


@pytest.mark.django_db
def test_the_bill_list_never_includes_another_patients(
    other_portal_account, billed_visit, finalise_invoice
):
    """AC-183 (negative)."""
    finalise_invoice(billed_visit)
    as_other = sign_in(other_portal_account.login_identifier)

    response = as_other.get(BILLS)

    assert response.status_code == 200, response.data
    assert response.data == []


# --- "through any parameter" --------------------------------------------------

@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", [VISITS, RESULTS, MEDICATION, BILLS])
def test_no_parameter_can_name_another_patient(
    endpoint, as_patient, portal_account, male_patient, facility_a, visit_numbers,
    amoxicillin_prescription,
):
    """AC-183 (negative) — the clause that says "through any parameter".

    Every name a determined caller would try, on every endpoint, against a
    patient who exists and has records. The portal derives the patient from
    the session, so all of these are ignored rather than validated — but
    "ignored" is a claim that needs proving once per endpoint, because a later
    filter added for convenience is exactly how it stops being true.
    """
    from visits.models import Visit

    Visit.objects.create(patient=male_patient, facility=facility_a)
    baseline = as_patient.get(endpoint).data

    for name in ["patient", "patient_id", "patient__id", "hospital_number",
                 "id", "pk", "account", "facility"]:
        response = as_patient.get(endpoint, {name: male_patient.pk})
        assert response.status_code == 200, (name, response.data)
        assert response.data == baseline, f"{name} changed what was returned"

    response = as_patient.get(endpoint, {"hospital_number": male_patient.hospital_number})
    assert response.data == baseline


@pytest.mark.django_db
def test_the_portal_exposes_no_detail_route_keyed_by_a_patient(as_patient, male_patient):
    """AC-183 (negative). There is no `/api/portal/record/<pk>/`; the router
    registers only list-level actions. A detail route would be a parameter
    naming a record, which is the shape this design does not have."""
    response = as_patient.get(f"/api/portal/record/{male_patient.pk}/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_an_unauthenticated_request_reads_nothing(api, open_visit):
    """No session, no data — and the refusal names no patient."""
    response = api.get(VISITS)

    assert response.status_code in (401, 403)
    assert "Amina" not in str(response.data)


# --- what the endpoints do not carry ------------------------------------------

@pytest.mark.django_db
def test_a_result_carries_no_internal_identifiers(
    as_patient, portal_account, resulted_item, as_lab
):
    """The portal is the outward-facing surface. It returns what a patient
    needs to read and not the hospital's internal keys, so a leak here cannot
    be walked back into the internal API."""
    resulted_item.order.patient = portal_account.patient
    resulted_item.order.save(update_fields=["patient"])
    verify(as_lab, resulted_item)

    row = as_patient.get(RESULTS).data[0]

    for forbidden in ["patient", "patient_id", "order", "order_item", "facility_id"]:
        assert forbidden not in row


@pytest.mark.django_db
def test_the_visit_list_is_bounded(as_patient, portal_account, facility_a, visit_numbers):
    """A patient with a long history gets a page, not the whole table. The cap
    is the view's, and it is asserted so that removing it is a visible change."""
    from visits.models import Visit

    now = timezone.now()
    for index in range(55):
        # Closed as they are made: the database allows a patient only one open
        # visit at a time, which is a different guarantee and already tested.
        Visit.objects.create(
            patient=portal_account.patient, facility=facility_a,
            arrived_at=now - timedelta(days=index + 1),
            status=Visit.COMPLETED, closed_at=now - timedelta(days=index),
        )

    response = as_patient.get(VISITS)

    assert len(response.data) == 50
