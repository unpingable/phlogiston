# SCV0-M2 — projection lifecycle reducer

Status: **qualified against deterministic fixtures** on 2026-08-22.

SCV0-M2 adds the separately installable `community-space-projection` package.
It is a pure, synchronous reducer over SCV0-M1 values and explicit
source-observation receipts. It has no transport, credential, persistence,
writer, policy, reader-session, UI, or serving behavior.

## Doctrine

```text
source state             != community admission state
community admission      != projection state
author mutation          != community decision
source absence           != community removal
projection update        != source mutation
```

The reducer answers only:

> Given these qualified community records and bounded source observations,
> what projection lifecycle state follows?

It does not decide whether to admit, who may moderate or read, whether content
is good or true, or whether referenced external receipts are authentic. Those
decisions remain at their issuing boundaries.

## Reducer contract

`ProjectionReducer` is bound to one `CommunityIdentity`. Its methods accept:

- a qualified M1 `Submission` and exact initial `SourceObservation`;
- a prior reducer state, exact M1 `ModeratorAuthorization` and
  `CommunityAdmission`, plus a successor exact-source observation;
- a prior admitted state plus a successor source observation; or
- a prior admitted state plus an exact M1 `RemovalRecord`.

Every noninitial source observation names the exact predecessor observation
and a separate currentness-receipt reference. The reducer follows that link;
it does not infer currentness from acquisition time, revision text, response
order, or repetition. `observedAt` is retained and must not contradict the
declared predecessor chronology, but it is not itself freshness proof.

Every `ProjectionLifecycle.state_id` is a SHA-256 digest of versioned canonical
JSON over the stable projection identity, lifecycle state, exact submission,
admission if present, source-observation identity, M1 projection reference if
present, removal if present, exact prior state, transition kind, ordered
transition inputs, and source-terminal flag. There are no random IDs, mutable
counters, or wall-clock-only identities.

## State table

| State | Required evidence | Reader-facing meaning | Explicit non-meaning |
| --- | --- | --- | --- |
| `Suggested` | exact qualified post + self-submission | community may consider the item | accepted or authorized to admit |
| `Added` | suggested lifecycle + exact admission/authorization + current exact source | community projection includes this admitted source version | community owns the source |
| `ChangedAtSource` | admitted lifecycle + successor present source with a different CID, or terminal old-CID reappearance | admitted author-owned source no longer has an eligible exact lifecycle | implicit readmission |
| `SourceUnavailable` | admitted lifecycle + qualified absence or bounded unavailable observation | admitted source cannot currently be projected | community removal |
| `Removed` | admitted lifecycle + exact append-only removal | community stopped projecting the item | source deletion or mutation |

Qualified absence and temporary inability to check are retained as distinct M1
projection relationships under the reader term `SourceUnavailable`:

- absence uses `deleted_by_author` and terminalizes the old admission;
- temporary unavailability uses `unavailable` and can recover to `Added` only
  through an explicit successor exact-source observation;
- a CID change or qualified absence is terminal for that admission, so later
  reappearance of the old CID remains `ChangedAtSource` rather than silently
  reviving `Added`.

Community removal dominates later source observations. A newly available
source therefore leaves the lifecycle `Removed` until a genuinely new
submission and admission are supplied by a later authorized campaign.

## Retained history

Reduction is append-shaped. A removed result retains the original submission,
admission, historical projection reference, current source observation,
removal record, exact prior-state ID, and ordered transition input IDs. It
does not erase or rewrite any earlier record. The reducer does not persist
history; callers must retain the addressed input/state objects if they need a
replay log.

Duplicate and conflicting admissions or removals are stable refusals. Nothing
is silently deduplicated, sorted, merged, or chosen as a winner.

## Claim boundaries

Projection state is rendering state only. It does not establish:

- source truth, quality, or endorsement;
- popularity, score, votes, ranking, or ordering authority;
- Space membership or community standing;
- moderator legitimacy or governance authority;
- reader entitlement or permissioned-data disclosure;
- source ownership, mutation, or deletion;
- global currentness beyond the supplied qualified predecessor/currentness
  references.

The result models do not accept caller-extensible claim fields.
`refuse_projection_claim_upgrade` rejects ranking, authority, visibility, and
source-mutation relabeling rather than retaining it as projection truth.

## Fixtures and witnesses

The fixture extends SCV0-M1's synthetic `invalid.test` identities and records
with exact, changed, absent, unavailable, and reappeared source observations.
It contains no credential or secret material. Fixture SHA-256:

```text
fc1e95e7654959a0cc99e25e7428dfee8824ff0334af04714183d311e89aab2c
```

M2-P1 through M2-P6 establish suggestion, addition, changed-source,
source-unavailable, removal, and retained-history behavior. M2-H1 through
M2-H12 refuse missing admission/submission, implicit readmission, deletion as
community removal, source mutation, automatic post-removal revival,
cross-community projection, stale timestamp laundering, duplicate/conflicting
admission, out-of-order lifecycle, ranking injection, and authority relabeling.
Additional witnesses keep CID-change terminality, source-path binding,
transition-evidence completeness, prior-state custody, and absence/unavailable
flavors explicit.

## Package and replacement boundary

`community-space-projection` depends only on `community-model` and the inert
`community-space-model`. Package-boundary tests prohibit observer,
`communityd`, network, transport, credentials, signing, SQLite/storage,
server/web, writer, and ranking dependencies. Public V0 projection and the
SA0–SA10d evidence stack remain unchanged.

The source-observation adapter can later be replaced by a composition from
SA1/SA6/SA10d receipts without changing lifecycle meanings. A future reader
session/disclosure layer may consume these states, but may not change them or
infer reader entitlement from them.

## Deferred boundaries

SCV0-M2 adds no reader sessions, disclosure policy, feed, ranking, UI,
transport, credentials, database, background worker, author/community writer,
live data, or deployment. SCV0-M3 remains the next predeclared slice, but it is
a materially different author-side write boundary and requires its own exact
wire/schema and capability review before implementation.
