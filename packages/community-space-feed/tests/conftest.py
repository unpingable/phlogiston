from __future__ import annotations

import json
from pathlib import Path

import pytest

from community_space_artifact import (
    ArtifactReceiptReferences,
    BoundedSourcePresentation,
    DisclosureMode,
    DisclosurePolicy,
    NonPublishedCandidate,
    ProjectionArtifact,
    ProjectionArtifactEntry,
)
from community_space_feed import (
    FeedPublicationRequest,
    LocalProjectionFeedBoundary,
    PublicProjectionChannel,
)

ROOT = Path(__file__).resolve().parents[3]
M5A_VECTOR = ROOT / "tests" / "fixtures" / "space-community" / "scv0-m5a.json"
M6A_VECTOR = ROOT / "tests" / "fixtures" / "space-community" / "scv0-m6a.json"

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
def m6a() -> dict[str, object]:
    m5a = json.loads(M5A_VECTOR.read_text(encoding="utf-8"))
    vector = json.loads(M6A_VECTOR.read_text(encoding="utf-8"))
    presentation_data = m5a["presentation"]
    assert isinstance(presentation_data, dict)
    presentation = BoundedSourcePresentation(
        source_reference_id=POST_ID,
        source_uri=str(presentation_data["sourceUri"]),
        source_cid=str(presentation_data["sourceCid"]),
        title=str(presentation_data["title"]),
        body=str(presentation_data["body"]),
        author_display_reference=str(presentation_data["authorDisplayReference"]),
        profile=str(presentation_data["profile"]),
    )
    ordinary_policy = DisclosurePolicy(
        mode=DisclosureMode.ORDINARY,
        policy_reference_id=str(m5a["ordinaryPolicyReference"]),
        publication_reference_id=str(m5a["ordinaryPublicationReference"]),
    )
    audit_policy = DisclosurePolicy(
        mode=DisclosureMode.TECHNICAL_AUDIT,
        policy_reference_id=str(m5a["auditPolicyReference"]),
        publication_reference_id=str(m5a["auditPublicationReference"]),
    )

    def artifact(state: str, *, audit: bool = False) -> ProjectionArtifact:
        removed = state == "removed"
        relationship = {
            "added": "exact",
            "changed_at_source": "changed_at_source",
            "removed": "exact",
        }[state]
        policy = audit_policy if audit else ordinary_policy
        entry = ProjectionArtifactEntry(
            projection_identity=PROJECTION_ID,
            projection_state_id=(
                "sha256:"
                + {"added": "c", "changed_at_source": "d", "removed": "e"}[state] * 64
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

    def publish(artifact: ProjectionArtifact, *, audit: bool = False):
        return LocalProjectionFeedBoundary().publish(
            FeedPublicationRequest(
                artifact=artifact,
                expected_artifact_id=artifact.artifact_id,
                expected_community_identity_id=artifact.community_identity_id,
                expected_publication_reference_id=artifact.publication_reference_id,
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

    added = artifact("added")
    changed = artifact("changed_at_source")
    removed = artifact("removed")
    added_audit = artifact("added", audit=True)
    removed_audit = artifact("removed", audit=True)
    candidate = NonPublishedCandidate(
        projection_identity=PROJECTION_ID,
        projection_state_id="sha256:" + "f" * 64,
        community_identity_id=COMMUNITY_ID,
        disclosure_policy_id=ordinary_policy.policy_id,
    )
    return {
        "vector": vector,
        "presentation": presentation,
        "added": added,
        "changed": changed,
        "removed": removed,
        "added_audit": added_audit,
        "removed_audit": removed_audit,
        "added_feed": publish(added),
        "changed_feed": publish(changed),
        "removed_feed": publish(removed),
        "added_audit_feed": publish(added_audit, audit=True),
        "removed_audit_feed": publish(removed_audit, audit=True),
        "candidate": candidate,
        "publish": publish,
    }
