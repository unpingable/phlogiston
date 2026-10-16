# SCV0-L10 — disposable Lexicon and Space bootstrap

Status: **fixture-qualified; hosted execution blocked by explicit OAuth denial**
(observed 2026-08-25)

L10 is the one-time authority bootstrap for the Juniper disposable alpha. It
does not participate in ordinary author, moderation, observation, publication,
or rendering operation.

## Compatibility correction

The first D2 spellings used
`network.bsky.spaces-alpha.neutralautomation.juniper.<name>`. The exact pinned
ATProto parser interprets every segment except the last as the reversed NSID
authority, producing
`juniper.neutralautomation.spaces-alpha.bsky.network`. Credential-free hosted
checks found that handle unresolved and its HTTPS name outside the hosted
certificate.

No old-spelling Lexicon or Juniper record was published. L10 therefore uses
single terminal names under the authority already frozen by D2:

```text
network.bsky.spaces-alpha.neutralautomation.juniperCommunity
network.bsky.spaces-alpha.neutralautomation.juniperPermissions
network.bsky.spaces-alpha.neutralautomation.juniperPost
network.bsky.spaces-alpha.neutralautomation.juniperSubmission
network.bsky.spaces-alpha.neutralautomation.juniperAdmission
network.bsky.spaces-alpha.neutralautomation.juniperRemoval
network.bsky.spaces-alpha.neutralautomation.juniperWithdrawal
```

All derive `neutralautomation.spaces-alpha.bsky.network`, which resolves over
the hosted alpha's HTTPS handle path to the frozen authority DID
`did:plc:ccqpqqfk4ihtbimtbomhnjle`. The correction changes no record schema,
consent, role, lifecycle, or exact-reference meaning. Old spellings are not
aliases.

## Two-session bootstrap

Lexicon publication uses only:

```text
atproto repo:com.atproto.lexicon.schema?action=create
```

The package loads exactly seven files, checks their complete canonical SHA-256
against source-pinned constants, publishes each at deterministic `rkey = NSID`,
and performs no hidden retry. A failed create may be settled only by exact
URI/value readback; conflict refuses.

After the Space and permission Lexicons resolve, Space creation uses a fresh
OAuth session with only:

```text
atproto space:<exact-type>?authority=<exact-DID>&skey=self&manage=create
```

It creates exactly the frozen Space URI with `publicPolicy` and open app
access. An ambiguous create is accepted only when `getSpace` returns that exact
URI and configuration. The two OAuth profiles use separate secret-store
directories. Raw sessions remain runtime-only.

## Claims and non-claims

L10 can establish that the pinned Lexicon documents occupy their exact public
repository paths and that the hosted service reports the exact public/open
Space configuration. It does not establish membership, community standing,
moderator authority, admission, artifact validity, governance authority, human
comprehension, or production readiness.

The bootstrap package is absent from the browser, `communityd`, observer, and
renderer dependency graphs. It has no Space-record writer RPC and cannot emit
any Juniper post, submission, admission, removal, or withdrawal.

## Pinned upstream

* ATProto Spaces reference: `89deb9faca20e56fa2a262fe9746ed52bc1095ba`
* Spaces proposal observation: `54c9cf5153d668c4f4fb4438529967412e861775`
* Node alpha packages: `spaces-alpha-20260818163953`

The live commands are deliberately operator-supervised and produce safe JSON
only. Their callback origin must be explicit IPv4 loopback. `auth-listen`
consumes the one-shot callback locally so that authorization codes and state do
not cross chat, logs, or operator copy/paste. Its listener expires after a
bounded 30-minute operator window. Live receipts are not committed if they
contain deployment-specific custody context.

Refusals expose only allowlisted error classes, OAuth error codes, and HTTP
status where available. Callback parameters, authorization codes, tokens,
exception messages, response payloads, and URLs are excluded.

## Hosted-alpha compatibility evidence

The disposable hosted authority successfully resolved, PAR completed, and the
authorization UI displayed the exact create-only grant. On repeated immediate
operator approval, the hosted authorization server redirected with the
standard OAuth result `error=access_denied`. The safe receipt was:

```json
{"error":"juniper_bootstrap_refused","classification":[{"kind":"oauth_callback_error","phase":"authorization_error","issuerParameter":"present","oauthError":"access_denied"}]}
```

No authorization code, access token, refresh token, or stored session survived
that result. Public server metadata advertised the ATProto profile, and the
pinned permission grammar accepts
`repo:com.atproto.lexicon.schema?action=create`; the Lexicon specification also
defines schemas as ordinary public records in that collection. The hosted
alpha nevertheless denied this bounded account grant. L10 therefore classifies
the hosted path as an upstream/deployment compatibility blocker rather than
requesting `transition:generic`, an app password, or a broader repo grant.

This is not evidence that the account lacks identity, that Lexicon publication
is generally invalid, or that a broader credential would be semantically
acceptable. A separate disposable Spaces-capable PDS is the bounded fallback;
the existing `juche.social` PDS must not be modified for convenience.
