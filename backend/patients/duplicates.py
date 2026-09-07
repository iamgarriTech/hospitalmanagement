"""Suspected-duplicate detection.

Duplicate patient records are a patient-safety problem, not a tidiness one: history,
allergies and results end up split across two charts. So detection runs before a record
is created — but it warns rather than blocks, because genuine near-duplicates exist
(twins registered together, a father and son sharing a name and a phone).
"""
from dataclasses import dataclass, field

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Q

from .models import Patient

NAME_SIMILARITY_THRESHOLD = 0.45
PHONE_WEIGHT = 0.40
DOB_WEIGHT = 0.30


@dataclass
class DuplicateCandidate:
    patient: Patient
    score: float
    reasons: list[str] = field(default_factory=list)


def find_possible_duplicates(
    *,
    given_name,
    family_name,
    other_names="",
    date_of_birth=None,
    phone="",
    facility=None,
    exclude_pk=None,
    limit=10,
):
    candidate_name = " ".join(
        part for part in (given_name, other_names, family_name) if part
    ).strip()

    queryset = Patient.objects.exclude(status=Patient.MERGED)
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)
    if facility is not None:
        queryset = queryset.filter(facility=facility)

    queryset = queryset.annotate(
        name_similarity=TrigramSimilarity("search_name", candidate_name)
    )

    matches = Q(name_similarity__gte=NAME_SIMILARITY_THRESHOLD)
    if phone:
        matches |= Q(phone_primary=phone) | Q(phone_alternate=phone)
    if date_of_birth and candidate_name:
        # Same date of birth plus any name resemblance at all is worth surfacing.
        matches |= Q(date_of_birth=date_of_birth, name_similarity__gte=0.25)

    candidates = []
    for patient in queryset.filter(matches)[: limit * 3]:
        score = float(patient.name_similarity or 0)
        reasons = []
        if score >= NAME_SIMILARITY_THRESHOLD:
            reasons.append(f"name {score:.0%} similar to “{patient.full_name}”")
        if phone and phone in (patient.phone_primary, patient.phone_alternate):
            score += PHONE_WEIGHT
            reasons.append(f"same phone number ({phone})")
        if date_of_birth and patient.date_of_birth == date_of_birth:
            score += DOB_WEIGHT
            reasons.append(f"same date of birth ({date_of_birth})")
        candidates.append(
            DuplicateCandidate(patient=patient, score=min(score, 1.0), reasons=reasons)
        )

    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    return candidates[:limit]
