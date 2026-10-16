from __future__ import annotations

from dataclasses import replace

import pytest

from community_model import ValidationError
from community_space_model import (
    CommunityAdmission,
    CommunityIdentity,
    ExactSpaceRecordReference,
    ProjectionReference,
    RenderState,
    SourceRelationship,
)
from community_space_projection import (
    LifecycleState,
    ProjectionReducer,
    SourceObservation,
    SourceObservationOutcome,
    refuse_projection_claim_upgrade,
)


def _reason(expected: str):
    return pytest.raises(ValidationError, match=rf"^{expected} at")


def _observation_data(m2: dict[str, object], name: str) -> dict[str, object]:
    vector = m2["m2_vector"]
    assert isinstance(vector, dict)
    observations = vector["observations"]
    assert isinstance(observations, dict)
    value = observations[name]
    assert isinstance(value, dict)
    return value


def test_m2_h1_added_without_admission_refuses(m2: dict[str, object]) -> None:
    with _reason("admission_required"):
        replace(m2["added"], admission=None)


def test_m2_h2_admission_without_submission_refuses(
    m2: dict[str, object],
) -> None:
    with _reason("submission_required"):
        replace(m2["added"], submission=None)


def test_m2_h3_source_change_is_not_implicit_readmission(
    m2: dict[str, object],
) -> None:
    state = m2["reducer"].observe(m2["added"], m2["changed"])
    assert state.state is LifecycleState.CHANGED_AT_SOURCE
    assert state.admission == m2["admission"]
    assert state.admission.admission_id == m2["added"].admission.admission_id
    assert state.transition.value == "source_observed"


def test_m2_h4_source_deletion_is_not_community_removal(
    m2: dict[str, object],
) -> None:
    state = m2["reducer"].observe(m2["added"], m2["absent"])
    assert state.state is LifecycleState.SOURCE_UNAVAILABLE
    assert state.removal is None
    assert state.admission == m2["admission"]


def test_m2_h5_community_removal_cannot_claim_source_mutation(
    m2: dict[str, object],
) -> None:
    with _reason("projection_claim_upgrade_refused"):
        refuse_projection_claim_upgrade({"sourceMutation": True})
    removed = m2["removed"]
    assert removed.submission.post == m2["added"].submission.post


def test_m2_h6_removed_item_does_not_reappear_automatically(
    m2: dict[str, object],
) -> None:
    data = _observation_data(m2, "reappeared")
    observation = SourceObservation(
        post=m2["post"],
        outcome=SourceObservationOutcome.PRESENT,
        observed_record=m2["post_record"],
        evidence_receipt_id=str(data["evidenceReceipt"]),
        currentness_receipt_id=str(data["currentnessReceipt"]),
        observed_at=str(data["observedAt"]),
        predecessor_observation_id=m2["removed"].source_observation.observation_id,
    )
    state = m2["reducer"].observe(m2["removed"], observation)
    assert state.state is LifecycleState.REMOVED
    assert state.removal == m2["removal"]
    assert state.admission == m2["admission"]


def test_m2_h7_cross_community_projection_refuses(
    m2: dict[str, object],
) -> None:
    other = CommunityIdentity(
        space=m2["space"], community_actor_did="did:web:other.invalid.test"
    )
    with _reason("projection_community_mismatch"):
        ProjectionReducer(other).suggest(m2["submission"], m2["initial"])


def test_m2_h8_newer_timestamp_cannot_launder_stale_observation(
    m2: dict[str, object],
) -> None:
    stale = SourceObservation(
        post=m2["post"],
        outcome=SourceObservationOutcome.PRESENT,
        observed_record=m2["post_record"],
        evidence_receipt_id="sha256:" + "4" * 64,
        currentness_receipt_id="sha256:" + "5" * 64,
        observed_at="2026-08-21T13:00:00Z",
        predecessor_observation_id=m2["initial"].observation_id,
    )
    with _reason("source_observation_stale"):
        m2["reducer"].observe(m2["added"], stale)


def test_m2_h9_duplicate_and_conflicting_admissions_refuse_explicitly(
    m2: dict[str, object],
) -> None:
    with _reason("duplicate_admission"):
        m2["reducer"].admit(
            m2["added"],
            m2["authorization"],
            m2["admission"],
            m2["after_admission"],
        )

    m1_vector = m2["m1_vector"]
    assert isinstance(m1_vector, dict)
    records = m1_vector["records"]
    collections = m1_vector["collections"]
    actors = m1_vector["actors"]
    assert all(isinstance(item, dict) for item in (records, collections, actors))
    alternate = records["conflictingAdmission"]
    assert isinstance(alternate, dict)
    conflicting_record = ExactSpaceRecordReference(
        space=m2["space"],
        author_did=str(actors["community"]),
        collection=str(collections["admission"]),
        rkey=str(alternate["rkey"]),
        cid=str(alternate["cid"]),
    )
    conflicting = replace(m2["admission"], record=conflicting_record)
    assert isinstance(conflicting, CommunityAdmission)
    with _reason("conflicting_admission"):
        m2["reducer"].admit(
            m2["added"],
            m2["authorization"],
            conflicting,
            m2["after_admission"],
        )


def test_m2_h10_out_of_order_lifecycle_refuses(m2: dict[str, object]) -> None:
    with _reason("invalid_lifecycle_transition"):
        m2["reducer"].remove(m2["suggested"], m2["removal"])
    with _reason("source_change_before_admission"):
        m2["reducer"].observe(m2["suggested"], m2["changed"])
    with _reason("submission_required"):
        replace(m2["suggested"], submission=None)

    out_of_order = SourceObservation(
        post=m2["post"],
        outcome=SourceObservationOutcome.PRESENT,
        observed_record=m2["post_record"],
        evidence_receipt_id="sha256:" + "6" * 64,
        currentness_receipt_id="sha256:" + "7" * 64,
        observed_at="2026-08-21T12:02:30Z",
        predecessor_observation_id=m2["after_admission"].observation_id,
    )
    with _reason("source_observation_order_invalid"):
        m2["reducer"].observe(m2["added"], out_of_order)


def test_m2_h11_ranking_injection_refuses() -> None:
    with _reason("projection_claim_upgrade_refused"):
        refuse_projection_claim_upgrade(
            {"score": 9001, "votes": 42, "orderingAuthority": True}
        )


def test_m2_h12_authority_relabeling_refuses() -> None:
    with _reason("projection_claim_upgrade_refused"):
        refuse_projection_claim_upgrade(
            {"projectionIsGovernanceDecision": True, "governanceAuthority": True}
        )


def test_author_withdrawal_cannot_be_replayed_or_relabel_source_absence(
    m2: dict[str, object],
) -> None:
    with _reason("duplicate_withdrawal"):
        m2["reducer"].withdraw(m2["withdrawn"], m2["withdrawal"])
    assert m2["withdrawn"].state is LifecycleState.AUTHOR_WITHDRAWN
    assert (
        m2["withdrawn"].source_observation.outcome is SourceObservationOutcome.PRESENT
    )
    assert m2["absent_state"].state is LifecycleState.SOURCE_UNAVAILABLE
    assert m2["absent_state"].author_withdrawal is None


def test_removed_item_cannot_be_relabelled_as_author_withdrawal(
    m2: dict[str, object],
) -> None:
    with _reason("invalid_lifecycle_transition"):
        m2["reducer"].withdraw(m2["removed"], m2["withdrawal"])


def test_withdrawal_cannot_relabel_the_retained_source_observation(
    m2: dict[str, object],
) -> None:
    relabelled = ProjectionReference(
        admission=m2["admission"],
        render_state=RenderState.HIDDEN_UNAVAILABLE,
        current_source_relationship=SourceRelationship.UNAVAILABLE,
        source_qualification_receipt_id=(
            m2["withdrawn"].source_observation.evidence_receipt_id
        ),
        last_qualification_check=m2["withdrawn"].source_observation.observed_at,
    )
    with _reason("withdrawal_source_state_invalid"):
        replace(m2["withdrawn"], projection_reference=relabelled)


def test_terminal_cid_change_cannot_revive_after_exact_cid_reappears(
    m2: dict[str, object],
) -> None:
    data = _observation_data(m2, "reappeared")
    reappeared = SourceObservation(
        post=m2["post"],
        outcome=SourceObservationOutcome.PRESENT,
        observed_record=m2["post_record"],
        evidence_receipt_id=str(data["evidenceReceipt"]),
        currentness_receipt_id=str(data["currentnessReceipt"]),
        observed_at=str(data["observedAt"]),
        predecessor_observation_id=m2["changed"].observation_id,
    )
    state = m2["reducer"].observe(m2["changed_state"], reappeared)
    assert state.state is LifecycleState.CHANGED_AT_SOURCE
    assert state.terminal_source_divergence is True


def test_source_path_substitution_refuses_before_reduction(
    m2: dict[str, object],
) -> None:
    other = ExactSpaceRecordReference(
        space=m2["space"],
        author_did=m2["post_record"].author_did,
        collection=m2["post_record"].collection,
        rkey="other-post",
        cid=m2["post_record"].cid,
    )
    with _reason("source_binding_mismatch"):
        SourceObservation(
            post=m2["post"],
            outcome=SourceObservationOutcome.PRESENT,
            observed_record=other,
            evidence_receipt_id="sha256:" + "8" * 64,
            currentness_receipt_id="sha256:" + "9" * 64,
            observed_at="2026-08-21T12:04:00Z",
            predecessor_observation_id=m2["after_admission"].observation_id,
        )


def test_direct_projection_state_cannot_omit_transition_evidence(
    m2: dict[str, object],
) -> None:
    with _reason("transition_inputs_invalid"):
        replace(m2["added"], transition_input_ids=())


def test_noninitial_state_requires_exact_prior_link(m2: dict[str, object]) -> None:
    with _reason("prior_state_required"):
        replace(m2["added"], prior_state_id=None)


def test_transition_inputs_cannot_be_relabelled(m2: dict[str, object]) -> None:
    with _reason("transition_inputs_invalid"):
        replace(
            m2["added"],
            transition_input_ids=(m2["added"].prior_state_id, "sha256:" + "a" * 64),
        )


def test_absence_cannot_be_relabelled_as_temporary_unavailability(
    m2: dict[str, object],
) -> None:
    relabelled = ProjectionReference(
        admission=m2["admission"],
        render_state=RenderState.HIDDEN_UNAVAILABLE,
        current_source_relationship=SourceRelationship.UNAVAILABLE,
        source_qualification_receipt_id=m2["absent"].evidence_receipt_id,
        last_qualification_check=m2["absent"].observed_at,
    )
    with _reason("source_unavailable_invalid"):
        replace(
            m2["absent_state"],
            projection_reference=relabelled,
        )
