# Decisions

Why things are the way they are. Mechanisms named here are what worked in the
reasoning — not mandates.

**Stack.** Django  + DRF, PostgreSQL 18, Next.js + React + TypeScript. DRF
serializers → drf-spectacular → OpenAPI → generated TS client; CI fails if the committed
client is stale. TanStack Query on the client. pytest + pytest-django, Playwright for the
end-to-end flow. Chosen over an all-TypeScript stack mainly because Django's ORM expresses
the PostgreSQL constraints this product depends on natively (`ExclusionConstraint`,
partial `UniqueConstraint`, trigram search), and because Phase 4 imaging and
interoperability rest on Python libraries — `pydicom`, `hl7apy`, `fhir.resources` — with
no mature TypeScript equivalents.

**Deployment and tenancy.** One deployment serves one organization, on-premises by
default, same artifact runnable as a managed cloud instance. Own database per customer —
no shared-table multi-tenancy, no `organization_id` discriminator. Facility is a
dimension *inside* a tenant (`facility_id` everywhere); branches, pharmacies, labs and
wards of one hospital group live in one database. Separate databases make cross-customer
leakage structurally impossible rather than merely tested for. Multi-organization, if it
ever happens, is a control plane that provisions isolated instances.

**Connectivity.** LAN-first: server in the hospital on a UPS, browsers on the local
network, so internet loss doesn't stop clinical work. **No offline write replication** —
conflicting clinical writes (two nurses recording different states for one medication
dose) have no safe automatic merge, and picking wrong is a patient-safety event. Instead:
a database-backed outbox for every external call, draft persistence on the consultation
and result-entry screens, and a per-ward read-only snapshot of active inpatients so total
server failure doesn't leave a ward blind.

**Clinical terminology and drug data.** Ship ICD-10 (WHO) for diagnoses and a curated
LOINC subset for lab test identity. **No SNOMED CT** — its licence runs through national
member affiliates and Nigeria isn't a member. Medication catalogue is hospital-owned,
seeded from the Nigeria Essential Medicines List; RxNorm is US-market-specific and is not
the source of truth. **No bundled drug-interaction database** — the serious ones are
commercially licensed and can't ship in a repo. Interaction checking is a pluggable
`InteractionProvider` with no default. Five checks ship that need no licensed data:
allergy match, therapeutic duplication, dose range, special-population flags, and
pharmacist-maintained contraindications. **The prescribing UI must state that drug–drug
interaction checking is not running** — a clinician who assumes a check exists prescribes
as though it does.



**Licensing.** Proprietary for now, developed as though already public, because
open-sourcing later is a possibility worth keeping cheap. Four rules preserve it: keep
copyright consolidated (CLA + DCO before any external merge — this is what otherwise
traps projects in their first licence); never commit a secret, since publication
publishes the whole history; avoid copyleft *dependencies*, enforced in CI, or a
permissive licence is foreclosed; keep licensed clinical content out of the tree. Root
`LICENSE` reads "All rights reserved" until the choice is made. When it is, the
recommendation is AGPL-3.0 plus a commercial dual licence.
