# Spaces alpha SA10d: bounded read-only observer

Status: qualified against deterministic local HTTP and pinned SA1–SA10c
fixtures on 2026-08-21.

## Doctrine

> Composition preserves claim boundaries; it does not amplify them.

SA10d is a synchronous orchestration layer, not a daemon. One explicit call
binds already qualified method-resolution and DID-document interpretation
receipts to one already qualified Space credential and DPoP request. It then
records one SA9d-d acquisition, passes the exact body to unchanged SA2/SA1,
and stores the resulting bounded state identity through SA10b. Ordered
operation responses pass through unchanged SA5 semantics, and recovery invokes
unchanged SA8 semantics.

The composition is:

```text
SA9c repo DID provenance + SA9b host/key selection
  + SA9d-c credential + SA9d-d exact request
  -> one explicit SA9d-d acquisition
  -> SA7 artifact
  -> SA2 CAR framing
  -> SA1 repository-state qualification
  -> optional SA6 reconciliation / SA8 recovery
  -> SA10b evidence custody
  -> existing EvidenceAdmission seam only with explicit writer discovery
```

## Guarantees

The snapshot receipt binds the exact resolution, host-selection, key-selection,
credential, request-binding, acquisition, CAR, SA1 state, persistence-event,
and admitted `(Space URI, record CID)` references used by the call. The
orchestrator refuses a different DID document, selected host, author key,
Space, repo DID, credential, request target, acquisition source, writer-set
state, or access subject.

Admission still requires a separately supplied `WriterSetClaim` whose exact
revision/hash matches the qualified state and an `AccessContext` bound to the
qualified credential's authority, applicant, and validity interval. The
writer claim remains authority testimony used for discovery; the successful
repo fetch does not manufacture it.

Operation pages retain request order. SA5 remains responsible for cursor-chain
and completeness classification. SA8 remains responsible for deciding whether
the result is a transition, snapshot-only, equal, insufficient, or refused.
SA10b stores those outcomes without upgrading them. Its durable head advances
from a recovery trace only for SA8's `qualified_transition` and
`snapshot_only` outcomes; equal, stale, conflict, insufficient, and hard
refusal outcomes cannot move it.

## Non-claims

SA10d does not prove complete history, global currentness, canonical truth,
Space membership, community standing, authorization, governance authority,
or effect execution. A valid credential is only protocol access evidence.
HTTP success does not qualify a CAR. A valid snapshot is not a transition.
Persistence and repeated acquisition add no confidence.

## Endpoint and fixture boundary

The normal profile requires the DPoP request origin to equal the SA9b-selected
repo-host origin. Deterministic socket tests use an explicit loopback-only
override because `*.invalid.test` is deliberately not contacted. Receipts from
that mode record `endpointBindingEstablished=false` and
`loopbackFixtureOverride=true`; they must not be represented as a real
identity-to-network binding. The provider's asserted source endpoint still has
to equal the selected origin so downstream source-context substitution tests
remain active.

There are no hidden retries, redirects, timers, background loops, writes,
public projection, or production configuration.

## Alpha assumptions and replacement boundary

SA10d imports its protocol shapes and pins exclusively from the existing
compatibility boundary: proposal commit
`54c9cf5153d668c4f4fb4438529967412e861775`, reference commit
`89deb9faca20e56fa2a262fe9746ed52bc1095ba`, and the separately pinned OAuth,
DID, CAR, commit, operation, credential, and recovery profiles documented by
SA1–SA9d-d. No new wire interpretation is introduced here.

Alpha churn should replace SA9c/SA9b identity inputs, SA9d-d acquisition, SA2
framing, or SA5 operation parsing at their existing boundaries. It must not
change the SA6/SA8 classifications, SA10b custody doctrine, EvidenceAdmission
meaning, or any public-ATProto behavior.

## Witnesses

Positive fixtures prove a local authenticated CAR reaches the existing
admission seam and durable store, a `listRepoOps` response reaches SA5 and SA8
transition qualification, and unavailable operations plus an equal snapshot
remain `equal_state` without transition evidence.

Hostile fixtures refuse selected-host substitution, endpoint mismatch outside
the explicit loopback profile, wrong writer revision/hash, incomplete
admission context, different credential/request bindings, invalid CAR/state,
and recovery relabeling. Receipt serialization is checked for raw credential
absence and retains all authority/currentness concepts as explicit non-claims.

## External integration status

SA10d's implementation and qualification remain deterministic/local. SA9e was
subsequently completed against an isolated checkout of the exact pinned
reference commit: a disposable local PDS issued a transient Space credential,
served a real `getRepo` CAR over loopback HTTP, and the unchanged SA2/SA1 path
qualified the retained artifact. That separate witness is recorded in
`SPACES-ALPHA-SA9E.md`; it does not upgrade SA10d's source identity,
currentness, history, authorization, or governance claims.
