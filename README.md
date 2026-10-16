# atproto-community

**This is the source of [Phlogiston](https://phlogiston.app)**, an experimental Bluesky reader.
The web app is [`apps/community-live`](apps/community-live); its
[About](https://phlogiston.app/about), [Privacy](https://phlogiston.app/privacy) and
[Terms](https://phlogiston.app/terms) pages are generated from
[`src/public-pages.ts`](apps/community-live/src/public-pages.ts). Each deployed
release is built from a commit of this repository, and the About page links to
it. Report bugs and data requests as issues; report security problems through
[private vulnerability reporting](../../security/advisories/new).

This public repository is published as snapshots of a private working
repository, without its history.

`atproto-community` explores portable, accountable community surfaces over
AT Protocol records. The central idea is that an author keeps custody of a
post while a separate community actor makes an inspectable decision to admit
or remove an exact version from that community's view.

The repository contains two related lines:

- the public-record V0: a bounded `submit -> admit -> render -> remove`
  community over author-owned ATProto posts; and
- an experimental Juniper/Spaces-alpha line that qualifies permissioned
  repository evidence and exercises a disposable community lifecycle without
  turning protocol access into community authority.

This is an experimental, pre-release system. V0 has an implemented and tested
record model, observer, deterministic projection, local authority-writer
boundary, reply policy worker, OAuth browser application, discussion/activity
views, archive/rebuild path, and retained historical evidence demo. The current
campaign restores a public app-layer social loop while the repository also
retains fixture-qualified Spaces-alpha evidence boundaries and its disposable
live-alpha implementation. Those results are bounded evidence, not a
production-readiness claim.

## What problem it addresses

Ordinary ATProto posts live in author-controlled repositories. A community
needs to say “this exact version belongs in our view” without taking ownership
of the post, rewriting it, or making the hosting PDS the community sovereign.
This project separates:

- source existence and exact-version custody;
- evidence qualification;
- a community's admission/removal decision;
- projection into a reader-facing artifact; and
- the renderer that presents that artifact.

That separation makes removal from a community different from deleting the
source and makes the basis of a community view inspectable.

## Implemented surfaces

| Surface | Current role |
|---|---|
| `packages/community-model/` | inert V0 records, identifiers, validation, and deterministic values |
| `packages/communitywatch/` | read-only observer/indexer and projection state |
| `packages/communitywatch-web/` | read-only community, audit, health, and retained-history views |
| `packages/communitywatch-archive/` | explicitly invoked observer-history archive/rebuild tooling |
| `packages/communityd/` | sole V0 community authority-writer boundary |
| `packages/community-policy/` | unprivileged automatic reply-admission worker |
| `packages/community-submit/` | bounded author submission surface |
| `apps/community-live/` | OAuth app for public posts/replies, return visits, and browser moderation |
| `packages/community-space-*` | pure models, reducers, artifacts, rendering, feeds, demos, and test instruments for the Spaces-backed line |
| `packages/communitywatch-spaces-alpha/` | isolated read-side Spaces-alpha acquisition and qualification |
| `packages/communitywatch-space-publisher/` | publication of already-qualified public projection artifacts |
| `apps/juniper-live/` | disposable Juniper alpha application and lifecycle surface |

The package names describe custody boundaries, not a promise that every
surface is installed, deployed, or stable. Start with
[`docs/V0-HANDOFF.md`](docs/V0-HANDOFF.md) for the closed V0 evidence and
[`docs/campaigns/PUBLIC-COMMUNITY-PCV0.md`](docs/campaigns/PUBLIC-COMMUNITY-PCV0.md)
for the current public social-loop contract. The frozen Spaces-alpha contract
remains at [`docs/campaigns/SPACE-COMMUNITY-SCV0-D2.md`](docs/campaigns/SPACE-COMMUNITY-SCV0-D2.md).
The full test command is below.

## What is proposed or non-authorizing

- [`ROADMAP.md`](ROADMAP.md) is the canonical candidate slice ladder. It does
  not authorize a slice by itself.
- [`docs/design/PRODUCT-DIRECTION.md`](docs/design/PRODUCT-DIRECTION.md)
  records non-authorizing product direction.
- [`IDEAS.md`](IDEAS.md) preserves the original idea
  capture and reuse map; it is design evidence, not current policy. Its root
  path is retained because the governed-loop contract protects it as an input.
- [`docs/research/ROADMAP2.md`](docs/research/ROADMAP2.md) is a parked research
  incubator with no selector role.
- [`docs/README.md`](docs/README.md) indexes current contracts, campaign
  records, status evidence, design notes, and historical material.

Only [`BUILD.md`](BUILD.md) authorizes bounded work. [`DOCTRINE.md`](DOCTRINE.md)
states the ratified architectural invariants. When either conflicts with a
design or roadmap note, the design or roadmap note is wrong.

## Explicit non-claims

This repository does not claim:

- production readiness, durable service availability, or a supported release;
- that a PDS is a community authority, or that PDS behavior must be modified;
- ownership of author posts by a community;
- that removal from a community deletes or mutates the author record;
- that transport success, a credential, evidence qualification, membership,
  standing, authorization, admission, and reader disclosure are interchangeable;
- private-community or general membership semantics;
- voting, ranking, comments, social graphs, recommendations, or a general
  trust-and-safety platform;
- that fixture qualification or one disposable alpha proves ATProto-wide
  interoperability, usability, legitimacy, or production fitness.

## Relationship to Unpingable

Within the Unpingable constellation this is a protocol/community system. It
applies recurring boundaries also seen elsewhere—observation before inference,
explicit custody, first-class refusal, evidence/authority/effect separation,
and claim/non-claim discipline—to community projection. Labelwatch and
Driftwatch supplied read-only reference patterns; their identity, credentials,
and authority are not inherited. Governed-loop records describe how bounded
work was admitted, but they do not make this repository a control plane for
other projects.

## Develop and verify

Python 3.12 is the declared target. From the repository root, with the project
development dependencies installed in an isolated environment:

```sh
python -m pytest
ruff check .
```

Node packages under `apps/` and selected `packages/` have their own pinned
`pnpm-lock.yaml` files and package-local test scripts. Consult the relevant
campaign record before exercising any live or authority-bearing surface. Never
introduce production credentials into the repository.

## License

atproto-community is licensed under either the
[Apache License 2.0](LICENSE-APACHE) or the [MIT License](LICENSE-MIT), at your
option. Package metadata records the equivalent SPDX expression
`MIT OR Apache-2.0`. Third-party and donor provenance remains documented in
[`docs/REUSE-MATRIX.md`](docs/REUSE-MATRIX.md) and must be reviewed separately
from this repository-level grant before publication.
