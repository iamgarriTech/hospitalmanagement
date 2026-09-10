"""Everything this software does not check, in one place. AC-189.

The rule behind this module: **a clinician or a cashier must never infer a
check that is not running.** Scattering that promise across a dozen screens
means it holds on the screens somebody remembered and fails on the rest, so
the whole picture is assembled here and rendered on one page anybody can
reach.

Two kinds of entry:

- `active: False` — a check that does not exist, or needs a licence or a
  configuration this deployment does not have. Read as: nothing is checking
  this.
- `active: True, reviewed: False` — a check that runs, on numbers **nobody
  clinically qualified has signed off.** Round times, overdue windows,
  triage targets and escalation thresholds are all in this category, and it is
  the more dangerous of the two: something happens, so it looks handled.

Anything added to this system that checks, scores, or warns belongs here
before it belongs on a screen.
"""

from django.conf import settings


def _clinical_review_state():
    """Has a named clinician signed off the clinical content?

    Deliberately a setting with a hostile default. Until a hospital sets it,
    every clinical default in this system reports itself as unreviewed —
    which is the truth, and the release gate in the roadmap says the project
    does not describe itself as suitable for real hospital use until it
    changes.
    """
    reviewer = getattr(settings, "CLINICAL_CONTENT_REVIEWER", "")
    return bool(reviewer), reviewer


def report():
    """The whole picture. Grouped as the screen shows it."""
    from pharmacy.safety import capabilities as pharmacy_capabilities

    reviewed, reviewer = _clinical_review_state()
    entries = []

    # --- prescribing ------------------------------------------------------
    for key, capability in pharmacy_capabilities().items():
        entries.append({
            "area": "Prescribing",
            "check": key.replace("_", " ").capitalize(),
            "active": capability["active"],
            "reviewed": reviewed,
            "detail": capability["detail"],
        })

    # --- coding -----------------------------------------------------------
    entries.append({
        "area": "Coding",
        "check": "SNOMED CT",
        "active": False,
        "reviewed": True,
        "detail": (
            "Not used. Its licence runs through national member affiliates and "
            "Nigeria is not a member. Diagnoses use ICD-10 and laboratory tests a "
            "curated LOINC subset. Every recorded code carries its system and "
            "version, so a future code set cannot silently re-render it."
        ),
    })
    entries.append({
        "area": "Coding",
        "check": "Complete LOINC and ICD-10 catalogues",
        "active": False,
        "reviewed": True,
        "detail": (
            "The catalogues here are curated subsets a hospital extends, not the "
            "full code sets. A code absent from the list is not a code that does "
            "not exist."
        ),
    })

    # --- clinical defaults, running but unreviewed ------------------------
    for check, detail in [
        ("Medication round times",
         "08:00, 14:00 and 20:00, with a 60-minute window before a dose counts "
         "as overdue."),
        ("Observation escalation thresholds",
         "Per-ward high and low bounds on temperature, blood pressure, pulse, "
         "respiratory rate, oxygen saturation and glucose."),
        ("Triage targets",
         "The four-level scale and its target waiting times, where a hospital "
         "has not replaced them with its own."),
        ("Consent wording",
         "The consent record captures what was discussed. The wording is a "
         "record of a conversation, not a substitute for the hospital's own "
         "consent form."),
        ("Maternity dating",
         "Estimated delivery dates use Naegele's rule — 280 days from the last "
         "period — and always state which basis was used."),
    ]:
        entries.append({
            "area": "Clinical defaults",
            "check": check,
            "active": True,
            "reviewed": reviewed,
            "detail": detail + (
                "" if reviewed else
                " NOT REVIEWED by a clinician. These are reasonable defaults "
                "chosen by the people who built the software."
            ),
        })

    # --- things that are not scored at all --------------------------------
    for area, check, detail in [
        ("Maternity", "Obstetric risk scoring",
         "Risk factors are recorded as the clinician describes them. Nothing "
         "here scores, ranks or acts on them."),
        ("Emergency", "Deterioration and breach escalation",
         "A patient past their triage target is reported as breaching. The "
         "software takes no action and does not decide what a department "
         "should do about it."),
        ("Theatre", "Surgical safety checklist",
         "Not implemented. The operation record captures the team, findings "
         "and consumables; it is not a WHO checklist and does not enforce one."),
        ("Laboratory", "Delta checks and result plausibility",
         "A result is checked against its reference range only. It is not "
         "compared with the patient's previous values, and an implausible "
         "figure is not queried."),
        ("Imaging", "Radiation dose tracking",
         "Not recorded. Cumulative dose per patient is not tracked or warned on."),
        ("Insurance", "Coordination of benefits",
         "A patient may hold two policies and the hospital sets which pays "
         "first, but the first policy that pays anything settles the charge. "
         "One charge is never split across two schemes."),
        ("Stores", "Drug and consumable recall handling",
         "A lot can be written off by hand. There is no recall feed and no "
         "automatic quarantine of an affected batch."),
    ]:
        entries.append({
            "area": area, "check": check, "active": False, "reviewed": True,
            "detail": detail,
        })

    # --- integration and messaging ----------------------------------------
    entries.append({
        "area": "Messaging",
        "check": "SMS and email delivery",
        "active": False,
        "reviewed": True,
        "detail": (
            "No provider is configured. Queued messages are written to the "
            "server log and marked sent with a note saying nothing left the "
            "building. Do not rely on a patient having been contacted."
        ),
    })
    entries.append({
        "area": "Integration",
        "check": "FHIR conformance",
        "active": False,
        "reviewed": True,
        "detail": (
            "The external API is FHIR-*shaped*, not a conformant FHIR server. "
            "No CapabilityStatement, no _include, no chained search, no "
            "transactions, no subscriptions, and it is read-only."
        ),
    })

    # --- offline ----------------------------------------------------------
    entries.append({
        "area": "Resilience",
        "check": "Offline clinical writing",
        "active": False,
        "reviewed": True,
        "detail": (
            "The server is expected to be in the building, so losing the "
            "internet does not stop work. But two nurses recording different "
            "outcomes for one dose have no safe automatic merge, so nothing "
            "can be written while the server itself is unreachable. Each ward "
            "has a printable read-only snapshot for that case."
        ),
    })

    return {
        "clinical_content_reviewed": reviewed,
        "clinical_content_reviewer": reviewer,
        "entries": entries,
        "summary": {
            "not_running": sum(1 for e in entries if not e["active"]),
            "running_unreviewed": sum(
                1 for e in entries if e["active"] and not e["reviewed"]
            ),
            "running_reviewed": sum(
                1 for e in entries if e["active"] and e["reviewed"]
            ),
        },
    }
