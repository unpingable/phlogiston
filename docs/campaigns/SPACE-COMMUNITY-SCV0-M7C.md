# SCV0-M7C — Human-facing synthetic showcase

Status: **implemented, republished, and byte-qualified** (revision 2,
2026-08-24)

## Why this pass exists

The M7A/M7B publication demonstrated the artifact boundary, but a blind read
correctly described it as a “specification rendered as a website.” M7C adds a
presentation layer aimed at the product question without changing the product
semantics:

> Can a visitor imagine a community that curates posts without taking
> ownership of them?

The named community, **Juniper Commons**, and all posts, people, identifiers,
and activity are fictional synthetic fixtures.

## Post-publication product reading

The showcase made the custody distinction understandable, but understanding
the mechanism is not yet a reason to visit. A useful community surface should
lead with the questions a reader or author already has:

* **What is in this community?**
* **What have communities done with my posts?**

The ordinary community view should therefore foreground the community and its
newly included material. Source/community/renderer custody is quiet plumbing
until it explains an exceptional lifecycle event: the author changed or
withdrew the source, the observer cannot presently reach it, or the community
removed its projection. An author-centric view over the same projection data
is a candidate later product slice, not authority granted by this campaign.

This reading does not resolve OQ-11. In particular, observer unavailability
must not be relabeled as intentional author withdrawal, and the current model
still has no qualified author-objection occurrence.

## Shape

```text
three exact synthetic Added artifacts
        +
one exact four-state lifecycle story
        ↓
typed M6A feeds / M6B semantic replay
        ↓
M7C human-facing renderer
        ↓
ordinary pages + separate audit pages
```

The ordinary page leads with the human proposition rather than project
terminology. It shows three plausible admitted presentations and explains
“Why is this here?” as source, community choice, and renderer. Separate pages
show `ChangedAtSource`, `SourceUnavailable`, and `Removed` without restoring
presentation fields that M5A deliberately withholds in those states.

The original 20-file M7A bundle remains byte-exact under `lab/`. M7C does not
rewrite the boundary fixture to make the showcase prettier.

## Deterministic receipt

* profile: `scv0-human-facing-synthetic-showcase/2`
* corpus ID:
  `sha256:248f97b0820707624e8f752ed6765e4feb36e99fa4aadeaf796eb19233db2e2d`
* bundle ID:
  `sha256:b8c1849636d9228450a2b6e7627bbfcee4b909e671d97922c027685f5608cb7d`
* file count: 45
* embedded M7A bundle ID:
  `sha256:9bc2a8935f1f239fbcd311287fcf3602fa4a7f1ebfd9bcada0d413dc26455b5e`

## Public witness

* site: <https://unpingable.github.io/atproto-community-demo/>
* repository: <https://github.com/unpingable/atproto-community-demo>
* publication commit: `2d4a33779c9b6d1ffa0cde27144671f1e21189af`
* generator custody commit: `0d3e8ff475ce687022db455751aa38f39ebeff93`
* GitHub Pages build: `built` (the current API returned no numeric build ID)

Revision 2 adds two plain-language disclosures without changing the frozen
machine non-claims: the showcase is designed for clarity but has not been
user-tested, and its admission/moderation authorization is synthetic. A real
community would bind the choice to its community actor and an exact
per-occurrence moderation authorization. It also replaces the densest artifact
jargon with the direct statement that the community picked the posts while
their authors still own and may change or delete them. Hosted-byte evidence is
recorded only after republication.

At `2026-08-24T20:53:39Z`, all 45 hosted bodies matched the exact locally
generated revision-2 bytes, including the manifest, checksums, ordinary and
audit feeds, every lifecycle page, and the retained M7A boundary lab.

M7C does not add an author-objection state. OQ-11 records that product decision
separately: unavailable observation is not evidence of deliberate retraction,
and author source custody does not currently imply a veto over community
inclusion.

The public repository describes the generator commit as custody evidence, not
as a public regeneration path: the generator repository remains private. The
public surface provides complete artifact inspection and byte verification;
it does not overstate source availability.

Replay with:

```text
PYTHONPATH=packages/community-space-demo/src:\
packages/community-space-artifact/src:\
packages/community-space-comprehension/src:\
packages/community-space-feed/src:\
packages/community-space-prototype/src:\
packages/community-space-model/src:\
packages/community-space-projection/src:\
packages/community-space-renderer/src:\
packages/community-model/src \
.venv/bin/python -m community_space_demo.showcase_cli OUTPUT
```

## Guarantees

M7C establishes only that:

* the showcased entries come from typed, integrity-checked projection
  artifacts and exact M6A feeds;
* the community feed contains three disclosed `Added` presentations;
* the lifecycle story binds the same exact source occurrence across all four
  states;
* ordinary pages contain no technical receipt identifiers;
* audit pages retain the independently disclosed receipt references;
* changed, unavailable, and removed pages do not republish the admitted source
  presentation;
* all navigation stays inside the static bundle and resolves to retained
  files;
* the bundle is deterministic, script-free, dependency-free in the browser,
  and checksum-covered.

## Hostile witnesses

The suite refuses or detects:

* missing or reordered lifecycle inputs;
* foreign-community/source lifecycle substitution;
* untyped corpus or base-bundle substitution;
* human-usability or authority relabeling;
* receipt leakage into ordinary pages;
* post-export byte mutation, extra files, and symlinks;
* broad or non-empty output targets;
* active script, external browser dependency, cookie, or authorization-header
  material.

## Non-claims

Visual polish is not evidence of human comprehension, usability,
accessibility conformance, desirability, or product-market fit. M7C also does
not establish live ATProto data, reader authentication or authorization,
membership, moderator or governance authority, source truth or ownership,
repository currentness, or production readiness.

The presentation metadata does not become identity evidence. The renderer
still cannot observe, admit, moderate, authenticate, write, rank, recommend,
or confer authority.
