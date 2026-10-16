# SCV0-L4 — live browser and public-artifact surface

Status: local real-socket qualification complete 2026-08-24.

## Product surface

The Juniper browser process now presents the useful community feed first,
supports ATProto OAuth entry, creates and self-submits exact author-owned post
versions, provides a source edit/delete activity view, exposes author
withdrawal when an exact admission record reference is present, and renders
plain-language “Why is this here?” explanations with a secondary technical
receipt page.

Routine pages use no CAR, LtHash, DPoP, or qualification vocabulary. The
activity page deliberately places source state beside community state so an
author can exercise the edit-after-admission reveal without an architecture
lecture.

## Public artifact boundary

The renderer reads only atomically published `ordinary.json` and `audit.json`
M6A feed envelopes. It checks the embedded artifact digest, channel/mode
binding, occurrence parity between channels, bounded size, lifecycle values,
and secret-shaped material. It does not read a Space, observer database,
writer credential, or moderator decision queue.

An author-side record write updates only the private bounded activity store.
It never inserts an optimistic feed item. A visible change must arrive through
the separately qualified publisher.

## Custody

The browser session cookie is opaque and HttpOnly/SameSite; POST routes also
require the configured exact Origin. OAuth sessions and the author action log
are mode-0600 runtime files under separate paths. Safe error pages disclose no
exception details or secret-bearing objects.

## Witnesses

A real loopback HTTP test demonstrates feed-first rendering, plain-language
progressive disclosure, an authenticated exact create/submission pair, no
optimistic projection, and cross-origin POST refusal. Feed tests reject
artifact mutation, disclosure-channel disagreement, and secret-shaped
publication. Activity tests retain the admitted source occurrence across
later source edits/deletion and refuse cross-author mutation.

No live OAuth ceremony, Space credential, community decision, observer, or
deployment is claimed by L4.
