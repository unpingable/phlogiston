# Documentation map

This index distinguishes authority, current implementation records, evidence,
and design history. A document's directory never overrides its explicit status
or the authorization rules in `BUILD.md`.

## Current controlling documents

- [`../BUILD.md`](../BUILD.md) — sole repository work-authorization ledger
- [`../DOCTRINE.md`](../DOCTRINE.md) — ratified V0 architectural law
- [`../ROADMAP.md`](../ROADMAP.md) — canonical candidate slice ladder;
  non-authorizing without a matching `BUILD.md` amendment
- [`OPEN-QUESTIONS.md`](OPEN-QUESTIONS.md) — unresolved protocol and governance decisions
- [`GOVERNED-LOOP.md`](GOVERNED-LOOP.md) — governed execution contract
- [`V0-STATE-MACHINE.md`](V0-STATE-MACHINE.md) — V0 reducer/state semantics
- [`TEST-PLAN.md`](TEST-PLAN.md) — repository verification surface
- [`REUSE-MATRIX.md`](REUSE-MATRIX.md) — donor provenance, license, and boundary review

## Current navigation and handoff

- [`V0-HANDOFF.md`](V0-HANDOFF.md) — V0 closeout, evidence identity, and local read-only demo
- [`campaigns/SPACE-COMMUNITY-SCV0-D2.md`](campaigns/SPACE-COMMUNITY-SCV0-D2.md)
  — frozen live disposable-alpha product contract
- [`campaigns/SPACE-COMMUNITY-SCV0-L11.md`](campaigns/SPACE-COMMUNITY-SCV0-L11.md)
  — latest isolated PDS fallback status on the inspected line
- [`campaigns/PUBLIC-COMMUNITY-PCV0.md`](campaigns/PUBLIC-COMMUNITY-PCV0.md)
  — current public app-layer social-loop contract, trust path, recovery law, and deferrals
- [`campaigns/pcv1-reference-client-candidate.md`](campaigns/pcv1-reference-client-candidate.md)
  — reference-client candidate custody record, gates, dogfood journey, and resume point
- `campaigns/` — milestone records; these state bounded claims and non-claims
- `status/` — dated audits, forcing cases, and blocker snapshots; not all are current

## Design evidence, not authority

- [`../IDEAS.md`](../IDEAS.md) — initial idea capture and reuse map; explicitly
  non-normative, retained at root because governance checks protect that path
- [`design/PRODUCT-DIRECTION.md`](design/PRODUCT-DIRECTION.md) — non-authorizing
  product direction and candidate tranches
- [`design/ATTENTION-CENTRALITY-BRAKE.md`](design/ATTENTION-CENTRALITY-BRAKE.md)
  — non-authorizing capture of an attention-centrality suppression product
  concept; carries no candidate ID and reserves no slice
- [`research/ROADMAP2.md`](research/ROADMAP2.md) — parked research incubator;
  ignored by the governed selector
- [`ROADMAP2-FORMAL-ASSURANCE.md`](ROADMAP2-FORMAL-ASSURANCE.md) — preparation
  testimony for the parked research line
- [`LEXICON-DRAFT.md`](LEXICON-DRAFT.md) — draft naming/schema material;
  publication is explicitly unresolved

## Historical and superseded material

- `OQ-*-PACKET.md` — question packets and their historical decision context;
  consult `OPEN-QUESTIONS.md` for current resolution state
- old hashed files under `status/governed-runway-blockers-*` — exact dated
  blocker snapshots; later snapshots may supersede earlier ones
- failed/superseded branches named by Git are retained as branch history, not
  a current implementation line

## Reading rule

For “what may be built,” read `BUILD.md`. For “what is architecturally
required,” read `DOCTRINE.md`. For “what exists,” read the root README, current
campaign record, source, and tests. Treat prose framed as an idea, direction,
candidate, parked research item, question packet, or dated status capture as
evidence of thinking—not as implemented behavior or authorization.
