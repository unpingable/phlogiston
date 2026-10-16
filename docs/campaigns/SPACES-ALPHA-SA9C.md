# SA9c — DID resolution provenance qualification

Status: fixture/reference qualified on 2026-08-21. SA9c is an observer-only
compatibility campaign authorized by `BUILD.md`.

> **DID methods establish provenance differently; common output must not erase
> those differences.**

> **Resolution provenance is not governance authority.**

## Architecture

```text
did:web + bounded HTTPS/WebPKI observation ─┐
                                            ├─ exact bytes + method receipt ─→ SA9b
did:plc + qualified operation evidence ─────┘
```

`ResolvedDidDocument` is the only shared seam. It binds the expected DID,
exact document bytes and SHA-256 digest to a method enum, method-specific
receipt ID, provenance class, observation time, claims, and non-claims. A
`did:web` result cannot be relabeled as PLC-chain evidence, or vice versa.
`to_sa9b_input()` passes the same byte object and method receipt ID into SA9b;
SA9b's service-selection behavior is unchanged.

## Claim matrix

| Claim | SA9c-web | SA9c-plc |
| --- | --- | --- |
| Method syntax/profile | hostname-level ATProto profile | 24-character PLC identifier |
| Exact document bytes/digest | acquired body | deterministically rendered state |
| HTTPS/WebPKI hostname acquisition | production HTTPS result only | no |
| Genesis-derived identifier | no | yes |
| Operation CID/`prev` evidence | no | yes |
| Rotation-key signatures | no | yes, k256 and P-256 |
| Recovery/nullification | no | bounded by supplied audit and directory times |
| Historical continuity | no | only the qualified active/nullified relationships supplied |
| Proof no newer state exists | no | no |
| Governance authority | no | no |

The loopback `did:web` test profile emits a distinct development provenance and
never emits the WebPKI claim.

## Pins and replacement boundary

- ATProto DID specification, observed 2026-08-21:
  `https://atproto.com/specs/did`
- did:web method specification, observed 2026-08-21:
  `https://w3c-ccg.github.io/did-method-web/`
- DID PLC specification v0.3.0 and reference checkout:
  `did-method-plc/did-method-plc@2ed82a5ccf1b424aa5e2f6c5b461dc0ee133278b`

Method churn is isolated to `did_web.py`, `did_plc.py`, and SA9c constants in
`compat.py`. SA9b consumes exact bytes and a provenance reference; SA9a and
SA0–SA8 are unchanged. A future blessed DID method must add another distinct
qualifier rather than widening either receipt.

## Non-claims and deferred work

SA9c does not establish remote artifact validity, service control at another
time, durable currentness, complete external history, actor intent, access,
standing, authorization, or governance authority. It does not implement live
PLC directory acquisition, OAuth, DPoP, Space credentials, authenticated
Spaces reads, synchronization, writes, or deployment.
