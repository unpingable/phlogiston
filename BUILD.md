# V0 build authorization

> Current Phlogiston namespace authority is the PN0 amendment below and
> [PHLOGISTON-NAMESPACE.md](docs/PHLOGISTON-NAMESPACE.md). Superseded namespace
> names in older amendments/campaign records are historical, not operational
> dependencies or publication instructions.

This document authorizes implementation of V0 only. Phase 0 produces design
and contract documents; production source begins only in a later milestone.

## Goal

```text
submit -> admit -> render -> remove
```

V0 must answer one question:

> Does a portable admission ledger over user-owned posts feel like a real
> community surface rather than merely a custom feed?

`DOCTRINE.md` is normative for architectural invariants. `IDEAS.md` supplies
context and a donor reuse map, but does not expand V0 scope.

## Ratified V0 defaults

- Public communities only.
- Self-submission only: the submitting repo must own the submitted post.
- One community actor with its own DID.
- One configured administrator DID; delegated roles are not part of V0.
- Manual admit/remove through an administrative CLI or deliberately narrow
  internal endpoint.
- A minimal read-only web AppView is the canonical rendered surface.
- Reverse chronological ordering by admission time only.
- No community-native comment records.
- An exact subject CID mismatch terminalizes that admission and hides it until
  a new submission and admission reference the then-current exact CID;
  reverting a CID never revives the old admission.
- SQLite is the bounded transactional hot store for observer cursors,
  idempotency and control state, the current projection, a compact audit index,
  and the immutable observation tail not yet covered by a sealed archive
  generation.
- V0-M2A adds separately installable, observer-only archive/rebuild tooling.
  Sealed immutable Parquet generations preserve exported observation history;
  DuckDB reads only manifest-listed sealed generations for bounded parity,
  audit, and rebuild work. Neither is used by ingest, web request handling, or
  `communityd`.
- Ingest never dual-writes Parquet. A closed observer/source high-water must be
  staged, schema/count/hash validated, durably sealed, and manifested before
  any retention action. Exactly covered SQLite occurrence rows may be pruned
  only after sealed-custody, hot/cold parity, rebuild, and crash-recovery gates
  pass; a shared payload variant remains until no retained tail row references
  it. The current projection, compact audit index, control state, and unexported
  tail remain in SQLite.
- Tests use fixtures and fake repository/writer adapters. Real ATProto
  adapters remain behind interfaces.
- No production key material.

## Required process boundary

`communitywatch` indexes, audits, projects, and renders. It is structurally
incapable of signing or writing authority records.

`communityd` validates administrative requests and is the only process that
may emit community admission or moderation records. The two processes use
separate packages, dependency sets, configuration, and credentials within
this repository.

Archive tooling is part of the observer side. Its analytical dependencies are
absent from the index/web and `communityd` runtime dependency closures and
import graphs. It has no transport, credential, signing, authority-writer, or
community-repository write capability. Any SQLite retention write runs only in
explicit offline maintenance mode with the live observer processes stopped.

## V0-D2 storage-refreeze amendment

The observed Labelwatch/Driftwatch storage forcing case promotes the previously
reserved hot/cold seam into V0. This amendment authorizes **V0-M2A — sealed
observer history** after V0-M2 and before V0-M3. V0-M2 preserves the SQLite
schema and archive-control seam; V0-M2A adds the separately installed archive
tool, sealed Parquet generations and manifests, a read-only DuckDB CLI, verified
prefix pruning, and rebuild/query parity over sealed history plus the SQLite
tail.

V0-M2A is an offline, explicitly invoked maintenance path. It does not authorize
a continuous archive daemon, cold-path public serving, object-store/distributed
operation, a networked analytical database, or production deployment. The
baseline work previously parked in roadmap slice S12 is absorbed by V0-M2A;
S12 remains non-authorizing and is re-scoped to later managed cold-path
operation.

This amendment records scope only. It does not start V0-M2 or V0-M2A without a
later explicit implementation task.

## Governed execution authorization

The single-use V0-G0 bootstrap authorization was consumed on 2026-08-14:
candidate commit `9bd774bd14fc9c695227f7ce32a5b738c37cb097` passed the V0
gate and the operator accepted the bootstrap outputs. The single-use block is
removed here per the ratified contract; Git history retains the
authorization. Governed execution now proceeds under the general V0
governed-loop contract delivered by V0-G0. The consumption record below pins
the same contract digest as the removed block and names the accepted
bootstrap-output human-acceptance receipt, which is retained in the
controller evidence store.

<!-- governed-execution-consumed:v1 -->
authorization_id = "V0-G0-bootstrap-1"
task = "V0-G0"
receipt_id = "HAR-V0-G0-2026-08-14-01"
contract_sha256 = "sha256:5196331349155397bb0f6b4f85a9adda5ed4e1741e75b043341f4a1f0ec0afa1"
<!-- /governed-execution-consumed -->

## Explicitly out of scope

- PDS modifications or forks
- community-scoped voting or ranking algorithms
- native comment records
- private communities
- membership and delegated role systems
- bans, locks, and flair
- fork/import/replay implementation or UI
- global search
- feed-generator compatibility until the canonical AppView proof works
- native mobile clients
- generalized trust-and-safety infrastructure
- continuous archive daemons, cold-path public serving, object-store or
  distributed archive operation, hot-path/web-request DuckDB, ClickHouse or
  another networked analytical store (the bounded offline V0-M2A path above is
  the only V0 cold-history authorization)
- production deployment or production community keys

## SA0 Spaces-alpha observation amendment

The explicit 2026-08-20 Spaces-alpha campaign authorizes **SA0** as one
bounded, post-V0 implementation exception to the public-only/private-community
exclusions above.  It does not amend the ratified V0 behavior or authorize a
roadmap slice.

SA0 may add a separately installable, observer-only compatibility package,
deterministic fixtures, refusal tests, and design documentation for read-side
Space repository discovery, direct-source observation, and evidence admission.
It may model non-secret access metadata and freeze the effective collection set
at a prospective governed-effect boundary.  It may not add a live credential
flow, hosted or production integration, a Space writer, community membership,
delegated roles, a new community authority record, an effect executor, or any
dependency from the existing public observer or `communityd` into the alpha
package.  No SA0 observation changes the current V0 projection by itself.

The alpha's writer set and notifications remain discovery/synchronization
hints.  Evidence admission requires a direct repo-host result through a
Spaces-specific verifier boundary; public MST/CAR proof semantics may not be
used as a substitute.  Fixture verification must identify itself as fixture
verification and must not be described as a live cryptographic proof.

## SA1 Spaces-alpha cryptographic qualification amendment

The explicit 2026-08-20 SA1 task authorizes **SA1 — Cryptographic Observation
Qualification** as one bounded follow-on inside the SA0 package.  SA1 may add
deterministic permissioned-repo vectors and read-only verification code for the
pinned alpha commit structure, record DAG-CBOR/CIDs, LtHash state, commit
context signature, MAC, and a bounded observation receipt.  A verified receipt
may feed the existing in-memory Spaces observation/admission seam.

SA1 does not authorize network fetch, DID resolution, credential issuance or
storage, OAuth, service authentication, a Space writer, public MST fallback,
community standing, governance authorization, effect execution, projection,
or deployment.  Cryptographic qualification establishes only the exact claims
enumerated by its receipt against supplied evidence and a supplied author key;
it does not convert source metadata, access, or historical state into
authority.  Unsupported alpha versions or algorithms must fail closed.

## SA2 Spaces-alpha raw CAR boundary amendment

The explicit 2026-08-20 SA2 task authorizes **SA2 — Raw CAR Boundary
Qualification** as one bounded follow-on inside the SA0 package.  SA2 may add
deterministic raw CAR fixtures and an isolated read-only adapter for the CARv1
framing, two ordered roots, DAG-CBOR/SHA-256 block identifiers, block order,
and exact conversion into the existing SA1 permissioned-repo evidence type.
SA1 remains the sole boundary that establishes cryptographic or semantic
observation claims.

SA2 does not authorize a second verification model, public-MST fallback,
network fetch, credentials, OAuth, service authentication, a Space writer,
community standing, governance authorization, effect execution, projection,
or deployment.  A well-formed CAR proves only container facts about the bytes
supplied to SA1; roots and block presence do not by themselves prove identity,
repository correctness, currentness, admission, or authority.  Unsupported or
ambiguous framing must fail closed behind the Spaces alpha compatibility
boundary.

## SA3 Spaces-alpha reference interoperability amendment

The explicit 2026-08-20 SA3 task authorizes **SA3 — Reference
Interoperability Qualification** as one bounded follow-on inside the SA0
package. SA3 may add a deterministic CAR artifact emitted by the exact pinned
ATProto Spaces reference serializer, a reproducible generator driver,
artifact/metadata parity validation, refusal tests, and campaign
documentation. The artifact may contain only the existing synthetic SA1
commit/index/record material and public verification inputs.

SA3 treats the reference implementation only as a serialization compatibility
oracle. It does not authorize trust in reference authority semantics, a new
cryptographic verifier, changes to SA1 claims, public-MST fallback, network
fetch at runtime, credentials, OAuth, a Space writer, community standing,
governance authorization, effects, projection, or deployment. Artifact parity
must feed the unchanged SA2-to-SA1 pipeline, and version or byte disagreement
must fail explicitly without conferring observation or governance authority.

## SA4 Spaces-alpha reference transition amendment

The explicit 2026-08-20 SA4 task authorizes **SA4 — Reference Multi-Record
Transition Qualification** as one bounded follow-on inside the SA0 package.
SA4 may add deterministic full-state CAR artifacts for consecutive synthetic
repository states, ordered create/update/delete operation fixtures validated by
the exact pinned reference implementation, a read-only transition qualifier
over unchanged SA1 qualified states, bounded transition receipts, refusal
tests, and campaign documentation.

SA4 establishes only that a supplied qualified source state plus a supported
ordered operation batch produces a supplied qualified target state. It does not
authorize a history store, a completeness or uninterrupted-ancestry claim,
actor legitimacy, user intent, authority, standing, governance authorization,
effects, network/PDS behavior, credentials, OAuth, or deployment. Full-state
snapshots must remain independently qualifiable without transition evidence;
operation logs remain supplied transition context rather than signed history.

## SA5 Spaces-alpha repo-operation acquisition amendment

The explicit 2026-08-21 SA5 task authorizes **SA5 — Repo Operation
Acquisition Boundary** as one bounded follow-on inside the SA0 package. SA5
may add deterministic `com.atproto.space.listRepoOps`-shaped fixtures and a
read-only adapter that validates the pinned response shape, preserves supplied
operation and page order, checks an explicitly observed cursor chain, and
constructs the existing SA4 `RepoTransition` candidate from a separately
qualified source state.

SA5 establishes only deterministic conversion of supplied response pages. A
closed pagination chain or terminal response commit is not complete history,
authenticated ancestry, source authority, authorization, or proof of the
target state. SA4 remains the sole transition qualifier. SA5 does not authorize
HTTP, credentials, OAuth, service authentication, writes, governance, effects,
projection, or deployment.

## SA6 Spaces-alpha reconciliation amendment

The explicit 2026-08-21 SA6 task authorizes **SA6 — Reconciliation and
Recovery Qualification** as a deterministic classifier over existing SA1
qualified states and optional SA4 transition evidence. SA6 may distinguish an
equal state, an exact qualified transition, a newer independently qualified
snapshot, and insufficient evidence. It may model retries, replay, stale
snapshots, missing transitions, and conflicting observations with fixtures.

SA6 does not authorize a history-completeness claim, a freshness oracle,
network synchronization, storage retention policy, credential handling,
authority, standing, governance authorization, effects, projection, or
deployment. Revision or acquisition time alone must not become ancestry or
currentness proof.

## SA7 Spaces-alpha future transport seam amendment

The explicit 2026-08-21 SA7 task authorizes **SA7 — Live Adapter Boundary
Preparation** as an interface-only seam inside the SA0 package. SA7 may define
inert request, source-context, and observed-artifact value types through which
a future transport could supply raw CAR bytes or `listRepoOps` response pages
to the unchanged SA2/SA5 boundaries. All transport metadata remains unverified
context.

SA7 does not authorize a concrete network client, HTTP dependency, OAuth,
credentials or token storage, service authentication, hosted accounts,
synchronization, writes, authority, governance, effects, projection, or
deployment. Supplying bytes through the interface creates no verification or
trust claim.

## SA8 Spaces-alpha recovery decision amendment

The explicit 2026-08-21 SA8 task authorizes **SA8 — Recovery Decision
Qualification** as a fixture-only orchestration layer inside the SA0 package.
SA8 may deterministically select between the existing SA5→SA4 transition path
and the existing SA7→SA2→SA1→SA6 snapshot-reconciliation path, record which
path was attempted, preserve exact existing receipt identities, and emit a
bounded audit trace including hard refusals.

SA8 is governed by: **Recovery can restore observability. It cannot manufacture
missing provenance.** A partial, unavailable, compacted, empty, or refused
operation result may cause independent snapshot qualification; it may not turn
that snapshot into transition evidence, complete history, canonical truth,
currentness, source authenticity, standing, authorization, or governance
authority. Retry and acquisition time add no semantic strength.

SA8 does not authorize a scheduler, retry queue, database, durable cursor,
network fetch, HTTP client, OAuth, credentials, service authentication, live
PDS integration, writes, governance, effects, projection, or deployment. It
does not amend SA1–SA7 or existing public ATProto behavior. Empty-repository
qualification remains deferred unless separately authorized.

## SA9a Spaces-alpha HTTP acquisition amendment

The explicit 2026-08-21 SA9a task authorizes **SA9a — HTTP Artifact
Acquisition Qualification** as one bounded, read-only external acquisition
layer inside the SA0 package. SA9a may issue unauthenticated GET requests for
the pinned `getRepo` and `listRepoOps` query methods, enforce explicit timeout,
body-size and same-origin redirect policy, retain sanitized acquisition
receipts, and emit the unchanged SA7 artifact types. Deterministic integration
tests may bind loopback HTTP servers and compose returned artifacts through
SA2–SA8.

SA9a is governed by: **Transport success is acquisition evidence, not source
authority.** HTTP status, HTTPS/TLS success, hostnames, response media types,
headers, redirects, timestamps, and repeated acquisition may not establish DID
or service binding, PDS or Space identity, artifact validity, currentness,
complete history, standing, authorization, or governance authority. Cross-
origin redirects fail closed, retries are absent, and secret-bearing request
or response headers may not enter receipts or logs.

SA9a does not authorize DID/service resolution, OAuth, Space credentials,
DPoP, cookies, account sessions, service authentication, writes, a scheduler,
persistence, governance, effects, projection, or deployment. It does not alter
the qualification or claim semantics of SA0–SA8 or the public ATProto path.

## SA9b Spaces-alpha DID document interpretation amendment

The explicit 2026-08-21 SA9b task authorizes **SA9b — DID Document / Service
Binding Qualification** as one bounded, deterministic interpretation layer
inside the SA0 package. SA9b may parse supplied bounded DID-document bytes,
require exact document identity, apply the pinned ordered ATProto PDS service
and account-key rules, apply the Spaces-alpha dedicated-host/key fallbacks,
normalize conservative service origins, bind receipts to the exact document
digest, and compare a selected origin with an SA9a acquisition receipt.

SA9b is governed by: **Service binding interprets identity evidence; it does
not create identity evidence.** Its receipts may state which service endpoint
or public-key reference follows from the supplied document. They may not state
that DID-method resolution was authentic or current, that a remote server is
controlled by the DID, that an artifact is valid, or that any actor has access,
standing, authorization, or governance authority. Dedicated Spaces fallback
provenance must remain explicit, and a malformed present dedicated entry may
not silently become an absent entry.

SA9b does not authorize PLC operation-log verification, live PLC or did:web
resolution, handle resolution, network DID-document fetch, OAuth, DPoP, Space
credentials, authenticated Spaces reads, synchronization, writes, governance,
effects, or deployment. It does not alter SA1–SA9a or public ATProto semantics.

## SA9c Spaces-alpha DID resolution provenance amendment

The explicit 2026-08-21 SA9c task authorizes **SA9c — DID Resolution
Provenance Qualification** as two separately testable, read-only method
qualifiers inside the SA0 package. SA9c-web may derive the hostname-level
`did:web` document location, make one bounded unauthenticated HTTPS acquisition
(or an explicitly marked loopback test acquisition), require an exact document
identity match, and retain WebPKI/HTTP provenance. SA9c-plc may validate
fixture/reference PLC operation evidence, including canonical operation CIDs,
genesis-derived identifiers, authorized rotation signatures, active-chain and
bounded recovery/nullification rules, tombstones, and deterministic DID-document
rendering. Both may pass their exact resulting document bytes and a visibly
method-specific receipt reference to unchanged SA9b interpretation.

SA9c is governed by: **DID methods establish provenance differently; common
output must not erase those differences.** It also preserves: **Resolution
provenance is not governance authority.** HTTPS/WebPKI acquisition does not
prove historical or perpetual domain control. A supplied PLC audit does not
prove that no newer operation exists, and directory timestamps remain
directory assertions rather than controller-signed facts. PLC rotation keys
must remain distinct from ordinary DID verification methods.

SA9c does not authorize a generic identity-verification flag, live public PLC
dependency, handle resolution, OAuth, DPoP, Space credentials, authenticated
Spaces reads, persistent synchronization, writes, governance, effects, or
deployment. It does not alter SA0–SA9b or public ATProto semantics.

## SA9d-a Spaces-alpha OAuth/DPoP request-binding amendment

The explicit 2026-08-21 SA9d-a task authorizes **SA9d-a — OAuth / DPoP
Request-Binding Qualification** as one fixture-only authentication primitive
inside the SA0 package. SA9d-a may qualify a supplied synthetic token response,
interpret the exact granted `space:` scopes under the independently pinned
ATProto OAuth and existing Spaces-alpha profiles, construct and verify an
ES256/P-256 DPoP proof for one bounded GET request, enforce server/session
nonce, token-hash, target, method, time, key, and bounded replay bindings, and
retain a secret-free request receipt. It may compose, without collapsing, the
existing SA9c resolution and SA9b service-binding receipts.

SA9d-a is governed by: **Authentication binds a credential to a request. It
does not bind that request to governance authority.** Raw access tokens and
DPoP private keys are runtime-only secret material and may not enter receipts,
manifests, logs, exceptions, or documentation. Requested scope is context only;
only the token response's granted scope is evaluated. The alpha's dynamic bare
collection default must be reproduced as protocol behavior while the existing
`FrozenEffectAuthorization` remains immutable and independently narrower.

SA9d-a does not authorize browser authorization, PAR or token HTTP calls,
authorization-code or refresh flows, OAuth persistence, metadata publication,
Space delegation tokens or credentials, authenticated transport, network I/O,
membership or standing, governed authorization, writes, effects, projection,
or deployment. It does not alter SA0–SA9c, `communityd`, or public ATProto
semantics.

## SA9d-b Spaces-alpha delegation-token qualification amendment

The explicit 2026-08-21 SA9d-b task authorizes **SA9d-b — Delegation Token
Qualification** as one fixture-only credential-verification layer inside the
SA0 package. SA9d-b may verify a synthetic PDS-issued delegation JWT under the
pinned Spaces proposal, bind it to the exact user, Space, Space-host audience,
time window, identifier, account signing-key selection, OAuth grant, and
SA9d-a DPoP request receipt, and retain only secret-free receipt material.
SA9b may add the narrow account `#atproto` key-selection profile needed for
that verification, and SA9d-a may recognize the read-only
`getDelegationToken` request target.

SA9d-b is governed by: **Delegation proves only that the user's PDS delegated
this application to request access to this exact Space. It is not a Space
authority admission decision.** Parsing a JWT, verifying an account-key
signature, a covering OAuth `read` scope, or observing a unique short-lived
token may not establish Space membership/access, credential issuance,
standing, authorization, user intent, or governance authority. Raw delegation
tokens are runtime-only secret material and may not enter receipts, manifests,
logs, exceptions, or documentation.

SA9d-b does not authorize live token acquisition, client attestation, Space
credentials, authenticated transport, browser/PAR/token flows, OAuth
persistence, network I/O, synchronization, writes, governance, effects, or
deployment. It does not alter SA0–SA9d-a, `communityd`, or public ATProto
semantics.

## SA9d-c Spaces-alpha Space-credential qualification amendment

The explicit 2026-08-21 SA9d-c task authorizes **SA9d-c — Space Credential
Qualification** as one fixture-only credential-verification layer inside the
SA0 package. SA9d-c may verify a synthetic Space-authority credential JWT,
bind its exact Space, issuer, time, identifier, credential-specific DPoP key,
SA9c/SA9b authority key and host selections, and the separate SA9d-b
delegation receipt, and retain only secret-free receipt material.

SA9d-c may state that a cryptographically qualified, in-window credential has
the pinned alpha's whole-Space read/sync capability semantics. It must also
state that the credential carries no JWT audience and is intended for repo
hosts serving that exact Space. The selected authority-host origin is issuance
context, not an invented token audience. The applicant is delegation context,
not a credential payload claim. The credential is multi-use; bounded issuance
`jti` replay checks must not be confused with credential-use replay semantics,
which remain DPoP request specific.

SA9d-c is governed by: **A qualified Space credential is protocol access
evidence, not community standing or governance authority.** Delegation request,
authority admission policy, credential issuance, live host acceptance,
membership, standing, and per-occurrence governed authorization remain
distinct. Raw credentials and DPoP private keys are runtime-only and may not
enter receipts, manifests, logs, exceptions, or documentation.

SA9d-c does not authorize live credential acquisition, client attestation,
authenticated transport, network I/O, persistent sessions, synchronization,
writes, governance, effects, or deployment. It does not alter SA0–SA9d-b,
`communityd`, or public ATProto semantics.

## SA9d-d Spaces-alpha authenticated-acquisition composition amendment

The explicit 2026-08-21 SA9d-d task authorizes **SA9d-d — Authenticated
Acquisition Composition** as one bounded follow-on inside the isolated Spaces
package. It may construct and verify credential-bound ES256 DPoP GET requests,
exercise explicit server-nonce challenge/retry attempts against a deterministic
loopback HTTP server, and emit the existing SA7 artifact types. Every attempt
must have its own proof, `jti`, and secret-free acquisition receipt; redirects
and automatic retries are prohibited.

SA9d-d is governed by: **Authenticated transport changes acquisition
provenance, not artifact meaning.** Space credentials, HTTP success, and nonce
handling do not qualify CARs, operations, repository state, identity,
currentness, standing, governance authority, or effects. SA2–SA8 remain the
only relevant evidence qualifiers. This amendment authorizes no live OAuth,
credential acquisition, persistent session, production network, writes,
governance integration, effects, or deployment.

## SA10a Spaces-alpha empty-repository qualification amendment

The explicit SA10a task authorizes a state-level receipt for a cryptographically
qualified empty permissioned repository and composition with the existing SA4
transition/reconciliation boundaries. No fake record or record receipt may be
created. Empty-state evidence proves the bounded signed commit, empty index,
and zero LtHash state only; it does not prove history, currentness, authority,
standing, or authorization.

## SA10b Spaces-alpha durable sync-state amendment

The explicit SA10b task authorizes an observer-only SQLite evidence ledger for
qualified state identities, acquisition attempts, cursor observations,
reconciliation classifications, recovery traces, missing provenance, and
conflicts. Persistence may replay and audit existing receipts but cannot create
or upgrade them. It authorizes no scheduler, network client, credential store,
writer, authority, governance integration, effect, or deployment.

## SA10c Spaces-alpha source-host migration amendment

The explicit SA10c task authorizes bounded comparison of two independently
qualified SA9c→SA9b service-binding epochs for the same DID/profile. A migration
receipt may select the second origin for future acquisition only; historical
artifact/source provenance remains bound to its original epoch. The layer does
not establish global DID currentness, canonical truth, artifact validity,
authorization, governance, writes, or deployment.

## SA10d Spaces-alpha bounded read-only observer amendment

The explicit SA10d task authorizes one deterministic, read-only composition
layer inside the isolated Spaces package. It may validate supplied SA9c/SA9b
repo-host and author-key receipts, use an already qualified SA9d-c credential
and SA9d-d request to acquire a full repository or ordered operation pages,
invoke the unchanged SA2–SA8 qualifiers, persist their receipt identities in
the SA10b evidence ledger, and construct the existing observation/admission
values when an explicit matching writer-discovery claim and access context are
also supplied.

SA10d is governed by: **Composition preserves claim boundaries; it does not
amplify them.** A transport result cannot qualify an artifact, a DID receipt
cannot establish global currentness, a credential cannot establish standing,
an operation response cannot establish complete history, and persistence
cannot manufacture confidence. Writer discovery remains authority testimony
and is never inferred from a successful repo fetch.

SA10d does not authorize live DID/OAuth/credential acquisition, a scheduler,
automatic retry, production configuration, public projection, community
standing, governance integration, effects, writes, or deployment. It does not
alter SA0–SA10c, `communityd`, or the public ATProto path.

## SCV0-D0 Space-backed community product-design amendment

The explicit 2026-08-21 product-direction task authorizes **SCV0-D0 —
Space-backed Community Vertical V0 Design** as one documentary tranche after
the frozen SA0–SA10d qualification campaign. SCV0-D0 may inspect the completed
public V0 and Spaces evidence boundaries, freeze one minimal human workflow,
name conceptual record roles and their repository placement, map process and
credential custody, define the ordinary-user and audit surfaces, record
blocking product decisions, and predeclare a commit-sized implementation
ladder.

SCV0-D0 is governed by: **The qualification substrate serves the community
product; it does not become the product, and product convenience does not
amplify evidence into authority.** The target remains one bounded
`submit → admit → render → remove` community over author-owned records. The
terms *evidence admission* and *community admission* must remain distinct.
Space access is not membership or standing; community standing is not
per-occurrence authorization; authenticated acquisition does not qualify an
artifact; and no mutable OAuth default may widen a previously frozen governed
write capability.

This amendment authorizes documentation only. It does not authorize a new or
published Lexicon, a permanent Space-type NSID, schema or source changes,
fixtures, user or community credentials, a Space writer, browser/OAuth work,
remote administration, authenticated serving, projection of permissioned data,
membership, replies, votes, ranking, governance effects, live network work, a
pilot, or deployment. SCV0 implementation requires a later explicit task that
names a milestone from the frozen design. Existing public V0 behavior,
SA0–SA10d, package boundaries, and the hosted-alpha freeze remain unchanged.

## SCV0-M1 exact-reference model amendment

The explicit 2026-08-21 SCV0-M1 task authorizes **SCV0-M1 — Exact Reference
and Record Models** as one fixture-only implementation milestone following
SCV0-D0. It may add one separately installable inert package containing
immutable Space-specific exact references, submission, per-occurrence
moderator authorization, community admission, projection-reference, and
removal values; deterministic validation and identity rules; synthetic
`invalid.test` fixtures; hostile witnesses; and campaign documentation.

SCV0-M1 is governed by: **Source existence is not community admission, and
community admission is not reader visibility.** Every submission, admission,
projection, and removal remains a separate record-shaped value with an exact
occurrence binding. A Space record reference must preserve Space authority,
record author, collection, rkey, canonical Space URI, CID, and the qualified
source-observation receipt. Community records may refer to author data but may
not copy, mutate, delete, or claim ownership of it. Evidence admission cannot
substitute for a community decision, and per-occurrence moderator
authorization cannot become standing or be replayed for another occurrence.

The new package is inert shared model code only. It may depend on
`community-model`; it may not depend on `communitywatch`, the Spaces observer,
`communityd`, an authority writer, transport, credentials, signing, storage,
or projection runtime. This amendment does not authorize permanent or
published Lexicon/Space-type NSIDs, network access, OAuth, Space credentials,
writers, UI, projection services, membership, roles, replies, votes, ranking,
moderation workflows, governance effects, or deployment. Existing public V0
and SA0–SA10d behavior remains unchanged.

## SCV0-M2 projection-lifecycle reducer amendment

The explicit 2026-08-22 SCV0-M2 task authorizes **SCV0-M2 — Projection
Lifecycle Reducer** as one fixture-only implementation milestone following
SCV0-M1. It may add one separately installable pure reducer package, immutable
source-observation and projection-lifecycle result values, deterministic state
identities, synthetic fixtures, positive and hostile transition witnesses, and
campaign documentation. Its inputs are already-qualified SCV0-M1 values and
explicit source-observation/currentness receipt references.

SCV0-M2 is governed by: **Source state, community admission state, and
projection state are distinct.** The reducer may classify an exact lifecycle
as suggested, added, changed at source, source unavailable, or removed. It may
not decide whether an item should be admitted, who may moderate or read, or
whether source content is good or true. A changed or absent source cannot
become an implicit readmission; a community removal cannot mutate or delete
the source; source unavailability cannot become a community removal; and
projection cannot become authority or ownership.

The reducer package may depend only on `community-model` and
`community-space-model`. It may not depend on an observer, `communityd`,
transport, network, credentials, signing, storage, background work, writer,
UI, serving, ranking, membership, roles, or governance effects. It does not
authorize reader disclosure, permanent Lexicons/Space-type identifiers, live
data, writes, or deployment. Existing public V0, SCV0-M1, and SA0–SA10d
behavior remains unchanged.

## SCV0-M3 fixture wire-adapter amendment

The explicit 2026-08-22 SCV0-M3 task authorizes **SCV0-M3 —
Author/Post/Submission Wire Contract Adapter** as one fixture-only translation
milestone following SCV0-M2. It may add one separately installable inert
adapter package, an explicitly noncanonical `test.invalid.*` wire profile,
strict deterministic JSON decoding, translation receipts, synthetic fixtures,
positive and hostile witnesses, and campaign documentation. The adapter may
construct only the existing SCV0-M1 exact-reference, post, submission, and
admission values; M2 remains the lifecycle authority for projection state.

SCV0-M3 is governed by: **Record-shape translation is not record
qualification.** Caller-supplied Space, author, community, source, occurrence,
and receipt references must match the separately supplied expected context.
Unknown convenience fields cannot add approval, visibility, authority,
membership, ranking, or source-mutation claims. A translation receipt binds
the exact fixture bytes to the resulting M1 value but does not authenticate
the bytes, resolve a DID, validate an ATProto repository, authorize a writer,
or admit an item.

The adapter package may depend only on `community-model` and
`community-space-model`. It may not depend on the observer, Spaces
qualification package, projection reducer, `communityd`, transport, network,
credentials, signing, storage, writer, UI, serving, ranking, membership,
roles, or governance effects. This amendment does not decide OQ-8, authorize
permanent or published NSIDs, live identities or records, writes, reader
disclosure, or deployment. Existing public V0, SCV0-M1/M2, and SA0–SA10d
behavior remains unchanged.

## SCV0-M4 reader-session/disclosure design amendment

The explicit 2026-08-22 SCV0-M4 task authorizes **SCV0-M4 — Reader Session /
Disclosure Boundary Design** as one documentary milestone following SCV0-M3.
It may compare community-operated reader service, reader-direct
synchronization, and shared multi-tenant reader infrastructure; trace where
permissioned data and credentials would exist; analyze reader identity,
access, membership, caching, and revocation; explain why the public V0 AppView
cannot be reused as an implicit disclosure oracle; and refine OQ-9 without
selecting an answer.

SCV0-M4 is governed by: **Reader authentication, Space read access, community
membership, projection state, and disclosure authorization are separate
facts.** A component's ability to acquire or qualify permissioned data does
not authorize it to serve that data. Historical evidence does not confer
current read access, and revocation cannot erase plaintext already disclosed
to a reader.

This amendment authorizes documentation only. It does not authorize source,
schema, fixture, package, server, API, database, cache, session, credential,
membership, UI, network, writer, governance, deployment, or public-AppView
changes. It does not decide OQ-9. Existing public V0, SCV0-M1–M3, and
SA0–SA10d behavior remains unchanged.

## SCV0-D1 community-owned projection-contract amendment

The explicit 2026-08-22 product-direction task authorizes **SCV0-D1 — Reader
Projection Contract** as one documentary milestone following SCV0-M4. It may
freeze product topology D, community-owned projection with a replaceable
shared rendering layer; define a versioned conceptual feed envelope and item,
publication, presentation, disclosure, provenance, and replacement
boundaries; record fields and capabilities that may not cross into the
renderer; and name separately authorized synthetic/local successor
experiments.

SCV0-D1 is governed by: **The community owns projection and disclosure
decisions; the renderer is only a window.** A renderer may consume an exact,
disclosure-scoped projection artifact but may not acquire raw author repos,
hold Space or moderator credentials, decide admission, mutate lifecycle
state, or strengthen receipt claims. Copying bounded source presentation into
a projection artifact is an explicit disclosure of an exact qualified source
version, not source ownership or mutation.

This amendment authorizes documentation only. It does not authorize a feed
schema or serializer, projection compiler/service, publication signature,
server, renderer, API, database, cache, credential, reader session, identity,
membership, network, writer, live permissioned data, UI, human trial, or
deployment. The operator's product-topology direction does not mechanically
close OQ-9 without the antecedent packet and authenticated decision receipt
required by the open-question register. Existing public V0, SCV0-M1–M4, and
SA0–SA10d behavior remains unchanged.

## SCV0-M5A synthetic projection-artifact amendment

The explicit 2026-08-22 SCV0-M5A task authorizes **SCV0-M5A — Pure Synthetic
Projection Artifact Compiler** as one fixture-only implementation milestone
following SCV0-D1. It may add one separately installable pure compiler package,
immutable ordinary/audit disclosure policy values, bounded synthetic source
presentation values, projection artifacts and non-published-candidate
receipts, deterministic identities, synthetic fixtures, hostile witnesses,
and campaign documentation.

SCV0-M5A is governed by: **Source record, community projection, and reader
artifact are distinct.** The compiler consumes only existing M2 lifecycle
values plus an explicit fixed disclosure profile and caller-supplied bounded
presentation. It may not fetch, qualify, authorize, admit, moderate, infer
reader access, or change lifecycle/community identity. Suggested items never
enter a reader artifact; changed/unavailable/removed states cannot silently
acquire replacement content; ordinary disclosure cannot inherit technical
receipt details.

The compiler package may depend only on `community-model`,
`community-space-model`, and `community-space-projection`. It may not depend
on the Spaces observer, wire adapter, `communityd`, transport, network,
credentials, signing, storage, writer, renderer, server, UI, membership,
roles, ranking, or recommendation code. All publication references remain
explicitly synthetic and unverified. This amendment does not authorize live
data, reader authentication, serving, caching, discovery, accounts, writes,
governance effects, or deployment. Existing public V0, SCV0-M1–M4, and
SA0–SA10d behavior remains unchanged.

## SCV0-M5B local fixture-renderer amendment

The explicit 2026-08-22 SCV0-M5B task authorizes **SCV0-M5B — Local Fixture
Renderer** as one local-only implementation milestone following SCV0-M5A. It
may add one separately installable pure renderer package, immutable rendered
semantic/page values, two deterministic HTML rendering implementations,
positive and hostile fixture witnesses, and campaign documentation.

SCV0-M5B is governed by: **The renderer is only a replaceable window over an
exact disclosure-scoped community artifact.** It consumes only the M5A
`ProjectionArtifact`, revalidates that artifact before use, escapes disclosed
text, and may render the community reference, lifecycle notices, bounded
presentation, and already-disclosed technical references. It may not fetch,
qualify, admit, authorize, infer access, mutate artifact/lifecycle state, or
strengthen any receipt claim. Different renderers must preserve equivalent
semantics for the same artifact.

The renderer package may depend only on `community-space-artifact`. It may not
import the M1/M2 packages, Spaces observer, wire adapter, `communityd`,
transport, network, credentials, signing, storage, writer, server, reader
session, database, cache, membership, roles, ranking, recommendation, or
governance-effect code. It produces an in-memory local page only. This
amendment does not authorize live data, serving, reader authentication,
discovery, accounts, publication signing, writes, governance effects, human
trial, or deployment. Existing public V0, SCV0-M1–M5A, and SA0–SA10d behavior
remains unchanged.

## SCV0-OQ9 public-projection V0 decision amendment

The explicit 2026-08-22 operator instruction authorizes **SCV0-OQ9 — Public
Projection First** as one documentary product-decision milestone following
SCV0-M5B. For SCV0 V0, a community may choose to publish an already-compiled
ordinary or separately identified technical-audit projection artifact for
public reading. A replaceable renderer consumes that artifact. The renderer
does not acquire private source state, credentials, reader identity, or
admission capability.

SCV0-OQ9 is governed by: **Public artifact publication is a community
disclosure decision, not reader authentication or permission inferred from
possession.** This V0 choice removes private reader-session mechanics from the
current product experiment; it does not solve them. Private communities,
membership, reader credentials, Space read grants, invitations, revocation,
private serving, authenticated feeds, and confidential discussion remain an
explicit future boundary.

This amendment authorizes the decision record and open-question update only.
It does not itself authorize a package, feed serializer, renderer change,
server, network route, database, cache, live Space data, identity, credential,
writer, governance effect, human trial, or deployment. The decision is
recorded as the operator's direct task instruction; no antecedent question
packet or external decision-receipt artifact is fabricated. Existing public
V0, SCV0-M1–M5B, and SA0–SA10d behavior remains unchanged.

## SCV0-M6A local public-feed boundary amendment

The explicit 2026-08-22 SCV0-M6A task authorizes **SCV0-M6A — Projection Feed
Artifact Service Boundary** as one fixture/local-only implementation milestone
following the SCV0-OQ9 public-projection decision. It may add one separately
installable pure feed-envelope package, immutable publication request/feed
values, a replaceable publisher Protocol, deterministic JSON representation,
synthetic fixtures, positive and hostile witnesses, and campaign
documentation.

SCV0-M6A is governed by: **The feed boundary serves only an exact already-
compiled artifact; it does not acquire, qualify, admit, authorize, moderate,
or infer reader permission.** It must preserve artifact/community identity,
lifecycle state, disclosed presentation, disclosure mode, and bounded
publication metadata. Ordinary publication may not contain technical-audit
disclosure, and publication cannot strengthen the artifact's claims.

The feed package may depend only on `community-space-artifact`. It may not
import M1/M2, the renderer, Spaces observer, wire adapter, `communityd`,
transport, network, credentials, signing, source-fetch, storage, database,
cache, server, reader session, membership, roles, ranking, recommendation, or
governance-effect code. It creates no listener or live route. Fixture
publication references remain synthetic and do not prove publisher authority.
This amendment does not authorize live data, accounts, authentication, private
disclosure, writes, human trial, or deployment. Existing public V0,
SCV0-M1–M5B, and SA0–SA10d behavior remains unchanged.

## SCV0-M6B minimal local browser-prototype amendment

The explicit 2026-08-22 SCV0-M6B task authorizes **SCV0-M6B — Minimal Human-
Facing Prototype** as one local-only implementation milestone following
SCV0-M6A. It may add one separately installable pure prototype package,
immutable prototype-page/site values, deterministic ordinary and technical-
audit HTML generation over exact M6A feeds and M5B semantics, synthetic
fixtures, positive and hostile witnesses, and campaign documentation.

SCV0-M6B is governed by: **The community owns inclusion and publication; the
prototype owns presentation only.** The ordinary page may show community and
author references, bounded presentation, lifecycle state, and a plain-language
“Why is this here?” explanation. A separate audit page may show artifact/feed
identities, lifecycle links, and already-disclosed receipt references. The
prototype must validate that ordinary/audit feeds describe the same exact
public lifecycle occurrence and must preserve canonical renderer semantics.

The prototype package may depend only on `community-space-feed` and
`community-space-renderer`. It may not import M1/M2/M5A directly, the Spaces
observer, wire adapter, `communityd`, transport, network, credentials, signing,
source-fetch, storage, database, cache, server, reader session, accounts,
membership, roles, posting, comments, moderation UI, voting, ranking,
recommendation, or governance-effect code. It returns in-memory escaped HTML
only. This amendment does not authorize live data, authentication, private
disclosure, writes, human trial, or deployment. Existing public V0,
SCV0-M1–M6A, and SA0–SA10d behavior remains unchanged.

## SCV0-M6C synthetic comprehension-instrument amendment

The explicit 2026-08-22 instruction to run the synthetic product validation
authorizes **SCV0-M6C — Synthetic Projection Comprehension Instrument** as one
fixture-only milestone following SCV0-M6B. It may add one separately
installable pure instrument package, a fixed question/cue profile, immutable
structured outcomes and replay receipts, synthetic fixtures, positive and
hostile witnesses, and campaign documentation.

SCV0-M6C is governed by: **Machine-detectable explanatory cues are a necessary
interface property, not evidence that a human understood the interface.** The
instrument may determine whether the canonical M6B ordinary/audit pages make
source ownership, community inclusion, lifecycle state, presentation
retention, and audit references mechanically recoverable. It must replay the
exact M6B feeds and refuse altered pages, caller answer keys, authority labels,
or audit disclosure in the ordinary view.

The instrument package may depend only on `community-space-prototype`. It may
not import M1/M2/M5A/M6A/M5B implementation packages directly, the Spaces
observer, `communityd`, transport, network, browser automation, model or AI
inference, analytics, telemetry, storage, database, cache, credentials,
reader sessions, accounts, membership, moderation, voting, ranking,
recommendation, or governance-effect code. It performs no human trial and
does not authorize live data, serving, authentication, private disclosure,
writes, deployment, or a usability claim. Existing public V0, SCV0-M1–M6B,
and SA0–SA10d behavior remains unchanged.

## SCV0-M7A/M7B synthetic public-demo amendment

The explicit 2026-08-22 instruction to build and publish a site authorizes
**SCV0-M7A — Deterministic Static Demo Export** and **SCV0-M7B — Disposable
Public Demo Publication** as two bounded product-validation milestones after
SCV0-M6C. M7A may add one separately installable demo package, synthetic
four-state fixture assembly, a pure static-bundle compiler, an explicit local
directory writer/checker, manifests/checksums, tests, and documentation. M7B
may publish one exact M7A bundle to a separate public artifact-only GitHub
repository and enable GitHub Pages for that repository.

These milestones are governed by: **The public demo is a disclosed synthetic
artifact, not a live community service.** The bundle may contain only the
already-disclosed synthetic ordinary/audit pages, exact synthetic feed JSON,
an explanatory landing page, and non-secret custody metadata. It must label
itself synthetic, carry no analytics or active script, and retain fixed
non-claims. The publisher must verify hosted bytes against the local manifest;
successful hosting does not establish community authority, reader identity,
ATProto interoperability, currentness, usability, or production readiness.

The demo package may depend only on the inert SCV0 artifact/feed/prototype/
comprehension packages. It may write only an explicitly supplied local export
directory and must refuse ambiguous replacement. It may not import observer,
`communityd`, transport, credentials, signing, Space access, database, cache,
membership, moderation, voting, ranking, recommendation, or governance-effect
code. M7B may use a separately named public repository with Apache-2.0/MIT
licensing and GitHub Pages, but may not deploy this application repository, a
server, private data, live identities, accounts, authentication, writes, or
production infrastructure. Existing public V0, SCV0-M1–M6C, and SA0–SA10d
behavior remains unchanged.

## SCV0-M7C human-facing synthetic showcase amendment

The explicit 2026-08-22 public-demo review authorizes **SCV0-M7C — Human-
Facing Synthetic Showcase** as one bounded presentation milestone after M7B.
M7C may add a separately versioned static showcase compiler, one named but
explicitly fictional community, several synthetic admitted presentations, a
human-readable lifecycle story, a separate technical-audit view, static CSS,
deterministic manifests/checksums, fixtures, tests, campaign documentation,
and republication to the existing disposable GitHub Pages repository.

M7C is governed by: **A friendlier renderer may improve legibility; it may not
strengthen the artifact's claims.** The showcase must consume typed M5A/M6A
artifacts through the existing M6B semantic boundary. Ordinary pages must not
receive technical receipt identifiers. Changed, unavailable, and removed
states must retain their exact source/community meanings, and the original M7A
boundary fixture must remain embedded and independently replayable.

The showcase may not add live data, a source fetcher, observer, writer,
credentials, identity resolution, reader authentication, membership,
moderation workflow, ranking, recommendation, analytics, cookies, executable
browser script, database, server, or production deployment. Fictional names
and copy are presentation metadata only and confer no identity or authority.
Human review motivates this presentation pass but does not authorize a claim
of human comprehension, usability, desirability, accessibility conformance,
or product-market fit. Existing public V0, SCV0-M1–M7B, and SA0–SA10d
semantics remain unchanged.

## SCV0-M8A retained V0 evidence-demo amendment

The explicit 2026-08-24 operator instruction authorizes **SCV0-M8A — Retained
V0 Evidence Demo** as one bounded public demonstration after M7C. M8A may add
a read-only historical-evidence surface inside `communitywatch-web`, fixture
tests, deployment configuration, campaign documentation, and one disposable
public deployment over a byte-pinned copy of the governed V0-M8 observer
store. The retained store contains non-production public ATProto test records
and independently verified repository observations from the completed V0
exercise; no new record write is required or authorized by this amendment.

M8A is governed by: **A retained verified observation is real historical
evidence, not proof of current repository state.** Every human and machine
surface must identify the evidence as captured history, bind the exact store
digest, preserve per-event verification outcomes, and refuse store mutation.
It may explain that a PDS-signed community record was observed and verified;
it may not turn that fact into currentness, complete history, community
legitimacy, membership, or governance authority. The canonical V0 AppView
and all SA/SCV0 reducers remain unchanged.

The deployed process must open the observer store read-only, use no
credential, perform no network acquisition, expose only GET/HEAD/OPTIONS, and
run separately from `communityd` and the Spaces packages. It may not add a
writer, admin endpoint, account, cookie, analytics, database mutation,
background observer, live Space data, private disclosure, ranking,
recommendation, or production claim. OQ-8 and OQ-10 remain open for a future
live SCV0 Space/community loop; this historical public V0 witness does not
decide them. Existing public V0, SCV0-M1–M7C, and SA0–SA10d semantics remain
unchanged.

## SCV0-D2 through live-disposable-alpha amendment

The explicit 2026-08-24 product instruction authorizes one bounded
**SCV0 live disposable alpha** after M8A. It consists only of D2's blocking
contract freeze and the smallest author write, community write, qualified
observer/publisher, public renderer, deployment, and sacrificial lifecycle
trial needed to exercise:

```text
create -> self-submit exact version -> authorize/admit -> publish
       -> source change/absence -> author withdrawal -> community removal
```

This amendment is governed by: **A community may make durable, inspectable
editorial decisions about an exact thing it does not own.** Author records
remain author-owned; the community actor alone writes admission/removal;
observer and renderer remain structurally unable to write either. A public
presentation requires an exact author self-submission carrying the frozen V0
disclosure consent. No write may affect projection until it has returned
through the ordinary Spaces acquisition and qualification boundaries.

The work may add visibly experimental Spaces-alpha Lexicons, immutable shared
values and lifecycle rules, a separately packaged browser OAuth/author writer,
a Spaces-alpha adapter inside `communityd`, supervised read-only observation
and atomic public-artifact publication, a public Juniper Commons surface, and
disposable hosted/local deployment configuration. Secrets are runtime/session
material only. Author, Space authority, and community actor use distinct
disposable DIDs and disjoint credential/process custody. The renderer receives
only the public projection artifact.

The author-withdrawal occurrence is exact and prospective: it stops ordinary
active presentation for that exact submission/admission while preserving the
historical community decision and its permitted receipt. It does not erase or
rewrite community-authored history, imply why an absent record disappeared,
or authorize substitution of another source version. Re-entry requires a new
exact self-submission and community decision.

This amendment does not authorize production identities/data, private-reader
sessions, membership, voting, ranking, comments, social graphs,
recommendations, notifications, a generalized account platform, remote
browser moderation, PDS modification, or claims of production readiness.
Alpha workarounds remain compatibility-local. Existing public V0 and SA0–SA10d
verification, authorization, custody, recovery, and currentness semantics may
not be weakened.

The live slice has a product-comprehension release gate. After the usable
deployment exists, at least one technically uninvolved person must exercise
the lifecycle without an architecture explanation and then describe in their
own words what Juniper does and how it differs from an ordinary repost or
aggregator. The feed/useful object comes first, the edit-after-admission path
must be easy to exercise, and protocol terms remain behind progressive
disclosure. The participant's explanation is recorded verbatim before the
intended model is explained. If the participant cannot identify the utility
after using the lifecycle, the result is **PRODUCT COMPREHENSION FAILURE**;
it is not user error, documentation debt, or permission to add features.

### SCV0-L10 authority bootstrap boundary

The live-alpha amendment authorizes the one-time, separately packaged
**SCV0-L10** authority bootstrap needed to publish the seven frozen
experimental Lexicons and create the exact public/open disposable Space. The
bootstrap uses two disjoint OAuth sessions: a create-only
`com.atproto.lexicon.schema` grant and an exact Space `manage=create` grant.
Neither session may be reused by the author application, `communityd`, the
observer, or the renderer.

The initially documented `.juniper.<name>` spellings are replaced before any
live publication by single terminal names such as `juniperPost`. The pinned
ATProto parser treated `juniper` as part of the reversed namespace authority,
yielding an unresolvable nested handle. This is a compatibility correction to
never-published experimental identifiers, not a second schema version or a
change to their semantics. L10 must pin document digests, refuse conflicting
readback, and make no membership, standing, governance, or production claim.

### SCV0-L11 isolated disposable Spaces-alpha PDS fallback

The live-alpha amendment authorizes **SCV0-L11** only because the preferred
BPS-hosted authority returned OAuth `access_denied` for the exact create-only
Lexicon publication grant. L11 may deploy one separately named, disposable
Spaces-alpha PDS container on the existing authorized Linode, bind it to a
new data directory and port, expose only exact Juniper PDS/account hostnames,
and provision only the three already-frozen disposable roles. It must pin the
official image digest and keep all generated PDS/account secrets outside Git.

L11 may amend the never-published D2 authority DID and experimental NSID
authority only as one atomic compatibility substitution after the replacement
accounts exist. Record schemas, consent, withdrawal, role separation,
qualification, authorization, and projection meanings do not change. The
existing `juche.social` PDS, its accounts, data, container, configuration, TLS
gate, and DID custody are out of scope and must remain unchanged. The fallback
PDS is test infrastructure, not a fork or modification of PDS behavior.

## PCV0 public-community social-loop amendment

### PN0 product-owned namespace correction (2026-10-03)

The owner explicitly rejected Juche and neutral.zone as Phlogiston's canonical
Lexicon authority and selected **PN0 — Phlogiston-owned Lexicon namespace**:
`app.phlogiston.community.*` under `phlogiston.app`. This authorizes the bounded
pre-publication rename of the existing eight documents and their current
Python/TypeScript collections, OAuth scopes, publisher/DNS bindings, deployment
examples and conformance fixtures. Preserve every schema field and behavior;
recompute document hashes and exact-reference fixture identities changed by the
rename. No new schema semantics, aliases or migration architecture are added.

The corresponding authority is `community.phlogiston.app`, with
`_lexicon.community.phlogiston.app TXT did=<dedicated authority DID>`. This
supersedes the neutral namespace/publication authority named by older amendments
below. Historical qualification receipts and campaign records remain intact.
Existing synthetic records are evidence, not public compatibility obligations;
any real current published consumer would require reconciliation before removal.

Account enrollment and exact-manifest publication acceptance remain held. This
correction does not authorize production record writes, Lexicon publication,
community activation, participant/room consent or new credential authority.
Juche remains implementation-reference-only and non-normative for Phlogiston.

The explicit 2026-09-07 implementation instruction authorizes **PCV0 — Public
Community Social Loop V0** as a bounded successor campaign. PCV0 restores the
public app-layer product path over normal ATProto identities and
`app.bsky.feed.post` records. The frozen Spaces-alpha implementation remains
historical evidence and may not be silently rewritten into this product path.

PCV0 may extend the unpublished `zone.neutral.community.*` schemas and public
V0 model before their first Lexicon publication; add explicit immutable reply
policy, automatic reply-admission, and reply-action records; extend the
read-only observer and AppView with opted-in reply trees, participant
presentation, pending state, discussion activity, and private application
last-seen state; add a normal-ATProto OAuth browser backend; add an unprivileged
reply-policy worker; and add a narrow Unix-socket request boundary through
which that backend and worker may request exact operations from `communityd`.
`communityd` remains the sole community-authority writer and must independently
revalidate every request at its write boundary.

The campaign is governed by: **an author supplies public content and explicit
community context; an immutable community policy decides eligibility; only the
community actor records admission or moderation authority.** A reply context
cannot grant membership, standing, or authority. Reply removal changes the
community view, not the author's repository, and remains effective across new
CIDs at the same logical reply URI until an explicit restore. Root removal or
author context withdrawal closes normal discovery and future reply admission
while retaining an explanatory historical permalink.

The trusted `community-web` backend may terminate OAuth and attest the restored
session DID to `communityd` only over its dedicated peer-authenticated socket.
That is a deliberate remote-administration trust boundary: the backend may
request bounded effects but holds no community repository credential.
`community-policy` may request only policy-qualified automatic reply admission.
The observer may neither request nor perform effects. Each process has a
separate principal, configuration, dependency closure, and private state.

All participant and authority writes must be prepared durably before dispatch,
use a predetermined record key, represent an ambiguous response as
`attempted_unknown`, and reconcile exact readback before retry or dependent
work. An ordinary supervised-process restart must recover pending work through
the browser without a duplicate record or terminal intervention.

PCV0 implementation and local fixtures may proceed before publication. Live
writes are gated on human acceptance of the exact Lexicon digests, verified
publication under the already-selected `community.neutral.zone` authority, and
verified `_lexicon.community.neutral.zone` resolution. Publication is
permanent protocol surface and is not delegated to unattended automation.

PCV0 does not authorize multiple communities or moderators, delegated roles,
membership, bans, locks, reports, private communities, all-public-reply
projection, per-reply manual admission, media, likes, reposts, votes, ranking,
search, recommendations, push/email notifications, community memory,
recurrence scoring, root restoration, fork/import/replay UI, native mobile
clients, or production-readiness claims. Internal dogfood is the only human
trial.

## PCV1 reference-client candidate composition amendment

The explicit 2026-09-10 implementation instruction authorizes **PCV1 —
Reference-Client Candidate Composition** as a bounded successor campaign to
PCV0. PCV1 extends the existing `community-live` browser app into a
reference-client *candidate*: a social reading and participation surface that
composes ordinary Bluesky identity, profile, and post data with the narrow
community index, instead of forking a full Bluesky client or replacing the
stock AppView.

PCV1 is governed by: **the community projection is the only essential read;
everything from Bluesky is decoration.** The observer API remains the sole
authoritative source for community state. Bluesky AppView data — handles,
display names, avatars, and any later post hydration — is cached presentation
data only: never identity, never authority, never keys. The DID remains the
identity. On hydration mismatch, staleness, rate limit, or outage, every
surface degrades to DID presentation and keeps working; hydration health must
never enter the readiness path or block community rendering.

PCV1 may add, inside `apps/community-live` only: static CSP-compatible
styling and page layout; coded error pages; route-level HTTP tests; local
bounded pagination over existing observer responses; a sign-out route that
ends only the browser session and a separate, explicit disconnect action that
revokes OAuth and explains what remains (revocation is never called logout);
an optional, separately configurable profile-hydration adapter; discussion,
community-context, "my discussions", unread, and moderation presentation
passes; truth-versus-projection explanations and validated outbound Bluesky
links; one automated browser qualification suite; and campaign documentation.

The hydration adapter is operator-pinned, not user-supplied: a configured
HTTPS-only AppView origin, strict timeout, body-size, and batch limits, and a
bounded TTL cache with negative caching. It must never become a
user-controllable fetch target. External avatars additionally require an
explicit privacy decision: either allowlist the exact Bluesky CDN origin,
validate image URLs, and document the viewer-request disclosure, or omit
avatars. The default is omission.

Because the observer's discussion list endpoint has no server-side
pagination, the observer client in `community-live` must enforce strict
response-byte and item-count acquisition ceilings and refuse oversized
responses with a truthful server-pagination-required state. It must never
silently truncate while presenting the list as complete. Reaching that
ceiling is the evidence that authorizes considering PCV1-M4.

All AppView-, observer-, and user-controlled presentation data is hostile
input. PCV1 must route every rendered text value through one centralized
HTML-escaping boundary; construct outbound Bluesky URLs only from validated
DID and AT URI components rather than emitting stored URLs as hyperlinks;
restrict external links and images to explicit `https:` origins; and carry
hostile fixtures — embedded markup, quotes, Unicode controls, absurdly long
names, malformed URLs, deceptive handles, and stylesheet- or script-shaped
text — proving that injected data cannot create markup, forms, navigation,
or same-origin requests. Content-Security-Policy remains defense in depth
and is never the escaping mechanism.

PCV1 consists of: **PCV1-M1** (this authorization and trust-boundary
freeze), **PCV1-M2** (presentation foundation, acquisition ceilings, the
hostile-presentation gate, sign-out/disconnect), **PCV1-M3** (the optional
profile-hydration adapter), **PCV1-M4** (conditional; see below),
**PCV1-M5** (discussion rendering and truth/projection UX), and **PCV1-M6**
(the automated browser suite and the two-account cross-PDS dogfood handoff).
The deliverable is named a reference-client candidate throughout; the
"reference client" claim is earned only after that dogfood campaign.

**PCV1-M4 — conditional projection amendment.** Only if PCV1-M2/M3 use
proves local pagination or plain text genuinely insufficient, a separately
authorized narrow `communitywatch-web` change may add cursor support to the
discussions endpoint and/or original-facet passthrough in the projection
payload. PCV1 does not authorize M4 by default; the client must prove the
need first. Client-side re-detection of links or rich text from post text
alone is forbidden.

PCV1 does not authorize membership or role systems, delegated moderators,
ranking or ordering other than the ratified reverse-chronological default,
nested reply threading, media or embed rendering, likes, reposts, votes,
search, recommendations, push or email notifications, a `social-app` or
other stock-client fork, multiple communities, private communities, reader
sessions, juche signup or any account-provisioning flow, observer or
`communityd` changes beyond a proven M4, lexicon changes, live publication,
or production-readiness claims. Existing PCV0 gates — lexicon publication
acceptance and the two-human dogfood gate — are unchanged, and PCV1 work
proceeds against local fixtures and fakes until they are met. Existing
public V0, SA0–SA10d, and SCV0 semantics remain unchanged.

## PHI0 Phlogiston community integration amendment

The explicit 2026-09-22 implementation instruction authorizes **PHI0 —
Phlogiston Community Integration V0** as a bounded application-integration
slice. PHI0 does not alter PCV0 or PCV1 and does not promote either candidate.
It proves whether Phlogiston can consume existing community authority and
projection boundaries without becoming an authority writer itself.

PHI0 may add one append-only `zone.neutral.community.memberAction` authority
record before publication of the still-unpublished `zone.neutral.community.*`
Lexicons; exact add/remove lifecycle validation in the inert shared model; an
exact membership operation on the existing peer-authenticated `communityd`
socket; observer reduction and a read-only membership endpoint; and a narrow
Phlogiston adapter, public community view, and authenticated operator surface.
The canonical Lexicon source must be singular and generated/runtime copies
must be checked byte-for-byte for drift.

The community actor remains the sole community-state writer. Phlogiston may
request a membership transition, inspect projection state, and present its
authoritative result, but it holds no community repository credential and may
not derive membership from OAuth, PDS account existence, participation, or a
local UI state. Membership transitions are keyed by stable DID, append-only,
idempotent, and terminal after removal for this slice. The observer remains
read-only and may not request effects.

PHI0 may also provide a minimal authenticated operator surface for official
PDS administrative XRPCs required by the isolated experiment: invite creation,
account creation, account inspection, and account search. These PDS-custody
operations must remain visually and architecturally distinct from community
authority. The application must call official HTTP APIs rather than shelling
out to operator CLIs, must discard returned account tokens, and must require
an explicit intent-bound confirmation for destructive community transitions.

Qualification must use pinned stock PDS software, synthetic identities, real
repository records, the real `communityd` operation boundary, observer proof
and projection, and Phlogiston rendering. Where multi-PDS behavior is claimed,
at least one isolated cross-PDS lifecycle is required. Production accounts,
credentials, services, DNS, Q2-observed state, Lexicon publication, protocol
schema deployment, and public registration remain excluded.

PHI0 does not authorize generalized roles, delegated moderators, private
communities, protocol deletion, production deployment, semantic discourse
inference, a PDS fork, a replacement AppView, or a second community business
logic implementation inside Phlogiston. Existing author ownership, exact
URI+CID admission, authority separation, reconciliation, and removal
semantics may not be weakened.

## PHI1 Phlogiston enrollment and recovery amendment

The explicit 2026-09-22 continuation instruction authorizes **PHI1 —
Phlogiston Enrollment and Integrated Recovery** as a non-production successor
to PHI0. PHI1 may add a Phlogiston-owned ATProto OAuth browser/session boundary
using the pinned official Node OAuth client; persistent opaque OAuth and web
session stores; explicit login, expiry, renewal, local logout, and provider
disconnect behavior; and read-only presentation of the authenticated DID's
separate projected community-membership state.

Authentication proves only control of an ATProto account for the lifetime of
the restored OAuth session. It may neither create nor imply membership,
admission, moderation standing, or operator enrollment. A stale or unavailable
projection yields an indeterminate membership presentation. Invalid, expired,
or revoked OAuth state invalidates the Phlogiston web session. The browser
receives only an opaque application cookie and never a PDS admin credential or
OAuth token.

PHI1 may also extend the isolated recovery harness to capture two stopped stock
PDS state trees, the durable `communityd` operation journal, exact public
configuration, and custody metadata; restore into blank synthetic
infrastructure; and reconstruct `communitywatch` projection state from exact
repository records. OAuth state and browser sessions are explicitly
re-enrollable secret state rather than community authority and must not be
required to reconstruct membership, admission, or removal.

Qualification must prove exact authority-record survival, removal persistence,
idempotent observer replay, no invented membership/admission, fail-closed
partial or mismatched restore, and degraded behavior when either PDS,
`communityd`, OAuth state, or projection is unavailable. It may use only
synthetic identities, pinned software, isolated local networks, and disposable
state. Public Lexicon publication, production OAuth metadata, DNS/TLS, real
accounts, production secrets, deployment, and activation remain separately
gated and unauthorized.

## PHI2 deployable-artifact readiness amendment

The explicit 2026-09-22 continuation instruction authorizes **PHI2 —
Phlogiston Deployable Artifact and Inert Activation Readiness**. PHI2 may
obtain and independently verify the exact lockfile-pinned OAuth package;
qualify deterministic clean-cache Phlogiston release construction; verify the
canonical community Lexicon source and publisher drift contract; and prepare
exact, non-installed systemd, Caddy, backup, rollback, and synthetic-activation
packets for the already selected production names.

PHI2 does not authorize Lexicon publication, PDS or application installation,
DNS/TLS/Caddy mutation, account or DID creation, OAuth enrollment, membership,
admission, moderation, record writes, production secrets, or production
activation. Existing production DNS and host state may be observed read-only.
No artifact, successful health check, or reachable route creates authority for
an account or community effect.

## PCV2 first-trial user-path amendment

The explicit 2026-09-24 implementation instruction authorizes **PCV2 — First
Trial User Path** as a bounded successor to PCV0 and PCV1. Its purpose is
narrow: make the first external trial measure whether humans want the
community rather than whether they can survive its plumbing. PCV2 consumes
the bounded portions of the non-authorizing PD-B1 and PD-C tranches in
`docs/design/PRODUCT-DIRECTION.md` (anonymous readable permalink, visible
submission lifecycle, moderator queue legibility, the deliberately simple
room notification) and the findings of the workspace user-path critique of
2026-09-24. Every other PD tranche remains `Authorized: no`. PCV2 changes
only `apps/community-live` and adds at most one new unprivileged process; it
does not alter PCV0 or PCV1 semantics, the observer's authority boundary, or
`communityd`.

PCV2 consists of three slices.

**PCV2-A — anonymous discussion permalink.** `community-live` may serve one
discussion page to an unauthenticated reader at a clean, pasteable path of
the form `/d/<rkey>`; the existing `/discussion?rkey=` route may redirect to
it. The anonymous page is assembled only from the read-only observer
projection and the already-authorized presentation hydration. It exposes no
forms, no moderator affordance, no participant-private state (unread,
"my discussions", operations), and no write capability. Every mutation route
and every participant-private page keeps its existing session requirement.
Not-found, malformed key, removed, and projection-unavailable states must be
truthful and distinct. This is the read half only; anonymous reading creates
no reader session.

**PCV2-B — visible submission lifecycle and room notification.**
`community-live` may show a signed-in author their own root submissions that
have no admission yet, sourced by reading the projection's moderation queue
server-side and filtering to the session DID; it may render that state in
ordinary language ("waiting for the moderator") without inventing any record
or state not derivable from the projection. The moderation queue page may
render enough of the submitted post to decide an admission without leaving
the surface, obtained through the existing PCV1 operator-pinned AppView
hydration adapter pattern (bounded, cached, HTTPS-only, hostile-input
escaped) and labelled as unverified presentation data; admission remains an
exact URI+CID decision that `communityd` independently revalidates. The
observer is not changed for this.

PCV2-B may add one new unprivileged process, `community-notify`, modelled on
`community-policy`: its own principal, configuration, dependency closure, and
private state; no repository credential; reads only the read-only projection
HTTP API; keeps a durable local cursor; and POSTs a fixed, minimal message
(event kind, community name, ordinary-language line, and the community
permalink) to at most one operator-configured HTTPS webhook URL — the
incoming webhook of the room the trial cohort already inhabits — when a root
submission becomes pending and when a root is admitted. Delivery is
best-effort and idempotent; it is never a delivery guarantee, never a
delivery record with authority meaning, and never an inbound command path.
This narrowly relaxes PCV0's "push/email notifications" non-goal for this
single outbound room webhook only. It authorizes no identity bridge, no bot
framework, no per-user subscriptions, no email, no push, and no
notification subsystem.

**PCV2-C — existing-post submission and explicit consequences.**
`community-live` may let a signed-in author submit an existing
`app.bsky.feed.post` from their own repository by Bluesky post URL or AT URI:
resolve it to an exact URI and current CID, refuse any post whose repository
is not the session DID, and write only the `zone.neutral.community.submit`
record through the existing durable contribution journal and readback
discipline. The ratified self-submission-only default is unchanged; PCV2
authorizes no third-party nomination and no user-delegated writer. The
composition form must state plainly, before submission, that it creates a
public post on the author's own Bluesky account; the same holds for public
replies. Copy directly on the participation path may be clarified (the
"opt in" wording, moderator removal/withdraw wording, and the seen/read
wording); no general redesign is authorized.

PCV2 is bound by: `communityd` remains the sole community-authority writer;
`communitywatch` and `communitywatch-web` remain read-only, credential-free,
and unchanged; all PCV1 hostile-input, escaping, and outbound-link rules
apply to every new surface; no new record type, lexicon change, membership,
role, ranking, search, media, or generic client work; fixtures and fakes
only, with the existing lexicon-publication and two-human dogfood gates
unchanged. PCV2 authorizes no deployment, activation, DNS/TLS/Caddy change,
production credential, or public trial; those remain gated by their own
authorities and by the Q2 observation window. Each slice ships with focused
tests and a clean typecheck and unit run of `community-live`.

### PCV2 qualification note (2026-09-25)

PCV2 verification includes an isolated real-PDS synthetic-user harness under
`qualification/pcv2/` (three stock-PDS containers with their real OAuth
authorization server and consent UI, `community-live`, `communityd`,
`communitywatch`, `community-notify`, Playwright browsers; stand-ins for the
did:plc directory, the AppView, and the room webhook, each labelled in the
receipt). It exists to exhaust plumbing mistakes before any human participant
sees the trial. It authorizes nothing: it runs on loopback with disposable
state and synthetic identities only, and its receipts are evidence of the
isolated path, never of production, deployment, or a trial. The two
loopback-only identity seams it needs (`COMMUNITY_PLC_DIRECTORY_URL`,
`COMMUNITY_HANDLE_RESOLVER_URL`) are refused unless the application itself
is a loopback origin.

## P0 self-service public playground amendment (2026-10-11)

The owner explicitly authorizes implementation of P0 under
[the accepted replacement contract](docs/P0-LAUNCH-CONTRACT.md). This supersedes
second-human/moderator, recruited-trial, room-notification and identity-migration
prerequisites for this bounded playground only. Historical dogfood receipts stay
unchanged and are not marked passed. One operator may control distinct technical
test identities; public OAuth opt-in does not confer moderator authority.

P0 uses ordinary Bluesky-hosted accounts. Juche accounts/infrastructure/migration
are excluded without fallback; Phlogiston PDS hosting remains deferred. Permit
bounded changes to community-live, communityd, read-only observer/query paths,
the existing deployment kit and qualification harness for durable submission
limits, bounded/fair intake, separate site-write and admission pause, private
exact-subject decline/readback, root-only manual admission, optional disabled
notifier and canonical phlogiston.app OAuth origin. No new Lexicon, authority
writer, PDS/federation infrastructure or unrelated governance machinery. Preserve
author custody, exact URI+CID, source terminality, peer/authority separation and
uncertain-write reconciliation. The private decline state is application custody,
not a public moderation record, and is not reconstructed by observer replay.

Real provider qualification needs explicitly authorized isolated test credentials
and actual streaming observation of a newly participating Bluesky DID. Fixtures
are local evidence only. Production credentials/accounts, Lexicon publication,
DNS, deployment and public activation remain unauthorized and separately gated.

### P0 isolated test correction (2026-10-11)

The owner subsequently authorizes existing Juche accounts as temporary integration
test infrastructure through an explicit isolated-test configuration. This narrowly
supersedes the preceding unconditional Juche test exclusion, not the public
Bluesky-only hosting assumption. No fallback, PDS service change, migration,
production deployment or permanent Lexicon publication is authorized. Juche test
results never satisfy the separate real Bluesky-hosted lifecycle launch gate.


## Controlled hosted PDS successor — owner authorization 2026-10-11

The owner now authorizes independently deploying maintained upstream ATProto PDS software at `phlogiston.social`, automated disposable-account provisioning and normal OAuth lifecycle tests, protected credential custody, and backup/independent restoration. This supersedes PDS-hosting deferral for the controlled environment; it does not authorize unrestricted public registration, migration of real users, Juche changes, or unrelated pushes. Public registration remains behind actual recovery and migration qualification.

P0 may select the exact hosted `https://phlogiston.social` provider through an explicit configuration mode, with separate decision/intake custody from the default Bluesky qualification path. No implicit provider substitution is permitted. Existing author-record custody, admission authority, bounded intake, pause, decline and observer recovery invariants continue unchanged. The normal application OAuth/write path must be exercised by a controlled browser; administrative provisioning does not qualify record writes. See the product repository's `docs/PDS-EXECUTION-20261011.md` and campaign recovery checkpoint for this execution authorization.

## Public-playground launch readiness — owner direction 2026-10-12

The owner accepts the completed bounded Constellation binding and directs the
campaign to finish the approved Bluesky-hosted Lexicon publication, qualify the
authorized `participant.example.com` participant through the normal OAuth path,
prepare the public application deployment and rollback, and verify the actual
submission/moderation/rendering lifecycle. This supersedes earlier publication
and preparation holds for this bounded work. Public application activation remains
reserved for approval of the concrete candidate. Public PDS registration remains
closed; replies, additional moderators, notification rooms and comprehensive
durability work remain deferred. No Constellation component changes are admitted.

An explicit combined provider setting may admit ordinary Bluesky-hosted author
repositories alongside the exact controlled Phlogiston PDS. Hosted-only mode
remains unchanged by default. Keep issuer/audience/DID checks paired, the authority
writer pinned to its configured community identity and PDS, and the observer
read-only. Actual external-provider qualification is required; configuration or
fixtures alone do not establish compatibility. Reuse the exact authorized saved
Phlogiston OAuth grant for Participant through normal SDK refresh if valid, preserving
protected custody; no unrelated account or ACL grant is authorized.

The owner subsequently explicitly supersedes the publisher's Bluesky-hosting
requirement: provision a dedicated project-owned identity on the existing
invite-only `phlogiston.social` PDS, retain `lexicon.phlogiston.app` as its handle,
and bind the approved NSIDs through their distinct `_lexicon` authority record.
Supported account provisioning and normal authenticated schema repository writes
are authorized, with independent DNS/DID/schema retrieval verification. Public
PDS registration stays closed. This does not substitute the hosted publisher for
the separate Participant external-PDS compatibility qualification.

## P1 integrated participant application — owner authorization 2026-10-12

The owner explicitly authorizes implementation, qualification and immediate
deployment of one bounded authenticated Phlogiston experience: account identity,
existing community activity/submissions and read-only Labelwatch account/post
observations. The Cabinet remains its first collection with anonymous browsing.
Reuse community-live's canonical OAuth/session and write boundaries; composition
is a participant surface, not an operator-only tool or new authority service.
No new scopes, Lexicons, writers, membership semantics, network-scale AppView or
Constellation changes. Attention controls require an existing qualified adapter;
no unavailable control is presented as working. Labelwatch refusal, incomplete
coverage and unavailable responses remain unknown, never an account verdict.
Labels cannot change community authority, admission, ranking or moderation.
This amendment supersedes earlier surface restrictions for P1 only.

## FR0 — Feed-first participant application (2026-10-12)

The operator authorizes immediate implementation, qualification and deployment of
an authenticated Following reader and conversation view using existing Bluesky
AppView RPCs through the participant's normal OAuth/PDS path. This corrects the
prior account-dashboard sequencing; it does not create a network-wide AppView.
Anonymous Cabinet browsing and existing community authority remain unchanged.

The bounded reader preserves applicable viewer/moderation preferences, upstream
order and cursors, and bounds fetch-ahead. Explicit optional conversation controls
use normal OAuth muteThread/unmuteThread, verified readback, and local Following
filtering. The interface must disclose the shared Bluesky notification effect.
This is an app-owned adapter, not a claim that the ACL Quench engine is deployed.
Unknown lineage or effect outcome must not become an asserted policy result.
Independent provider/runtime qualification is required before enabling controls.
Labelwatch observations remain read-only context, never community authority.
No new post/reply/like writes, generic policy framework, or PDS changes are in scope.

## FR0-UX — Compact reader and display preference (2026-10-12)

The owner requests a tighter, familiar Bluesky-like reading density and a
Claude Opus UX/design review, retaining Phlogiston's distinct functionality.
This presentation successor may adjust feed/conversation markup, spacing,
typography and navigation, and provide browser-local Light, Dark and System
appearance. System is the default and follows the device setting. This grants
no new account permissions or policy authority and changes no feed filtering,
quiet-effect, community admission or Labelwatch observation semantics.
Existing build/deploy authority applies to the bounded web successor after
responsive, theme, permission-boundary and regression qualification.

## CW1 — Bluesky client with composable social views (2026-10-12)

The owner redirects the product toward a capable Bluesky client with optional
composable views and authorizes the next bounded implementation and deployment.
CW1 adds saved custom-feed reading through normal scoped OAuth, one optional
companion source, pinned persistence by default, opt-in feed pairings, and
explicit temporary conversation/context inspection that preserves underlying
reading position. Community is a selectable source with unchanged exact-version
admission semantics. No generic widget/layout framework or automatic switching
based on scrolling or inferred interests.

Local quiet is an explicitly feed-scoped application preference, separately
stored from the existing Bluesky notification-mute adapter. It performs no
provider write. Resolve a structural thread root before saving, fail closed on
unknown lineage, and do not imply semantic/topic-wide suppression. Provider
notification changes remain separately labeled, scoped, and consented.

Improve media/quote/repost rendering while independently applying appropriate
moderation contexts. Observations remain inspectable context, not authority.
Preserve existing grants for Following; new custom-feed RPCs require an explicit
read-permission step-up. No implicit broad grants, new identity infrastructure,
network-wide indexing, community ranking changes, or Constellation modifications.
Post composition, likes/reposts, notifications and wider client parity are the
product direction, not completion claims for CW1.

## PF1 — Personal feed curation and first-use clarity (2026-10-12)

The owner's clarified acceptance supersedes the initial author-post assumption.
Implement and deploy a personal view of the consumer's Following timeline with
additional exclusions from an explicitly selected curator's public direct block
records. Keep content sources, curator policy and consumer identity separate in
versioned declarative definitions; no publishing identity is granted or implied.
Preview, name/save/edit/delete, and open the view in either pane. Definitions are
private to the signed-in account. Reply/repost transformations are separate from
sources and exclusions. Preserve normal consumer moderation and source order.

Acquire public blocks through a bounded supported-provider read path with an
explicit freshness/coverage contract. Unavailable, incomplete or malformed policy
reads must not silently become an empty exclusion set. No copied blocks, provider
writes, second account session, public feed publication or generic policy engine.
Following-graph sources require a later retrieval qualification and are not the
alt's authenticated Following timeline. Full ACL/Quench remains separate.

First-use/help copy explains current reader capabilities, operator-configured
communities, private personal views versus published feeds, and returning-user
dismissal. Native participation follows separately. Optional Observe mode must
be a distinct actual read-only permission grant, not hidden write controls; it
is recorded for that successor, not claimed by the current submission grant.

## FD2 — signed-out product entry (2026-10-12)

Owner-authorized bounded implementation and web deployment: present Phlogiston before the public Cabinet on the anonymous root; centralize reader-profile sign-in at `/signin`; add header access; redirect protected document GETs with validated local return destinations carried through the existing nonce-bound OAuth flow. Keep anonymous collection access, exact current scopes, session and mutation boundaries, moderation and authenticated workspace behavior. JSON endpoints and mutations do not become sign-in redirects. PDS enrollment remains parked in #25 behind durability #10. No account creation, new client features or policy integration is authorized by this slice.

Qualification: signed-out desktop/mobile, real Cabinet content, local destination validation and negative controls, normal OAuth return, existing full web checks and web-only deployment with exact rollback. Formalization consideration: allowlisted read destinations and nonce-bound callbacks preserve the existing permission boundary; bounded HTTP negative cases and actual OAuth qualification suffice, without a new protocol or model. Owner root; source and results bound in the FD2 campaign receipt.

## AG1 — accountable attention in the reader (2026-10-13)

Owner-authorized bounded implementation on the existing branch; no deployment and
no push. Issue #27 states the direction and does not authorize by itself; this
amendment does, for the reader only. Following, saved custom feeds, personal
feeds and conversations must not silently apply Phlogiston's own suppression.

Accounting boundary: every item Phlogiston **receives** for a page and
deliberately does not show carries one named disposition, and the page states the
totals. The tally covers that retrieved page or observation window only. Items an
upstream service never returned are outside it; Phlogiston does not count,
estimate or explain them, and does not assert a ranking rationale for an order it
did not produce.

Who decided is modelled separately from what Phlogiston could establish. Not
being able to read or establish something is an observation status, never a
decider, and is never presented as a source, community or viewer decision. A
curator's public blocks carry two facts: the curator authored them and the
viewer chose to apply them. Blocks the viewer did not place are not attributed
to the viewer.

Exact numbers appear only where Phlogiston enumerated the items. A bounded
conversation says that more was received than is shown; it does not invent a
remaining count.

Community tombstones, admission context and their rendering are already
qualified and are not changed or routed through reader code. No new scopes,
stores, writers, upstream calls, Lexicons, policy engine or AppView
responsibility. Existing moderation withholding, permission and session
boundaries are preserved.

Qualification: deterministic unit and route tests for each disposition, the
received-item accounting identity, distinct blocked/not-found/unreadable
conversation states, and the full existing web checks. Remaining semantic gaps
are reported for owner review rather than resolved silently.

### AG1 follow-up (2026-10-13)

Owner-accepted narrow corrections. A label is evidence from its labeler; the
account's moderation settings, which may be defaults, decide the effect, so
label-based hiding is counted apart, names the label source, and is not called a
choice. A blocking party is named only when the response establishes it;
otherwise the reader says a block prevents display. Each received item takes
exactly one disposition. Quieting or restoring in the page replaces that page's
counts with a refresh notice rather than leaving stale totals. The `/context`
refusal for hidden posts, unfetched conversation branches and quoted-post
markers remain later follow-ups.

### AG1 release authorization (2026-10-13)

AG1 is accepted. With the browser test that drives the real Quiet here, Undo and
Restore controls and checks the accounting notice passing, the owner authorizes
pushing this branch and a web-only deployment through the existing qualified
release path: the immutable web generation and managed drop-in producer, only
`community-live` restarted, the exact prior drop-in retained for rollback, and
authority/observer services, configuration, controls and private state unchanged.
Verify the served build identity and smoke-test Following, quiet/restore and
Community live. The deferred AG1 items stay deferred. The next feature ships as
a separate release.

## CC1 — community conversation in the reader (2026-10-14, #28)

Owner-authorized bounded implementation and separate web-only release. The S18
observer read path does not exist in the live P0 runtime: the observer ingests
no reply trees and P0 renders root-only discussions. CC1 therefore does not
implement S18 and adds no ingestion, inclusion rule, reply admission or
community authority. It uses the existing qualified reader path, the viewer's
own OAuth `getPostThread`, to present an admitted post's public replies on its
community page as Bluesky testimony under the viewer's settings, labelled as
not reviewed or admitted by the community.

Contract: only the exact admitted URI and CID is extended with a conversation;
a changed post keeps the admitted text and withholds the newer conversation
with a link to read it; a removed admission keeps its tombstone and reads no
conversation; an unreadable conversation is an observation limit and never a
removal; signed-out readers are offered sign-in back to the same page; a
submission-only grant is offered the existing reader connection. A
conversation whose post or declared root is a currently admitted post links
back to its community page when the observer can say so; observer failure adds
no context and does not block the conversation. Community cards name the link
"Open in <community>". Small reader fixes: singular count wording and the
empty-page line's alignment.

## CC2 — signed-out public conversation and live reply qualification (2026-10-14, #28)

Owner-authorized, separate web-only release. CC1's renderer was first qualified
live against one real, explicitly labelled reply posted by the
`author-a-20261011.phlogiston.social` qualification identity to an operator
seed; no other participation was created.

Signed-out readers of an admitted post's community page now see its public
replies through one unauthenticated read of the public AppView
(`COMMUNITY_APPVIEW_ORIGIN`, default `https://public.api.bsky.app`). The read
is issued only for the exact admitted root URI taken from the projection, never
for a caller-supplied URI; depth 2 and parent height 0 are fixed; the response
is time- and byte-bounded; repeat views share a 30-second cache bounded by the
discussion cap. No credentials, scopes, ingestion, storage or proxy route are
added. Rendering uses Bluesky's default moderation with no viewer, so an
author's `!no-unauthenticated` opt-out is honoured and attributed to the author.
The admitted-CID check, removed-root, changed-post and unreadable outcomes are
identical to CC1. Signed-out pages link only to Bluesky, keep the community's
own rendering of the admitted post, and say how to use one's own settings.

### CC3 — moderator form placement (2026-10-14)

Owner-directed UX fix shipped as its own web-only release. In P0 the root
removal form follows the public conversation inside a "Moderator actions"
disclosure instead of interrupting the post and its replies; it is still shown
only to the configured moderator and posts the same command. This release also
carries the first rehearsed web rollback (CC3 → CC2 → CC3).
