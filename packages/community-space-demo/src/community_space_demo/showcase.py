"""Human-facing, synthetic-only showcase over exact SCV0 artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from html import escape
from importlib.resources import files as resource_files
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Final, Mapping, Protocol

from community_space_artifact import (
    ArtifactReceiptReferences,
    BoundedSourcePresentation,
    DisclosureMode,
    DisclosurePolicy,
    ProjectionArtifact,
    ProjectionArtifactEntry,
)
from community_space_feed import (
    FeedPublicationRequest,
    LocalProjectionFeedBoundary,
    PublicProjectionChannel,
)
from community_space_prototype import LocalCommunityPrototype, PrototypeSite

from .demo import (
    DemoFile,
    StaticDemoBundle,
    StaticDemoCompiler,
    build_synthetic_demo_sites,
)

SHOWCASE_VERSION: Final = "scv0-human-facing-synthetic-showcase/2"
COMMUNITY_NAME: Final = "Juniper Commons"
COMMUNITY_TAGLINE: Final = "Neighbors sharing tools, notes, and small victories."

_STATE_ORDER: Final = (
    "added",
    "changed_at_source",
    "source_unavailable",
    "removed",
)

_STATE_LABELS: Final = {
    "added": "Added",
    "changed_at_source": "Updated by the author",
    "source_unavailable": "Original unavailable",
    "removed": "Removed by Juniper Commons",
}

_STATE_SLUGS: Final = {
    "added": "added",
    "changed_at_source": "changed-at-source",
    "source_unavailable": "source-unavailable",
    "removed": "removed",
}

_STATE_STORIES: Final = {
    "added": (
        "The community featured this exact author-owned post.",
        "The author keeps the source. Juniper Commons records only its choice to include it.",
    ),
    "changed_at_source": (
        "The author updated the source post.",
        "The original community admission remains visible, but the renderer does not silently substitute the new version.",
    ),
    "source_unavailable": (
        "The source cannot be observed right now.",
        "Juniper Commons remembers that it admitted a reference; it does not invent replacement content.",
    ),
    "removed": (
        "Juniper Commons removed the item from its feed.",
        "That community decision does not delete or rewrite the author’s original record.",
    ),
}

_CLAIMS: Final = (
    "typed_projection_artifacts_replayed",
    "ordinary_and_audit_disclosure_separated",
    "human_copy_bound_to_existing_lifecycle_semantics",
    "original_m7a_bundle_embedded",
    "file_digests_recorded",
)

_NON_CLAIMS: Final = (
    "live_atproto_data",
    "human_comprehension",
    "human_usability",
    "human_desirability",
    "accessibility_conformance",
    "reader_authentication",
    "reader_authorization",
    "membership",
    "moderator_authority",
    "governance_authority",
    "source_truth",
    "source_ownership",
    "repository_currentness",
    "production_readiness",
)

_SHA_RE: Final = re.compile(r"sha256:[0-9a-f]{64}")


class _RenderedEntry(Protocol):
    lifecycle_state: str
    lifecycle_notice: str
    author_did: str
    title: str | None
    body: str | None
    author_display_reference: str | None
    receipt_references: tuple[tuple[str, str], ...]
    lifecycle_links: tuple[str, ...]


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _id(label: str) -> str:
    return _digest(f"{SHOWCASE_VERSION}:{label}".encode())


def _style_bytes() -> bytes:
    return (
        resource_files("community_space_demo")
        .joinpath("assets/showcase.css")
        .read_bytes()
    )


@dataclass(frozen=True, slots=True)
class ShowcaseCorpus:
    """Exact typed inputs for the friendly renderer; never live source data."""

    community_site: PrototypeSite
    lifecycle_sites: Mapping[str, PrototypeSite]

    def __post_init__(self) -> None:
        if not isinstance(self.community_site, PrototypeSite):
            raise TypeError("showcase community site must be a PrototypeSite")
        self.community_site.validate_integrity()
        entries = self.community_site.canonical_semantics.entries
        if len(entries) != 3 or any(
            item.lifecycle_state != "added" for item in entries
        ):
            raise ValueError(
                "showcase community feed requires three exact Added entries"
            )
        if tuple(self.lifecycle_sites) != _STATE_ORDER:
            raise ValueError("showcase lifecycle sites must use the frozen order")
        object.__setattr__(
            self,
            "lifecycle_sites",
            MappingProxyType(dict(self.lifecycle_sites)),
        )
        community_id = self.community_site.canonical_semantics.community_identity_id
        reference = entries[0]
        for expected_state, site in self.lifecycle_sites.items():
            if not isinstance(site, PrototypeSite):
                raise TypeError("showcase lifecycle site must be a PrototypeSite")
            site.validate_integrity()
            state_entries = site.canonical_semantics.entries
            if (
                len(state_entries) != 1
                or state_entries[0].lifecycle_state != expected_state
            ):
                raise ValueError("showcase lifecycle site state mismatch")
            item = state_entries[0]
            if site.canonical_semantics.community_identity_id != community_id:
                raise ValueError("showcase lifecycle community mismatch")
            if (
                item.source_uri != reference.source_uri
                or item.admitted_source_cid != reference.admitted_source_cid
                or item.author_did != reference.author_did
            ):
                raise ValueError("showcase lifecycle source occurrence mismatch")

    @property
    def corpus_id(self) -> str:
        return _digest(
            _canonical_bytes(
                {
                    "showcaseVersion": SHOWCASE_VERSION,
                    "communitySiteId": self.community_site.site_id,
                    "lifecycleSiteIds": {
                        state: site.site_id
                        for state, site in self.lifecycle_sites.items()
                    },
                }
            )
        )


@dataclass(frozen=True, slots=True)
class ShowcaseBundle:
    files: tuple[DemoFile, ...]
    corpus_id: str
    embedded_m7a_bundle_id: str
    community_site_id: str
    verified_claims: tuple[str, ...] = _CLAIMS
    explicit_non_claims: tuple[str, ...] = _NON_CLAIMS
    showcase_version: str = SHOWCASE_VERSION

    def __post_init__(self) -> None:
        if self.showcase_version != SHOWCASE_VERSION:
            raise ValueError("unsupported showcase version")
        if self.verified_claims != _CLAIMS or self.explicit_non_claims != _NON_CLAIMS:
            raise ValueError("showcase claims and non-claims are fixed")
        for label, value in (
            ("corpus_id", self.corpus_id),
            ("embedded_m7a_bundle_id", self.embedded_m7a_bundle_id),
            ("community_site_id", self.community_site_id),
        ):
            if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
                raise ValueError(f"{label} must be a sha256 identifier")
        if not self.files or len({item.path for item in self.files}) != len(self.files):
            raise ValueError("showcase requires uniquely named files")
        for item in self.files:
            if not isinstance(item, DemoFile):
                raise TypeError("showcase files must be typed DemoFile values")
            item.__post_init__()

    @property
    def manifest_bytes(self) -> bytes:
        return _canonical_bytes(
            {
                "showcaseVersion": self.showcase_version,
                "synthetic": True,
                "communityName": COMMUNITY_NAME,
                "corpusId": self.corpus_id,
                "communitySiteId": self.community_site_id,
                "embeddedM7aBundleId": self.embedded_m7a_bundle_id,
                "files": tuple(item.to_manifest_entry() for item in self.files),
                "verifiedClaims": self.verified_claims,
                "explicitNonClaims": self.explicit_non_claims,
            }
        )

    @property
    def bundle_id(self) -> str:
        return _digest(self.manifest_bytes)

    @property
    def all_files(self) -> tuple[DemoFile, ...]:
        manifest = DemoFile.create(
            "manifest.json", "application/json", self.manifest_bytes
        )
        checksum_lines = tuple(
            f"{item.body_sha256.removeprefix('sha256:')}  {item.path}"
            for item in (*self.files, manifest)
        )
        checksums = DemoFile.create(
            "checksums.txt",
            "text/plain; charset=utf-8",
            ("\n".join(checksum_lines) + "\n").encode(),
        )
        return (*self.files, manifest, checksums)

    def write_directory(self, directory: Path) -> None:
        if not isinstance(directory, Path):
            raise TypeError("showcase output must be a pathlib.Path")
        resolved = directory.resolve()
        if resolved in {Path("/").resolve(), Path.home().resolve()}:
            raise ValueError("refusing broad showcase output directory")
        if resolved.exists() and (not resolved.is_dir() or any(resolved.iterdir())):
            raise ValueError("showcase output directory must be absent or empty")
        resolved.mkdir(parents=True, exist_ok=True)
        for item in self.all_files:
            target = resolved.joinpath(*PurePosixPath(item.path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item.body)
        self.verify_directory(resolved)

    def verify_directory(self, directory: Path) -> str:
        if not isinstance(directory, Path):
            raise TypeError("showcase output must be a pathlib.Path")
        resolved = directory.resolve()
        if not resolved.is_dir():
            raise ValueError("showcase output directory does not exist")
        observed: dict[str, bytes] = {}
        for path in sorted(resolved.rglob("*")):
            if path.is_symlink():
                raise ValueError("showcase output may not contain symbolic links")
            if path.is_file():
                observed[path.relative_to(resolved).as_posix()] = path.read_bytes()
        expected = {item.path: item.body for item in self.all_files}
        if observed.keys() != expected.keys():
            raise ValueError("showcase output file set mismatch")
        for path, body in expected.items():
            if observed[path] != body:
                raise ValueError(f"showcase output byte mismatch: {path}")
        return self.bundle_id


class HumanShowcaseCompiler:
    """Add human legibility without altering the supplied artifact semantics."""

    def compile(
        self,
        corpus: ShowcaseCorpus,
        embedded_m7a: StaticDemoBundle,
    ) -> ShowcaseBundle:
        if not isinstance(corpus, ShowcaseCorpus):
            raise TypeError("showcase compiler requires a ShowcaseCorpus")
        corpus.__post_init__()
        if not isinstance(embedded_m7a, StaticDemoBundle):
            raise TypeError("showcase compiler requires the exact M7A bundle")
        embedded_m7a.__post_init__()

        files: list[DemoFile] = [
            DemoFile.create(".nojekyll", "application/octet-stream", b""),
            DemoFile.create("styles.css", "text/css; charset=utf-8", _style_bytes()),
            DemoFile.create(
                "index.html",
                "text/html; charset=utf-8",
                self._home(corpus.community_site).encode(),
            ),
            DemoFile.create(
                "audit.html",
                "text/html; charset=utf-8",
                self._audit(corpus.community_site, back_href="./").encode(),
            ),
            DemoFile.create(
                "about.html",
                "text/html; charset=utf-8",
                self._about().encode(),
            ),
            DemoFile.create(
                "feed.json",
                "application/json",
                corpus.community_site.ordinary_feed.to_bytes(),
            ),
            DemoFile.create(
                "audit-feed.json",
                "application/json",
                corpus.community_site.audit_feed.to_bytes(),
            ),
        ]

        for state, site in corpus.lifecycle_sites.items():
            slug = _STATE_SLUGS[state]
            files.extend(
                (
                    DemoFile.create(
                        f"states/{slug}/index.html",
                        "text/html; charset=utf-8",
                        self._state_page(site, state).encode(),
                    ),
                    DemoFile.create(
                        f"states/{slug}/audit.html",
                        "text/html; charset=utf-8",
                        self._audit(site, back_href="index.html").encode(),
                    ),
                    DemoFile.create(
                        f"states/{slug}/feed.json",
                        "application/json",
                        site.ordinary_feed.to_bytes(),
                    ),
                    DemoFile.create(
                        f"states/{slug}/audit-feed.json",
                        "application/json",
                        site.audit_feed.to_bytes(),
                    ),
                )
            )

        for item in embedded_m7a.all_files:
            files.append(
                DemoFile.create(
                    f"lab/{item.path}",
                    item.media_type,
                    item.body,
                )
            )

        return ShowcaseBundle(
            files=tuple(files),
            corpus_id=corpus.corpus_id,
            embedded_m7a_bundle_id=embedded_m7a.bundle_id,
            community_site_id=corpus.community_site.site_id,
        )

    def _head(self, title: str, *, stylesheet: str = "styles.css") -> str:
        return (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{escape(title)}</title>"
            '<meta name="description" content="A synthetic community feed where authors keep their posts and communities own inclusion decisions.">'
            f'<link rel="stylesheet" href="{escape(stylesheet)}">'
            "</head><body>"
        )

    def _header(self, *, prefix: str = "") -> str:
        return (
            '<header class="site-header shell">'
            f'<a class="brand" href="{escape(prefix or "./")}">'
            '<span class="brand-mark" aria-hidden="true">J</span>'
            f"<span>{escape(COMMUNITY_NAME)}</span></a>"
            '<nav class="site-nav" aria-label="Primary">'
            f'<a href="{escape(prefix)}#how-it-works">How it works</a>'
            f'<a href="{escape(prefix)}about.html">About this demo</a>'
            f'<a class="audit-link" href="{escape(prefix)}audit.html">View audit trail</a>'
            "</nav></header>"
        )

    def _footer(self, *, prefix: str = "") -> str:
        return (
            '<footer class="site-footer shell"><span>Fictional community. Synthetic data. Designed for clarity, but not yet user-tested.</span>'
            f'<span><a href="{escape(prefix)}manifest.json">Manifest</a> · '
            f'<a href="{escape(prefix)}checksums.txt">Checksums</a> · '
            f'<a href="{escape(prefix)}lab/">Boundary lab</a></span></footer></body></html>'
        )

    def _home(self, site: PrototypeSite) -> str:
        site.validate_integrity()
        entries = "".join(
            self._post(entry) for entry in site.canonical_semantics.entries
        )
        state_cards = "".join(
            self._state_card(state)
            for state in ("changed_at_source", "source_unavailable", "removed")
        )
        return (
            self._head(f"{COMMUNITY_NAME} — a portable community")
            + self._header()
            + '<main><section class="hero shell"><div><p class="eyebrow">A portable community, shown with synthetic data</p>'
            "<h1>A community feed that doesn’t own the posts it displays.</h1>"
            '<p class="hero-copy">Juniper Commons chooses what belongs here. Authors keep their originals. '
            "This page is just one replaceable window onto the community’s published choices.</p>"
            '<div class="chips"><span class="chip">Author-owned posts</span>'
            '<span class="chip">Community-owned inclusion</span>'
            '<span class="chip">Replaceable renderer</span></div></div>'
            '<aside class="hero-card"><p class="kicker">You’re visiting</p>'
            f'<p class="community-name">{escape(COMMUNITY_NAME)}</p>'
            f'<p class="community-description">{escape(COMMUNITY_TAGLINE)}</p>'
            '<ol class="flow"><li><b>1</b> A neighbor publishes a post</li>'
            "<li><b>2</b> The community chooses to feature it</li>"
            "<li><b>3</b> Any compatible app can render that choice</li></ol></aside></section>"
            '<section class="section shell" id="feed"><div class="section-heading">'
            '<div><p class="eyebrow">From the commons</p><h2>Featured by the community</h2></div>'
            "<p>The community picked these posts. Their authors still own them, and can change or delete them at any time.</p>"
            f'</div><div class="feed">{entries}</div></section>'
            '<section class="section lifecycle-section" id="lifecycle"><div class="shell">'
            '<div class="section-heading"><div><p class="eyebrow">The honest bits</p>'
            "<h2>When the source changes, the feed says so.</h2></div>"
            "<p>A community decision and an author’s source state are different facts. The renderer keeps both visible.</p></div>"
            f'<div class="state-grid">{state_cards}</div></div></section>'
            '<section class="section shell" id="how-it-works"><div class="principle">'
            '<div><p class="eyebrow">The product idea</p><h2>Communities can curate without taking custody.</h2></div>'
            "<div><p>The useful split is deliberately simple:</p><ul>"
            "<li><strong>Authors</strong> own and update their source posts.</li>"
            "<li><strong>Communities</strong> publish inclusion and removal decisions.</li>"
            "<li><strong>Renderers</strong> present those decisions without becoming the authority.</li>"
            '</ul><p class="quiet-links"><a href="audit.html">Why are these items here?</a> '
            '<a href="about.html">What this demo does not claim</a></p></div></div></section></main>'
            + self._footer()
        )

    def _post(self, entry: _RenderedEntry) -> str:
        if (
            entry.lifecycle_state != "added"
            or entry.title is None
            or entry.body is None
        ):
            raise ValueError("showcase home accepts only disclosed Added presentations")
        author = entry.author_display_reference or entry.author_did
        initial = author.lstrip("@")[0].upper()
        return (
            '<article class="post"><div class="avatar" aria-hidden="true">'
            f"{escape(initial)}</div><div>"
            '<div class="post-meta"><strong>'
            f"{escape(author)}</strong><span>·</span><span>author-owned post</span>"
            '<span class="state-pill">Featured here</span></div>'
            f'<h3>{escape(entry.title)}</h3><p class="post-body">{escape(entry.body)}</p>'
            '<details class="why"><summary>Why is this here?</summary><div class="why-grid">'
            "<div><strong>Source</strong>The author owns the original post.</div>"
            "<div><strong>Community</strong>Juniper Commons chose to feature this exact version.</div>"
            "<div><strong>Renderer</strong>This page displays that published community choice.</div>"
            '</div><p class="synthetic-note"><strong>In this demo:</strong> the admission and moderation authorization are synthetic. '
            "A real community would bind this choice to its community actor and one specific moderation authorization.</p>"
            '<p class="quiet-links"><a href="audit.html">See the technical trail</a></p>'
            "</details></div></article>"
        )

    def _state_card(self, state: str) -> str:
        title, description = _STATE_STORIES[state]
        return (
            '<article class="state-story">'
            f'<span class="state-pill {escape(self._state_class(state))}">{escape(_STATE_LABELS[state])}</span>'
            f"<h3>{escape(title)}</h3><p>{escape(description)}</p>"
            f'<a href="states/{escape(_STATE_SLUGS[state])}/">See this state clearly →</a>'
            "</article>"
        )

    def _state_page(self, site: PrototypeSite, state: str) -> str:
        site.validate_integrity()
        entry = site.canonical_semantics.entries[0]
        if entry.lifecycle_state != state:
            raise ValueError("state page and lifecycle semantics disagree")
        title, description = _STATE_STORIES[state]
        presentation = ""
        if entry.title is not None:
            presentation = (
                f"<h3>{escape(entry.title)}</h3>"
                f'<p class="post-body">{escape(entry.body or "")}</p>'
            )
        return (
            self._head(
                f"{_STATE_LABELS[state]} — {COMMUNITY_NAME}",
                stylesheet="../../styles.css",
            )
            + self._header(prefix="../../")
            + '<main class="shell state-focus"><section class="page-hero">'
            '<p class="eyebrow">One source, two kinds of change</p>'
            f"<h1>{escape(title)}</h1><p>{escape(description)}</p></section>"
            '<article class="post"><div class="avatar" aria-hidden="true">M</div><div>'
            f'<div class="post-meta"><strong>@maya.invalid.test</strong><span class="state-pill {escape(self._state_class(state))}">'
            f"{escape(_STATE_LABELS[state])}</span></div>{presentation}"
            f'<div class="notice-box">{escape(entry.lifecycle_notice)}</div>'
            '<details class="why" open><summary>Why is this here?</summary><div class="why-grid">'
            "<div><strong>Author state</strong>The source remains controlled by its author.</div>"
            "<div><strong>Community state</strong>This notice reflects Juniper Commons’ separate projection record.</div>"
            "<div><strong>No silent upgrade</strong>This renderer does not turn one fact into the other.</div>"
            '</div></details><p class="quiet-links"><a href="audit.html">Inspect this state’s audit trail</a> '
            '<a href="../../#lifecycle">Back to the lifecycle story</a></p></div></article></main>'
            + self._footer(prefix="../../")
        )

    def _audit(self, site: PrototypeSite, *, back_href: str) -> str:
        site.validate_integrity()
        feed = site.audit_feed
        entries = "".join(
            self._audit_entry(item, index)
            for index, item in enumerate(site.audit_semantics.entries, 1)
        )
        stylesheet = "styles.css" if back_href == "./" else "../../styles.css"
        prefix = "./" if back_href == "./" else "../../"
        return (
            self._head(f"Audit trail — {COMMUNITY_NAME}", stylesheet=stylesheet)
            + self._header(prefix=prefix)
            + '<main class="shell"><section class="page-hero"><p class="eyebrow">Technical view</p>'
            "<h1>Why these items are here.</h1><p>The identifiers below let another tool compare the published artifact and lifecycle references. "
            "They are evidence pointers—not proof of popularity, truth, membership, or governance legitimacy.</p>"
            f'<p class="quiet-links"><a href="{escape(back_href)}">← Back to the ordinary view</a></p></section>'
            '<section class="audit-summary"><div><span>Published feed</span>'
            f"<code>{escape(feed.feed_id)}</code></div><div><span>Projection artifact</span>"
            f"<code>{escape(feed.artifact_id)}</code></div></section>"
            f'<section class="audit-list" aria-label="Audit entries">{entries}</section></main>'
            + self._footer(prefix=prefix)
        )

    def _audit_entry(self, entry: _RenderedEntry, index: int) -> str:
        receipts = "".join(
            f"<li><strong>{escape(label)}</strong><br><code>{escape(value)}</code></li>"
            for label, value in entry.receipt_references
        )
        links = "".join(
            f"<li><code>{escape(value)}</code></li>" for value in entry.lifecycle_links
        )
        title = entry.title or _STATE_STORIES[entry.lifecycle_state][0]
        return (
            f'<article class="audit-card" id="entry-{index}">'
            f'<span class="label">Entry {index} · {escape(_STATE_LABELS[entry.lifecycle_state])}</span>'
            f"<h2>{escape(title)}</h2><p>{escape(entry.lifecycle_notice)}</p>"
            f"<h3>Receipt references</h3><ul>{receipts}</ul>"
            f"<h3>Available lifecycle links</h3><ul>{links}</ul></article>"
        )

    def _about(self) -> str:
        return (
            self._head(f"About — {COMMUNITY_NAME}")
            + self._header(prefix="./")
            + '<main class="shell"><section class="page-hero"><p class="eyebrow">About this experiment</p>'
            "<h1>The community owns the choice. The app is only the window.</h1>"
            "<p>This is a fictional, synthetic demonstration of a portable community projection. "
            "It contains no live ATProto account, Space, credential, member, or moderation action.</p></section>"
            '<section class="section"><div class="principle"><div><h2>What it demonstrates</h2></div>'
            "<ul><li>An author-owned post can be referenced without transferring ownership.</li>"
            "<li>A community can publish its separate choice to include or remove that reference.</li>"
            "<li>Ordinary and technical renderers can show the same lifecycle semantics.</li></ul></div>"
            '<div class="notice-box"><strong>What it does not establish:</strong> identity authenticity, '
            "reader permission, membership, moderator authority, source truth, currentness, or production readiness. "
            '<strong>Designed for clarity, but not yet user-tested.</strong></div><p class="quiet-links"><a href="./">See the community view</a> '
            '<a href="audit.html">Inspect the audit view</a> <a href="lab/">Open the original boundary lab</a></p>'
            "</section></main>" + self._footer()
        )

    def _state_class(self, state: str) -> str:
        return {
            "added": "",
            "changed_at_source": "changed",
            "source_unavailable": "unavailable",
            "removed": "removed",
        }[state]


def _presentation(
    slug: str,
    *,
    cid: str,
    title: str,
    body: str,
    author: str,
) -> BoundedSourcePresentation:
    return BoundedSourcePresentation(
        source_reference_id=_id(f"post:{slug}"),
        source_uri=f"at://did:web:{author.removeprefix('@')}/test.invalid.community.post/{slug}",
        source_cid=cid,
        title=title,
        body=body,
        author_display_reference=author,
    )


def _receipts(
    slug: str, *, admission_id: str, removal_id: str | None
) -> ArtifactReceiptReferences:
    return ArtifactReceiptReferences(
        source_qualification_receipt_id=_id(f"{slug}:source-qualification"),
        source_observation_receipt_id=_id(f"{slug}:source-observation"),
        source_currentness_receipt_id=_id(f"{slug}:source-currentness"),
        submission_evidence_receipt_id=_id(f"{slug}:submission"),
        moderator_authorization_id=_id(f"{slug}:moderator-authorization"),
        admission_id=admission_id,
        projection_reference_id=_id(f"{slug}:projection-reference"),
        removal_id=removal_id,
    )


def _policies(label: str) -> tuple[DisclosurePolicy, DisclosurePolicy]:
    return (
        DisclosurePolicy(
            mode=DisclosureMode.ORDINARY,
            policy_reference_id=_id(f"{label}:ordinary-policy"),
            publication_reference_id=_id(f"{label}:ordinary-publication"),
        ),
        DisclosurePolicy(
            mode=DisclosureMode.TECHNICAL_AUDIT,
            policy_reference_id=_id(f"{label}:audit-policy"),
            publication_reference_id=_id(f"{label}:audit-publication"),
        ),
    )


def _site(entries: tuple[dict[str, object], ...], *, label: str) -> PrototypeSite:
    community_id = _id("community:juniper-commons")
    ordinary_policy, audit_policy = _policies(label)

    def artifact(*, audit: bool) -> ProjectionArtifact:
        policy = audit_policy if audit else ordinary_policy
        typed_entries: list[ProjectionArtifactEntry] = []
        for spec in entries:
            slug = str(spec["slug"])
            state = str(spec["state"])
            presentation = spec["presentation"]
            if not isinstance(presentation, BoundedSourcePresentation):
                raise TypeError("showcase source presentation must be typed")
            removal_id = _id(f"{slug}:removal") if state == "removed" else None
            admission_id = _id(f"{slug}:admission")
            typed_entries.append(
                ProjectionArtifactEntry(
                    projection_identity=_id(f"{slug}:projection"),
                    projection_state_id=_id(f"{slug}:state:{state}"),
                    lifecycle_state=state,
                    community_identity_id=community_id,
                    post_reference_id=presentation.source_reference_id,
                    source_uri=presentation.source_uri,
                    admitted_source_cid=presentation.source_cid,
                    author_did=f"did:web:{str(spec['author']).removeprefix('@')}",
                    admission_id=admission_id,
                    admitted_at=str(spec["admitted_at"]),
                    source_observation_id=_id(f"{slug}:observation:{state}"),
                    source_relationship={
                        "added": "exact",
                        "changed_at_source": "changed_at_source",
                        "source_unavailable": "unavailable",
                        "removed": "exact",
                    }[state],
                    presentation=presentation if state == "added" else None,
                    technical_receipts=(
                        _receipts(
                            slug,
                            admission_id=admission_id,
                            removal_id=removal_id,
                        )
                        if audit
                        else None
                    ),
                    available_lifecycle_links=(
                        (
                            _id(f"{slug}:admitted-event"),
                            _id(f"{slug}:projection-event:{state}"),
                        )
                        if audit
                        else ()
                    ),
                    removal_id=removal_id,
                )
            )
        return ProjectionArtifact(
            community_identity_id=community_id,
            community_actor_did="did:web:juniper-commons.invalid.test",
            space_identity_id=_id("space:juniper-commons"),
            projection_version="scv0-projection-reducer/1",
            disclosure_mode=policy.mode,
            disclosure_policy_id=policy.policy_id,
            disclosure_policy_reference_id=policy.policy_reference_id,
            publication_reference_id=policy.publication_reference_id,
            entries=tuple(typed_entries),
        )

    def publish(*, audit: bool):
        item = artifact(audit=audit)
        return LocalProjectionFeedBoundary().publish(
            FeedPublicationRequest(
                artifact=item,
                expected_artifact_id=item.artifact_id,
                expected_community_identity_id=item.community_identity_id,
                expected_publication_reference_id=item.publication_reference_id,
                channel=(
                    PublicProjectionChannel.TECHNICAL_AUDIT
                    if audit
                    else PublicProjectionChannel.ORDINARY
                ),
                published_at=(
                    "2026-08-22T19:00:01Z" if audit else "2026-08-22T19:00:00Z"
                ),
            )
        )

    return LocalCommunityPrototype().render(publish(audit=False), publish(audit=True))


def build_showcase_corpus() -> ShowcaseCorpus:
    """Construct a fixed fictional community without network or secret material."""

    posts = (
        {
            "slug": "free-tool-shelf",
            "state": "added",
            "author": "@maya.invalid.test",
            "admitted_at": "2026-08-22T18:30:00Z",
            "presentation": _presentation(
                "free-tool-shelf",
                cid="bafyreicj4w5qcnzob6gqff7ydadwzgbkh4r3p5xozr5pj4f7ke5ybjqr5i",
                title="The free tool shelf is open this Saturday",
                body="Bring what you can spare, borrow what you need, and label anything that wants to find its way home.",
                author="@maya.invalid.test",
            ),
        },
        {
            "slug": "balcony-tomatoes",
            "state": "added",
            "author": "@jules.invalid.test",
            "admitted_at": "2026-08-22T17:10:00Z",
            "presentation": _presentation(
                "balcony-tomatoes",
                cid="bafyreiaij7wqrolyv5gx2glkordkq22yacpgg23bdwyweenwlknk37zjyu",
                title="A tiny guide to balcony tomatoes",
                body="Three containers, one afternoon of sun, and the varieties that stayed cheerful through a very wet June.",
                author="@jules.invalid.test",
            ),
        },
        {
            "slug": "repair-cafe-notes",
            "state": "added",
            "author": "@ren.invalid.test",
            "admitted_at": "2026-08-22T15:45:00Z",
            "presentation": _presentation(
                "repair-cafe-notes",
                cid="bafyreicl6ujc6ncfktctxxroxognfn7d2fqavvrryoc2lv6m4i6hpbkfti",
                title="What we learned from repairing six lamps",
                body="Loose sockets caused four failures. The other two taught us why a multimeter and patience belong in every repair kit.",
                author="@ren.invalid.test",
            ),
        },
    )
    community_site = _site(posts, label="community-feed")
    first = posts[0]
    lifecycle = {
        state: _site(
            (
                {
                    **first,
                    "state": state,
                    "admitted_at": "2026-08-22T18:30:00Z",
                },
            ),
            label=f"lifecycle:{state}",
        )
        for state in _STATE_ORDER
    }
    return ShowcaseCorpus(community_site=community_site, lifecycle_sites=lifecycle)


def build_showcase_bundle() -> ShowcaseBundle:
    base = StaticDemoCompiler().compile(build_synthetic_demo_sites())
    return HumanShowcaseCompiler().compile(build_showcase_corpus(), base)


def refuse_showcase_claim_upgrade(labels: object) -> None:
    if not isinstance(labels, dict) or any(not isinstance(key, str) for key in labels):
        raise TypeError("showcase claim labels must be an object")
    if labels:
        raise ValueError("showcase presentation cannot add human or authority claims")
