# VitaCore — product guide

What the system does, who does it, and what it deliberately will not do.

This is the document to read before the code. [prd.md](../prd.md) is the full
domain scope, [roadmap.md](roadmap.md) is the build order, and the
`phase-*-acceptance.md` files are the definition of done. This one is for a
person deciding whether the product fits their hospital, or a member of staff
working out where their job lives in it.

---

## What it is

One record per patient, from the front desk to the ward and back to the cash
desk. A hospital group runs its branches, pharmacies, laboratories and stores on
a single deployment, and every branch keeps its own prices, stock, staff and
rules.

Built for a Nigerian hospital first: most bills are split with an HMO, the
internet is unreliable and the server lives in the building, and the drug
catalogue is the hospital's own rather than a US formulary. None of that is
hard-coded — it is what the defaults assume.

## Who uses it

Each role sees its own work and nothing else. Roles are database rows a hospital
creates and edits at runtime, so this list is what the demo hospital ships with,
not what the software permits.

### Front of house

**Receptionist** — registers patients, checks them in, and puts them in the
queue. Registration warns about a likely duplicate before creating one; merging
two records is a separate permission a receptionist does not hold.

**Medical Records Officer** — merges duplicates, corrects identities, and reads
the access log. The access log matters: looking at a patient's record is itself
recorded, so "who has read this chart" is answerable.

### Clinical

**Nurse** — records observations and reads charts. Cannot amend a clinical
record: correcting an observation records a new one and marks the old as an
error, so the original stays visible.

**Doctor / Consultant** — consultations, diagnoses, laboratory and imaging
requests, prescriptions. A consultation is versioned: finalising it freezes it,
and amending appends a version carrying who changed it and why. The consultant
additionally holds `override_safety_warning`, which is what allows prescribing
past a serious interaction with a recorded reason.

**Ward Doctor** — requests a bed, admits, moves patients between beds, plans and
completes discharge, and writes daily reviews. Prescribes for inpatients, which
puts doses on the drug chart automatically.

**Ward Nurse** — gives medication and records observations on the ward. Records
nursing notes, fluid balance and shift assessments. Cannot admit or discharge.

**Ward Manager** — runs the ward. The only role that can complete a discharge
with an unsettled bill, and doing so is recorded as an exception rather than as
a discharge.

### Diagnostics

**Laboratory Technician** — collects specimens and enters results. Cannot verify
them.

**Laboratory Scientist** — collects, enters, verifies and amends. Verification is
a separate permission on purpose: whoever typed a number is not automatically
the person who signs it off.

**Radiographer** — schedules examinations and records them as performed. Does
not report them.

**Radiologist** — reports, verifies and amends. **Imaging Registrar** writes
reports and cannot release them.

### Pharmacy, money and administration

**Pharmacist** — dispenses against a prescription, from a named batch, and
receives stock.

**Storekeeper** — runs a store: receives deliveries, issues to wards and
theatres, moves stock between stores, and corrects the record. Deliberately
cannot authorise their own correction — a second signature is worth nothing if
one person holds both halves of it.

**Stores Manager** — creates stores, sets what each one carries and at what
level, and authorises a colleague's correction above the store's own limit.

**Cashier** — takes payments and small discounts within a per-role limit, counts
their till at the end of a shift, and can take over a colleague's till mid-shift.
Cannot sign their own till off: counting the money and signing for it are
different acts.

**Accountant** — approves larger discounts, issues refunds, signs off each till
against its count, records corrections found afterwards, and writes off money a
scheme has not paid.

**Insurance Officer** — records policies and eligibility, requests
preauthorisation, assembles and submits claims, and records what providers pay.
Deliberately cannot write a shortfall off: the desk that raises a claim does not
decide to stop chasing it.

**Hospital Administrator** — creates roles, grants access, configures facilities,
catalogues, prices, numbering formats and insurance plans. Reads the audit log.

---

## How a day runs

### The outpatient day

Register → check in → queue → observations → consultation → laboratory or
imaging request → specimen collected → result entered → result verified →
clinician reviews → prescription → dispense → invoice → payment → visit closed.

The queue is a graph, not a line: a patient comes back from the laboratory to
the consulting room, and back again to the pharmacy. Each move records who moved
them.

### The inpatient stay

Admission request → bed allocated → observations and escalations → drug chart →
doses given → daily reviews → investigations → bed transfers → discharge plan →
final billing → payment → discharge summary.

An admission request and an admission are separate, because a clinician decides
a patient needs a bed and the ward decides which bed and when. A doctor should
not have to know whether a bed is free before asking for one.

### The cash desk

Open a till with a counted float → take payments → hand the till to the next
cashier, or close it → count the drawer, one figure per payment method → an
accountant signs it off, which freezes it → any correction found afterwards is a
new adjusting entry naming the session.

The count is per payment method rather than one figure for the drawer, because
₦5,000 short on cash against ₦5,000 over on transfers nets to zero, reconciles
clean, and hides two real mistakes.

### The store

Receive a delivery with its lot number and expiry → issue to a ward, theatre or
named person → move stock between stores → correct the record where a count
disagrees with it. Every one of those writes a movement saying what, how much,
from where, to where, why and who.

Stock leaves soonest-expiry-first, so it does not go out of date on the shelf,
and an expiry date travels with stock that moves — a ward cupboard cannot end up
holding goods it thinks are fresh.

### The claim

Charges raised during care → coverage resolved on each one → claim assembled
from those charges → submitted → acknowledged → paid, or rejected → corrected →
resubmitted once. A provider payment is applied line by line, and what a scheme
does not pay is either written off with a reason or moved to the patient with a
reason.

---

## What the system guarantees

These are properties, each with a test proving it holds. The full list and the
reasoning are in [CLAUDE.md](../CLAUDE.md); this is what they mean in practice.

**Two patients cannot be in one bed.** Not "should not" — the database refuses
overlapping occupancies. Twelve nurses pressing Admit on the same bed at the
same instant produce one allocation and eleven refusals.

**Every medication administration names who gave it and when.** A dose with no
named nurse cannot be recorded at all. The states where nothing reached the
patient — missed, refused, withheld — each require a reason, because "missed"
with no explanation is a gap somebody will have to guess about.

**A dose cannot be given twice.** A double-tapped button produces one
administration.

**Clinical records preserve history.** Amending a consultation, a result or an
imaging report appends a version with author and reason. The superseded text
stays and prints as superseded, because somebody may have made a decision on it.

**Nursing notes cannot be rewritten.** There is no edit control anywhere, and
the database refuses an UPDATE. A correction is a new note pointing at the
original.

**Coverage is frozen at the time of service.** A scheme renegotiating its rates
in March cannot change what a patient owed in February. The split is stored with
a copy of the rule that produced it.

**A resubmitted claim does not double-bill.** A charge can sit on one live claim;
a rejected claim releases its lines so the correction can pick them up.

**Reconciled money does not change.** Corrections are new adjusting entries, for
cash and for insurance alike. A signed-off till keeps the figures it was signed
off with, and the correction sits beside them with an author and a reason.

**A till cannot be counted around.** A payment taken at the instant a till is
being closed either lands before the close and is included in the figure signed
off, or is refused. It cannot end up inside a session that was closed without
seeing it — money reconciled as absent and sitting in the drawer.

**A till changes hands with two names on it.** The incoming cashier counts the
drawer and confirms the handover, so the second signature is a second person.
The float moves across whole: never in two open sessions, never in none.

**A retried request produces one charge and one payment.** Double-clicking is
safe.

**Stock cannot go negative.** Twelve storekeepers issuing the last box at the
same instant produce one issue and eleven refusals, each naming the quantity
actually available. A negative balance is a number nobody can act on and a
shortage nobody was warned about.

**Expired stock cannot be issued, and the refusal names the date.** "Cannot
issue" sends somebody looking for the problem; "expired on 03 Aug 2026" tells
them which boxes to pull off the shelf. Expired stock also stops counting
towards the reorder level, so a store holding forty expired boxes and none in
date reports as out rather than as full.

**A stock correction above a value the store sets needs a second person**, and
that person has to actually hold the authorising permission — otherwise the
control is defeated by naming any colleague with an account.

**A store's ledger reconstructs its balance at every point**, not only at the
end. A ledger that agrees only on the last row cannot say when it diverged,
which is the one question a stock discrepancy asks.

**The audit history is tamper-evident.** Every meaningful action records what
happened, who, when, to which patient, and the previous and new values. The rows
are hash-chained and the database refuses UPDATE and DELETE on them.

**A user permitted at one facility cannot read another's.** An out-of-scope
record returns "not found", never "forbidden" — because "no such patient" and "a
patient you may not see" have to be indistinguishable.

**No credential is readable by JavaScript.** The browser only ever talks to the
Next.js app, which proxies to the API server-side and re-issues the session
cookie on its own host — first-party and `HttpOnly`. There is no token in
browser storage.

**External failure never blocks clinical or financial work.** Losing the
internet cannot roll back a consultation, a dispense or a payment.

---

## What it deliberately does not do

Being clear about this is part of the product. A clinician must never infer a
check that is not running.

**No drug-interaction database.** The serious interactions are checked from a
hospital-maintained list; there is no licensed commercial database behind it,
and the prescribing screen says so. Inferring a full interaction check from a
warning that appears is exactly the failure this note exists to prevent.

**No SNOMED CT.** Its licence runs through national member affiliates and
Nigeria is not a member. Diagnoses use ICD-10 and laboratory tests a curated
LOINC subset. A recorded diagnosis carries its code system and version, so a
future code set cannot silently re-render it.

**No offline writing.** The server lives in the hospital on a UPS and browsers
work on the local network, so losing the internet does not stop clinical work.
But two nurses recording different outcomes for one medication dose have no safe
automatic merge, and picking wrong is a patient-safety event. Instead: drafts
survive a disconnect on the consultation and result screens, external calls go
through a database-backed outbox, and each ward has a printable read-only
snapshot of its inpatients so total server failure does not leave it blind.

**No Django admin.** It writes straight through the ORM, bypassing every
permission check and producing no audit rows. The administration screens are
part of the product.

**No coordination of benefits across two schemes.** A patient can hold two
policies and the hospital sets which pays first, but the first policy that pays
anything settles the charge. Splitting one charge across two schemes produces
figures nobody can explain, and no Nigerian HMO settles that way today.

**Not an ERP.** Procurement stops at purchase orders, goods received and
supplier invoices. There is no general ledger.

**Stock does not move between facilities.** Two branches can each run their own
stores on one deployment, but goods crossing from one to the other is a sale or
an inter-branch supply with its own paperwork, not a store transfer. Allowing it
as a transfer would let the audit trail go quiet exactly at the facility
boundary, which is the one place it must not.

**Modular means a hospital can leave a module unused** — not that there is a
plugin system, a config-driven clinical UI, or a rules engine. An unused module
produces no navigation entries, no empty dashboards and no required fields.

---

## What is built, and what is not

| | |
|---|---|
| **Foundation** | Facilities, roles, permissions, audit, patient identity |
| **Outpatient day** | Registration through payment, end to end |
| **Inpatient care** | Admission through discharge, including the drug chart |
| **Radiology** | Catalogue, requests, reports, verification, amendments |
| **Insurance** | Providers, plans, coverage, preauthorisation, claims, settlement |
| **Cash desk** | Tills, per-method counting, sign-off, corrections, shift handover |
| **Stores** | Items, stores, stock, movements, transfers, corrections, alerts |

Not yet built, in the order it is coming: procurement, procedures and theatre,
referrals, emergency department, maternity, reporting, an external API, and a
patient portal. The criteria for each are in
[phase-3-acceptance.md](phase-3-acceptance.md).

## Before this runs a real hospital

Two things are outstanding and neither is an engineering decision.

**A named clinician has to sign off the clinical content.** Medication round
times, the window after which a dose counts as overdue, the default escalation
thresholds, triage scales and consent wording are currently reasonable defaults
chosen by the people who built the software. The release gate in
[roadmap.md](roadmap.md) says plainly that without a named clinical reviewer the
phase does not ship and the project does not describe itself as suitable for
real hospital use. That still stands.

**The install and restore drills need running on real hardware.** The Compose
file and the backup procedure are written and the restore has been timed on a
development machine. Neither has been run on a hospital's server.

## Where to go next

- [operations.md](operations.md) — running it, backups, and the restore drill
- [decisions.md](decisions.md) — the architectural choices and why
- [performance.md](performance.md) — measured figures, and the defects behind them
- [roadmap.md](roadmap.md) — phases, exclusions and release gates
- [../CLAUDE.md](../CLAUDE.md) — the constraints the code is written under
