from __future__ import annotations

import json
from pathlib import Path

import pytest

from community_space_model import (
    AuthorizedAction,
    AuthorWithdrawal,
    CommunityAdmission,
    CommunityIdentity,
    ExactSpaceRecordReference,
    ModeratorAuthorization,
    PostReference,
    ProjectionReference,
    RemovalRecord,
    RenderState,
    SourceRelationship,
    SpaceIdentity,
    Submission,
)

ROOT = Path(__file__).resolve().parents[3]
VECTOR = ROOT / "tests" / "fixtures" / "space-community" / "scv0-m1.json"


def _record(
    vector: dict[str, object],
    *,
    space: SpaceIdentity,
    name: str,
    author: str,
    collection: str,
) -> ExactSpaceRecordReference:
    records = vector["records"]
    assert isinstance(records, dict)
    record = records[name]
    assert isinstance(record, dict)
    return ExactSpaceRecordReference(
        space=space,
        author_did=author,
        collection=collection,
        rkey=str(record["rkey"]),
        cid=str(record["cid"]),
    )


@pytest.fixture
def m1() -> dict[str, object]:
    vector = json.loads(VECTOR.read_text(encoding="utf-8"))
    raw_space = vector["space"]
    actors = vector["actors"]
    collections = vector["collections"]
    receipts = vector["receipts"]
    times = vector["times"]
    assert isinstance(raw_space, dict)
    assert isinstance(actors, dict)
    assert isinstance(collections, dict)
    assert isinstance(receipts, dict)
    assert isinstance(times, dict)

    space = SpaceIdentity(
        authority_did=str(raw_space["authorityDid"]),
        space_type=str(raw_space["spaceType"]),
        skey=str(raw_space["skey"]),
    )
    community = CommunityIdentity(
        space=space, community_actor_did=str(actors["community"])
    )
    post_record = _record(
        vector,
        space=space,
        name="post",
        author=str(actors["author"]),
        collection=str(collections["post"]),
    )
    post = PostReference(
        record=post_record,
        source_qualification_receipt_id=str(receipts["postQualification"]),
    )
    submission_record = _record(
        vector,
        space=space,
        name="submission",
        author=str(actors["author"]),
        collection=str(collections["submission"]),
    )
    submission = Submission(
        record=submission_record,
        post=post,
        submitting_actor_did=str(actors["author"]),
        community=community,
        submitted_at=str(times["submittedAt"]),
        submission_evidence_receipt_id=str(receipts["submissionEvidence"]),
    )
    admit_authorization = ModeratorAuthorization(
        community=community,
        decision_id="decision-admit-1",
        moderator_did=str(actors["moderator"]),
        action=AuthorizedAction.ADMIT,
        target_occurrence_id=submission.submission_id,
        authorization_basis_receipt_id=str(receipts["authorizationBasis"]),
        authorized_at=str(times["admitAuthorizedAt"]),
        expires_at=str(times["admitExpiresAt"]),
        provenance_receipt_id=str(receipts["authorizationProvenance"]),
    )
    admission_record = _record(
        vector,
        space=space,
        name="admission",
        author=str(actors["community"]),
        collection=str(collections["admission"]),
    )
    admission = CommunityAdmission(
        record=admission_record,
        community=community,
        post=post,
        submission=submission,
        authorization=admit_authorization,
        source_observation_receipt_id=str(receipts["postQualification"]),
        admitted_at=str(times["admittedAt"]),
    )
    projection = ProjectionReference(
        admission=admission,
        render_state=RenderState.INCLUDED,
        current_source_relationship=SourceRelationship.EXACT,
        source_qualification_receipt_id=str(receipts["currentSourceQualification"]),
        last_qualification_check=str(times["checkedAt"]),
    )
    remove_authorization = ModeratorAuthorization(
        community=community,
        decision_id="decision-remove-1",
        moderator_did=str(actors["moderator"]),
        action=AuthorizedAction.REMOVE,
        target_occurrence_id=admission.admission_id,
        authorization_basis_receipt_id=str(receipts["removalBasis"]),
        authorized_at=str(times["removeAuthorizedAt"]),
        expires_at=str(times["removeExpiresAt"]),
        provenance_receipt_id=str(receipts["removalProvenance"]),
    )
    removal_record = _record(
        vector,
        space=space,
        name="removal",
        author=str(actors["community"]),
        collection=str(collections["removal"]),
    )
    removal = RemovalRecord(
        record=removal_record,
        admission=admission,
        authorization=remove_authorization,
        reason_category="community_policy",
        removed_at=str(times["removedAt"]),
    )
    withdrawal_record = ExactSpaceRecordReference(
        space=space,
        author_did=str(actors["author"]),
        collection="test.invalid.community.withdrawal",
        rkey="withdrawal-1",
        cid="bafyreihhponjv2pdbmg33nxvccrgj34546avahl3nojk5cplawofvn2d3m",
    )
    withdrawal = AuthorWithdrawal(
        record=withdrawal_record,
        admission=admission,
        submission=submission,
        withdrawal_evidence_receipt_id="sha256:" + "ab" * 32,
        withdrawn_at="2026-08-21T12:04:30Z",
    )

    return {
        "vector": vector,
        "space": space,
        "community": community,
        "post_record": post_record,
        "post": post,
        "submission_record": submission_record,
        "submission": submission,
        "admit_authorization": admit_authorization,
        "admission_record": admission_record,
        "admission": admission,
        "projection": projection,
        "remove_authorization": remove_authorization,
        "removal_record": removal_record,
        "removal": removal,
        "withdrawal_record": withdrawal_record,
        "withdrawal": withdrawal,
    }
