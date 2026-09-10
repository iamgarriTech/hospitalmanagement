# VitaCore

A hospital management system for a hospital group: one record per patient, from
the front desk to the ward and back to the cash desk. Branches, pharmacies,
laboratories and stores share one deployment and keep their own prices, stock,
staff and rules.

Django REST Framework, Next.js, PostgreSQL. Intended for real hospital use, and
built for a Nigerian hospital first — most bills are split with an HMO, the
server lives in the building because the internet is not reliable, and the drug
catalogue is the hospital's own.

**[Read the product guide](docs/product-guide.md)** — what it does, who does it,
what it guarantees, and what it deliberately does not do.

## Running it

PostgreSQL 18 and the Python and Node already on your machine. Development uses
the host database directly; `compose.yaml` is the on-premises install, not the
development loop.

```bash
# Backend — http://localhost:8009
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
createdb hms_dev
cp .env.example .env                              # then edit
.venv/bin/python backend/manage.py migrate
.venv/bin/python backend/manage.py seed_demo      # synthetic configuration
.venv/bin/python backend/manage.py demo_day       # synthetic activity
.venv/bin/python backend/manage.py runserver 8009

# Frontend — http://localhost:3100
cd frontend && npm install && npm run dev
```

Sign in at `http://localhost:3100`. In demo mode the sign-in screen offers one
account per role, so an evaluator can walk the whole hospital. Every screen has
work on it — patients waiting, specimens on the bench, a critical result
awaiting acknowledgement, inpatients on the wards, bills part-paid — because an
empty queue demonstrates nothing.

`demo_day` leaves the hospital mid-shift deliberately. Synthetic data only:
there is never real patient data in this repository.

> **`DEMO_MODE` must be off in any real deployment.** It makes the server hand
> working credentials to the sign-in screen. The frontend cannot decide this —
> the server withholds them, and a test asserts the password string does not
> appear in the response at all.

## Checks

The same ones CI runs. All of them gate the build; none of them print warnings
nobody reads.

```bash
# Backend
.venv/bin/ruff check .
.venv/bin/python backend/manage.py makemigrations --check --dry-run
.venv/bin/python -m pytest
.venv/bin/python backend/manage.py verify_audit_chain

# Frontend
cd frontend
npx tsc --noEmit
npm run lint        # accessibility rules are errors here, not warnings
npm test
npm run build
```

## Layout

```
backend/          Django project; one app per domain area
  accounts/       users, roles, permissions, lockout
  audit/          hash-chained, append-only audit log
  patients/       identity, duplicates, merging
  visits/         attendance and the queue
  clinical/       consultations, versioning, observations
  laboratory/     catalogue, orders, specimens, results
  imaging/        radiology catalogue, requests, reports
  inpatient/      wards, beds, admissions, drug chart, nursing
  pharmacy/       formulary, stock, prescribing, dispensing
  billing/        services, prices, invoices, payments, till
  insurance/      providers, plans, coverage, claims, settlement
  inventory/      stores, items, stock, movements, procurement
  procedures/     catalogue, consent, theatre bookings, operation notes
  maternity/      pregnancy, antenatal care, delivery, newborn records
  reporting/      live queries over everything above; no stored aggregates
  integration/    the read-only FHIR-shaped external API
  portal/         patient logins — its own accounts, sessions and cookie
frontend/         Next.js app; the browser talks only to this
docs/             the product guide, decisions, operations, acceptance criteria
scripts/          benchmarks
deploy/           on-premises install
```

The browser never calls the API directly. Next.js proxies to it server-side and
re-issues the session cookie on its own host, so the session stays first-party
and `HttpOnly` — no token in browser storage, and no CORS on the API.

## Status

All of it is built: foundation, the outpatient day, inpatient care, radiology,
insurance, the cash desk, stores, procurement, procedures and theatre,
referrals, the emergency department, maternity, reporting, the outbound message
queue, the external API facade and the patient portal.

**Read [what is not checked](docs/product-guide.md#what-it-deliberately-does-not-do)
before relying on any of it.** The running system serves the same list at
`/limitations`, assembled from the code rather than written by hand — including
every clinical default that runs on numbers **no clinician has signed off**.

Two things are outstanding, and neither is an engineering decision.

**A named clinician has to sign off the clinical content**
— medication round times, overdue windows, escalation thresholds — and the
install and restore drills need running on a hospital's own hardware. Both are
stated in the [product guide](docs/product-guide.md#before-this-runs-a-real-hospital).

## Documentation

| | |
|---|---|
| [Product guide](docs/product-guide.md) | What it does, role by role, and what it will not do |
| [Operations](docs/operations.md) | Running it, backups, the restore drill |
| [Decisions](docs/decisions.md) | Architectural choices and the reasoning |
| [Performance](docs/performance.md) | Measured figures, and the defects behind them |
| [Roadmap](docs/roadmap.md) | Phases, exclusions, release gates |
| [prd.md](prd.md) | Full domain scope — reference, not a build order |
| [CLAUDE.md](CLAUDE.md) | The constraints the code is written under |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Getting it running, the checks, and the firm rules |
| [SECURITY.md](SECURITY.md) | Reporting a vulnerability, and deploying safely |
| [LICENSING.md](LICENSING.md) | Which of the two licences applies to you |

Acceptance criteria per phase are in `docs/phase-*-acceptance.md`. Each
criterion is testable, and the ones that are *not* claimed say so.

## Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md)
for how to get it running, what the checks are, and the handful of rules that
are not negotiable in a system meant to hold patient records.

Two kinds of contribution are worth singling out:

- **Clinical corrections.** Round times, overdue windows and escalation
  thresholds here are defaults chosen by software people. If one is wrong,
  [say so](.github/ISSUE_TEMPLATE/clinical_correction.yml) — it is the most
  valuable issue you can open.
- **Security reports.** Privately, please: [SECURITY.md](SECURITY.md).

Everyone taking part is expected to follow the
[code of conduct](CODE_OF_CONDUCT.md).

## Licence

Dual-licensed — see [LICENSING.md](LICENSING.md) for which applies to you.

**[GNU AGPL v3](LICENSE)** by default. A hospital running VitaCore for its own
patients publishes nothing and owes nothing: use it, modify it, run it on your
own server. What the AGPL asks is that anyone offering a *modified* version to
other people as a network service publishes their changes.

**A commercial licence** for organisations the AGPL does not suit — a host
serving clinics it does not own, a vendor embedding it in a closed product, or
an institution whose procurement bars copyleft.

Contributions come in under the [CLA](CLA.md), which is what makes offering
both possible. You keep the copyright in what you write.

CI fails the build on any GPL, AGPL or SSPL dependency. That is not a
contradiction: we cannot relicense somebody else's copyleft code, so one in the
tree would quietly end the commercial half of that arrangement.
