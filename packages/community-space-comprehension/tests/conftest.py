from __future__ import annotations

import json
from pathlib import Path

import pytest

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
from community_space_prototype import LocalCommunityPrototype

ROOT = Path(__file__).resolve().parents[3]
M5A_VECTOR = ROOT / "tests" / "fixtures" / "space-community" / "scv0-m5a.json"
M6C_VECTOR = ROOT / "tests" / "fixtures" / "space-community" / "scv0-m6c.json"

COMMUNITY_ID = "sha256:" + "1" * 64
SPACE_ID = "sha256:" + "2" * 64
PROJECTION_ID = "sha256:" + "3" * 64
ADMISSION_ID = "sha256:" + "4" * 64
REMOVAL_ID = "sha256:" + "5" * 64
POST_ID = "sha256:33981b56015a979c8f4333d2ae46aa2cdc7f00090a2dbca4e1f23aed18560688"


def _receipts(*, removed: bool) -> ArtifactReceiptReferences:
    return ArtifactReceiptReferences(
        source_qualification_receipt_id="sha256:" + "6" * 64,
        source_observation_receipt_id="sha256:" + "7" * 64,
        source_currentness_receipt_id="sha256:" + "8" * 64,
        submission_evidence_receipt_id="sha256:" + "9" * 64,
        moderator_authorization_id="sha256:" + "a" * 64,
        admission_id=ADMISSION_ID,
        projection_reference_id="sha256:" + "b" * 64,
        removal_id=REMOVAL_ID if removed else None,
    )


@pytest.fixture
def m6c() -> dict[str, object]:
    m5a = json.loads(M5A_VECTOR.read_text(encoding="utf-8"))
    vector = json.loads(M6C_VECTOR.read_text(encoding="utf-8"))
    presentation_data = m5a["presentation"]
    assert isinstance(presentation_data, dict)
    presentation = BoundedSourcePresentation(
        source_reference_id=POST_ID,
        source_uri=str(presentation_data["sourceUri"]),
        source_cid=str(presentation_data["sourceCid"]),
        title=str(presentation_data["title"]),
        body=str(presentation_data["body"]),
        author_display_reference=str(presentation_data["authorDisplayReference"]),
    )
    policies = {
        False: DisclosurePolicy(
            mode=DisclosureMode.ORDINARY,
            policy_reference_id=str(m5a["ordinaryPolicyReference"]),
            publication_reference_id=str(m5a["ordinaryPublicationReference"]),
        ),
        True: DisclosurePolicy(
            mode=DisclosureMode.TECHNICAL_AUDIT,
            policy_reference_id=str(m5a["auditPolicyReference"]),
            publication_reference_id=str(m5a["auditPublicationReference"]),
        ),
    }

    def artifact(state: str, *, audit: bool) -> ProjectionArtifact:
        removed = state == "removed"
        relationship = {
            "added": "exact",
            "changed_at_source": "changed_at_source",
            "source_unavailable": "unavailable",
            "removed": "exact",
        }[state]
        policy = policies[audit]
        entry = ProjectionArtifactEntry(
            projection_identity=PROJECTION_ID,
            projection_state_id=(
                "sha256:"
                + {
                    "added": "c",
                    "changed_at_source": "d",
                    "source_unavailable": "e",
                    "removed": "f",
                }[state]
                * 64
            ),
            lifecycle_state=state,
            community_identity_id=COMMUNITY_ID,
            post_reference_id=POST_ID,
            source_uri=presentation.source_uri,
            admitted_source_cid=presentation.source_cid,
            author_did="did:web:author.invalid.test",
            admission_id=ADMISSION_ID,
            admitted_at="2026-08-21T12:02:00Z",
            source_observation_id="sha256:" + "0" * 64,
            source_relationship=relationship,
            presentation=presentation if state == "added" else None,
            technical_receipts=_receipts(removed=removed) if audit else None,
            available_lifecycle_links=(
                ("sha256:" + "1" * 64, "sha256:" + "2" * 64) if audit else ()
            ),
            removal_id=REMOVAL_ID if removed else None,
        )
        return ProjectionArtifact(
            community_identity_id=COMMUNITY_ID,
            community_actor_did="did:web:community.invalid.test",
            space_identity_id=SPACE_ID,
            projection_version="scv0-projection-reducer/1",
            disclosure_mode=policy.mode,
            disclosure_policy_id=policy.policy_id,
            disclosure_policy_reference_id=policy.policy_reference_id,
            publication_reference_id=policy.publication_reference_id,
            entries=(entry,),
        )

    def feed(state: str, *, audit: bool):
        item = artifact(state, audit=audit)
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
                published_at=str(
                    vector["auditPublishedAt"]
                    if audit
                    else vector["ordinaryPublishedAt"]
                ),
            )
        )

    prototype = LocalCommunityPrototype()
    sites = {
        state: prototype.render(feed(state, audit=False), feed(state, audit=True))
        for state in (
            "added",
            "changed_at_source",
            "source_unavailable",
            "removed",
        )
    }
    return {"vector": vector, "sites": sites}
