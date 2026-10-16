# SCV0-M4 — reader-session and disclosure boundary

Status: **design boundary documented; human decision required** on 2026-08-22.

SCV0-M4 adds no serving implementation. It analyzes how a future reader might
receive an SCV0 projection without turning an observer, projector, or public
AppView into an unauthorized disclosure oracle. OQ-9 remains open and blocks
shared reader UI and any human trial serving permissioned Space content.

## Doctrine

```text
reader authentication != community membership
community membership   != Space read access
Space read access       != disclosure authorization
projection state        != reader visibility
qualified evidence      != permission to rebroadcast
```

The existing SA stack can establish bounded identity, authentication,
acquisition, and repository claims. M1–M3 can establish exact community
records, projection lifecycle, and fixture translation. None of those layers
answers which reader may receive which permissioned bytes.

## The decision to make

The human decision is not simply “add login.” It must choose a custody and
delivery topology, then define the explicit rule that maps current reader
evidence to a bounded disclosure. The rule must keep at least four inputs
separate:

| Input | Bounded meaning | Not established |
| --- | --- | --- |
| reader authentication | this session demonstrated control under the selected authentication mechanism | community membership or Space access |
| Space access evidence | this reader/application presently has protocol access under a bounded credential | membership, standing, or permission to redistribute |
| community membership | an explicit governed community fact, if SCV0 ever introduces one | protocol access or per-response authorization |
| projection lifecycle | qualified records reduce to Suggested/Added/ChangedAtSource/SourceUnavailable/Removed | entitlement to see that state or its content |

SCV0 currently has no membership model. A future decision may choose not to
add one, or may define an explicit rule relating membership to disclosure. It
may not infer membership from possession of a Space credential or from a
successful authenticated request.

## Model A — community-operated reader service

```text
community authority
        ↓
community reader service
        ↓
authorized readers
```

### Shape

A service operated for one community acquires and qualifies Space artifacts,
reduces community records, authenticates readers, evaluates the selected
disclosure rule, and returns a bounded projection. The community authority and
reader-service process remain separate logical roles even if one operator runs
both.

### Benefits

- Centralizes protocol churn and the SA qualification stack rather than
  placing it in every reader client.
- Can provide a simple browser experience and consistent projection semantics.
- Can enforce a single response and technical-receipt disclosure budget.
- Per-community operation reduces cross-tenant cache and credential mixing.

### Trust and custody cost

- The service sees reader identities, access attempts, qualified community
  state, and any plaintext it renders.
- It becomes a new online disclosure enforcement point and a high-value cache,
  logging, and session target.
- A community operator can omit or selectively serve projections even when
  the underlying receipts are valid; qualification does not make the operator
  neutral.
- If it holds reusable reader or Space credentials, compromise expands beyond
  already rendered data. Whether it may hold such credentials is unresolved.

### Scaling and revocation

Each community owns operational capacity and incident response. Revocation can
deny future service responses after the relevant reader/access state is
re-evaluated, but cannot erase prior responses, browser caches, screenshots,
or exports. Cache keying must include community, Space, reader authorization
epoch, projection state, and disclosure policy; those requirements are not an
implemented cache design.

## Model B — reader-direct synchronization

```text
reader client
        ↓
Space authority / repo hosts
```

### Shape

The reader obtains its own bounded Space access, synchronizes author and
community repositories directly, runs or consumes the qualification logic,
and constructs the projection locally. A discovery service could supply
non-authoritative hints, but would not deliver permissioned records.

### Benefits

- Avoids a central service that sees every reader and every rendered item.
- Keeps disclosed plaintext and offline caches under the reader's custody.
- Aligns network access with the credential holder rather than delegating
  broad read capability to a projection operator.
- Makes operator substitution or community-service outage less decisive once
  the reader has qualified material.

### Cost and UX burden

- Every client inherits DID resolution, authentication, credential, CAR,
  transition, recovery, storage, alpha-compatibility, and update complexity.
- Initial synchronization and local qualification may be expensive, especially
  on constrained or browser clients.
- Repo hosts learn reader network access patterns directly; direct sync is not
  anonymous merely because it avoids a central AppView.
- Offline use necessarily retains plaintext beyond the instant of access.

### Revocation

Credential revocation can prevent later synchronization. It cannot retract
records already downloaded, prove deletion from a client cache, or invalidate
historical observation receipts. The product must state that limit honestly.
Whether offline retention is a supported user right, a bounded cache, or
disallowed product behavior is a human product decision.

## Model C — shared reader infrastructure

```text
many communities
        ↓
shared serving layer
        ↓
reader sessions
```

### Shape

One provider hosts reader-session and projection delivery for multiple
communities. It may reuse mechanical qualification code, but every credential,
artifact, cache entry, authorization decision, and response must remain bound
to an exact tenant/community/Space and reader context.

### Benefits

- Lowest per-community operational burden and easiest route to uniform client
  UX.
- Shared protocol compatibility, observability, and capacity management.
- Could expose the same bounded projection contract across communities.

### Isolation and multi-tenant risk

- Compromise or policy error can expose many communities at once.
- Cache-key omission, credential mix-up, confused-deputy requests, search
  indexes, metrics, logs, or support tooling can cross disclosure boundaries.
- The provider observes a cross-community reader graph and may infer sensitive
  relationships even without exposing record contents.
- A successful authorization for one tenant cannot be reused for another
  Space, community, projection, receipt disclosure, or cache entry.
- Shared infrastructure intensifies the need for independently auditable
  tenant isolation and explicit data-retention limits.

### Revocation

The serving layer must re-evaluate the selected reader/access rule at a human-
chosen boundary and invalidate tenant- and reader-bound cached responses. It
still cannot claw back data already disclosed. “Removed from one community”
must not become “erase the source” or a global cross-tenant ban.

## Permissioned-data custody map

Where decrypted or permissioned data exists depends on the selected model:

| Location | Data/capability that may exist | Boundary that remains |
| --- | --- | --- |
| author PDS / permissioned repo host | authoritative hosted repository state and protocol access enforcement | hosting a record does not confer community authority |
| Space authority | Space declaration, writer discovery, access/admission decisions, and credential signing; content access depends on deployment | Space access policy is not community standing or moderation |
| observer / syncer | acquired CAR/op bytes, qualified state, and evidence receipts, transient access material under SA rules | read access and qualification do not authorize serving |
| projection service | selected lifecycle state and, if server-side rendering is chosen, bounded plaintext/content plus reader-session context | projection does not establish reader entitlement; this is the new disclosure oracle risk |
| reader client | rendered plaintext, receipt disclosure, and possibly offline qualified artifacts | later revocation cannot make already disclosed bytes unknown |

The Space authority and community authority are distinct roles. The observer
and projection service are also distinct capabilities even if a future
deployment co-locates processes. Co-location does not erase receipt or policy
boundaries.

## Revocation cases

### Reader removed or session invalidated

A future service can refuse subsequent responses once it has qualified the
relevant new reader state. A cached response already delivered remains a
historical disclosure. Authentication/session invalidation alone does not
prove community-membership revocation unless an explicit membership model says
so.

### Space credential changed, expired, or revoked

Present protocol acquisition may stop. Historical qualified observations
remain historical evidence; they do not grant new access. Renewed access does
not renew any governed authorization or establish that earlier cached content
may still be disclosed.

### Community admission changed or removed

M2 yields `Removed` for the exact projection lifecycle. A reader service can
stop returning it in future projections, but the `CommunityAdmission`, source
reference, and prior reader disclosures remain addressable history. Removal
does not delete the author record.

### Cached projection data

Cache eviction, TTLs, encryption-key rotation, and offline retention can bound
future availability but cannot guarantee erasure from a reader-controlled
device. The chosen product contract must name what “revoked” means instead of
promising retroactive secrecy.

## Why the public AppView is not the reader boundary

The public V0 AppView is intentionally unauthenticated and operates on public
broadcast records. Reusing its routes for Space-derived projections would
collapse:

```text
observer can acquire
        into
any caller may receive
```

Ordinary WebPKI, a valid projection state, or an SA-qualified receipt does not
supply the missing reader authorization. Even an endpoint that hides content
but exposes existence, author, community, receipt IDs, timestamps, or state
changes can become a disclosure oracle. Any reuse of renderer code would need
a new authenticated delivery boundary and an explicit field-level/joint-view
disclosure budget; the current public routes cannot be enabled by
configuration.

## Comparison

| Concern | A: community service | B: direct sync | C: shared service |
| --- | --- | --- | --- |
| protocol burden | community operator | each client | infrastructure provider |
| plaintext custody | service and reader | reader | shared provider and reader |
| reader privacy | community sees sessions | repo hosts see fetches | provider sees cross-community graph |
| compromise radius | one community | one reader/device | many tenants |
| browser UX | comparatively simple | difficult | comparatively simple |
| offline behavior | optional bounded client cache | inherent/likely | optional bounded client cache |
| revocation reach | future responses only | future sync only | future responses across tenant-bound caches |
| isolation burden | process/community boundary | client/repo boundary | strongest tenant and cache isolation required |

No row establishes a winner. Hybrid designs inherit the obligations of every
component they combine; they are not an escape from the decision.

## Human decisions required by OQ-9

Before implementation, a human-reviewed decision must pin:

1. Model A, B, C, or an explicitly bounded hybrid.
2. The exact evidence required for a reader session and which component checks
   it.
3. Whether SCV0 introduces membership; if so, the governed rule connecting it
   to disclosure without treating access as standing.
4. Credential custody: whether any service may receive or retain reusable
   reader/Space credentials.
5. The projection and technical-receipt fields each audience may receive,
   including joint-view/existence leakage.
6. Cache and offline-retention policy, authorization recheck boundary, and the
   honest semantics of revocation.
7. Reader privacy, tenant isolation, logging, metrics, support, and incident
   response constraints.
8. Fail-closed behavior for missing, stale, conflicting, or unavailable
   identity/access/source/projection evidence.

## Guarantees and non-claims

This document guarantees only that the decision surface and its claim
boundaries are recorded. It does not prove or choose reader identity,
membership, Space access, disclosure authorization, revocation, service
security, currentness, privacy, governance legitimacy, or product usability.

No server, database, API, cache, UI, credential, membership record, network
client, or serving route was created. OQ-9 remains open. Implementation stops
here pending an explicit human decision.
