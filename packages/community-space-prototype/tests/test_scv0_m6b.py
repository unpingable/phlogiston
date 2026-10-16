from __future__ import annotations

import hashlib
from pathlib import Path

from community_space_prototype import PROTOTYPE_VERSION, PrototypeSite


def test_m6b_added_page_is_human_facing(m6b: dict[str, object]) -> None:
    site = m6b["added_site"]
    assert isinstance(site, PrototypeSite)
    assert site.prototype_version == PROTOTYPE_VERSION
    assert "<h1>Community</h1>" in site.ordinary_html
    assert "Synthetic community post" in site.ordinary_html
    assert "did:web:author.invalid.test" in site.ordinary_html
    assert '<p class="state">Added</p>' in site.ordinary_html
    assert "Why is this here?" in site.ordinary_html
    assert "The author still owns the source." in site.ordinary_html


def test_m6b_ordinary_and_audit_views_are_separate(m6b: dict[str, object]) -> None:
    site = m6b["added_site"]
    audit_receipt = "sha256:" + "6" * 64
    assert audit_receipt not in site.ordinary_html
    assert site.audit_feed.feed_id not in site.ordinary_html
    assert audit_receipt in site.audit_html
    assert site.audit_feed.feed_id in site.audit_html
    assert "Receipt references" in site.audit_html
    assert site.canonical_semantics.entries[0].receipt_references == ()
    assert site.audit_semantics.entries[0].receipt_references


def test_m6b_changed_page_preserves_lifecycle_without_replacement(
    m6b: dict[str, object],
) -> None:
    site = m6b["changed_site"]
    assert "Changed at source" in site.ordinary_html
    assert "admitted presentation was not replaced" in site.ordinary_html
    assert "Synthetic community post" not in site.ordinary_html
    assert site.canonical_semantics.entries[0].title is None


def test_m6b_removed_page_preserves_removal_without_source_ownership(
    m6b: dict[str, object],
) -> None:
    site = m6b["removed_site"]
    assert "Removed" in site.ordinary_html
    assert "author source was not mutated" in site.ordinary_html
    assert "Synthetic community post" not in site.ordinary_html
    assert site.canonical_semantics.entries[0].removal_id is not None


def test_m6b_site_is_deterministic_and_bound_to_exact_feeds(
    m6b: dict[str, object],
) -> None:
    site = m6b["added_site"]
    ordinary, audit = m6b["pairs"]["added"]
    replay = m6b["prototype"].render(ordinary, audit)
    assert replay == site
    assert replay.site_id == site.validate_integrity()
    assert site.ordinary_html_sha256.startswith("sha256:")
    assert site.audit_html_sha256.startswith("sha256:")


def test_m6b_fixture_checksum_and_nonsecret_status(m6b: dict[str, object]) -> None:
    assert m6b["vector"]["secretMaterialPresent"] is False
    fixture = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "space-community"
        / "scv0-m6b.json"
    )
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == (
        "3cf550281cca4409b12a2364b1153c63d0a466f8c88b4e31285c7dd1655defb9"
    )
