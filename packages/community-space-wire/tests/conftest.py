from __future__ import annotations

import json
from pathlib import Path

import pytest

from community_model import canonical_json_bytes
from community_space_model import (
    AuthorizedAction,
    CommunityIdentity,
    ModeratorAuthorization,
    SpaceIdentity,
)
from community_space_wire import (
    adapt_admission_input,
    adapt_source_post,
    adapt_submission,
)

ROOT = Path(__file__).resolve().parents[3]
VECTOR = ROOT / "tests" / "fixtures" / "space-community" / "scv0-m3.json"


@pytest.fixture
def m3() -> dict[str, object]:
    vector = json.loads(VECTOR.read_text(encoding="utf-8"))
    source_value = vector["sourcePost"]
    submission_value = vector["submission"]
    admission_value = vector["admissionInput"]
    assert all(
        isinstance(value, dict)
        for value in (source_value, submission_value, admission_value)
    )

    source_payload = canonical_json_bytes(source_value)
    submission_payload = canonical_json_bytes(submission_value)
    admission_payload = canonical_json_bytes(admission_value)

    space = SpaceIdentity(
        authority_did="did:web:space-authority.invalid.test",
        space_type="test.invalid.community",
        skey="community-lab",
    )
    community = CommunityIdentity(
        space=space,
        community_actor_did="did:web:community.invalid.test",
    )
    adapted_post = adapt_source_post(
        source_payload,
        expected_space=space,
        expected_author_did="did:web:author.invalid.test",
    )
    adapted_submission = adapt_submission(
        submission_payload,
        post=adapted_post.post,
        expected_community=community,
    )
    authorization = ModeratorAuthorization(
        community=community,
        decision_id="decision-admit-1",
        moderator_did="did:web:moderator.invalid.test",
        action=AuthorizedAction.ADMIT,
        target_occurrence_id=adapted_submission.submission.submission_id,
        authorization_basis_receipt_id="sha256:" + "3" * 64,
        authorized_at="2026-08-21T12:01:00Z",
        expires_at="2026-08-21T12:06:00Z",
        provenance_receipt_id="sha256:" + "4" * 64,
    )
    adapted_admission = adapt_admission_input(
        admission_payload,
        community=community,
        post=adapted_post.post,
        submission=adapted_submission.submission,
        authorization=authorization,
    )
    return {
        "vector": vector,
        "source_value": source_value,
        "submission_value": submission_value,
        "admission_value": admission_value,
        "source_payload": source_payload,
        "submission_payload": submission_payload,
        "admission_payload": admission_payload,
        "space": space,
        "community": community,
        "adapted_post": adapted_post,
        "adapted_submission": adapted_submission,
        "authorization": authorization,
        "adapted_admission": adapted_admission,
    }
