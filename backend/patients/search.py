"""One search box across every identifier reception actually has to hand.

Staff type whatever the patient gave them — a hospital number, a phone number, a name, a
date of birth — so the query is classified rather than making the user pick a field.

Classification short-circuits on purpose. An exact hospital-number lookup must not pay
for a trigram scan and a similarity sort over the whole table: it is the single most
common query at a front desk, and it should be an index hit. Only if a precise lookup
finds nothing does the fuzzy name search run, so a mistyped number still finds someone.
"""
import re
from datetime import date

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Q, Value

NAME_MATCH_THRESHOLD = 0.30
NON_DIGITS = re.compile(r"\D")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Hospital numbers carry a separator or a prefix; a bare digit string is a phone number.
LOOKS_LIKE_HOSPITAL_NUMBER = re.compile(r"^[A-Za-z0-9]+[/-]")


def _as_date(term):
    if not ISO_DATE.match(term):
        return None
    try:
        return date.fromisoformat(term)
    except ValueError:
        return None


def _by_name(queryset, term):
    """Filter with the `%` operator, then rank.

    `__trigram_similar` compiles to `search_name % term`, which the GIN trigram index
    serves. Filtering on `TrigramSimilarity(...) >= x` instead compiles to
    `similarity(search_name, term) >= x`, which no index can serve — it computes a
    similarity for every row in the table. Ranking is done after the filter, so the
    similarity is only computed for the handful of rows that matched.

    The `%` threshold is Postgres's `pg_trgm.similarity_threshold` (0.3 by default),
    which NAME_MATCH_THRESHOLD is kept equal to; the explicit filter below makes the
    boundary the same regardless of server configuration.
    """
    return (
        queryset.filter(search_name__trigram_similar=term)
        .annotate(relevance=TrigramSimilarity("search_name", term))
        .filter(relevance__gte=NAME_MATCH_THRESHOLD)
        .order_by("-relevance", "family_name", "given_name")
    )


def search_patients(queryset, term):
    term = (term or "").strip()
    if not term:
        return queryset.annotate(relevance=Value(0.0))

    # Hospital number: exact, uppercased, so the unique index is used. `iexact` would
    # wrap the column in UPPER() and force a scan.
    if LOOKS_LIKE_HOSPITAL_NUMBER.match(term):
        exact = queryset.filter(hospital_number=term.upper()).annotate(relevance=Value(1.0))
        if exact.exists():
            return exact

    digits = NON_DIGITS.sub("", term)
    if len(digits) >= 6 and not LOOKS_LIKE_HOSPITAL_NUMBER.match(term):
        by_phone = queryset.filter(
            Q(phone_primary__contains=digits) | Q(phone_alternate__contains=digits)
        ).annotate(relevance=Value(1.0))
        if by_phone.exists():
            return by_phone

    born_on = _as_date(term)
    if born_on:
        return queryset.filter(date_of_birth=born_on).annotate(relevance=Value(1.0))

    return _by_name(queryset, term)
