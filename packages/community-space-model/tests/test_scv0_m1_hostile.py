from __future__ import annotations

from dataclasses import replace

import pytest

from community_model import ValidationError
from community_space_model import (
    AdmissionDisposition,
    AuthorWithdrawal,
    CommunityAdmission,
    CommunityIdentity,
    ExactSpaceRecordReference,
    PostReference,
    ProjectionReference,
    RemovalRecord,
    RenderState,
    SourceRelationship,
    SpaceIdentity,
    Submission,
    classify_admission_candidate,
    refuse_claim_upgrade,
)


def test_withdrawal_by_non_author_refuses(m1: dict[str, object]) -> None:
    foreign = replace(
        m1["withdrawal_record"],
        author_did="did:web:other.invalid.test",
    )
    with _reason("author_binding_mismatch"):
        replace(m1["withdrawal"], record=foreign)


def test_withdrawal_cannot_target_another_submission(
    m1: dict[str, object],
) -> None:
    alternate_record = replace(m1["submission_record"], rkey="submission-other")
    alternate = replace(m1["submission"], record=alternate_record)
    assert isinstance(alternate, type(m1["submission"]))
    with _reason("withdrawal_occurrence_mismatch"):
        AuthorWithdrawal(
            record=m1["withdrawal_record"],
            admission=m1["admission"],
            submission=alternate,
            withdrawal_evidence_receipt_id=(
                m1["withdrawal"].withdrawal_evidence_receipt_id
            ),
            withdrawn_at=m1["withdrawal"].withdrawn_at,
        )


def _reason(expected: str):
    return pytest.raises(ValidationError, match=rf"^{expected} at")


def test_m1_h1_admission_without_observation_refuses(
    m1: dict[str, object],
) -> None:
    with _reason("source_observation_required"):
        CommunityAdmission(
            record=m1["admission_record"],
            community=m1["community"],
            post=m1["post_record"],
            submission=m1["submission"],
            authorization=m1["admit_authorization"],
            source_observation_receipt_id=("sha256:" + "1" * 64),
            admitted_at="2026-08-21T12:02:00Z",
        )


def test_m1_h2_admission_without_authorization_refuses(
    m1: dict[str, object],
) -> None:
    with _reason("authorization_required"):
        CommunityAdmission(
            record=m1["admission_record"],
            community=m1["community"],
            post=m1["post"],
            submission=m1["submission"],
            authorization=None,
            source_observation_receipt_id=("sha256:" + "1" * 64),
            admitted_at="2026-08-21T12:02:00Z",
        )


def test_m1_h3_authorization_replay_for_second_submission_refuses(
    m1: dict[str, object],
) -> None:
    vector = m1["vector"]
    assert isinstance(vector, dict)
    records = vector["records"]
    collections = vector["collections"]
    actors = vector["actors"]
    receipts = vector["receipts"]
    assert all(
        isinstance(item, dict) for item in (records, collections, actors, receipts)
    )
    alternate = records["alternateSubmission"]
    assert isinstance(alternate, dict)
    alternate_record = ExactSpaceRecordReference(
        space=m1["space"],
        author_did=str(actors["author"]),
        collection=str(collections["submission"]),
        rkey=str(alternate["rkey"]),
        cid=str(alternate["cid"]),
    )
    second_submission = Submission(
        record=alternate_record,
        post=m1["post"],
        submitting_actor_did=str(actors["author"]),
        community=m1["community"],
        submitted_at="2026-08-21T12:00:30Z",
        submission_evidence_receipt_id=str(receipts["submissionEvidence"]),
    )
    with _reason("authorization_occurrence_mismatch"):
        CommunityAdmission(
            record=m1["admission_record"],
            community=m1["community"],
            post=m1["post"],
            submission=second_submission,
            authorization=m1["admit_authorization"],
            source_observation_receipt_id=str(receipts["postQualification"]),
            admitted_at="2026-08-21T12:02:00Z",
        )


def test_m1_h4_cross_community_admission_refuses(
    m1: dict[str, object],
) -> None:
    other = CommunityIdentity(
        space=m1["space"], community_actor_did="did:web:other.invalid.test"
    )
    record = replace(m1["admission_record"], author_did=other.community_actor_did)
    with _reason("community_binding_mismatch"):
        CommunityAdmission(
            record=record,
            community=other,
            post=m1["post"],
            submission=m1["submission"],
            authorization=m1["admit_authorization"],
            source_observation_receipt_id=("sha256:" + "1" * 64),
            admitted_at="2026-08-21T12:02:00Z",
        )


def test_m1_h5_source_mutation_claim_refuses() -> None:
    with _reason("claim_upgrade_refused"):
        refuse_claim_upgrade({"sourceMutation": True})


def test_m1_h6_projection_without_admission_refuses() -> None:
    with _reason("admission_required"):
        ProjectionReference(
            admission=None,
            render_state=RenderState.INCLUDED,
            current_source_relationship=SourceRelationship.EXACT,
            source_qualification_receipt_id="sha256:" + "5" * 64,
            last_qualification_check="2026-08-21T12:03:00Z",
        )


def test_m1_h7_removal_without_prior_admission_refuses(
    m1: dict[str, object],
) -> None:
    with _reason("prior_admission_required"):
        RemovalRecord(
            record=m1["removal_record"],
            admission=None,
            authorization=m1["remove_authorization"],
            reason_category="community_policy",
            removed_at="2026-08-21T12:05:00Z",
        )


def test_m1_h8_duplicate_and_conflicting_admission_are_explicit(
    m1: dict[str, object],
) -> None:
    admission = m1["admission"]
    assert (
        classify_admission_candidate((admission,), admission)
        is AdmissionDisposition.DUPLICATE
    )

    vector = m1["vector"]
    assert isinstance(vector, dict)
    records = vector["records"]
    collections = vector["collections"]
    actors = vector["actors"]
    receipts = vector["receipts"]
    assert all(
        isinstance(item, dict) for item in (records, collections, actors, receipts)
    )
    alternate = records["conflictingAdmission"]
    assert isinstance(alternate, dict)
    conflicting_record = ExactSpaceRecordReference(
        space=m1["space"],
        author_did=str(actors["community"]),
        collection=str(collections["admission"]),
        rkey=str(alternate["rkey"]),
        cid=str(alternate["cid"]),
    )
    conflicting = CommunityAdmission(
        record=conflicting_record,
        community=m1["community"],
        post=m1["post"],
        submission=m1["submission"],
        authorization=m1["admit_authorization"],
        source_observation_receipt_id=str(receipts["postQualification"]),
        admitted_at="2026-08-21T12:02:00Z",
    )
    assert (
        classify_admission_candidate((admission,), conflicting)
        is AdmissionDisposition.CONFLICT
    )


def test_m1_h9_stale_authorization_refuses(m1: dict[str, object]) -> None:
    authorization = replace(
        m1["admit_authorization"], expires_at="2026-08-21T12:01:30Z"
    )
    with _reason("authorization_stale"):
        CommunityAdmission(
            record=m1["admission_record"],
            community=m1["community"],
            post=m1["post"],
            submission=m1["submission"],
            authorization=authorization,
            source_observation_receipt_id="sha256:" + "1" * 64,
            admitted_at="2026-08-21T12:02:00Z",
        )


def test_m1_h10_authority_relabeling_refuses() -> None:
    with _reason("claim_upgrade_refused"):
        refuse_claim_upgrade({"communityStanding": True, "governanceAuthority": True})


def test_wrong_space_cannot_be_self_submitted(m1: dict[str, object]) -> None:
    other_space = SpaceIdentity(
        authority_did="did:web:other-space.invalid.test",
        space_type="test.invalid.community",
        skey="community-lab",
    )
    post = PostReference(
        record=replace(m1["post_record"], space=other_space),
        source_qualification_receipt_id="sha256:" + "1" * 64,
    )
    with _reason("space_binding_mismatch"):
        replace(m1["submission"], post=post)


def test_wrong_author_cannot_self_submit(m1: dict[str, object]) -> None:
    with _reason("author_binding_mismatch"):
        replace(m1["submission"], submitting_actor_did="did:web:other.invalid.test")


def test_invalid_cid_never_forms_exact_reference(m1: dict[str, object]) -> None:
    with _reason("cid_invalid"):
        replace(m1["post_record"], cid="bafynot-a-cid")


def test_evidence_receipt_is_not_a_community_admission(
    m1: dict[str, object],
) -> None:
    evidence_receipt = "sha256:" + "8" * 64
    with _reason("source_observation_required"):
        CommunityAdmission(
            record=m1["admission_record"],
            community=m1["community"],
            post=evidence_receipt,
            submission=m1["submission"],
            authorization=m1["admit_authorization"],
            source_observation_receipt_id=evidence_receipt,
            admitted_at="2026-08-21T12:02:00Z",
        )


def test_space_access_label_cannot_mint_standing() -> None:
    with _reason("claim_upgrade_refused"):
        refuse_claim_upgrade({"spaceAccess": True, "communityStanding": True})


def test_projection_state_cannot_claim_visible_changed_source(
    m1: dict[str, object],
) -> None:
    with _reason("projection_state_invalid"):
        replace(
            m1["projection"],
            current_source_relationship=SourceRelationship.CHANGED,
        )


def test_record_chronology_cannot_be_reversed(m1: dict[str, object]) -> None:
    authorization = replace(
        m1["admit_authorization"],
        authorized_at="2026-08-21T11:58:00Z",
        expires_at="2026-08-21T12:06:00Z",
    )
    with _reason("admission_chronology_invalid"):
        replace(
            m1["admission"],
            authorization=authorization,
            admitted_at="2026-08-21T11:59:00Z",
        )
    with _reason("projection_chronology_invalid"):
        replace(m1["projection"], last_qualification_check="2026-08-21T11:59:00Z")

    removal_authorization = replace(
        m1["remove_authorization"],
        authorized_at="2026-08-21T11:58:00Z",
        expires_at="2026-08-21T12:09:00Z",
    )
    with _reason("removal_chronology_invalid"):
        replace(
            m1["removal"],
            authorization=removal_authorization,
            removed_at="2026-08-21T11:59:00Z",
        )
