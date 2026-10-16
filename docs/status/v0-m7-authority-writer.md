# V0-M7 — Authority writer (real PDS adapters)

Status: implemented, offline-tested. `./scripts/check` green.

## Surface

`communityd` now has real adapters in `packages/communityd/src/communityd/pds.py`,
wired by `cli.build_runtime` when the config selects them:

- `PdsTransport` — stdlib-only JSON XRPC with bounded timeout, bounded retries
  for idempotent requests (GETs, `createSession`), and single-attempt writes.
- `PdsRecordReader` — public `com.atproto.repo.getRecord`; exact-vs-current CID
  comparison. Results carry `trust_pds` / `unverified` provenance.
- `PdsAuthorityLedgerReader` — public `com.atproto.repo.listRecords`, paginated
  over the community repo's admission/modAction collections, filtered by exact
  subject. No observer storage or artifact is touched (the port's standing rule).
- `PdsAuthorityWriter` — authenticated `com.atproto.repo.createRecord` at the
  deterministic rkey (`community_model.admission_rkey` / `removal_rkey`).
  Pre-create readback: compatible occupant → same operation ("existing");
  incompatible authority-defining fields → hard conflict (exit 5). No
  update/delete exists.
- `PdsSession` — lazy `com.atproto.server.createSession`; the bearer token is
  held in memory only. A session whose DID is not the configured community DID
  is rejected.
- `EnvFileCredentialProvider` — `credential_ref = "env:VARNAME"`; the variable
  names a JSON file outside the repo: `{"identifier": ..., "app_password": ...}`.
  Missing env/file/malformed → exit 7 before any network call.
- `communityd.fakepds` — a loopback (127.0.0.1) fake PDS speaking those four
  procedures for tests, with response-drop injection for ambiguity tests.

Config accepts `reader_adapter`/`ledger_adapter`/`writer_adapter = "pds"` and
`credential_provider = "env_file"` (`config/communityd.example.toml` documents
both; defaults stay fake/offline). `community_pds_url` must be a bare https
origin, or loopback http for tests. The `pds` writer requires `env_file`.

## Rulings implemented

- OQ-3/A: communityd holds an *authenticated capability* (app-password session;
  the PDS signs and commits). No key custody anywhere. The secret transits
  exactly: credential file → in-memory `SessionCredential` → `createSession`
  request body → in-memory token. It is never logged, never in error JSON,
  never written; reprs are redacted and tests grep outputs and server request
  logs for the canary.
- OQ-4/A: any real adapter selection uses `LocalAdminAuthorizer`
  (OS effective UID vs `allowed_uid`) before any reader/credential/writer call;
  mismatched-UID tests assert zero network I/O. The configured administrator
  DID remains community-attested attribution and may equal the actor DID in V0.

## Ambiguous-write resolution (exactly)

`createRecord` is sent once, with one payload and one `createdAt`. On timeout,
transport failure, malformed success payload, or HTTP 5xx — any case where the
commit may have landed — the writer never blind-retries. It reads back the
deterministic rkey:

- occupant compatible (all fields except generated `createdAt` equal) → return
  that reference as the same operation;
- occupant incompatible → `ImmutableConflictError` (exit 5);
- no record → the write definitively failed (exit 8);
- readback itself fails → outcome remains ambiguous (exit 8).

## Governed execution (2026-08-15)

X7 write-smoke exercised these adapters live against the participant repo under
packet `CEP-V0-X7-2026-08-14-05` and passed:
`EXR-V0-X7-WRITE-SMOKE-run-v0-x7-2026-08-15-02-20260815033140` — four writes
(post, submission, admission via `communityd admit`, removal via
`communityd remove`), four Jetstream v2 events, four independent
`com.atproto.sync.getRecord` proof CARs, verified projection transitions
(submitted → visible → removed), 22 of 24 authorized requests, 0 retries,
21,282 bytes, ~6 s. Every counted request is itemized in the retained
`request_log.ndjson`. Two earlier attempts (-03, -04) failed closed on
harness defects (proof-fetch parameter; 24-request ceiling) and are retained
as failure evidence; their eight records are immutable and distinct from the
-05 records. `v0-gate V0-M7` passed on candidate `4d72bb4` in a pristine
checkout; the execution evidence bundle is
`runs/v0-m7-2026-08-14/v0-m7/manifest.json` in the evidence repository.

Two request-economy repairs landed with the -05 cycle: PLC DIDs resolve
through `plc.directory` directly (no wasted PDS probe), and one deterministic
create performs one existence check — `create_immutable` reports
created/existing via `ImmutableCreateOutcome`, replacing the operations
layer's duplicate pre-read.

## Known V0 limits (honest list)

- All repos are read through the configured `community_pds_url`; multi-PDS DID
  resolution for author repos is future work (single-PDS deployment assumption).
- PDS reads are `trust_pds`/`unverified`; no repo-proof verification on the
  writer side (observer-side proof policy is the OQ-2 surface).
- No token refresh: a 401 from the PDS mid-invocation is exit 7; CLI
  invocations are seconds long, so expiry mid-run is out of V0 scope.
- PDS rejection of a well-formed record (4xx) maps to exit 8.
