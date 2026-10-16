# SA9c-plc — DID PLC operation-history qualification

Status: deterministic/reference qualified against PLC v0.3.0 on 2026-08-21.

## Guarantee

Given bounded audit evidence, SA9c-plc checks canonical DAG-CBOR and recomputes
every operation CID; derives the DID from the exact signed genesis operation;
verifies compact low-S SHA-256 ECDSA signatures for k256 and P-256 rotation
keys; distinguishes rotation authority from ordinary `verificationMethods`;
constructs ancestry from `prev` CIDs rather than array order; applies ordered
rotation priority and the pinned recovery rule; checks supplied nullification
flags; and derives either deterministic exact DID-document bytes or an active
deactivated tombstone state.

The receipt retains supplied operation order, directory timestamps, signer and
curve per operation, active CIDs, nullified CIDs, recovery use, legacy use,
P-256 use, and the exact output digest. Nullified branch evidence is not erased.

## Reference corpus and replay

The synthetic corpus was emitted with
`@did-plc/lib@0.1.0` at
`did-method-plc/did-method-plc@2ed82a5ccf1b424aa5e2f6c5b461dc0ee133278b`.
It contains no private keys, credentials, accounts, or user data. Fixture
SHA-256:

```text
8a45e23e5c59164d1b84f78ec6c3dfecb38e4bb2a4ff0927d1b8aa4ef280a32a
```

Verifier-driver SHA-256:

```text
1b44dbaa61415cd66f83e0f4c35517a16f698adc9242fc4327562a4672707ebc
```

The pinned reference replay is:

```text
node tests/fixtures/spaces-alpha/reference/sa9c-plc-verify.mjs \
  <pinned-did-method-plc-worktree> \
  tests/fixtures/spaces-alpha/reference/sa9c-plc-reference.json
```

It independently rechecks canonical operations, CIDs, creation, update,
recovery/nullification, tombstone/legacy normalization, and rendered-document
semantics. The local Python qualifier separately derives the same outcomes.

## Recovery semantics and limits

An ordinary update must extend the active tip and be signed by a rotation key
authorized by its parent. A recovery may fork from an active ancestor only when
its signer has strictly higher priority than the signer of the first nullified
operation and the directory-time interval is at most 72 hours. A lower-priority
inversion, late recovery, missing parent, nullification mismatch, or tombstone
bypass refuses.

The 72-hour inputs are directory-supplied context. They are not signed by the
DID controller. This implementation can say the supplied evidence satisfies
the method rule under those supplied times; it cannot independently prove the
directory was honest about time or ordering. Nor can supplied audit evidence
prove that no newer valid operation exists elsewhere.

## Legacy status

Legacy `create` genesis operations are supported, their DID is derived from the
original signed legacy bytes, and their state is explicitly normalized under
the pinned reference semantics. This is not a fail-open compatibility shim.

## Non-claims and replacement boundary

PLC qualification is not trust in `plc.directory` current-document JSON. A
disagreeing summary is reported as disagreement and cannot override qualified
history. The result does not prove complete history, durable currentness,
directory honesty, actor intent, service control, access, standing,
authorization, or governance authority.

PLC-specific schemas, crypto selection, recovery, and rendering are isolated in
`did_plc.py`; v0.3.0 pins live in `compat.py`. SA9b receives exact bytes and the
PLC receipt ID without acquiring PLC semantics of its own.
