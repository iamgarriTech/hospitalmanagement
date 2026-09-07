"""Guard the query plans behind AC-13.

Both of these are easy to break with a change that still returns correct results and
quietly becomes a sequential scan. At 500k patients that is the difference between a
3 ms lookup and a 300 ms one, so it is worth asserting on the plan and not only the rows.
"""
import pytest
from django.db import connection

from patients.models import Patient
from patients.search import search_patients


def plan_for(queryset):
    sql, params = queryset.query.sql_with_params()
    with connection.cursor() as cursor:
        cursor.execute(f"EXPLAIN {sql}", params)
        return "\n".join(row[0] for row in cursor.fetchall())


@pytest.mark.django_db
def test_hospital_number_search_is_an_index_lookup_not_a_scan(patient_payload, facility_a,
                                                              hospital_numbers):
    patient = Patient.objects.create(
        given_name="Amina", family_name="Yusuf", sex="female", facility=facility_a
    )
    plan = plan_for(search_patients(Patient.objects.all(), patient.hospital_number))
    assert "Seq Scan" not in plan, plan
    assert "hospital_number" in plan


@pytest.mark.django_db
def test_name_search_filters_through_the_trigram_index(facility_a, hospital_numbers):
    Patient.objects.create(
        given_name="Amina", family_name="Yusuf", sex="female", facility=facility_a
    )
    plan = plan_for(search_patients(Patient.objects.all(), "Amina Yusuf"))
    # The `%` operator is what the GIN index serves; `similarity() >= x` is not.
    assert "search_name %" in plan or "patient_search_name_trgm" in plan, plan
