# V0 test plan

## Test discipline

The complete suite runs offline with fixtures, fake adapters, temporary
directories, and no credentials. Tests may not contact ATProto services or
modify `../labelwatch` or other sibling repositories. Every milestone runs its
available package and root invariant tests. V0-M3 introduces the vertical
acceptance test; it and every subsequent milestone must run it.

For governed execution, the V0 order is `V0-M1`, `V0-D2`, `V0-M2`, `V0-M2A`,
then `V0-M3` through `V0-M8`, and gates are cumulative. The `V0-G0` bootstrap
in `GOVERNED-LOOP.md` assigns stable
requirement IDs to the assertions below, maps them to milestone gates, and
creates `./scripts/v0-gate TASK_ID`. Until that protected mapping and gate pass
an OQ-7 A/B decision and bootstrap-output acceptance, this prose is an
acceptance design, not a machine-selectable work queue. The documentation-only
V0-D1 task then freezes M1's observable contracts and golden vectors before
product implementation begins.

## Governance bootstrap tests

V0-G0 must cover every governance artifact used by the controller before any
later task may depend on it:

- Accept canonical valid fixtures and reject missing, duplicate, unknown,
  placeholder, and conditionally forbidden packet/receipt/change-set fields.
- Reject empty answer sets, duplicate answer IDs, a recommendation or selection
  outside the admissible set, an agent-prepared packet containing a ruling, and
  a free-text, partial, hybrid, or multi-answer receipt.
- Reject `select` without one answer/change set, `defer` without a revisit
  trigger/deadline, `reject_packet` without a reason/replacement state, and
  `repack_required` without novel-evidence references.
- Reject packet, evidence, governing-input, authentication, and required-result
  digest substitution; reject conflicting active receipts without an explicit
  supersession chain.
- Prove authentication evidence attests the canonical decision-payload digest,
  the pinned operator-trust policy controls accepted identities/methods, and no
  authentication object hashes bytes containing its own digest.
- Require distinct common-policy attestations for the OQ ruling, bootstrap
  launch, and bootstrap-output acceptance; prove that no decision receipt can
  authenticate either later artifact by implication.
- Prove `manual-controller-channel-v1` remains the concrete governed-V0 trust
  root after bootstrap acceptance, every later entry pins it, and neither an
  entry packet nor mutable configuration can replace it without a selected and
  applied transition packet.
- Prove `defer`, `reject_packet`, `repack_required`, missing evidence, and an
  unapplied required amendment remain `BLOCKED_HUMAN`; malformed artifacts or
  mismatched digests are `CONTRACT_INVALID`.
- Prove a selected receipt satisfies only its declared blocker and never the
  complete task/slice authorization intersection by itself.
- Golden-test the human-readable renderer so it neither adds nor drops an
  answer, recommendation, counterevidence, uncertainty, or consequence.
- Prove the bootstrap digest graph is acyclic: the positive `BUILD.md` block
  pins the contract, the controller-entry packet pins that exact `BUILD.md`, and
  no antecedent embeds a descendant digest.
- Golden-test the frozen pre-bootstrap verifier: it treats the exact Markdown
  packet as opaque bytes, accepts only the common bootstrap trust policy and a
  selected A/B receipt for V0-G0, parses only the frozen change-set and receipt
  grammars plus the frozen entry/acceptance grammars, runs outside the candidate
  checkout, and never lets G0-generated validators approve themselves.
- Reject malformed bootstrap scalar types, evidence-reference shapes,
  non-canonical JSON, receipt/change-set ID disagreement, and an entry or
  acceptance payload authenticated by the OQ decision's attestation.
- Prove the bootstrap entry pins the external frozen-verifier bytes, the exact
  governance input set, every base path as protected, and the three add-only G0
  path patterns. Reject broader paths, modified base files, links, special
  files, traversal, or a verifier-digest substitution.
- Prove bootstrap acceptance covers the evidence manifest and every G0 output,
  includes every mandatory output role, and rejects subsets, extra or
  unclassified files, duplicate paths, or generated-validator self-approval.
- Apply each OQ-7 change set to its exact base in a disposable tree and verify
  every declared result: A/B add the identical contract-pinned V0-G0 block and
  their distinct register decisions; C changes only the register. Reject path,
  ordering, base, result, receipt-ID, and patch-byte substitutions.
- Validate an equivalent post-bootstrap JSON golden under the generated schemas
  without treating that representation as retroactive OQ-7 authorization.
- Prove controller-entry, slice-ratification, and human-acceptance receipts pin
  the required schemas, validator/renderer programs, trust policy, results, and
  purpose-specific evidence.
- Prove a `contract_freeze` human-acceptance receipt covers D1 execution
  evidence and every reviewed contract/fixture digest, accepts only the fixed
  verdicts, and is required before V0-M1.
- Prove a slice governance result records only a predeclared receipt ID, the
  later slice-ratification receipt pins that result tree, and the still-later
  controller entry pins the receipt digest without a cycle.
- Prove a current run's evidence never references its future human-acceptance
  receipt and that procedural OQ outcomes cannot supersede an applied selection
  without a new transition packet, change set, receipt, and governance result.
- Prove external evidence write/readback verifies every retained byte and that
  unavailable or altered storage can never return `PASS`.

## Schema and model tests

- Validate DID, DID-authority AT URI, CID, datetime, community identity, exact
  strong references, allowed collections, and record round trips.
- Reject URI-only subjects, handle-authority subjects, non-post subjects,
  malformed records, community mismatch, and unsupported actions.
- Prove self-submission requires envelope repo DID equal to subject repo DID;
  no payload field can override it.
- Validate the four provisional Lexicons and examples against the local
  Lexicon validator/model implementation.
- Prove canonical serialization and payload hashes are stable across process
  runs, mapping order, and supported Python versions. Cover `dag_cbor`,
  `observer_json_v0`, and `delete_envelope_v0`; never equate observer JSON hash
  with record CID.
- Keep source event time, observer `received_at`, and signed `createdAt`
  distinct. Require offset-bearing RFC 3339, normalize UTC, accept the
  five-minute skew boundary, and reject later values with `created_at_future`
  for profile/submit/admission while still storing/checkpointing the event.
  Prove an otherwise valid future-dated removal still masks and gets the
  finding. Signed time never sets source high-water or a custody partition.

## State-machine and invariant tests

- Exercise every state and precedence rule in `V0-STATE-MACHINE.md`.
- Cover admission before submission, removal before admission, dependency
  arrival after pending, wrong community, wrong repo, unverified envelope,
  unauthorized actor, mismatched admission/submit subjects, and removal of an
  unknown admission.
- Reject an external admission whose referenced submission was already
  superseded/deleted before first validation; keep admission-before-current-
  submission pending until exact resolution.
- Accept an exact current submission update as a new intent version before
  admission; admission must reference that exact version.
- Prove valid submission alone never renders and valid admission renders only
  the exact current CID.
- Prove a CID mismatch or confirmed deletion makes the affected admission
  lifecycle terminal; an exact resolver result after a transient error may
  recover without new authority.
- Prove unverified/failed mismatch or missing evidence cannot terminalize and
  maps to `subject_unavailable`; accepted resolver testimony may terminalize.
- Find mismatch/deletion before an externally emitted admission and prove it
  projects directly stale/deleted without flashing visible. A later transport
  error cannot demote terminal stale/deleted state to `subject_unavailable`.
- Prove a new submission/admission for the new current CID creates a distinct
  visible lifecycle while the old stale/deleted lifecycle stays in audit.
- Admit CID A, observe CID B, revert to A, and prove the old lifecycle remains
  stale; a duplicate admission of the old submission cannot revive it. A new A
  submission/admission may create a visible lifecycle while the first remains
  terminal.
- Create equivalent submissions S1/S2 before mismatch, admit S1, terminalize,
  then admit S2 after revert; S2 remains ineligible because its first observed
  observer sequence predates terminal state. Only trust-accepted records whose
  first-observed sequences are later may seed the fresh lifecycle; a pending
  pre-terminal admission cannot be held for restoration either.
- Observe submission/admission unverified before terminal state, then receive
  trusted corroboration afterward. They may become authentic but retain their
  first-observed sequences and cannot revive the exact subject.
- Prove a valid removal masks every duplicate admission for the exact subject
  and never masks a later different CID.
- Collapse semantic duplicate submissions/admissions to one card without
  losing their audit records; use the earliest `(createdAt, admission URI)` so
  duplicates cannot bump chronology.
- Reject an occupied deterministic authority rkey with differing content.
- Treat authority record update/delete as specified: admission fails closed;
  removal cannot be erased into restoration; profile updates remain valid.
- Refuse exact-subject readmission after removal; if externally observed, keep
  projected status `removed` and emit `unsupported_readmission` separately.
- After OQ-5 is decided, lock its submission-update/delete behavior in a named
  reducer fixture before the state-hardening milestone can pass.
- Shuffle cross-repository dependency arrival and require equivalent reference
  validity. Replay one persisted observation sequence twice and require
  equivalent lifecycle/current state, findings, pagination, and audit; do not
  claim two observers saw the same subject history.

## SQLite, ingestion, and rebuild tests

- Verify fresh schema, each forward migration, newer-schema rejection,
  indexes/constraints, foreign keys, WAL, bounded busy timeout, and
  read-only/query-only connections.
- Prove immutable raw event variants, delivery receipts, and subject
  observations cannot be updated or deleted through application repositories.
- Prove semantic event identity is independent of SQLite rowid, insertion
  order, source delivery replay, and arrival time.
- Require canonical `rev:<repo-revision>` across adapters and ATProto TID
  ordering. Missing/invalid revision goes to immutable quarantine and advances
  its source cursor atomically without authority effect.
- Feed raw incoming deliveries with no derived IDs/sequences; assert only the
  index writer validates/derives event keys, allocates sequence, and atomically
  chooses event+receipt versus quarantine+cursor.
- Re-deliver an identical event and get idempotence; deliver the same semantic
  key with a different payload and get a conflict finding, not silent ignore.
- Render one audit row per `event_variant_key` with semantic key, hash scope,
  CID, receipts, outcome, and `semantic_event_conflict`; never pick one
  conflicting payload as canonical.
- Render quarantined delivery rows with stable hash-based audit keys, null
  semantic/variant identities, raw-envelope hash scope, and rejection reason;
  pagination never uses SQLite rowid.
- Prove an unverified/failed conflicting variant cannot suppress an accepted
  variant; two incompatible trust-accepted variants fail projection closed.
- Deliver one semantic event from two sources and retain both receipt cursors,
  receipt times, trust modes, methods/versions, and evidence hashes while
  projecting it once; a later receipt cannot bump audit ordering.
- Exercise locally verified, relay-attested, unverified, and failed receipts;
  only the configured OQ-2 trust policy affects eligibility.
- Preserve method/version/evidence provenance on exact, mismatch, missing, and
  errored subject resolution observations, including verify-repo/trust-PDS/test
  mode and verified/attested/unverified/failed outcome without relabeling.
- Allocate one global observer sequence transactionally across deliveries,
  quarantines, and subject observations. Make the admission-triggered check the
  lifecycle start; apply terminal/fresh-intent eligibility by sequence with
  stable keys, never reducer insertion order.
- Atomically commit event variant, delivery receipt, current-record/lifecycle
  update, projection-build admissibility, and that source cursor. Inject
  failure before commit, restart, replay, and prove nothing was skipped or
  double-applied.
- Prove resolver network I/O holds no SQLite write transaction. Crash between
  I/O and observation commit, repeat the check, and prove the admission stayed
  pending and never flashed visible.
- Fill the worker queue and hold SQLite busy: ingestion applies backpressure or
  reconnects and does not drop/checkpoint an unprocessed event.
- At M2, delete only generation-scoped semantic tables and rebuild them from
  the SQLite immutable tail. At M2A, repeat after a sealed export and verified
  prefix prune, rebuilding from manifest-listed Parquet history plus the
  sequence-disjoint SQLite occurrence tail while stable-key-deduplicating
  payload variants that intentionally occur in both. Normalized/lifecycle/
  current/audit rows, findings, counts, pagination, and semantic hashes are
  content-equivalent; generation IDs, heartbeats, build times, source errors,
  and cursors are explicitly excluded.
- Mark non-active projection generations `building` and `failed`; web continues
  using the prior complete active generation. It refuses no-active,
  incompatible, or high-water-mismatched active generations.
- Exercise simultaneous index writes and read-only web queries without partial
  generations or long-reader WAL starvation.

## `communitywatch` API and rendering tests

- Ignore irrelevant collections while retaining malformed relevant records
  and validation reasons in audit.
- Subscribe to the four configured community collections only; assert the
  indexer never requests the global `app.bsky.feed.post` stream and resolves
  only subjects reached through submissions/admissions.
- Project authority only from the configured community repo and outcomes
  accepted by the selected trust policy; never relabel relay attestation as
  local verification.
- Keep unauthorized/unverified admissions and actions audit-visible without
  affecting current state.
- Apply the latest authenticity-accepted current `profile/self` by
  community-repo order;
  test update, delete, malformed, unverified, and missing profile. Every bad or
  absent case falls back to configured slug + community DID/null description
  without changing admission state.
- Return only `visible` entries in reverse admission chronology with stable,
  opaque pagination and bounded limits.
- Return 404 for an unknown community and 405 for POST/PUT/PATCH/DELETE.
- Escape post/profile/reason text and hostile URIs; prevent script injection,
  header injection, and path traversal.
- Open SQLite read-only, perform no migration or network resolution, and expose
  schema/projection/freshness health accurately.
- Verify current page/posts return 503 for unavailable/high-water mismatch,
  health returns the exact 200/503 shape, and audit serves the last compatible
  complete generation with `fresh:false` but refuses if none exists.
- Contract-test every audit outcome/reason code and CLI/API error code; reject
  unknown reason codes in V0 fixture output.
- Show stale/degraded banners without leaking internal paths, raw exceptions,
  configuration, or credentials.
- Assert no public API cursor or audit identity contains a SQLite rowid.
- Assert observer sequence is exposed, if at all, only as explicitly local
  custody order and never as portable event identity.

## `communityd` tests

- Reject an unauthorized principal before any reader, credential, or writer
  call, including effective UID mismatch; the actor DID cannot be supplied on
  the command line.
- For admission, require current exact submission and subject, self-submission,
  matching community, and configured community actor.
- Assert admission payload contains exact submission and subject strong refs
  plus configured actor attribution.
- Derive admission rkeys from exact submission and removal rkeys from exact
  admission. The daemon-owned ledger reader paginates community records by
  exact subject and makes admission exit 5 after any valid removal, without
  observer access; a new submission before removal may create a new lifecycle.
- For removal, require the exact admission and matching embedded subject, but
  permit removal when the underlying post is now stale or missing.
- Assert repeated semantic operations return the identical record reference;
  incompatible authority-defining fields at the same rkey fail without
  overwrite, while the stored timestamp/reason remain unchanged on retry.
- Assert read, validation, authorization, credential, and writer failures never
  report success.
- Contract-test exits 0/2/3/4/5/6/7/8, success JSON on stdout only, error JSON
  on stderr only, and redaction of secrets/raw exceptions.
- Assert the writer interface exposes immutable community-record creation only
  and is never invoked for a user repository.
- Assert logs redact credential values and `communityd` cannot import or open
  observer SQLite, Parquet, manifests, or projection cursors.

## Package and process-boundary tests

- Build/install each wheel in a clean environment and inspect metadata:
  - `communitywatch` has no credential, signing, authority-record writer, or
    general ATProto write-client dependency; local observer SQLite writes and
    bidirectional WebSocket transport remain permitted;
  - `communityd` is absent from its dependency graph;
  - a general ATProto writer SDK, DuckDB, and PyArrow are absent from the base
    watcher dependency closure, and the index/web import graphs do not reach
    archive modules or entry points;
  - the separately installed observer archive tool may add DuckDB/PyArrow but
    has no network transport, credential, signing, authority writer, web, or
    `communityd` dependency/import; and
  - DuckDB/PyArrow are absent from `community_model` and `communityd` always.
- Static imports reject `communityd`, writer, credential, signing, and
  authority-client modules anywhere under `communitywatch`.
- Strict config parsers reject writer/credential keys in watcher configuration
  and observer/database/artifact keys in daemon configuration.
- Launch index, web, and daemon as separate subprocesses with isolated temp
  roots and allow-listed environments; only daemon receives a fake credential
  reference.
- Verify web cannot mutate SQLite and watcher cannot invoke the fake authority
  writer even when daemon-related environment variables are present.

## Offline vertical-phase acceptance test

Use fake transports and one temporary observer SQLite database:

1. Seed an ordinary author-owned post at CID A and an exact self-submission.
2. Ingest and project. Audit contains the submission; page/API contains no post.
3. Run `communityd` admission through its fake writer, ingest the emitted
   verified repo event, and verify the post appears exactly once at URI+CID A.
4. Change the fake repository's current post to CID B and append the resolver
   observation. Verify the entry becomes `stale_cid` and disappears.
5. Run `communityd` removal against the exact admission, ingest it, and verify
   current state becomes `removed` and remains absent.
6. Verify the compact audit index retains submission, admission, mismatch
   evidence, and removal, including exact references, hashes, and
   validation/authority outcomes.
7. Verify the fake call log contains no system update/delete of the user post,
   no watcher authority-writer invocation, and no daemon access to observer
   storage.

The test passes only if rebuilding from the currently available immutable
custody (SQLite tail alone or sealed history plus tail) produces the same final
audit and current projection.

## V0-M2A sealed-history tests

These become cumulative requirements at V0-M2A:

- install archive tooling in a separate clean environment and prove the base
  index/web and `communityd` environments neither acquire nor import it;
- close an observer-sequence prefix and per-source high-waters without holding
  an ingest read snapshot; export its delivery receipts, quarantined
  deliveries, and subject observations while a later/late-arriving occurrence
  remains in the SQLite tail and enters a later generation;
- partition principally by trusted observer `received_at`, never actor-supplied
  or source time, and reference deduplicated event/subject payload variants from
  compact receipts;
- place receipts/observations for one event variant and one subject variant on
  both sides of the cut; retain the variants while the tail references them,
  then stable-key-deduplicate their intentional hot/cold overlap during query
  and rebuild;
- staged export, rename, or durability failure leaves the prior sealed
  generation and SQLite source detail untouched, and recovery
  quarantines/cleans an unsealed stage;
- failure after sealed generation publication but before last-good pointer
  acceptance is discovered with the prior pointer unchanged and recovered
  without silently changing consumers;
- target deployment filesystem rename/crash behavior is tested, not assumed;
- artifact schema/bytes, row count, min/max observer time and sequence,
  per-source high-waters, and manifest agree before sealing; hot/cold query and
  rebuild parity pass before accepting the generation and switching the
  last-good pointer;
- failure while writing the acceptance receipt, switching the last-good
  pointer, or reconciling SQLite archive-control state either leaves the prior
  pointer accepted or recovers the new receipt/pointer idempotently; it never
  permits pruning while the three disagree;
- partial/missing partitions, late arrivals, quarantine, supersession, and
  schema-version rejection are explicit rather than inferred from file
  presence;
- retention refuses before seal, parity, rebuild, acceptance receipt,
  last-good pointer switch, and SQLite-control reconciliation;
  an injected prune failure rolls back both exact-prefix deletion and its
  recorded prune coordinate, while retry is idempotent;
- pruning deletes only covered occurrence rows; it retains a payload variant
  while any tail row references it and garbage-collects it only after the final
  reference is covered;
- rebuilding from accepted history plus the sequence-disjoint occurrence tail
  byte-compares semantically with the pre-prune audit/projection, rejects
  occurrence gaps/overlap, and permits only stable-key variant overlap;
- DuckDB and pre-export SQLite queries have fixture parity over duplicate,
  conflicting, quarantined, late, and high-cardinality/non-deduplicating data;
- cold queries open no hot SQLite handle, stream bounded partition/horizon
  results under an external process memory ceiling, and do not build an
  unbounded in-memory identity map; and
- artifact receipts confer no admission/moderation authority, `communityd`
  cannot open the database/artifacts/manifests, and web requests remain
  SQLite-only after pruning.
