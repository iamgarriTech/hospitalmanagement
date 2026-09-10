# Decisions

Why things are the way they are. Mechanisms named here are what worked in the
reasoning — not mandates.

**Stack.** Django  + DRF, PostgreSQL , Next.js  + TypeScript. DRF
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



**Licensing — decided.** **AGPL-3.0, plus a commercial licence**, as this document
recommended while the choice was open. `LICENSE` is the AGPL text;
[LICENSING.md](../LICENSING.md) says which of the two applies to whom.

The AGPL was chosen over a permissive licence for one reason: section 13. A hospital
running VitaCore for its own patients owes nothing, but anyone offering a *modified*
version to other people as a service has to publish their changes. Without that, the
predictable outcome for a system like this is a vendor taking the work, improving it,
selling it back to Nigerian hospitals as a hosted product, and keeping the
improvements. The commercial licence exists for the cases the AGPL genuinely does not
fit — a host that cannot publish, a vendor embedding it, an institution whose
procurement bars copyleft — and it is what makes the project fundable without closing
it.

Three of the four preserving rules stay, and one changes shape:

- **Copyright stays consolidated.** [CLA.md](../CLA.md) plus DCO sign-off on every
  commit. This is not optional under dual-licensing: a contribution received under the
  AGPL alone could never appear in a commercially licensed copy, and the second licence
  would stop being offerable without anybody noticing until a customer asked.
  Contributors keep their copyright; the CLA grants a licence and assigns nothing.
- **Never commit a secret.** Publication publishes the whole history. CI runs gitleaks
  over the full history, not just the diff.
- **No GPL, AGPL or SSPL dependencies** — still enforced in CI, and now for a sharper
  reason than before. It is not that they clash with our licence; they clash with the
  *commercial* one, because we have no right to relicense somebody else's copyleft
  code. LGPL is allowed and reported on every run: it exists to permit an unmodified
  library being used from a differently-licensed program, and Next.js reaches libvips
  through sharp for image handling.
- **Licensed clinical content stays out of the tree.** Unchanged, and the reason is in
  the SNOMED CT decision above.

**No per-file licence headers.** The FSF recommends one at the top of every source
file. 350-odd files of boilerplate would bury the comments that explain *why* code is
shaped the way it is, which are the ones a maintainer actually needs. `LICENSE`,
`LICENSING.md` and the README statement are unambiguous about what the terms are, and
that is what the terms have to be: unambiguous.
