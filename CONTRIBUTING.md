# Contributing to VitaCore

Thanks for looking. This is a hospital system, so a few of the rules below are
firmer than you may be used to. They exist because the cost of getting them
wrong is a patient record, a drug chart, or somebody's money.

## Before anything else

Read [the product guide](docs/product-guide.md). It says what the system does,
what it guarantees, and — just as importantly — what it deliberately does not
do. A pull request that adds a clinical check the guide says is absent will be
turned down, because a clinician inferring a check that is not running is the
failure mode the whole document exists to prevent.

[CLAUDE.md](CLAUDE.md) is the short version of the engineering constraints. It
is written for both people and coding agents.

## Getting it running

PostgreSQL 18, and whatever Python and Node you already have. Nothing here
needs a specific patch version.

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
createdb hms_dev
cp .env.example .env                              # then edit
.venv/bin/python backend/manage.py migrate
.venv/bin/python backend/manage.py seed_demo      # synthetic configuration
.venv/bin/python backend/manage.py demo_day       # synthetic activity
.venv/bin/python backend/manage.py runserver 8009

cd frontend && npm install && npm run dev         # http://localhost:3100
```

Sign in at `http://localhost:3100`. In demo mode the sign-in screen lists one
account per role, so you can walk the whole hospital without creating anything.

## The checks

Run these before opening a pull request. CI runs the same ones and they all
gate the build.

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

## The rules that are not negotiable

These come from [CLAUDE.md](CLAUDE.md) and each has tests behind it. A change
that weakens one will not be merged, however convenient it is.

1. **No real patient data, ever.** Synthetic only, in tests, fixtures, demo
   data, screenshots and issue reports alike. Not "anonymised" real data —
   synthetic.
2. **No secrets in the repository.** Not in a test, not in a comment, not in a
   commit that gets reverted afterwards.
3. **No `django.contrib.admin`.** It writes straight through the ORM, past
   every permission check, and produces no audit rows. Administration screens
   are part of the product.
4. **Facility isolation.** An out-of-scope record returns 404, never 403 —
   "no such patient" and "a patient you may not see" have to be
   indistinguishable.
5. **Concurrency invariants are enforced by the database.** A check a race can
   slip past does not count. Use a constraint, a conditional `UPDATE`, or a
   lock — and prove it with a test that actually fails when the guard is
   removed.
6. **Clinical and financial history is append-only.** Amending appends a
   version with an author and a reason. Reconciled money is corrected by a new
   adjusting entry, never by an edit.
7. **No GPL, AGPL or SSPL dependencies.** CI fails the build on them. This
   surprises people, given the project's own licence is the AGPL — the reason
   is that VitaCore is [dual-licensed](LICENSING.md), and we have no right to
   relicense somebody else's copyleft code under the commercial half. LGPL is
   fine and CI lists what is in use.

## Style and shape

- Idiomatic Django, DRF and Next.js. Use the framework rather than
  reimplementing it.
- One Django app per domain area, organised by feature rather than by layer.
- No service or repository layer over the ORM. Behaviour lives on models and
  in plain functions; views and serializers stay thin.
- No abstraction until a second real caller exists.
- Shared list-and-form machinery is expected for **configuration** screens and
  never for clinical, prescribing, dispensing or billing ones. Those are
  hand-designed, because a generic form is how a dose ends up in the wrong box.
- Comments explain *why*, not *what*. If a line is surprising, say what would
  go wrong without it.

## Tests

Every behaviour a hospital depends on needs a test that proves it, including
the refusals — a boundary with no test proving it refuses is not a boundary.

Two things worth knowing:

- **A concurrency test that cannot fail proves nothing.** Before trusting one,
  remove the guard it is testing and check that it goes red. Several tests in
  this repository were rewritten after failing that check.
- Name tests after the property, not the function:
  `test_two_patients_cannot_occupy_one_bed_under_concurrency`, not
  `test_allocate`.

## Clinical content

Round times, overdue windows, escalation thresholds, triage scales and consent
wording in this repository are **reasonable defaults chosen by software
people, not by clinicians.** They have not been signed off by anybody
qualified, and the project says so plainly in the product guide.

If you are changing any of them, say in the pull request what the change is
based on. If you are a clinician and something here is wrong, an issue saying
so is one of the most valuable contributions you can make.

## Pull requests

- One concern per pull request.
- Say what changes for the person using the software, not just what changed in
  the code.
- If you touched anything under "the rules that are not negotiable", say which
  test covers it.
- If something is unfinished, say so in the description. A stub presented as
  complete is worse than an open branch.

## Signing off

Two things, both quick, and both explained in [CLA.md](CLA.md):

- **Every commit** carries a `Signed-off-by:` line — the Developer Certificate
  of Origin, confirming you have the right to submit the code. `git commit -s`
  adds it for you.
- **Your first pull request** carries a comment saying you agree to the CLA.

The CLA exists because VitaCore is [dual-licensed](LICENSING.md), and offering
both an AGPL and a commercial licence requires rights broad enough to cover
both. **You keep the copyright in everything you write** — it grants a licence
and assigns nothing, and you remain free to use your own work anywhere else.
