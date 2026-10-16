from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from community_space_comprehension import (
    ComprehensionVerdict,
    SyntheticComprehensionInstrument,
    SyntheticComprehensionReport,
    refuse_comprehension_claim_upgrade,
)
from community_space_feed import FeedPublicationRequest, LocalProjectionFeedBoundary
from community_space_prototype import LocalCommunityPrototype


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


@pytest.mark.parametrize(
    "claim",
    (
        {"humanComprehension": True},
        {"humanUsability": True},
        {"readerAuthorization": True},
        {"governanceAuthority": True},
    ),
)
def test_synthetic_success_cannot_upgrade_to_human_or_authority_claims(
    claim: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="cannot add human"):
        refuse_comprehension_claim_upgrade(claim)


def test_noncanonical_page_with_recomputed_digest_refuses(
    m6c: dict[str, object],
) -> None:
    site = m6c["sites"]["changed_at_source"]
    altered = site.ordinary_html.replace("Changed at source", "Updated")
    modified = replace(
        site,
        ordinary_html=altered,
        ordinary_html_sha256=_digest(altered),
    )
    with pytest.raises(ValueError, match="canonical M6B replay"):
        SyntheticComprehensionInstrument().qualify(modified)


def test_audit_reference_leak_with_recomputed_digest_refuses(
    m6c: dict[str, object],
) -> None:
    site = m6c["sites"]["added"]
    receipt = site.audit_semantics.entries[0].receipt_references[0][1]
    altered = site.ordinary_html.replace("</body>", f"<p>{receipt}</p></body>")
    modified = replace(
        site,
        ordinary_html=altered,
        ordinary_html_sha256=_digest(altered),
    )
    with pytest.raises(ValueError, match="canonical M6B replay"):
        SyntheticComprehensionInstrument().qualify(modified)


def test_raw_page_or_caller_answer_key_refuses(m6c: dict[str, object]) -> None:
    with pytest.raises(TypeError, match="typed PrototypeSite"):
        SyntheticComprehensionInstrument().qualify(
            {"html": "Added", "answer": "community owns source"}  # type: ignore[arg-type]
        )


def test_empty_or_multi_entry_profile_cannot_be_inferred_from_global_cues(
    m6c: dict[str, object],
) -> None:
    added = m6c["sites"]["added"]
    removed = m6c["sites"]["removed"]

    def extend(feed, second_feed):
        second = replace(
            second_feed.artifact.entries[0], projection_identity="sha256:" + "0" * 64
        )
        artifact = replace(feed.artifact, entries=(feed.artifact.entries[0], second))
        return LocalProjectionFeedBoundary().publish(
            FeedPublicationRequest(
                artifact=artifact,
                expected_artifact_id=artifact.artifact_id,
                expected_community_identity_id=artifact.community_identity_id,
                expected_publication_reference_id=artifact.publication_reference_id,
                channel=feed.channel,
                published_at=feed.published_at,
            )
        )

    site = LocalCommunityPrototype().render(
        extend(added.ordinary_feed, removed.ordinary_feed),
        extend(added.audit_feed, removed.audit_feed),
    )
    with pytest.raises(ValueError, match="supports one lifecycle entry"):
        SyntheticComprehensionInstrument().qualify(site)


def test_report_cannot_be_relabelled_as_success(m6c: dict[str, object]) -> None:
    report = SyntheticComprehensionInstrument().qualify(m6c["sites"]["removed"])
    failed = replace(
        report,
        outcomes=(replace(report.outcomes[0], answerable=False), *report.outcomes[1:]),
        verdict=ComprehensionVerdict.INFORMATION_INSUFFICIENT,
    )
    with pytest.raises(ValueError, match="does not match exact site"):
        failed.validate_against(m6c["sites"]["removed"])


def test_outcome_failure_cannot_keep_success_verdict(m6c: dict[str, object]) -> None:
    report = SyntheticComprehensionInstrument().qualify(m6c["sites"]["added"])
    with pytest.raises(ValueError, match="verdict contradicts outcomes"):
        SyntheticComprehensionReport(
            prototype_site_id=report.prototype_site_id,
            ordinary_html_sha256=report.ordinary_html_sha256,
            audit_html_sha256=report.audit_html_sha256,
            outcomes=(
                replace(report.outcomes[0], answerable=False),
                *report.outcomes[1:],
            ),
            verdict=ComprehensionVerdict.INFORMATION_SUFFICIENT,
        )


def test_timestamp_or_possession_cannot_become_currentness_or_permission() -> None:
    with pytest.raises(ValueError, match="cannot add human"):
        refuse_comprehension_claim_upgrade(
            {"laterPublicationMeansCurrent": True, "possessionMeansPermission": True}
        )
