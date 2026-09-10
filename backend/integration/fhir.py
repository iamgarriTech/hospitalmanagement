"""FHIR-shaped representations of the hospital's records.

**Read this before treating it as FHIR.** This is a *FHIR-shaped* facade, not
a conformant FHIR server. It emits resources whose field names and structure
follow R4 closely enough that an integrator can map them without a
translation table, and that is the whole claim. It does not implement
CapabilityStatement, `_include`, chained search, transactions, subscriptions,
or the operation framework, and it is read-only.

Saying so plainly is AC-189's rule applied to an integration surface: an
integrator who assumes conformance will write a client that breaks, and an
integrator who is told the truth will not.

Codes carry their system and version from the record, so a diagnosis recorded
under ICD-10 renders as ICD-10 forever — guarantee 8, and the reason nothing
here re-maps a code on the way out.
"""

from django.utils import timezone

from core.formatting import trim_decimal


def _reference(kind, pk):
    return {"reference": f"{kind}/{pk}"}


def _identifier(system, value):
    return {"system": system, "value": value}


def patient(record):
    """FHIR Patient.

    `identifier` carries the hospital number, which is the only identifier
    this system mints. A national identity number, where a hospital records
    one, would belong here too — and deliberately does not, because this
    software does not hold one.
    """
    return {
        "resourceType": "Patient",
        "id": str(record.pk),
        "identifier": [
            _identifier("urn:vitacore:hospital-number", record.hospital_number),
        ],
        "active": record.status == "active",
        "name": [{
            "use": "official",
            "family": record.family_name,
            "given": [part for part in (record.given_name, record.other_names)
                      if part],
            "text": record.full_name,
        }],
        "telecom": [
            {"system": "phone", "value": number, "use": use}
            for number, use in [(record.phone_primary, "mobile"),
                                (record.phone_alternate, "home")]
            if number
        ] + ([{"system": "email", "value": record.email}] if record.email else []),
        "gender": record.sex,
        "birthDate": record.date_of_birth.isoformat() if record.date_of_birth else None,
        # Not a FHIR field. An estimated birth date is a clinically important
        # distinction and dropping it silently would be worse than an
        # extension an integrator can ignore.
        "_birthDateEstimated": record.date_of_birth_is_estimated,
        "address": [{
            "line": [record.address_line] if record.address_line else [],
            "city": record.city,
            "state": record.state,
            "country": record.country,
        }] if record.address_line or record.city else [],
        "managingOrganization": _reference("Organization", record.facility_id),
        "link": (
            [{"other": _reference("Patient", record.merged_into_id),
              "type": "replaced-by"}]
            if record.merged_into_id else []
        ),
    }


def encounter(record):
    """FHIR Encounter — a consultation."""
    status = {
        "draft": "in-progress",
        "finalised": "finished",
    }.get(record.status, "unknown")
    return {
        "resourceType": "Encounter",
        "id": str(record.pk),
        "status": status,
        "class": {"code": record.encounter_type},
        "subject": _reference("Patient", record.patient_id),
        "participant": [{
            "individual": _reference("Practitioner", record.clinician_id),
        }] if record.clinician_id else [],
        "period": {
            "start": record.started_at.isoformat() if record.started_at else None,
            "end": record.finalised_at.isoformat() if record.finalised_at else None,
        },
        "serviceProvider": _reference("Organization", record.facility_id),
    }


def condition(diagnosis):
    """FHIR Condition — a recorded diagnosis.

    The coding carries its system *and* its version, straight from the record.
    Guarantee 8: a diagnosis recorded under ICD-10 in 2026 must not re-render
    under a later code set, and the only way to promise that is to never
    re-map on the way out.
    """
    version = diagnosis.version
    return {
        "resourceType": "Condition",
        "id": str(diagnosis.pk),
        "clinicalStatus": {"coding": [{"code": "active"}]},
        "verificationStatus": {"coding": [{"code": diagnosis.certainty}]},
        "code": {
            "coding": [{
                "system": diagnosis.code_system,
                "code": diagnosis.code,
                "display": diagnosis.code_display or diagnosis.description,
                "version": diagnosis.code_version,
            }] if diagnosis.code else [],
            "text": diagnosis.description,
        },
        "subject": _reference("Patient", version.encounter.patient_id),
        "encounter": _reference("Encounter", version.encounter_id),
        "recordedDate": version.authored_at.isoformat(),
    }


def observation_from_vitals(record, field, code, display, value, unit=None):
    """One FHIR Observation out of a vital-signs row.

    A vital-signs record holds several measurements; FHIR models each as its
    own Observation, so one row fans out into several resources. The id is
    composite so an integrator can address each one stably.
    """
    return {
        "resourceType": "Observation",
        "id": f"{record.pk}-{field}",
        "status": "final",
        "category": [{"coding": [{"code": "vital-signs"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": code,
                             "display": display}], "text": display},
        "subject": _reference("Patient", record.patient_id),
        "effectiveDateTime": record.recorded_at.isoformat(),
        "performer": [_reference("Practitioner", record.recorded_by_id)],
        "valueQuantity": {"value": float(value), "unit": unit} if unit else None,
        "valueInteger": None if unit else int(value),
    }


# LOINC codes for the observations this system records. A curated subset, not
# the whole of LOINC — see the note in the module docstring and AC-189.
VITALS_CODES = [
    ("temperature_c", "8310-5", "Body temperature", "Cel"),
    ("pulse_bpm", "8867-4", "Heart rate", "/min"),
    ("systolic_bp", "8480-6", "Systolic blood pressure", "mm[Hg]"),
    ("diastolic_bp", "8462-4", "Diastolic blood pressure", "mm[Hg]"),
    ("respiratory_rate", "9279-1", "Respiratory rate", "/min"),
    ("oxygen_saturation", "59408-5", "Oxygen saturation", "%"),
]


def observations_from_vitals(record):
    for field, code, display, unit in VITALS_CODES:
        value = getattr(record, field, None)
        if value is None:
            continue
        yield observation_from_vitals(record, field, code, display, value, unit)


def observation_from_result(result):
    """FHIR Observation — a laboratory result.

    Only ever a verified one. AC-185 forbids an unverified result reaching a
    patient, and the same reasoning applies with more force to an external
    system that may act on it automatically: a number nobody has signed is not
    a result, it is a reading.
    """
    item = result.order_item
    parameter = result.parameter
    return {
        "resourceType": "Observation",
        "id": str(result.pk),
        "status": "final",
        "category": [{"coding": [{"code": "laboratory"}]}],
        "code": {
            "coding": [{
                "system": parameter.code_system or "http://loinc.org",
                "code": parameter.code,
                "display": parameter.name,
                "version": parameter.code_version,
            }] if parameter.code else [],
            "text": parameter.name,
        },
        "subject": _reference("Patient", item.order.patient_id),
        "effectiveDateTime": result.entered_at.isoformat(),
        "issued": item.verified_at.isoformat() if item.verified_at else None,
        "performer": [_reference("Practitioner", item.verified_by_id)]
        if item.verified_by_id else [],
        "valueQuantity": (
            {"value": float(result.value_numeric), "unit": result.unit}
            if result.value_numeric is not None else None
        ),
        "valueString": result.value_text or None,
        "interpretation": [{"coding": [{"code": result.flag}]}]
        if result.flag else [],
        "referenceRange": [{
            "low": {"value": float(result.range_low)}
            if result.range_low is not None else None,
            "high": {"value": float(result.range_high)}
            if result.range_high is not None else None,
            "text": result.range_note,
        }] if result.range_low is not None or result.range_high is not None else [],
        "note": [{"text": result.comment}] if result.comment else [],
    }


def medication_request(item):
    """FHIR MedicationRequest — a prescribed medication."""
    prescription = item.prescription
    return {
        "resourceType": "MedicationRequest",
        "id": str(item.pk),
        # The item's own status where it has moved on, otherwise the
        # prescription's: one cancelled line does not cancel the script.
        "status": {
            "active": "active",
            "dispensed": "completed",
            "partially_dispensed": "active",
            "cancelled": "cancelled",
        }.get(item.status if item.status == "cancelled" else prescription.status,
              "unknown"),
        "intent": "order",
        "medicationCodeableConcept": {
            "coding": [{
                "system": item.medication.code_system,
                "code": item.medication.code,
                "display": item.medication.generic_name,
                "version": item.medication.code_version,
            }] if item.medication.code else [],
            "text": (
                f"{item.medication.generic_name} {item.medication.strength} "
                f"{item.medication.dosage_form}"
            ).strip(),
        },
        "subject": _reference("Patient", prescription.patient_id),
        "authoredOn": prescription.prescribed_at.isoformat(),
        "requester": _reference("Practitioner", prescription.prescribed_by_id),
        "dosageInstruction": [{
            # `trim_decimal`, not the raw Decimal: a DecimalField renders as
            # "4.000 tablet", which reads as a precision nobody measured.
            "text": (
                f"{trim_decimal(item.dose)} {item.dose_unit} {item.route}, "
                f"{item.frequency_per_day} times a day for {item.duration_days} days"
            ).strip(),
            "route": {"text": item.route},
            "doseAndRate": [{
                "doseQuantity": {"value": float(item.dose), "unit": item.dose_unit},
            }],
            # Frequency is stored as a count per day rather than free text, so
            # it maps cleanly onto FHIR's timing repeat instead of needing a
            # string an integrator has to parse.
            "timing": {"repeat": {
                "frequency": item.frequency_per_day,
                "period": 1,
                "periodUnit": "d",
                "boundsDuration": {"value": item.duration_days, "unit": "d"},
            }},
        }],
        "dispenseRequest": {
            "quantity": {"value": item.quantity_prescribed},
        },
    }


def bundle(resource_type, resources, *, total=None):
    """A FHIR searchset Bundle.

    `timestamp` is when the search ran, which matters for the same reason a
    report states it: two people comparing pulls need to be able to see why
    they differ.
    """
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "timestamp": timezone.now().isoformat(),
        "total": total if total is not None else len(resources),
        "entry": [{"resource": resource} for resource in resources],
    }
