# S1 × OQ-1 — namespace selection vs namespace publication

**Schema:** factual-governed-runway-status-v1

**Authority effect:** none

**Observed at:** 2026-08-17

**Scope:** the ratified OQ-1 record, the S1 candidate entry in `ROADMAP.md`,
and the current repository contents

**Rulings made:** none

This note does not select an operator answer, promote a candidate, amend
`BUILD.md`, discharge a blocker, or resolve the ambiguity it describes. It
records a traced gap so a future S1 packet starts from the real state.

## Summary

OQ-1 is decided and its ruling is fully applied for the V0 question it was
asked. It does not follow that S1's dependency on OQ-1 is discharged. OQ-1
answered a **selection** question; S1 requires a **publication** act. The
existing OQ-1 record does not authorize, describe, or supply acceptance
criteria for that act.

The S1 dependency on OQ-1 therefore remains listed and is **not** stale.

## What OQ-1 actually decided

The packet `OQP-OQ-1-2026-08-14-01` asks:

> Which owned reverse-DNS authority replaces `invalid.community.*` for the
> four community Lexicon NSIDs (profile, submit, admission, modAction)?

Its "Why now" scopes the forcing case to V0-M7 and write-enabled exercises:
no write-enabled exercise packet could be issued until permanent NSIDs
existed to pin. Its Answer A consequence block names exactly one required
amendment:

> Lexicon/constants/fixtures rename commit before the M7 task packet is issued

That amendment was performed in commit `c3c8a9a` and is complete. The ruling
named the authority `community.neutral.zone` (NSIDs
`zone.neutral.community.*`) under receipt `OQDR-OQ-1-2026-08-14-A-01`.

## What S1 requires beyond that

S1 lists as an addition "permanent lexicon NSIDs **published**" and as a
deliverable `lexicons/<ns>/*.json` (four, **published**). Current state:

- no `lexicons/` directory exists in this repository;
- no Lexicon schema documents have been authored in any form other than the
  review fixtures in `docs/LEXICON-DRAFT.md`;
- nothing in the repository serves, resolves, or binds the namespace at its
  reverse-DNS authority; and
- the NSID strings exist only as Python constants
  (`packages/community-model/src/community_model/constants.py:7-10`) and the
  registry in `lexicons.py:30-33`.

S1 also attaches a permanence obligation to publication — "published NSIDs are
permanent protocol surface — frozen forever" — which the selection ruling did
not itself trigger, because selecting a name that is only referenced in-repo
freezes nothing externally.

## The ambiguity, stated but not resolved

The OQ-1 record is silent on every question S1's publication step raises:

1. **Ownership evidence.** The ruling asserts a "project-controlled" domain.
   The packet's own Answer A uncertainty records that the domain is "an
   ownership/branding fact only the operator can supply." No artifact in the
   repository or evidence store demonstrates registration or DNS control of
   `community.neutral.zone`.
2. **Publication mechanism.** Neither OQ-1 nor S1 names how the authority is
   established or what constitutes publication for these NSIDs.
3. **Actor and ceremony.** S1 marks production key generation as an
   unbatchable human ceremony. Whether Lexicon publication is likewise a human
   ceremony, an automatable task-ladder step, or a prerequisite to both is
   unstated.
4. **Freeze point.** When the permanence obligation attaches — at ruling, at
   authoring, at publication, or at first live record under a published
   schema — is undefined.
5. **Sufficiency.** Whether the existing OQ-1 receipt can be cited as the
   authority for publication, or whether S1 requires a separate promoted
   question, is precisely the open item already recorded in the
   `ROADMAP.md` slice-lane normalization backlog:

   > distinguish OQ-1's pre-V0-M7 permanent namespace decision from S1's
   > later production publication/deployment step

   That backlog entry is marked a known review debt and not agent-editable.
   This note supplies its factual trace; it does not discharge it.

## Incidental finding — S1 task-ladder step 1 already ran

S1's machine task ladder opens with:

> 1. NSID migration in one atomic commit — done when a grep gate finds zero
>    draft NSIDs outside history docs and the full suite exits 0.

That step was satisfied out of band by `c3c8a9a` during V0-M7 preparation,
before S1 was authorized or its packet prepared. S1's ladder therefore begins
in a partially-completed state. Recorded as a fact for whoever prepares the
S1 packet; no conclusion is drawn here about whether the out-of-band
execution counts against the ladder.

## Related repair

The same rename commit mechanically rewrote three sentences whose correct
referent was the *old* namespace, inverting their meaning. Repaired
separately in `ROADMAP.md` (S1 "Adds") and `docs/LEXICON-DRAFT.md` (status
and naming). Those are documentary repairs of a sed artifact and carry no
authority effect.
