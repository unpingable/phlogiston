# SCV0-L9 — supervised qualified projection publisher

**Status:** fixture-qualified 2026-08-24; live process not deployed yet.

L9 composes the existing boundaries into one explicit observer operation:

```text
author-action discovery hint
        ↓
L8 authenticated getRepo (separate Node process)
        ↓
SA9c PLC audit + SA9b repo/Space-host bindings
        ↓
SA2 CAR framing → SA1 state qualification
        ↓
SA6 bounded reconciliation
        ↓
L7 M1/M2/M5A/M6A compiler
        ↓
atomic public projection generation
```

The separately installable `communitywatch-live` package is an
observer/publisher. It has no ATProto writer, signing key, browser session, or
`communityd` dependency. L8 owns its own OAuth/session directory and writes
immutable private CAR and acquisition receipts; L9 receives only their paths
and safe receipt fields.

## Exact composition gates

Before SA1 qualification, L9 requires:

- the L8 receipt identifier recomputes from its exact canonical fields;
- the spooled body's SHA-256 and byte count match the receipt;
- zero hidden artifact retries and zero redirects;
- the configured exact Space appears in the receipt;
- the artifact request origin equals the independently SA9c/SA9b-qualified
  account repo host;
- exactly one successful credential-exchange attempt appears in preserved
  order and its origin equals the independently qualified Space-authority
  host; and
- the SA9b-selected account signing key verifies the unchanged SA1 commit.

HTTP success, DPoP binding, origin matching, CAR framing, and SA1 qualification
remain separate claims. None is sufficient alone.

## Reconciliation and publication

Every immutable CAR is qualified independently. Equal observations remain
acquisition evidence but do not create semantic transitions. Stale,
same-revision-conflicting, or cross-context qualified state refuses rather
than replacing the retained head. An unavailable author may yield the existing
explicit `unavailable` lifecycle only when prior qualified state exists. An
unavailable community repo is a hard publication refusal.

The compiler receives only qualified histories and separately parsed safe
`communityd` receipts. L7 publishes an immutable generation and atomically
updates `current`. Nothing becomes public before re-observation and
qualification.

The author action journal is a discovery hint only. It cannot establish source
records, completeness, admission, authorization, currentness, or authority.

## Evidence and non-claims

Private observer custody retains exact PLC audit bytes, L8 CAR bytes, their
bounded acquisition receipts, SA1 snapshot custody, SA6 relationship receipts,
and run receipts. Public output contains only compiled projection artifacts.
OAuth tokens, delegation tokens, Space credentials, DPoP private keys/proofs,
raw permissioned repos, and observer evidence do not enter the public bundle.

L9 establishes that retained transport evidence passed the existing identity,
container, cryptographic, reconciliation, lifecycle, and disclosure boundaries
before publication. It does **not** establish complete history, global
currentness, standing, governance authority, product comprehension, or
production readiness. Repetition does not upgrade confidence. Qualified PLC
audit evidence still does not prove that no newer valid operation exists.

The product-comprehension gate remains downstream. A technically uninvolved
person must exercise the deployed lifecycle without coaching, and their
verbatim explanation must be recorded before the intended model is explained.
L9 cannot satisfy that human criterion.

## Witnesses and replacement boundary

PLC redirects, duplicate-key/malformed JSON, DID substitution, non-boolean
nullification, CAR mutation, credential-exchange host substitution, receipt
mutation, and caller completeness labels refuse. Empty discovery publishes
nothing. Supervisor receipts retain `completeHistory=false` and
`governanceAuthority=false`.

The retained SA9e hosted-alpha CAR is the positive external witness: it passes
L8 custody and replays through unchanged SA2 and SA1 qualification.

The command-based L8 adapter, PLC HTTP implementation, process supervisor, and
publication target may be replaced independently. Replacement may not change
SA1–SA10d, M1/M2, or public-artifact semantics. A future listRepoOps
optimization cannot manufacture history or replace full-repo recovery.
