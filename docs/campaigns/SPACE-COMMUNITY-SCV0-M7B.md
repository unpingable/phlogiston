# SCV0-M7B — Disposable public demo publication

Status: **published and byte-qualified** (2026-08-22 local / 2026-08-23 UTC)

## Publication

The M7A synthetic bundle is published from a separate public artifact-only
repository:

* site: <https://unpingable.github.io/atproto-community-demo/>
* publication repository: <https://github.com/unpingable/atproto-community-demo>
* publication commit: `65f0d4aded424bc6c20cd0f5ed228e8849d928c8`
* generator repository commit: `6416d54cd3ab7c0643b75ab192f6050ff6e898d9`
* Pages build: `1168804228`, status `built`
* bundle ID:
  `sha256:9bc2a8935f1f239fbcd311287fcf3602fa4a7f1ebfd9bcada0d413dc26455b5e`

The publication repository contains the 20 generated files plus a README,
NOTICE, and Apache-2.0/MIT license texts. It contains no application runtime,
observer, writer, credential, live identity, or live Space data.

## Hosted-byte witness

At `2026-08-23T00:57:57Z`, the deployed `checksums.txt` body matched the local
M7A body exactly. Every one of its 19 listed payloads—including `.nojekyll`,
the landing page, four ordinary pages, four audit pages, eight feed artifacts,
and the manifest—was then fetched independently over HTTPS with
`Accept-Encoding: identity`. Each hosted body matched both its listed SHA-256
digest and its local byte sequence. Together with `checksums.txt`, all 20 M7A
files therefore had exact hosted-byte parity for that bounded acquisition.

The human-facing root and the four directory routes were also fetched without
redirect following and matched their generated `index.html` bytes exactly.

Replay the source export locally with:

```text
PYTHONPATH=packages/community-space-demo/src:\
packages/community-space-artifact/src:\
packages/community-space-comprehension/src:\
packages/community-space-feed/src:\
packages/community-space-prototype/src:\
packages/community-space-model/src:\
packages/community-space-projection/src:\
packages/community-space-renderer/src:\
packages/community-model/src \
.venv/bin/python -m community_space_demo OUTPUT
```

Then compare the output against the public `checksums.txt`.

## Claim boundary

M7B proves only that GitHub Pages returned the exact synthetic M7A payloads in
one bounded read-only observation. GitHub and Pages are publication transport,
not community authority.

It does not establish:

* live ATProto or Spaces interoperability;
* publisher, moderator, membership, or governance authority;
* reader identity, authentication, authorization, or private disclosure;
* repository or source currentness beyond the bounded acquisition;
* source truth or ownership;
* human comprehension, desirability, accessibility, or usability;
* production readiness or availability.

Repeated retrieval would be a new acquisition observation, not a semantic
confidence upgrade. A future host may replace GitHub Pages without changing
M1–M7A projection semantics.
