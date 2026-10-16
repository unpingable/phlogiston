# SCV0-M6A — Projection feed artifact boundary

Status: **implemented, fixture/local-only** (2026-08-22)

## Doctrine

```text
ProjectionArtifact
        ↓
local public-feed boundary
        ↓
PublishedProjectionFeed
```

The feed boundary publishes only an already-compiled M5A artifact. It does not
fetch source records, acquire Space data, qualify evidence, decide admission,
moderate, authenticate a publisher or reader, or authorize disclosure. Public
publication is the product policy selected by OQ-9; this fixture boundary
demonstrates its representation, not live community-signing authority.

## Contract

`ProjectionFeedPublisher` is the replaceable interface. The only implementation
in M6A, `LocalProjectionFeedBoundary`, performs no I/O and accepts one typed
`FeedPublicationRequest` binding:

* exact artifact identity;
* exact community identity;
* exact M5A publication reference;
* explicit `public_ordinary` or `public_technical_audit` channel;
* publication timestamp as context only.

It revalidates the request and complete nested artifact at publication time.
The output `PublishedProjectionFeed` retains the exact artifact object,
canonical artifact bytes digest, community/artifact/publication identities,
channel, disclosure mode, timestamp, fixed claims, and fixed non-claims. Its
canonical JSON and feed identity replay deterministically.

The channel must match the artifact's M5A disclosure mode. An audit artifact
cannot enter the ordinary channel, and an ordinary feed therefore cannot
contain technical receipt disclosure. Entry order, lifecycle state, bounded
presentation, and removal/lifecycle information remain exactly those already
selected by M5A.

## What M6A establishes

For supplied fixture values, M6A establishes only:

* the artifact passed M5A integrity checks at publication;
* the requested public channel matches its disclosure mode;
* the envelope embeds the exact canonical artifact representation;
* later artifact mutation causes the feed's recorded identity/digest binding
  to fail.

The fixture timestamp is publication provenance, not repository currentness.
The synthetic M5A publication reference is preserved but is not authenticated
as a live community signature.

## Positive witnesses

* M6A-P1 — an `Added` ordinary artifact becomes one visible feed entry with
  only its bounded presentation;
* M6A-P2 — `ChangedAtSource` remains a lifecycle change without silent
  replacement;
* M6A-P3 — `Removed` preserves the disclosed removal/audit history without
  content republication;
* M6A-P4 — two independent M5B renderers consume the exact embedded artifact
  and produce equal semantics.

Additional witnesses check deterministic JSON/identity, publication metadata,
and fixture custody.

## Hostile witnesses

* M6A-H1 — raw source-record-shaped input is refused;
* M6A-H2 — an M5A non-published `Suggested` candidate is refused;
* M6A-H3 — arbitrary moderator-authority metadata and claim upgrades are
  refused;
* M6A-H4 — mutation after publication breaks artifact identity binding;
* M6A-H5 — technical audit cannot be served through the ordinary channel;
* M6A-H6 — possession/publication cannot become reader authorization or
  membership.

Additional witnesses reject artifact/community substitution, treat timestamps
as non-currentness context, and revalidate post-construction request mutation.

Fixture: `tests/fixtures/space-community/scv0-m6a.json`, SHA-256
`981ea8fea4d68763f890a5790ec02459e35c8c391a34f08fbb52d3d691876400`.

## Non-claims

A `PublishedProjectionFeed` does not prove:

* live publisher or community authority;
* reader identity, authentication, permission, membership, or standing;
* source truth, ownership, or currentness;
* moderator legitimacy or governance authority;
* network availability, serving behavior, or production readiness.

The package depends only on `community-space-artifact` and the standard
library. It contains no transport, server, database, cache, credentials,
signing, renderer, M1/M2, observer, writer, ranking, or recommendation code.

## Replacement boundary

A future publication implementation may produce the same envelope from a
community-controlled signed publication path, but that would be a new
qualification boundary. It may not retroactively upgrade these fixture feeds.
Private reader sessions and authenticated/private feeds remain deferred under
OQ-9's future boundary.
