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
    OperationUnavailableReason,
    RecoveryOutcome,
    SpaceIdentity,
    SpaceRecordBlock,
    SpaceRepoEvidence,
    encode_commit_context,
)
from communitywatch_spaces_alpha.crypto import commit_mac, lthash_add, lthash_digest
from spaces_support import (
    sa4_author,
    sa4_evidence,
    sa4_space,
    sa5_pages,
    space_car_from_evidence,
)
from test_sa8_recovery import (
    _acquire,
    _artifact,
    _decision,
    _states,
)


def _partial_n_acquisition(n, source_vectors, sa5_vectors):
    page = sa5_pages(sa5_vectors, "o1CompleteBatch")[0]
    partial = replace(
        page,
        response_cursor="3mtaaaabbbbbg/0",
        terminal_commit_sha256=None,
    )
    return _acquire(n, source_vectors, (partial,))


def _same_revision_fork_car(source_vectors, vectors) -> bytes:
    evidence = sa4_evidence(source_vectors, vectors, "n")
    records = list(evidence.record_blocks)
    original = records[0]
    decoded = decode_dag_cbor(original.record_bytes)
    assert isinstance(decoded, dict)
    mutated_bytes = encode_dag_cbor(
        {**decoded, "text": "same revision independent qualified fork"}
    )
    records[0] = SpaceRecordBlock(
        collection=original.collection,
        rkey=original.rkey,
        cid=cid_for_dag_cbor(mutated_bytes),
        record_bytes=mutated_bytes,
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
    fork = SpaceRepoEvidence(
        source_vector_identifier="sa8:same-revision-conflict",
        proof_kind=evidence.proof_kind,
        protocol_assumption=evidence.protocol_assumption,
        commit_bytes=encode_dag_cbor(commit),
        index_bytes=index_bytes,
        record_blocks=tuple(records),
    )
    return space_car_from_evidence(fork)


def test_rcv_h1_older_snapshot_is_insufficient_despite_later_acquisition_time(
    sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    _, n1, n2 = _states(sa4_source_vectors, sa4_vectors)
    acquisition = _acquire(
        n2, sa4_source_vectors, sa5_pages(sa5_vectors, "o3EmptyTerminal")
    )
    trace = _decision(
        n2,
        sa4_source_vectors,
        _artifact(
            sa4_source_vectors,
            sa4_vectors,
            "n1",
            observed_at="2099-01-01T00:00:00Z",
        ),
        acquisition=acquisition,
        qualified_at="2099-01-01T00:00:01Z",
        decided_at="2099-01-01T00:00:02Z",
    )

    assert trace.outcome is RecoveryOutcome.INSUFFICIENT_EVIDENCE
    assert trace.reconciliation_reason == "observed_state_is_stale_or_replayed"
    assert trace.currentness is False
    assert trace.observed_state.repo_commit_hash == n1.commit.state_hash.hex()


def test_rcv_h2_same_revision_conflict_is_preserved_without_a_winner(
    sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    n, _, _ = _states(sa4_source_vectors, sa4_vectors)
    acquisition = _partial_n_acquisition(n, sa4_source_vectors, sa5_vectors)
    artifact = replace(
        _artifact(sa4_source_vectors, sa4_vectors, "n"),
        car_bytes=_same_revision_fork_car(sa4_source_vectors, sa4_vectors),
    )
    trace = _decision(
        n,
        sa4_source_vectors,
        artifact,
        acquisition=acquisition,
    )

    assert trace.outcome is RecoveryOutcome.INSUFFICIENT_EVIDENCE
    assert trace.reconciliation_reason == (
        "same_revision_has_conflicting_qualified_state"
    )
    assert trace.observed_state.repo_rev == trace.known_state.repo_rev
    assert trace.observed_state.repo_commit_hash != trace.known_state.repo_commit_hash


def test_rcv_h3_invalid_full_snapshot_is_a_hard_refusal_not_rescued_by_partial_ops(
    sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    _, n1, _ = _states(sa4_source_vectors, sa4_vectors)
    acquisition = _acquire(
        n1, sa4_source_vectors, sa5_pages(sa5_vectors, "o2MultiPage")[:2]
    )
    valid = _artifact(sa4_source_vectors, sa4_vectors, "n2")
    trace = _decision(
        n1,
        sa4_source_vectors,
        replace(valid, car_bytes=valid.car_bytes[:-1]),
        acquisition=acquisition,
    )

    assert trace.outcome is RecoveryOutcome.HARD_REFUSAL
    assert trace.failure_reason_code is not None
    assert trace.observed_state is None
    assert trace.transition_receipt_id is None


@pytest.mark.parametrize("substitution", ["space", "author", "repo_host"])
def test_rcv_h4_source_context_substitution_is_refused(
    substitution, sa4_source_vectors, sa4_vectors
) -> None:
    n, _, _ = _states(sa4_source_vectors, sa4_vectors)
    artifact = _artifact(sa4_source_vectors, sa4_vectors, "n1")
    if substitution == "space":
        identity = replace(
            artifact.request.identity,
            space=SpaceIdentity(
                authority_did="did:web:other-spaces.test.invalid",
                space_type="invalid.test.communityspace",
                skey="transition-board",
            ),
        )
        artifact = replace(
            artifact, request=replace(artifact.request, identity=identity)
        )
    elif substitution == "author":
        identity = replace(
            artifact.request.identity,
            repo_did="did:plc:anotherfixtureauthor",
        )
        artifact = replace(
            artifact, request=replace(artifact.request, identity=identity)
        )
    else:
        artifact = replace(
            artifact,
            source=replace(
                artifact.source,
                source_endpoint="https://substitute-repo.test.invalid",
            ),
        )
    trace = _decision(
        n,
        sa4_source_vectors,
        artifact,
        unavailable_reason=OperationUnavailableReason.COMPACTED_OR_UNAVAILABLE,
    )

    assert trace.outcome is RecoveryOutcome.HARD_REFUSAL
    assert trace.failure_reason_code == "spaces_recovery_source_mismatch"


def test_rcv_h5_retries_do_not_upgrade_snapshot_semantics(
    sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    _, n1, _ = _states(sa4_source_vectors, sa4_vectors)
    acquisition = _acquire(
        n1, sa4_source_vectors, sa5_pages(sa5_vectors, "o2MultiPage")[:2]
    )
    first = _decision(
        n1,
        sa4_source_vectors,
        _artifact(sa4_source_vectors, sa4_vectors, "n2"),
        acquisition=acquisition,
    )
    retried = _decision(
        n1,
        sa4_source_vectors,
        _artifact(
            sa4_source_vectors,
            sa4_vectors,
            "n2",
            observed_at="2026-08-22T12:01:00Z",
        ),
        acquisition=acquisition,
        qualified_at="2026-08-22T12:01:01Z",
        decided_at="2026-08-22T12:01:02Z",
    )

    assert first.outcome is retried.outcome is RecoveryOutcome.SNAPSHOT_ONLY
    assert first.transition_receipt_id is retried.transition_receipt_id is None
    with pytest.raises(ValidationError, match="does not match SA6"):
        replace(retried, outcome=RecoveryOutcome.QUALIFIED_TRANSITION)


def test_rcv_h6_retry_with_conflicting_qualified_evidence_does_not_win_by_recency(
    sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    n, _, _ = _states(sa4_source_vectors, sa4_vectors)
    acquisition = _partial_n_acquisition(n, sa4_source_vectors, sa5_vectors)
    first = _decision(
        n,
        sa4_source_vectors,
        _artifact(sa4_source_vectors, sa4_vectors, "n"),
        acquisition=acquisition,
    )
    fork_artifact = replace(
        _artifact(
            sa4_source_vectors,
            sa4_vectors,
            "n",
            observed_at="2026-08-23T12:01:00Z",
        ),
        car_bytes=_same_revision_fork_car(sa4_source_vectors, sa4_vectors),
    )
    retry = _decision(
        n,
        sa4_source_vectors,
        fork_artifact,
        acquisition=acquisition,
        qualified_at="2026-08-23T12:01:01Z",
        decided_at="2026-08-23T12:01:02Z",
    )

    assert first.outcome is RecoveryOutcome.EQUAL_STATE
    assert retry.outcome is RecoveryOutcome.INSUFFICIENT_EVIDENCE
    assert (
        retry.reconciliation_reason == "same_revision_has_conflicting_qualified_state"
    )


def test_rcv_h7_newer_timestamp_cannot_launder_stale_snapshot_currentness(
    sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    _, _, n2 = _states(sa4_source_vectors, sa4_vectors)
    acquisition = _acquire(
        n2, sa4_source_vectors, sa5_pages(sa5_vectors, "o3EmptyTerminal")
    )
    trace = _decision(
        n2,
        sa4_source_vectors,
        _artifact(
            sa4_source_vectors,
            sa4_vectors,
            "n1",
            observed_at="2099-12-31T23:59:57Z",
        ),
        acquisition=acquisition,
        qualified_at="2099-12-31T23:59:58Z",
        decided_at="2099-12-31T23:59:59Z",
    )

    assert trace.outcome is RecoveryOutcome.INSUFFICIENT_EVIDENCE
    assert trace.currentness is False


@pytest.mark.parametrize(
    "claim",
    [
        "canonical_truth",
        "complete_history",
        "authenticated_ancestry",
        "currentness",
        "standing",
        "authorization",
        "governance_authority",
    ],
)
def test_rcv_h8_recovery_trace_refuses_authority_relabeling(
    claim, sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    _, n1, _ = _states(sa4_source_vectors, sa4_vectors)
    acquisition = _acquire(
        n1, sa4_source_vectors, sa5_pages(sa5_vectors, "o2MultiPage")[:2]
    )
    asserted = _artifact(sa4_source_vectors, sa4_vectors, "n2")
    asserted = replace(
        asserted,
        source=replace(
            asserted.source,
            asserted_transport_security="caller-claims-authenticated-ancestry",
            asserted_service_identity="caller-claims-canonical-authority",
        ),
    )
    trace = _decision(
        n1,
        sa4_source_vectors,
        asserted,
        acquisition=acquisition,
    )

    assert trace.outcome is RecoveryOutcome.SNAPSHOT_ONLY
    assert trace.to_provenance()["fullRepoArtifact"]["trustClassification"] == (
        "unverified_sa7_source_context"
    )
    with pytest.raises(ValidationError, match="cannot confer"):
        replace(trace, **{claim: True})
