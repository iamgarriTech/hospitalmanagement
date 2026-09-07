# Phase 1 Acceptance Criteria

Scope: the outpatient day, one facility. See [roadmap.md](roadmap.md) for what is
excluded.

Every criterion below is testable. "Where appropriate" does not appear in this document
on purpose — the PRD uses that phrase 20 times, and for the phase actually being built
it has to be replaced with something a test can fail against.

Each item is written as **AC-n** and must have at least one automated test. Items marked
**(negative)** test that something is *refused* — those are the ones that matter most.

---

## Identity, access, audit

- **AC-1** A role created at runtime with only `patient:read` can open a patient profile
  and cannot reach the billing screen or any billing endpoint. **(negative)**
- **AC-2** Permission checks are enforced server-side. Removing the client-side guard and
  calling the endpoint directly still fails with 403. **(negative)**
- **AC-3** Every mutation writes one audit row containing actor, timestamp, action,
  patient/resource id, and before/after values for changed fields.
- **AC-4** The application database role cannot UPDATE or DELETE audit rows. Attempting
  it errors. **(negative)**
- **AC-5** Audit rows carry a hash of the previous row; altering any historical row out
  of band is detectable by a chain-verification command.
- **AC-6** Ten failed logins for one account within the lockout window lock it, and the
  failures are audited. **(negative)**
- **AC-7** Viewing a patient record writes an access-log entry. A "who accessed this
  patient" view exists and is itself permission-gated.

## Patient registration and identity

- **AC-8** Registering a patient issues a hospital number in the configured format,
  unique under concurrent registration (two simultaneous registrations never collide).
- **AC-9** Registering a patient whose name + date of birth + phone closely match an
  existing record surfaces the suspected duplicate **before** the record is created, with
  the option to open the existing patient instead.
- **AC-10** Duplicate detection is not a hard block: an authorized user can deliberately
  create a genuine near-duplicate, and that override is audited with a reason.
- **AC-11** Merging two patients preserves every encounter, prescription, result,
  invoice, and payment from both. Nothing is deleted; the merged-away record remains
  resolvable and points to the survivor.
- **AC-12** Allergies, blood group, genotype, and chronic conditions are visible on the
  patient header on every clinical screen without an extra click.

## Search and performance

- **AC-13** Patient search by hospital number, name, phone, or date of birth returns
  correct results, and p95 latency is **under 300 ms with 500,000 patients seeded**.
- **AC-14** Opening a patient profile with 200 historical encounters renders in **under
  1 s p95** under 50 concurrent users.
- **AC-15** The queue view for a clinic with 150 waiting patients loads in **under 500 ms
  p95** and reflects state changes made by another user within 5 seconds.
- **AC-16** Load target for the phase: **200 concurrent staff sessions** on the reference
  single-server install without error-rate increase.

## Queue and check-in

- **AC-17** Queue state transitions follow a defined state machine. An invalid transition
  (e.g. `completed` → `in consultation`) is refused by the server. **(negative)**
- **AC-18** Every queue transition records who moved the patient and when; the patient's
  movement through the visit is reconstructable from that history.
- **AC-19** Two staff calling the same patient concurrently results in one call, not two;
  the loser sees the current state, not a silent overwrite.

## Consultation and clinical history

- **AC-20** Editing a saved encounter creates a new version. The prior version remains
  retrievable with its original author, timestamp, and values.
- **AC-21** Amending a past encounter never mutates a different encounter's recorded
  diagnosis. A test asserts an older encounter's diagnosis is byte-identical after a
  later one is amended. **(negative)**
- **AC-22** An amendment requires a reason, and the reason is stored on the version.
- **AC-23** A consultation note draft survives a transient disconnect: the client retains
  typed content locally and shows an explicit saved/unsaved indicator.
- **AC-24** Vitals are stored with units and timestamps, and a trend view plots a series
  over time for temperature, blood pressure, pulse, respiratory rate, SpO2, and weight.
- **AC-25** BMI is derived, not free-typed, and recalculates when height or weight changes.

## Laboratory

- **AC-26** A single ordered test can carry multiple result parameters, each with its own
  unit and reference range. A full blood count entered as one test produces one report
  with all its parameters. **(negative on the naive model:** a test that assumes one
  test = one value fails this.**)**
- **AC-27** Reference ranges resolve by the patient's sex and age band where the test
  defines them.
- **AC-28** Results outside the reference range are flagged, and the flag is conveyed by
  text/icon as well as color (accessibility).
- **AC-29** A result classified critical raises a notification to the ordering clinician,
  and the acknowledgement — who, when — is recorded and queryable.
- **AC-30** An unverified result is not visible to the ordering clinician as a final
  result. Verification is a distinct permission from result entry. **(negative)**
- **AC-31** Correcting a verified result creates an amendment; the superseded value stays
  on the record and the printed report shows it as amended.
- **AC-32** Specimen collection produces a sample identifier, and the order's status
  reflects collection → processing → resulted → verified without skipping states.

## Prescribing and pharmacy

- **AC-33** Prescribing a drug the patient is recorded as allergic to raises an
  interruptive warning naming the allergy; proceeding requires an explicit reason that is
  stored. **(negative)**
- **AC-34** Prescribing a second drug with an ingredient already active for the patient
  raises a therapeutic-duplication warning.
- **AC-35** A dose outside the catalogue's min/max for that route and age band is flagged.
- **AC-36** The prescribing screen states plainly which safety checks are active and that
  drug–drug interaction checking is **not** running unless a provider is configured
  is configured. This is an acceptance criterion, not documentation.
- **AC-37** Dispensing decrements stock for the specific batch dispensed and records
  batch and expiry against the dispense.
- **AC-38** Dispensing an expired batch is refused. **(negative)**
- **AC-39** Stock cannot go negative through any dispensing path, including two
  pharmacists dispensing the last unit concurrently. **(negative)**
- **AC-40** Partial dispensing leaves the prescription's outstanding quantity correct, and
  a second partial dispense cannot exceed the remainder. **(negative)**
- **AC-41** A dispense appears in the patient's medication history and writes an audit row.

## Billing and payment

- **AC-42** Charges are generated from clinical events (consultation, each lab test, each
  dispensed item) rather than typed by hand.
- **AC-43** Submitting the same charge-generating action twice — a double-clicked button,
  a retried request with the same idempotency key — produces one charge, not two.
  **(negative)**
- **AC-44** Recording the same payment twice with the same idempotency key produces one
  payment. **(negative)**
- **AC-45** A discount beyond the acting user's configured limit is refused and requires
  a user with the approving permission. **(negative)**
- **AC-46** Refunds require the refund permission, a reason, and appear in audit with the
  original payment referenced. **(negative)**
- **AC-47** Once a cashier session is reconciled, its payments and invoices cannot be
  edited or deleted by any application role. Corrections happen as new adjusting entries.
  **(negative)**
- **AC-48** Invoice totals equal the sum of their items after discount and tax, asserted
  by a property test over generated invoices.
- **AC-49** A receipt reprint is identical to the original and is logged as a reprint.

## Workflow integration

- **AC-50** One end-to-end automated test drives the full Phase 1 flow through the UI:
  register → check-in → vitals → consultation → lab order → collection → result →
  verification → clinician review → prescription → dispense → invoice → payment →
  visit closed, then asserts the completed visit is reconstructable from patient history
  alone, and that every step produced audit rows.
- **AC-51** The same test run as a user missing one permission at each step fails at
  exactly that step. **(negative)**

## Configuration and the admin boundary

- **AC-57** `django.contrib.admin` is not in `INSTALLED_APPS` and is not mounted at any
  URL. A test asserts both. **(negative)**
- **AC-58** Configuration writes go through the same permission and audit path as
  clinical writes: changing a service price, a laboratory reference range, or a role's
  permissions is refused without the relevant permission and produces an audit row with
  before/after values. **(negative)**
- **AC-59** The nine Phase 1 configuration areas (facilities, departments, clinics; roles
  and permissions; services and prices; laboratory test catalogue with panels,
  parameters, units and reference ranges; medication catalogue with strength, form, route
  and dose ranges; payment methods; numbering formats) are each administrable in the
  application without touching source code or the database directly.
- **AC-60** No configuration area required only by a later phase is present — no wards,
  rooms, beds, suppliers, inventory items, or insurance providers. **(negative)**

## Dashboards, accessibility, operations

- **AC-52** Six role dashboards (doctor, nurse, receptionist, pharmacist, lab scientist,
  cashier) each show only work items actionable by that role. No shared statistics page
  standing in for all six.
- **AC-53** The Phase 1 screens are keyboard-navigable end to end: patient search,
  vitals entry, consultation, result entry, and payment can each be completed without a
  mouse.
- **AC-54** Automated accessibility checks pass on Phase 1 screens; no status is conveyed
  by color alone.
- **AC-55** `git clone` → documented setup → `docker compose up` → seeded demo hospital →
  log in as each of the six roles and walk the flow, with no manual data entry.
- **AC-56** A backup taken during the flow restores to a consistent state with no
  half-completed visit, and the restore is documented and timed.
