# SCV0-OQ9 — Public projection first

Status: **frozen for SCV0 V0** (2026-08-22)

## Decision

SCV0 V0 uses **public projection artifacts with community-controlled
publication**:

```text
author-owned source
        ↓
qualified observation
        ↓
community admission
        ↓
community-owned projection artifact
        ↓
replaceable renderer
        ↓
reader
```

The community chooses which already-compiled disclosure-scoped artifact to
publish. Publication is an explicit public disclosure decision. The renderer
consumes that artifact and does not acquire private source state, Space
credentials, moderator capability, admission authority, or reader identity.

This decision was issued directly by the operator in the explicit SCV0 V0
implementation task. The earlier D1 record correctly noted that no antecedent
question packet, required change set, or authenticated external decision
receipt existed. This record does not fabricate one retroactively; it records
the direct task source and the exact bounded consequence.

## Rationale

Public projection first allows V0 to validate:

* community-owned publication decisions;
* portable, deterministic projection artifacts;
* independently replaceable renderers;
* the separation of source, admission, projection, publication, and
  presentation authority.

It does so without introducing reader authorization, reusable reader
credentials, private plaintext custody, cache invalidation, or the inherently
limited promise of revocation after disclosure.

This is the smallest product experiment that can answer whether the community
surface is legible to a person. It does not claim to solve the harder private
community problem.

## Frozen V0 semantics

```text
qualified source existence != community admission
community admission         != artifact publication
artifact publication        != reader authentication
artifact possession         != permission or standing
renderer presentation       != community authority
```

An ordinary public artifact exposes only its bounded presentation and
lifecycle fields. A technical-audit artifact is a separate, explicitly named
public disclosure whose receipt references do not become authority. No
ordinary representation may silently inherit technical-audit fields.

The renderer may choose layout, accessibility, and explanation wording while
preserving canonical artifact semantics. It may not fetch raw repositories,
infer admission, hide or change lifecycle meaning, or strengthen receipt
claims.

## Explicitly deferred boundary

SCV0 V0 does not implement or solve:

* private communities or confidential discussion;
* community membership;
* reader identity, accounts, sessions, or credentials;
* Space read grants or invitations;
* access-control or authenticated feeds;
* private projection serving;
* revocation semantics or erasure after disclosure.

These are explicit future product and security decisions, not accidental
omissions. A successor private-reader campaign must return to the distinct
M4 questions about authentication, current Space access, membership,
credential/plaintext custody, audience budgets, caching, revocation limits,
tenant isolation, and fail-closed behavior. It must not reinterpret the public
artifact contract as proof that a private reader is entitled to anything.

## Non-goals

Public projection does not establish source truth, community legitimacy,
membership, popularity, moderator standing, governance authority, reader
intent, confidential access, or production readiness. It does not authorize
live Space identities, records, credentials, writes, deployment, or reuse of
the existing public AppView for private data.

## Authorized successors

This decision permits separately bounded fixture/local experiments only:

1. M6A may wrap an exact M5A artifact in a deterministic public feed
   publication representation without network serving.
2. M6B may render that representation as a tiny local browser prototype with
   ordinary and technical-audit pages kept separate.

Neither successor may introduce accounts, login, reader authentication,
posting, comments, moderation UI, voting, ranking, recommendation, network
serving, live permissioned data, or deployment.
