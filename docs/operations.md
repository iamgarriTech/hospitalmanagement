# Operations

## Running it

Development uses the host PostgreSQL directly; the Compose file is the
on-premises install and is not the development loop.

```
# Backend
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
createdb hms_dev
cp .env.example .env          # then edit
.venv/bin/python backend/manage.py migrate
.venv/bin/python backend/manage.py seed_demo     # synthetic configuration
.venv/bin/python backend/manage.py demo_day      # synthetic activity
.venv/bin/python backend/manage.py runserver 8009

# Frontend (port 3100; 3000 is often taken)
cd frontend && npm install && npm run dev
```

Sign in at `http://localhost:3100/login`. In demo mode the sign-in screen lists
one account per role — see the note on `DEMO_MODE` below.

## Demo mode

`DEMO_MODE` (defaults to `DEBUG`) makes `/api/meta/` serve working sample
credentials to the sign-in screen. **It must be off in any real deployment.**
Working credentials printed on a live hospital's login page is not a small
mistake, and the frontend deliberately cannot decide this — the server withholds
them, and `test_production_serves_no_credentials_at_all` asserts the password
string does not appear in the response at all.

## Backup and restore

### Taking a backup

```
pg_dump --format=custom --file=/backups/hms-$(date +%F-%H%M).dump hms
```

`--format=custom` gives a single consistent snapshot that `pg_restore` can load
selectively. A dump taken while the hospital is working is a consistent
point-in-time view, not a torn one — the drill below was deliberately run
*during* activity to prove that.

### Restoring

```
createdb hms_restored
pg_restore --dbname=hms_restored --no-owner --no-privileges /backups/hms-….dump
python backend/manage.py verify_audit_chain     # against the restored database
```

### Restore drill — AC-56

Run during active use, with `demo_day` generating visits, results, dispensing
and payments while `pg_dump` was running.

| | |
|---|---|
| Dump | 0.4 s |
| Restore | 0.8 s |
| **Total recovery** | **1.5 s** |

Consistency of the restored database — every check returned zero failures:

- no visit past `waiting` without its state history
- no dispense without a matching stock movement
- no payment detached from a cashier session
- no stock batch with a negative balance
- no prescription line dispensed beyond what was prescribed
- no invoice whose total disagrees with its lines
- no encounter without a current version, and none with two
- no parameter with two current laboratory results
- no two patients sharing a hospital number

And after the restore:

- **the audit chain verified** — intact across all events
- **the append-only trigger survived**: a raw
  `UPDATE audit_auditevent` was refused with `append-only; UPDATE is not
  permitted`

Row counts in the restored copy are lower than the live database because the
dump was a snapshot taken mid-activity. That is the correct result: a consistent
earlier point in time, rather than a partial view of a later one.

Re-run this drill on the real server before each release. Timings on production
hardware with a production-sized database will differ; the consistency checks
will not.

## What to watch

- **The UPS is not optional.** The server is expected to be in the building
  (see the connectivity decision), and the emergency read-only ward snapshot is
  the fallback for total failure.
- **Migrations run forward from the previous release.** Self-hosted deployments
  upgrade on their own schedule, so every release must be reachable from the one
  before it.
- **`verify_audit_chain` is a real check, not decoration.** Run it after any
  restore and on a schedule. It recomputes every row's hash; a broken chain
  means the log has been altered out of band.
