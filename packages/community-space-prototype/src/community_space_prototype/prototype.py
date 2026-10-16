"""Human-readable, in-memory pages over exact public projection feeds."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from html import escape
from typing import Final

from community_space_feed import PublicProjectionChannel, PublishedProjectionFeed
from community_space_renderer import (
    AccessibleFixtureRenderer,
    RenderedEntrySemantics,
    RenderedProjectionSemantics,
)

PROTOTYPE_VERSION: Final = "scv0-local-community-prototype/1"

_NON_CLAIMS: Final = (
    "reader_authentication",
    "reader_authorization",
    "membership",
    "moderator_authority",
    "governance_authority",
    "source_truth",
    "source_ownership",
    "repository_currentness",
    "ranking",
)

_STATE_LABELS: Final = {
    "added": "Added",
    "changed_at_source": "Changed at source",
    "source_unavailable": "Source unavailable",
    "author_withdrawn": "Author asked not to be featured",
    "removed": "Removed",
}


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _public_core(semantics: RenderedProjectionSemantics) -> tuple[object, ...]:
    return (
        semantics.community_identity_id,
        semantics.community_reference,
        tuple(
            (
                entry.projection_identity,
                entry.projection_state_id,
                entry.lifecycle_state,
                entry.lifecycle_notice,
                entry.source_uri,
                entry.admitted_source_cid,
                entry.author_did,
                entry.title,
                entry.body,
                entry.author_display_reference,
                entry.removal_id,
            )
            for entry in semantics.entries
        ),
    )


@dataclass(frozen=True, slots=True)
class PrototypeSite:
    ordinary_feed: PublishedProjectionFeed
    audit_feed: PublishedProjectionFeed
    canonical_semantics: RenderedProjectionSemantics
    audit_semantics: RenderedProjectionSemantics
    ordinary_html: str
    audit_html: str
    ordinary_html_sha256: str
    audit_html_sha256: str
    explicit_non_claims: tuple[str, ...] = _NON_CLAIMS
    prototype_version: str = PROTOTYPE_VERSION

    def __post_init__(self) -> None:
        if self.prototype_version != PROTOTYPE_VERSION:
            raise ValueError("unsupported prototype version")
        if self.explicit_non_claims != _NON_CLAIMS:
            raise ValueError("prototype cannot strengthen feed claims")
        self._validate_binding()

    @property
    def site_id(self) -> str:
        material = "\n".join(
            (
                self.prototype_version,
                self.ordinary_feed.feed_id,
                self.audit_feed.feed_id,
                self.ordinary_html_sha256,
                self.audit_html_sha256,
            )
        )
        return _digest(material)

    def _validate_binding(self) -> None:
        self.ordinary_feed.validate_integrity()
        self.audit_feed.validate_integrity()
        if self.ordinary_feed.channel is not PublicProjectionChannel.ORDINARY:
            raise ValueError("prototype ordinary feed has the wrong channel")
        if self.audit_feed.channel is not PublicProjectionChannel.TECHNICAL_AUDIT:
            raise ValueError("prototype audit feed has the wrong channel")
        ordinary = (
            AccessibleFixtureRenderer().render(self.ordinary_feed.artifact).semantics
        )
        audit = AccessibleFixtureRenderer().render(self.audit_feed.artifact).semantics
        if ordinary != self.canonical_semantics or audit != self.audit_semantics:
            raise ValueError("prototype canonical semantics mismatch")
        if _public_core(ordinary) != _public_core(audit):
            raise ValueError(
                "ordinary and audit feeds describe different projection state"
            )
        if _digest(self.ordinary_html) != self.ordinary_html_sha256:
            raise ValueError("ordinary prototype page integrity mismatch")
        if _digest(self.audit_html) != self.audit_html_sha256:
            raise ValueError("audit prototype page integrity mismatch")

    def validate_integrity(self) -> str:
        self.__post_init__()
        return self.site_id


class LocalCommunityPrototype:
    """Compose two public feeds into separate ordinary and audit pages."""

    def render(
        self,
        ordinary_feed: PublishedProjectionFeed,
        audit_feed: PublishedProjectionFeed,
    ) -> PrototypeSite:
        if not isinstance(ordinary_feed, PublishedProjectionFeed) or not isinstance(
            audit_feed, PublishedProjectionFeed
        ):
            raise TypeError("prototype requires typed public projection feeds")
        ordinary_feed.validate_integrity()
        audit_feed.validate_integrity()
        if ordinary_feed.channel is not PublicProjectionChannel.ORDINARY:
            raise ValueError("prototype requires an ordinary public feed")
        if audit_feed.channel is not PublicProjectionChannel.TECHNICAL_AUDIT:
            raise ValueError("prototype requires a technical-audit public feed")
        ordinary = AccessibleFixtureRenderer().render(ordinary_feed.artifact).semantics
        audit = AccessibleFixtureRenderer().render(audit_feed.artifact).semantics
        if _public_core(ordinary) != _public_core(audit):
            raise ValueError(
                "ordinary and audit feeds describe different projection state"
            )
        ordinary_html = self._ordinary_page(ordinary)
        audit_html = self._audit_page(audit, audit_feed)
        return PrototypeSite(
            ordinary_feed=ordinary_feed,
            audit_feed=audit_feed,
            canonical_semantics=ordinary,
            audit_semantics=audit,
            ordinary_html=ordinary_html,
            audit_html=audit_html,
            ordinary_html_sha256=_digest(ordinary_html),
            audit_html_sha256=_digest(audit_html),
        )

    def _ordinary_page(self, semantics: RenderedProjectionSemantics) -> str:
        entries = "".join(self._ordinary_entry(entry) for entry in semantics.entries)
        return (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>Community</title><style>"
            "body{font:16px system-ui;max-width:48rem;margin:2rem auto;padding:0 1rem;}"
            "article{border:1px solid #ccc;border-radius:.6rem;padding:1rem;margin:1rem 0;}"
            ".state{font-weight:700}.muted{color:#555}summary{cursor:pointer}"
            "</style></head><body><header><h1>Community</h1>"
            f'<p class="muted">{escape(semantics.community_reference)}</p></header>'
            f'<main aria-label="Community feed">{entries}</main></body></html>'
        )

    def _ordinary_entry(self, entry: RenderedEntrySemantics) -> str:
        title = escape(entry.title) if entry.title is not None else "Community item"
        body = f"<p>{escape(entry.body or '')}</p>" if entry.body is not None else ""
        author = (
            f'<p class="muted">By {escape(entry.author_display_reference or entry.author_did)}</p>'
            if entry.lifecycle_state == "added"
            else ""
        )
        label = escape(_STATE_LABELS[entry.lifecycle_state])
        return (
            f"<article><h2>{title}</h2>{body}{author}"
            f'<p class="state">{label}</p><p>{escape(entry.lifecycle_notice)}</p>'
            "<details><summary>Why is this here?</summary>"
            "<p>This item reflects this community’s published inclusion and lifecycle decision. "
            "The author still owns the source.</p>"
            '<p><a href="audit.html">Open the separate technical audit page</a></p>'
            "</details></article>"
        )

    def _audit_page(
        self,
        semantics: RenderedProjectionSemantics,
        feed: PublishedProjectionFeed,
    ) -> str:
        entries = "".join(self._audit_entry(entry) for entry in semantics.entries)
        return (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>Community technical audit</title></head><body>"
            "<header><h1>Technical audit</h1>"
            f"<p>Feed <code>{escape(feed.feed_id)}</code></p>"
            f"<p>Artifact <code>{escape(feed.artifact_id)}</code></p>"
            '<p><a href="index.html">Back to ordinary view</a></p></header>'
            f"<main>{entries}</main></body></html>"
        )

    def _audit_entry(self, entry: RenderedEntrySemantics) -> str:
        receipts = "".join(
            f"<li>{escape(label)}: <code>{escape(value)}</code></li>"
            for label, value in entry.receipt_references
        )
        links = "".join(
            f"<li><code>{escape(value)}</code></li>" for value in entry.lifecycle_links
        )
        return (
            "<article><h2>Why is this here?</h2>"
            f"<p>Lifecycle: <strong>{escape(_STATE_LABELS[entry.lifecycle_state])}</strong></p>"
            f"<p>{escape(entry.lifecycle_notice)}</p>"
            f"<h3>Receipt references</h3><ul>{receipts}</ul>"
            f"<h3>Lifecycle chain</h3><ul>{links}</ul></article>"
        )


def refuse_prototype_claim_upgrade(labels: object) -> None:
    """Presentation cannot invent authority, ownership, or ranking."""

    if not isinstance(labels, dict) or any(not isinstance(key, str) for key in labels):
        raise TypeError("prototype claim labels must be an object with string keys")
    if labels:
        raise ValueError("prototype cannot add authority, ownership, or ranking claims")
