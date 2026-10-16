# SCV0-L3 — browser OAuth custody boundary

Status: fixture-qualified 2026-08-24; no live ceremony exercised yet.

## Boundary

Juniper uses the pinned ATProto alpha `NodeOAuthClient` with DPoP-bound client
metadata and the exact experimental permission-set include scope. Hosted
configuration exposes discoverable client metadata; explicit loopback
configuration uses the ATProto development metadata profile.

OAuth state and saved sessions live beneath a required runtime directory in
separate mode-0700 directories and mode-0600, atomically replaced files. Store
keys are SHA-256 filenames. Browser sessions use independent random opaque
cookies whose plaintext is never persisted; only the cookie digest indexes a
bounded eight-hour DID session.

## Claims and non-claims

This boundary is secret custody and client construction. It does not prove an
OAuth ceremony occurred, that any returned grant covers an operation, that a
Space credential was issued, or that a record was observed, qualified,
admitted, or published. The existing SA9d request-binding semantics remain
unchanged and authoritative for those bounded authentication claims.

No token, refresh token, DPoP private key, OAuth state, or browser-cookie value
enters a receipt, public artifact, exception message, filename, test snapshot,
or Git. Browser route integration and the first live ceremony are later steps.
