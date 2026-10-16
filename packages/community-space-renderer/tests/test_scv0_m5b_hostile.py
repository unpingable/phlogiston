from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from community_model import ValidationError
from community_space_artifact import BoundedSourcePresentation
from community_space_renderer import (
    AccessibleFixtureRenderer,
    CompactFixtureRenderer,
    RenderedProjectionSemantics,
    refuse_renderer_claim_upgrade,
)


def test_m5b_h1_raw_space_record_refuses(m5b: dict[str, object]) -> None:
    raw = {
        "$type": "test.invalid.community.post",
        "text": "raw Space record",
        "spaceCredential": "not-for-renderer",
    }
    with pytest.raises(TypeError, match="typed ProjectionArtifact"):
        CompactFixtureRenderer().render(raw)


def test_m5b_h2_credential_bearing_tampered_artifact_refuses(
    m5b: dict[str, object],
) -> None:
    artifact = m5b["added"]
    presentation = artifact.entries[0].presentation
    assert isinstance(presentation, BoundedSourcePresentation)
    object.__setattr__(presentation, "body", "access_token: synthetic-secret")
    with pytest.raises(ValidationError, match="^artifact_secret_material_refused at"):
        AccessibleFixtureRenderer().render(artifact)


def test_m5b_h3_renderer_cannot_infer_authorization() -> None:
    with pytest.raises(ValueError, match="cannot add authorization"):
        refuse_renderer_claim_upgrade(
            {"readerAuthorized": True, "governanceAuthority": True}
        )
    with pytest.raises(ValueError, match="cannot strengthen"):
        RenderedProjectionSemantics(
            artifact_id="sha256:" + "1" * 64,
            community_identity_id="sha256:" + "2" * 64,
            community_reference="did:web:community.invalid.test",
            disclosure_mode="ordinary_reader",
            entries=(),
            explicit_non_claims=(),
        )


def test_m5b_h4_renderer_is_read_only_over_immutable_artifact(
    m5b: dict[str, object],
) -> None:
    artifact = m5b["removed"]
    before = artifact.artifact_id
    page = CompactFixtureRenderer().render(artifact)
    assert artifact.artifact_id == before == page.artifact_id
    with pytest.raises((FrozenInstanceError, AttributeError)):
        artifact.entries = ()  # type: ignore[misc]
    with pytest.raises((FrozenInstanceError, AttributeError)):
        page.semantics.entries[0].lifecycle_state = "added"  # type: ignore[misc]


def test_renderer_escapes_disclosed_presentation(m5b: dict[str, object]) -> None:
    artifact = m5b["added"]
    presentation = artifact.entries[0].presentation
    assert isinstance(presentation, BoundedSourcePresentation)
    escaped = replace(presentation, title="<script>alert(1)</script>")
    entry = replace(artifact.entries[0], presentation=escaped)
    changed_artifact = replace(artifact, entries=(entry,))
    page = CompactFixtureRenderer().render(changed_artifact)
    assert "<script>" not in page.html
    assert "&lt;script&gt;" in page.html


def test_ordinary_renderer_cannot_display_technical_details(
    m5b: dict[str, object],
) -> None:
    page = CompactFixtureRenderer().render(m5b["added"])
    assert page.semantics.entries[0].receipt_references == ()
    assert "Why is this here?" not in page.html


def test_removed_audit_retains_history_without_republishing_content(
    m5b: dict[str, object],
) -> None:
    page = AccessibleFixtureRenderer().render(m5b["removed_audit"])
    entry = page.semantics.entries[0]
    assert entry.receipt_references
    assert entry.lifecycle_links
    assert entry.title is None
    assert "Why is this here?" in page.html
    assert "Synthetic community post" not in page.html
