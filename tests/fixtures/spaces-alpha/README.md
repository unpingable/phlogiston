# Spaces alpha deterministic fixture

`campaign.json` is the SA0 source fixture.  It contains only invented DIDs,
`.invalid` hosts, non-canonical `invalid.test.*` NSIDs, and public test text.
It must never contain an OAuth token, delegation token, Space credential, DPoP
private key, cookie, authorization header, invite code, or private user content.
SA9d-a may retain a synthetic public DPoP JWK and proof digest, never a secret
scalar or raw proof-bearing request header.

The record CIDs are real DAG-CBOR CIDs recomputed by the tests.  The commit
hashes and `fixture` verification claims model outputs from the still-missing
Spaces commit-verifier adapter; they are deterministic witness values, not live
LtHash/MAC/signature proofs.  Changing record values requires regenerating and
reviewing their CIDs.  Changing an alpha shape requires updating the pins and
compatibility analysis in `docs/campaigns/SPACES-ALPHA-SA0.md`.

`sa1-qualification.json` is the SA1 cryptographic vector set.  Unlike the SA0
placeholder hashes, its commit blocks, canonical DAG-CBOR index and records,
record CIDs, BLAKE3-XOF LtHash states, HKDF-expand/HMAC values, and compact
low-S ES256K signatures are internally consistent.  A fixed test public key is
included; the private scalar used once to generate the static vector is not a
credential and is not retained in the fixture or product package.  The vector
also carries C1–C8 mutation material and uses only the same invented identities,
hosts, and `invalid.test.*` namespace.

The SA1 vector is a deterministic protocol witness, not a hosted-alpha
transcript.  Its `authorKeyBindingMethod` is deliberately unverified fixture
context: the verifier checks the signature against the supplied public key but
does not resolve a DID document or turn that key reference into ecosystem-wide
identity.  Regeneration requires rechecking the BLAKE3/LtHash snapshot against
the pinned reference code and updating `docs/campaigns/SPACES-ALPHA-SA1.md`.

`sa2-car.json` wraps the SA1 initial-state blocks in deterministic raw CARv1
framing.  It pins two roots in commit/index order, DAG-CBOR/SHA-256 CIDs, and
the upstream block order, plus CAR-H1–CAR-H8 hostile containers.  The public
CAR witness is copied from this repository's inert
`mst-empty-intermediate/submit.car` fixture solely to prove that SA2 refuses
public one-root CAR material; it is not accepted through a fallback.  No SA2
container result is an observation receipt.  Regeneration requires preserving
byte-for-byte equivalence with the SA1 blocks and rechecking the reference pin
recorded in `docs/campaigns/SPACES-ALPHA-SA2.md`.

`reference/sa3-golden.car` is the raw CAR emitted by the pinned
`@atproto/space.serializeRepo` implementation at commit
`89deb9faca20e56fa2a262fe9746ed52bc1095ba`.  `sa3-reference.json` records its
SHA-256 digest, reference root/block interpretation, generator identity and
command, and expected unchanged SA1 receipt.  The tracked
`reference/sa3-generate.mjs` driver passes only the existing synthetic SA1
commit and record bytes to that serializer; it verifies the reference checkout
pin and emits two copies to demonstrate byte stability.  The manifest's base64
copy is checked against the raw file.  Regeneration requires the exact pinned
reference checkout and its built `@atproto/space` dependency closure; no key,
credential, account, or hosted service is involved.

`sa4-source.json` contains three consecutive synthetic multi-record repository
states and two ordered operation batches: an add, then a mixed add/update/delete
batch. The signed commits were created once with the pinned reference
`RepoCommit.sign()` and a disposable synthetic key generated only in process
memory; only the public key and signed fixture bytes remain. Upstream signing
uses fresh random IKM, so those signed commit bytes are fixed source inputs, not
a byte-reproducible signing vector.

`reference/sa4-{n,n1,n2}.car` and `sa4-transition.json` are reproducible from
that source with `reference/sa4-generate.mjs`. The generator verifies its Git
pin, serializes every state twice, records roots/block order/hashes, and uses
the pinned `RepoCommit.applyOps()` to check both supplied operation batches
against their target commits. The operation log is not inside the CAR and is
not signed ancestry. No fixture stores signing material, OAuth/token data,
credential data, accounts, or private user content.

`sa5-list-repo-ops.json` wraps the existing SA4 operation batches in the exact
pinned `com.atproto.space.listRepoOps` JSON response shape. It includes a
single terminal page, a three-page cursor chain, and an empty terminal page.
The signed-commit JSON is response context copied from existing public fixture
bytes; SA5 stores only its deterministic digest and does not verify it. Cursor
closure is not history completeness.

`sa6-reconciliation.json` names expected bounded classifications over existing
SA4 qualified states. It contains no new record or cryptographic material and
has no `history_verified` outcome. SA7 adds no fixture payload of its own: its
interface tests hand the existing SA4 CAR and SA5 response pages unchanged to
their established adapters.

`sa8-recovery.json` names the deterministic recovery decision witnesses over
the existing SA4 CAR states and SA5 operation responses. It adds no wire data,
keys, or cryptographic material. Positive cases select either the exact SA4
transition path or the independent SA2/SA1 snapshot path; hostile cases retain
stale/conflicting/refused evidence without inventing history. The manifest pins
the recovery method, version, compatibility commit, and doctrine recorded in
`docs/campaigns/SPACES-ALPHA-SA8.md`.

`sa9a-http.json` pins the read-only HTTP acquisition method, replacement
boundary, redirect/retry/content transformation policies, and HTTP1–HTTP4,
E2E1–E2E3, and HTTP-H1–HTTP-H12 witness names. It contains no network payload:
real loopback servers return the existing SA4 CAR and SA5 response fixtures.
Only synthetic `.invalid` identities and source context are used. The test
server injects synthetic secret-looking headers solely to prove that values are
not retained; none are written to fixture manifests or product provenance.

`sa9b-did-binding.json` pins bounded DID-document interpretation against the
ATProto DID specification observed on 2026-08-21 and the exact Spaces proposal
commit already used by this campaign. It contains synthetic `did:plc`
identifiers, `.invalid.test` service origins, and public multikey examples only.
The fixture exercises ordinary PDS selection, a dedicated Space host and key,
and explicit fallback to the account PDS and account key. The document bytes
are deterministically encoded by the test helper before hashing. Neither the
fixture nor a resulting receipt is DID-method resolution evidence; no private
key, credential, token, account, or hosted resolver material is present.

`reference/sa9c-plc-reference.json` is a static synthetic corpus emitted by
`@did-plc/lib@0.1.0` at commit
`2ed82a5ccf1b424aa5e2f6c5b461dc0ee133278b`. It covers modern genesis and
updates, rotation-key replacement, P-256 authority, higher-priority recovery
with retained nullified operations, a tombstone, legacy genesis, and hostile
valid signatures from ineligible keys. Only signed operations and public keys
remain; the disposable generation scalars are not retained. The tracked
`reference/sa9c-plc-verify.mjs` checks the exact reference commit, operation
CIDs, method decisions, nullification flags, and rendered documents. Its
fixture SHA-256 is
`8a45e23e5c59164d1b84f78ec6c3dfecb38e4bb2a4ff0927d1b8aa4ef280a32a`.
SA9c-web adds no stored identity data: real loopback tests generate ephemeral
synthetic `did:web` documents in process and mark them as development
acquisitions rather than WebPKI evidence.

`sa9d-a-oauth-dpop.json` pins only public/digested outputs from a deterministic
fixture-only ES256 DPoP request. The access token is derived transiently in test
memory and only its SHA-256/`ath` values are retained; the P-256 scalar is
derived transiently from a plainly synthetic test seed and only its public JWK
and thumbprint are retained. The manifest contains no authorization header,
token plaintext, private scalar, refresh token, code, verifier, or cookie.

`sa9d-b-delegation.json` pins only public identifiers and digests from a
deterministic fixture-only delegation qualification. The compact delegation
JWT, synthetic OAuth token, account-signing scalar, and DPoP scalar exist only
in test memory. The manifest binds the exact user, Space, logical Space-host
audience, time window, token digest, and independent SA9c/SA9b/SA9d-a receipt
identities. It is neither a reusable credential nor a Space admission record.

`sa9d-c-credential.json` pins public identifiers and digests from a
deterministic fixture-only Space-credential qualification. The compact
credential, authority-signing scalar, and credential-specific DPoP scalar
exist only in test memory. The manifest records the exact Space, authority,
delegation context, `cnf.jkt`, key/host receipt identities, and whole-Space
read/sync semantics. It contains no credential plaintext and confers no
membership, standing, governance authority, or write permission.

`sa9d-d-authenticated-acquisition.json` pins the fixture-only composition
between an already qualified credential, a fresh credential-bound DPoP request,
and the unchanged SA7 artifact-provider seam. It retains no credential, proof,
token, nonce, or private key. Distinct nonce attempts remain distinct
acquisition events and cannot change downstream SA2–SA8 semantics.

`reference/sa9e-local-pds.car` was acquired from a real loopback PDS started
from the pinned ATProto reference commit. The reference test created two
synthetic PLC accounts, one synthetic Space, two records, exchanged a transient
delegation token for a transient Space credential, performed an authenticated
`com.atproto.space.getRepo` GET, and verified the resulting CAR with the pinned
`@atproto/space` verifier. `reference/sa9e-local-pds.json` retains the exact CAR
digest, public author key, synthetic identities, reference repo state, and the
unchanged local SA2/SA1 receipt IDs. It retains no token, credential, private
key, cookie, or authorization header. The loopback URL is acquisition context,
not qualified network-source identity. The tracked
`reference/sa9e-local-pds-generate.test.ts` is the reproducible reference-PDS
test; fresh runs are semantically reproducible but not byte-identical because
the reference test generates fresh PLC identities, repo keys, commit IKM, revs,
and loopback ports.

`reference/sa9e-hosted-alpha-get-repo.car.b64` and
`reference/sa9e-hosted-alpha-list-repo-ops.json.b64` retain one disposable,
read-only hosted-alpha acquisition as auditable base64 text. The accompanying
`reference/sa9e-hosted-alpha.json` binds their exact byte digests, public PLC
operation, bounded identity/authentication/acquisition receipt identifiers,
and unchanged SA1/SA5/SA10d outcomes. It contains no access token, refresh
token, DPoP private key, delegation token, Space credential, cookie, or
authorization header. Hosted success remains one acquisition observation, not
currentness, complete history, admission, standing, or governance authority.
