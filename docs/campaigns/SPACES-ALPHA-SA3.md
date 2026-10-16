# SA3 — Spaces alpha reference interoperability qualification

**Status:** deterministic cross-language fixture implementation; no network,
credentials, authority, or deployment. **Upstream observation date:**
2026-08-20. The reference implementation is a serialization and compatibility
oracle only, not a trust root or protocol specification.

## Architectural result

SA3 adds a comparison seam above the replaceable SA2 container adapter and
leaves the SA1 qualifier unchanged:

```text
pinned TypeScript @atproto/space.serializeRepo
        |
raw golden CAR + reference interpretation manifest
        |
communitywatch_spaces_alpha.interop
        |
unchanged SA2 roots + blocks + SpaceRepoEvidence
        |
unchanged SA1 qualify_repo_state
        |
bounded SpaceObservationReceipt
```

`compare_reference_car()` first requires the exact generator, upstream commit,
package version, fixture format, raw artifact digest, and local SA2/SA3 adapter
versions. It then invokes SA2 and compares ordered roots, block count, ordered
CIDs, exact block bytes, and supported codec/multihash interpretation with the
reference manifest. It returns the ordinary SA2 extraction. The caller passes
that extraction to the existing SA1 qualifier, after which
`assert_qualification_parity()` compares deterministic receipt identities.

The interoperability result has an empty semantic-observation claim set and
`governanceAuthority: false`. It cannot qualify a record itself. SA1 still runs
directly on pre-separated evidence, and SA2 still parses CARs without any
governance dependency. Neither the public ATProto verifier nor `communityd` is
imported or modified.

## Reference artifact and reproducibility

The oracle is `@atproto/space` version `0.0.1` from
`bluesky-social/atproto` commit
`89deb9faca20e56fa2a262fe9746ed52bc1095ba`, the exact pin used by SA1 and SA2.
The generator calls that commit's `serializeRepo()` and parses its result with
the same checkout's `readCarStream()`. It supplies the existing synthetic SA1
initial commit and one record; it does not generate a commit, signature, key,
identity, access grant, or credential.

Reproduction uses a full or dependency-complete checkout at that exact commit,
Node `v24.13.0`, the repository-pinned pnpm `11.11.0`, and built
`@atproto/space` workspace dependencies:

```text
corepack pnpm install --filter @atproto/space... --frozen-lockfile
corepack pnpm --filter @atproto/space... build
node tests/fixtures/spaces-alpha/reference/sa3-generate.mjs \
  <pinned-atproto-worktree> \
  tests/fixtures/spaces-alpha/sa1-qualification.json \
  tests/fixtures/spaces-alpha/reference/sa3-golden.car
```

The driver refuses a checkout whose HEAD differs from the pin. Its SHA-256 is
`c74e1e648f803018e812d0751c320e740122ba2e0a431b2ea7e35285e994d5a1`.
The raw 580-byte artifact SHA-256 is
`2ac249edc712c796211250bd7084850fc3d2cb576a575fa4c6c93da92115dd23`.
It contains, in order:

1. commit root/block
   `bafyreiggysipccymaundrv76fomitpnvusiphomwx6w6tsrtf3khenb5ye`;
2. index root/block
   `bafyreiayevockqye2equ2wggsgmvq2jrxvzcl5pv7sdky7zc7zc5vwauvy`;
3. record block
   `bafyreicuy2luqzpdzwcidb27j72njmsobbyzic5m54kccc33svu7uumfqa`.

Two serializer calls in one pinned reference process emitted byte-identical
CARs with that digest. A separate regeneration produced the same artifact.
The golden is also byte-identical to the locally framed SA2 CAR1. Tests do not
infer interoperability from that equality alone: they separately compare
roots, ordered blocks, bytes, codec interpretation, extracted SA1 evidence,
verified claim sets, and receipt ID
`sha256:c7584ad43983317c1a251aef0b9ee4801669579898a84ca3528c18e8e868abf0`.

## What SA3 proves

For this pinned synthetic repository state and exact artifact, SA3 proves that:

- the independent TypeScript serializer and local SA2 parser agree on CAR
  bytes, ordered roots, ordered block CIDs, block bytes, and CID components;
- SA2 extracts exactly the pre-existing SA1 commit, index, record ordering,
  record CID, and record bytes; and
- unchanged SA1 qualification produces the same structured verified claims
  and deterministic receipt as the direct pre-separated route.

These are interoperability facts about supplied fixture evidence. The SA1
receipt retains its bounded cryptographic meaning; SA3 adds no verified
identity or repository claim.

## What SA3 does not prove

SA3 does not prove that the reference implementation is correct, secure, or
authoritative. It does not prove Space authority, author identity beyond SA1's
supplied-key checks, source-host authenticity, credential/access validity,
currentness, membership, standing, admission policy, governance legitimacy,
authorization, effect execution, public archival equivalence, or production
readiness. Historical receipt parity cannot become current authority.

The reference generator is not called by package or root tests. Its dependency
tree and Git checkout are reproducibility tooling, not product dependencies.
The committed artifact and manifest make deterministic tests hermetic.

## Interoperability and hostile witnesses

The positive tests establish:

- I1 exact root count, order, and CIDs;
- I2 exact block count, CID order, bytes, and codec/multihash interpretation;
- I3 equality with the existing SA1 input, including record order/CID/bytes;
- I4 equality of SA1 verified claims, qualified result, and receipt identity;
  and
- I5 byte-identical output across two reference generations, plus equality to
  the existing SA2 CAR1.

Refusal tests demonstrate:

- R1 one mutated block byte fails golden digest parity and then SA2 CID
  validation when tested directly;
- R2 a locally valid parse with a changed reference block interpretation fails
  explicit parity comparison;
- R3 an equivalent-value but noncanonical CAR header-length varint is refused,
  rather than treated as an alternate encoding;
- R4 a valid public one-root ATProto CAR has no Spaces qualification fallback;
- R5 changed upstream commit/package or local adapter/interoperability versions
  fail compatibility; and
- altered expected receipt metadata cannot relabel a different SA1 result.

## Remaining alpha gaps

Implementation incomplete:

- the reproducibility driver uses the pinned serializer library, not a running
  reference PDS/provider-to-consumer session.

SA4 supplies the previously missing multi-record and consecutive-state CAR
serialization witnesses. Its operation batches remain fixture inputs because
the pinned full-state CAR format does not contain an operation log.

Upstream unspecified or unstable:

- the permissioned-data branch moved after the pinned commit and the Spaces
  package disappeared from its later observed head;
- no stable release promises that CAR root/order, canonical block order,
  codecs, or index representation will remain unchanged; and
- reference correctness and canonical-encoding requirements are not promoted
  here beyond what the pinned implementation and local fail-closed parser
  demonstrate.

Intentionally deferred: live fetching, a hosted or local PDS, service
authentication, DID resolution, credentials/OAuth, credential storage, Space
membership, community standing, governance authorization, effects, projection,
and deployment.

## Adversarial review result

The reference implementation never becomes a trust root: all stored reference
metadata is pin-checked and then compared, not promoted to SA1 claims. Artifact
presence and root identity do not admit a record. No credential is modeled.
No cryptographic claim is widened into governance. The public verifier remains
untouched. All reference-specific metadata and comparisons are isolated in
`interop.py`, `compat.py`, and the SA3 fixtures/tests; CAR churn remains in SA2.

## Next smallest experiment

Add a second pinned reference golden covering one multi-record repository
transition, then compare its extracted state with the existing SA1 transition
qualification path. This exercises ordering and parent/state interoperability
without adding network, OAuth, governance, or effects.
