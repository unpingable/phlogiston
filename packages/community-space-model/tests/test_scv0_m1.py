from __future__ import annotations

import hashlib
from dataclasses import fields
from pathlib import Path

from community_space_model import (
    COMPATIBILITY_PROFILE,
    AuthorizedAction,
    AuthorWithdrawal,
    CommunityAdmission,
    PostReference,
    ProjectionReference,
    RemovalRecord,
    RenderState,
    SourceRelationship,
    Submission,
)


def test_exact_author_withdrawal_preserves_admission_history(
    m1: dict[str, object],
) -> None:
    withdrawal = m1["withdrawal"]
    assert isinstance(withdrawal, AuthorWithdrawal)
    assert withdrawal.admission is m1["admission"]
    assert withdrawal.submission is m1["submission"]
    assert withdrawal.record.author_did == m1["post"].record.author_did
    assert withdrawal.withdrawal_id == withdrawal.withdrawal_id


def test_m1_p1_valid_source_post_reference(m1: dict[str, object]) -> None:
    post = m1["post"]
    assert isinstance(post, PostReference)
    assert post.record.uri == (
        "at://did:web:space-authority.invalid.test/space/"
        "test.invalid.community/community-lab/"
        "did:web:author.invalid.test/test.invalid.community.post/post-1"
    )
    assert post.record.space.authority_did != post.record.author_did
    assert post.reference_id.startswith("sha256:")
    assert not hasattr(post, "community")
    assert not hasattr(post, "admitted")


def test_m1_p2_valid_submission(m1: dict[str, object]) -> None:
    submission = m1["submission"]
    assert isinstance(submission, Submission)
    assert submission.post is m1["post"]
    assert submission.record.author_did == submission.submitting_actor_did
    assert submission.submission_id.startswith("sha256:")
    assert not hasattr(submission, "accepted")
    assert not hasattr(submission, "standing")


def test_m1_p3_valid_community_admission(m1: dict[str, object]) -> None:
    admission = m1["admission"]
    assert isinstance(admission, CommunityAdmission)
    assert admission.authorization.action is AuthorizedAction.ADMIT
    assert (
        admission.authorization.target_occurrence_id
        == admission.submission.submission_id
    )
    assert admission.record.author_did == admission.community.community_actor_did
    assert admission.admission_id.startswith("sha256:")


def test_m1_p4_valid_projection_reference(m1: dict[str, object]) -> None:
    projection = m1["projection"]
    assert isinstance(projection, ProjectionReference)
    assert projection.render_state is RenderState.INCLUDED
    assert projection.current_source_relationship is SourceRelationship.EXACT
    assert projection.projection_id.startswith("sha256:")
    assert {field.name for field in fields(ProjectionReference)} == {
        "admission",
        "render_state",
        "current_source_relationship",
        "source_qualification_receipt_id",
        "last_qualification_check",
    }


def test_m1_p5_valid_removal_record(m1: dict[str, object]) -> None:
    removal = m1["removal"]
    assert isinstance(removal, RemovalRecord)
    assert removal.authorization.action is AuthorizedAction.REMOVE
    assert removal.authorization.target_occurrence_id == removal.admission.admission_id
    assert removal.removal_id.startswith("sha256:")
    assert not hasattr(removal, "delete_source")


def test_fixture_profile_is_noncanonical_and_secret_free(
    m1: dict[str, object],
) -> None:
    vector = m1["vector"]
    assert isinstance(vector, dict)
    assert vector["profile"] == COMPATIBILITY_PROFILE
    assert vector["namespaceStatus"] == "synthetic-noncanonical-invalid.test"
    assert vector["secretMaterialPresent"] is False

    fixture = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "space-community"
        / "scv0-m1.json"
    )
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == (
        "1de3f4389661752dcad50d58c2dddd9b6fbb80bdd96473a9498de18868357457"
    )


def test_identifiers_replay_deterministically(m1: dict[str, object]) -> None:
    assert m1["post"].reference_id == m1["post"].reference_id
    assert m1["submission"].submission_id == m1["submission"].submission_id
    assert m1["admission"].admission_id == m1["admission"].admission_id
    assert m1["projection"].projection_id == m1["projection"].projection_id
    assert m1["removal"].removal_id == m1["removal"].removal_id
