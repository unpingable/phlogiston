# Operator question OQ-4

- Packet ID: `OQP-OQ-4-2026-08-14-01`
- Schema: `operator-question-packet-v1`
- Prepared: 2026-08-14T21:55:44Z by agent-prepared draft
- Prepared-against base commit: `c87b198f5ce14efde1f485fbff85c8cc9d335fba`

## Question

Ratify the deliberately local V0 model — communityd treats OS access (effective UID equals configured allowed_uid) as authorization and the configured administrator DID as community-attested attribution — or require an independently authenticated admin request before the community actor emits?

## Why now

OQ-4 blocks treating a real operator DID in actor as more than an unchecked claim. M7 implements the local authorizer now; the observer side (complete through M6) already validates attributed actor equals the configured administrator DID.

## Work blocked

Treating a real operator DID in actor as more than an unchecked claim (V0-M7).

## Bounded by

- BUILD.md
- DOCTRINE.md
- AGENTS.md
- docs/GOVERNED-LOOP.md

## Governing inputs

- scope authority: `BUILD.md` (5884 bytes, `sha256:ee50d817d9a81032731a962cfb843525e8c99a29332f25b066734a3a832862cc`)
- architecture doctrine: `DOCTRINE.md` (2622 bytes, `sha256:cf7bb22ae2e1d2a117bf7b35c1746d5f0045e69eee40784b0a10889efb22584c`)
- agent instructions: `AGENTS.md` (3332 bytes, `sha256:1a4c9b2b0b0779c1a9caa255eef977f67f77989d4720796a2e1861494413c7ac`)
- open-question register: `docs/OPEN-QUESTIONS.md` (10489 bytes, `sha256:41f28cc5117cd9855f876e035b7651344a5d9f5a20bfa5013e0d4b86bb3acfc5`)
- governed execution contract: `docs/GOVERNED-LOOP.md` (50121 bytes, `sha256:5196331349155397bb0f6b4f85a9adda5ed4e1741e75b043341f4a1f0ec0afa1`)
- authorized V0 milestone design: `docs/IMPLEMENTATION-PLAN.md` (43789 bytes, `sha256:9713bfb4729844bbd029423f3f66cf192ab9b90c172b7585bfd6d5b4fd55da35`)

## Forcing case

Sufficiency predicate: M7's authorizer and the admission attribution semantics must be fixed before the adapter contract tests and the X7 write smoke can be pinned.

- attribution-model analysis: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-4-analysis.txt` (text/plain; charset=utf-8, 1465 bytes, `sha256:f79547206925856f62386a77fde9c4d0e53beb5fbea6787f788594e41f5ce670`)

## Answer A

- Fit: Ratify the local model: OS/process authorization; actor is precisely community-attested attribution ('the community actor attests this DID requested the action'); no remote admin endpoint; for the V0 trial the administrator DID and the community actor DID may be the same disposable identity.
- Basis: Register recommendation; matches the implemented observer semantics exactly; real delegated admin auth is classified as post-V0 protocol work.
- Uncertainty: Whether the human trial finds community-attested attribution legible enough to feel like a real place.

### Supporting evidence

- attribution-model analysis: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-4-analysis.txt` (text/plain; charset=utf-8, 1465 bytes, `sha256:f79547206925856f62386a77fde9c4d0e53beb5fbea6787f788594e41f5ce670`)

### Opposing evidence

- attribution is not an independently verified admin signature: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-4-analysis.txt` (text/plain; charset=utf-8, 1465 bytes, `sha256:f79547206925856f62386a77fde9c4d0e53beb5fbea6787f788594e41f5ce670`)

### Consequences

- Authority deltas: communityd emits records attributing the configured administrator DID under local OS authorization.
- Guarantee deltas: The attribution claim is precisely scoped: no admin-authenticity guarantee is made or implied.
- Blockers satisfied:
  - OQ-4 blocks V0-M7
- Blockers remaining:
  - OQ-1 and OQ-3 remain open until separately ruled
- Tasks eligible:
  - V0-M7 becomes selectable once OQ-1 and OQ-3 are also decided
- Amendments required: none
- Replay/fork implications: No replay seam impact.
- Abuse/T&S implications: A local UID spoof is bounded by OS access control on the operator's machine; no remote surface.

## Answer B

- Fit: Require independently authenticated admin requests in V0: the admin signs a request with their own DID key and the community actor verifies it before emitting.
- Basis: Stronger attribution: the actor field becomes a verified admin claim.
- Uncertainty: Admin key custody for the operator's real DID is undesigned.

### Supporting evidence

- stronger-attribution argument: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-4-analysis.txt` (text/plain; charset=utf-8, 1465 bytes, `sha256:f79547206925856f62386a77fde9c4d0e53beb5fbea6787f788594e41f5ce670`)

### Opposing evidence

- pulls post-V0 protocol work into V0; no V0 consumer of the proof: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-4-analysis.txt` (text/plain; charset=utf-8, 1465 bytes, `sha256:f79547206925856f62386a77fde9c4d0e53beb5fbea6787f788594e41f5ce670`)

### Consequences

- Authority deltas: An admin proof field would be added to admission and modAction records.
- Guarantee deltas: Would add an admin-authenticity guarantee the V0 observer does not consume.
- Blockers satisfied:
  - OQ-4 blocks V0-M7
- Blockers remaining:
  - OQ-1 and OQ-3 remain open until separately ruled
- Tasks eligible: none
- Amendments required:
  - Record-shape change churns the frozen Lexicons before the trial
- Replay/fork implications: No replay seam impact.
- Abuse/T&S implications: Admin key custody becomes a new target.

## Answer C

- Fit: Local authorization now, but reserve record surface for a later admin-proof field.
- Basis: Keeps a post-V0 upgrade path explicit.
- Uncertainty: The reserved shape may not fit the eventual post-V0 design.

### Supporting evidence

- upgrade-path argument: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-4-analysis.txt` (text/plain; charset=utf-8, 1465 bytes, `sha256:f79547206925856f62386a77fde9c4d0e53beb5fbea6787f788594e41f5ce670`)

### Opposing evidence

- speculative generality; optional fields can be added non-breakingly later: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-4-analysis.txt` (text/plain; charset=utf-8, 1465 bytes, `sha256:f79547206925856f62386a77fde9c4d0e53beb5fbea6787f788594e41f5ce670`)

### Consequences

- Authority deltas: Same authority effect as A, plus an unused reserved field in V0 records.
- Guarantee deltas: Same guarantees as A.
- Blockers satisfied:
  - OQ-4 blocks V0-M7
- Blockers remaining:
  - OQ-1 and OQ-3 remain open until separately ruled
- Tasks eligible:
  - V0-M7 becomes selectable once OQ-1 and OQ-3 are also decided
- Amendments required:
  - Lexicon edit for the reserved field
- Replay/fork implications: No replay seam impact.
- Abuse/T&S implications: An unspecified reserved field invites divergent private interpretations.

## Recommendation

Recommended answer: `A`

It ratifies what is already implemented and specified, keeps V0 minimal, and leaves delegated admin auth to post-V0 protocol work where the register already places it.

## Novelty condition

A replacement packet is required if the trial shows community-attested attribution is misleading to users, or if a concrete post-V0 delegated-auth design becomes available early.
