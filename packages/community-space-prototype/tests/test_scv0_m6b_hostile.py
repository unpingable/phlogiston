from __future__ import annotations

from dataclasses import replace

import pytest

from community_space_prototype import refuse_prototype_claim_upgrade


def test_ui_h1_prototype_cannot_invent_authority() -> None:
    with pytest.raises(ValueError, match="cannot add authority"):
        refuse_prototype_claim_upgrade(
            {"moderatorAuthority": True, "governanceAuthority": True}
        )


def test_ui_h2_hidden_lifecycle_breaks_page_integrity(m6b: dict[str, object]) -> None:
    site = m6b["changed_site"]
    with pytest.raises(ValueError, match="ordinary prototype page integrity"):
        replace(
            site,
            ordinary_html=site.ordinary_html.replace("Changed at source", "Updated"),
        )
    assert site.canonical_semantics.entries[0].lifecycle_state == "changed_at_source"


def test_ui_h3_prototype_cannot_change_artifact_meaning(
    m6b: dict[str, object],
) -> None:
    ordinary_added, _ = m6b["pairs"]["added"]
    _, audit_changed = m6b["pairs"]["changed_at_source"]
    with pytest.raises(ValueError, match="different projection state"):
        m6b["prototype"].render(ordinary_added, audit_changed)


def test_ui_h4_prototype_cannot_claim_source_ownership() -> None:
    with pytest.raises(ValueError, match="cannot add authority"):
        refuse_prototype_claim_upgrade({"sourceOwnership": "community"})


def test_raw_artifact_or_mapping_is_not_a_prototype_feed(
    m6b: dict[str, object],
) -> None:
    ordinary, audit = m6b["pairs"]["added"]
    with pytest.raises(TypeError, match="typed public projection feeds"):
        m6b["prototype"].render(ordinary.artifact, audit)
    with pytest.raises(TypeError, match="typed public projection feeds"):
        m6b["prototype"].render({"feed": ordinary}, audit)


def test_audit_feed_cannot_be_used_as_ordinary_view(m6b: dict[str, object]) -> None:
    _, audit = m6b["pairs"]["added"]
    with pytest.raises(ValueError, match="ordinary public feed"):
        m6b["prototype"].render(audit, audit)


def test_prototype_has_no_ranking_or_reader_authorization_claims(
    m6b: dict[str, object],
) -> None:
    site = m6b["added_site"]
    assert "ranking" in site.explicit_non_claims
    assert "reader_authorization" in site.explicit_non_claims
    assert "score" not in site.ordinary_html.lower()
    assert "vote" not in site.ordinary_html.lower()
    with pytest.raises(ValueError, match="cannot add authority"):
        refuse_prototype_claim_upgrade({"artifactPossessionAuthorizesReader": True})


def test_postpublication_presentation_mutation_refuses(m6b: dict[str, object]) -> None:
    ordinary, audit = m6b["pairs"]["added"]
    presentation = ordinary.artifact.entries[0].presentation
    assert presentation is not None
    object.__setattr__(presentation, "title", "<script>alert(1)</script>")
    with pytest.raises(ValueError, match="published artifact identity mismatch"):
        m6b["prototype"].render(ordinary, audit)
