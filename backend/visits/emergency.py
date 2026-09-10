"""The emergency department.

Three rules carry this, and each exists because of a specific way an ED goes
wrong:

- **Registration is short.** A patient arriving by ambulance is registered in
  the fields a nurse can answer while the trolley is moving. Everything else
  is filled in later, and an unidentified patient is registered with no name
  at all rather than not registered.
- **Re-triage appends.** A patient who arrived green and went red
  deteriorated; they were not "corrected". Editing the first assessment erases
  the fact an incident review is looking for.
- **An episode ends once.** Two outcomes make the department's own figures
  unanswerable; none means it never closes and the patient stays on the board
  forever.
"""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from patients.models import Patient, register_unidentified

from .models import (
    EmergencyEpisode,
    TriageAssessment,
    TriageLevel,
    TriageScale,
    Visit,
)


class EmergencyError(ValidationError):
    """A refusal somebody in the department needs to read."""


@transaction.atomic
def register_arrival(*, facility, presenting_complaint, actor, patient=None,
                     unidentified=False, sex="unknown", estimated_age_years=None,
                     arrival_mode=EmergencyEpisode.WALK_IN, brought_in_by="",
                     circumstances="", clinic=None, arrived_at=None):
    """AC-167. Get them into the system, now.

    Either an existing patient or, where nobody can say who they are, a fresh
    record under a temporary identity. The temporary one is merged later
    through the ordinary duplicate-merge path, which is what keeps everything
    recorded under it.
    """
    if not presenting_complaint.strip():
        raise EmergencyError(
            "Record why they are here, even if it is only 'collapsed in the "
            "street'. An episode with no complaint cannot be triaged."
        )
    if patient is None and not unidentified:
        raise EmergencyError(
            "Name the patient, or register them as unidentified."
        )

    if patient is None:
        patient = register_unidentified(
            facility=facility, sex=sex,
            estimated_age_years=estimated_age_years, actor=actor,
        )

    try:
        # A savepoint: the refusal below has to run a query, and a constraint
        # violation would otherwise poison the caller's transaction.
        with transaction.atomic():
            visit = Visit.objects.create(
                patient=patient, facility=facility, clinic=clinic,
                arrived_at=arrived_at or timezone.now(),
                reason=presenting_complaint[:255],
                checked_in_by=actor,
            )
    except IntegrityError:
        # One open attendance per patient. A patient waiting in the outpatient
        # queue who collapses and is brought round to the ED is a real thing
        # that happens, and it must not arrive as a server error — the nurse
        # needs to be told which attendance to close.
        open_visit = Visit.objects.filter(
            patient=patient, closed_at__isnull=True
        ).select_related("facility").first()
        raise EmergencyError(
            f"{patient.full_name} already has an open attendance"
            + (f" at {open_visit.facility.name}, started "
               f"{timezone.localtime(open_visit.arrived_at):%H:%M}. Close it, or "
               f"continue on that attendance."
               if open_visit else ".")
        )
    return EmergencyEpisode.objects.create(
        visit=visit, arrival_mode=arrival_mode,
        presenting_complaint=presenting_complaint,
        brought_in_by=brought_in_by, circumstances=circumstances,
    )


def active_scale(facility):
    """The scale this facility triages on, or None if none is configured."""
    return TriageScale.objects.filter(
        facility=facility, is_active=True
    ).prefetch_related("levels").first()


@transaction.atomic
def triage(*, episode, level, actor, complaint="", observations="",
           reason_for_retriage=""):
    """AC-168, AC-169. Assess, or re-assess.

    A re-triage is a new assessment with a reason, never an edit. The earlier
    one stays, so the record shows what changed and when.
    """
    if not episode.is_open:
        raise EmergencyError(
            f"That episode closed as {episode.get_outcome_display().lower()}."
        )
    if level.scale.facility_id != episode.visit.facility_id:
        raise EmergencyError("That triage level belongs to another facility's scale.")

    previous = episode.current_triage()
    sequence = 1 if previous is None else previous.sequence + 1

    if sequence > 1 and not reason_for_retriage.strip():
        raise EmergencyError(
            "Say why the severity is being reassessed. Without it the record "
            "shows a level that changed for no stated reason, and nobody can "
            "tell whether the patient deteriorated or the first triage was wrong."
        )

    return TriageAssessment.objects.create(
        episode=episode, level=level, sequence=sequence, complaint=complaint,
        observations=observations, reason_for_retriage=reason_for_retriage,
        assessed_by=actor,
    )


def queue(*, facility, include_untriaged=True):
    """AC-168. The board: sickest first, then longest waiting.

    Ordered by severity before arrival time, which is the whole difference
    between an emergency queue and a clinic one. An untriaged patient sorts
    ahead of everybody: nobody knows how sick they are yet, and that is itself
    the most urgent state to be in.
    """
    episodes = EmergencyEpisode.objects.filter(
        visit__facility=facility, outcome=""
    ).select_related(
        "visit__patient", "visit__facility",
    ).prefetch_related("triage_assessments__level")

    # Sorted in Python rather than SQL. "The rank of the *latest* assessment"
    # is a correlated lookup that Django expresses only as a subquery per row,
    # and the board is at most a few dozen patients — the prefetch above makes
    # this two queries either way, and this version is readable.
    rows = []
    for episode in episodes:
        current = episode.current_triage()
        if current is None and not include_untriaged:
            continue
        rows.append({
            "episode": episode,
            # Untriaged sorts to the very top: an unknown severity is the most
            # urgent thing on the board, not the least.
            "rank": current.level.rank if current else 0,
            "level": current.level if current else None,
            "waited": episode.waiting_minutes(),
            "breaching": _is_breaching(episode, current),
        })
    rows.sort(key=lambda row: (row["rank"], -row["waited"]))
    return rows


def _is_breaching(episode, assessment):
    """Waited longer than their level's target. AC-168.

    Reported rather than acted on: the software does not know what a
    department should do about a breach, and pretending otherwise would be
    inventing clinical policy.
    """
    if assessment is None or assessment.level.target_minutes is None:
        return False
    return episode.waiting_minutes() > assessment.level.target_minutes


@transaction.atomic
def close(*, episode, outcome, actor, note=""):
    """AC-170. Exactly one outcome, with a time.

    Refused on an episode that already has one. Correcting a wrong outcome is
    deliberately not possible here: it is a change to a closed clinical record
    and belongs with whoever handles those, not with the nurse clearing the
    board at the end of a shift.
    """
    if not episode.is_open:
        raise EmergencyError(
            f"That episode already closed as "
            f"{episode.get_outcome_display().lower()} at "
            f"{timezone.localtime(episode.outcome_at):%d %b %H:%M}."
        )
    valid = {value for value, _ in EmergencyEpisode.OUTCOME_CHOICES}
    if outcome not in valid:
        raise EmergencyError(f"{outcome} is not an outcome an episode can end in.")
    if outcome == EmergencyEpisode.LEFT_WITHOUT_BEING_SEEN and (
        episode.triage_assessments.exists() and not note.strip()
    ):
        raise EmergencyError(
            "A triaged patient leaving without being seen needs a note. Somebody "
            "assessed them as needing care and they went home instead."
        )

    episode.outcome = outcome
    episode.outcome_at = timezone.now()
    episode.outcome_note = note
    episode.outcome_recorded_by = actor
    episode.save(update_fields=["outcome", "outcome_at", "outcome_note",
                                "outcome_recorded_by"])
    return episode


def unidentified_patients(*, facility):
    """AC-167. Who is still nameless, so somebody chases it.

    A temporary identity that nobody merges becomes a permanent duplicate, and
    the patient's next attendance starts a third record.
    """
    return Patient.objects.filter(
        facility=facility, is_unidentified=True, status="active"
    ).order_by("created_at")


def seed_default_scale(*, facility, name="Four-level triage"):
    """A starting scale for a hospital that has not configured one.

    Four levels, because that is the smallest scale that distinguishes the
    decisions an ED actually makes: now, soon, wait, and not here. **The
    numbers are not clinically approved** — they are a starting point a
    hospital's own clinicians are expected to replace.
    """
    scale, created = TriageScale.objects.get_or_create(
        facility=facility, name=name, defaults={"is_active": True}
    )
    if not created:
        return scale
    for rank, level_name, colour, target, description in [
        (1, "Immediate", "red", 0, "Life-threatening. Seen on arrival."),
        (2, "Very urgent", "orange", 15, "Serious. Deteriorating or in severe pain."),
        (3, "Urgent", "yellow", 60, "Needs treatment but stable."),
        (4, "Standard", "green", 240, "Can safely wait."),
    ]:
        TriageLevel.objects.create(
            scale=scale, rank=rank, name=level_name, colour=colour,
            target_minutes=target, description=description,
        )
    return scale
