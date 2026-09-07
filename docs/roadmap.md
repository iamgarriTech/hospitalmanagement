# Roadmap and Phasing

`prd.md` is the domain specification: what a mature system covers. It is deliberately
broad and it is **not** a work order. This document is the work order.

The rule for the whole project: **one vertical workflow reaches production quality
before the next one starts.** A module is not "done" because its screens render. It is
done when the acceptance criteria for its phase pass, including the negative tests.

## Why phase at all

The PRD lists 35+ modules at equal weight and a 17-item Definition of Done where every
item is mandatory. Built in that order, the result is 35 modules that look complete and
none that a hospital can run a clinic day on. In healthcare that is worse than an
honestly narrow tool, because staff trust what the screen implies.

Depth first. Breadth on a schedule.

---

## Phase 0 — Foundation (no clinical features)

Everything downstream depends on these being right, and all of them are expensive to
retrofit.

- Repository, CI, `docker compose up` working for a fresh clone
- Postgres schema baseline + versioned migration tooling; migrations are reviewable SQL
- Authentication (self-hosted sessions), password policy, brute-force lockout
- RBAC: roles are data, not code. Permissions are granular verbs on resources
- `facility_id` present and non-null on every operational table, enforced in the data layer
- Append-only audit log with hash chaining; app DB role has no UPDATE/DELETE on it
- Synthetic demo-data seeding harness (no real data, ever)
- Secret scanning in CI; dependency license check in CI

**Gate:** a user logs in, is denied an action they lack permission for, and both the
denial and the successful actions appear in the audit log with actor, timestamp,
affected resource, and before/after values.

## Phase 1 — The outpatient day (the first vertical slice)

The single workflow, end to end, for one facility:

```
register → check-in → queue → vitals/triage → consultation → lab order
→ specimen collection → result entry → verification → clinician review
→ prescription → pharmacy dispense → invoice → payment → visit closed → history
```

Included: patient registration and duplicate detection, patient search, the queue with
real movement states, encounters with amendment history, vitals, diagnoses (ICD-10),
prescriptions, the lab catalogue with multi-parameter results and reference ranges,
critical-result flagging, dispensing with stock decrement and batch tracking, invoicing,
payments, receipts, and role-aware dashboards for the six roles that touch this flow.

Also included, because the flow cannot be configured without them: the nine Phase 1
administration screens: facilities/departments/clinics, roles and permissions, services
and prices, the laboratory test catalogue, the medication catalogue, payment methods, and
numbering formats. There is no Django admin — the
configuration UI is part of the product and goes through the same permission and audit
path as everything else.

**Explicitly excluded from Phase 1** — do not start these, do not stub them in the nav:
inpatient/admissions, beds, MAR, nursing, emergency department, imaging, theatre,
procedures, maternity, insurance claims, procurement, purchase orders, referrals,
patient portal, notifications beyond in-app, reporting beyond the Phase 1 set,
multi-facility UI, any public API.

Acceptance criteria: [phase-1-acceptance.md](phase-1-acceptance.md)

## Phase 2 — Inpatient care

Admission requests and admission, ward/room/bed allocation with overlap prevented at the
database level, bed transfers with traceable movement history, inpatient clinical notes,
nursing assessments and notes, the medication administration record with its full state
set, daily reviews, discharge planning, discharge summary, discharge medication, final
billing. Basic imaging orders and reports (no PACS).

Gate additions: no two patients can occupy one bed under concurrent writes; every MAR
entry names who administered and when; a discharge cannot complete with unreconciled
inpatient charges.

## Phase 3 — Money and materials at depth

Insurance/HMO: providers, plans, patient policies, coverage rules, preauthorization,
claims, rejection and resubmission, provider payments, reconciliation. Cashier sessions
and daily reconciliation with post-reconciliation immutability. Inventory and stores
beyond pharmacy: suppliers, purchase requests with approval, purchase orders, goods
received, transfers, adjustments, expiry and low-stock alerts. The reporting and
analytics set with permission-respecting filters.

## Phase 4 — Reach

Versioned external API facade (FHIR-shaped read endpoints first), referrals, procedures,
theatre/surgery, maternity, patient portal, notification channels (SMS/email via the
outbox), import/export with permission enforcement, emergency department workflows.

## Phase 5 — Only if the business asks

Multi-organization control plane. This provisions isolated instances; it
does not convert the schema to shared-table multi-tenancy.

---

## Release gates (every phase, not just Phase 1)

1. **Clinical review.** A named, qualified clinician signs off on the workflows in the
   phase before release. Triage scales, critical-result thresholds, MAR timing windows,
   dose-check rules, and consent wording are not engineering decisions. Without a named
   reviewer the phase does not ship, and the project does not describe itself as
   suitable for real hospital use.
2. **Security review.** Permission boundaries have negative tests. Every new endpoint is
   checked for authorization, input validation, and audit coverage.
3. **Migration drill.** Migrations run forward against a seeded database from the
   previous release, on a copy of realistic-volume data. Self-hosted deployments upgrade
   on their own schedule, so every release must be reachable from the one before it.
4. **Backup and restore drill.** A restore from backup is performed and timed. An
   untested backup is not a backup.
5. **Honest-capability check.** Any safety feature that is absent or unlicensed is stated
   plainly in the UI and README. A clinician must never infer a check
   that is not running.

Decisions and their reasoning: [decisions.md](decisions.md).
