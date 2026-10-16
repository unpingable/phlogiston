# SCV0-L7 — qualified live projection publication

Status: deterministic qualification complete 2026-08-24; live acquisition and
supervised polling pending.

## Composition

```text
SA1-qualified author/community snapshots
  + bounded communityd authority-write receipts
  -> exact experimental-record adapters
  -> unchanged M1 values
  -> unchanged M2 lifecycle reducer
  -> M5A ordinary/audit artifacts
  -> M6A public feeds
  -> immutable content-addressed generation
  -> atomic `current` pointer
  -> Juniper renderer
```

`communitywatch-space-publisher` is observer-only. It has no network client,
credentials, signing key, writer, database, server, or dependency on
`communityd`. It consumes the non-secret canonical result emitted by the
authority process, reconstructs the exact per-occurrence authorization, and
requires the independently qualified admission/removal record to match it.
The authority output cannot make a record visible by itself.

Snapshot histories are independently qualified repository states. SA6 remains
the classifier for equality, newer-snapshot reconciliation, conflict, and
staleness. The compiler records no complete-history or global-currentness
claim. Transport failure is a separate explicit observation from qualified
record absence.

## Lifecycle behavior

An exact current source remains `Added`. A later source CID produces
`ChangedAtSource`; under the frozen V0 rule, the admitted presentation is
hidden rather than silently replaced or served as a stale copy. Qualified
absence produces `SourceUnavailable` with `deleted_by_author`; acquisition
failure produces the same lifecycle family with the distinct `unavailable`
relationship. Author withdrawal and community removal remain separate exact
events and retain their admission/source history.

The ordinary feed omits technical occurrence references. The audit feed may
include the exact admission record URI and CID so an author can create a
strong-reference withdrawal and a reader can inspect the bounded event chain.
Neither disclosure channel contains OAuth, DPoP, Space credentials, writer
secrets, or moderator-private material.

## Atomic publication

One ordinary/audit pair is written, fsynced, and retained below a generation
directory named by its content-derived identity. Only then is the local
`current` symlink replaced atomically. Prior generations remain available for
custody and rollback analysis. The renderer resolves `current` only when it
points to one direct, hex-addressed child of `generations`; it refuses pointer
escape. Legacy fixed fixture directories remain readable for deterministic
tests.

## Guarantees and non-claims

This layer proves deterministic composition from the supplied qualified states
and exact authority occurrences into one disclosure-scoped publication. It
does not prove authentic acquisition, unseen-history completeness, reader
authorization, moderator standing, community legitimacy, source truth,
popularity, or human comprehension. The fresh uncoached human trial required
by SCV0-D2 remains a release gate after the live lifecycle is exercisable.

## Hostile witnesses

- missing/substituted authority output or extra authority claims refuse;
- stale, conflicting, cross-repository, or reordered qualified snapshots
  refuse;
- changed and deleted source content is never republished from the current
  source under the old admission;
- author withdrawal cannot become community removal, and removal cannot mutate
  the author source;
- duplicate authority occurrences conflict rather than deduplicate;
- untyped publication input and a content-address collision refuse;
- the renderer refuses a `current` pointer outside immutable generations;
- deleted-by-author and temporarily-unavailable copy remain visibly distinct.

## Replacement boundary

A future supervised acquisition loop may construct the same `QualifiedSnapshot`
and `AuthorityWriteReceipt` inputs from hosted Spaces artifacts. Replacing that
loop or the local filesystem publication mechanism must not change SA1, M1,
M2, M5A, or M6A semantics.
