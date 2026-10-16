# SA8 — Spaces alpha recovery decision qualification

**Status:** deterministic fixture-only orchestration over SA2–SA7; no network,
scheduler, retry queue, persistence, credential, authentication, writer,
governance, effect, or deployment behavior. **Upstream observation date:**
2026-08-21.

## Doctrine

> **Recovery can restore observability. It cannot manufacture missing
> provenance.**

SA8 records why one existing evidence path was selected. It never decides that
weak evidence is sufficient and does not duplicate the qualification logic in
SA1, SA2, SA4, SA5, or SA6.

```text
SA5 operation acquisition
        |
        +-- complete candidate --> SA2 CAR handoff + SA4 --> SA6
        |
        `-- partial / empty / unavailable
                              --> SA2 --> SA1 --> SA6
```

A complete SA5 candidate is tried only through SA4 using the target blocks
extracted by SA2. If SA4 refuses the candidate, the refusal remains in the
trace; the same CAR may then be qualified independently by SA1 as a snapshot.
A successful snapshot cannot overwrite the failed transition result.

## Decision model and guarantees

`RecoveryDecisionTrace` binds the known and observed state identities, their
exact SA1 receipt IDs, a local fingerprint of the complete supplied SA5 result,
its status and ordered-operation digest, the reason operation evidence was
unavailable, SA4 attempt and refusal status, SA7 request and source context,
supplied and SA2 CAR digests, any exact SA4 receipt ID, the SA6 disposition, and
the recovery method/version. The SA5 fingerprint binds page/cursor/order/source
details without authenticating them. The trace also enumerates which
transition provenance remains missing.

The exact path table is:

| Acquisition and qualification | SA4 action | Result |
| --- | --- | --- |
| SA5 complete + SA4 valid | qualify exact candidate | `qualified_transition` |
| SA5 complete + SA4 refused + valid later snapshot | preserve refusal; independently run SA1/SA6 | `snapshot_only` |
| SA5 partial/empty/unavailable + valid later snapshot | skip | `snapshot_only` |
| SA5 partial/empty/unavailable + equal snapshot | skip | `equal_state` |
| valid stale or same-revision conflicting snapshot | skip/refused as applicable | `insufficient_evidence` |
| source binding, SA2, or SA1 failure | not reached/refused as applicable | `hard_refusal` |

SA8 therefore proves only that the recorded acquisition outcome selected the
recorded existing qualification path and that the resulting trace faithfully
preserves the receipts and classifications produced by those layers.

Recovery source continuity is conservative in this bounded campaign. The SA7
request Space/author, SA5 Space/author/repo host when present, SA1 source
context, SA7 source endpoint, and repo host recorded in the known SA1 receipts
must agree. Host migration requires a future explicit source-binding
qualification; an unverified replacement endpoint is not accepted here.

## Non-claims

SA8 does not prove complete history, canonical truth among conflicting states,
authenticated ancestry, user intent, wall-clock currentness, access,
membership, standing, authorization, governance legitimacy, or permission to
write. An acquisition timestamp is provenance only. A greater revision can
support SA6's `snapshot_only` classification but is not immediate-ancestry
proof. Repetition does not upgrade a snapshot into a transition or resolve a
conflict.

Caller assertions in SA7 transport context remain unverified. Trace fields for
canonical truth, complete history, authenticated ancestry, currentness,
standing, authorization, and governance authority are fixed to `false` and
relabeling is rejected.

## Alpha assumptions and pins

SA8 inherits the isolated compatibility assumptions recorded by SA1–SA7 and
pins `bluesky-social/atproto` commit
`89deb9faca20e56fa2a262fe9746ed52bc1095ba`. Its method is
`sa5-path-selection+sa4-or-sa2-sa1-sa6`, version `sa8-v1`, and fixture format
`spaces-alpha-sa8-recovery-vector-v1`. No new alpha wire shape or cryptographic
semantic is introduced.

The pinned alpha does not provide a complete-history commitment or a canonical
resolution rule for deniable same-revision conflicts. SA8 preserves those
limitations as `snapshot_only` or `insufficient_evidence` rather than adding a
local truth rule.

## Empty repository status

Empty qualified repositories remain deferred. SA8's bounded fixtures all use
the existing per-record SA1/SA4 receipt model, so correctness does not require a
fake record or a new state-level receipt. Recovery of an empty repository must
stop before SA1 until a separately authorized state-level empty-repository
qualification exists.

## Replacement boundary

`recovery.py` is the orchestration boundary. A future provider may populate the
unchanged SA7 artifact types, and alpha framing or oplog changes may remain in
SA2/SA5 compatibility code. Neither change requires modifying SA1 claims, SA4
transition semantics, SA6 classifications, admission, or governance.

## Witnesses

RCV1–RCV5 cover the complete-transition path, partial and unavailable snapshot
recovery, equal-state recovery, and independent snapshot survival after an SA4
refusal. RCV-H1–RCV-H8 cover stale recovery, same-revision conflict, invalid
CAR/snapshot refusal, Space/author/repo-source substitution, retry idempotence,
conflicting retry evidence, timestamp laundering, and authority relabeling.
