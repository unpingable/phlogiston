# SCV0-L8 — isolated authenticated artifact acquisition

Status: deterministic local-HTTP qualification complete 2026-08-24; hosted
OAuth custody and acquisition pending deployment.

## Boundary

```text
observer OAuth session (secret runtime)
  -> PDS delegation token (transient)
  -> fresh ES256 Space-credential key (transient)
  -> authority credential exchange (transient credential)
  -> one exact credential-bound GET
  -> private observer spool bytes + non-secret acquisition receipt
```

`packages/communitywatch-alpha-node` is a separately installed, read-only
acquisition process. It does not import `communityd`, the author browser app,
the projection publisher, or any shared authority model. It declares only the
pinned `getDelegationToken` query and directly performs the pinned
`getSpaceCredential`, `getRepo`, and `listRepoOps` requests. It has no ATProto
write RPC or generic arbitrary-request command.

The process uses the pinned ATProto permissioned-data packages at commit
`89deb9faca20e56fa2a262fe9746ed52bc1095ba`, published as
`0.0.0-spaces-alpha-20260818163953`. It generates a fresh P-256/ES256 key for
each acquisition command. Delegation token, Space credential, private key, and
raw DPoP proofs remain in memory and are never included in stdout, receipt
JSON, filenames, or exception output.

## Acquisition contract

Configuration supplies already-selected authority and repository-host origins.
L8 does not resolve or authenticate those origins; later composition must retain
the SA9b/SA9c receipts that selected them. Plain HTTP is refused except for an
explicit loopback-fixture profile. Requests refuse redirects, enforce time and
body bounds, request identity content encoding, and write the exact response
bytes into a mode-0600 file below a mode-0700 observer spool.

The OAuth library may perform profile-required nonce handling or one
invalid-token refresh. Each underlying OAuth-library HTTP request is captured
as a distinct safe attempt containing only ordinal, method, URL, status, and
purpose. No header or body is retained. The credential exchange and artifact
GET are separately visible attempts. The primitive artifact GET has zero
automatic retries and never follows redirects. A supervisor must represent a
later poll/retry as another acquisition request and receipt.

## Receipt claims and non-claims

The receipt binds the exact request target, exact response bytes/digest/length,
credential and delegation digests, fresh public DPoP-key thumbprint, proof
digests, safe attempt sequence, and spool filename. The generated exchange and
resource proofs are verified locally against their exact method/target,
credential hash, and public-key thumbprint before use.

This proves a bounded credential-bound HTTP acquisition attempt. It does not
prove the delegation or credential signature, authentic DID resolution,
service authority, artifact validity, Space admission, community standing,
governance authority, currentness, or complete history. The existing SA9d-b/c
qualifiers remain the authority for token claims; SA2–SA10d remain the authority
for artifact/state/reconciliation claims. A successful L8 receipt cannot make
an artifact public. L7 accepts only independently qualified states.

## Witnesses

Positive local socket witnesses cover exact CAR bytes, exact operation-page
bytes and cursor parameters, self-verification of ES256 DPoP method/target/key/
credential binding, private spool modes, bounded attempt order, and secret-free
receipt serialization.

Hostile witnesses cover cross-target redirects, oversized bodies, malformed or
authority-decorated credential responses, request-ID path escape, extra caller
fields, non-loopback plaintext origins, and serialized token/credential leaks.
HTTP status and content type remain acquisition facts only; downstream
qualification is intentionally absent from this package.

## Replacement boundary

A future OAuth implementation or hosted-alpha compatibility adapter may replace
this process while producing the same exact bytes and bounded acquisition
receipt. It must not change SA1–SA10d, M1/M2, L7 publication, or community
authorization semantics. The next bounded slice is a supervised Python process
that consumes this private spool, qualifies artifacts through the existing
pipeline, reconciles durable state, and invokes L7 only after qualification.
