# Phase 2 Acceptance Criteria — Inpatient care

Scope: admission through discharge. See [roadmap.md](roadmap.md) for what Phase 2
excludes.

Continues the numbering from Phase 1, so AC-61 onwards. Same rules as
[phase-1-acceptance.md](phase-1-acceptance.md): every criterion is testable,
**(negative)** marks the ones that test something is *refused*, and no criterion
is written as "where appropriate".

The three additions to the release gate for this phase:

1. No two patients can occupy one bed, under concurrent writes.
2. Every medication administration names who gave it and when.
3. A discharge cannot complete with unreconciled inpatient charges.

---

## Status — 2026-09-08

**Backend and screens complete.** Every criterion from AC-61 to AC-117 is
built. AC-118 (forward migration and the restore drill) has not been run.

| | |
|---|---|
| Backend tests | **319 passing** |
| Frontend tests | **19 passing** |
| API endpoints | 318 routes, schema clean (0 errors) |
| Screens | 8 new (37 routes total), all build |
| Accessibility lint | clean (errors, not warnings) |
| Keyboard gate | clean — no click handler on a non-interactive element |
| Migrations | no drift |
| Ward board | 21 queries, 42 ms, 49 KiB |
| MAR chart | 8 queries, 22 ms, 58 KiB |

| Area | Criteria | Status |
|---|---|---|
| Admission | AC-61 – AC-66 | **Pass** |
| Beds and occupancy | AC-67 – AC-73 | **Pass** — AC-69 gate: 12 threads, 1 allocated, 11 refused |
| Transfers | AC-74 – AC-77 | **Pass** |
| Nursing | AC-78 – AC-82 | **Pass** |
| Medication administration | AC-83 – AC-91 | **Pass** — AC-84 gate enforced by the column |
| Inpatient clinical record | AC-92, AC-93 | **Pass** |
| Imaging | AC-94 – AC-98 | **Pass** — an unverified report reaches nobody |
| Discharge | AC-99 – AC-105 | **Pass** — AC-100 gate refuses; override needs the permission |
| Inpatient billing | AC-106 – AC-109 | **Pass** |
| Ward operations | AC-110 – AC-112 | **Pass** — snapshot is a file with no external references |
| Workflow integration | AC-113, AC-114 | **Pass** at the API, incl. 14 permission walks |
| Ward board performance | AC-115 | **Pass** — 444 ms p95, 50 users (from 4,221 ms) |
| MAR performance | AC-116 | **Pass** — 205 ms p95 |
| Keyboard and accessibility | AC-117 | **Pass** — jsx-a11y clean, CI keyboard gate clean |
| Forward migration and restore | AC-118 | **Not run** |

### What is not claimed

- **AC-118** — the forward-migration and restore drill has not been run against
  a database holding Phase 1 data with inpatients present.
- **The Phase 2 screens are not covered by a browser test.** They typecheck,
  lint clean against the same jsx-a11y error set as Phase 1, pass the CI
  keyboard gate, build, and every endpoint behind them was driven through the
  API as each role. What has *not* been verified automatically is the rendered
  DOM, because there is no browser test runner in the project — the same
  limitation Phase 1 recorded for AC-23's indicator.
- **AC-115's same-instant burst** — 50 requests in the same millisecond is
  556 ms p95, over the 500 ms target by 11%. The criterion says 50 concurrent
  *users*, who read and type rather than firing simultaneously, and that figure
  passes at 444 ms; the burst is reported rather than claimed. See
  [performance.md](performance.md).

### One structural change made during this phase

`wards`, `admissions` and `mar` were three Django apps for one workflow, and
`nursing` would have made four. They are now one `inpatient` app, organised by
concern inside it — `models/`, `services/`, `serializers/`, `views/`, each
holding `wards.py`, `admissions.py`, `mar.py` and `nursing.py`. An admission,
its bed, the drug chart and the nursing record are inseparable; split across
apps they need a circular import and four migration graphs kept in step by hand.

This cost almost nothing because none of those tables exist in a Phase 1
database — it was a module rename, not a data migration. Phase 1's migrations
are untouched, so AC-118 still has a real Phase 1 state to run forward from.

`imaging` will stay its own app, parallel to `laboratory`. Folding both into a
shared `diagnostics` app would mean renaming a released `laboratory`, which
*is* a data migration, for no functional gain.

---

## Admission

- **AC-61** An admission request records the requesting clinician, the reason, the
  working diagnosis and the responsible consultant, and appears on a ward's
  pending list without a bed being allocated yet.
- **AC-62** Admitting a patient allocates a specific bed and opens an admission
  with a number in the configured format, unique under concurrent admission.
- **AC-63** A patient who is already an inpatient cannot be admitted a second
  time. **(negative)**
- **AC-64** Admitting requires the admit permission; a nurse who may record
  observations cannot admit. **(negative)**
- **AC-65** Admission from an existing outpatient visit carries the patient,
  facility and visit forward rather than asking again, and the visit's queue
  state reflects that they have been admitted.
- **AC-66** The admission is audited with the bed, ward, reason and responsible
  consultant.

## Beds and occupancy

- **AC-67** Wards, rooms and beds are administrable: a ward can be created, given
  rooms, and rooms given beds, without touching the database.
- **AC-68** A bed has a state — available, occupied, reserved, being cleaned,
  unavailable for maintenance — and the ward view shows the count in each.
- **AC-69 (the gate)** Two patients cannot occupy one bed. Enforced by a database
  **exclusion constraint** over bed and occupancy period, so a race cannot
  produce it: twelve threads admitting to the same bed simultaneously produce one
  occupancy and eleven refusals. **(negative)**
- **AC-70** Allocating a bed that is being cleaned or is unavailable for
  maintenance is refused, and the refusal names the state. **(negative)**
- **AC-71** Bed movement history is traceable: for any bed, who occupied it and
  when, in order, with no gaps in the record.
- **AC-72** A bed cannot be marked available while a patient occupies it.
  **(negative)**
- **AC-73** Ward occupancy is derived from live occupancies, never from a counter
  that could drift: a property test over generated admissions and discharges
  asserts the count equals the number of open occupancies.

## Transfers

- **AC-74** A bed transfer closes the previous occupancy and opens a new one in
  the same transaction, so the patient is never in two beds and never in none.
- **AC-75** A ward transfer records the reason, who authorised it, and both the
  origin and destination.
- **AC-76** A transfer to an occupied bed is refused. **(negative)**
- **AC-77** The patient's movement through the hospital is reconstructable from
  the admission alone: every bed, ward, and the time in each.

## Nursing

- **AC-78** A nursing assessment records its author, the shift, and the
  observations taken, and is attached to the admission rather than to a visit.
- **AC-79** Nursing notes are append-only in effect: a correction adds a new
  note referencing the original, and the original stays legible. **(negative on
  editing)**
- **AC-80** Intake and output are recorded with volumes and a running balance
  over a configurable period, and the balance is derived rather than stored.
- **AC-81** Inpatient vital observations appear on the same trend as outpatient
  ones, so a patient's temperature chart does not restart at admission.
- **AC-82** An observation outside the configured escalation thresholds is
  flagged for escalation, and the escalation — who was told, when, what was done
  — is recorded. **(negative:** an unacknowledged escalation stays on a list.**)**

## Medication administration

- **AC-83** An inpatient prescription generates a **schedule** of due doses from
  the frequency and duration, each with its own due time.
- **AC-84 (the gate)** Every administration records who gave it, when, the dose
  given and the batch it came from. An administration with no administering
  nurse cannot be created. **(negative)**
- **AC-85** The full state set is supported and each requires what it needs:
  administered, missed, delayed, refused, withheld, discontinued. Missed,
  refused, withheld and discontinued each require a reason. **(negative)**
- **AC-86** A dose cannot be administered twice: a retried request or a
  double-tap produces one administration. **(negative)**
- **AC-87** Administering a dose decrements ward stock for the specific batch,
  and an expired batch is refused. **(negative)**
- **AC-88** The allergy check runs at administration as well as at prescribing,
  because the nurse is the last check before the drug reaches the patient.
  Proceeding requires a reason, which is recorded. **(negative)**
- **AC-89** A discontinued medication has no further due doses, and the doses
  already given remain on the record. **(negative)**
- **AC-90** The MAR reads as a chart: rows are medications, columns are due
  times, and each cell states its state in words as well as colour.
- **AC-91** A dose more than a configurable window past its due time is shown as
  overdue, and overdue doses appear on a ward list.

## Inpatient clinical record

- **AC-92** A daily review is an encounter attached to the admission, versioned
  the same way an outpatient consultation is: amending it appends a version with
  author and reason, and never alters an earlier one. **(negative)**
- **AC-93** Inpatient investigations and imaging are ordered against the
  admission and appear on the patient's record alongside outpatient ones.

## Imaging

- **AC-94** An imaging catalogue is administrable: modality, body part,
  preparation instructions and price.
- **AC-95** An imaging order records the requesting clinician and the clinical
  question, and moves through requested → scheduled → performed → reported →
  verified without skipping. **(negative)**
- **AC-96** A report carries findings and a conclusion, is verified by someone
  holding the verification permission, and an unverified report does not reach
  the requesting clinician as a finding. **(negative)**
- **AC-97** Amending a verified report appends a version with a reason; the
  superseded report stays on the record and prints as amended. **(negative
  without a reason)**
- **AC-98** A critical imaging finding raises the same acknowledgement
  requirement as a critical laboratory result.

## Discharge

- **AC-99** Discharge planning records the expected date, the destination and
  what has to happen first, and appears on a ward list.
- **AC-100 (the gate)** A discharge cannot complete while inpatient charges are
  unbilled or the admission's invoice has an outstanding balance, unless someone
  holding the override permission records a reason. **(negative)**
- **AC-101** Discharging closes the bed occupancy, frees the bed for cleaning
  rather than straight to available, and closes the admission.
- **AC-102** A discharge summary is produced containing the admission and
  discharge diagnoses, what was done, the discharge medication and the follow-up
  instructions — assembled from the record, not retyped.
- **AC-103** Discharge medication is a prescription the pharmacy can dispense,
  not free text. **(negative:** free-text discharge drugs are not accepted where
  a formulary entry exists.**)**
- **AC-104** The discharge summary is printable and reprints identically, with
  reprints logged.
- **AC-105** Discharge is audited with both diagnoses, the destination and the
  length of stay.

## Inpatient billing

- **AC-106** Bed usage is charged per night from the occupancy, at the ward's
  configured rate, without anyone typing it. Charges are idempotent per night.
  **(negative on double-charging)**
- **AC-107** A part-night at admission and at discharge is charged by the
  hospital's configured rule, and the rule is stated on the invoice line rather
  than being implicit.
- **AC-108** Inpatient medication, investigations and procedures land on the
  admission's invoice, not on a stale outpatient one.
- **AC-109** Length of stay and total charges reconcile: a property test over
  generated admissions asserts nights charged equals nights occupied.

## Ward operations

- **AC-110** A ward view shows every occupied bed, its patient, their allergies,
  overdue doses and outstanding escalations — enough to hand over a shift from
  one screen.
- **AC-111** The emergency read-only ward snapshot required by the connectivity
  decision is generated and retrievable independently of the application being
  up: name, bed, allergies, active medication, working diagnosis, responsible
  consultant.
- **AC-112** Ward dashboards are role-aware: a nurse, a doctor and a ward
  manager see different work.

## Workflow integration

- **AC-113** One automated test drives the whole inpatient stay through the API:
  admission request → admit → allocate bed → nursing assessment → observations →
  MAR schedule → administer → daily review → investigation → transfer →
  discharge planning → final billing → payment → discharge — then asserts the
  stay is reconstructable from the patient's record alone and that every step
  produced audit rows.
- **AC-114** The same walk with one permission missing at each step fails at
  exactly that step and no earlier. **(negative)**

## Performance and operations

- **AC-115** The ward view for a 40-bed ward with a full complement of patients,
  medications and observations loads in **under 500 ms p95**, measured under 50
  concurrent users.
- **AC-116** The MAR for one patient with 20 active medications over a 7-day stay
  loads in **under 400 ms p95**.
- **AC-117** Every Phase 2 screen is completable by keyboard and passes the same
  accessibility checks as Phase 1.
- **AC-118** Migrations run forward from the Phase 1 release against a database
  holding Phase 1 data, and the restore drill passes with inpatient data present.
