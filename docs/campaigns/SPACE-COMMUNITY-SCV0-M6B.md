# SCV0-M6B — Minimal local community prototype

Status: **implemented, synthetic and local-only** (2026-08-22)

## Product thesis

> The community owns inclusion and publication decisions; the renderer owns
> presentation only.

M6B turns the exact M6A public feed envelope into two in-memory HTML pages:

```text
public ordinary feed ───────→ ordinary community page
public technical-audit feed → separate audit page
```

Both feeds must describe the same exact community and lifecycle occurrence.
The prototype independently renders each embedded M5A artifact through the
existing M5B canonical renderer and refuses the pair if their public lifecycle
semantics differ. It performs no source fetch, admission, authorization,
moderation, network serving, or file write.

## Ordinary view

The ordinary page shows only:

* the community reference;
* the M5A-bounded presentation for an `Added` item;
* the disclosed author display reference;
* the exact lifecycle label and plain-language lifecycle notice;
* a short “Why is this here?” explanation that distinguishes community
  publication from author ownership.

`ChangedAtSource` remains a change notice and does not silently replace the
admitted presentation. `Removed` remains a tombstone and says that the author
source was not mutated. The ordinary page contains no audit receipt IDs.

## Technical-audit view

The separate audit page may show only technical fields that the M5A audit
policy already disclosed:

* feed and artifact identities;
* lifecycle state and notice;
* receipt **references**;
* available lifecycle links.

The prototype does not dereference receipts or interpret them as authority.
Technical disclosure never flows into the ordinary page merely because the
two pages are built together for this local fixture.

## Positive witnesses

* M6B-P1 — an `Added` feed renders a legible community item, author reference,
  lifecycle state, and plain-language explanation;
* M6B-P2 — ordinary and audit disclosures remain separate;
* M6B-P3 — `ChangedAtSource` renders a lifecycle notice without content
  replacement;
* M6B-P4 — `Removed` renders a removal state without source mutation;
* deterministic replay binds both exact feed IDs and both page digests into a
  stable local site identity.

These witnesses use
`tests/fixtures/space-community/scv0-m6b.json` (SHA-256
`3cf550281cca4409b12a2364b1153c63d0a466f8c88b4e31285c7dd1655defb9`).

## Hostile witnesses

* UI-H1 — presentation cannot invent moderator or governance authority;
* UI-H2 — hiding/changing lifecycle text breaks the bound page digest while
  canonical lifecycle semantics remain available;
* UI-H3 — ordinary and audit feeds describing different lifecycle states are
  refused;
* UI-H4 — presentation cannot claim community ownership of the source;
* raw artifacts and mappings cannot bypass the typed feed boundary;
* an audit feed cannot be substituted for the ordinary channel;
* possession cannot become reader permission and ranking remains a non-claim;
* post-publication presentation mutation breaks the feed/artifact identity
  before rendering.

## Claim boundary

The prototype demonstrates that a person can inspect a synthetic public
community projection and recover its lifecycle explanation without giving the
renderer admission or source authority. It proves deterministic presentation
of the exact supplied feeds and separation of ordinary/audit disclosures.

It does **not** prove source truth, source ownership, reader authentication,
reader permission, membership, moderator legitimacy, governance authority,
repository currentness, popularity, usability with real people, or production
readiness. Public artifact possession is disclosure, not authentication.

## Deliberate limitations

M6B returns escaped HTML strings in memory. It is not a server or deployed
site. It has no accounts, login, posting, comments, moderation UI, voting,
ranking, recommendations, transport, storage, cache, database, credentials,
or live Space data.

Private reader sessions, confidential projections, Space read grants,
invitations, membership, and revocation remain the explicit future OQ-9
boundary. They can be added before publication without changing the M5A/M6A
artifact semantics; they cannot be inferred from this public prototype.
