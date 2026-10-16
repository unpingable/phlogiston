from __future__ import annotations

from community_model import canonical_json_bytes, sha256_digest
from community_space_projection import (
    LifecycleState,
    ProjectionReducer,
    SourceObservation,
    SourceObservationOutcome,
)
from community_space_wire import (
    NAMESPACE_STATUS,
    WIRE_PROFILE,
    adapt_admission_input,
    adapt_source_post,
    adapt_submission,
)


def test_source_post_translates_into_exact_m1_reference(m3: dict[str, object]) -> None:
    adapted = adapt_source_post(
        m3["source_payload"],
        expected_space=m3["space"],
        expected_author_did="did:web:author.invalid.test",
    )

    assert adapted.post == m3["adapted_post"].post
    assert adapted.receipt.domain_value_id == adapted.post.reference_id
    assert adapted.receipt.exact_wire_sha256 == sha256_digest(m3["source_payload"])
    assert adapted.receipt.profile == WIRE_PROFILE
    assert "community_admission_policy" in adapted.receipt.explicit_non_claims


def test_submission_translates_and_preserves_exact_occurrence(
    m3: dict[str, object],
) -> None:
    adapted = adapt_submission(
        m3["submission_payload"],
        post=m3["adapted_post"].post,
        expected_community=m3["community"],
    )

    assert adapted.submission == m3["adapted_submission"].submission
    assert adapted.receipt.domain_value_id == adapted.submission.submission_id
    assert adapted.submission.post == m3["adapted_post"].post
    assert adapted.submission.community == m3["community"]


def test_admission_placeholder_composes_only_with_existing_authorization(
    m3: dict[str, object],
) -> None:
    adapted = adapt_admission_input(
        m3["admission_payload"],
        community=m3["community"],
        post=m3["adapted_post"].post,
        submission=m3["adapted_submission"].submission,
        authorization=m3["authorization"],
    )

    assert adapted.admission == m3["adapted_admission"].admission
    assert adapted.admission.authorization == m3["authorization"]
    assert adapted.receipt.domain_value_id == adapted.admission.admission_id


def test_wire_adapter_composes_with_unchanged_m2_reducer(m3: dict[str, object]) -> None:
    post = m3["adapted_post"].post
    submission = m3["adapted_submission"].submission
    admission = m3["adapted_admission"].admission
    first = SourceObservation(
        post=post,
        outcome=SourceObservationOutcome.PRESENT,
        observed_record=post.record,
        evidence_receipt_id="sha256:" + "8" * 64,
        currentness_receipt_id="sha256:" + "9" * 64,
        observed_at="2026-08-21T12:00:30Z",
    )
    second = SourceObservation(
        post=post,
        outcome=SourceObservationOutcome.PRESENT,
        observed_record=post.record,
        evidence_receipt_id="sha256:" + "a" * 64,
        currentness_receipt_id="sha256:" + "b" * 64,
        observed_at="2026-08-21T12:02:30Z",
        predecessor_observation_id=first.observation_id,
    )
    reducer = ProjectionReducer(m3["community"])

    suggested = reducer.suggest(submission, first)
    added = reducer.admit(suggested, m3["authorization"], admission, second)

    assert suggested.state is LifecycleState.SUGGESTED
    assert added.state is LifecycleState.ADDED
    assert added.admission == admission


def test_fixture_declares_noncanonical_profile(m3: dict[str, object]) -> None:
    assert m3["vector"]["profile"] == WIRE_PROFILE
    assert m3["vector"]["namespaceStatus"] == NAMESPACE_STATUS
    assert m3["vector"]["secretMaterialPresent"] is False
    for name in ("source_value", "submission_value", "admission_value"):
        assert canonical_json_bytes(m3[name])


def test_translation_replays_deterministically(m3: dict[str, object]) -> None:
    first = adapt_source_post(
        m3["source_payload"],
        expected_space=m3["space"],
        expected_author_did="did:web:author.invalid.test",
    )
    second = adapt_source_post(
        m3["source_payload"],
        expected_space=m3["space"],
        expected_author_did="did:web:author.invalid.test",
    )

    assert first == second
    assert first.receipt.receipt_id == second.receipt.receipt_id
