# Spaces alpha SA9d-c — Space-credential qualification

**Status:** fixture-qualified on 2026-08-21. No live credential acquisition,
client attestation, authenticated transport, writer, governance integration,
or deployment was added.

> **A qualified Space credential is protocol access evidence, not community
> standing or governance authority.**

## Compatibility pin

SA9d-c retains Spaces proposal commit
`54c9cf5153d668c4f4fb4438529967412e861775`. The pinned alpha credential is a
compact JWT with `typ=atproto-space-credential+jwt`, `alg=ES256K` or `ES256`,
and `kid=#atproto_space` or the explicit SA9b fallback `#atproto`. Its payload
contains exactly:

```text
iss = Space authority DID
sub = exact Space URI
cnf.jkt = credential-specific application DPoP-key thumbprint
iat / exp
jti
```

It deliberately has **no `aud` claim**. The proposal defines one credential as
multi-use across repo hosts serving the Space. The fixture profile supports the
proposal's documented default 7,200-second lifetime exactly; another lifetime
fails closed as unsupported alpha input.

## Qualification boundary

```text
SA9c exact authority DID document
        ↓
SA9b Space signing-key selection + Space-host selection
        +
SA9d-b delegation receipt for the applicant and exact Space
        +
credential-specific public DPoP key
        +
runtime-only Space credential JWT
        ↓
SA9d-c credential qualification
        ↓
secret-free SpaceCredentialReceipt
```

The authority key may be the dedicated `#atproto_space` key or SA9b's explicit
fallback `#atproto`; the JWT `kid` must match the selected path. The authority
host may likewise be dedicated or fallback, with that provenance retained.
The selected network origin is issuance context only. It is not inserted into
the token as an audience and does not identify every repo host at which the
credential might later be presented.

The credential payload does not name the applicant. SA9d-c therefore records
`applicantContextDid` only from the independent matching delegation receipt.
It does not misdescribe that DID as a JWT claim. Credential issuance must occur
inside the delegation token's validity interval.

## What SA9d-c proves

For supplied fixture evidence, qualification establishes:

* exact credential token class, issuer, Space, absence of JWT audience,
  validity interval and bounded issuance `jti` observation;
* compact signature verification under the exact Space-authority key selected
  from the SA9c document by SA9b;
* `cnf.jkt` equality with the supplied credential-specific ES256 DPoP public
  key;
* exact SA9c authority-document, SA9b key/host, and SA9d-b delegation receipt
  composition; and
* the pinned credential's protocol meaning: whole-Space read/sync, no write.

The receipt records credential SHA-256 and `ath`, key thumbprint, authority and
Space, applicant context, key/host/resolution/delegation receipt IDs, access and
audience semantics, time, and exact verified claims. Raw credential text and
the DPoP private scalar remain in redacted, non-serializable runtime wrappers.

## What SA9d-c does not prove

It does not prove why or under what application policy the authority admitted
the request, that the applicant DID is embedded in the credential, globally
current DID state, live host acceptance, a repo host's identity, complete
history, Space membership, community standing, user intent, per-occurrence
governed authorization, artifact validity, repository currentness, or
governance authority.

The distinctions remain:

```text
delegation request
    != authority admission policy/decision evidence
    != signed Space credential
    != live credential acceptance
    != community standing
    != governed authorization
```

A valid credential is protocol access evidence under the bounded supplied
identity and time evidence. It is not a membership or governance record.

## Replay semantics

The credential itself is multi-use. SA9d-c's finite replay window applies only
while processing issuance results: seeing the same issuer/credential `jti`
twice in that bounded result domain refuses duplicate qualification. It is not
a prohibition on presenting one qualified credential to several repo hosts.
Each eventual protected-resource request needs its own fresh DPoP proof and
`jti`; that belongs to SA9d-d.

## Witnesses

Positive fixtures cover dedicated key/host selection, explicit account-key/PDS
fallback, exact Space/authority/applicant-context binding, delegation issuance
timing, `cnf.jkt`, whole-Space read/sync semantics, no write, deterministic
receipt replay, and secret-free provenance.

Hostile fixtures refuse wrong token type/key, Space, authority, expected
applicant, injected JWT audience, invalid/stale/future/delegation time, invalid
`jti`, DPoP-key and authority-key substitution, bounded issuance replay,
authority-host/resolution substitution, runtime credential substitution, and
attempts to relabel access as membership, standing, governance authority,
effect authorization, or write permission.

## Evidence and replacement boundary

`tests/fixtures/spaces-alpha/sa9d-c-credential.json` contains public identifiers
and receipt/credential digests only. The credential and synthetic signing/DPoP
private values are constructed in test memory. Fixture SHA-256:
`af024a97b619bc4ec2dee72ac2e085b7bd4086dfcb1db447dd4420bc86e8c8ba`.

A future authority-response adapter may supply the same runtime credential and
existing bounded receipts without changing SA9d-b, SA9b/c, SA1–SA8, public
ATProto, or governance semantics.

## Deferred

Client attestation, a live `getSpaceCredential` request/result, nonce challenge
transport, credential-bound HTTP acquisition, persistent session state,
membership, governance, writes, and deployment remain outside SA9d-c.
