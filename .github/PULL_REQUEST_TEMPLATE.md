## What this changes

<!-- What is different for the person using the software? Not just what
     changed in the code. One or two sentences. -->

## Why

<!-- The problem in the hospital that this solves. Link the issue if there is
     one. -->

## How to see it working

<!-- Steps against a freshly seeded demo hospital:
       manage.py seed_demo && manage.py demo_day
     Which account should the reviewer sign in as? -->

## Checks

- [ ] `ruff check .`
- [ ] `manage.py makemigrations --check --dry-run`
- [ ] `pytest`
- [ ] `manage.py verify_audit_chain`
- [ ] `npx tsc --noEmit` · `npm run lint` · `npm test` · `npm run build`

## The rules

<!-- Tick what applies; delete what does not. -->

- [ ] No real patient data anywhere in this change — synthetic only
- [ ] No secrets, in the diff or in any commit on the branch
- [ ] New endpoints are facility-scoped, and out-of-scope records return 404
- [ ] New permissions are enforced server-side, with a test proving the refusal
- [ ] Any new concurrency guard has a test that **fails when the guard is
      removed** — I checked, rather than assuming
- [ ] Clinical or financial records are appended to, never overwritten
- [ ] No copyleft dependency added

## Clinical content

<!-- Delete this section if the change touches none. Otherwise: what is the
     new value, and what is it based on? Defaults in this repository have not
     been signed off by a clinician, and a change should say whether it has. -->

## Anything unfinished

<!-- Say so here. A stub presented as complete is worse than an open branch. -->
