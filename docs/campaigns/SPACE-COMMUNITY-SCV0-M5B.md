# SCV0-M5B — Local fixture renderer

Status: **implemented, local and fixture-only** (2026-08-22)

## Doctrine

```text
community-owned projection artifact
        ↓
replaceable shared renderer
        ↓
reader
```

The renderer is only a window. It is not an observer, community authority,
moderator, credential holder, reader-authorization service, or source of
lifecycle state.

## Renderer contract

Input is exactly one typed, immutable M5A `ProjectionArtifact`. Before
rendering, both implementations re-run the artifact's complete structural and
nested-value validation. Raw records, untyped mappings, and tampered artifacts
are not accepted.

Output is one immutable in-memory `RenderedPage` containing:

* the exact artifact identity;
* a renderer style and version;
* a renderer-independent `RenderedProjectionSemantics` value;
* escaped local HTML.

No file is written and no socket, server, API, database, cache, credential, or
session exists. The package imports only `community_space_artifact`; it has no
M1/M2, ATProto, Spaces, observer, writer, or authority dependency.

## Rendered lifecycle semantics

The page renders the community actor DID as a reference because M5A does not
disclose a community display-name field. It renders each artifact entry as:

| State | Local presentation |
| --- | --- |
| `Added` | Bounded disclosed title/body/author reference plus “Added by this community.” |
| `ChangedAtSource` | “Source changed” notice; no silent replacement presentation. |
| `SourceUnavailable` | Unavailability notice; no fabricated replacement content. |
| `Removed` | Community-removal notice; no removed content republication and no source-mutation claim. |

`Suggested` cannot arrive because M5A refuses to put it in a reader artifact.
The ordinary artifact therefore has no moderation-preview rendering path.

For a technical-audit artifact only, the local page adds a collapsed “Why is
this here?” section containing the receipt references and immediate lifecycle
links that M5A already disclosed. The renderer does not retrieve the receipts
or interpret their IDs as authority.

## Replaceability witness

`CompactFixtureRenderer` and `AccessibleFixtureRenderer` use intentionally
different HTML structures. For the same exact artifact they produce equal
`RenderedProjectionSemantics` and retain the same artifact identity. This
demonstrates that a renderer implementation is replaceable without moving
admission or disclosure decisions into the renderer.

A malicious or buggy renderer can, of course, display misleading HTML. M5B
does not make renderer code trustworthy. The containment property is narrower:
the renderer cannot change the immutable community-owned artifact, issue a
stronger receipt, or become the authority behind that artifact. A reader or
auditor can compare another renderer against the same artifact and its stable
semantic view.

## Executable witnesses

Positive witnesses prove:

* M5B-P1 — an `Added` ordinary artifact renders its bounded presentation and
  lifecycle notice;
* M5B-P2 — a changed artifact renders the lifecycle notice without old or new
  source content;
* M5B-P3 — a removed artifact renders the removal state without republishing
  content;
* M5B-P4 — compact and accessible renderers preserve equivalent semantics for
  the same artifact.

Additional positive coverage renders source unavailability and checks the
fixture checksum.

Hostile witnesses prove:

* M5B-H1 — a raw Space-record-shaped mapping is refused;
* M5B-H2 — credential-bearing post-compilation tampering is caught by nested
  artifact revalidation;
* M5B-H3 — rendering cannot infer reader authorization or governance
  authority;
* M5B-H4 — renderer inputs and semantic outputs are immutable and rendering
  does not alter artifact identity.

Additional witnesses prove HTML escaping, ordinary/audit separation, and
removed-audit history retention without content republication.

Fixture: `tests/fixtures/space-community/scv0-m5b.json`, SHA-256
`c2197e766e0cc876232f8b24c32e00d11b98afb6fbaf3ff054d93c1b105ab8d2`.

## Claims and non-claims

M5B proves only that independently replaceable local renderer implementations
can consume the same valid disclosure-scoped artifact and preserve equivalent
lifecycle semantics without receiving community authority.

Rendering does **not** establish:

* reader authorization or reader visibility entitlement;
* community membership or legitimacy;
* moderator or governance authority;
* source truth, ownership, or currentness;
* artifact publication authenticity;
* honest behavior by arbitrary renderer code.

The displayed `source_uri`, DID, CID, and receipt IDs are values already
disclosed by M5A. Their display creates no new identity, currentness,
authorization, or evidence claim.

## Deferred boundary

This local page is the last mechanical step authorized here. Live serving,
reader authentication, disclosure enforcement, caching, discovery, accounts,
publication signing, human trial, UI product work, writes, and deployment
remain absent. Any step that places a projection artifact before a real reader
must first resolve OQ-9's reader/disclosure authorization boundary through the
repository's human decision process.
