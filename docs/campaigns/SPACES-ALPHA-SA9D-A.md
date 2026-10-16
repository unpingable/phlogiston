# Spaces alpha SA9d-a — OAuth / DPoP request-binding qualification

**Status:** fixture-qualified on 2026-08-21. No network I/O, browser flow,
token endpoint, refresh, Space credential, writer, governance integration, or
deployment was added.

> **Authentication binds a credential to a request. It does not bind that
> request to governance authority.**

## Compatibility pins

SA9d-a independently pins the authoritative [ATProto OAuth
specification](https://atproto.com/specs/oauth) as observed 2026-08-21 and
[RFC 9449](https://www.rfc-editor.org/rfc/rfc9449.html). Spaces permissions
remain pinned to proposal commit
`54c9cf5153d668c4f4fb4438529967412e861775`; SA9d-a does not advance the
SA0–SA9c alpha compatibility pin.

The observed OAuth profile requires DPoP, server-issued per-session/per-server
nonces, unique proof `jti` values, ES256/P-256 support, opaque client-side
tokens, token-bound DPoP keys, protected-resource `ath`, an actually granted
scope returned in the token response, and the `atproto` scope. The local proof
window is deliberately bounded to 300 seconds old and 30 seconds future; this
is an instrument policy, not repository or governance currentness.

## Boundary and grant model

`oauth_request.py` holds one replaceable compatibility boundary:

```text
synthetic returned token context + runtime-only token
        ↓
OAuthGrantReceipt (token digest, returned scopes, subject, DPoP thumbprint)
        + runtime-only P-256 session key + server/session nonce
        ↓
exact GET + ES256 DPoP proof
        ↓
RequestBindingReceipt
```

The grant receipt records the exact returned scope string and its ordered
tokens. Requested scope is retained separately as unverified request context;
it is never evaluated as granted access. The token response `sub` must match
the expected account DID, but that fact is not community standing.

Raw access-token text and the DPoP private scalar exist only in deliberately
redacted runtime wrappers. Persistent receipts contain the token SHA-256,
`ath`, public JWK/thumbprint, proof digest, exact request, nonce digest,
`jti`, and receipt references. They contain no token, private key, refresh
token, authorization code, PKCE verifier, cookie, or authorization-header
value.

## DPoP qualification

The proof constructor and verifier require exactly:

* JWT `typ=dpop+jwt`, `alg=ES256`, and a public P-256 JWK;
* a valid compact low-S ES256 signature from the session-bound key;
* exact `htm=GET`;
* RFC 9449 `htu` binding after conservative URI normalization;
* bounded `iat` and an explicitly supplied `jti`;
* the nonce supplied for the exact resource origin and session;
* `ath = base64url(SHA-256(access_token))`;
* a permitted Space-scope evaluation for the exact `space` and `repo` query
  parameters of `getRepo` or `listRepoOps`.

RFC 9449 excludes query and fragment from the `htu` claim. SA9d-a therefore
binds the complete request URL separately in the receipt and separately checks
the security-relevant Space/repo query parameters. URL normalization lowercases
scheme/host, removes the default HTTPS port, normalizes unreserved percent
escapes, and refuses dot segments, userinfo, non-HTTPS origins, ambiguous
hostnames, and fragments. It is not origin-prefix matching.

Replay checking is an explicit finite in-memory domain. Reusing the same `jti`
in that domain refuses; this is not a claim of ecosystem-wide or durable replay
knowledge. A nonce update creates a new proof, `jti`, and receipt rather than
mutating the first attempt.

## Spaces permission semantics

The evaluator preserves `space:<spaceType>` plus `authority`, `skey`, repeated
`collection`, `action`, and `manage`. Defaults and wildcard behavior follow the
pinned alpha proposal. In particular:

* `authority` defaults to `self`, resolved against the token subject;
* `skey` defaults to `*`;
* omitted actions mean `read/create/update/delete`;
* `read` covers all repos and ignores collection;
* `read_self` covers only the subject's repo and, in the pinned proposal text,
  remains collection-constrained; `read` also satisfies a `read_self` request;
* omitted collections dynamically resolve from the current Space-type
  declaration; `spaceType=*` has an empty default;
* `manage` is parsed and preserved but SA9d-a constructs no management or write
  request.

This last `read_self` rule is intentionally taken from the pinned proposal's
matching section and examples. It is narrower than an informal summary that
would treat all read modes as collection-independent.

### Dynamic scope versus frozen governance authorization

The release witness holds both facts at once:

```text
T0 declaration [A] + bare OAuth scope
    → protocol create(B) denied

T1 declaration [A, B] + same bare OAuth scope
    → protocol create(B) permitted by the alpha evaluator

FrozenEffectAuthorization captured at T0
    → still permits only A
```

The protocol evaluator is allowed to reproduce the proposal's dynamic update
contract. It cannot convert into or mutate `FrozenEffectAuthorization`.

| Fact | Protocol meaning | Governance meaning |
| --- | --- | --- |
| OAuth `read` | covering Space read/delegation RPC grant | none by itself |
| OAuth `read_self` | collection-bounded own-repo read | none by itself |
| OAuth write grant | protocol may permit a record write | not per-occurrence authorization |
| dynamic collection default | protocol permission may widen | frozen governed authority does not |
| token `sub` | bounded OAuth account/session subject | not community standing |
| DPoP proof | possession and exact request/token binding | not user intent |
| authenticated RPC acceptance | deliberately not tested here | response still needs SA1–SA8 qualification |

## What SA9d-a proves

For supplied fixture inputs, a successful receipt establishes exactly the
returned grant observation used, the bound public DPoP key, ES256 signature,
HTTP method, normalized DPoP target, exact full request URL digest, nonce,
proof time, bounded replay observation, `ath`, subject/client references, and
the protocol-only Space permission evaluation. SA9c provenance, SA9b endpoint
selection, and SA9d-a request binding can be cross-checked while their receipt
identities remain separate.

## What SA9d-a does not prove

It does not prove the OAuth ceremony, live token validity or server acceptance,
Space credential issuance, membership, standing, user intent, governed
authorization, response validity, repository currentness, or governance
authority. It cannot send its request. It does not alter SA9a or any SA1–SA8
evidence meaning.

## Deterministic evidence and replacement boundary

`tests/fixtures/spaces-alpha/sa9d-a-oauth-dpop.json` contains only public JWK
material and digests. Tests derive a disposable scalar and token in memory from
plain synthetic labels, reproduce the proof/receipt digests, exercise
AUTH1–AUTH10, AUTH-H1–AUTH-H20 and AUTH-E2E1–AUTH-E2E3, and scan receipt/repr/
exception surfaces for the runtime token.

Fixture SHA-256:
`38c9c204e01948852831e78b448985f5495624eee8e6893e5cf6b85646aef4c8`.

A future OAuth session implementation may provide the same bounded returned
grant, runtime token, DPoP key, nonce, and request inputs. It can be replaced
without changing SA9b identity interpretation, SA9a acquisition, SA1–SA8
qualification, or governance semantics.

## Deferred

Browser/PAR/PKCE/token flows, refresh and persistence, live metadata, nonce
challenge transport, Space delegation tokens, Space credentials, authenticated
fetch, standing, authorization, effects, writes, and deployment remain outside
SA9d-a.
