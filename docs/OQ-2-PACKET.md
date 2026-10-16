# OQ-2 operator-question packet

**Status:** prepared unsigned; non-authorizing

**Schema:** manually reviewed Markdown, following the OQ-7 bootstrap exception
format pending V0-G0 bootstrap-output acceptance

**Packet ID:** `OQP-OQ-2-2026-08-14-01`

**Question ID:** OQ-2

**Prepared:** 2026-08-14 against base commit
`9bd774bd14fc9c695227f7ce32a5b738c37cb097`

**Preparer:** agent-produced proposal

**Authority effect:** none

**Human receipt required:** yes

This is a review object, not an operator decision, a controller-entry packet,
an execution-evidence bundle, a `BUILD.md` amendment, or a community authority
record. It contains no ruling or signature field.

## Protected review inputs

| Role | URI | SHA-256 |
|---|---|---|
| promoted-question register (post-OQ-5/OQ-7 decisions) | `repo:docs/OPEN-QUESTIONS.md` | `sha256:40296ace173a75b698bc811a800a035b4bf31f8d3021a0b2f10c4b4c4acccc40` |
| authorized V0 milestone design | `repo:docs/IMPLEMENTATION-PLAN.md` | `sha256:9713bfb4729844bbd029423f3f66cf192ab9b90c172b7585bfd6d5b4fd55da35` |

External evidence for the forcing case was captured 2026-08-14 under
`/tmp/oq2-evidence/` (live Jetstream v2, relay firehose, and PDS proof-CAR
samples, plus an end-to-end independent verification script and transcript).
Upstream sources cited inline below.

## Question

Must `communitywatch` (1) retain and independently verify repository
commit/CAR material for authority records, or (2) trust a specifically
configured relay's verification and state that trust boundary in every
audit/export? The same review must ratify subject-resolution trust:
independently verify repo/CID evidence or accept the hosting PDS's
attestation. Event and resolver policies remain separately labeled even if
both choose an attested boundary.

## Why this is being asked now

OQ-2 blocks V0-M6 (live ingestion). The register's analysis predates the
Jetstream v2 rewrite released 2026-08-13, so the cost/feasibility premises of
every answer needed re-checking against the actual current event shape. That
evidence now exists (below).

## Observed forcing case

1. OQ-2 is a named blocker for V0-M6 in the register.
2. V0-M5 is the last remaining milestone before M6; the ingestion adapter's
   trust shape must be settled before M6 implementation.
3. Jetstream v2 changed the wire contract the original analysis assumed
   (v1 nested `commit` object, `time_us` cursor; v2 flat payload, `seq`
   cursor, new sync/info event kinds, keyed HTTP replay archive).

## Evidence from the 2026-08-14 campaign

Captured live and from authoritative upstream sources
(`github.com/bluesky-social/jetstream` main, `bsky.network/docs/jetstream`,
`atproto.com/specs/{event-stream,sync,repository}`):

- **Jetstream v2 commit events carry digests only, never proofs.** Required:
  `seq, did, time, rev, operation, collection, rkey`; optional `cid` (record
  CID) and `record` (decoded JSON). **No commit CID, no signed commit bytes,
  no CAR slice, no `since`/`prevData`.** The v2 design doc lists
  "cryptographic proof storage" as explicit non-goal #2; its documented ingest
  validation is syntactic only (rev is TID-shaped, paths are NSID/rkey-valid).
- **Deletes carry no `cid` and no `record`** — identity is URI-only; a deleted
  record's CID is unrecoverable from Jetstream unless previously seen.
- **Independent verification is cheap and was demonstrated end-to-end** on a
  live capture: resolve DID doc (plc.directory), one unauthenticated
  `com.atproto.sync.getRecord` HTTP GET to the author's PDS (~4 KB proof
  CAR), then verify: all CAR block hashes; record block hash == claimed CID;
  commit signature against the DID document's secp256k1 key; MST proof chain
  from the signed commit root to the record entry. The relay firehose
  (`com.atproto.sync.subscribeRepos`) is self-certifying per spec and carries
  per-commit CAR slices live.
- **Ordering/cursor reality:** `seq` is a monotonic per-instance cursor,
  inclusive on resume, at-least-once (consumers must be idempotent); per-DID
  ordering only, no cross-repo ordering; live lookback ~36 hours on hosted
  instances with `CursorTooOld` below the floor; deep replay via keyed,
  metered HTTP archive whose compaction physically rewrites sealed segments
  (not immutable evidence).
- **Fit against the V0 evidence model:** `trust_mode`, `verification_outcome`,
  and the hash scopes `observer_json_v0`/`delete_envelope_v0` map cleanly;
  `commit_cid` cannot be populated from Jetstream at all; `commit_rev` and
  `repo_order` are only relay-attested unless taken from a verified signed
  commit; `record_bytes` (raw DAG-CBOR) never appears on the Jetstream wire —
  `payload_hash` scope `dag_cbor` requires canonical re-encoding (spec-endorsed
  DRISL) or proof-CAR bytes; `evidence_ref`/`evidence_hash` must be minted by
  the adapter from retained proof material.

**Conclusion from evidence:** "require independently verifiable repo/commit
evidence for authority records" is implementable as written, at bounded cost
(the community surface is one small known repo in V0; one ~4 KB
unauthenticated GET per authority event). The engineering-cost argument for
accepting bare relay attestation on the authority path is no longer credible.

## Admissible answers

### A — Verify at ingest (recommended)

For the four community authority collections, treat Jetstream v2 as the
notification/cursor source only. Each in-scope delivery triggers a synchronous
proof fetch (`com.atproto.sync.getRecord`, or `getRepo` for the small
community repo) from the DID-resolved PDS; the adapter verifies commit
signature against the current DID document, the MST chain, and the record
block hash against the claimed CID; `rev`/order come from the signed commit,
not the envelope. Proof CAR (or its hash plus locator) is persisted as
`evidence_ref`/`evidence_hash`; only then may the receipt carry
`verification_outcome=verified`. Subject resolution uses the same getRecord
verification (`ResolveResult.trust_mode=verify_repo`), so exact-subject
evidence comes nearly free. Deletes require verify-at-ingest or prompt
confirmation, because delete evidence evaporates.

**M6 consequence:** `communitywatch` gains a read-only sync client (DID
resolution + CAR/MST/secp256k1 verification) within its detect-only charter.

### B — Hybrid attest-then-verify

Admit Jetstream deliveries as `attested` for low-latency projection, then
asynchronously upgrade to `verified` (or quarantine on proof failure) before
any authority effect. More moving parts; delete evidence can evaporate before
the upgrade runs.

### C — Trust the relay, labeled

Jetstream-only ingestion; every receipt/audit/export labeled `attested` with
the relay identity as evidence. Simplest M6; weakest: no commit CIDs exist on
the wire, deletes carry no CID, archive compaction erases content, and the
"cannot be mistaken for local signature verification" requirement would need
schema-level enforcement, not prose.

## Recommendation

**Recommended answer:** A

The evidence removes the cost objection to verification on the authority path,
and V0's entire thesis (a portable admission ledger) rests on the authority
records being independently checkable. Resolver trust follows the same answer,
as the OQ-2 text anticipates, with both policies separately labeled.

## Consequences by answer

### A

- **Authority delta:** none; satisfies only the OQ-2 blocker.
- **Blockers satisfied:** OQ-2. V0-M6 becomes eligible once its other
  prerequisites (M5) pass.
- **M6 shape:** filtered Jetstream v2 subscription (four collections,
  community DID allow-list, `seq` cursor, idempotent re-delivery) + verifying
  adapter as above; receipts carry proof-CAR evidence references.
- **Replay/fork implications:** retained proof material makes observed
  authority history independently re-checkable.
- **Abuse/T&S implications:** forged relay testimony cannot create authority
  projections.

### B / C

Same shape with progressively weaker evidence and correspondingly labeled
receipts; C additionally requires schema-level attestation labeling.

## Novelty condition

A replacement packet is required if: upstream changes the v2 wire contract
before M6; verification proves impractical at observed community scale; or the
operator wants a policy not exactly represented above (e.g., per-collection
mixed trust).

## Operator ruling

Absent by design. A separate human operator-decision receipt pins this
packet's digest and uses one ruling from
`select | defer | reject_packet | repack_required`.
