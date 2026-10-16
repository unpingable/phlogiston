# Labelwatch donor reuse matrix

## Inspection and copying rule

The donor is `../labelwatch`, inspected read-only at commit
`7f04bdd44aea5aaf97c03ff5f98144ba5ec0761b`. Source code is the authority for
this matrix: `ARCHITECTURE.md` still describes schema v19 while `db.py` is v23,
and some cursor documentation no longer matches storage in `meta`.

Do not install or import Labelwatch as a dependency. Reuse means copying a
small reviewed implementation or reapplying a pattern into the appropriate
new package. Every copied fragment must add its source path/symbol, donor
commit, modification summary, chosen license, and observer-boundary review to
this document before merge.

## Matrix

| Donor module and symbols | Classification | V0 decision and boundary analysis |
|---|---|---|
| `src/labelwatch/utils.py`: `stable_json`, `hash_sha256`, `now_utc`, `format_ts` | **Reuse nearly unchanged** | Pure, dependency-free candidates for `community_model`. `stable_json` is deterministic Python JSON for constrained local receipts, not cross-language canonical JSON or DAG-CBOR; `format_ts` must reject/normalize naive datetimes instead of inheriting host timezone. Hashes are local receipts, never ATProto CIDs/signatures. Adapt or omit `get_git_commit`, which contains Labelwatch environment/layout assumptions. |
| `src/labelwatch/config.py`: `Config`, `load_config` | **Reuse after adaptation** | Keep the small dataclass/TOML idea, not its fields/defaults. Build strict and disjoint watcher/daemon parsers. The donor silently ignores unknown keys and performs little type validation, which is unsafe for credentialed configuration. |
| `src/labelwatch/db.py`: `connect`, `init_db`, `_ensure_columns`, `get_meta`, `set_meta`, `get_schema_version`, `migrate` | **Reuse after adaptation** | WAL, busy timeout, `sqlite3.Row`, schema guards, forward migrations, and `query_only=ON` are useful patterns. Write a new schema/migrations. Avoid helper-owned commits such as cursor setters; ledger event, projection, and checkpoint must share one caller-owned transaction. |
| `db.py`: append-only tables, `insert_discovery_event`, `insert_label_events` | **Reuse after adaptation** | Preserve immutable observations plus rebuildable derived state. Do not rely on `INSERT OR IGNORE`: it can hide payload conflicts, and nullable SQLite unique columns dedupe poorly. Compare repeated semantic keys and surface differing payloads. |
| `src/labelwatch/state.py`: `init_sidecar`, `meta_get`, `meta_set`, `is_admissible`, `_apply_chunk`, `pilot_backfill` | **Reuse after substantial adaptation** | The pilot's immutable-source/derived-state split, build-status gate, resumable cursor idea, and refusal to render incomplete state fit. It is explicitly pilot-only and lacks dedicated tests. The donor can commit derived changes before its cursor commit and double-apply after a crash, so V0 needs one atomic transaction or deterministic full rebuild. |
| `src/labelwatch/discovery_stream.py`: `_build_ws_url`, `_stream_loop`, `_worker`, `run` | **Reuse after substantial adaptation** | Keep collection filtering, a single SQLite writer, reconnect loop, fatal-error signaling, signal handling, and identity-event awareness. Replace all labeler assumptions and the fixed five-second reconnect with bounded exponential backoff/jitter. Do **not** copy its loss semantics: it can save the newest received cursor before worker durability; drop on `QueueFull`, exhausted busy retries, or arbitrary handler exceptions; and cancel without draining at shutdown. V0 applies backpressure, drains/stops safely, and checkpoints only durable processing. |
| `src/labelwatch/ingest.py`: `LabelEvent`, `normalize_label`, polling functions | **Do not reuse** | `queryLabels` semantics permit absent CIDs and do not provide the authenticated repository envelope required here. Retain only the general test invariant that checkpoint advancement follows committed inserts. |
| `src/labelwatch/runner.py`: `_heartbeat`, `_report_loop`, `run_loop` | **Reuse after adaptation** | Meta-backed stage heartbeats and failure isolation are useful. `communityd` must never enter this runner/package. Canonical ingest failures must produce externally visible degraded/stale health. Omit Linux memory trimming and report threads for V0. |
| `src/labelwatch/server.py`: `_TokenBucket`, `_DiskCache`, `_validate_did`, `configure_handler`, `run_server` | **Reuse after adaptation** | Cache replacement, kill switch, concurrency gate, and read-only DB connections are references. `_validate_did` is only a prefix/length/control-character screen, the server supplies only `nosniff`, and some requests resolve handles live; V0 needs strict DID parsing, a complete header policy, and no request-time network. The limiter is global despite per-IP docs, and timed-out threads can outlive a released semaphore. |
| `src/labelwatch/report.py`: `_write_json`, `_prepare_out_dir`, `_commit_out_dir`, `generate_report` | **Do not reuse wholesale** | The report is large, branded, schema-specific, and accepts pre-rendered HTML, making escaping caller-dependent. `_write_json` writes final files directly; the two directory renames briefly remove output. Build the renderer fresh. Small publication helpers may be adapted only with cleanup and crash/visibility tests. |
| `src/labelwatch/receipts.py`: `config_hash`, `receipt_hash` | **Reuse after adaptation** | Deterministic-Python-JSON SHA-256 observer receipts are useful within a versioned scope. The new model includes semantic event identity, payload hash/scope, source delivery, trust method/evidence, projection version, and validation result. Receipts remain explicitly distinct from signed authority. |
| `src/labelwatch/rules.py`: `run_rules` and rule functions | **Do not reuse domain logic** | Label volume/spike/churn rules have no community meaning and are DB-coupled rather than pure. Reuse only the idea of explicit evidence/reason outputs; implement new pure reducer checks for missing references, exact-CID mismatch, unauthorized/mutated action, duplicates, and conflicts. |
| `src/labelwatch/derive.py`: frozen signal/result types and pure classifiers | **Reuse after adaptation** | Pure-input/pure-output reducer organization is useful. Its frozen dataclasses still contain mutable `reason_codes` lists, so new deeply immutable values use tuples. Discard all regime/risk scoring and moral vocabulary; implement only the explicit community state machine. |
| `src/labelwatch/provenance.py`: `BskyClient`, score models, derivations | **Do not reuse** | Fixed public endpoints, Labelwatch user-agent, identity scoring, and governance semantics inherit the wrong identity. Build a new narrow read-only subject/repository resolver. |
| `src/labelwatch/publication.py` and posted-finding helpers | **Do not reuse** | “Publication readiness” is Labelwatch policy, not community admission. It imports writer-facing posting types and collapses the observer/emitter boundary. `assess_all_fights` also imports `is_finding_posted` while `db.py` defines `has_been_posted`, so it is not reliable generic plumbing. |
| `src/labelwatch/posting.py`: `BlueskyConfig`, `BlueskyPublisher`; `cli.py`: `cmd_post` | **Do not reuse** | These load app passwords, log in, post, and upload blobs under Labelwatch identity. They are the concrete reason Labelwatch cannot be imported as an observer dependency. `communityd` needs a new immutable authority-record writer, not a renamed social publisher. |
| `pyproject.toml` | **Do not reuse wholesale** | It installs a writer-capable `atproto` SDK for the entire package. `communitywatch` must omit general write clients; `websockets` may be observer-only. Separate distributions and clean-wheel tests enforce this. |
| `deploy/*.service` | **Reuse after adaptation** | Unit hardening, resource limits, `NoNewPrivileges`, `ProtectSystem`, and narrow writable paths are useful references. The donor's units all run as the same `labelwatch` principal; V0 must instead give watcher and daemon different principals, configs, environments, dependencies, and writable roots. Copy no Labelwatch names or environment variables. |
| `tests/test_discovery_stream.py`, `test_cursor_persistence.py`, `test_db_schema.py`, `test_multi_ingest.py` | **Reuse after adaptation** | Translate cold-start, migration, restart, rewind, replay, contention, and per-source isolation scenarios. Reverse donor expectations that drop queued/busy events, and require checkpoint-after-commit plus explicit payload-conflict findings. |
| Registry, boundary, climate, authority, posting, and finding-specific modules not listed above | **Do not reuse** | Their entities, scores, moral vocabulary, and public surfaces do not belong in the admission ledger. Similar-looking nouns are not reusable semantics. |

## Missing/new work

- Strict record models and Lexicon validation with mandatory URI+CID subjects.
- Semantic event variants, per-source delivery/authenticity receipts, global
  observer causality coordinates, quarantine, and a durable checkpoint protocol.
- Deterministic authorization/projection with explicit duplicate/conflict results.
- Exact-CID subject resolver and offline fake repository adapter.
- Read-only API, escaped HTML community surface, and audit view.
- `communityd` administrator boundary, credential provider, fake writer, and
  immutable real writer adapter.
- Wheel/import/config tests proving that `communitywatch` cannot reach
  credentials, signing, write methods, or `communityd`.
- Atomic event/projection/checkpoint transactions and deterministic rebuild.

## Licensing

The donor offers `MIT OR Apache-2.0` through `LICENSE-MIT`, `LICENSE-APACHE`,
and `pyproject.toml`; it has no `NOTICE` file. Before the first code copy, this
repository must choose a project license and a donor-license compliance path.

- Under MIT, preserve the donor copyright and permission notice with copied
  substantial portions.
- Under Apache-2.0, distribute the license, retain notices, and mark modified
  files as changed.

Phase 0 copies no donor source, so its only provenance obligation is this
inspection record. “Plumbing theft” begins only after the boundary and license
review are attached to the actual copied code.

## Related cold-path references

V0-M2A now authorizes a bounded DuckDB/Parquet implementation, but it does not
authorize importing donor code. The useful doctrine below is folded into the
V0 storage contract; every source copy still requires a function-level row,
license choice, and boundary review before implementation. The listed tracked
files were inspected read-only at
Driftwatch commit `6227bd81c014f24cc8e51600a1937fab089ab308`; unrelated
worktree changes were neither read as authority nor modified.

| Reference | Decision |
|---|---|
| `../driftwatch/specs/gaps/gap-spec-cold-path-parquet-duckdb.md` and `gap-spec-cold-path-phase-3.5-forward-parquet-capture.md` | Adopt the hot-SQLite/cold-Parquet split and the rule that DuckDB is an offline off-ramp, never ingest or request handling. Reject synchronous dual-write and continuous tiny-file export. |
| `../driftwatch/specs/gaps/gap-spec-log-structured-artifact-system.md` | Reserve stable semantic IDs, schema versions, lifecycle, high-water, hashes, quarantine, and limitation fields. Do not build its generalized artifact system for V0. |
| `../driftwatch/specs/gaps/gap-spec-facts-snapshot-manifest.md` and `gap-spec-facts-export-duckdb-snapshot-001.md` | Reuse manifest/admissibility questions and controlled quarantine tests during V0-M2A. Settle hash scope and versioning explicitly instead of copying unresolved choices. |
| `../driftwatch/src/labeler/facts_export_duckdb_snapshot.py`: `_ensure_snapshot_schema`, `_resolve_parquet_paths`, `_read_uri_rows`, `_write_manifest_atomic`, `export_snapshot_once` | **Do not reuse yet.** Its `rowid_src` warning demonstrates why SQLite coordinates cannot become identity. `_read_uri_rows` loads file rows plus a global URI-dedup map in Python and uses path-order last-row-wins, unsuitable for immutable event history. Publication can expose a manifest before final artifact replacement. Later hash/high-water/separate schema-version fields come from specs, not this implementation. |
| `../driftwatch/tests/test_facts_export_duckdb_snapshot.py` | During V0-M2A, adapt quarantine, missing-input, manifest, count, and attach test ideas only after the required provenance/license review. Add the missing case where manifest creation succeeds but final artifact publication fails. |
| `../driftwatch/docs/SQLITE-PRODUCTION-REFERENCE.md` | Reuse after adaptation for bounded transactions, explicit schema versions, WAL connection lifetime, and long-reader avoidance. Communitywatch still needs its own measured limits. |

Parquet is custody of observer history, never the portable admission ledger.
DuckDB is read-only question machinery. Cold artifacts retain the
source authenticity status, exact record CID, and payload hash, but neither an
artifact receipt nor a manifest is signed with or interpreted as community
authority. No cold-path dependency may enter `community_model` or `communityd`.
Driftwatch is also dual-licensed `MIT OR Apache-2.0`; any future source copy
must record the chosen option and notices independently of this design review.

## Spaces alpha live-client references (2026-08-24)

The live Juniper adapter was written fresh against exported package APIs. The
pinned Bulletin checkout was inspected only as a compatibility oracle; it has
no repository license file, so none of its application source was copied.

| Reference | Decision |
|---|---|
| `bulletin/lib/auth/client.ts`, `lib/auth/metadata.ts`, and OAuth route handlers at `ccca73d212167e20da56db4691ba7c94e9ad5ccc` | **Inspect only; no source copy.** These established which alpha package exports Bulletin exercises and confirmed that browser state/session persistence is secret-bearing application custody. Juniper uses a separately written file-store and web-session boundary. No Bulletin identity, configuration, UI, or logging behavior is inherited. No license is asserted for this checkout. |
| `@atproto/lex-client`, `@atproto/lex-schema`, `@atproto/oauth-client-node`, and related packages from `bluesky-social/atproto` permissioned-data commit `89deb9faca20e56fa2a262fe9746ed52bc1095ba` | **Use public APIs under MIT OR Apache-2.0.** Juniper pins the published `0.0.0-spaces-alpha-20260818163953` packages and independently declares only the three read/write RPC shapes needed by its narrow adapter. This protocol compatibility code stays in `apps/juniper-live`; it does not enter shared models or the observer. |

The authority-side `packages/communityd-alpha-node` process independently
declares the pinned `createRecord`/`getRecord` shapes from the same dual-licensed
ATProto source. Its small hashed-file OAuth store repeats the already-reviewed
Juniper browser-store pattern rather than importing the author application:
the duplication is deliberate process/dependency custody. No browser route,
author collection, session directory, or source code from unlicensed Bulletin
is shared with the authority process.

The SCV0-L7 live projection composer and atomic generation publisher were
written fresh from this repository's qualified SA1/M1/M2/M5A/M6A interfaces.
No Labelwatch/Driftwatch publication function or Bulletin application code was
copied. The immutable-generation-plus-pointer pattern is an independent,
narrow implementation whose observer-only dependency graph is enforced by the
clean-wheel package suite; it has no authority writer, network client, signer,
credential, SQLite, or `communityd` import.

The L8 `packages/communitywatch-alpha-node` OAuth file store repeats the small
hashed-file/0600 pattern from `packages/communityd-alpha-node/src/store.ts` and
`apps/juniper-live/src/storage.ts` rather than importing either authority or
author application. This is deliberate custody duplication: the observer has
its own OAuth session directory and no authority-writer dependency. The
acquisition and receipt implementation is new code over the exported pinned
ATProto `@atproto/space` DPoP API. The upstream `_space.ts` test helper at
commit `89deb9faca20e56fa2a262fe9746ed52bc1095ba` was inspected only to confirm
the two-hop delegation/credential exchange; no reference application or test
source was copied. The upstream packages are MIT OR Apache-2.0; this project
continues its existing dual-license treatment.

## Intra-repository reuse — `community-submit` (2026-08-17)

The participant-side self-submission tool re-implements a small amount of
`communityd` behaviour rather than importing it. Recorded here because the
same provenance discipline applies to intra-repository copies as to donor
code, even though no external license question arises (both live in this
repository).

| Original | Decision |
|---|---|
| `communityd/pds.py`: `SessionCredential`, `EnvFileCredentialProvider` | **Re-implemented, not imported**, as `community_submit.transport.Credential` and `community_submit.cli.load_credential`. Same shape (`env:VARNAME` → JSON file outside the repository, redacted `repr`, messages that never echo the path or contents). Importing `communityd` would put the community's authority-writer code and the participant's credential in one distribution and one import graph. |
| `communityd/pds.py`: `PdsTransport`, `PdsSession` | **Re-implemented, narrowed.** The participant client speaks exactly three XRPC calls (`createSession`, `repo.getRecord`, `repo.createRecord`). It has no ledger reader and no authority writer, so `create_immutable`, `listRecords` pagination, and the community-ledger scoping checks are deliberately absent. |
| `communityd/pds.py`: `PdsAuthorityWriter._resolve_ambiguous` | **Pattern reused, re-implemented.** One write attempt, never retried; a lost response is settled by reading back the deterministic rkey and comparing authority-defining fields. Copying the reasoning matters more than copying the code: a blind retry can fork a repository history. |
| `governance/tools/v0_exercise.py`: `_x7_rkey` | **Pattern reused.** V0 requires submission rkeys to be TIDs, so a content digest is folded into the TID alphabet to keep re-runs idempotent at one key. `community_submit.submit.submission_rkey` derives from `(community DID, subject URI, subject CID)` rather than from an exercise token. |

Boundary consequences: `community-submit` depends only on `community-model`.
The package-boundary suite pins that whitelist, so it cannot import
`communitywatch`, `communitywatch-archive`, `communitywatch-web`, or
`communityd`, and none of them may import it. It writes one collection —
`app.phlogiston.community.submit` — into the authenticated participant's own
repository. It holds no community credential, names no admission or
moderation collection, and adds no authority. Observer-only assumptions
elsewhere are unaffected: nothing in the observer changed.

## SCV0-L9 live observer composition (2026-08-24)

The `packages/communitywatch-live` supervisor was written fresh against this
repository's SA9b/SA9c, SA2/SA1, SA6, and L7 APIs. No Labelwatch, Driftwatch,
Bulletin, or PLC-directory implementation code was copied. Its stdlib HTTP
PLC-audit acquisition is intentionally narrow; immutable evidence custody and
atomic publication call already-reviewed intra-repository APIs.

Observer-only assumptions remain safe. The package has no signing, authority
writer, `communityd`, or credential-store import, and its clean-wheel boundary
test enforces that graph.

## SCV0-L10 disposable authority bootstrap (2026-08-24)

No Labelwatch or Driftwatch code was copied. The secret JSON file-store shape
and ambiguous-write/readback pattern were adapted from this repository's
`apps/juniper-live/src/storage.ts` and
`packages/communityd-alpha-node/src/write.ts`: file permissions remain 0700 /
0600, one create is attempted, and only an exact readback settles an ambiguous
result. The implementation was rewritten for two one-time bootstrap profiles.
All code is covered by this repository's Apache-2.0/MIT licensing.

Observer assumptions remain safe because `juniper-bootstrap-alpha` is a
separate authority-only Node package and is absent from every observer,
renderer, and `communityd` dependency graph. It can write only pinned Lexicon
records and invoke exact Space creation; it cannot write posts, submissions,
admissions, removals, or withdrawals.

## PCV0 supervised Lexicon publisher (2026-09-08)

No Labelwatch or Driftwatch code is reused. The new, separately installed PCV0
publisher adapts these intra-repository Juniper bootstrap pieces:

| Original module and function | Why reusable | Changes and boundary review |
|---|---|---|
| `packages/juniper-bootstrap-alpha-node/src/bootstrap.ts`: `stable`, `parseLexicons`, `publishExactLexicons` | The bounded canonical-JSON digest, exact schema-set validation, deterministic record key, single create attempt, and exact readback pattern are protocol-independent ceremony safeguards. | Rewritten for all seven `app.phlogiston.community.*` schemas, a supplied namespace-authority DID, a digest-bound human acceptance artifact, durable pre-dispatch intents, DNS verification, and secret-free receipts. The package can write only `com.atproto.lexicon.schema`; it has no community actor or participant writer. |
| `packages/juniper-bootstrap-alpha-node/src/store.ts`: `SecretStore` | OAuth state/session custody must be private, atomic, and outside Git. | Rewritten with distinct PCV0 paths and the same 0700-directory/0600-file constraints. It is deliberately duplicated instead of imported so the permanent-schema publisher does not depend on the disposable Juniper package. |
| `packages/juniper-bootstrap-alpha-node/src/loopback.ts`: `startLoopbackCallbackServer`; `worker.ts`: `completeCallback`, `client`, Lexicon publication adapter | Interactive loopback OAuth and create-only repository access match the required supervised publication ceremony. | Rebranded and narrowed to a single Lexicon profile, supplied authority DID, exact callback, and `atproto repo:com.atproto.lexicon.schema?action=create`. OAuth errors are reduced to allowlisted classifications; callback parameters, tokens, and library prose never enter output. No Space operation or unattended credential path remains. |

All cited source and the new package are covered by this repository's `MIT OR
Apache-2.0` license. Observer-only assumptions remain safe: the package is absent
from observer, browser, policy, and `communityd` dependency graphs and is invoked
only for the human-gated publication ceremony. Its DNS resolver and repository
ports are injectable for offline tests; publication possession confers no
community moderation or admission authority.
