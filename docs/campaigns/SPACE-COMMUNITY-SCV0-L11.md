# SCV0-L11 — isolated disposable Spaces-alpha PDS fallback

Status: **isolated PDS live; custom Lexicon/Space creation pending** (2026-08-25)

## Trigger

The preferred BPS-hosted authority explicitly denied the exact create-only
Lexicon OAuth grant after operator consent. L10 refused to broaden the grant.
L11 is the bounded fallback already contemplated by the live-alpha instruction:
one disposable reference PDS, isolated from the user's existing PDS.

## Deployment boundary

The fallback uses the official amd64 Spaces-alpha image by immutable manifest
digest:

```text
ghcr.io/bluesky-social/atproto:pds-spaces-alpha@sha256:bc8ad28e0082b3098a38ac95eb15f2d2f37392d2a287799ab7b5ab9917975e32
```

It has its own container, port 3001, data directory, environment file, repo
signing key, PLC rotation key, DPoP secret, JWT secret, administrator secret,
accounts, and systemd unit. Caddy names are explicit; no wildcard/on-demand
policy is broadened. The existing `juche.social` PDS remains on port 3000 and
is not a dependency, mount, migration source, or fallback credential source.

The live deployment has:

* public origin `https://juniper-pds.sp00ky.net`;
* exact account hosts `authority`, `author`, and `moderator` beneath that
  origin;
* container root filesystem read-only, all capabilities dropped, and exactly
  two explicit writable bind mounts (`/pds` and `/app/data`);
* no Docker restart policy while bootstrap remains incomplete;
* an append-only Caddy route over the four exact names, with the preexisting
  configuration checksum retained for rollback.

The public role bindings are:

| Role | DID |
| --- | --- |
| Space/Lexicon authority | `did:plc:wklgd4ebjiajx4gj3fthp62m` |
| author | `did:plc:amynaqqmdog7ualmiopxhh4x` |
| community actor/moderator | `did:plc:3yjj2vbc42du6epwxyfccw4v` |

Each account has a separately generated password retained only in the host's
mode-0600 credential file. Account-creation access/refresh tokens were neither
retained nor emitted.

## Authority compatibility substitution

No Juniper Lexicon or live record exists under the hosted D2 authority. After
the replacement authority account is created, its exact DID and the NSIDs
derived from `authority.juniper-pds.sp00ky.net` may replace the hosted values
atomically. This is one never-published experimental authority substitution,
not a schema generation. Every record field, exact URI+CID subject, consent,
withdrawal, community-authority, observer, and projection invariant remains
unchanged.

## Claims and non-claims

L11 can establish which immutable PDS image and isolated host configuration
were deployed and which disposable DIDs it created. It does not establish PDS
correctness, durable availability, production fitness, community legitimacy,
membership, standing, authorization, artifact validity, or governance. All
records still traverse the existing qualification and authorization layers.

Deployment success is infrastructure evidence, not permission to weaken an
existing hostile witness.

## Short-lived bootstrap authorization

The PDS reports an expired PAR request through the OAuth callback as
`access_denied`. Server-side evidence distinguishes this from a user or policy
denial with `AccessDeniedError: This request has expired`. The callback page is
therefore deliberately generic, and `bootstrap-authority.sh` generates each
short-lived authorization URL in the operator's terminal immediately before
it is needed. It publishes only after the corresponding callback completes and
destroys the temporary OAuth state/session directory when the two-stage
bootstrap ends.

The subsequent code-received failure was local rather than upstream: the
token endpoint returned HTTP 200, public DID/handle/service resolution passed,
and the client then revoked the token because the bootstrap `SecretStore`
could not persist a session under a colon-bearing DID key. Session/state keys
are now mapped to SHA-256 filenames. This accepts the OAuth library's DID key
contract without placing a DID, OAuth state, or other raw key in a filename.
The repair is fixture-qualified; no additional browser attempt is part of this
compatibility investigation.

The evidence chain for that diagnosis is bounded and secret-free:

```text
authorization redirect issued code
        -> token endpoint HTTP 200
        -> public DID/handle/PDS/issuer resolution passed
        -> no session row/file existed
        -> token revocation HTTP 200
        -> SecretStore DID-key reproduction failed under old filename rule
        -> SHA-256 filename repair round-trips the same DID key
```

This does not claim that a future authorization must succeed for every reason;
it establishes a specific repaired cause for the observed post-code failure.
No Lexicon or Space was published during the investigation.

## Is custom Lexicon bootstrap required?

Yes, for the frozen Juniper milestone. The pinned permissioned-data proposal
defines a Space type as an NSID that resolves to a published Lexicon `space`
declaration. That declaration supplies the type identity, consent-facing name,
and default record collections. Reusing the reference `my.bulletin.board` type,
skipping resolution, or treating the local schemas as if published would alter
the frozen D2 contract. Custom Lexicon publication is therefore an operational
prerequisite for this custom Space, even though it proves no governance claim.

## Quality gates

The bounded implementation passed:

* root Ruff lint and format checks;
* all 1,251 Python tests, including prior SA/SCV0 and package-boundary
  witnesses;
* all 39 affected Node tests (15 bootstrap, 3 authority writer, 3 observer
  acquisition, and 18 live application) and all four TypeScript type checks;
* wheel and sdist builds for all 18 Python packages;
* shell syntax checks for the installer and bootstrap wrapper;
* the secret-pattern scan, with only intentional placeholders and hostile
  synthetic test strings present;
* `git diff --check`.

One initial root-suite run exhausted its pytest temporary filesystem after
1,236 passing tests. An isolated-temp rerun completed all 1,251 tests. The
environmental failure did not justify a code or assertion change.
