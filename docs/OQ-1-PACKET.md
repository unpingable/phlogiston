# Operator question OQ-1

- Packet ID: `OQP-OQ-1-2026-08-14-01`
- Schema: `operator-question-packet-v1`
- Prepared: 2026-08-14T21:55:44Z by agent-prepared draft
- Prepared-against base commit: `c87b198f5ce14efde1f485fbff85c8cc9d335fba`

## Question

Which owned reverse-DNS authority replaces invalid.community.* for the four community Lexicon NSIDs (profile, submit, admission, modAction)? All four move together, and the reserved draft IDs must never be published or aliased.

## Why now

V0-M7 (the real authority writer) and the V0-X7-WRITE-SMOKE create the first real community records. The ratified contract requires the M7 packet to allow only the permanent admission and removal NSIDs pinned by the selected OQ-1 decision receipt, with invalid.community.* never emitted. The register's precondition — choose only after the four record shapes survive the offline milestone — is now met: M1-M6 are complete and verified.

## Work blocked

Publishing Lexicons and creating real community records; concretely V0-M7 and any write-enabled exercise.

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
- draft lexicon shapes: `docs/LEXICON-DRAFT.md` (8363 bytes, `sha256:3b87f4565b5835489a09e0bdf9b57fcd819f3c8694eb9e8913960e293cb343ff`)

## Forcing case

Sufficiency predicate: No write-enabled exercise packet can be issued until permanent NSIDs exist to pin; the first real write is permanent protocol surface and cannot carry a draft NSID.

- contract and precondition analysis: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-1-analysis.txt` (text/plain; charset=utf-8, 1478 bytes, `sha256:4e0c388deaef7d47e03fa7e7709ee39d094e2ccfd9bf881b665b7df79fc1d95f`)

## Answer A

- Fit: Adopt an operator-named, project-controlled domain now and atomically rename all four NSIDs before M7; the ruling text itself names the exact domain. Satisfies the contract's permanent-NSID pin before any write exists, so there is no live migration.
- Basis: Register recommendation's precondition is met (record shapes survived the offline milestones, including hardened and live-verified ingestion); doctrine forbids publishing the reserved draft IDs, and X7 writes real records to a real PDS repository.
- Uncertainty: The domain string is an ownership/branding fact only the operator can supply; a poor name is permanent.

### Supporting evidence

- precondition-met analysis: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-1-analysis.txt` (text/plain; charset=utf-8, 1478 bytes, `sha256:4e0c388deaef7d47e03fa7e7709ee39d094e2ccfd9bf881b665b7df79fc1d95f`)

### Opposing evidence

- permanence risk: the name is final protocol surface: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-1-analysis.txt` (text/plain; charset=utf-8, 1478 bytes, `sha256:4e0c388deaef7d47e03fa7e7709ee39d094e2ccfd9bf881b665b7df79fc1d95f`)

### Consequences

- Authority deltas: No community authority changes; the four NSIDs are renamed in one mechanical sweep.
- Guarantee deltas: The draft-namespace non-publication guarantee is preserved by never writing draft records.
- Blockers satisfied:
  - OQ-1 blocks V0-M7 and any write exercise
- Blockers remaining:
  - OQ-3 and OQ-4 remain open until separately ruled
- Tasks eligible:
  - V0-M7 becomes selectable once OQ-3 and OQ-4 are also decided
- Amendments required:
  - Lexicon/constants/fixtures rename commit before the M7 task packet is issued
- Replay/fork implications: No replay seam impact; renamed collections are what M6 ingestion filters.
- Abuse/T&S implications: A colliding or squatted name would be an abuse vector; the operator's owned domain avoids it.

## Answer B

- Fit: Run the V0 trial on invalid.community.* as explicitly disposable draft records and rename post-trial. Unblocks M7 without a naming decision.
- Basis: V0 is non-production and its actor disposable by design.
- Uncertainty: Whether 'never published' tolerates disposable test records on a live PDS is a doctrine interpretation the operator would own.

### Supporting evidence

- non-production framing: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-1-analysis.txt` (text/plain; charset=utf-8, 1478 bytes, `sha256:4e0c388deaef7d47e03fa7e7709ee39d094e2ccfd9bf881b665b7df79fc1d95f`)

### Opposing evidence

- conflicts with the ratified contract and doctrine non-publication rule: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-1-analysis.txt` (text/plain; charset=utf-8, 1478 bytes, `sha256:4e0c388deaef7d47e03fa7e7709ee39d094e2ccfd9bf881b665b7df79fc1d95f`)

### Consequences

- Authority deltas: Draft NSIDs would be emitted by X7, which the ratified contract currently forbids.
- Guarantee deltas: Weakens the draft-namespace non-publication guarantee by operator interpretation.
- Blockers satisfied: none
- Blockers remaining:
  - OQ-1 remains effectively open; the namespace question returns at the V0-to-slice transition
- Tasks eligible: none
- Amendments required:
  - GOVERNED-LOOP.md change set removing the permanent-NSID requirement for X7 (OQ-7-class amendment)
- Replay/fork implications: Trial evidence would carry draft NSIDs and could not be cited as permanent protocol behavior.
- Abuse/T&S implications: Publishing reserved .invalid NSIDs to a live network risks collision with unrelated experimenters.

## Answer C

- Fit: Register a new dedicated domain for the project first, then proceed as in A.
- Basis: Cleanest long-term ownership if no suitable domain is already controlled.
- Uncertainty: Whether registration completes on the trial timeline.

### Supporting evidence

- ownership analysis: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-1-analysis.txt` (text/plain; charset=utf-8, 1478 bytes, `sha256:4e0c388deaef7d47e03fa7e7709ee39d094e2ccfd9bf881b665b7df79fc1d95f`)

### Opposing evidence

- registration latency and cost before the trial: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-1-analysis.txt` (text/plain; charset=utf-8, 1478 bytes, `sha256:4e0c388deaef7d47e03fa7e7709ee39d094e2ccfd9bf881b665b7df79fc1d95f`)

### Consequences

- Authority deltas: No authority changes; the new domain becomes the permanent authority.
- Guarantee deltas: Guarantees unchanged.
- Blockers satisfied:
  - OQ-1 blocks V0-M7 and any write exercise
- Blockers remaining:
  - OQ-3 and OQ-4 remain open until separately ruled
- Tasks eligible:
  - V0-M7 becomes selectable once OQ-3 and OQ-4 are also decided
- Amendments required:
  - Domain registration outside the repository, then the same rename as A
- Replay/fork implications: No replay seam impact.
- Abuse/T&S implications: None beyond A.

## Recommendation

Recommended answer: `A`

The contract already requires permanent NSIDs for X7, the register's precondition is met, and the rename is cheapest now. The ruling must name the exact operator-controlled domain; if none is available, select C or repack.

## Novelty condition

A replacement packet is required if the operator has no suitable controlled domain, if upstream Lexicon tooling imposes a naming constraint not yet known, or if the trial should deliberately run on draft NSIDs (answer B's amendment path).
