# SA9d-d — authenticated acquisition composition

Status: fixture-qualified on 2026-08-21. Compatibility remains pinned to the
Spaces proposal at `54c9cf5153d668c4f4fb4438529967412e861775` and the
SA9d-a OAuth/RFC 9449 profile.

> Authenticated transport changes acquisition provenance, not artifact meaning.

## Boundary

SA9d-d consumes an SA9d-c qualified Space credential and its credential-bound
P-256 key. It constructs a GET DPoP proof binding `htm`, the exact `htu`,
`iat`, `jti`, and `ath`; a server nonce is bound when supplied. A separate
read-only HTTP adapter performs exactly one request, refuses redirects, performs
no retry, bounds response bodies, and emits the unchanged SA7 CAR or operation
page artifact. Receipts retain credential/proof digests, public-key thumbprint,
request target, status, response digest, and nonce digest. Token plaintext,
private keys, DPoP JWTs, and authorization header values are runtime-only.

The localhost profile is an explicit deterministic fixture exception. It does
not relax HTTPS for non-loopback targets.

## Explicit nonce attempts

A nonce challenge is a completed acquisition attempt with its own receipt. The
caller must construct a second proof with the returned server-scoped nonce and
a fresh `jti`, then make a second visible request. Nothing mutates the first
receipt and the transport has zero automatic retries. The alpha proposal does
not itself establish a universal nonce challenge for every repo request; this
campaign qualifies the RFC/ATProto challenge behavior when exercised.

## Guarantees and non-claims

SA9d-d proves which credential-bound request was made and which bytes/status a
bounded endpoint returned. Tests show the same CAR bytes retain the existing
SA2/SA1 result and operation JSON retains the existing SA5 interpretation.

It does not prove service identity, live credential validity beyond the local
verification inputs, artifact validity, repository currentness, complete
history, membership, standing, governance authority, user intent, or effect
authorization. HTTP success remains acquisition evidence. SA2–SA8 remain the
only artifact/state/transition/recovery qualifiers.

## Replacement boundary

`credential_request.py` owns credential-DPoP request binding.
`authenticated_acquisition.py` owns the replaceable HTTP attempt. Neither
changes SA7 or any downstream evidence semantics.
