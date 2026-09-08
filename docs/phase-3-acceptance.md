# Phase 3 Acceptance Criteria — Completing the product

Phases 3 and 4 of [roadmap.md](roadmap.md) merged, because the goal changed: not
"the next slice" but a hospital that can run its whole day on this. Numbering
continues from Phase 2, so **AC-119 onwards**.

Same rules as before. Every criterion is testable. **(negative)** marks the ones
that test something is *refused*. Nothing is written as "where appropriate".

Built in dependency order, not all at once — one workflow reaches working
quality before the next starts, and the app stays running with tests green
throughout. The order is stated at the bottom and the reason for it is that
insurance changes the billing model: everything built on "the patient pays the
whole bill" gets more expensive to retrofit each day it stands.

## The additions to the release gate for this phase

1. **A claim resubmitted after rejection does not double-bill.** Not "should
   not" — cannot.
2. **Coverage is resolved at the time of service and stored with the charge.**
   A plan edited next month must not change what a patient owed last month.
3. **Every report respects the permission and facility boundary of the person
   running it.** A report is the classic way facility isolation leaks.
4. **Every stock movement is traceable to the act that caused it**, across
   pharmacy, general stores and theatre.

---

## Insurance: providers, plans and policies

- **AC-119** Insurance providers and HMOs are administrable: name, type, contact,
  claim submission channel, and whether they are currently accepting claims.
- **AC-120** A provider has plans; a plan states what it covers — covered
  services, exclusions, co-pay (fixed or percentage), and any per-visit or
  annual limit.
- **AC-121** A patient holds a policy: provider, plan, policy number, dependant
  status, start and end dates. Two active policies on one patient are allowed,
  with a stated order of precedence.
- **AC-122** An expired policy is not offered at the point of service, and
  cannot be selected. **(negative)**
- **AC-123** Coverage is resolved per charge and recorded on it: which policy,
  which rule, what the scheme pays, what the patient pays. The record is enough
  to explain the split to a patient afterwards without re-running the rules.
- **AC-124 (the gate)** Editing a plan or a price does not change any charge
  already raised. A property test over generated charges asserts the split
  recorded yesterday is unchanged after today's edit. **(negative)**
- **AC-125** An excluded service is charged wholly to the patient, and the
  exclusion is named on the invoice line rather than appearing as an unexplained
  amount.
- **AC-126** A service with no coverage rule at all is charged wholly to the
  patient and flagged for the billing office, not silently treated as covered.
  **(negative)**
- **AC-127** The patient-facing total on an invoice is the patient's share, and
  the scheme's share is shown separately. A cashier never asks a patient for the
  scheme's money.

## Insurance: eligibility and preauthorisation

- **AC-128** Eligibility can be recorded against a policy with the date checked,
  who checked, and the answer. An unverified policy is usable but marked as
  unverified — a hospital cannot refuse care while waiting for an HMO to answer
  the phone.
- **AC-129** A service that a plan requires preauthorisation for cannot be
  claimed without an authorisation reference. **(negative)**
- **AC-130** Preauthorisation records the request, the reference, the approving
  provider, validity dates, and what was approved. An expired authorisation does
  not satisfy AC-129. **(negative)**
- **AC-131** Care is never blocked by a missing authorisation: the service can
  proceed, the charge is raised, and the claim is held with the reason stated.
  **(negative on blocking)**

## Insurance: claims

- **AC-132** A claim is assembled from charges already raised, never retyped.
  Its lines carry the service, the date, the clinician, the diagnosis codes and
  the scheme's share.
- **AC-133** A claim moves through draft → submitted → acknowledged → paid, or
  → rejected → resubmitted, without skipping. **(negative)**
- **AC-134** A charge cannot appear on two open claims. **(negative)**
- **AC-135 (the gate)** A rejected claim resubmitted after correction produces
  one claim in the provider's hands and one expected payment, not two. Enforced
  in the database, not by a check a race can slip past. **(negative)**
- **AC-136** A rejection records the reason, the date, and which lines were
  rejected. A partly rejected claim leaves the accepted lines paid and the
  rejected ones actionable.
- **AC-137** A provider payment is reconciled against claim lines: short
  payments and rejections are visible per line, and the remainder is either
  written off with a reason or moved to the patient with a reason. **(negative
  on silent write-off)**
- **AC-138** Reconciled insurance records are immutable; corrections are new
  adjusting entries. The same guarantee as cash.
- **AC-139** An ageing report shows what each provider owes and for how long,
  scoped to the facilities the caller may see.

## Cashier reconciliation at depth

- **AC-140** A cashier's day closes with a count: expected against counted, per
  payment method, with a variance and a stated reason for any variance.
  **(negative on closing with an unexplained variance)**
- **AC-141** After reconciliation the session's payments and invoices are
  frozen; a correction is a new adjusting entry that names the session it
  corrects. **(negative)**
- **AC-142** A shift handover between cashiers on one till transfers the float
  with both signatures.

## Inventory and stores

- **AC-143** A general inventory item is administrable: category, unit of issue,
  reorder level, and whether it is a controlled item.
- **AC-144** Store locations are administrable per facility, and stock is held
  per store, not per facility. A ward store and the main store are different
  places.
- **AC-145** Every stock movement records what, how much, from where, to where,
  why, and who — receipts, issues, transfers, adjustments, damage, expiry and
  returns alike.
- **AC-146 (the gate)** Stock cannot go negative under concurrency: twelve
  simultaneous issues of the last unit produce one issue and eleven refusals.
  **(negative)**
- **AC-147** A stock adjustment requires a reason and a second person's
  authorisation above a configurable value. **(negative)**
- **AC-148** Expired stock cannot be issued, and the refusal names the expiry
  date. **(negative)**
- **AC-149** Low-stock and expiry alerts are per store and per item, driven by
  the reorder level and a configurable expiry horizon.
- **AC-150** An item's history reconstructs its balance: a property test over
  generated movements asserts the running balance equals the recorded stock on
  hand at every point.

## Procurement

- **AC-151** Suppliers are administrable with contact, payment terms, and whether
  they are currently approved to supply.
- **AC-152** A purchase request records the requester, the store, the items and
  the justification, and requires approval above a configurable value.
  **(negative)**
- **AC-153** An approver cannot approve their own request. **(negative)**
- **AC-154** A purchase order is raised from an approved request and carries the
  supplier, the agreed prices and the expected date.
- **AC-155** Goods received are recorded against the order line by line, with
  batch numbers and expiry dates, and a short delivery leaves the order line
  open rather than closing it. **(negative)**
- **AC-156** Receiving goods creates the stock movement that puts them on the
  shelf — a receipt with no movement, or a movement with no receipt, cannot
  exist. **(negative)**
- **AC-157** A supplier invoice is matched against what was ordered and what
  arrived; a mismatch is surfaced rather than paid.

## Procedures and theatre

- **AC-158** A procedure catalogue is administrable: name, category, typical
  duration, consumables, and price.
- **AC-159** A procedure request records the requesting clinician, the
  indication, and consent where the procedure requires it. **(negative without
  consent where required)**
- **AC-160** A performed procedure records the team, the findings, the outcome,
  the consumables used and the medication given — and the consumables come off
  stock.
- **AC-161** Theatre rooms and sessions are schedulable, and two operations
  cannot be booked into one theatre at the same time. Enforced by the database.
  **(negative)**
- **AC-162** An operation note is a versioned clinical record: amending appends
  a version with author and reason. **(negative)**
- **AC-163** A procedure bills once, from the act of performing it, not from the
  request. **(negative on billing a cancelled procedure)**

## Referrals

- **AC-164** An internal referral moves a patient to another department or
  clinician with the reason and the clinical question, and appears on the
  receiving clinician's list.
- **AC-165** An external referral records the destination, the reason, what was
  sent, and the outcome when it comes back.
- **AC-166** A referral letter is generated from the record, reprints
  identically, and reprints are logged.

## Emergency department

- **AC-167** A patient can be registered in under the configured number of
  fields, and an unidentified patient can be registered without a name, then
  merged when identified without losing anything recorded under the temporary
  identity. **(negative on loss)**
- **AC-168** Triage assigns a severity on a configurable scale, and the queue
  orders by severity before arrival time.
- **AC-169** A deteriorating patient's re-triage is recorded as a new
  assessment, not an edit, and the original stays. **(negative)**
- **AC-170** An emergency episode ends in exactly one outcome — admitted,
  transferred, referred, discharged, died, or left without being seen — and the
  outcome is recorded with a time. **(negative on two outcomes)**

## Maternity

- **AC-171** A pregnancy record carries the estimated delivery date, its basis,
  and the antenatal visits against it.
- **AC-172** A delivery record links mother and baby, and the baby is a patient
  in their own right with their own record from birth. **(negative on a baby
  with no record)**
- **AC-173** Maternity can be left unused by a hospital that does not provide
  it, with no empty screens in the navigation. **(negative)**

## Reporting

- **AC-174 (the gate)** Every report is scoped to the facilities and permissions
  of the person running it. A test runs each report as a user restricted to one
  facility and asserts no other facility's data appears in any row, total or
  count. **(negative)**
- **AC-175** The clinical, financial, pharmacy, laboratory and inpatient report
  sets each answer the questions their department actually asks, with the date
  range and facility as filters.
- **AC-176** A report states the moment it was run and the filters that produced
  it, so two people comparing printouts can tell why they differ.
- **AC-177** Every report exports to CSV with the same rows it shows on screen,
  and the export is audited with the filters used.
- **AC-178** No report is served from a stored aggregate that could drift; where
  one is introduced for measured performance reasons, a test asserts it agrees
  with the live query.

## External API and integration

- **AC-179** A versioned read-only API facade exposes patient, encounter,
  observation, medication and result resources in a FHIR-shaped form, and its
  version is in the path.
- **AC-180** The facade enforces the same permissions and facility scoping as
  the internal API, tested with a token restricted to one facility. **(negative)**
- **AC-181** Notification channels (SMS, email) send through the database-backed
  outbox: an unavailable provider delays delivery and never fails or rolls back
  the clinical or financial write that triggered it. **(negative)**
- **AC-182** A failed external send is retried with backoff, is visible as
  failed after the retries, and never silently disappears. **(negative)**

## Patient portal

- **AC-183** A patient can see their own appointments, verified results, active
  medication and bills — and nothing else, ever, including no other patient's
  data through any parameter. **(negative)**
- **AC-184** Portal authentication is separate from staff authentication, with
  no shared session and no staff permission reachable from a portal account.
  **(negative)**
- **AC-185** An unverified result never appears in the portal. **(negative)**

## Operations and honesty

- **AC-186** A hospital can leave any module unused, and unused modules produce
  no navigation entries, no empty dashboards and no required fields. **(negative)**
- **AC-187** Every screen added in this phase is keyboard-completable and passes
  the same accessibility checks as Phases 1 and 2.
- **AC-188** Migrations run forward from the Phase 2 release against a database
  holding Phase 2 data, and the restore drill passes with insurance, stock and
  theatre data present.
- **AC-189** Any safety or coverage check that is absent, unlicensed or
  unverified is stated plainly in the UI and the README. A clinician or a
  cashier must never infer a check that is not running.

---

## Build order

Dependency order, not preference. Each block reaches working quality before the
next starts.

1. **Insurance** — providers, plans, policies, coverage resolution, then
   preauthorisation, then claims, then provider payments and reconciliation.
   First because it changes what an invoice *means*, and everything built on
   "the patient pays the whole bill" gets more expensive to retrofit daily.
2. **Cashier reconciliation at depth** — small, and it completes the money
   story insurance opens.
3. **Inventory and stores**, then **procurement** on top of it. Procurement
   without somewhere to put the goods is a form that does nothing.
4. **Procedures**, then **theatre** on top of procedures. Theatre is a procedure
   with a room and a team.
5. **Referrals** and **emergency department** — both reuse triage, queue and
   admission, which exist.
6. **Maternity** — modular, and depends on the patient-linking work being solid.
7. **Reporting** — last of the internal work, because it reports on all of the
   above and a report written against half the schema gets rewritten.
8. **External API facade**, **notification channels**, then **patient portal**.
   The portal is last: it is the only outward-facing surface, and it should be
   built against a schema that has stopped moving.

## What needs a decision that is not mine

- **Release gate 1 — clinical sign-off.** Phase 2 shipped MAR round times
  (08:00/14:00/20:00), a 60-minute overdue window, and default escalation
  thresholds. Phase 3 adds triage scales and consent wording. The roadmap says
  plainly that without a named clinical reviewer the phase does not ship and the
  project does not describe itself as suitable for real hospital use. Those
  numbers are currently mine, and I am not a clinician.
- **Patient portal scope.** AC-183 to AC-185 open the only externally reachable
  surface in the system. It is the one place where a mistake is a public data
  breach rather than an internal one, and it deserves an explicit decision to
  build rather than being swept in with everything else.
