"""Pure local HTML views over immutable M5A projection artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from html import escape
from typing import Final

from community_space_artifact import (
    ArtifactReceiptReferences,
    BoundedSourcePresentation,
    ProjectionArtifact,
    ProjectionArtifactEntry,
)

RENDERER_VERSION: Final = "scv0-local-fixture-renderer/1"

_STATE_NOTICES: Final = {
    "added": "Added by this community.",
    "changed_at_source": (
        "Source changed after admission; the admitted presentation was not replaced."
    ),
    "source_unavailable": ("The previously admitted source is currently unavailable."),
    "author_withdrawn": (
        "The author asked not to be featured here; the historical community decision remains inspectable."
    ),
    "removed": (
        "Removed from this community projection; the author source was not mutated."
    ),
}

_NON_CLAIMS: Final = (
    "reader_authorization",
    "membership",
    "moderator_authority",
    "governance_authority",
    "source_truth",
    "source_ownership",
    "repository_currentness",
)


class RendererStyle(StrEnum):
    COMPACT = "compact_fixture_html"
    ACCESSIBLE = "accessible_fixture_html"


@dataclass(frozen=True, slots=True)
class RenderedEntrySemantics:
    entry_id: str
    projection_identity: str
    projection_state_id: str
    lifecycle_state: str
    lifecycle_notice: str
    source_uri: str
    admitted_source_cid: str
    author_did: str
    title: str | None
    body: str | None
    author_display_reference: str | None
    receipt_references: tuple[tuple[str, str], ...]
    lifecycle_links: tuple[str, ...]
    removal_id: str | None
    withdrawal_id: str | None


@dataclass(frozen=True, slots=True)
class RenderedProjectionSemantics:
    artifact_id: str
    community_identity_id: str
    community_reference: str
    disclosure_mode: str
    entries: tuple[RenderedEntrySemantics, ...]
    explicit_non_claims: tuple[str, ...] = _NON_CLAIMS

    def __post_init__(self) -> None:
        if self.explicit_non_claims != _NON_CLAIMS:
            raise ValueError("renderer semantics cannot strengthen artifact claims")


@dataclass(frozen=True, slots=True)
class RenderedPage:
    artifact_id: str
    style: RendererStyle
    semantics: RenderedProjectionSemantics
    html: str
    renderer_version: str = RENDERER_VERSION

    def __post_init__(self) -> None:
        if self.renderer_version != RENDERER_VERSION:
            raise ValueError("unsupported renderer version")
        if self.artifact_id != self.semantics.artifact_id:
            raise ValueError("rendered page does not bind artifact semantics")
        if not isinstance(self.html, str) or not self.html:
            raise ValueError("rendered page must contain local HTML")


def _receipt_pairs(
    receipts: ArtifactReceiptReferences | None,
) -> tuple[tuple[str, str], ...]:
    if receipts is None:
        return ()
    values = (
        ("source qualification", receipts.source_qualification_receipt_id),
        ("source observation", receipts.source_observation_receipt_id),
        ("source currentness", receipts.source_currentness_receipt_id),
        ("submission evidence", receipts.submission_evidence_receipt_id),
        ("moderator authorization", receipts.moderator_authorization_id),
        ("community admission", receipts.admission_id),
        ("projection", receipts.projection_reference_id),
    )
    if receipts.withdrawal_id is not None:
        values = (*values, ("author withdrawal", receipts.withdrawal_id))
    if receipts.removal_id is not None:
        values = (*values, ("community removal", receipts.removal_id))
    return values


def _entry_semantics(entry: ProjectionArtifactEntry) -> RenderedEntrySemantics:
    presentation = entry.presentation
    if presentation is not None and not isinstance(
        presentation, BoundedSourcePresentation
    ):
        raise TypeError("artifact presentation is not renderable")
    state = str(entry.lifecycle_state)
    try:
        notice = _STATE_NOTICES[state]
    except KeyError as exc:
        raise ValueError("artifact lifecycle state is not renderable") from exc
    return RenderedEntrySemantics(
        entry_id=entry.entry_id,
        projection_identity=entry.projection_identity,
        projection_state_id=entry.projection_state_id,
        lifecycle_state=state,
        lifecycle_notice=notice,
        source_uri=entry.source_uri,
        admitted_source_cid=entry.admitted_source_cid,
        author_did=entry.author_did,
        title=None if presentation is None else presentation.title,
        body=None if presentation is None else presentation.body,
        author_display_reference=(
            None if presentation is None else presentation.author_display_reference
        ),
        receipt_references=_receipt_pairs(entry.technical_receipts),
        lifecycle_links=entry.available_lifecycle_links,
        removal_id=entry.removal_id,
        withdrawal_id=entry.withdrawal_id,
    )


def _semantics(artifact: object) -> RenderedProjectionSemantics:
    if not isinstance(artifact, ProjectionArtifact):
        raise TypeError("renderer requires a typed ProjectionArtifact")
    artifact.validate_integrity()
    return RenderedProjectionSemantics(
        artifact_id=artifact.artifact_id,
        community_identity_id=artifact.community_identity_id,
        community_reference=artifact.community_actor_did,
        disclosure_mode=str(artifact.disclosure_mode),
        entries=tuple(_entry_semantics(entry) for entry in artifact.entries),
    )


def _audit_html(entry: RenderedEntrySemantics) -> str:
    if not entry.receipt_references and not entry.lifecycle_links:
        return ""
    receipts = "".join(
        f"<li><span>{escape(label)}</span>: <code>{escape(value)}</code></li>"
        for label, value in entry.receipt_references
    )
    links = "".join(
        f"<li><code>{escape(value)}</code></li>" for value in entry.lifecycle_links
    )
    return (
        '<details class="technical-audit"><summary>Why is this here?</summary>'
        f"<h4>Receipt references</h4><ul>{receipts}</ul>"
        f"<h4>Available lifecycle links</h4><ul>{links}</ul></details>"
    )


def _presentation_html(entry: RenderedEntrySemantics) -> str:
    if entry.title is None:
        return ""
    return (
        f"<h3>{escape(entry.title)}</h3>"
        f"<p>{escape(entry.body or '')}</p>"
        f'<p class="author">By '
        f"{escape(entry.author_display_reference or entry.author_did)}</p>"
    )


class CompactFixtureRenderer:
    """Minimal markup; no acquisition, policy, or authorization behavior."""

    style = RendererStyle.COMPACT

    def render(self, artifact: object) -> RenderedPage:
        semantics = _semantics(artifact)
        entries = "".join(
            (
                f'<article data-state="{escape(entry.lifecycle_state)}">'
                f"{_presentation_html(entry)}"
                f'<p class="lifecycle">{escape(entry.lifecycle_notice)}</p>'
                f"{_audit_html(entry)}</article>"
            )
            for entry in semantics.entries
        )
        html = (
            '<!doctype html><html><head><meta charset="utf-8">'
            "<title>Community projection fixture</title></head><body>"
            f"<header><h1>Community projection</h1><code>"
            f"{escape(semantics.community_reference)}</code></header>"
            f"<main>{entries}</main></body></html>"
        )
        return RenderedPage(
            artifact_id=semantics.artifact_id,
            style=self.style,
            semantics=semantics,
            html=html,
        )


class AccessibleFixtureRenderer:
    """Alternative markup proving that the artifact does not bind one renderer."""

    style = RendererStyle.ACCESSIBLE

    def render(self, artifact: object) -> RenderedPage:
        semantics = _semantics(artifact)
        entries = "".join(
            (
                f'<li><section aria-labelledby="entry-{index}">'
                f'<h2 id="entry-{index}">Projection item {index}</h2>'
                f"{_presentation_html(entry)}"
                f'<p role="status">{escape(entry.lifecycle_notice)}</p>'
                f"{_audit_html(entry)}</section></li>"
            )
            for index, entry in enumerate(semantics.entries, start=1)
        )
        html = (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            "<title>Community projection fixture</title></head><body>"
            "<main><h1>Community projection</h1>"
            f"<p>Community reference: <code>"
            f"{escape(semantics.community_reference)}</code></p>"
            f'<ol aria-label="Projection entries">{entries}</ol></main></body></html>'
        )
        return RenderedPage(
            artifact_id=semantics.artifact_id,
            style=self.style,
            semantics=semantics,
            html=html,
        )


def refuse_renderer_claim_upgrade(labels: object) -> None:
    """Rendering cannot infer access, authority, truth, or lifecycle changes."""

    if not isinstance(labels, dict) or any(not isinstance(key, str) for key in labels):
        raise TypeError("renderer claim labels must be an object with string keys")
    if labels:
        raise ValueError("renderer cannot add authorization or authority claims")
