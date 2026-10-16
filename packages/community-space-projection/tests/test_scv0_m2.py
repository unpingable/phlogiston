from __future__ import annotations

import hashlib
from dataclasses import fields
from pathlib import Path

from community_space_model import RenderState, SourceRelationship
from community_space_projection import (
    REDUCER_VERSION,
    LifecycleState,
    ProjectionLifecycle,
    SourceObservation,
    SourceObservationOutcome,
    TransitionKind,
)


def test_m2_p1_submission_becomes_suggested(m2: dict[str, object]) -> None:
    state = m2["suggested"]
    assert isinstance(state, ProjectionLifecycle)
    assert state.state is LifecycleState.SUGGESTED
    assert state.transition is TransitionKind.SUBMISSION_QUALIFIED
    assert state.admission is None
    assert state.projection_reference is None
    assert state.removal is None
    assert state.source_observation.outcome is SourceObservationOutcome.PRESENT


def test_m2_p2_admission_becomes_added(m2: dict[str, object]) -> None:
    state = m2["added"]
    assert isinstance(state, ProjectionLifecycle)
    assert state.state is LifecycleState.ADDED
    assert state.transition is TransitionKind.ADMISSION_QUALIFIED
    assert state.admission is m2["admission"]
    assert state.projection_reference.render_state is RenderState.INCLUDED
    assert (
        state.projection_reference.current_source_relationship
        is SourceRelationship.EXACT
    )
    assert state.prior_state_id == m2["suggested"].state_id


def test_m2_p3_source_update_becomes_changed_at_source(
    m2: dict[str, object],
) -> None:
    state = m2["changed_state"]
    assert isinstance(state, ProjectionLifecycle)
    assert state.state is LifecycleState.CHANGED_AT_SOURCE
    assert state.projection_reference.render_state is RenderState.HIDDEN_CHANGED
    assert state.source_observation.observed_record.uri == m2["post"].record.uri
    assert state.source_observation.observed_record.cid != m2["post"].record.cid
    assert state.admission is m2["admission"]
    assert state.terminal_source_divergence is True


def test_m2_p4_source_absence_becomes_source_unavailable(
    m2: dict[str, object],
) -> None:
    state = m2["absent_state"]
    assert isinstance(state, ProjectionLifecycle)
    assert state.state is LifecycleState.SOURCE_UNAVAILABLE
    assert state.source_observation.outcome is SourceObservationOutcome.ABSENT
    assert state.projection_reference.render_state is RenderState.HIDDEN_DELETED
    assert (
        state.projection_reference.current_source_relationship
        is SourceRelationship.DELETED
    )
    assert state.removal is None


def test_m2_p5_community_removal_becomes_removed(m2: dict[str, object]) -> None:
    state = m2["removed"]
    assert isinstance(state, ProjectionLifecycle)
    assert state.state is LifecycleState.REMOVED
    assert state.transition is TransitionKind.COMMUNITY_REMOVED
    assert state.removal is m2["removal"]
    assert state.prior_state_id == m2["added"].state_id


def test_m2_p6_removal_preserves_admission_and_source_history(
    m2: dict[str, object],
) -> None:
    added = m2["added"]
    removed = m2["removed"]
    assert removed.admission is added.admission
    assert removed.submission.post == added.submission.post
    assert removed.source_observation == added.source_observation
    assert removed.projection_reference == added.projection_reference
    assert removed.removal.removal_id in removed.transition_input_ids
    assert added.state_id in removed.transition_input_ids


def test_author_withdrawal_is_distinct_and_preserves_editorial_history(
    m2: dict[str, object],
) -> None:
    state = m2["withdrawn"]
    assert isinstance(state, ProjectionLifecycle)
    assert state.state is LifecycleState.AUTHOR_WITHDRAWN
    assert state.transition is TransitionKind.AUTHOR_WITHDREW
    assert state.author_withdrawal is m2["withdrawal"]
    assert state.admission is m2["admission"]
    assert state.removal is None
    assert state.submission.post is m2["post"]


def test_community_removal_after_withdrawal_retains_both_occurrences(
    m2: dict[str, object],
) -> None:
    state = m2["removed_after_withdrawal"]
    assert state.state is LifecycleState.REMOVED
    assert state.author_withdrawal is m2["withdrawal"]
    assert state.removal is m2["removal"]
    assert state.admission is m2["admission"]


def test_state_identity_is_deterministic_and_contains_no_ranking_fields(
    m2: dict[str, object],
) -> None:
    state = m2["changed_state"]
    assert state.state_id == state.state_id
    assert state.reducer_version == REDUCER_VERSION
    assert state.source_observation.observation_id in state.transition_input_ids
    names = {field.name for field in fields(ProjectionLifecycle)}
    assert names.isdisjoint({"score", "votes", "popularity", "rank", "visible"})


def test_fixture_is_pinned_nonsecret_and_replays(m2: dict[str, object]) -> None:
    vector = m2["m2_vector"]
    assert isinstance(vector, dict)
    assert vector["reducerVersion"] == REDUCER_VERSION
    assert vector["secretMaterialPresent"] is False
    fixture = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "space-community"
        / "scv0-m2.json"
    )
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == (
        "fc1e95e7654959a0cc99e25e7428dfee8824ff0334af04714183d311e89aab2c"
    )


def test_temporary_unavailability_is_distinct_from_qualified_absence(
    m2: dict[str, object],
) -> None:
    state = m2["unavailable_state"]
    assert state.state is LifecycleState.SOURCE_UNAVAILABLE
    assert state.source_observation.outcome is SourceObservationOutcome.UNAVAILABLE
    assert state.projection_reference.render_state is RenderState.HIDDEN_UNAVAILABLE
    assert state.terminal_source_divergence is False


def test_temporary_unavailability_can_recover_without_rewriting_admission(
    m2: dict[str, object],
) -> None:
    vector = m2["m2_vector"]
    assert isinstance(vector, dict)
    observations = vector["observations"]
    assert isinstance(observations, dict)
    data = observations["reappeared"]
    assert isinstance(data, dict)
    recovered = SourceObservation(
        post=m2["post"],
        outcome=SourceObservationOutcome.PRESENT,
        observed_record=m2["post_record"],
        evidence_receipt_id=str(data["evidenceReceipt"]),
        currentness_receipt_id=str(data["currentnessReceipt"]),
        observed_at=str(data["observedAt"]),
        predecessor_observation_id=m2["unavailable"].observation_id,
    )
    state = m2["reducer"].observe(m2["unavailable_state"], recovered)
    assert state.state is LifecycleState.ADDED
    assert state.admission is m2["admission"]
    assert state.terminal_source_divergence is False
