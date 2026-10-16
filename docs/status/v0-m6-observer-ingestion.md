# V0-M6 — Observer ingestion

**Schema:** factual-milestone-note-v1

**Authority effect:** none

**Rulings made:** none

This note records what V0-M6 added and how the OQ-2 operator ruling (answer A
with the later-revision qualification) is represented in code and data. It
marks nothing complete and changes no contract.

## What was added

- `communitywatch.websocket` — minimal stdlib masked-frame WebSocket client
  (ws/wss). The frame/handshake pattern is adapted from the repository's
  governed read-only exercise harness (`governance/tools/v0_exercise.py`);
  this is a fresh product implementation, not an import of governance
  tooling, and no donor-repository code was copied.
- `communitywatch.jetstream` — Jetstream v2 filtered subscription adapter
  implementing the `EventSource` port. It subscribes to the four community
  collections; `wantedDids` is supported but empty by default because
  submission authors are not known a priori. Every delivery it emits is an
  unverified claim (`trust_mode=verify_repo`, `verification_outcome=
  unverified`, method `jetstream-v2-transport`).
- `communitywatch.secp256k1` — pure-Python secp256k1 ECDSA **verify only**
  (no key generation or signing path exists in the package), checked against
  independently minted OpenSSL vectors, with low-S enforcement.
- `communitywatch.repoproof` — CARv1 parsing with per-block hash checks,
  MST membership/non-membership lookup, signed-commit verification against
  the DID document key, and DID-document key/PDS-endpoint extraction.
- `communitywatch.syncclient` — bounded unauthenticated HTTP GET, did:plc /
  did:web document resolution, and `com.atproto.sync.getRecord`/`getRepo`
  fetchers.
- `communitywatch.verifying` — `VerifyingEventSource` (claim -> verified
  deliveries) and `VerifiedSubjectResolver` (exact-subject refresh through
  the same verified getRecord path, `trust_mode=verify_repo`).
- `communitywatch.runner` + `cli`/`builder` — the index pipeline:
  source -> verify -> atomic ingest (event, receipt, projection, and cursor
  commit together), plus the resolve stage feeding the existing health
  surface (`lastIngestAt` from `ingest_sources.last_success_at`,
  `lastResolveAt` from `subject_observations.checked_at`, per-source
  cursors).
- `community_model.dag_cbor.encode_dag_cbor` — canonical encoder, the exact
  inverse of the existing decoder (needed to re-encode unsigned commits for
  signature verification).
- Observer config gains an optional `administrator_did` key (required by the
  index CLI); the strict parser still rejects every unknown and every
  credential-shaped key, and the example TOML uses `wss://` for the event
  source.

## OQ-2 representation

Jetstream events are treated strictly as transport/discovery evidence. Each
in-scope claim triggers a proof fetch from the DID-resolved PDS
(`getRecord`, or `getRepo` for deletes/absence); verification checks every
CAR block hash, the commit signature against the current DID document key,
MST membership or non-membership, and the record block hash against the
claimed CID. `rev`/order come only from the signed commit. The proof CAR's
locator and `sha256:` hash persist as `event_receipts.evidence_ref` /
`evidence_hash` (and the same columns on `subject_observations`).

Later-revision qualification, exactly as ruled:

- proof rev == claimed event rev, claims consistent: one `verified`
  receipt (method `repo-proof-v1`).
- proof rev later than the claimed event rev: the historical event is
  ingested `unverified` (fail closed; the reducer records the existing
  `authenticity_unverified` finding), and a separate `verified` resync
  delivery (method `repo-resync-v1`, cursor `<seq>%resync%<proof-rev>`)
  carries the current repository state at the signed commit's own revision.
  The later proof is never represented as authentication of the historical
  event.
- A repository state proof attests presence/absence, never the claimed
  operation. Verified current state is therefore represented as a presence
  fact (`create`) or absence fact (`delete`) at the signed revision;
  claimed updates that cannot be corroborated stay `unverified` rather than
  becoming verified mutations, so a forged relay "update" cannot convict a
  pristine create-only authority record.
- Contradiction at the event's own revision, malformed CAR/MST material, or
  a bad signature: `failed` (bad CARs keep their evidence hash). Transport
  or DID-resolution failure: `unverified` with no evidence.

## Known limitations (offline milestone)

- Events stranded `unverified` by an anomalously stale proof (proof rev
  older than the claimed rev) are not retried automatically; recovery is an
  operator cursor rewind, which is durable and idempotent.
- did:web resolution is implemented and URL-construction-tested; only the
  did:plc path is exercised end-to-end (loopback TLS is impractical).
- All tests are offline: loopback fake Jetstream (WS) and fake PDS/PLC
  (HTTP) servers, programmatically built CAR/MST fixtures, and OpenSSL
  secp256k1 known-answer vectors.

## Addendum 2026-08-14 — v1/v2 wire correction

The first controlled live smoke run caught a wire mismatch: the adapter
initially implemented the frozen v1 shape (flat `kind`/`commit` events at
`/subscribe` with `wantedCollections`/`wantedDids`). The adapter now targets
the v2 wire verified live on 2026-08-14 against the public instances and
https://bsky.network/docs/jetstream/:

- tail path `/xrpc/network.bsky.jetstream.subscribeEvents` with repeated
  `collections=`/`dids=` params plus `kinds=commit` (a collections filter
  constrains commit events only);
- `{"$type": "message", "payload": {...}}` envelopes with
  `network.bsky.jetstream.subscribeEvents#commit` payloads (`seq` cursor,
  inclusive resume, at-least-once);
- the example configuration points at `wss://jetstream.us-west.bsky.network`
  (the jetstream1/jetstream2 hosts serve only the frozen v1 wire);
- a regression test proves a v1-shaped flat message quarantines as
  unrecognized input instead of being silently accepted.

No verification, provenance, resync, or OQ-2 later-revision semantics
changed; only the transport wire shape moved.

## Governed outcome (2026-08-14)

V0-M6 completed as a governed task: candidate commit
`1e2ebb3cc6bcf1ba878204662ce533cb7e680201` (one bounded commit over task base
`d64b583`, `Governor-Task: V0-M6`) passed `./scripts/v0-gate V0-M6` in a fresh
clean checkout under task packet `CEP-V0-M6-2026-08-14-02`, including the new
`exercise_receipts` check. The controlled live exercise `V0-X6-READ-SMOKE`
(packet `CEP-V0-X6-2026-08-14-03`, v2 relay host confirmed by the operator)
returned PASS receipt `EXR-V0-X6-READ-SMOKE-run-v0-x6-2026-08-14-01-20260814213447`:
3 requests, 743 bytes, 0 events, 0 proof fetches, 0 writes, exactly the three
pinned origins. The first attempt (`0a9c53e`, v1 wire) failed the smoke before
any gate PASS and is preserved un-promoted on branch `failed-v0-m6-attempt-1`.
The execution-evidence bundle (`run-v0-m6-2026-08-14-02`) is retained in the
controller evidence store and validated.

## Defect repair (2026-08-15): empty intermediate MST nodes

During V0-M8 trial-state reconstruction from the retained X7 -05 artifacts,
`repoproof.mst_lookup` was found to reject spec-legal empty intermediate MST
nodes ("only the root of an empty tree may be empty"). The ATProto repository
specification permits empty intermediate nodes that point to a sub-tree
containing entries, and the production PDS emitted exactly such a proof path
for the X7 -05 submission CAR. The verifier therefore reported genuinely
valid proof material as failed. The X6 read smoke had captured zero commit
events (0 proof fetches), so verify-at-ingest had never run against a live
CAR of this tree shape before.

Repair `c757ad9` (Governor-Task: V0-M6, packet `CEP-V0-M6-2026-08-15-01`):
the walk descends through an empty intermediate's left link; empty leaves
below the root, an empty root pointing at a subtree, and node cycles remain
fail-closed. Hostile tests cover each pruned shape, and the retained live
submit CAR is a golden regression fixture
(`tests/fixtures/mst-empty-intermediate/`). Offline suite 557 passed;
`v0-gate V0-M6` re-run in a pristine checkout against the existing X6 PASS
receipt: PASS. Bundle: `runs/v0-m6-2026-08-15/v0-m6/manifest.json`.
