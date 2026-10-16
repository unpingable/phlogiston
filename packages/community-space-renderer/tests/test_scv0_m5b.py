from __future__ import annotations

import hashlib
from pathlib import Path

from community_space_renderer import (
    RENDERER_VERSION,
    AccessibleFixtureRenderer,
    CompactFixtureRenderer,
    RendererStyle,
)


def test_m5b_p1_added_artifact_renders(m5b: dict[str, object]) -> None:
    page = CompactFixtureRenderer().render(m5b["added"])
    assert page.renderer_version == RENDERER_VERSION
    assert page.style is RendererStyle.COMPACT
    assert page.artifact_id == m5b["added"].artifact_id
    assert page.semantics.entries[0].lifecycle_state == "added"
    assert "Synthetic community post" in page.html
    assert "Added by this community." in page.html
    assert "Why is this here?" not in page.html


def test_m5b_p2_changed_artifact_renders_lifecycle_notice(
    m5b: dict[str, object],
) -> None:
    page = CompactFixtureRenderer().render(m5b["changed"])
    entry = page.semantics.entries[0]
    assert entry.lifecycle_state == "changed_at_source"
    assert entry.title is None
    assert "admitted presentation was not replaced" in page.html
    assert "Synthetic community post" not in page.html


def test_m5b_p3_removed_artifact_renders_removal_state(
    m5b: dict[str, object],
) -> None:
    page = AccessibleFixtureRenderer().render(m5b["removed"])
    entry = page.semantics.entries[0]
    assert entry.lifecycle_state == "removed"
    assert entry.removal_id is not None
    assert "author source was not mutated" in page.html
    assert "Synthetic community post" not in page.html


def test_m5b_p4_replaceable_renderers_preserve_equivalent_semantics(
    m5b: dict[str, object],
) -> None:
    compact = CompactFixtureRenderer().render(m5b["added_audit"])
    accessible = AccessibleFixtureRenderer().render(m5b["added_audit"])
    assert compact.style is not accessible.style
    assert compact.html != accessible.html
    assert compact.semantics == accessible.semantics
    assert compact.artifact_id == accessible.artifact_id
    assert "Why is this here?" in compact.html
    assert "Why is this here?" in accessible.html


def test_source_unavailable_renders_no_replacement_content(
    m5b: dict[str, object],
) -> None:
    page = CompactFixtureRenderer().render(m5b["unavailable"])
    entry = page.semantics.entries[0]
    assert entry.lifecycle_state == "source_unavailable"
    assert entry.title is None and entry.body is None
    assert "currently unavailable" in page.html


def test_author_withdrawal_renders_no_content_and_retains_audit_occurrence(
    m5b: dict[str, object],
) -> None:
    ordinary = CompactFixtureRenderer().render(m5b["withdrawn"])
    audit = CompactFixtureRenderer().render(m5b["withdrawn_audit"])
    entry = ordinary.semantics.entries[0]
    assert entry.lifecycle_state == "author_withdrawn"
    assert entry.title is None and entry.body is None
    assert entry.withdrawal_id is not None
    assert "asked not to be featured" in ordinary.html
    assert "author withdrawal" in audit.html


def test_fixture_digest_and_nonsecret_status(m5b: dict[str, object]) -> None:
    assert m5b["vector"]["secretMaterialPresent"] is False
    fixture = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "space-community"
        / "scv0-m5b.json"
    )
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == (
        "c2197e766e0cc876232f8b24c32e00d11b98afb6fbaf3ff054d93c1b105ab8d2"
    )
