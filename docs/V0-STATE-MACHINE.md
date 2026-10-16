# V0 state machine

## Model

State is a deterministic projection over immutable observations. It is never a
mutable status written back into an authority record. The projection keeps four
kinds of truth separate:

1. **Repository observation:** which signed record version or delete operation
   the indexer observed, with its commit envelope.
2. **Structural validity:** whether that record matches the provisional schema
   and its exact references agree.
3. **Authority validity:** whether an admission/action came from the configured
   community repo with authenticity evidence accepted by the ratified trust
   policy and configured actor attribution.
4. **Subject availability:** whether the admitted URI currently resolves to the
   admitted CID.

An event can remain audit-worthy while having no effect on the current view.

## Projected states

| State | Meaning | Rendered |
|---|---|---:|
| `pending` | A required referenced record has not arrived, or resolution failed without proving absence. | No |
| `submitted` | A valid self-submission and exact post exist, but no valid admission exists. | No |
| `visible` | A valid admission exists for the exact current post version and no masking state applies. | Yes |
| `invalid` | Schema, repository ownership, collection, community, or exact-reference validation failed. | No |
| `unauthorized` | An authority-shaped record came from the wrong repo or names a nonconfigured actor. | No |
| `stale_cid` | Admission validation finds, or later observes, a post CID different from the admitted CID. | No |
| `subject_deleted` | Admission validation finds, or later observes, a post delete/authoritative not-found. | No |
| `subject_unavailable` | A transient resolver/transport error prevents an exact check. | No |
| `removed` | A valid removal masks the exact admitted post version in this community. | No |
| `conflict` | Observations require unsupported semantics or violate create-only authority identity. | No |

`invalid`, `unauthorized`, and `conflict` are also audit finding classes. They
do not erase the underlying observations.

## Validity predicates

### Submission

A submission is valid only if:

- the envelope operation is `create` or `update` with an exact record CID;
- its record repo DID is the DID authority in `subject.uri`;
- `subject.uri` uses a DID authority and the
  `app.bsky.feed.post` collection;
- `subject` contains both URI and CID;
- `community` equals the configured community DID; and
- the record timestamp and all DID/URI/CID values validate. Timestamp must have
  an RFC 3339 offset and may not exceed first accepted receipt by five minutes.

Self-submission is an envelope invariant; a redundant submitter field cannot
prove it. Before admission, both the exact submission and subject must resolve
for `communityd`. The proposed V0 rule after admission is that the observed
submission remains historical intent even if the user later updates/deletes
the submission. This proposal is called out for ratification in
`OPEN-QUESTIONS.md`; it must not become an accidental implementation detail.

### Admission

An admission is valid only if:

- it is a create event in the configured community actor repo;
- repository authenticity evidence satisfies the selected ingest trust model;
- `actor` equals the configured administrator DID;
- its exact submission record is valid and current at first admission
  validation (later mutation is governed by OQ-5);
- its submission and subject strong references match exactly; and
- its rkey/payload agrees with the writer's immutable operation identity.

An admission seen before its submission is `pending`, not invalid. It is
re-evaluated when the dependency arrives.

### Removal

A removal is valid only if:

- it is a create event in the configured community actor repo;
- repository authenticity policy and `actor` authorization pass;
- `action` is exactly `remove`;
- its admission strong reference identifies a valid admission; and
- its repeated subject strong reference exactly matches that admission.

A syntactically valid but more-than-five-minute future `createdAt` emits a
finding but does not cancel an otherwise valid removal; removal ordering comes
from community-repo commit order. A malformed datetime remains structurally
invalid.

Removal applies to the exact `(community DID, subject URI, subject CID)`, not
to the post at every future CID. It masks every duplicate admission for that
exact version so a duplicate record cannot bypass moderation.

## Normal transitions

```text
valid submit + exact subject
  unseen/pending -> submitted

valid admission + exact subject
  submitted/pending -> visible

different current post CID found during admission validation or observed later
  submitted/pending/visible -> stale_cid

post deletion/not-found found during admission validation or observed later
  submitted/pending/visible/stale_cid -> subject_deleted

transient resolver failure
  visible -> subject_unavailable -> visible on a later exact result

valid removal
  visible/pending/stale_cid/subject_deleted -> removed

new submission + admission for a newly exact current version
  stale_cid/subject_deleted -> a new visible admission lifecycle
```

A mismatch or confirmed deletion is terminal for the affected admission
lifecycle. Reverting the post to an earlier CID does not revive that admission;
a new exact submission and admission are required. A transient resolver error
is not deletion and is reversible without new authority.

Mismatch/missing becomes terminal only from resolver evidence accepted by its
configured trust mode. Unverified/failed resolution is `subject_unavailable`,
never proof of deletion or mutation.

## Precedence

For each community and exact subject version, reduce valid observations in this
order:

1. Malformed, unverified, and unauthorized records have no authority effect.
2. No valid admission yields `submitted` or `pending`.
3. Any valid removal yields `removed`.
4. A create-only authority identity/payload collision yields `conflict`.
5. A confirmed post deletion yields `subject_deleted`.
6. An observed post CID change yields `stale_cid`.
7. A current resolver error yields `subject_unavailable`.
8. An exact current post yields `visible`.

Removal precedes duplicate handling deliberately. Once the community removes
an exact version, another admission record cannot make that version visible.

## Replay, duplicates, and conflicts

Delivery duplication and semantic duplication are different:

- Re-delivery of the same repository event is idempotent. Semantic identity is
  `(repo DID, required rev:<validated repo revision>, collection, rkey,
  operation)`. Record CID and payload hash are evidence outside that identity.
  Arrival time and
  SQLite rowid are never identity.
- The semantic event variant, immutable source receipt/authenticity evidence,
  projection changes, and that source's durable cursor checkpoint commit
  together. The same semantic identity with a different CID/payload is retained
  as a second variant rather than ignored. Only variants accepted by the trust
  policy can conflict in projection; unverified testimony cannot suppress a
  verified event.
- Multiple submission records for the same community, author, URI, and CID
  remain in audit and group as one semantic intent for display/audit counting,
  but each exact submission ref retains its first observed observer sequence
  for lifecycle eligibility.
- Multiple valid admissions for the same exact subject remain in audit but
  render one card. The earliest valid `(createdAt, admission URI)` supplies the
  display time, preventing duplicates from bumping chronology.
- A removal masks all such admissions for that exact subject.
- A new admission for the same exact subject after removal is unsupported in
  V0: `communityd` refuses it. If observed anyway, the projected entry remains
  `removed` and `communitywatch` emits an `unsupported_readmission` conflict
  finding. New-CID submission/admission is a different lifecycle.

Cross-repository arrival order cannot change reference validity: unresolved
strong references remain pending and are re-evaluated. Subject history is
observer-relative and fully captured by stored sequences. Generation-scoped
semantic tables are disposable and must rebuild
content-equivalently from stored observations plus versioned projection rules;
local generation IDs, cursors, heartbeats, and build timestamps are excluded.

Each exact submission strong reference owns a logical admission lifecycle;
individual admission URI+CID rows point to it. A mismatch/deletion is terminal
for every duplicate admission of that submission. First validation creates a
fresh subject observation and persists its local monotonic `observer_sequence`
as lifecycle start; an adverse start initializes terminal state without
flashing visible. Later observations apply by stored observer sequence (stable
observation-key tie-breaker), never reducer insertion order. Another admission
referencing the same submission cannot revive it. A distinct new submission
plus admission can create a lifecycle after terminal mismatch/deletion only if
both records' first observed global observer sequences are later than the
latest terminal observation sequence for that exact subject. “First” includes
unverified observation; later trusted corroboration grants eligibility but
cannot refresh the record's causal age. Thus equivalent
intent or authority that predated the terminal event cannot be held in reserve
as a restore. Eligible later intent can create a lifecycle even if the post
reverts to a previously used CID; the earlier lifecycle remains terminal. The
rendered `community_entry` aggregates
eligible lifecycles rather than storing terminal history itself.

“After removal” is determined by authenticity-accepted community-repository
commit order, never `createdAt` or observer arrival. If multiple valid removals exist, the
earliest in that repo order (action URI tie-breaker) is canonical for projected
reason/context; all remain in audit and all mask the exact subject.

## Authority-record mutation

`communityd` creates records and exposes no update/delete operation.

- Updating or deleting an admission outside `communityd` cannot grant or
  preserve visibility. Retain every observation, emit a mutation finding, and
  fail that admission closed.
- Updating or deleting a removal cannot silently restore content. Retain the
  previously observed removal effect and emit a mutation finding.
- The community profile is a declaration and may be updated; each version is
  still audited.

This asymmetric, most-restrictive behavior is a V0 safety boundary, not a
general governance system or future restore policy.

## Audit limits

The observer can prove an append-only history of what it observed. A fresh
indexer reading only current repo state cannot recover records edited/deleted
before it saw them. Any claim of globally reconstructible audit history needs
archive manifests, signed snapshots, or later fork/replay work. V0 must state
this limitation rather than calling its local observation log canonical truth.
