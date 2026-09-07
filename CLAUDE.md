# Hospital Management System

Django REST Framework backend, Next.js frontend, PostgreSQL. Intended for real hospital
use, so the constraints below are not style preferences.

Full domain scope is in `prd.md` — reference, not a build order.
Phase plan: `docs/roadmap.md`. Definition of done: `docs/phase-1-acceptance.md`.
Decisions and their reasoning: `docs/decisions.md`.

## Local environment

- PostgreSQL 18 already running on 5432, connects as the local user. `btree_gist`,
  `pg_trgm`, `pgcrypto`, `uuid-ossp` available.
- **Docker is not installed. Never run `docker` or `docker compose`.** Write the Compose
  file as the install deliverable; don't execute it.
- Python 3.14 + Django 6.1, in `.venv/` at the repo root. **Use the Python and Node
  already on this machine.** Do not install language runtimes, do not change global
  tooling, do not tell the user to upgrade theirs.
- Use `npm` (the installed `pnpm` wants a newer Node than is here).
- No Redis, no broker. The task queue is database-backed.

## Build order

Phase 0 foundation, then Phase 1 in workflow order: register → check-in → queue → vitals
→ consultation → lab order → collection → result → verification → clinician review →
prescription → dispense → invoice → payment → visit closed.

One workflow reaches working quality before the next starts. Build each configuration
screen when the slice that needs it arrives. Keep the app running and tests green
throughout.

## Guarantees the system must hold

These come from `prd.md`; they are properties a hospital depends on, and each needs a
test proving it holds. **How you achieve them is your call** — schema shape, constraint
type, and mechanism are engineering decisions, not mine. `docs/decisions.md` notes
mechanisms that work well for some of these; treat them as suggestions.

1. **Multi-facility isolation.** A hospital group's branches, pharmacies, labs and stores
   share one deployment, with per-facility prices, services, inventory and staff. Data and
   configuration scope to a facility, and a user permitted at one facility must not read
   another's. Worth settling early — retrofitting facility scoping onto populated clinical
   tables is a migration nobody enjoys.
2. **Audit history is tamper-evident and not rewritable by the application.** For every
   meaningful action: what happened, who, when, which patient or resource, and the
   previous/new values.
3. **Clinical records preserve history.** Amending creates a version carrying author,
   time, and reason; it never overwrites, and it never alters a different encounter.
4. **Permissions are configurable at runtime and enforced server-side.** Hospital admins
   create roles; nothing about them is hard-coded. Every boundary has a test proving it
   refuses.
5. **Concurrency cannot break invariants.** Two staff acting at the same instant must not
   double-book a bed, double-charge a patient, double-record a payment, or drive stock
   negative. Checks a race can slip past don't satisfy this.
6. **Reconciled financial records are immutable.** Corrections are new adjusting entries.
7. **Duplicate submission is safe.** A double-clicked button or a retried request produces
   one charge and one payment.
8. **Coded clinical data survives code-set changes.** A diagnosis recorded today must not
   re-render differently under a future code set, and must be able to carry more than one
   coding system.
9. **No authentication credential readable by JavaScript.** Patient records make an XSS
   payoff too expensive. The frontend and API sit on **different domains**, so the browser
   talks only to Next.js, which proxies to Django server-side and re-issues the session
   cookie on its own host — first-party, `HttpOnly`, and unaffected by third-party cookie
   blocking. No JWT in browser storage, no CORS on Django.
10. **External-service failure never blocks a clinical or financial write.** Internet loss
    must not roll back a consultation, a dispense, or a payment.
11. **No `django.contrib.admin`** — not installed, not mounted. It bypasses permissions and
    audit entirely.
12. **No secrets and no real patient data in the repo, ever.** Synthetic data only.

## Conventions

Idiomatic Django, DRF, and Next.js. Use Django's own auth, permission table, migrations,
storage API, and i18n rather than reimplementing them. One Django app per domain area
(patients, encounters, laboratory, pharmacy, billing) — organise by feature, not layer.

## Don't over-engineer

- One project, one database, one deployment unit. No microservices, event sourcing, CQRS,
  Celery, Redis, or GraphQL.
- No service or repository layer over the ORM. Behaviour on models and plain functions;
  views and serializers stay thin. No base ViewSet hierarchy beyond DRF's generics.
- Two validation layers: DRF serializers server-side, Zod client-side for form UX. The
  database constraints are the third and they're declarative.
- No abstraction until a second real caller exists. No abstract base class with one
  subclass. Django's storage API is the file abstraction — don't wrap it. The only
  bespoke interface is `InteractionProvider`.
- Shared list/form machinery is expected for **configuration** screens. Never for
  clinical, prescribing, dispensing, or billing screens — those are hand-designed.
- "Modular" means a hospital can leave modules unused. Not a plugin system, config-driven
  clinical UI, or rules engine.
- No caching or extra indexes without a measurement.

## Reporting

Run the tests and show the output. Don't claim a criterion passes without a test proving
it. If something is unfinished, say so — no stubs presented as complete.
