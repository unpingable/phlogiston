# SA9e — reference/local read-only integration

Status: **qualified local reference witness and one disposable hosted-alpha
read-only smoke; campaign frozen** on 2026-08-21. This campaign uses only
synthetic identities and disposable services. It performs no production
account operation, governance action, or write outside creation of the
disposable test Space and its single synthetic record through the pinned
Bulletin sample application.

## Reference custody and execution

The implementation oracle is the exact existing compatibility pin:

- repository: `bluesky-social/atproto`;
- branch observed: `permissioned-data`;
- commit: `89deb9faca20e56fa2a262fe9746ed52bc1095ba`;
- package: `@atproto/space@0.0.1`;
- package manager: the checkout-pinned pnpm `11.11.0`;
- runtime: Node `v24.13.0`.

An isolated shallow checkout at that commit was dependency-installed and built.
Its own `packages/pds/tests/space/sync.test.ts` witness named `serves a
verifiable CAR for full-state recovery` passed against disposable PostgreSQL
and Redis containers: one test passed, 21 unrelated cases were skipped. That
test creates multiple local PDSes, mints a Space credential through the
reference delegation/authority flow, performs a real loopback HTTP `getRepo`,
and validates the CAR with `verifyRepoCarFull`.

The tracked `tests/fixtures/spaces-alpha/reference/sa9e-local-pds-generate.test.ts`
uses the same reference test infrastructure to retain one synthetic artifact.
To regenerate it, copy that file into the exact checkout's
`packages/pds/tests/space/` directory, start the checkout's disposable test DB
and Redis services, and run:

```text
SA9E_OUTPUT_DIR=<empty-output-dir> \
DB_POSTGRES_URL=postgresql://pg:password@127.0.0.1:5433/postgres \
REDIS_HOST=127.0.0.1:6380 \
NODE_OPTIONS=--experimental-vm-modules \
pnpm exec jest tests/space/sa9e-local-pds-generate.test.ts --runInBand
```

The generator retains no delegation token, Space credential, DPoP proof,
authorization header, cookie, or private key. All secret-bearing material is
confined to the disposable reference process.

## Composition result

The exercised path is:

```text
reference local PDS + authority
  -> transient delegation and Space credential
  -> authenticated loopback HTTP getRepo
  -> exact 806-byte CAR
  -> pinned @atproto/space verifyRepoCarFull
  -> unchanged local SA2 CAR extraction
  -> unchanged local SA1 qualification
  -> two bounded observation receipts
```

The retained CAR SHA-256 is
`ac8b3a16b1a3d5178d1b75515a3bd8255fa5892d6ae8e780d3d3bcc66ca5f8a3`.
Its two ordered roots are:

1. `bafyreiaipujf6ovw2aqwdakkbwvjb2hsveq3znzkpkm3cghdlaxyybzzsm`;
2. `bafyreiaq2yjwjtrk4sdw6lbsr5nenqdh3zec5hrv3ks5hyjzccx2nvmupu`.

The CAR contains the commit, index, and two record blocks in pinned canonical
order. Local SA1 independently verifies the commit structure/context, supplied
author-key signature, context MAC, LtHash state, canonical record bytes/CIDs,
record paths, author binding, and Space binding. It produces receipt IDs
`sha256:af3782c9f06ea99c928f8b74005c4ab94195296d819ed9b786a5924f8f409be2`
and
`sha256:3acdeec65604cc9d4d0d19b633bd0cc356b0ceaa286f8609e8a6be6145620d12`.

The reference verifier result and the local SA1 receipts coexist; neither is
promoted into source authority or governance authority. The recorded loopback
URL proves where this acquisition occurred. It is not a DID-qualified service
binding. The stable HTTPS fixture label supplied to SA1 remains explicitly
unverified context, and `networkSourceIdentityQualified` is false.

## Regeneration stability

Two fresh reference runs both passed and emitted the same record count,
collection/rkey order, CAR root/block shape, and qualification semantics. They
were not byte-identical (`ac8b3a…` versus `852c41…`): the reference environment
generates new PLC/account keys and DIDs, commit IKM/revisions, and loopback
ports. SA9e therefore pins one exact observation artifact while documenting
semantic, not byte, regeneration stability. No test assumes fresh PDS output is
byte deterministic.

## Guarantees and non-claims

SA9e demonstrates that the pinned reference PDS can execute its synthetic
permissioned read flow and that the bytes it serves interoperate with unchanged
SA2/SA1. The deterministic regression checks the retained digest, ordered
roots/blocks, record count, author/Space cryptographic binding, and receipt IDs.

It does not prove that the reference implementation is correct, that the
loopback host belongs to a DID, that the retained state is globally current,
that no unseen history exists, or that the credential represents Space
membership, community standing, governance authority, or effect authorization.
Credential acceptance is acquisition context; the response still requires
independent evidence qualification. A snapshot remains a snapshot, not a
transition or complete history.

Hostile regressions demonstrate that a mutated CAR is refused despite the
successful-acquisition label, a wrong-Space/governance relabel cannot override
the signed commit binding, loopback acquisition is not promoted to source
identity, and no secret-bearing field survives in the manifest.

## Alpha and replacement boundaries

The PDS APIs, credential exchange, two-root CAR shape, permissioned commit,
index, LtHash, and reference test helpers are volatile alpha behavior pinned to
the commit above. Reference build and generator churn is external tooling. The
local product boundary remains SA2/SA1 and can be replaced or updated without
changing governance semantics. Existing public ATProto verification is
unchanged.

## Quality gates

The reference checkout's focused `getRepo` integration passed, and the export
generator passed twice. The repository-local SA9e local-reference suite has
five passing tests, and the hosted replay/refusal suite adds four. The full
repository check completed with 962 passing tests,
Ruff lint and format passed, all seven Python packages produced both wheel and
sdist artifacts without build isolation, the retained artifact secret-pattern
scan was empty, and `git diff --check` passed. The first sandboxed full-suite
attempt was not a product failure: the sandbox denied all localhost socket
creation; the identical suite passed with localhost permission.

## Hosted-alpha read-only smoke

The user created the disposable hosted identity
`did:plc:ccqpqqfk4ihtbimtbomhnjle`
(`neutralautomation.spaces-alpha.bsky.network`) and, through the exact pinned
Bulletin commit, created the synthetic Space
`at://did:plc:ccqpqqfk4ihtbimtbomhnjle/space/my.bulletin.board/self` with one
synthetic text record. Creation was setup only; the qualification smoke itself
used read RPCs.

One secret-bearing OAuth session remained confined to a disposable Bulletin
SQLite database under `/tmp`. The live runner retained no access token,
refresh token, OAuth code, DPoP private key, delegation token, Space credential,
authorization header, cookie, or nonce. It independently:

1. qualified the public PLC audit with SA9c-plc;
2. selected the PDS and account/Space fallback keys with unchanged SA9b;
3. qualified the returned OAuth grant and exact nonce-bound delegation request
   with SA9d-a;
4. qualified the PDS delegation JWT and Space-authority credential with
   SA9d-b/SA9d-c;
5. constructed fresh credential-bound requests and used unchanged SA9d-d;
6. passed the returned CAR through unchanged SA10d (and therefore SA2/SA1);
7. passed the returned operation page through unchanged SA10d/SA5.

The hosted `getRepo` response was HTTP 200, content type
`application/vnd.ipld.car`, 609 bytes, SHA-256
`483c4bf1f9eb5da79f768260452ab269fb9c857db607995d313fc389ff15cb48`.
Its two ordered roots and three ordered blocks (commit, index, one record)
matched the pinned SA2 shape. SA1 qualified revision `3mtn3fop2xe25`, state
hash `1a9979c238e19924f4df2a7f11af6ffe25de6f78adcc3330f0dca3499c4b101a`,
and the one exact record/CID. SA10d established the PLC-derived host binding,
recorded the acquisition and qualified state, and produced receipt
`sha256:5fdb283bce1d327b0599f4d9018d3b4f19b3d47f4bcaf092877a6024e874b259`.
No writer-discovery/access admission tuple was supplied, so admission count was
zero.

The hosted `listRepoOps` request used `since=3mtn3fop2xe25`, `limit=100`, and
`excludeValues=true`. Its HTTP 200 body was 347 bytes, SHA-256
`f3130a273d6c651f074aab8057396201815fda2c5bc060e556ea78c76e566eae`.
It contained no operations and the terminal commit for the same revision.
Unchanged SA5 classified it `empty_terminal_page`: the cursor chain closed,
but no SA4 transition and no history-completeness claim was created.

The exact bodies are retained as base64 text because repository edits use the
auditable text patch path. Tests decode them, verify their byte digests, replay
the CAR through SA9c/SA9b/SA2/SA1, replay the operation body through SA5, and
retain hostile CAR-mutation and wrong-Space relabel refusals. The live
SA9d-d/SA10d request receipts are retained by identifier and bounded outcome;
they cannot be deterministically reconstructed after deliberately discarding
their secret-bearing runtime credentials.

### Hosted compatibility divergence

The hosted OAuth metadata advertised both ES256 and ES256K (among other
algorithms). The pinned Bulletin OAuth runtime sorts ES256K first and its first
session therefore generated a `secp256k1` DPoP key. SA9d-a is deliberately
fixture-qualified only for mandatory ES256/P-256, so it correctly refused to
pretend that session was an SA9d-a object. A disposable copy of the exact
reference client runtime was constrained to the server-advertised ES256 option,
the browser ceremony was repeated, and the resulting P-256 session entered
SA9d-a unchanged. Delegation and Space credential JWTs remained ES256K because
the disposable PLC DID's selected `#atproto` signing key is k256; existing
SA9d-b/SA9d-c already qualify that separately.

This is alpha compatibility evidence about reference-client algorithm
preference, not a reason to widen the frozen SA9d-a campaign after exposure.
It did not alter CAR, state, transition, reconciliation, recovery, admission,
or governance semantics.

At freeze time, read-only upstream-head inspection found no pin drift:

- proposal `main`: `54c9cf5153d668c4f4fb4438529967412e861775`;
- reference `permissioned-data`: `89deb9faca20e56fa2a262fe9746ed52bc1095ba`;
- Bulletin `main`: `ccca73d212167e20da56db4691ba7c94e9ad5ccc`.

The campaign is frozen after this single hosted observation. The retained
artifact is not a claim of production readiness, globally current state,
complete history, membership, standing, governance authority, or effect
authorization. Alpha churn should produce new compatibility evidence rather
than weaker deterministic qualification.

## Next smallest experiment

No further Spaces campaign is authorized by this freeze. If work resumes after
human review, the smallest useful experiment is to repeat the same read-only
artifact comparison against the user's isolated lab PDS, using another
sacrificial identity and preserving the hosted and self-hosted acquisitions as
distinct source epochs. That would test operator/host portability without
adding governance, writes to community state, or production deployment.
