from __future__ import annotations

import json
from pathlib import Path

import pytest

from community_space_artifact import (
    BoundedSourcePresentation,
    DisclosureMode,
    DisclosurePolicy,
)
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
M5A_VECTOR = ROOT / "tests" / "fixtures" / "space-community" / "scv0-m5a.json"


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
def m5a() -> dict[str, object]:
    m1 = json.loads(M1_VECTOR.read_text(encoding="utf-8"))
    m2 = json.loads(M2_VECTOR.read_text(encoding="utf-8"))
    vector = json.loads(M5A_VECTOR.read_text(encoding="utf-8"))
    raw_space = m1["space"]
    actors = m1["actors"]
    collections = m1["collections"]
    receipts = m1["receipts"]
    times = m1["times"]
    source = m2["source"]
    presentation_data = vector["presentation"]
    assert all(
        isinstance(item, dict)
        for item in (
            raw_space,
            actors,
            collections,
            receipts,
            times,
            source,
            presentation_data,
        )
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
        m1,
        space=space,
        name="post",
        author=str(actors["author"]),
        collection=str(collections["post"]),
    )
    post = PostReference(
        record=post_record,
        source_qualification_receipt_id=str(receipts["postQualification"]),
    )
    submission = Submission(
        record=_record(
            m1,
            space=space,
            name="submission",
            author=str(actors["author"]),
            collection=str(collections["submission"]),
        ),
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
    admission = CommunityAdmission(
        record=_record(
            m1,
            space=space,
            name="admission",
            author=str(actors["community"]),
            collection=str(collections["admission"]),
        ),
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
    removal = RemovalRecord(
        record=_record(
            m1,
            space=space,
            name="removal",
            author=str(actors["community"]),
            collection=str(collections["removal"]),
        ),
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

    initial_data = _observation_data(m2, "initial")
    initial = SourceObservation(
        post=post,
        outcome=SourceObservationOutcome.PRESENT,
        observed_record=post_record,
        evidence_receipt_id=str(initial_data["evidenceReceipt"]),
        currentness_receipt_id=str(initial_data["currentnessReceipt"]),
        observed_at=str(initial_data["observedAt"]),
    )
    after_data = _observation_data(m2, "afterAdmission")
    after_admission = SourceObservation(
        post=post,
        outcome=SourceObservationOutcome.PRESENT,
        observed_record=post_record,
        evidence_receipt_id=str(after_data["evidenceReceipt"]),
        currentness_receipt_id=str(after_data["currentnessReceipt"]),
        observed_at=str(after_data["observedAt"]),
        predecessor_observation_id=initial.observation_id,
    )
    changed_data = _observation_data(m2, "changed")
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
    unavailable_data = _observation_data(m2, "unavailable")
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
    unavailable_state = reducer.observe(added, unavailable)
    removed = reducer.remove(added, removal)
    withdrawn = reducer.withdraw(added, withdrawal)
    removed_after_withdrawal = reducer.remove(withdrawn, removal)
    presentation = BoundedSourcePresentation(
        source_reference_id=str(presentation_data["sourceReferenceId"]),
        source_uri=str(presentation_data["sourceUri"]),
        source_cid=str(presentation_data["sourceCid"]),
        title=str(presentation_data["title"]),
        body=str(presentation_data["body"]),
        author_display_reference=str(presentation_data["authorDisplayReference"]),
        profile=str(presentation_data["profile"]),
    )
    ordinary = DisclosurePolicy(
        mode=DisclosureMode.ORDINARY,
        policy_reference_id=str(vector["ordinaryPolicyReference"]),
        publication_reference_id=str(vector["ordinaryPublicationReference"]),
    )
    audit = DisclosurePolicy(
        mode=DisclosureMode.TECHNICAL_AUDIT,
        policy_reference_id=str(vector["auditPolicyReference"]),
        publication_reference_id=str(vector["auditPublicationReference"]),
    )
    return {
        "vector": vector,
        "community": community,
        "post": post,
        "suggested": suggested,
        "added": added,
        "changed": changed_state,
        "unavailable": unavailable_state,
        "removed": removed,
        "withdrawn": withdrawn,
        "removed_after_withdrawal": removed_after_withdrawal,
        "withdrawal": withdrawal,
        "presentation": presentation,
        "ordinary": ordinary,
        "audit": audit,
    }
