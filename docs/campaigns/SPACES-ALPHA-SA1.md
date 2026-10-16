# SA1 — Spaces alpha cryptographic observation qualification

**Status:** deterministic fixture implementation; no live fetch, credentials,
or deployment. **Upstream observation date:** 2026-08-20. This is a bounded
implementation of volatile alpha behavior, not a stable AT Protocol
specification or a governance authority system.

## Architectural result

SA1 extends, and does not redesign, the SA0 package boundary:

```text
Space authority writer discovery (unverified discovery testimony)
        |
direct repo-host blocks (source metadata remains explicit)
        |
Spaces-alpha cryptographic qualification
        |
per-record bounded observation receipt
        |
existing SpaceObservation / EvidenceAdmission
        |
existing governance boundary (unchanged)
```

`communitywatch_spaces_alpha.qualification` parses the pinned permissioned
commit and DRISL-style DAG-CBOR index blocks, verifies record blocks, and emits
immutable receipts. `communitywatch_spaces_alpha.crypto` contains only
verification primitives: the constrained BLAKE3-XOF/LtHash implementation,
HKDF-expand/HMAC calculation, and ES256K verification. It has no key generation
or signing function. The existing public CAR/MST verifier is neither imported
nor used as a fallback. `communityd`, the public observer, projections,
submission flow, and governed effect path are unchanged.

SA0's visibly test-only `fixture` adapter mode remains available to its original
campaign tests. In `verified` mode, claim strings alone are no longer enough:
the observer requires matching SA1 receipt identifiers and checks each receipt
against the snapshot's Space, author, repo state, record, verifier version, and
source context before observation/admission.

## Pinned alpha compatibility boundary

SA1 retains the SA0 pins:

- [proposal 0016](https://github.com/bluesky-social/proposals/tree/54c9cf5153d668c4f4fb4438529967412e861775/0016-permissioned-data)
  at `54c9cf5153d668c4f4fb4438529967412e861775`;
- [reference implementation PR](https://github.com/bluesky-social/atproto/pull/5187)
  at head `89deb9faca20e56fa2a262fe9746ed52bc1095ba`;
- [Bulletin](https://github.com/bluesky-social/bulletin/tree/ccca73d212167e20da56db4691ba7c94e9ad5ccc)
  at `ccca73d212167e20da56db4691ba7c94e9ad5ccc`; and
- the [2026-08-20 announcement](https://atproto.com/blog/atproto-spaces-alpha).

Volatile constants remain in `compat.py`: commit version `1`, context tag
`atproto-space-v1`, 2048-byte LtHash state, proof/vector identifiers, verifier
method/version, and the currently supported signature subset (`ES256K`). An
unknown commit version, alpha label, proof kind, or signature algorithm fails
with an explicit compatibility error.

## Exact verified claim

For each record receipt, SA1 establishes against the supplied bytes and public
key that:

- the signed commit is canonical DAG-CBOR with exactly the alpha-v1 fields and
  valid field sizes/revision syntax;
- the context bytes contain the expected canonical Space URI, expected author
  DID text, commit revision, and commit IKM with the specified big-endian
  length prefixes;
- a compact low-S ES256K signature over SHA-256 of that context verifies
  against the **supplied** public key;
- the no-extract HKDF-SHA256-expand/HMAC-SHA256 value binds that context to the
  commit's 32-byte repository hash under the alpha construction;
- every canonical index path/CID contributes
  `{collection}/{rkey}/{record_cid}` to the 1024-lane, little-endian uint16
  LtHash state, whose SHA-256 digest equals the commit hash;
- each record block occurs in canonical index order, its path and CID equal the
  index entry, its exact bytes hash to that DAG-CBOR CID, and its bytes decode as
  one canonical DAG-CBOR map; and
- the receipt's author and Space equal the values in the verified signed
  context, yielding the canonical alpha Space record URI.

For the advanced vector, SA1 additionally proves that the supplied prior index
recomputes to the supplied prior LtHash state and that one final-revision
operation batch transforms both into the verified current index/state. The
alpha commit has no parent field. The receipt therefore says
`state_transition_from_supplied_prior`; it does **not** claim signed ancestry or
an archival commit chain.

The receipt records protocol/method versions, source-vector ID, verification
time, commit/index/context/key fingerprints, exact structured claims, and the
record/repo identities. Its identifier binds both verified inputs and explicitly
unverified acquisition context. No generic `verified=true` field exists.

## Explicitly unverified context and non-claims

The repo host, author-key reference, key-binding method, evidence reference,
and writer-discovery reference are retained under `unverifiedContext`. SA1
checks their consistency with the SA0 snapshot but does not cryptographically
promote them. In particular, SA1 does not resolve the author DID document. Its
signature claim is exactly “this context verified against this supplied public
key,” while the key-to-DID binding remains an upstream/caller fact requiring a
later resolver boundary.

The Space authority's `listRepos` testimony is not an input to the LtHash proof
and is not a verified receipt claim. A matching writer claim may route the
existing observer to a repo, but only fetched repo evidence produces the
receipt. Likewise, a receipt does not prove:

- Space access, credential validity, membership, community standing, or
  governance authority;
- admission under every policy, per-occurrence effect authorization, or effect
  execution;
- that the source host served the blocks, service authentication, or freshness
  beyond the observer's locally established head;
- global account status, ecosystem-wide key identity, or Space-authority
  endorsement of a repo's contents;
- public CAR/MST validity, relay visibility, public archival equivalence, or a
  durable third-party authorship proof.

The last limit is fundamental to the current alpha construction: the IKM is
present in the commit, so a holder can calculate a MAC for another state hash.
The author signature covers context, not repository contents. SA1 verifies the
sync-time construction without marketing the retained receipt as a public,
non-deniable proof.

## Deterministic and hostile witnesses

`tests/fixtures/spaces-alpha/sa1-qualification.json` contains an initial repo,
an advancing repo plus supplied state transition, and mutation inputs. Tests
demonstrate:

- C1 altered record bytes fail the claimed record CID;
- C2 CID-valid bytes with malformed/non-canonical DAG-CBOR fail content
  parsing;
- C3 an added index entry with an unchanged commit accumulator fails LtHash;
- C4 the valid commit fails under another Space context;
- C5 the valid commit fails under another author context;
- C6 an altered supplied prior accumulator fails the state relationship;
- C7 commit version `2` fails with an alpha compatibility reason; and
- C8 public CAR/MST-shaped material is refused before commit parsing and cannot
  be upgraded into a Spaces observation.

Additional witnesses refuse a substituted author public key and refuse a
hand-constructed `verified` adapter claim that has no qualification receipts.
The BLAKE3 empty hash and the reference implementation's LtHash `one`/`two`
snapshot are locked as cross-implementation checks.

## Alpha uncertainty and intentional deferrals

Implementation limits in SA1:

- input blocks are already separated by the fixture boundary; SA1 does not yet
  parse CAR framing or verify the two root CIDs/block order from raw CAR bytes;
- only ES256K is implemented; the upstream crypto layer can also encounter
  P-256 account keys;
- no DID resolver establishes that the supplied public key was the author's
  current key at an independently established time; and
- the transition verifier intentionally supports one atomic final-revision
  operation batch, not paginated/multi-revision `listRepoOps` recovery.

Upstream-unspecified or weak properties:

- commits do not contain a parent link and operation logs are not committed
  history, so no signed ancestry proof exists in this format;
- deniable MAC/signature semantics do not yield public archival proof;
- the proposal/reference remain alpha inputs without production security
  review or stability guarantees; and
- durable evidence retention after access loss/Space deletion remains a policy
  question outside cryptographic qualification.

Intentionally deferred: live network fetch, service authentication, credential
or OAuth flows, hosted/local PDS integration, membership, moderation,
governance standing/authorization, effect writers, and public projection.

## OQ-1 impact

SA1 uses only `invalid.test.*` fixture NSIDs and does not select or publish a
Space type. It does not reopen the decided V0 namespace choice. The unresolved
S1 publication gap still matters more for a future Space type because that NSID
would also be an OAuth consent/default-collection boundary. Cryptographic
qualification supplies no authority to perform that publication or freeze its
semantics.

## Next smallest experiment

Add one deterministic, reference-generated full `getRepo` CAR vector and a
streaming Spaces CAR framing adapter that verifies exactly two ordered roots
(commit, index) plus indexed record block order before calling this unchanged
qualification core. This closes the largest remaining serialization gap without
introducing network credentials or production deployment.
