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

ROOT = Path(__file__).resolve().parents[3]
M5A_VECTOR = ROOT / "tests" / "fixtures" / "space-community" / "scv0-m5a.json"
M5B_VECTOR = ROOT / "tests" / "fixtures" / "space-community" / "scv0-m5b.json"

COMMUNITY_ID = "sha256:" + "1" * 64
SPACE_ID = "sha256:" + "2" * 64
PROJECTION_ID = "sha256:" + "3" * 64
ADMISSION_ID = "sha256:" + "4" * 64
REMOVAL_ID = "sha256:" + "5" * 64
WITHDRAWAL_ID = "sha256:" + "d" * 64
POST_ID = "sha256:33981b56015a979c8f4333d2ae46aa2cdc7f00090a2dbca4e1f23aed18560688"


def _receipts(*, removed: bool, withdrawn: bool = False) -> ArtifactReceiptReferences:
    return ArtifactReceiptReferences(
        source_qualification_receipt_id="sha256:" + "6" * 64,
        source_observation_receipt_id="sha256:" + "7" * 64,
        source_currentness_receipt_id="sha256:" + "8" * 64,
        submission_evidence_receipt_id="sha256:" + "9" * 64,
        moderator_authorization_id="sha256:" + "a" * 64,
        admission_id=ADMISSION_ID,
        projection_reference_id="sha256:" + "b" * 64,
        removal_id=REMOVAL_ID if removed else None,
        withdrawal_id=WITHDRAWAL_ID if withdrawn else None,
    )


@pytest.fixture
def m5b() -> dict[str, object]:
    m5a = json.loads(M5A_VECTOR.read_text(encoding="utf-8"))
    vector = json.loads(M5B_VECTOR.read_text(encoding="utf-8"))
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
    ordinary = DisclosurePolicy(
        mode=DisclosureMode.ORDINARY,
        policy_reference_id=str(m5a["ordinaryPolicyReference"]),
        publication_reference_id=str(m5a["ordinaryPublicationReference"]),
    )
    audit = DisclosurePolicy(
        mode=DisclosureMode.TECHNICAL_AUDIT,
        policy_reference_id=str(m5a["auditPolicyReference"]),
        publication_reference_id=str(m5a["auditPublicationReference"]),
    )

    def artifact(state: str, *, technical: bool = False) -> ProjectionArtifact:
        removed = state == "removed"
        withdrawn = state == "author_withdrawn"
        relationship = {
            "added": "exact",
            "changed_at_source": "changed_at_source",
            "source_unavailable": "unavailable",
            "author_withdrawn": "exact",
            "removed": "exact",
        }[state]
        policy = audit if technical else ordinary
        entry = ProjectionArtifactEntry(
            projection_identity=PROJECTION_ID,
            projection_state_id=(
                "sha256:"
                + {
                    "added": "c",
                    "changed_at_source": "d",
                    "source_unavailable": "e",
                    "author_withdrawn": "a",
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
            technical_receipts=(
                _receipts(removed=removed, withdrawn=withdrawn) if technical else None
            ),
            available_lifecycle_links=(
                ("sha256:" + "1" * 64, "sha256:" + "2" * 64) if technical else ()
            ),
            removal_id=REMOVAL_ID if removed else None,
            withdrawal_id=WITHDRAWAL_ID if withdrawn else None,
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

    return {
        "vector": vector,
        "presentation": presentation,
        "added": artifact("added"),
        "added_audit": artifact("added", technical=True),
        "changed": artifact("changed_at_source"),
        "unavailable": artifact("source_unavailable"),
        "withdrawn": artifact("author_withdrawn"),
        "withdrawn_audit": artifact("author_withdrawn", technical=True),
        "removed": artifact("removed"),
        "removed_audit": artifact("removed", technical=True),
    }
