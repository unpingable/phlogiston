from __future__ import annotations

import hashlib
from pathlib import Path

from community_space_feed import (
    FEED_VERSION,
    LocalProjectionFeedBoundary,
    ProjectionFeedPublisher,
    PublicProjectionChannel,
)
from community_space_renderer import (
    AccessibleFixtureRenderer,
    CompactFixtureRenderer,
)


def test_m6a_p1_added_artifact_becomes_visible_feed_entry(
    m6a: dict[str, object],
) -> None:
    feed = m6a["added_feed"]
    assert isinstance(LocalProjectionFeedBoundary(), ProjectionFeedPublisher)
    assert feed.feed_version == FEED_VERSION
    assert feed.validate_integrity() == feed.feed_id
    assert feed.channel is PublicProjectionChannel.ORDINARY
    assert feed.artifact_id == m6a["added"].artifact_id
    assert len(feed.entries) == 1
    assert feed.entries[0].presentation == m6a["presentation"]
    assert feed.entries[0].technical_receipts is None


def test_m6a_p2_changed_at_source_is_not_replaced(m6a: dict[str, object]) -> None:
    feed = m6a["changed_feed"]
    entry = feed.entries[0]
    assert str(entry.lifecycle_state) == "changed_at_source"
    assert entry.presentation is None
    rendered = CompactFixtureRenderer().render(feed.artifact)
    assert "admitted presentation was not replaced" in rendered.html


def test_m6a_p3_removed_feed_preserves_history_without_content(
    m6a: dict[str, object],
) -> None:
    feed = m6a["removed_audit_feed"]
    entry = feed.entries[0]
    assert str(entry.lifecycle_state) == "removed"
    assert entry.presentation is None
    assert entry.removal_id is not None
    assert entry.technical_receipts is not None
    assert entry.available_lifecycle_links


def test_m6a_p4_independent_renderers_preserve_artifact_semantics(
    m6a: dict[str, object],
) -> None:
    artifact = m6a["added_feed"].artifact
    compact = CompactFixtureRenderer().render(artifact)
    accessible = AccessibleFixtureRenderer().render(artifact)
    assert compact.html != accessible.html
    assert compact.semantics == accessible.semantics
    assert compact.artifact_id == accessible.artifact_id == artifact.artifact_id


def test_feed_bytes_are_deterministic_and_preserve_publication_metadata(
    m6a: dict[str, object],
) -> None:
    feed = m6a["added_feed"]
    assert feed.to_bytes() == feed.to_bytes()
    assert feed.feed_id.startswith("sha256:")
    assert feed.community_identity_id == m6a["added"].community_identity_id
    assert feed.publication_reference_id == m6a["added"].publication_reference_id
    assert feed.published_at == "2026-08-22T16:00:00Z"
    assert b'technicalReceipts":null' in feed.to_bytes()


def test_m6a_fixture_checksum_and_nonsecret_status(m6a: dict[str, object]) -> None:
    assert m6a["vector"]["secretMaterialPresent"] is False
    fixture = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "space-community"
        / "scv0-m6a.json"
    )
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == (
        "981ea8fea4d68763f890a5790ec02459e35c8c391a34f08fbb52d3d691876400"
    )
