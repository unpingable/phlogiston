# SA10a — empty repository state qualification

Status: fixture-qualified on 2026-08-21 against the unchanged Spaces alpha and
SA1 compatibility pins.

SA10a adds a state-level receipt for the ordinary zero-record boundary. The
existing SA1 verifier still establishes commit structure, author/Space context
signature, commit MAC, canonical empty index, and the LtHash digest. SA10a then
binds those exact block/state identities into one empty-state receipt. It emits
no `RepoRecord` and no `SpaceObservationReceipt`.

An SA10a-qualified empty state can be the source of unchanged SA4 transition
qualification. The positive lifecycle witness proves empty → first record and
SA6 classifies the supplied relationship as `qualified_transition`. An empty
snapshot without the SA10a receipt remains ineligible as SA4 transition
evidence. Receipt relabeling and nonempty evidence passed to the empty qualifier
are refused.

The receipt does not prove record existence, complete or uninterrupted
history, currentness, source authority, standing, authorization, or governance
authority. Empty state validity is not proof that the repository was always
empty or that no newer state exists. Recovery still cannot manufacture missing
provenance.

The alpha does not provide a special empty-repository wire object: the pinned
behavior is the ordinary signed permissioned commit plus an empty canonical
index and zero LtHash accumulator. Likely commit/index churn remains isolated
to SA1/SA2; the state-level lifecycle seam is isolated in `empty_state.py`.
