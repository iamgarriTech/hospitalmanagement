# Licensing

VitaCore is dual-licensed.

## 1. GNU AGPL v3 — the open-source licence

The default. Free to use, read, modify and share, under the terms in
[LICENSE](LICENSE).

The clause that matters most is **section 13**. Under the AGPL, running
modified VitaCore as a network service counts as distribution: if you offer it
to other people over a network — a hosted product, a service for clinics you
do not own — you must offer those users the complete corresponding source of
your modified version, under the AGPL.

This is deliberate. It means a hospital can run and adapt this freely, and it
means somebody cannot take the work, improve it, sell it as a hosted service,
and keep the improvements to themselves.

### What the AGPL does *not* require

- **A hospital running VitaCore for its own patients** publishes nothing. Your
  staff and your patients are not "other users" being offered a service in the
  sense section 13 means. Use it, modify it, run it on your own server: no
  obligation is triggered.
- **Internal modifications you never distribute** stay yours.
- Your **patient data** is your data. The licence covers the software, and
  nothing in it asks you to publish anything about the people you treat.

## 2. A commercial licence — for when the AGPL does not fit

Some organisations cannot use AGPL software: a hosting provider that wants to
offer VitaCore to clinics without publishing its own changes, a vendor
embedding it in a closed product, or an institution whose procurement policy
refuses copyleft outright.

A commercial licence removes the AGPL's obligations in exchange for a fee.

To ask about one, open an issue titled "Commercial licence enquiry" — with no
confidential detail in it — and a maintainer will arrange a private
conversation.

## Which one applies to me?

| You are | Licence |
|---|---|
| A hospital running it for your own patients | AGPL — nothing to publish |
| A developer reading, learning from or contributing to it | AGPL |
| A hospital that modified it and shares those changes | AGPL |
| Hosting it as a service for clinics you do not own | AGPL (publish your changes) **or** commercial |
| Embedding it in a closed-source product you sell | Commercial |
| Barred by policy from using AGPL software | Commercial |

If you are unsure, you are almost certainly in the first row.

## Contributing, and why there is a CLA

Dual-licensing only works if one party holds enough rights to grant both
licences. If a contribution arrived under the AGPL alone, it could never be
included in a commercially licensed copy — and the second licence would
quietly stop being offerable.

So contributions are accepted under the [Contributor Licence
Agreement](CLA.md). It asks you to grant a licence broad enough to cover both,
while **you keep the copyright in what you write**. It does not ask you to
assign anything away.

Every commit must also carry a `Signed-off-by:` line — the [Developer
Certificate of Origin](https://developercertificate.org/), which is you
confirming you have the right to submit the code. `git commit -s` adds it.

## Dependencies

Dual-licensing constrains what this project may depend on, and more tightly
than a single AGPL licence would.

A GPL or AGPL dependency cannot be shipped under a commercial licence — we
have no right to relicense somebody else's copyleft code — so including one
would silently end the commercial option. **CI therefore fails the build on
any GPL, AGPL or SSPL dependency**, even though the project's own licence is
the AGPL.

LGPL dependencies are allowed and listed by CI on every run. They must stay
unmodified and dynamically linked; the one currently in the tree is `libvips`,
reached through `sharp`, which Next.js uses for images.

## Third-party notices

The dependency licence inventory is produced by CI on every run and attached
to the build as `licences-python.csv` and `licences-node.csv`.
