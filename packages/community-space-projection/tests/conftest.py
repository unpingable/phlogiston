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
    RemovalRecord,
    SpaceIdentity,
    Submission,
)
from community_space_projection import (
    ProjectionReducer,
    SourceObservation,
    SourceObservationOutcome,
)

ROOT = Path(__file__).resolve().parents[3]
M1_VECTOR = ROOT / "tests" / "fixtures" / "space-community" / "scv0-m1.json"
M2_VECTOR = ROOT / "tests" / "fixtures" / "space-community" / "scv0-m2.json"


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


def _observation_data(vector: dict[str, object], name: str) -> dict[str, object]:
    observations = vector["observations"]
    assert isinstance(observations, dict)
    value = observations[name]
    assert isinstance(value, dict)
    return value


@pytest.fixture
def m2() -> dict[str, object]:
    m1_vector = json.loads(M1_VECTOR.read_text(encoding="utf-8"))
    m2_vector = json.loads(M2_VECTOR.read_text(encoding="utf-8"))
    raw_space = m1_vector["space"]
    actors = m1_vector["actors"]
    collections = m1_vector["collections"]
    receipts = m1_vector["receipts"]
    times = m1_vector["times"]
    source = m2_vector["source"]
    assert all(
        isinstance(value, dict)
        for value in (raw_space, actors, collections, receipts, times, source)
    )

    space = SpaceIdentity(
        authority_did=str(raw_space["authorityDid"]),
        space_type=str(raw_space["spaceType"]),
        skey=str(raw_space["skey"]),
    )
    community = CommunityIdentity(
        space=space, community_actor_did=str(actors["community"])
    )
    post_record = _record(
        m1_vector,
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
        m1_vector,
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
    authorization = ModeratorAuthorization(
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
        m1_vector,
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
        authorization=authorization,
        source_observation_receipt_id=str(receipts["postQualification"]),
        admitted_at=str(times["admittedAt"]),
    )
    removal_authorization = ModeratorAuthorization(
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
        m1_vector,
        space=space,
        name="removal",
        author=str(actors["community"]),
        collection=str(collections["removal"]),
    )
    removal = RemovalRecord(
        record=removal_record,
        admission=admission,
        authorization=removal_authorization,
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

    initial_data = _observation_data(m2_vector, "initial")
    initial = SourceObservation(
        post=post,
        outcome=SourceObservationOutcome.PRESENT,
        observed_record=post_record,
        evidence_receipt_id=str(initial_data["evidenceReceipt"]),
        currentness_receipt_id=str(initial_data["currentnessReceipt"]),
        observed_at=str(initial_data["observedAt"]),
    )
    after_admission_data = _observation_data(m2_vector, "afterAdmission")
    after_admission = SourceObservation(
        post=post,
        outcome=SourceObservationOutcome.PRESENT,
        observed_record=post_record,
        evidence_receipt_id=str(after_admission_data["evidenceReceipt"]),
        currentness_receipt_id=str(after_admission_data["currentnessReceipt"]),
        observed_at=str(after_admission_data["observedAt"]),
        predecessor_observation_id=initial.observation_id,
    )
    changed_data = _observation_data(m2_vector, "changed")
    changed_record = ExactSpaceRecordReference(
        space=space,
        author_did=post_record.author_did,
        collection=post_record.collection,
        rkey=post_record.rkey,
        cid=str(source["changedCid"]),
    )
    changed = SourceObservation(
        post=post,
        outcome=SourceObservationOutcome.PRESENT,
        observed_record=changed_record,
        evidence_receipt_id=str(changed_data["evidenceReceipt"]),
        currentness_receipt_id=str(changed_data["currentnessReceipt"]),
        observed_at=str(changed_data["observedAt"]),
        predecessor_observation_id=after_admission.observation_id,
    )
    absent_data = _observation_data(m2_vector, "absent")
    absent = SourceObservation(
        post=post,
        outcome=SourceObservationOutcome.ABSENT,
        observed_record=None,
        evidence_receipt_id=str(absent_data["evidenceReceipt"]),
        currentness_receipt_id=str(absent_data["currentnessReceipt"]),
        observed_at=str(absent_data["observedAt"]),
        predecessor_observation_id=after_admission.observation_id,
    )
    unavailable_data = _observation_data(m2_vector, "unavailable")
    unavailable = SourceObservation(
        post=post,
        outcome=SourceObservationOutcome.UNAVAILABLE,
        observed_record=None,
        evidence_receipt_id=str(unavailable_data["evidenceReceipt"]),
        currentness_receipt_id=str(unavailable_data["currentnessReceipt"]),
        observed_at=str(unavailable_data["observedAt"]),
        predecessor_observation_id=after_admission.observation_id,
    )

    reducer = ProjectionReducer(community)
    suggested = reducer.suggest(submission, initial)
    added = reducer.admit(suggested, authorization, admission, after_admission)
    changed_state = reducer.observe(added, changed)
    absent_state = reducer.observe(added, absent)
    unavailable_state = reducer.observe(added, unavailable)
    removed = reducer.remove(added, removal)
    withdrawn = reducer.withdraw(added, withdrawal)
    removed_after_withdrawal = reducer.remove(withdrawn, removal)

    return {
        "m1_vector": m1_vector,
        "m2_vector": m2_vector,
        "space": space,
        "community": community,
        "post_record": post_record,
        "post": post,
        "submission": submission,
        "authorization": authorization,
        "admission": admission,
        "removal": removal,
        "withdrawal": withdrawal,
        "initial": initial,
        "after_admission": after_admission,
        "changed": changed,
        "absent": absent,
        "unavailable": unavailable,
        "reducer": reducer,
        "suggested": suggested,
        "added": added,
        "changed_state": changed_state,
        "absent_state": absent_state,
        "unavailable_state": unavailable_state,
        "removed": removed,
        "withdrawn": withdrawn,
        "removed_after_withdrawal": removed_after_withdrawal,
    }
