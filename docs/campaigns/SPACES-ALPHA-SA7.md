# SA7 — Spaces alpha future transport boundary preparation

**Status:** interface and inert value types only. There is no HTTP client,
OAuth, credential, hosted account, authentication, synchronization, writer,
authority, or deployment. **Upstream observation date:** 2026-08-21.

## Architectural result

SA7 names the smallest seam at which a future transport could attach:

```text
future SpaceArtifactTransport implementation (absent)
        |
        +-- ObservedCarArtifact --------> unchanged SA2 -> SA1
        |
        `-- ObservedRepoOpsArtifact ----> unchanged SA5 -> SA4
```

`SpaceArtifactTransport` is a Python `Protocol`, not an implementation. Its
requests explicitly identify the caller's request ID, target Space, author
repository DID, method, and incremental `since`/cursor/limit settings.
Observed artifacts hold exact CAR bytes or exact parsed SA5 pages.

`TransportSourceContext` carries the endpoint, artifact reference, observation
time, and optional caller assertions about transport security or service
identity. Those assertions are labeled unverified context. The type fixes
credential-material presence, service authentication, and authority to
`false`; it has no token, key, cookie, or authorization-header field.

## Guarantees

SA7 establishes only deterministic handoff:

- `ObservedCarArtifact.sa2_input()` returns the exact supplied bytes;
- `ObservedRepoOpsArtifact.sa5_input()` returns the exact supplied page tuple;
- operation artifacts must match the explicit first-page request; and
- future implementations have one narrow provider contract for the two
  artifact forms.

Fixture tests pass SA7 artifacts through unchanged SA2/SA1 and SA5 boundaries.
Any later qualification is made by those existing layers, never SA7.

## Non-claims

Supplying an artifact does not prove CAR validity, response validity, Space or
author identity, endpoint authenticity, access, credential validity,
currentness, completeness, standing, authorization, governance legitimacy, or
permission to write. Timestamps and asserted TLS/service labels remain caller
context and do not become verified claims.

SA7 contains no concrete transport and performs no network operation.

## Alpha assumptions and pins

The interface names only the pinned
`com.atproto.space.getRepo` and `com.atproto.space.listRepoOps` methods at
`bluesky-social/atproto` commit
`89deb9faca20e56fa2a262fe9746ed52bc1095ba`. Boundary version is `sa7-v1`.
CAR semantics remain in SA2; incremental response semantics remain in SA5.

## Replacement boundary

A future transport package may implement the protocol and populate these
artifacts, subject to a separately authorized campaign. It can be replaced
without touching SA1 cryptography, SA2 CAR parsing, SA4 transition
qualification, SA5 response parsing, SA6 recovery classification, admission,
or governance. No such implementation is authorized or present in SA7.
