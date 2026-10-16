# SA0 — Spaces alpha observation campaign

**Status:** deterministic fixture slice implemented; no live credential or
deployment.  **Upstream observation date:** 2026-08-20.  This note describes
volatile alpha behavior, not a stable AT Protocol specification.

## Scope and architectural result

ATProto now exposes two materially different observation surfaces relevant to
this project:

```text
public broadcast                         permissioned Spaces
       |                                         |
relay / Jetstream discovery             Space authority writer discovery
       |                                         |
public repo CAR + MST verification       credentialed direct repo-host sync
       |                                         |
public observation/admission             Space observation/admission
       +------------------+----------------------+
                          |
                 governed community boundary
                          |
                 per-occurrence authorization
                          |
                   authorized effect
```

SA0 adds the separately installable `communitywatch-spaces-alpha` package.  It
does not change `communitywatch`'s Jetstream runner, public repository verifier,
SQLite projection, AppView, `communityd`, or participant submission path.  The
paths do not yet converge in storage: SA0 produces an immutable
`EvidenceAdmission` in memory, explicitly scoped to observation, which is the
smallest safe normalized seam to evaluate before any projection migration.

The package contains no HTTP client, credential minting flow, secret store,
signer, writer, database, or effect executor.  Its three-method
`DirectSpaceSource` port lets a later adapter provide writer discovery, DID-to-
repo-host binding, and a verified direct repo snapshot without importing public
MST semantics.  Package-boundary tests enforce that separation.

## What did not change

Spaces do not alter the project's governance doctrine:

```text
observation != evidence admission
access != community standing
standing != per-occurrence authorization
authorization != execution
historical evidence != current authority
```

An SA0 evidence admission is neither a `zone.neutral.community.admission`
authority record nor permission to render the record in the V0 community view.
It cannot call `communityd`.  The existing public V0 path still requires exact
AT URI + CID, independent public-repo proof, configured community authority,
and the local per-invocation administrator authorizer before an effect.

## Alpha compatibility boundary

All volatile constants live in `communitywatch_spaces_alpha.compat`.  SA0 pins:

- [Spaces alpha announcement](https://atproto.com/blog/atproto-spaces-alpha),
  read 2026-08-20;
- [proposal 0016](https://github.com/bluesky-social/proposals/tree/54c9cf5153d668c4f4fb4438529967412e861775/0016-permissioned-data)
  at `54c9cf5153d668c4f4fb4438529967412e861775`;
- [reference implementation PR](https://github.com/bluesky-social/atproto/pull/5187)
  head `89deb9faca20e56fa2a262fe9746ed52bc1095ba`;
- [Bulletin](https://github.com/bluesky-social/bulletin/tree/ccca73d212167e20da56db4691ba7c94e9ad5ccc)
  at `ccca73d212167e20da56db4691ba7c94e9ad5ccc`; its vendored upstream
  lexicons identify alpha-package commit
  `2f77206ff8010710db5733c454abff9eb5ebb96b`.

The isolated assumptions include the `at://{authority}/space/{spaceType}/
{skey}/{author}/{collection}/{rkey}` URI, `com.atproto.space.{listRepos,
getRepo,listRepoOps,getLatestCommit,notifyWrite}`, signed-commit format `1`,
context tag `atproto-space-v1`, LtHash record-set commitment, deniable commit
shape, and dynamic default collections for bare `space:<spaceType>` OAuth
scopes.  Replacing the alpha should primarily replace this module, its direct
source adapter, and fixtures—not the public verifier or governance core.

## Provenance and bounded claim

Every admitted observation retains:

- Space identity: authority DID, Space type NSID, and skey;
- record identity: author DID, collection, rkey, canonical Space URI, exact
  record CID, DAG-CBOR bytes, and decoded value;
- acquisition: Space host, independently resolved repo host, writer-set
  discovery method/rev/hash, direct repo rev/hash, acquisition time, and
  non-secret access metadata (issuer, user, client ID, method, validity window);
- verification: mode, verifier/method version, author-key reference, evidence
  reference, commit format, alpha assumption label, and the exact claims made:
  Space context, author signature context, commit MAC, LtHash record set, and
  record CIDs.

No OAuth token, delegation token, Space credential, DPoP proof/private key,
authentication header, or other reusable secret has a field in the model.

In `verified` mode, the model means that a separately reviewed Spaces verifier
asserted all required claims and that the source/identity/state bindings agree.
In the current deterministic campaign, the mode is visibly `fixture`: the fake
adapter represents that verifier output, while SA0 independently checks record
CIDs and every provenance binding.  Fixture admission therefore proves the
refusal and synchronization semantics against pinned data; it does **not**
prove that SA0 has performed live LtHash, MAC, DID-key, DPoP, or service-auth
verification.

“Current” means current relative to the newest directly verified repo head this
observer established.  It is not a global archival proof and does not promise
that a later, unobserved write has not occurred.  Advancing a head makes older
admissions historical without deleting them.

## Trust and synchronization boundaries

| Boundary | SA0 treatment |
|---|---|
| Space authority | Identifies the Space, resolves the Space host, and issues read access; does not confer community authority. |
| Space host | Source of writer discovery and notification routing; its per-repo state is testimony. |
| Writer set (`listRepos`) | Discovery only. Same-revision hash conflict and a repo behind the claimed revision fail closed; a newer direct repo state may supersede a lagging authority claim. |
| Repo host | Direct source for a writer's permissioned repo; must match the independently recorded author-to-host binding. |
| Author DID | Record authority and expected signed-commit context; must match both fetched repo and each Space URI. |
| Permissioned commit | Spaces-specific verifier claim over signature context, MAC, LtHash, and record CIDs; never relabeled as public MST proof. |
| Notification | Best-effort sync hint only. It creates no observation and supplies no record evidence. |
| Syncer | Periodically reconciles `listRepos` and fetches repo hosts, so a dropped notification does not prevent recovery. |
| Access context | Acquisition-time read fact only. Expiry/loss blocks new fetches but does not rewrite history or prove membership revocation. |
| Space type declaration | Volatile protocol/OAuth input, not immutable governed authority. |

Absence from a later writer listing removes the discovery route; it does not
delete historical evidence or prove access/standing revocation.  A source must
be fetched to establish record contents, and a notification is never passed to
the admission function.

## Mutable OAuth authorization containment

The proposal intentionally resolves omitted `collection` parameters from the
current Space type declaration.  Thus a bare scope that covered `[A]` at T0 may
cover `[A, B]` after declaration mutation at T1.

SA0's `FrozenEffectAuthorization` records the **effective collection set at the
governed boundary**, the scope, time, and declaration evidence reference.
`permits()` consults only that immutable set.  The H8 witness freezes `[A]`,
then presents `[A, B]`; B remains refused.  The value is necessary but not
sufficient: `assess_effect_preconditions` reports whether independently
supplied currentness, community standing, and a per-occurrence authorization
reference are present, but it always sets `authority_conferred` to false.  SA0
implements no effect path, and `communityd` remains unchanged, so mutable OAuth
expansion has no route into an existing writer.

## Deterministic campaign and hostile witnesses

`tests/fixtures/spaces-alpha/campaign.json` uses only test DIDs, hosts, content,
and the explicitly non-canonical namespace `invalid.test.*`.  It covers an
initial writer listing and direct fetch, an advancing repo, notification-driven
refetch, and notification-free periodic recovery.  Refusal tests cover:

- H1 writer-set same-revision/hash substitution;
- H2 notification-only evidence;
- H3 same record coordinates in a different Space;
- H4 Space-record author versus source-bound repo mismatch;
- H5 repo-host substitution;
- H6 stale revision after a newer established head;
- H7 lost access without history/standing mutation, followed by renewed read;
- H8 dynamic Space-type collection widening;
- H9 access/admitted evidence without community standing; and
- H10 standing without per-occurrence authorization.

An additional witness refuses incomplete Spaces verification rather than
falling back to public MST/CAR semantics.

## Known alpha and SA0 limits

- Proposal 0016 calls itself a proposal; the reference PR is open and draft.
  Endpoint names, lexicons, URI validation, token claims, CAR layout, commit
  construction, and OAuth behavior may change.
- The upstream announcement says the code has not received careful security
  review, the hosted data is disposable, no sensitive data should be uploaded,
  and production use is inappropriate.
- SA0 has no live credential/DPoP implementation and no live verifier.  Its
  `verified` adapter contract is a required next boundary, not an implemented
  cryptographic claim.
- Repo-host binding is supplied by the source adapter with an evidence
  reference; SA0 checks substitution but does not yet resolve DID documents.
- Notification service-auth verification is outside SA0.  This is safe for
  admission because notifications remain hints, but a real receiver must still
  authenticate them to prevent sync abuse.
- Permissioned commit deniability means retained material must not be marketed
  as a durable third-party proof of what an author wrote.
- Credential loss may mean expiry, user/app access change, transient failure,
  or Space deletion.  SA0 does not infer membership revocation from it.
- SA0 neither persists permissioned content nor defines retention/deletion
  compliance after Space deletion.  That must be decided before durable sync.
- Public account identity/status events may still require the public firehose,
  as the proposal notes; SA0 does not implement that cross-surface lifecycle.

## Integration status

Fixture-only.  The environment has a Docker CLI but no local
`ghcr.io/bluesky-social/atproto:pds-spaces-alpha` image and no running
Spaces-capable PDS.  Hosted alpha use requires an invite/test account and
interactive OAuth; none was requested or inspected.  Pulling and configuring a
new alpha PDS plus disposable identities would be a separate integration
experiment, not a cheap use of already-present infrastructure.

## OQ-1 impact

OQ-1 is no longer unresolved in this repository: the 2026-08-14 decision chose
`zone.neutral.community.*` for the four V0 record NSIDs.  However,
`docs/status/s1-oq1-publication-gap.md` records an unresolved S1 publication
authorization/process gap.  Spaces raise the stakes because a Space type NSID
is both a semantic identifier and an OAuth consent/default-collection boundary;
namespace control, publication freeze, and mutation policy therefore matter
more than for schema lookup alone.

SA0 does not reopen the OQ-1 selection, publish any NSID, or make
`zone.neutral.community.*` a Space type.  Fixtures use `invalid.test.*`, which
is deliberately non-canonical and must never become a production namespace.
No prototype integration needs a permanent project Space type until a later,
human-authorized publication decision defines its semantics and OAuth mutation
policy.

## Highest-leverage next experiment

Implement a fixture-backed **real Spaces commit verifier adapter** against the
pinned reference implementation's serialized repo vectors: verify the author
signature context and MAC, recompute LtHash from the index, verify record CIDs,
then drive the existing SA0 source port without enabling network credentials.
That closes the largest current proof gap while preserving deterministic tests
and avoiding hosted-alpha/OAuth volatility.
