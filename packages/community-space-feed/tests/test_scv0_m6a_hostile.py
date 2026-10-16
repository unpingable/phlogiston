from __future__ import annotations

import pytest

from community_space_artifact import BoundedSourcePresentation
from community_space_feed import (
    FeedPublicationRequest,
    LocalProjectionFeedBoundary,
    PublicProjectionChannel,
    refuse_feed_claim_upgrade,
)


def _request(artifact: object, m6a: dict[str, object], *, audit: bool = False):
    expected = m6a["added"]
    return FeedPublicationRequest(
        artifact=artifact,
        expected_artifact_id=expected.artifact_id,
        expected_community_identity_id=expected.community_identity_id,
        expected_publication_reference_id=expected.publication_reference_id,
        channel=(
            PublicProjectionChannel.TECHNICAL_AUDIT
            if audit
            else PublicProjectionChannel.ORDINARY
        ),
        published_at="2026-08-22T16:00:00Z",
    )


def test_m6a_h1_raw_source_record_refuses(m6a: dict[str, object]) -> None:
    request = _request(
        {"$type": "test.invalid.community.post", "text": "raw source"}, m6a
    )
    with pytest.raises(TypeError, match="only a ProjectionArtifact"):
        LocalProjectionFeedBoundary().publish(request)


def test_m6a_h2_suggested_candidate_is_not_published(
    m6a: dict[str, object],
) -> None:
    request = _request(m6a["candidate"], m6a)
    with pytest.raises(TypeError, match="only a ProjectionArtifact"):
        LocalProjectionFeedBoundary().publish(request)


def test_m6a_h3_moderator_authority_metadata_refuses() -> None:
    with pytest.raises(TypeError, match="typed publication request"):
        LocalProjectionFeedBoundary().publish(
            {"artifact": "x", "moderatorAuthority": True}  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="cannot add authorization"):
        refuse_feed_claim_upgrade({"moderatorAuthority": True})


def test_m6a_h4_postpublication_mutation_breaks_identity(
    m6a: dict[str, object],
) -> None:
    feed = m6a["added_feed"]
    presentation = feed.artifact.entries[0].presentation
    assert isinstance(presentation, BoundedSourcePresentation)
    object.__setattr__(presentation, "title", "Mutated after publication")
    with pytest.raises(ValueError, match="published artifact identity mismatch"):
        feed.validate_integrity()


def test_m6a_h5_audit_artifact_cannot_use_ordinary_channel(
    m6a: dict[str, object],
) -> None:
    artifact = m6a["added_audit"]
    request = FeedPublicationRequest(
        artifact=artifact,
        expected_artifact_id=artifact.artifact_id,
        expected_community_identity_id=artifact.community_identity_id,
        expected_publication_reference_id=artifact.publication_reference_id,
        channel=PublicProjectionChannel.ORDINARY,
        published_at="2026-08-22T16:00:00Z",
    )
    with pytest.raises(ValueError, match="channel and artifact disclosure mode"):
        LocalProjectionFeedBoundary().publish(request)


def test_m6a_h6_publication_possession_is_not_reader_authorization() -> None:
    with pytest.raises(ValueError, match="cannot add authorization"):
        refuse_feed_claim_upgrade(
            {"artifactPossessionAuthorizesReader": True, "membership": True}
        )


def test_request_identity_and_community_substitution_refuse(
    m6a: dict[str, object],
) -> None:
    artifact = m6a["added"]
    with pytest.raises(ValueError, match="request artifact identity mismatch"):
        LocalProjectionFeedBoundary().publish(
            FeedPublicationRequest(
                artifact=artifact,
                expected_artifact_id="sha256:" + "f" * 64,
                expected_community_identity_id=artifact.community_identity_id,
                expected_publication_reference_id=artifact.publication_reference_id,
                channel=PublicProjectionChannel.ORDINARY,
                published_at="2026-08-22T16:00:00Z",
            )
        )
    with pytest.raises(ValueError, match="request community mismatch"):
        LocalProjectionFeedBoundary().publish(
            FeedPublicationRequest(
                artifact=artifact,
                expected_artifact_id=artifact.artifact_id,
                expected_community_identity_id="sha256:" + "e" * 64,
                expected_publication_reference_id=artifact.publication_reference_id,
                channel=PublicProjectionChannel.ORDINARY,
                published_at="2026-08-22T16:00:00Z",
            )
        )


def test_publication_time_is_context_not_currentness(m6a: dict[str, object]) -> None:
    artifact = m6a["changed"]
    request = FeedPublicationRequest(
        artifact=artifact,
        expected_artifact_id=artifact.artifact_id,
        expected_community_identity_id=artifact.community_identity_id,
        expected_publication_reference_id=artifact.publication_reference_id,
        channel=PublicProjectionChannel.ORDINARY,
        published_at="2036-08-22T16:00:00Z",
    )
    feed = LocalProjectionFeedBoundary().publish(request)
    assert "repository_currentness" in feed.explicit_non_claims
    assert feed.entries[0].presentation is None


def test_postconstruction_request_channel_tampering_refuses(
    m6a: dict[str, object],
) -> None:
    artifact = m6a["added"]
    request = FeedPublicationRequest(
        artifact=artifact,
        expected_artifact_id=artifact.artifact_id,
        expected_community_identity_id=artifact.community_identity_id,
        expected_publication_reference_id=artifact.publication_reference_id,
        channel=PublicProjectionChannel.ORDINARY,
        published_at="2026-08-22T16:00:00Z",
    )
    object.__setattr__(request, "channel", "private_reader")
    with pytest.raises(ValueError, match="unsupported public projection channel"):
        LocalProjectionFeedBoundary().publish(request)
