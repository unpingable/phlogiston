# SA9b — Spaces alpha DID document / service binding qualification

**Status:** deterministic interpretation of bounded, supplied DID-document
bytes; optional origin comparison with an existing SA9a receipt; no DID-method
resolution, live identity fetch, credential, authenticated Spaces request,
writer, governance, effect, or deployment behavior. **Upstream observation
date:** 2026-08-21.

## Doctrine

> **Service binding interprets identity evidence; it does not create identity
> evidence.**

SA9b occupies the boundary between a supplied identity document and the
network location used by SA9a:

```text
exact supplied DID-document bytes
        |
        v
bounded document interpretation
        |
        v
service/key selection receipt
        |
        +-- selected service origin -- compare --> SA9a acquisition origin
        `-- selected public-key reference --------> future composition seam
```

Parsing, internal consistency, and selection do not prove how the bytes were
obtained. `fixture`, `caller_supplied`, and unverified/future resolver labels
remain provenance context; every SA9b receipt fixes DID-resolution authenticity
and currentness to `false`.

## Pinned upstream interpretation

The ordinary account rules are pinned to the [ATProto DID
specification](https://atproto.com/specs/did), observed 2026-08-21. SA9b accepts
only the blessed `did:plc` and `did:web` methods, requires the document `id` to
equal the expected DID, and recognizes either a relative fragment or the exact
fully qualified expected-DID fragment. A fragment qualified by another DID is
refused.

For `account_repo_host`, the ordered service array is scanned for the first
valid entry whose identifier is `#atproto_pds` and whose type is exactly
`AtprotoPersonalDataServer`. An invalid earlier candidate does not shadow a
later valid candidate; entries are never sorted or deduplicated. For supported
public signing material, SA9b accepts modern `Multikey` entries controlled by
the exact document DID and compressed public `k256` or `p256` multikey bytes.
SA9b does not validate a Space commit or credential with the selected key.

The Spaces rules are pinned to proposal commit
`54c9cf5153d668c4f4fb4438529967412e861775` and the campaign's reference commit
`89deb9faca20e56fa2a262fe9746ed52bc1095ba`:

* `space_authority_host` prefers `#atproto_space_host`; only when that fragment
  is absent does it fall back to the valid ordered `#atproto_pds` entry;
* `space_authority_signing_key` prefers `#atproto_space`; only when that
  fragment is absent does it fall back to the valid ordered `#atproto` key.

Fallback is explicit in both the selection enum and verified claim set. The
proposal does not specify a dedicated Space-host service type, so SA9b requires
a nonempty type and records it but does not infer its semantics. The alpha says
fallback applies when a dedicated entry is absent. SA9b therefore fails closed
when that exact dedicated fragment is present but all such entries are invalid;
it does not reinterpret malformed presence as absence. This conservative rule
is isolated in `did_binding.py` and is a likely alpha churn point.

## Endpoint normalization

Service endpoints are parsed with the standard URL parser and reduced to a
canonical origin: lowercase ASCII hostname (or canonical IP literal), HTTPS
scheme, and an explicit non-default port when supplied. Port 443 is elided.
Only an empty path or `/` is accepted. Userinfo, a path prefix, query,
fragment, malformed/out-of-range port, Unicode hostname input, percent-encoded
host ambiguity, and a trailing DNS dot are refused. Punycode may be supplied
in ASCII form; SA9b performs no IDNA conversion or DNS lookup.

HTTP is prohibited for identity bindings. The sole exception is an explicit
`fixture` input that opts into an insecure loopback origin, allowing real local
SA9a socket tests without weakening production-shaped documents. The exception
is recorded as `fixture_loopback_http` in the receipt.

`assess_http_endpoint_binding` compares the selected origin with both the
requested and final origins already retained by SA9a. It returns
`endpoint_match`, `endpoint_mismatch`, or `unqualified_http_acquisition`.
Requested-origin equality cannot launder a different final origin. A match says
only that SA9a contacted the origin selected from these supplied bytes; it does
not establish authentic resolution, server control, or artifact validity.

## Receipt guarantees

`DidBindingReceipt` binds its identity to:

* expected DID and exact document SHA-256;
* document provenance kind/reference and optional media type;
* interpretation profile and dedicated/fallback selection;
* selected identifier, recorded type, canonical origin or selected key
  controller/public multikey/curve;
* endpoint policy, exact structured verified claims, qualification time,
  method/version, and alpha profile.

The structured claims say only that the supplied document ID matched, a
specific ordered entry was selected, its origin was well formed or its public
multikey/controller passed the bounded checks, and whether an alpha fallback
was applied. `require_receipt_document_binding` rejects reuse with mutated
bytes or provenance. Endpoint assessments bind both receipt IDs and all compared
origins, disposition, and reason.

SA9b does **not** prove PLC operation-chain validity, did:web HTTPS provenance,
resolver authenticity, DNS authority, freshness/currentness of DID state,
remote service control, canonical PDS status, Space authority, artifact
validity, repository currentness, access, membership, standing, authorization,
governance legitimacy, or permission to write. Successful HTTPS syntax is not
service ownership, key selection is not key authenticity, and SA9a response
success is not identity evidence.

## Witnesses and replacement boundary

DID1–DID6 cover ordinary PDS binding, dedicated Space host, explicit host
fallback, dedicated Space key, explicit key fallback, and SA9a origin match.
BIND-E2E1 keeps endpoint match and independent SA2/SA1 artifact qualification
as two receipts; BIND-E2E2 represents host and key selection independently;
BIND-E2E3 retains both fallback reasons.

DID-H1–DID-H14 cover document mismatch, foreign fragments, wrong type,
forbidden URL components and scheme, invalid-dedicated ambiguity, foreign key
controller, SA9a mismatch/redirect behavior, caller relabeling, ordered
duplicates, and document mutation. Extra witnesses reject duplicate JSON keys,
ambiguous host syntax, and receipt/assessment mutation.

`did_binding.py` is the replaceable interpretation boundary. A future DID-method
resolver can produce explicitly provenance-bearing document bytes without
changing SA9a or the SA1–SA8 evidence semantics. Authentic DID resolution must
remain a separate receipt and may compose with, but may not be smuggled into,
SA9b.
