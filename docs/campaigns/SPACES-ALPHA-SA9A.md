# SA9a — Spaces alpha HTTP artifact acquisition qualification

**Status:** read-only, unauthenticated HTTP acquisition into the unchanged SA7
seam; deterministic real-loopback tests; no DID resolution, credentials,
service authentication, write behavior, governance, effect, AppView, or
deployment behavior. **Upstream observation date:** 2026-08-21.

## Doctrine

> **Transport success is acquisition evidence, not source authority.**

SA9a records one explicit network observation. It does not interpret the body:

```text
explicit URL + GET
        |
        v
bounded HTTP observation receipt
        |
        v
unchanged SA7 CAR or operation-page artifact
        |
        +-- CAR bytes ------> SA2 --> SA1
        `-- response pages -> SA5 --> SA4
```

SA9a terminates at SA7. The composition witnesses invoke SA2–SA8 only from
tests; `http_acquisition.py` does not import or duplicate their qualification
logic.

## Contract and guarantees

`HttpSpaceArtifactProvider` implements the SA7 `SpaceArtifactTransport`
protocol for the pinned `com.atproto.space.getRepo` and
`com.atproto.space.listRepoOps` query endpoints. It issues only GET requests.
There is no general request executor and no mutation method.

Each attempt has a caller request ID and produces a bound
`HttpAcquisitionReceipt`. A successful receipt retains:

* requested and final URLs, GET method, safe controlled request headers, HTTP
  status, selected response headers, body SHA-256 and decoded length;
* an ordered redirect chain, observation time, artifact kind, timeout, response
  bound, implementation/version, zero automatic retries, and the
  `identity-only` content-transformation policy.

The bytes hashed are exactly the bytes handed to SA7. Requests send
`Accept-Encoding: identity`; any non-identity response encoding is refused, so
wire and application bytes are not ambiguously compared. The client buffers at
most the configured limit plus one detection byte. Empty bodies, non-200
statuses, interrupted or length-mismatched bodies, unsupported encodings, and
over-limit bodies refuse with an acquisition receipt. CAR content type is
context only: valid CAR with `text/plain` is acquired, while JSON mislabeled as
CAR is acquired and then refused by SA2.

`listRepoOps` pagination is explicit rather than an automatic retry. Every page
is one visible HTTP receipt; the response cursor is encoded into the next
same-origin request without sorting or rewriting pages. SA5 alone validates the
cursor chain and decides whether retrieval is complete or partial.

## Redirect, retry, timeout, and URL policy

Cross-origin redirects are refused before the target is fetched. Same-origin
redirects are followed up to three hops and every hop is retained. Repeated
URLs cause a loop refusal; a longer acyclic chain causes a redirect-limit
refusal. Redirect URL userinfo is never followed and is redacted before the
refusal enters provenance. No redirect changes the caller-supplied SA7 source
context or confers source authority.

The primitive makes exactly one attempt and performs zero automatic retries.
Deliberate later attempts therefore remain distinct observations. Timeout is
explicit, positive, at most 60 seconds, and defaults to five seconds.

Production-shaped base URLs must use HTTPS. Plain HTTP is accepted only for a
loopback address. Because SA7 intentionally requires an HTTPS source context,
loopback tests separately supply the synthetic logical repo endpoint. The real
requested loopback URL remains in the SA9a receipt, while that logical endpoint
remains visibly caller-supplied and unverified. They are not asserted equal.

Normal platform WebPKI verification applies to HTTPS. Successful TLS proves a
connection to credentials accepted for that hostname; it does not prove that
the hostname is the correct ATProto service for a DID, author, repository, or
Space. SA9a performs no DID or service resolution and sets its corresponding
trust fields to `false`.

## Secret handling

The request model has no custom-header, token, cookie, credential, DPoP, or
session field. Controlled headers are limited to `Accept`, `Accept-Encoding`,
and `User-Agent`. Receipt response headers are allowlisted to content metadata,
ETag, and Last-Modified. `Authorization`, `Cookie`, `Proxy-Authorization`,
`DPoP`, and `Set-Cookie` values cannot enter receipts. Tests inject synthetic
secret-bearing response headers and verify they are absent from provenance,
captured logs, and request headers.

## Non-claims

SA9a does not prove DID/service binding, PDS or repo-host identity, Space
authority, author identity, artifact validity, permissioned repository state,
currentness, immediate ancestry, complete history, credential possession,
access, membership, standing, authorization, governance legitimacy, or
permission to perform an effect. HTTP 200, HTTPS/TLS, hostname, content type,
headers, redirect success, receipt time, and repetition cannot mint any such
claim. Receipt trust fields for DID binding, source authority, artifact
validity, currentness, authorization, and governance authority are fixed to
`false`.

Transport can retain bytes representing an empty repository, but the existing
SA1 per-record receipt model cannot qualify that state. SA9a does not fabricate
a record receipt; the downstream empty-state gap remains unchanged.

## Alpha assumptions and pins

SA9a inherits SA0–SA8 and pins `bluesky-social/atproto` commit
`89deb9faca20e56fa2a262fe9746ed52bc1095ba`, the alpha endpoint names and query
parameters recorded in `compat.py`, method
`stdlib-urllib-get+bounded-body+same-origin-redirects`, version `sa9a-v1`, and
fixture format `spaces-alpha-sa9a-http-vector-v1`. The proposal currently
requires a credential for normal Spaces access; anonymous/test acquisition is
the only SA9a use. Credentialed acquisition is intentionally deferred.

Upstream endpoint shapes, pagination, response media types, and authentication
requirements remain volatile. SA9a does not assert a canonical content type or
that a terminal operation response proves complete history.

## Replacement boundary and witnesses

`http_acquisition.py` is replaceable as a unit. A successor must emit the same
unchanged SA7 artifacts and cannot change SA1–SA8 evidence semantics.

HTTP1–HTTP4 cover full CAR acquisition, operation-page acquisition, explicit
multi-page ordering, and repeat-event stability. E2E1–E2E3 show unchanged
SA1, SA4, and SA8 outcomes after real HTTP acquisition. HTTP-H1–HTTP-H12 cover
cross- and same-origin redirects, loops, truncation, body bounds, media-type
confusion, operation origin drift, differing retries, timestamp laundering,
header authority injection, and secret exclusion. Additional witnesses cover
read timeout and non-identity content encoding.
