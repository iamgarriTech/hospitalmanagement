# Measured performance

Every figure here was measured, not estimated. Where a target was missed the
cause is named and the fix recorded, because "we made it faster" without saying
what was slow is not a result anyone can act on.

## How it was measured

- **gunicorn**, 4 workers × 4 threads (the reference install in `compose.yaml`),
  not the development server.
- **PostgreSQL 18** on the same machine, holding **500,000 patients**, one of
  whom has **200 historical encounters** with versions, diagnoses and vitals.
- Real logins, so session lookup and facility-scoped permission resolution are
  inside every measurement.
- Latency is wall-clock at the client, including JSON serialisation.

Caveat worth stating: this was measured on a development laptop also running
Postgres, two dev servers and unrelated work. The figures are indicative and
the *query counts* are the machine-independent part. Re-measure on the real
server before quoting these to a hospital.

## AC-13 — patient search, p95 < 300 ms at 500k patients

| Query | p50 before | p50 after |
|---|---|---|
| Hospital number | 252.4 ms | **2.7 ms** |
| Phone number | 202.9 ms | 81.5 ms |
| Surname | 180.4 ms | 83.5 ms |
| Full name | 237.0 ms | 192.1 ms |
| Misspelled name | 230.7 ms | 136.0 ms |
| **Overall p95** | **291.5 ms** | **212.8 ms** |

Two defects found and fixed:

1. **Name search was a sequential scan.** `TrigramSimilarity(...) >= 0.3`
   compiles to `similarity(col, term) >= 0.3`, which no index can serve — it
   computed a similarity for all 500,000 rows. `__trigram_similar` compiles to
   the `%` operator, which the GIN index serves.
2. **`iexact` on hospital number defeated the unique index** by wrapping the
   column in `UPPER()`. Numbers are now stored uppercase and looked up with
   `exact`, and the search short-circuits on an identifier rather than paying
   for a trigram scan it does not need.

`patients/tests/test_search_uses_indexes.py` asserts on the query plan, because
this regresses while still returning correct results.

## AC-14 — patient profile with 200 encounters, 50 concurrent users, p95 < 1 s

| | p95 |
|---|---|
| First measurement | **3,355 ms** — FAIL |
| After fixing the N+1 | 1,628 ms — FAIL |
| After tab-gating the queries | 644 ms |
| 50 concurrent users, human pacing | **51 ms** — PASS |
| 50 simultaneous opens (burst) | 541 ms — PASS |

Two defects:

1. **An N+1 that discarded its own prefetch.** `Encounter.current_version` called
   `self.versions.filter(is_current=True).first()`. A *filtered* manager cannot
   use the prefetch cache, so it issued a fresh query per encounter, and
   `version_count` another. One list view cost **158 queries**. Iterating the
   prefetched list instead, and joining `authored_by` inside the prefetch,
   brought it to **8**. The same mistake was present in `Invoice.is_frozen` and
   was fixed there too.
2. **The profile fetched all seven tabs on mount.** Only two are needed to open
   a chart; the rest now fetch when their tab is selected. Seven requests
   became two.

The criterion says 50 concurrent *users*. Fifty staff with a chart open are not
fifty requests in the same millisecond — they read and type — so the headline
figure paces requests. The all-at-once burst is reported as well, and also
passes.

## AC-16 — 200 concurrent staff sessions, no error-rate increase

| | result |
|---|---|
| Sessions established | 200, **0 login failures** |
| Errors across 1,200 role-typical requests | **0** |
| p95, human pacing | **25 ms** |
| p95, all-at-once burst | ~1,000 ms |

No endpoint in the mix exceeded 6 ms or 8 queries in-process, so the burst
figure is queueing, not slow code: 200 simultaneous requests against 4 × 4 = 16
handler slots.

**Sizing note.** Raising gunicorn to 9 workers × 4 threads made things *worse*
on an 8-core box — 36 workers-threads oversubscribes the CPU and opens 36
Postgres connections. Worker count should be tuned on the real hardware, not
copied from a formula; the reference install stays at 4 × 4.

## Reproducing

```
createdb hms_bench
DATABASE_URL=postgres://…/hms_bench python backend/manage.py migrate
DATABASE_URL=postgres://…/hms_bench python backend/manage.py seed_demo
# 500k patients + one with 200 encounters: see the scripts referenced in the
# commit that added this document
DATABASE_URL=postgres://…/hms_bench gunicorn config.wsgi:application \
  --chdir backend --bind 127.0.0.1:8020 --workers 4 --threads 4
```
