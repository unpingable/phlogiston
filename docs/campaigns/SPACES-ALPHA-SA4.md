# SA4 — Spaces alpha reference multi-record transition qualification

**Status:** deterministic fixture implementation; no network, PDS, credential,
authority, or deployment. **Upstream observation date:** 2026-08-20. SA4
qualifies one bounded supplied state relationship. It is not a historical or
authorization proof.

## Architectural result

SA4 composes the existing boundaries without changing them:

```text
reference full-state CAR N ----> unchanged SA2 ----> unchanged SA1 state N
                                                           |
supplied ordered operation batch --------------------------|
                                                           v
reference full-state CAR N+1 --> unchanged SA2 --> unchanged SA1 state N+1
                                                           |
                                                           v
                                      bounded SA4 transition receipt
```

`qualify_repo_transition()` accepts an existing `QualifiedRepoState` and target
`SpaceRepoEvidence` carrying SA1's existing `RepoTransition`. It requires the
supplied prior revision, exact 2048-byte LtHash state, and path/CID index to
equal the qualified source. It then calls unchanged `qualify_repo_state()` for
the target. SA1 applies operations in supplied order, checks every `prev`
against the staged index, recomputes index and LtHash evolution, and requires
the result to equal the independently qualified target.

Only then does SA4 emit `SpaceTransitionReceipt`. Its identifier binds:

- source and target Space, author, revision, repository hash, commit/index
  block CIDs, record-index digest, and all SA1 receipt IDs;
- each operation's original ordinal, kind, revision, path, prior CID, and
  resulting CID;
- the fixed alpha assumption, SA4 method/version, verified claims, and
  verification time.

SA4 never sorts operations. A `QualifiedSpaceTransition` validates that its
source and target still match the receipt. Snapshot qualification remains the
ordinary SA1 route and requires no SA4 evidence.

## Pinned reference behavior

The reference oracle remains `@atproto/space` version `0.0.1` at
`bluesky-social/atproto` commit
`89deb9faca20e56fa2a262fe9746ed52bc1095ba`. At that commit:

- `RepoOp` uses `prev: null` for create, `cid: null` for delete, and both CIDs
  for update;
- `RepoCommit.applyOps()` removes `prev` and adds `cid` in supplied order;
- LtHash set accumulation converges for independent operations regardless of
  order; and
- `serializeRepo()` emits only a full commit/index/record CAR. It does not put
  the operation batch or parent ancestry in that CAR.

The reference generator therefore checks two distinct things: each stored
state serializes to the expected CAR, and replaying the separately supplied
operation batch from the stored prior LtHash state matches the target commit.
The local verifier adds the stricter staged-index `prev` checks already present
in SA1. The reference implementation remains a compatibility oracle, not a
source of authority.

## Reference artifacts and reproducibility

The source contains two records at N, three at N+1, and three at N+2:

```text
N:    alpha-v1, beta-v1
N+1:  alpha-v1, beta-v1, gamma-v1
N+2:  alpha-v1, beta-v2, delta-v1
```

The batches are:

```text
N -> N+1:   add gamma
N+1 -> N+2: add delta, update beta, remove gamma
```

Artifact pins:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `sa4-n.car` | 764 | `c564c3ff8a4663014e6100d26a78ce4ba5f60da01799c2b09a307e8febd1ac9e` |
| `sa4-n1.car` | 954 | `aec612cf702f6cd39cf84b635017772d57cbca08ad132107664d40b92d9711dd` |
| `sa4-n2.car` | 954 | `28b912b64e1b9c98b78d06ac04c60517cc28c9de0d44a9f64214632a78a4fb73` |

Additional pins:

- generator SHA-256:
  `fc0132528f7f880b33cced1401c25c1862a7c22c3f1ed5452169d02b9056aeef`;
- source-vector SHA-256:
  `554e2b6bdda9258235c8dab5f2371aea505d4e1ed1593ed90a189d13324041a9`;
- manifest SHA-256:
  `e9a7725c0242cae1955f32f3b34ab9a7b7f39a80d12d1bc35691c08823c28f43`;
- ordered-operation digests: N→N+1
  `a027289630c37737eacb3b81b83b2806d5a83d410032a571ef070f1fd96f43c9`
  and N+1→N+2
  `9b128157d538a6103b04ac3304b5772d2cefce13c89b5086ce325807cc928fc7`;
- transition receipt IDs: N→N+1
  `sha256:55a0adf0522c47333b174c0071f8dc7a99f5239182c5ccbdc810760a7c92337f`
  and N+1→N+2
  `sha256:6bd6827ac83a780f0ea852ba08da80e5a293a381366a56d362eca8d1f952e526`.

Reproduction uses Node `v24.13.0`, pnpm `11.11.0`, and the built pinned
workspace dependency closure:

```text
corepack pnpm install --filter @atproto/space... --frozen-lockfile
corepack pnpm --filter @atproto/space... build
node tests/fixtures/spaces-alpha/reference/sa4-generate.mjs \
  <pinned-atproto-worktree> \
  tests/fixtures/spaces-alpha/sa4-source.json \
  tests/fixtures/spaces-alpha/reference \
  tests/fixtures/spaces-alpha/sa4-transition.json
```

Each serializer is invoked twice and must be byte-identical. A separate full
generator invocation produced byte-identical CARs and manifest.

The stored commits were initially produced with the pinned reference
`RepoCommit.sign()` and a disposable synthetic Secp256k1 key that existed only
in generator process memory. The private bytes were neither exported nor
retained. Upstream signing intentionally uses fresh random IKM; recreating
those signed commit bytes is therefore not deterministic. Reproducibility
begins at the committed synthetic source blocks, just as SA3 begins with SA1's
committed signed input. This limitation is explicit rather than hidden by
retaining signing material.

## What SA4 proves

A valid SA4 receipt proves, against the supplied evidence:

- both endpoint states independently passed SA1 qualification;
- the supplied prior revision, index, and LtHash state are exactly the source
  state named in the receipt;
- the exact ordered create/update/delete effects were applied with valid
  staged `prev` relationships;
- the resulting index and LtHash state equal the independently qualified target;
- reference `RepoCommit.applyOps()` reaches the same target accumulator for the
  golden batches; and
- SA2/reference CAR roots, blocks, bytes, and ordering match the pinned
  manifests for all three endpoint states.

This is the equation “qualified N + supplied supported batch = qualified
N+1.” It is deliberately no stronger.

## What SA4 does not prove

The alpha commit has no parent field and the operation log is not committed or
signed ancestry. Consequently SA4 does not prove uninterrupted or complete
history, that these are the only possible intervening operations, that no
external state was unseen, or that a revision is the immediate successor in a
global history. A direct N→N+2 relationship could be qualified only if a
supplied batch actually begins at N and produces N+2; even then it would remain
one bounded relationship, not completeness.

SA4 also does not prove user intent, actor legitimacy, key-to-DID status beyond
SA1's supplied-key boundary, Space access, membership, standing, admission,
permission to write, governance legitimacy, authorization, or effect
execution. Receipt provenance fixes `completeHistory`, `signedAncestry`,
`operationLogAuthenticated`, `actorLegitimacy`, `authorization`, and
`governanceAuthority` to `false`.

## Positive and hostile witnesses

Positive tests establish:

- T1 N→N+1 adds gamma to a two-record state and matches the final index/state;
- T2 beta's old and new CIDs differ and the update reaches the qualified target;
- T3 the mixed add/update/remove batch succeeds with exact input ordering; and
- T4 N→N+1 and N+1→N+2 qualify independently, with the first target identity
  exactly equal to the second source identity.

Refusal and boundary tests establish:

- T-H1 a valid final state with a mismatched prior accumulator is refused;
- T-H2 N→N+2 using only the N+1→N+2 batch is refused, while N+2 remains a valid
  snapshot without a transition claim;
- T-H3 reordering independent operations is explicitly demonstrated to reach
  the same target; SA4 preserves both supplied orders and gives them different
  receipt IDs rather than silently sorting;
- T-H4 a mutated operation with unchanged target metadata is refused;
- T-H5 final-state-only evidence may qualify through SA1 but cannot produce an
  SA4 transition receipt;
- T-H6 a final index/LtHash mismatch is refused by unchanged SA1;
- T-H7 the same artifacts under another Space context fail cryptographic
  binding; and
- T-H8 receipt relabeling as complete history, signed/authenticated history,
  actor legitimacy, authorization, or governance authority is refused.

## Alpha limitations

Implementation incomplete:

- SA4 requires receipt-bearing nonempty states; an empty-repository endpoint
  has no per-record SA1 receipt and needs a separate state-level qualification
  design;
- one add batch and one independent-path mixed batch are covered; same-path
  multi-operation chains are only covered by earlier SA1 logic; and
- the operation fixture is already structured. No `listRepoOps` response or
  pagination adapter exists.

Upstream unspecified or unstable:

- operation logs are mutable service output rather than signed history;
- revision identifiers are ordered but expose no cryptographically established
  immediate-successor relationship;
- operation pagination, retention, duplicate delivery, and recovery behavior
  remain alpha service concerns; and
- commit, index, CAR, operation, and LtHash shapes may change after the pin.

Intentionally deferred: live PDS/network access, service authentication,
credential/OAuth handling, DID resolution, membership, standing, governance,
authorization, effects, projection, historical storage, and deployment.

## Adversarial review result

Final-state qualification remains SA1 snapshot evidence unless an explicit
source and operation batch also pass SA4. Transition validity never becomes
authority. No operation sorting occurs. SA1 and SA2 are unchanged. Every SA4
claim is bound into a dedicated receipt, while all historical and authority
non-claims are fixed false. Alpha-specific methods and pins remain inside the
separate Spaces package compatibility boundary and replaceable fixture tools.

## Next smallest experiment

Add a deterministic pinned `com.atproto.space.listRepoOps` response fixture and
a narrow pagination/order adapter that produces the existing `RepoTransition`
input. Keep SA4, SA1, and governance semantics unchanged.
