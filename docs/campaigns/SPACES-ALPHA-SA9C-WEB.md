# SA9c-web — did:web resolution provenance

Status: deterministic transport/profile qualification, 2026-08-21.

## Guarantee

For the production profile, SA9c-web derives exactly
`https://<hostname>/.well-known/did.json`, makes one GET with ordinary platform
WebPKI verification, `Accept-Encoding: identity`, bounded time/body/redirect
limits, and no credentials, cookies, or hidden retries. It refuses cross-origin
redirects and insecure downgrade, parses unambiguous UTF-8 JSON, requires the
returned document `id` to equal the requested DID, and binds the exact response
bytes to its receipt.

The corresponding claim is bounded:

> The origin encoded by this hostname-level `did:web` served these exact bytes
> during this acquisition under ordinary HTTPS/WebPKI validation.

The deterministic socket suite uses only an explicitly enabled encoded-port
loopback profile. That profile uses HTTP, records
`development_loopback_acquisition`, and does **not** claim WebPKI verification.

## Refusals

The ATProto profile refuses path DIDs. Localhost and encoded ports fail outside
explicit development mode. DID mismatch, duplicate JSON keys, HTML/error data,
oversize or truncated bodies, transformed content encodings, cross-origin
redirects, and receipt/body mutation all fail closed. Repeated acquisitions
remain separate observations even when both documents are internally valid.

## Non-claims

HTTPS is not historical continuity, perpetual domain control, DNSSEC, proof of
absence of compromise, migration continuity, global currentness, artifact
validity, authorization, or governance authority. Caller labels cannot add
those claims.

## Alpha/profile pin and replacement boundary

Hostname-only ATProto behavior is pinned to `https://atproto.com/specs/did` as
observed 2026-08-21; URL derivation follows the did:web specification observed
the same day. Acquisition policy lives solely in `did_web.py`. Replacing it
does not alter SA9b selection or SA0–SA9a evidence semantics.
