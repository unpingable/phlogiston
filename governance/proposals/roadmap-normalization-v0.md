# Roadmap normalization proposal (v0)

**Status:** proposal, non-authorizing. Produced by V0-G0 as the
`roadmap_normalization_proposal` artifact required for bootstrap-output
acceptance. It repairs nothing by itself; applying any of it requires a
separately authorized governance change.

**Generated:** 2026-08-14 from `governance/tools/validate_roadmap.py` output
over `ROADMAP.md` at the G0 candidate base.

## Canonical field grammar proposal

For each slice entry, normalize to exactly these fields with canonical values:

- `ID / Status:` — `S<n> — parked | candidate | ratified | done` (no
  qualifiers; parenthetical remarks move to the thesis line or a note field).
- `Type:` — exactly `testimony | guarantee | mixed` (parenthetical rationale
  moves to prose).
- `Blocking OQs:` — comma-separated handles existing in
  `docs/OPEN-QUESTIONS.md` (OQ-N) or the OQ-R register, or the literal
  `none registered`.
- `Depends on:` (new canonical field) — the acyclic prerequisite slice set,
  replacing dependency claims currently scattered across `Adds`, entry gates,
  and ordering prose.
- `Authorized:` — the literal `no | yes`, agreeing with `BUILD.md`.
- Optional `Entry gate (HUMAN)`, `Exit review (HUMAN)`, `Task ladder
  (MACHINE)`, `Donor assets`, `Replay seam obligation`, `Deliverables`,
  `Evidence log` retain their current prose roles.

## Detected defects and proposed dispositions

The validator reports these defects at the G0 base (all post-V0 lane; none
blocks the V0 runway):

| Defect | Slice | Proposed disposition |
|---|---|---|
| non-canonical `Type` qualifier | S1, S2, S5, S6, S7, S8, S9, S10, S11, S12, S13, S15, S16, S17 | Move the parenthetical rationale into prose; keep the enum bare. Human confirms each reclassification matches intent. |
| type/authority mismatch | S2 | Testimony entry describes an authority-bearing write (generator record emitted by `communityd`). Human splits or reclassifies the slice (GOV-SLICE-003). |
| dependency inconsistency | S8 | `Adds` requires S10 and S18; the entry gate names S6/S7; S8 precedes S10. Human resolves into the canonical `Depends on:` field (GOV-SLICE-004). |
| non-canonical `Status` qualifier | S16 | `parked (hard)` -> `parked`; the "hard" note moves to prose. |

## Non-goals

This proposal does not change any slice status, authorize any slice, alter the
V0 runway, or define S1's production operation contract (GOV-SLICE-007). The
OQ-1/S1 dependency conflation (GOV-SLICE-008) is resolved by the proposed
`Depends on:` field's explicit semantics at ratification time.
