# SA6 — Spaces alpha reconciliation and recovery qualification

**Status:** deterministic classifier over existing SA1/SA4 outputs; no
network, notification listener, state store, credential, authority, write, or
deployment behavior. **Upstream observation date:** 2026-08-21.

## Architectural result

```text
known SA1-qualified state
new SA1-qualified state
optional exact SA4 transition receipt
        |
        v
SA6 bounded reconciliation
        |
        +-- equal_state
        +-- qualified_transition
        +-- snapshot_only
        `-- insufficient_evidence
```

SA6 compares the repository identities derived by SA4 from already qualified
states. Observation receipt IDs are deliberately excluded from semantic state
equality so re-fetching identical bytes at a later time is `equal_state`, not a
new state or freshness proof.

An SA4 receipt produces `qualified_transition` only when its exact source and
target repository identities match the supplied known and observed states. A
later qualified revision without that link is `snapshot_only`. Older states,
same-revision conflicts, cross-Space/author states, and mismatched transition
evidence are `insufficient_evidence`.

## Guarantees

Given independently qualified inputs, SA6 establishes only the classification
that follows from their exact identities and any exact linking SA4 receipt. It
therefore supports bounded recovery behavior:

- retry/replay of an identical state is idempotent (`equal_state`);
- a missed notification can recover a later valid snapshot without inventing
  a transition (`snapshot_only`);
- a supplied exact SA4 link remains `qualified_transition`; and
- stale, conflicting, cross-Space, or gap-bearing evidence is not forced into
  transition acceptance.

## Non-claims

There is intentionally no `history_verified` disposition. SA6 does not prove
complete knowledge, uninterrupted history, immediate ancestry, absence of
unseen operations, wall-clock freshness, current authority, access,
membership, standing, authorization, or governance legitimacy. A greater TID
is used only to distinguish a later supplied snapshot from a stale one; it is
not an ancestry proof. Reconciliation time is provenance, not freshness.

All result authority, authorization, currentness, and complete-history fields
are fixed to `false` and guarded against relabeling.

## Alpha assumptions and pins

SA6 inherits the SA1 state identity and SA4 transition semantics pinned to
`bluesky-social/atproto` commit
`89deb9faca20e56fa2a262fe9746ed52bc1095ba`. Its compatibility method is
`qualified-state-relation+optional-sa4-transition`, version `sa6-v1`.
`sa6-reconciliation.json` contains only references to the existing synthetic
SA4 states and expected bounded dispositions.

Upstream does not supply a complete-history commitment in the permissioned
commit or operation log. SA6 makes no attempt to manufacture one.

The same-revision conflict witness also reflects the pinned deniable-signature
shape: the signature binds the Space/author/revision/IKM context, while the
repository hash is linked through a MAC derived from the published IKM. The
test deterministically changes a record set and recomputes that hash/MAC under
the same signed context. Both supplied states can therefore pass SA1's bounded
checks while conflicting at one revision. SA6 treats this only as
`insufficient_evidence`; it does not select a canonical state or infer intent.

## Replacement boundary

Recovery policy is isolated in `reconciliation.py`. Changes to notification
delivery, oplog retention, or future ancestry material can replace or extend
that classifier without changing SA1 qualification, SA2/SA5 adapters, SA4
receipts, admission, or governance semantics.

## Witnesses

Tests cover semantic equality across different observation times, exact SA4
transition linkage, a newer snapshot after a notification gap, stale/replayed
state, missing intermediate context, conflicting transition evidence, and an
otherwise identical state identity relabeled to another Space. The latter
cannot be upgraded to `equal_state`. All four dispositions are enumerated and
`history_verified` is absent.
