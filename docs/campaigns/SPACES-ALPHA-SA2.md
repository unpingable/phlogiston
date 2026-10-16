# SA2 — Spaces alpha raw CAR boundary qualification

**Status:** deterministic fixture implementation; no network, credentials, or
deployment. **Upstream observation date:** 2026-08-20. This is a transport
adapter for volatile alpha behavior, not a stable AT Protocol specification or
a second observation-verification model.

## Architectural result

SA2 adds one replaceable container boundary inside the existing separate
Spaces package:

```text
raw CAR bytes
        |
communitywatch_spaces_alpha.car
        |
ordered roots + content-addressed blocks + container provenance
        |
exact existing SpaceRepoEvidence
        |
unchanged SA1 qualify_repo_state
        |
bounded SpaceObservationReceipt
        |
existing SpaceObservation / EvidenceAdmission seam
```

`parse_space_car()` parses and validates the container. It cannot produce a
receipt. `extract_space_repo_evidence()` uses SA1's canonical index parser to
route the first commit block, second index block, and remaining record blocks
into the existing `SpaceRepoEvidence` type. `qualify_repo_state()` remains the
only code that establishes permissioned-commit, LtHash, MAC, signature,
record-content, author, or Space claims. SA1 can still be tested directly with
pre-separated inputs, and the regression witness produces exactly the same SA1
result from both input routes.

Neither the public `communitywatch` CAR/MST verifier nor `communityd` is
imported. There is no public-proof fallback, writer, signer, transport client,
or secret-bearing type.

## Pinned alpha compatibility boundary

SA2 pins the producer/consumer layout at the same [reference implementation PR
5187](https://github.com/bluesky-social/atproto/pull/5187) commit used by SA1,
`89deb9faca20e56fa2a262fe9746ed52bc1095ba`. Specifically, that commit's
`packages/space/src/sync/provider.ts` emits:

- CAR version `1`;
- exactly two roots, ordered commit then index;
- the commit and index as the first two blocks, matching those roots; and
- one record block per canonical index entry, in index order.

Its `consumer.ts` checks the same ordering and relies on the common CAR reader
to hash block bytes against their CIDs. SA2 accepts only CIDv1 DAG-CBOR
(`0x71`) blocks with SHA-256 multihashes (`0x12`, 32 bytes), matching the pinned
vectors. These constants and adapter identifiers live in `compat.py`, while
framing and handoff logic live only in `car.py`.

The PR's moving `permissioned-data` head was observed at
`f2c33aa4a72c95762c2708cf02acbfab7ddd2b5a` later on 2026-08-20; that tree no
longer contained the Spaces package. SA2 therefore does not silently retarget
the fixture to the branch head. It retains the reproducible implementation
commit and records the branch movement as direct evidence of alpha volatility.

## Exact SA2 container facts

For supplied raw bytes, a successful `ParsedSpaceCar` establishes only that:

- the header is one complete canonical DAG-CBOR map with CAR version `1`;
- it contains exactly two CID root slots in the pinned order (their commit and
  index structures remain SA1 concerns);
- all length-delimited sections are complete and use canonical unsigned
  varints;
- every block identifier uses the pinned CID components and its SHA-256 digest
  matches the exact block bytes;
- no duplicate block identifier occurs;
- the first block matches root 0, the second matches root 1, and original block
  order is retained; and
- the deterministic CID-to-bytes index contains those exact blocks.

The container provenance records those claims, raw-CAR SHA-256, ordered roots,
ordered block CIDs/sizes, adapter method/version, and separately labeled caller
context (`sourceVectorIdentifier` and alpha assumption). It deliberately has an
empty `semanticObservationClaims` set and `governanceAuthority: false`.

For handoff, SA2 additionally requires the remaining block count and order to
match the canonical index entries. That establishes deterministic routing into
SA1, not the truth of the index. SA1 reparses the index and independently checks
the commit, LtHash, cryptographic context, record CIDs, and record content.

## What SA2 does not prove

CAR validity does not prove author identity, Space authority/identity,
credential or access validity, source-host authenticity, repository
correctness, record currentness, community admission, standing, governance
legitimacy, per-occurrence authorization, or effect execution. A root is a
content identifier, not authority. A present record block is input to SA1, not
an admitted observation. Historical container validity cannot become current
authority.

SA2 also makes no public MST/CAR claim and provides no public archival
equivalence. A public CAR may be a valid CARv1 container under public ATProto
semantics while still being invalid at this Spaces-specific boundary.

## Deterministic and hostile witnesses

`tests/fixtures/spaces-alpha/sa2-car.json` wraps the SA1 initial commit, index,
and record bytes in raw CAR framing. CAR1 parses, hands off an exactly equal
`SpaceRepoEvidence`, and yields the same SA1 qualified state and receipt as the
unchanged pre-separated fixture route.

Refusal tests demonstrate:

- CAR-H1 swapped roots fail before qualification;
- CAR-H2 one root and CAR-H3 three roots fail the exact root-count rule;
- CAR-H4 a truncated block fails framing;
- CAR-H5 altered block bytes fail their declared CID;
- CAR-H6 a repeated CID with conflicting bytes fails as ambiguous;
- CAR-H7 a valid container and valid handoff reach SA1, where the unchanged
  commit hash versus LtHash mismatch is refused;
- CAR-H8 a real public one-root CAR fixture is refused, with no fallback;
- identical duplicate blocks also fail closed;
- a missing record named by the index remains visible and fails handoff;
- an unsupported block codec fails compatibility; and
- malformed framing, unsupported CAR versions, and unsupported alpha labels
  fail explicitly.

## Remaining alpha gaps

Implementation incomplete:

- the API consumes a complete `bytes` value and indexes it in memory; it is not
  a bounded streaming parser for large repositories.

The previously missing independent serializer witness is supplied by SA3:
the pinned TypeScript `@atproto/space.serializeRepo` emits a golden CAR that is
compared through SA2 and SA1.  That fixture does not add a running PDS or live
integration.

Upstream unspecified or unstable:

- the PR branch has already moved away from the pinned implementation;
- duplicate-block policy is not a Spaces protocol guarantee, so SA2 rejects
  all duplicates rather than assigning them meaning; and
- future CAR versions, root count/order, codecs, multihashes, index-only CARs,
  and record-block omission rules may change. SA2 fails closed instead of
  inferring compatibility.

Intentionally deferred: live fetching, service authentication, DID resolution,
credentials/OAuth, credential storage, Space membership, community standing,
governance authorization, effects, projection, and production deployment.

## Adversarial review result

Caller labels remain under unverified container context; they cannot populate
SA1 claims. No credential is modeled. CAR claims stop before cryptographic or
governance interpretation. The public verifier is untouched and unimported.
SA1's direct fixture entry remains intact. Replacing CAR framing requires
changes only in `compat.py`, `car.py`, its fixtures/tests, and this note—not in
the governance core or public observation path.

## Next smallest experiment

Add one deterministic cross-language golden CAR generated directly by the
pinned reference implementation and assert byte/block parity with CAR1. This
tests interoperability at the new boundary without adding network, OAuth, or
governance integration.
