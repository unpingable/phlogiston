# SCV0-D1 — reader projection contract

Status: **product topology frozen; documentary contract only** on 2026-08-22.

SCV0-D1 selects the product shape called **D: community-owned projection,
shared rendering layer**. This is the escape hatch between a community and an
application operator:

```text
qualified source/community records
        ↓
community-owned projection decision
        ↓
exact disclosure-scoped projection artifact
        ↓
replaceable shared renderer
        ↓
reader presentation
```

The renderer is a window. It does not become the community, observer,
moderator, source host, or disclosure authority.

This document defines the artifact the renderer may eventually consume. It
does not define a network format, API, signature algorithm, server, session,
cache, or user interface. The conceptual field names below are contract roles,
not a published Lexicon or committed serialization.

## Why topology D

Topology D keeps the authority-bearing decision on the community side while
allowing rendering to become convenient or shared later:

- a community can replace the renderer without recreating admissions;
- a renderer can serve many communities without acquiring their moderator or
  Space credentials;
- a renderer failure or product shutdown does not become the canonical
  projection history;
- a community chooses the exact disclosure artifact rather than relying on a
  shared service to infer what its read access permits it to rebroadcast; and
- a local proof can exercise compilation and rendering with synthetic data
  before reader authentication or production custody is chosen.

This does not make shared infrastructure neutral. A renderer can omit,
misrender, track readers, or retain artifacts. The contract only prevents those
behaviors from becoming community admission authority.

## Contract doctrine

```text
community admission       != projection publication
projection publication    != renderer authority
renderer possession       != reader authorization
source presentation copy  != source ownership
artifact timestamp        != source currentness
receipt reference         != receipt qualification
```

The community owns two distinct decisions:

1. which exact source occurrence is in its projection, already represented by
   M1/M2 admission and lifecycle values; and
2. which bounded representation of that projection is disclosed under one
   publication occurrence.

The second decision cannot be inferred merely because an observer can read the
Space or because an M2 item is `Added`.

## Community Projection Feed

The conceptual top-level object is `CommunityProjectionFeed`. A later exact
wire milestone must preserve these roles or return to design review.

### Contract identity

- `contract_version`: exact projection-contract compatibility profile;
- `artifact_id`: deterministic digest over the complete normalized artifact;
- `community_identity`: exact M1 `CommunityIdentity`, including Space and
  community actor;
- `projection_identity`: stable community projection identifier;
- `reducer_version`: exact M2 reducer profile used for lifecycle states;
- `disclosure_profile`: exact identifier for the selected field/audience
  budget;
- `publication_occurrence_id`: reference to the community-owned publication
  decision binding this exact artifact and disclosure profile; and
- `assembled_at`: retained acquisition/assembly context only, excluded from
  claims of source or authorization currentness.

`artifact_id` must not use a random ID, mutable counter, or wall-clock time as
its semantic identity. Artifact order, fields, lifecycle values, disclosed
presentation bytes, receipt references, and publication binding must all be
covered by it.

### Feed items

Every `CommunityProjectionItem` retains:

- deterministic item identity;
- exact community identity;
- exact M1 post reference ID;
- Space identity, author DID, collection, rkey, canonical Space URI, and exact
  admitted CID;
- exact submission, admission, and M2 lifecycle state IDs;
- lifecycle state and the source relationship it represents;
- admission time and current source-observation identity;
- bounded disclosed presentation, when the disclosure profile permits it;
- presentation payload digest and presentation compatibility profile;
- source, admission, authorization, lifecycle, and translation receipt
  references needed by the selected explanation budget; and
- explicit non-claims.

The artifact never changes an M1/M2 value. It copies their identities and
bounded presentation into a disclosure envelope.

## Lifecycle inclusion rules

The renderer receives a community projection, not the moderation queue:

| M2 state | Feed treatment | Non-meaning |
| --- | --- | --- |
| `Suggested` | excluded | suggestion is not community publication |
| `Added` | included with the exact disclosure-approved source presentation | renderer owns or independently admitted the source |
| `ChangedAtSource` | lifecycle entry/tombstone; no substituted new-CID content | changed source is implicitly readmitted |
| `SourceUnavailable` | lifecycle entry/tombstone under the declared unavailable/absent flavor | community removed the source |
| `Removed` | removal entry/tombstone retaining admission/removal identity; no source payload | source record was deleted or history erased |

Reverting to an old CID does not revive an old `Added` artifact. A genuinely
new submission/admission creates a new occurrence and feed item.

Whether an ordinary product view displays lifecycle tombstones or only exposes
them through “Why is this here?” is presentation policy. The artifact must
retain enough state for either presentation without rewriting history.

## Bounded source presentation

A useful renderer cannot fetch raw author repositories, so an `Added` item may
carry a bounded presentation of the exact qualified admitted source version.
That presentation is a disclosed copy, not a community authority record or a
replacement source object.

The presentation boundary must bind:

- the exact source URI and CID;
- a presentation compatibility profile;
- exact disclosed fields or bytes;
- a digest of those bytes; and
- the source-qualification receipt reference supporting their derivation.

Presentation fields cannot affect admission, lifecycle state, ordering, or
authority. Titles, summaries, author labels, previews, media hints, and similar
values remain presentation. Unknown fields must not become moderator,
membership, ranking, or disclosure claims.

OQ-8 still blocks a permanent post schema. A fixture compiler may use an
explicit `test.invalid.*` presentation profile; D1 does not define the live
content schema or extraction rule.

## Disclosure profiles

One feed artifact has one exact disclosure profile. The renderer may present a
subset for UX, but it may not combine artifacts or fields to exceed that
profile and call the result community-approved.

At minimum, a future profile must distinguish:

### Ordinary projection

Enough information to render the community item and explain its lifecycle in
ordinary language. It need not expose internal moderation evidence, raw
cryptographic material, or every receipt identifier.

### Technical audit projection

Exact source URI/CID, Space/community identities, state/admission/removal IDs,
and only the receipt references the community explicitly chose to disclose.
Receipt references remain pointers, not proof that the renderer independently
qualified them.

Ordinary and audit disclosure may be separate artifacts with separate IDs and
publication occurrences. A renderer cannot derive the audit artifact from a
weaker ordinary artifact or use the existence of one as authorization for the
other.

The audience semantics for live artifacts remain unresolved under OQ-9. A
future publication may be public, Space-access-bound, community-policy-bound,
or otherwise scoped only after a formal human decision. `disclosure_profile`
does not itself authenticate a reader.

## Community-owned publication binding

For live use, the renderer must receive evidence that the community chose to
publish this exact artifact under this exact disclosure profile. The future
publication binding must cover at least:

- community identity and community-actor role;
- artifact ID;
- disclosure profile/audience-policy reference;
- one publication occurrence identity;
- publication time as event context, not source currentness;
- compatibility profile; and
- authority/signature provenance appropriate to the later chosen transport.

D1 does not define or issue that authority record. OQ-10 still blocks live
community capability custody. A synthetic/local compiler must label any
publication reference as a fixture placeholder and cannot claim community
signature or live disclosure authorization.

## Renderer contract

A conforming shared renderer may:

- parse one supported projection-artifact version;
- validate deterministic artifact integrity;
- preserve community, item, lifecycle, disclosure-profile, and publication
  identities;
- apply only explicitly declared presentation rules;
- render ordinary explanations and technical references that the artifact
  actually contains; and
- report unsupported, invalid, missing, or conflicting artifacts without
  inventing a plausible view.

It must not:

- read raw author or community repositories;
- hold OAuth tokens, DPoP private keys, delegation tokens, Space credentials,
  cookies, or moderator/community-writer capability;
- decide, synthesize, or rewrite admission/removal;
- turn `Suggested` into published content;
- replace source URI/CID or changed-source content;
- infer membership, standing, reader access, or disclosure authorization;
- add ranking, score, popularity, or ordering authority;
- strengthen receipt references into independently verified claims;
- silently merge conflicting artifacts or choose “latest received”; or
- expose the artifact through the existing unauthenticated public AppView
  merely because it can render it.

Renderer caches, if ever authorized, are copies of exact artifacts and remain
bound to artifact, community, disclosure profile, and later audience/session
policy. Cache possession is never authority.

## Mechanical ordering

SCV0 retains reverse chronological ordering by exact admission time as the
only V0 view policy. A later artifact serializer must use a deterministic
tie-break over exact admission/item identity. This is mechanical presentation,
not popularity or ranking, and cannot alter lifecycle eligibility.

## Replacement and portability boundary

The artifact exists specifically so a renderer can be replaced:

```text
community compiler ── projection artifact ── renderer A
                                      └───── renderer B
```

Given identical supported artifact bytes, conforming renderers must preserve
the same item eligibility, source references, lifecycle labels, and disclosed
receipt references. CSS, layout, and accessible presentation may differ.
Renderer-specific accounts, metrics, cache keys, or database identifiers may
not enter artifact identity.

The community remains responsible for the publication decision. The renderer
remains responsible for faithful presentation and, once separately selected,
reader delivery enforcement. Neither role inherits the other's authority.

## Proposed bounded successor experiments

These names are non-authorizing and avoid reusing D0's already assigned M6
identifier:

1. **SCV0-M5A — fixture projection artifact compiler.** Pure/local conversion
   of synthetic M1 records plus M2 states into one deterministic D1 artifact.
   No server, reader auth, credentials, live data, or authority signature.
2. **SCV0-M5B — local fixture renderer.** Consume only the M5A artifact and
   render Added/ChangedAtSource/SourceUnavailable/Removed plus “Why is this
   here?” locally. No accounts, network, cache, or permissioned data.

D0 already uses `SCV0-M6` for a sacrificial multi-identity trial blocked on
OQ-8–OQ-10. D1 does not silently repurpose that milestone as a renderer.

## Governance and stop boundary

The operator's product-direction message selects topology D for design work.
Under the repository's open-question register, OQ-9 cannot become
mechanically `decided` without an antecedent packet, required change set, and
authenticated external decision receipt. None is fabricated retroactively.

Therefore:

- D is frozen as the SCV0 product topology;
- synthetic/local M5A/M5B may be separately proposed;
- no live projection publication, shared serving, reader session, or human
  trial is authorized;
- audience authentication, disclosure policy, retention, and revocation remain
  for the formal OQ-9 decision; and
- OQ-8 and OQ-10 continue to block live schema and authority custody.

This is the intended stop: define the glass handed to the window maker, then
do not build the window until a separately bounded implementation task exists.

## SCV0 V0 OQ-9 addendum — 2026-08-22

The operator later made the bounded V0 product decision recorded in
`SPACE-COMMUNITY-SCV0-OQ9.md`: public projection artifacts with
community-controlled publication. That decision supersedes D1's stop only for
separately authorized synthetic/local public feed and browser experiments.

It does not select any of M4's permissioned-reader models. Private reader
sessions, membership, reader credentials, Space read grants, invitations,
revocation, private projection serving, authenticated feeds, confidential
discussion, and live permissioned-data disclosure remain deferred. The
renderer still receives only the published artifact and no raw source repo or
authority capability.
