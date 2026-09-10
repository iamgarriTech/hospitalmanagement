# Changelog

Notable changes, newest first. Written for somebody deciding whether to
upgrade, so it says what changes for the people using the software rather than
what changed in the code.

This project follows [Semantic Versioning](https://semver.org) from 1.0
onwards. Before then, `0.x` releases may change the API and the schema; read
the upgrade notes.

## Unreleased

### Added

- **Cash desk, at depth.** Tills are now counted per payment method rather
  than as one figure for the drawer — ₦5,000 short on cash against ₦5,000 over
  on transfers used to net to zero and hide two real mistakes. A till is
  counted, signed off by somebody other than the cashier who counted it, and
  frozen; corrections afterwards are new adjusting entries. A shift handover
  passes the float between two named people, confirmed by the cashier
  receiving it.
- **Stores.** Items, stores, stock held per store rather than per facility,
  and a movement recording every change — what, how much, from where, to
  where, why and who. Stock leaves soonest-expiry-first. Expired stock cannot
  be issued and stops counting towards the reorder level. Corrections above a
  value each store sets need a second person, and that person must actually
  hold the authorising permission.
- **Procurement.** Suppliers, purchase requests with approval above a
  threshold, orders at agreed prices, goods received line by line with batch
  and expiry, and three-way invoice matching that surfaces a mismatch rather
  than paying it. An approver cannot approve their own request; whoever
  entered an invoice cannot release it for payment.
- Open-source project files: licensing, contribution guidance, security
  policy, code of conduct, issue and pull-request templates.

### Fixed

- **A payment could land in a till that was being closed** — money reconciled
  as absent and sitting in the drawer. The payment path now holds a row lock,
  and either the payment lands before the close and is counted, or it is
  refused with a clear conflict.
- **A bed allocation losing a race returned a 500** rather than "that bed is
  occupied". Under real contention PostgreSQL sometimes reports a deadlock
  while checking the exclusion constraint instead of an overlap; both are now
  translated into a refusal that names the bed and the patient in it.
- A reconciled till told the accountant to close a session they had already
  signed off. It now points them at recording a correction.
- An open till reported its own takings as an unexplained variance, putting a
  permanent warning on every till in the building.

### Changed

- **Licence: AGPL v3, plus a commercial licence** (previously "all rights
  reserved"). See [LICENSING.md](LICENSING.md).
- Reconciling a till takes a count sheet (`counts`) instead of a single
  `counted_total`. **This is a breaking API change** — see the upgrade notes
  in [docs/operations.md](docs/operations.md#upgrading).

## Earlier work

Foundation, the outpatient day, inpatient care, radiology and insurance were
built before this changelog began. [docs/roadmap.md](docs/roadmap.md) has the
phases and [docs/product-guide.md](docs/product-guide.md) describes what
exists today.
