from __future__ import annotations

from dataclasses import replace

import pytest

from community_model import (
    ValidationError,
    cid_for_dag_cbor,
    decode_dag_cbor,
    encode_dag_cbor,
)
from communitywatch_spaces_alpha import (
    REFERENCE_COMMIT,
    SA6_RECONCILER_VERSION,
    SA6_SOURCE_VECTOR_FORMAT,
    ReconciliationDisposition,
    ReconciliationResult,
    SpaceIdentity,
    SpaceRecordBlock,
    SpaceRepoEvidence,
    encode_commit_context,
    identify_qualified_repo_state,
    qualify_repo_state,
    reconcile_qualified_states,
)
from communitywatch_spaces_alpha.crypto import commit_mac, lthash_add, lthash_digest
from spaces_support import (
    qualified_sa4_snapshot,
    qualified_sa4_transition,
    sa4_algorithm,
    sa4_author,
    sa4_evidence,
    sa4_public_key,
    sa4_source_context,
    sa4_space,
    timestamp,
)


def _states(source_vectors: dict[str, object], vectors: dict[str, object]):
    n = qualified_sa4_snapshot(source_vectors, vectors, "n", "2026-08-20T15:00:02Z")
    n_to_n1 = qualified_sa4_transition(
        n,
        source_vectors,
        vectors,
        "n1",
        "n-to-n1",
        "2026-08-20T15:01:02Z",
    )
    n1_to_n2 = qualified_sa4_transition(
        n_to_n1.target,
        source_vectors,
        vectors,
        "n2",
        "n1-to-n2",
        "2026-08-20T15:02:02Z",
    )
    return n, n_to_n1, n1_to_n2


def test_sa6_fixture_names_only_supported_bounded_dispositions(sa6_vectors) -> None:
    compatibility = sa6_vectors["compatibility"]
    assert isinstance(compatibility, dict)
    assert sa6_vectors["format"] == SA6_SOURCE_VECTOR_FORMAT
    assert compatibility["referenceCommit"] == REFERENCE_COMMIT
    assert compatibility["reconcilerVersion"] == SA6_RECONCILER_VERSION
    cases = sa6_vectors["cases"]
    assert isinstance(cases, list)
    assert {str(case["expected"]) for case in cases if isinstance(case, dict)} == {
        disposition.value for disposition in ReconciliationDisposition
    }
    assert "history_verified" not in {item.value for item in ReconciliationDisposition}


def _same_revision_fork(source_vectors, vectors):
    evidence = sa4_evidence(source_vectors, vectors, "n")
    records = list(evidence.record_blocks)
    original = records[0]
    decoded_record = decode_dag_cbor(original.record_bytes)
    assert isinstance(decoded_record, dict)
    changed_record = {**decoded_record, "text": "same revision conflicting fork"}
    changed_bytes = encode_dag_cbor(changed_record)
    changed_cid = cid_for_dag_cbor(changed_bytes)
    records[0] = SpaceRecordBlock(
        collection=original.collection,
        rkey=original.rkey,
        cid=changed_cid,
        record_bytes=changed_bytes,
    )
    index = {
        f"{record.collection}/{record.rkey}": {"$link": record.cid}
        for record in records
    }
    index_bytes = encode_dag_cbor(index)
    state = bytes(2048)
    for path, link in index.items():
        state = lthash_add(state, f"{path}/{link['$link']}")
    commit = decode_dag_cbor(evidence.commit_bytes)
    assert isinstance(commit, dict)
    commit["hash"] = lthash_digest(state)
    context = encode_commit_context(
        sa4_space(source_vectors),
        sa4_author(source_vectors),
        str(commit["rev"]),
        commit["ikm"],
    )
    commit["mac"] = commit_mac(commit["ikm"], context, commit["hash"])
    fork_evidence = SpaceRepoEvidence(
        source_vector_identifier="sa6:same-revision-conflict",
        proof_kind=evidence.proof_kind,
        protocol_assumption=evidence.protocol_assumption,
        commit_bytes=encode_dag_cbor(commit),
        index_bytes=index_bytes,
        record_blocks=tuple(records),
    )
    return qualify_repo_state(
        fork_evidence,
        expected_space=sa4_space(source_vectors),
        expected_author_did=sa4_author(source_vectors),
        author_public_key=sa4_public_key(source_vectors),
        signature_algorithm=sa4_algorithm(source_vectors),
        source=sa4_source_context(source_vectors),
        verified_at=timestamp("2026-08-21T12:04:30Z"),
    )


def test_equal_state_is_semantic_equality_not_receipt_time_freshness(
    sa4_source_vectors, sa4_vectors
) -> None:
    first = qualified_sa4_snapshot(
        sa4_source_vectors, sa4_vectors, "n", "2026-08-20T15:00:02Z"
    )
    replay = qualified_sa4_snapshot(
        sa4_source_vectors, sa4_vectors, "n", "2026-08-21T12:00:00Z"
    )
    result = reconcile_qualified_states(
        first,
        replay,
        reconciled_at=timestamp("2026-08-21T12:00:01Z"),
    )
    assert result.disposition is ReconciliationDisposition.EQUAL_STATE
    assert result.known_state.qualification_receipt_ids != (
        result.observed_state.qualification_receipt_ids
    )
    assert result.currentness is False


def test_exact_sa4_receipt_yields_only_qualified_transition(
    sa4_source_vectors, sa4_vectors
) -> None:
    _, first, second = _states(sa4_source_vectors, sa4_vectors)
    result = reconcile_qualified_states(
        first.target,
        second.target,
        transition=second,
        reconciled_at=timestamp("2026-08-21T12:01:00Z"),
    )
    assert result.disposition is ReconciliationDisposition.QUALIFIED_TRANSITION
    assert result.transition_receipt == second.receipt
    provenance = result.to_provenance()
    assert provenance["completeHistory"] is False
    assert provenance["authorization"] is False


def test_missing_notification_recovers_as_snapshot_only_without_inventing_history(
    sa4_source_vectors, sa4_vectors
) -> None:
    n, _, second = _states(sa4_source_vectors, sa4_vectors)
    result = reconcile_qualified_states(
        n,
        second.target,
        reconciled_at=timestamp("2026-08-21T12:02:00Z"),
    )
    assert result.disposition is ReconciliationDisposition.SNAPSHOT_ONLY
    assert result.transition_receipt is None
    assert result.complete_history is False


def test_stale_and_replayed_old_state_are_insufficient_not_freshness_proof(
    sa4_source_vectors, sa4_vectors
) -> None:
    _, first, second = _states(sa4_source_vectors, sa4_vectors)
    result = reconcile_qualified_states(
        second.target,
        first.target,
        reconciled_at=timestamp("2026-08-21T12:03:00Z"),
    )
    assert result.disposition is ReconciliationDisposition.INSUFFICIENT_EVIDENCE
    assert result.reason == "observed_state_is_stale_or_replayed"
    assert result.currentness is False


def test_missing_intermediate_transition_does_not_link_known_to_observed(
    sa4_source_vectors, sa4_vectors
) -> None:
    n, _, second = _states(sa4_source_vectors, sa4_vectors)
    result = reconcile_qualified_states(
        n,
        second.target,
        transition=second,
        reconciled_at=timestamp("2026-08-21T12:04:00Z"),
    )
    assert result.disposition is ReconciliationDisposition.INSUFFICIENT_EVIDENCE
    assert result.reason == (
        "supplied_transition_does_not_link_known_and_observed_states"
    )
    assert result.considered_transition_receipt_id == second.receipt.receipt_id


def test_same_revision_conflicting_qualified_states_are_insufficient(
    sa4_source_vectors, sa4_vectors
) -> None:
    known = qualified_sa4_snapshot(
        sa4_source_vectors, sa4_vectors, "n", "2026-08-20T15:00:02Z"
    )
    fork = _same_revision_fork(sa4_source_vectors, sa4_vectors)
    assert known.commit.rev == fork.commit.rev
    assert known.commit.state_hash != fork.commit.state_hash
    result = reconcile_qualified_states(
        known,
        fork,
        reconciled_at=timestamp("2026-08-21T12:04:31Z"),
    )
    assert result.disposition is ReconciliationDisposition.INSUFFICIENT_EVIDENCE
    assert result.reason == "same_revision_has_conflicting_qualified_state"


def test_conflicting_transition_evidence_is_not_forced_into_snapshot_acceptance(
    sa4_source_vectors, sa4_vectors
) -> None:
    _, first, second = _states(sa4_source_vectors, sa4_vectors)
    result = reconcile_qualified_states(
        first.source,
        second.target,
        transition=first,
        reconciled_at=timestamp("2026-08-21T12:05:00Z"),
    )
    assert result.disposition is ReconciliationDisposition.INSUFFICIENT_EVIDENCE
    assert result.transition_receipt is None


def test_equivalent_state_identifiers_from_another_space_cannot_be_equal(
    sa4_source_vectors, sa4_vectors
) -> None:
    n = qualified_sa4_snapshot(
        sa4_source_vectors, sa4_vectors, "n", "2026-08-20T15:00:02Z"
    )
    identity = identify_qualified_repo_state(n)
    other = replace(
        identity,
        space=SpaceIdentity(
            authority_did="did:web:other-spaces.test.invalid",
            space_type=identity.space.space_type,
            skey=identity.space.skey,
        ),
    )
    insufficient = ReconciliationResult(
        known_state=identity,
        observed_state=other,
        disposition=ReconciliationDisposition.INSUFFICIENT_EVIDENCE,
        reason="space_or_author_identity_differs",
        reconciled_at=timestamp("2026-08-21T12:06:00Z"),
    )
    assert insufficient.disposition is ReconciliationDisposition.INSUFFICIENT_EVIDENCE
    with pytest.raises(ValidationError) as caught:
        replace(insufficient, disposition=ReconciliationDisposition.EQUAL_STATE)
    assert caught.value.reason_code == "spaces_reconciliation_invalid"


@pytest.mark.parametrize(
    "claim",
    [
        "complete_history",
        "currentness",
        "authority",
        "authorization",
        "governance_authority",
    ],
)
def test_reconciliation_result_cannot_be_relabelled_as_authority(
    sa4_source_vectors, sa4_vectors, claim
) -> None:
    n = qualified_sa4_snapshot(
        sa4_source_vectors, sa4_vectors, "n", "2026-08-20T15:00:02Z"
    )
    result = reconcile_qualified_states(
        n,
        n,
        reconciled_at=timestamp("2026-08-21T12:07:00Z"),
    )
    with pytest.raises(ValidationError) as caught:
        replace(result, **{claim: True})
    assert caught.value.reason_code == "spaces_reconciliation_invalid"
