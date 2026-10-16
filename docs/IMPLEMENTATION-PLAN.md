# V0 implementation plan

## Purpose and fixed boundaries

V0 is one public community actor projecting signed community context over
ordinary user-owned `app.bsky.feed.post` records. Its canonical proof is:

```text
submit -> admit -> render in a minimal web AppView -> remove
```

The PDS is unchanged. The author retains the post. Removal changes only the
community projection. The web surface is canonical; a feed generator is a
later compatibility surface.

## Repository and package layout

V0-M1 starts with three independently installable Python distributions in one
repository:

```text
packages/
  community-model/       # import: community_model
  communitywatch/        # import: communitywatch
  communityd/            # import: communityd
tests/
  acceptance/
config/
  communitywatch.example.toml
  communityd.example.toml
```

`community_model` contains frozen value types, provisional record models,
strict validation, canonical JSON/hashing, state enums, and a pure
deterministic reducer. It has no network, database, credential, signing, or
ATProto SDK dependency.

`communitywatch` depends on `community_model` and narrowly scoped read-only
transports. It owns ingestion, subject resolution, SQLite persistence and
projection, audit queries, the JSON read API, and minimal HTML AppView. It
must not depend on `communityd`, a credential provider, or a general ATProto
client exposing writes.

`communityd` depends on `community_model`. It owns its own record reader,
administrator authorization, credential provider, and authority-writer
interfaces. It must not import `communitywatch` or open the observer database.

V0-M2A adds a separately installable observer-only archive tool. Its exact
packaging as an optional observer extra or a fourth distribution is a bounded
implementation choice, but its dependency and import closure is not: DuckDB
and PyArrow are absent from the index/web and `communityd` runtime dependency
closures, and those processes' import graphs do not reach archive code. The
archive tool may depend on `communitywatch` and `community_model`; neither may
depend on it. It has no network transport, credential, signing,
authority-writer, or community-repository write path.

Each distribution has its own `pyproject.toml`, tests, dependency metadata,
and console entry points. A root, non-publishable tooling configuration may
coordinate checks but must not collapse the packages into one wheel.

The only permitted product dependency edges are:

```text
observer archive tool ---> communitywatch ---> community_model <--- communityd
```

## Runtime processes

### `communitywatch-index`

- Is the sole migrator and live writer of the observer SQLite database.
- Reads public repository events, stores immutable observations, resolves
  relevant post versions, and transactionally rebuilds current projections.
- Subscribes only to the four configured community collections. It does not
  ingest the global post firehose; referenced posts are fetched by the exact
  resolver initially and on the refresh schedule.
- Applies backpressure rather than dropping authority-ledger events.
- Checkpoints an ingest cursor only in the transaction that durably stores
  and projects every event through that cursor.
- Has no authority credential, signing dependency, or write adapter.

### Observer archive tool

- Runs only as an explicitly invoked offline maintenance CLI with
  `communitywatch-index` and `communitywatch-web` stopped.
- Closes an observer/source high-water, stages and seals immutable Parquet
  generations, verifies manifests and hot/cold parity, and may prune exactly
  covered SQLite observation detail only after every retention gate passes.
- Opens sealed, manifest-listed artifacts through DuckDB for bounded parity,
  audit, and rebuild queries; it never puts DuckDB on ingest or request paths.
- Updates only observer archive-control and retention state. It cannot write an
  ATProto repository or confer community authority.

### `communitywatch-web`

- Opens SQLite with URI read-only mode and `PRAGMA query_only=ON`.
- Serves `GET` and `HEAD` only and performs no network resolution in a request.
- Exposes:
  - `GET /c/{slug}`: canonical, escaped community page;
  - `GET /c/{slug}/audit`: human-readable admission/removal log;
  - `GET /api/v0/communities/{did}/posts`: visible projected entries;
  - `GET /api/v0/communities/{did}/audit`: immutable events and outcomes; and
  - `GET /health`: schema, projection version, cursor, and freshness.
- Refuses to serve a partial or incompatible projection and displays stale or
  degraded state explicitly.

### `communityd`

- Is a manual local CLI in V0, not a public HTTP service.
- Proposes OS access to the process as the development authorization boundary,
  pending an OQ-4 selected decision. The configured administrator DID is
  community-attested attribution, not an independently proven user signature;
  real administrator authentication is an explicit pre-network decision in
  `OPEN-QUESTIONS.md`.
- Reads exact referenced records and creates only immutable admissions and
  removals in the configured community actor repository.
- Never receives an observer database or configuration path.
- Offers no record update or delete operation.

Deployment uses separate OS principals, virtual environments, configuration
paths, and writable directories. Only the `communityd` principal may read its
external credential reference.

## Shared and service interfaces

The following shapes are contracts, not an instruction to put transport code
in the shared package:

```python
@dataclass(frozen=True)
class RecordRef:
    uri: str
    cid: str

@dataclass(frozen=True)
class IncomingDelivery:
    source: str
    cursor: str
    source_event_time: datetime | None
    received_at: datetime
    raw_envelope: bytes | Mapping[str, object]
    trust_mode: Literal["verify_repo", "trust_relay", "test_fixture"]
    verification_outcome: Literal["verified", "attested", "unverified", "failed"]
    verification_method: str
    verifier_version: str
    evidence_ref: str | None
    evidence_hash: str | None

@dataclass(frozen=True)
class RepoEvent:
    semantic_event_key: str
    event_variant_key: str
    commit_identity: str
    repo_order: str
    repo_did: str
    operation: Literal["create", "update", "delete"]
    collection: str
    rkey: str
    record_uri: str
    record_cid: str | None
    commit_rev: str | None
    commit_cid: str | None
    record: Mapping[str, object] | None
    record_bytes: bytes | None
    payload_hash: str
    payload_hash_scope: Literal[
        "dag_cbor", "observer_json_v0", "delete_envelope_v0"
    ]

@dataclass(frozen=True)
class EventReceipt:
    event_variant_key: str
    source: str
    cursor: str
    source_event_time: datetime | None
    received_at: datetime
    observer_sequence: int
    trust_mode: Literal["verify_repo", "trust_relay", "test_fixture"]
    verification_outcome: Literal["verified", "attested", "unverified", "failed"]
    verification_method: str
    verifier_version: str
    evidence_ref: str | None
    evidence_hash: str | None

@dataclass(frozen=True)
class ResolveResult:
    status: Literal["exact", "mismatch", "missing", "error"]
    requested: RecordRef
    current_cid: str | None
    record: Mapping[str, object] | None
    checked_at: datetime
    trust_mode: Literal["verify_repo", "trust_pds", "test_fixture"]
    verification_outcome: Literal["verified", "attested", "unverified", "failed"]
    resolution_method: str
    resolver_version: str
    evidence_ref: str | None
    evidence_hash: str | None

@dataclass(frozen=True)
class CurrentRecordResult:
    status: Literal["present", "missing", "error"]
    uri: str
    current_cid: str | None
    record: Mapping[str, object] | None
    checked_at: datetime
    trust_mode: Literal["verify_repo", "trust_pds", "test_fixture"]
    verification_outcome: Literal["verified", "attested", "unverified", "failed"]
    resolution_method: str
    resolver_version: str
    evidence_ref: str | None
    evidence_hash: str | None

@dataclass(frozen=True)
class AuthoritySubjectState:
    subject: RecordRef
    valid_admissions: tuple[RecordRef, ...]
    valid_removals: tuple[RecordRef, ...]
    community_repo_high_water: str

@dataclass(frozen=True)
class AuthorizedAdmin:
    did: str
    effective_uid: int
```

The index normalizer represents commit identity as
`rev:<validated ATProto repository revision>`; commit CID and proof remain
evidence, not alternate identities.
`repo_order` compares the validated raw revisions with the ATProto TID
comparator. An event lacking a valid repo revision is quarantined/audited but
cannot enter authority projection.

`semantic_event_key` is `sha256:<lowercase hex>` over UTF-8
`v0 NUL repo_did NUL commit_identity NUL collection NUL rkey NUL operation`
(the validated fields cannot contain NUL); incoming adapters cannot supply an
arbitrary identity. `commit_identity` and comparable within-repo
`repo_order` are required. A local verifier uses the signed commit identity and
chain order; a relay adapter records its weaker attested identity/order in the
receipt evidence under the OQ-2 policy. Record CID/payload hash are deliberately
outside the key so conflicting testimony remains detectable.

`IncomingDelivery` is the transport boundary and has no derived key or observer
sequence. The index writer decodes/validates its raw envelope, derives
`RepoEvent` keys/hashes/order, allocates the global sequence, and constructs the
stored `EventReceipt` in the same transaction. Invalid/missing revision or
undecodable input becomes `quarantined_deliveries` with that cursor/sequence;
the adapter never fabricates a valid event just to advance a checkpoint.

`event_variant_key` is SHA-256 over UTF-8
`v0 NUL semantic_event_key NUL record_cid-or-dash NUL payload_hash_scope NUL
payload_hash`. Delivery receipts foreign-key this variant, so conflicting CIDs
or payload testimony never borrow one another's verification evidence.

When locally verified DAG-CBOR bytes exist, `payload_hash` is SHA-256 of those
bytes with scope `dag_cbor`. A JSON-only adapter uses V0 UTF-8 JSON (sorted
keys, compact separators, Unicode preserved, no NaN) with scope
`observer_json_v0`; this is observer evidence, not a CID. Deletes hash the
canonical event envelope under `delete_envelope_v0`. Raw bytes are retained
when available, and hash scope always travels with the hash.

`communitywatch` owns these ports:

```python
EventSource.read(after_cursor: str | None) -> EventBatch[IncomingDelivery]
SubjectResolver.resolve_exact(ref: RecordRef) -> ResolveResult
CommunityQuery.list_visible(community_did, limit, cursor) -> Page
CommunityQuery.list_audit(community_did, limit, cursor) -> Page
```

`communityd` owns separate ports:

```python
RecordReader.get_exact(ref: RecordRef) -> ResolveResult
RecordReader.get_current(uri: str) -> CurrentRecordResult
AuthorityLedgerReader.find_subject_lifecycle(
    community_did: str, subject: RecordRef
) -> AuthoritySubjectState
AdminAuthorizer.require(action) -> AuthorizedAdmin
AuthorityWriter.create_immutable(
    repo_did, collection, semantic_operation_id, record
) -> RecordRef
```

`AdminAuthorizer` obtains the local effective UID from the process, compares it
with the daemon configuration, and returns the single configured administrator
DID; callers cannot supply that DID. This is the proposed OQ-4 local model.

`AuthorityLedgerReader` is daemon-owned and reads/paginates the community
actor's current admission/action collections directly. It never queries
communitywatch or observer artifacts. It exists specifically so a removed exact
subject cannot be re-admitted through a second submission.

`create_immutable` derives a deterministic rkey from the semantic operation
and checks that key before creation. A compatible existing record is returned;
incompatible authority-defining fields are a hard conflict. For a new record,
one payload and `createdAt` are retained across in-process retries; after an
ambiguous crash, a later invocation discovers the existing record by rkey.
Admission compatibility compares submission, subject, and actor. Removal
compatibility compares action, admission, subject, actor, and requested reason;
only generated `createdAt` is excluded.
Admission identity derives from the exact submission URI+CID; removal identity
derives from the exact admission URI+CID. A new submission can therefore mint
a new admission lifecycle after a recorded CID mismatch, including a post that
reverts to an earlier CID. The ledger reader—not the operation rkey—enforces
the no-readmission-after-removal rule. The port exposes no overwrite/delete.

JSON pagination sorts by signed admission `createdAt` descending, then
admission URI descending as a stable tie-breaker. The opaque cursor encodes
that pair. Limits are bounded to 1–100. This is chronology, not a ranking
algorithm.

Every signed `createdAt` must be RFC 3339 with an explicit offset and is
normalized to UTC for comparison/output. A value more than five minutes after
the semantic event's first accepted observer receipt produces
`created_at_future`; older timestamps are allowed. It invalidates profile,
submission, and admission effects so future time cannot pin chronology. A
well-formed, otherwise valid removal still masks fail-closed because removal
ordering uses community-repo order, not its timestamp. Arrival/source times
never replace signed chronology. Raw timestamps remain immutable.

### Read API wire shape

`GET /api/v0/communities/{did}/posts?limit=50&cursor=...` returns:

```json
{
  "community": {
    "did": "did:web:community.invalid",
    "slug": "homelab",
    "displayName": "Homelab",
    "description": "..."
  },
  "entries": [
    {
      "subject": {"uri": "at://...", "cid": "bafy..."},
      "submission": {"uri": "at://...", "cid": "bafy..."},
      "admission": {"uri": "at://...", "cid": "bafy..."},
      "authorDid": "did:...",
      "admittedAt": "2026-07-10T14:02:00Z",
      "post": {"text": "...", "createdAt": "2026-07-10T14:00:00Z"},
      "sourceUrl": "https://bsky.app/profile/.../post/..."
    }
  ],
  "cursor": null,
  "projectionVersion": "v0",
  "generatedAt": "2026-07-10T14:04:00Z"
}
```

Only the minimal post text/time needed by the page is hydrated in V0; arbitrary
embeds are not rendered. `sourceUrl` is a convenience link, never identity.

`GET /api/v0/communities/{did}/audit?limit=50&cursor=...` returns the same
community identity and pagination metadata with this core shape:

```json
{
  "communityDid": "did:web:community.invalid",
  "events": [
    {
      "auditRowKey": "event:sha256:...:sha256:...",
      "semanticEventKey": "sha256:...",
      "eventVariantKey": "sha256:...",
      "payloadHash": "sha256:...",
      "payloadHashScope": "dag_cbor",
      "record": {"uri": "at://...", "cid": "bafy..."},
      "operation": "create",
      "kind": "admission",
      "subject": {"uri": "at://...", "cid": "bafy..."},
      "actor": "did:web:admin.invalid",
      "reason": null,
      "createdAt": "2026-07-10T14:02:00Z",
      "firstReceivedAt": "2026-07-10T14:02:01Z",
      "verificationOutcomes": ["verified"],
      "receiptCount": 1,
      "outcome": "valid",
      "reasonCodes": []
    }
  ],
  "cursor": null,
  "projection": {
    "generation": "g1",
    "version": "v0",
    "fresh": true
  },
  "generatedAt": "2026-07-10T14:04:00Z"
}
```

Audit sorts by first observer receipt descending, then stable `auditRowKey`.
Event rows use `event:<semanticEventKey>:<eventVariantKey>`; quarantined
deliveries use `quarantine:<lowercase SHA-256 hex>` over UTF-8
`v0 NUL source NUL cursor NUL raw-envelope-hash`. Its opaque cursor encodes
receipt time plus row key. It labels the ordering and does not claim global
commit order.
It emits one row per `eventVariantKey`; receipt count,
verification outcomes, record CID, and validation outcome belong to that
variant. Conflicting variants therefore appear as separate `conflict` rows with
`semantic_event_conflict`, never as one arbitrarily selected payload.
Quarantine rows have null semantic/event-variant keys and record, `kind` set to
`quarantine`, raw-envelope payload hash/scope, outcome `invalid`, and the
quarantine reason. Malformed input therefore remains auditable without being
invented into a repository event.
Allowed `outcome` values are `valid`, `pending`, `invalid`, `unauthorized`,
`ignored`, `duplicate`, and `conflict`.

The stable V0 reason vocabulary is:

```text
schema_invalid                 unsupported_record_type
did_invalid                    at_uri_invalid
cid_invalid                    datetime_invalid
commit_revision_invalid        payload_evidence_invalid
created_at_future              community_mismatch
repo_mismatch                  subject_collection_invalid
strong_ref_mismatch            reference_pending
reference_missing              subject_cid_mismatch
subject_deleted                resolver_error
authenticity_unverified        authenticity_failed
authority_repo_mismatch        actor_unauthorized
authority_record_mutated       semantic_event_conflict
duplicate_semantic_record      unsupported_readmission
unsupported_action             profile_unavailable
projection_missing             projection_incomplete
projection_stale               schema_incompatible
ingest_stale                   resolve_stale
```

`GET /health` returns:

```json
{
  "status": "ok",
  "schemaVersion": 1,
  "projectionVersion": "v0",
  "activeGeneration": "g1",
  "projectionStatus": "complete",
  "highWaterMatches": true,
  "lastIngestAt": "2026-07-10T14:03:00Z",
  "lastResolveAt": "2026-07-10T14:03:30Z",
  "sources": [
    {
      "name": "primary",
      "committedCursor": "123456",
      "projectedCursor": "123456",
      "matches": true
    }
  ],
  "generatedAt": "2026-07-10T14:04:00Z",
  "reasonCodes": []
}
```

Health `status` is `ok`, `stale`, or `unavailable`. The current page/posts API
returns 503 unless a compatible active projection is complete and its
high-water matches committed ingest. Audit may return the last complete active
generation with `fresh: false` and a banner because it is observation history,
not the current moderation surface; it returns 503 only when no compatible
complete generation exists.

Errors are JSON `{ "error": "stable_code", "message": "safe text" }`.
Malformed cursors/limits return 400, unknown community 404, unsupported methods
405, and unavailable current projection 503. Health returns 200 only for `ok`;
otherwise 503. No response contains filesystem paths or raw exception text.

### Administrative CLI contract

```text
communityd --config PATH admit \
  --submission-uri AT_URI --submission-cid CID

communityd --config PATH remove \
  --admission-uri AT_URI --admission-cid CID [--reason TEXT]
```

The CLI does not accept an actor override. The proposed local authorizer checks
the effective UID against configured `allowed_uid` and returns the single
administrator DID. Success writes one JSON object to stdout containing
`operation` (`created` or `existing`) plus the authority record URI/CID; stderr
is reserved for redacted diagnostics. Failure leaves stdout empty and writes
`{ "error": "stable_code", "message": "safe text" }` to stderr.

Stable exits are: `0` success/help, `2` usage or configuration, `3` local
authorization, `4` record/reference validation, `5` immutable conflict or
unsupported readmission, `6` read/resolution unavailable, `7` credential
unavailable, and `8` write failed or remained ambiguous. Creation of the
user-owned submission is a client responsibility and is not performed by
either service.

## Exact V0 data flow

### Profile decoration

The latest authenticity-accepted current `app.phlogiston.community.profile/self` in
community-repo commit order decorates the page/API. Profile update is allowed.
Missing, invalid, unverified, or deleted profile never changes ledger validity;
the AppView falls back to configured slug as `displayName`, `null` description,
and the community DID. A bad new current profile triggers fallback rather than
silently retaining an older declaration.

### Submit

1. An author creates a normal `app.bsky.feed.post` in their repository.
2. The same repository creates a provisional community submission containing
   the target community DID and the post's exact AT URI and CID.
3. `communitywatch-index` first stores the raw repository event and its
   authenticity outcome, then parses it. Malformed or unverified relevant
   records remain audit-visible but cannot affect projection.
4. The submission is valid only when its repository DID equals the DID
   authority in the subject AT URI and its community, URI, CID, and timestamp
   validate. Handle authorities are rejected; canonical subject AT URIs use a
   DID authority.
5. The resolver records whether the exact post is current. A valid submission
   without admission is `submitted`: visible in audit, absent from the page.

Submission must still resolve exactly when `communityd` admits it. The
recommended rule, pending an OQ-5 selected decision, is that later update/deletion of
the submission does not revoke admission: V0 has no author-withdrawal action,
and the observed signed intent remains in audit. Post mutation/deletion still
fails display closed.

### Admit

1. The operator runs `communityd admit` with the exact submission URI and CID.
2. `communityd` checks the local principal, resolves the exact submission and
   subject, validates self-submission and community identity, and constructs
   an admission containing both exact references.
3. It queries the daemon-owned authority-ledger reader for the exact subject.
   A valid removal in community-repo order causes exit 5. Existing
   admissions do not block a distinct new submission lifecycle.
4. Otherwise the writer creates the admission in the community actor repo
   under a submission-derived deterministic, create-only rkey. A compatible
   record already at that rkey is returned as the same operation.
5. `communitywatch-index` accepts authority only from the configured community
   repo when its immutable receipt meets the trust policy selected under OQ-2 and
   its attributed actor equals the configured administrator DID. Relay
   attestation, if allowed, remains labeled `attested`, never `verified`.
6. Out-of-order admission remains pending until its exact submission is
   observed/resolved current. It becomes valid only if both records agree on
   community and subject; a submission already superseded/deleted before first
   validation cannot authorize admission.
7. First validation records a fresh, admission-triggered subject observation
   as the logical lifecycle's start coordinate. Exact, mismatch, missing, and
   error initialize visible, stale, deleted, and unavailable respectively; an
   externally emitted admission never flashes visible before this check.

### Render

- The web process reads only committed projection rows.
- The page shows `visible` entries in reverse admission chronology, including
  the escaped ordinary-post snapshot, author DID, admission time, and compact
  community-context marker.
- A scheduled resolver refresh records exact, mismatch, missing, or error
  observations for every active subject. The web request itself never fetches.
- Only outcomes accepted by the configured resolver trust mode can establish
  exact/mismatch/missing. Unverified/failed evidence yields temporary
  `subject_unavailable` and cannot terminalize a lifecycle.
- Missing posts, changed CIDs, resolver errors, authority conflicts, and
  incomplete projection builds are hidden rather than shown optimistically.
- A changed post becomes visible only through a new exact submission and a new
  admission. The prior admission remains stale in audit.

### Remove

1. The operator runs `communityd remove` with the exact admission URI and CID
   and an optional short reason.
2. `communityd` validates administrator, community, admission, and subject,
   then creates an immutable `remove` action at the admission-derived operation
   rkey in the community actor repo. It does not require the underlying post to
   remain exact or present; stale/deleted content must still be removable.
3. The action references the exact admission and repeats its exact subject.
4. `communitywatch-index` validates it and projects that exact community and
   subject version as `removed`. This also prevents a duplicate admission from
   bypassing a valid removal.
5. The post leaves the current page. Submission, admission, removal, and
   subject observations remain in audit. No service updates or deletes the
   author's post.

Repeated source delivery is idempotent. Multiple semantically equivalent
admissions for the same community and exact subject remain in audit but form
one logical entry using the earliest `(createdAt, admission URI)`; they cannot
bump chronology or bypass removal. Differing payload at one immutable operation
identity is `conflict` and hidden. Exact-subject readmission after removal
leaves projected state `removed` and adds an `unsupported_readmission` finding.
Unauthorized or malformed records remain audit-visible but have no effect.
Admission/removal updates or deletes made outside the create-only writer are
asymmetric and fail closed: a mutated admission loses visibility, while a
previously observed removal keeps masking its subject so deletion cannot act
as an accidental restore. Both emit findings; profiles may be updated normally.

## Persistence model

The observer uses one SQLite database in WAL mode with foreign keys, bounded
busy timeout, explicit transactions, forward-only migrations, and rejection
of a database newer than the running code. SQLite holds the transactional
present, compact audit index, and unexported immutable tail. Sealed Parquet
generations hold exported immutable history; a rebuild reads the accepted
sealed occurrence prefix and then the sequence-disjoint SQLite occurrence tail
without gaps. Stable payload variants may intentionally appear in both.

Hot immutable-tail tables are append-only while their rows remain in SQLite.
The offline archive tool may prune only an exact sealed prefix under the
retention contract below:

- `repo_events`: a local surrogate `event_id` (never portable identity), stable
  `semantic_event_key`, stable `event_variant_key`, event schema version,
  required commit identity and within-repo order, repo DID, operation,
  collection/rkey, record URI/CID,
  canonical record JSON, optional verified DAG-CBOR, and payload hash/scope.
  Unique identity is `event_variant_key` so a repeated equal variant is
  idempotent while two payload/CID claims under one semantic key remain
  explicit evidence rather than a silent `INSERT OR IGNORE`.
- `event_receipts`: immutable source delivery of one repo-event variant,
  foreign-keyed by `event_variant_key`, including source/cursor, optional source
  event time, observer `received_at`, globally monotonic local-custody
  `observer_sequence`,
  configured trust mode, verification outcome/method/version, and evidence
  reference/hash. Multiple sources may testify to one variant without
  overwriting provenance or duplicating it.
- `quarantined_deliveries`: raw envelope/hash, source/cursor, receipt time,
  global observer sequence, and reason for a delivery that cannot form a
  semantic event (including missing/invalid repo revision). Quarantine and
  cursor advancement still commit atomically; quarantined input has no effect.
- `subject_observation_variants`: normalized requested URI/CID, resolution
  status, current CID, record snapshot and payload hash/scope under a stable
  variant key. Repeated unchanged checks reference one bulky variant rather
  than copying its snapshot every minute.
- `subject_observations`: compact per-check receipts referencing a subject
  variant, including triggering event, checked time, resolution trust
  mode/outcome, method/version, evidence reference/hash, stable observation
  key, and the same global monotonic `observer_sequence` used by delivery
  receipts. The live writer allocates it transactionally; it is
  observer-causality, not portable event identity or a public cursor.

Multiple representation scopes do not by themselves mean semantic conflict.
Only variants with at least one receipt accepted by the ratified trust policy
participate; unverified/failed testimony cannot suppress an accepted
event. Among participating variants, the reducer compares claimed record CID
and normalized decoded content. Different CIDs for one semantic event conflict;
the same CID with disagreeing
decoded content conflicts; DAG-CBOR and observer-JSON evidence that decode to
the same record are corroborating variants.

Signed record `createdAt`, source event time, observer receipt time, and
subject-check time remain distinct. Audit observation order uses the earliest
receipt of any outcome; timestamp-skew validation uses the earliest receipt
accepted by the trust policy. A second source cannot bump either earlier value.
Which verification outcomes may influence projection is the explicit OQ-2
decision, never inferred from a bare boolean.

For lifecycle causality, `first_observed_sequence` is the minimum global
observer sequence among all receipts for the semantically equivalent exact
record, regardless of trust outcome. Authority still requires an accepted
receipt, but freshness compares first observed—not first accepted—with terminal
subject-observation sequence. Trusted corroboration arriving later cannot make
old intent newly eligible. Timestamp-skew validation separately uses the first
accepted receipt time.

Rebuildable derived tables carry a `generation_id` so a full rebuild can be
constructed without exposing partial state:

- `audit_index`: compact, payload-free event/subject occurrence identity,
  exact URI+CID references, observer/source times, trust/validation outcomes,
  hashes, and reason codes sufficient for the V0 audit API. It retains an
  entry for archived detail so web requests never open Parquet or DuckDB.
- `records_current`: latest observed record version/deletion by AT URI.
- `community_profiles`: latest authenticity-accepted current `profile/self`
  decoration.
- `ledger_records`: normalized profile/submit/admission/removal fields and
  validation outcome for each immutable record version.
- `subject_current`: latest resolution outcome by exact subject reference.
- `admission_lifecycles`: one row per admission URI+CID, including its exact
  submit/subject, a logical lifecycle key derived from the exact submission,
  admission-triggered start observation/sequence, first later terminal
  mismatch/deletion observation, removal, and lifecycle status.
  All duplicate admissions referencing one submission share its terminal
  lifecycle; a later exact result or another admission of that same submission
  cannot revive it. A different submission may seed a post-terminal lifecycle
  only when both its and an admitting record's first-observed receipt sequences
  are greater than the latest terminal observation sequence for that
  exact subject; preexisting equivalent intent or authority cannot be held in
  reserve.
- `community_entries`: one aggregate rendered row per community and subject
  URI+CID, choosing the earliest eligible admission lifecycle or canonical
  removal while retaining all lifecycle rows.
- `projection_findings`: current unresolved, unauthorized, malformed, stale,
  and conflict findings.

Operational control tables do **not** carry `generation_id` and are not claimed
to be replay-equivalent:

- `meta`: schema/projection/code versions, active generation, and ingest,
  resolve, projection, and report heartbeats.
- `projection_builds`: generation ID, reducer/schema version,
  `building | complete | failed`, start/completion time, per-source high-water,
  immutable/derived row counts, and failure reason.
- `ingest_sources`: durable cursor and last success/error for each source.
- `archive_generations`: immutable generation/manifest identity, explicit
  `staged | sealed | accepted | superseded | quarantined` lifecycle, partition
  and schema versions, row counts and byte hashes, min/max received time and
  observer sequence, per-source high-water, exclusions/quarantine, last-good
  pointer state, and any verified-prune coordinate.

Generation-scoped semantic rows can be deleted and reproduced content-
equivalently from manifest-listed accepted history plus the sequence-disjoint
SQLite occurrence tail. Payload variants present on both sides are
stable-key-deduplicated; equivalence excludes local generation IDs and
operational timestamps/errors. Each ingest batch stores event variants and
delivery receipts in the tail, updates the compact audit index and
current/lifecycle state, applies projection, and advances that source cursor in
one transaction. A failed transaction advances nothing. Stream reception uses
bounded backpressure; it never drops a ledger event or checkpoints a merely
received delivery.

Network resolution never occurs inside a SQLite write transaction. Ingest may
commit a dependency/lifecycle as `pending`; the resolver performs I/O without a
write lock, then transactionally inserts its immutable observation/sequence,
and variant when new, updates the compact audit index, lifecycle/current
projection, and heartbeat. A crash before that transaction simply repeats the
check, and no admission renders meanwhile.

`meta.active_projection_generation` names the only generation the web reads.
Normal incremental batches update that generation and its high-water in their
atomic transaction. A full active-projection rebuild streams only the accepted
last-good manifest history and then the SQLite tail into a new generation while
the live index writer is paused. A sealed-but-unaccepted archive generation may
be read only by its pre-acceptance parity/rebuild check. The active rebuild then
marks its SQLite generation complete and swaps the active pointer in one
transaction; rollback leaves the prior complete generation active. A
post-rollback diagnostic may mark the attempted build failed, but non-active
building/failed rows do not poison the last complete projection. Web refuses
only when there is no compatible complete active generation or its high-water
does not match committed ingest.

Reference validity is set-based rather than arrival-based: unresolved
cross-repository dependencies are re-evaluated when present. Subject
availability is explicitly observation-relative: lifecycle start and later
changes use persisted `observer_sequence`, never reducer insertion order.
Replaying the same stored events, receipts, and observations gives the same
result, while two observers may honestly record different histories. Within
the community repo, commit order resolves record-current state. V0 has no
restore action, so a valid removal dominates every admission for its exact subject.
For all remaining state, the deterministic precedence is:

1. malformed, unverified, or unauthorized records have no projection effect;
2. no valid admission means `submitted` or `pending` and hidden;
3. any valid removal means `removed` and hidden;
4. an immutable-operation payload collision means `conflict` and hidden;
5. missing subject means `subject_deleted` and hidden;
6. a current or previously observed post-admission CID mismatch means
   `stale_cid` and hidden;
7. resolver error means `subject_unavailable` and hidden; and
8. otherwise semantically duplicate admissions collapse to one `visible` entry.

## Configuration separation

`communitywatch.toml` requires community DID/slug, observer SQLite path,
public event-source URL, and public resolver configuration. Defaults are
subject refresh 60 seconds, bind `127.0.0.1`, port `8080`, page size 50/max 100,
and stale threshold 180 seconds. It may configure publication/cache paths and
bounded read timeouts. Its strict parser rejects unknown keys. It has no token,
password, session, private-key, credential, signing, or PDS-write field.

`communityd.toml` contains community DID, one administrator DID, community
PDS/service URL, required local `allowed_uid`, reader/writer adapter selection,
credential-provider name, external credential reference, and bounded
timeout/retry settings. No live adapter has a URL or credential default. The
secret value is never stored in TOML. Example configuration selects fake
adapters and uses placeholder DIDs.

The observer archive tool receives an observer SQLite path, artifact root,
closed high-water, batch/file limits, and process resource bounds through its
own strict maintenance configuration or CLI arguments. It accepts no network,
credential, signing, authority-writer, or community-repository target field.

The packages do not share a configuration class or inherit an environment
wholesale. Logs redact secret-bearing values.

## V0-M2A sealed-history seam

The storage doctrine is:

> Community-repository records carry authority. SQLite holds transactional
> observer state, the current projection, compact audit index, and unexported
> immutable tail. Sealed Parquet generations hold exported observer history.
> DuckDB asks bounded questions of that sealed history. Artifact receipts prove
> custody operations, never community authority.

The V0-D2 amendment records the observed history-size and WAL-contention
forcing case and authorizes V0-M2A. M2 preserves stable semantic event identity,
source high-water, distinct source/received/signed times, payload hash,
authenticity, schema versions, compact audit rows, and archive-control state so
M2A never depends on SQLite rowids or rewrites schema v1. Exports preserve
`observer_sequence` only as this observer's causal coordinate; it is never
merged or compared as portable identity across observers.

V0-M2A proceeds in this order:

1. add the separately installed observer archive tool and prototype offline
   export from fixtures or a copied test database;
2. close an observer-sequence prefix with explicit per-source high-waters, then
   write immutable delivery receipts, quarantined deliveries, and subject
   observations partitioned principally by trusted observer `received_at`,
   with bulky event and subject variants referenced by stable keys. A variant
   referenced on both sides of the cut is included in the generation and
   retained in SQLite for the tail. A late arrival has a later observer
   sequence and enters a later generation even when its source or signed time
   falls in an older date;
3. stage artifacts and a manifest in one uniquely named generation on the
   target filesystem; validate schema, counts, byte hashes, min/max received
   time and observer sequence, per-source high-waters, exclusions, quarantine,
   supersession, and `cannot_testify` limitations; `fsync` files/directories,
   rename the generation into the sealed inventory, and `fsync` its parent.
   Sealing does not change the accepted last-good pointer. Verify the target
   filesystem's rename/crash semantics, reject cross-filesystem publication,
   and recover abandoned or sealed-but-unaccepted generations;
4. add a read-only DuckDB CLI that opens no hot SQLite handle, restricts work to
   manifest-listed partitions and bounded horizons, streams results rather
   than materializing unbounded identity maps, and is tested under an external
   process memory ceiling; and
5. prove query and rebuild parity between the pre-export SQLite source and the
   sealed occurrence prefix plus sequence-disjoint SQLite occurrence tail,
   stable-key-deduplicating intentionally overlapping payload variants. Only
   then write and `fsync` an immutable acceptance receipt and atomically switch
   the last-good pointer to the generation plus receipt digest. Reconcile the
   SQLite archive-control row idempotently; pruning remains forbidden until the
   pointer, receipt, and SQLite state agree. A later explicit offline retention
   transaction may prune exact covered receipt, quarantine, and
   subject-observation rows and record its coordinate atomically; it prunes an
   event/subject variant only when no retained tail row references it. Any
   failed check or crash preserves or idempotently recovers the source detail.

Never dual-write Parquet in ingest, stream tiny files continuously, put DuckDB
in web requests, infer completeness from file presence, or let `communityd`
read observer SQLite/artifacts/manifests. The web process continues to serve the
committed SQLite projection and compact audit index. Continuous archive
operation, cold public serving, object-store/distributed publication, and a
networked analytical database remain out of scope.

## Commit-sized implementation milestones

The stable V0 sequence is `V0-M1`, `V0-D2`, `V0-M2`, `V0-M2A`, then `V0-M3`
through `V0-M8`. This list defines product scope; `GOVERNED-LOOP.md` defines
selection, prerequisites, cumulative done commands, evidence, and stop
behavior. No milestone is complete merely because a later milestone is
described as "remaining" elsewhere.

The storage-refrozen offline vertical phase is five bounded milestones, one
documentary. The acceptance test lands in V0-M3 and gates the phase as a whole:

1. **V0-M1 — Contracts and fixtures:** scaffold three distributions; add
   deep-immutable shared values, strict provisional record validation,
   profile/post/ledger fixtures, port contracts, canonical hashing, and
   package-boundary tests.
2. **V0-D2 — Storage refreeze:** authorize the bounded hot-SQLite,
   cold-Parquet, read-only-DuckDB custody split and its isolation/retention
   contract. This documentary milestone starts no implementation.
3. **V0-M2 — Observer state core:** add SQLite v1 event variants/receipts,
   deduplicated subject variants and compact observation receipts, audit index,
   generation/archive-control tables, pure reducer/lifecycles, fake event
   source/resolver, and hot-tail replay/rebuild tests.
4. **V0-M2A — Sealed observer history:** add separately installed observer
   archive tooling, sealed Parquet generations/manifests, a bounded read-only
   DuckDB CLI, verified prefix retention, and hot+cold query/rebuild parity.
5. **V0-M3 — Offline vertical acceptance:** add fake authority
   reader/writer/authorizer, daemon operations, minimal escaped renderer/query
   layer, profile fallback, and the single end-to-end acceptance test in
   `TEST-PLAN.md`.
6. **V0-M4 — State and replay hardening:** cover every malformed, missing,
   unauthorized, trust-mode, out-of-order, deleted, duplicate, conflict,
   mutation, crash, and queue-pressure case, including OQ-5's selected-answer
   submission-mutation fixture.
7. **V0-M5 — Canonical AppView:** add the read-only web subprocess, exact JSON
   contracts/pagination, audit view, headers/escaping, freshness/health, and
   concurrent WAL tests.
8. **V0-M6 — Observer ingestion:** after OQ-2, implement filtered authenticated
   stream ingestion, durable rewind/dedupe, exact subject refresh, provenance,
   and isolated stage heartbeats.
9. **V0-M7 — Authority writer:** after OQ-1/OQ-3/OQ-4, implement the real
   adapter, daemon-owned ledger reader, local CLI, immutable idempotent writes,
   credential isolation, and adapter contract tests.
10. **V0-M8 — Human V0 trial:** use only a non-production actor, evaluate
   whether the page feels like a bounded place, and record the result.
   Feed-generator compatibility remains later.

The offline phase's single vertical acceptance test proves: submission is
hidden; admission makes the exact post visible; CID mismatch hides it; removal
keeps it hidden; audit retains every event; and neither observer nor emitter
ever mutates/deletes the user post.
