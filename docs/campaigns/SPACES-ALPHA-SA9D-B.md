# Spaces alpha SA9d-b — delegation-token qualification

**Status:** fixture-qualified on 2026-08-21. No live token acquisition,
client attestation, Space credential, network request, writer, governance
integration, or deployment was added.

> **Delegation proves only that the user's PDS delegated this application to
> request access to this exact Space. It is not a Space authority admission
> decision.**

## Compatibility pin

SA9d-b retains Spaces proposal commit
`54c9cf5153d668c4f4fb4438529967412e861775`, independently of the authoritative
OAuth/RFC pins used by SA9d-a. The alpha proposal defines a delegation JWT with:

* `typ=atproto-space-delegation+jwt`;
* `alg=ES256K` or `ES256` and exactly `kid=#atproto`;
* `iss` equal to the user DID;
* `sub` equal to the complete Space URI;
* `aud` equal to `{space-authority-DID}#atproto_space_host`;
* integer `iat`, `exp`, and a random single-use `jti`;
* no `lxm` claim; and
* a signature by the account `#atproto` signing key.

The bounded fixture profile supports the proposal's documented default
60-second lifetime exactly. A different lifetime fails closed rather than
being guessed. This is a deliberately narrow alpha compatibility limit, not a
claim that the proposal permanently forbids other short lifetimes.

The `aud` value names the logical Space-host service fragment even when SA9b
would select a fallback PDS network origin. The JWT audience, DID-document
service selection, and actual network endpoint remain separate receipts.

## Qualification boundary

`delegation.py` composes existing evidence rather than replacing it:

```text
SA9c exact user DID document
        ↓
SA9b account #atproto key selection
        +
SA9d-a returned OAuth read grant + exact DPoP getDelegationToken request
        +
runtime-only compact delegation JWT
        ↓
SA9d-b signature/claim qualification
        ↓
secret-free DelegationTokenReceipt
```

SA9b gained one additive `ACCOUNT_SIGNING_KEY` interpretation profile so the
ordinary `#atproto` key can be selected without mislabeling the user as a Space
authority. SA9d-a gained only recognition of the pinned read-only
`getDelegationToken?space=...` target. It requires a whole-Space `read` grant;
`read_self` cannot be laundered into delegation-token acquisition.

The receipt binds the token digest, issuer, exact Space, audience, algorithm,
key identifier, validity interval, `jti`, account-key receipt, method-specific
SA9c receipt and method, OAuth grant receipt, DPoP request receipt and key
thumbprint, scope-evaluation receipt, bounded replay domain, evaluation time,
and exact verified claims. The raw JWT remains in a redacted, non-serializable
runtime wrapper.

## What SA9d-b proves

For the supplied fixture evidence, qualification establishes:

* the compact JWT has the exact alpha delegation header/payload class and no
  service-auth `lxm` claim;
* `iss`, `sub`, and `aud` match the supplied user, Space, and logical Space-host
  audience;
* the token is inside the supported 60-second fixture window and its `jti` was
  not previously observed in the supplied finite replay domain;
* its compact signature verifies under the account `#atproto` public key
  selected from the exact SA9c document by SA9b; and
* its acquisition context is the same returned OAuth grant and exact SA9d-a
  DPoP-bound `getDelegationToken` request covered by a protocol `read` grant.

The token does not cryptographically identify the client application. The
receipt merely binds the independently observed OAuth/DPoP request context in
which this token result was qualified. Alpha client attestation is a later,
separate credential class.

## What SA9d-b does not prove

It does not prove an authentic browser/OAuth ceremony, live PDS issuance or
acceptance, global single use, client identity, Space-authority admission,
Space credential issuance, present Space access, membership, community
standing, user intent, per-occurrence governed authorization, artifact
validity, repository currentness, or governance authority. A directory or
network timestamp is not introduced. A delegation cannot be converted into a
Space credential or governance receipt.

## Positive and hostile witnesses

Positive fixtures qualify the exact ES256 delegation, account-key and SA9c
document provenance, covering OAuth `read`, exact DPoP request, time/audience/
Space bindings, bounded single use, deterministic receipt replay, and
secret-free provenance.

Hostile fixtures refuse wrong `typ`/`alg`/`kid`, an `lxm`/extra claim, wrong
issuer, Space or audience, invalid/expired/future time, invalid or replayed
`jti`, signature and account-key substitution, `read_self` laundering,
`getRepo` relabeling, resolution/OAuth/request-context substitution, runtime
token substitution, and attempts to relabel the receipt as admission or
governance authority.

## Evidence and replacement boundary

`tests/fixtures/spaces-alpha/sa9d-b-delegation.json` contains only public
identifiers and receipt/token digests; the JWT and both synthetic private keys
are generated in test memory. Fixture SHA-256:
`ac1db8730abf43c4b91e3d03e01ee34f51cb710cb24a5002b7515a202c595be0`.

A future token response adapter may produce the same runtime token plus
existing OAuth/DPoP/identity inputs. Replacing that adapter cannot alter SA9b,
SA9d-a, SA1–SA8, public ATProto, or governance semantics.

## Deferred

Live `getDelegationToken`, client attestation, `getSpaceCredential`, Space
credential qualification, credential-bound DPoP, authenticated acquisition,
persistent replay state, membership, governance, writes, and deployment remain
outside SA9d-b.
