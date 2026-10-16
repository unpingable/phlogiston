from __future__ import annotations

from dataclasses import replace

from communitywatch_spaces_alpha import (
    REFERENCE_COMMIT,
    SA8_RECOVERY_DOCTRINE,
    SA8_RECOVERY_METHOD,
    SA8_RECOVERY_VERSION,
    SA8_SOURCE_VECTOR_FORMAT,
    ArtifactRequestIdentity,
    FullRepoArtifactRequest,
    FullRepoArtifactRole,
    ObservedCarArtifact,
    OperationSourceContext,
    OperationUnavailableReason,
    RecoveryOutcome,
    Sa4AttemptDisposition,
    TransitionEvidenceState,
    TransportSourceContext,
    acquire_repo_transition_candidate,
    qualify_recovery_decision,
)
from spaces_support import (
    qualified_sa4_snapshot,
    qualified_sa4_transition,
    sa4_algorithm,
    sa4_author,
    sa4_car,
    sa4_public_key,
    sa4_source_context,
    sa4_space,
    sa5_pages,
    timestamp,
)

_REPO_HOST = "https://repo-transition.test.invalid"


def _states(source_vectors, vectors):
    n = qualified_sa4_snapshot(source_vectors, vectors, "n", "2026-08-20T15:00:02Z")
    n1_transition = qualified_sa4_transition(
        n,
        source_vectors,
        vectors,
        "n1",
        "n-to-n1",
        "2026-08-20T15:01:02Z",
    )
    n2_transition = qualified_sa4_transition(
        n1_transition.target,
        source_vectors,
        vectors,
        "n2",
        "n1-to-n2",
        "2026-08-20T15:02:02Z",
    )
    return n, n1_transition.target, n2_transition.target


def _operation_context(source_vectors, *, source_ref="fixture:sa8:ops"):
    return OperationSourceContext(
        space=sa4_space(source_vectors),
        repo_did=sa4_author(source_vectors),
        repo_host=_REPO_HOST,
        source_ref=source_ref,
        acquired_at=timestamp("2026-08-21T12:00:00Z"),
    )


def _artifact(
    source_vectors,
    vectors,
    state_name,
    *,
    artifact_ref=None,
    observed_at="2026-08-21T12:01:00Z",
):
    reference = artifact_ref or f"fixture:sa8:full-repo:{state_name}"
    return ObservedCarArtifact(
        request=FullRepoArtifactRequest(
            ArtifactRequestIdentity(
                request_id=f"sa8-full-{state_name}",
                space=sa4_space(source_vectors),
                repo_did=sa4_author(source_vectors),
            )
        ),
        source=TransportSourceContext(
            transport_name="fixture-provider",
            source_endpoint=_REPO_HOST,
            artifact_ref=reference,
            observed_at=timestamp(observed_at),
        ),
        car_bytes=sa4_car(vectors, state_name),
    )


def _decision(
    known,
    source_vectors,
    artifact,
    *,
    acquisition=None,
    unavailable_reason=None,
    qualified_at="2026-08-21T12:01:01Z",
    decided_at="2026-08-21T12:01:02Z",
):
    source = replace(
        sa4_source_context(source_vectors),
        repo_host=artifact.source.source_endpoint,
        evidence_ref=artifact.source.artifact_ref,
    )
    return qualify_recovery_decision(
        known,
        operation_acquisition=acquisition,
        operation_unavailable_reason=unavailable_reason,
        full_repo_artifact=artifact,
        author_public_key=sa4_public_key(source_vectors),
        signature_algorithm=sa4_algorithm(source_vectors),
        qualification_source=source,
        qualified_at=timestamp(qualified_at),
        decided_at=timestamp(decided_at),
    )


def _acquire(known, source_vectors, pages):
    return acquire_repo_transition_candidate(
        pages,
        source_state=known,
        context=_operation_context(source_vectors),
    )


def test_sa8_fixture_pins_recovery_boundary(sa8_vectors) -> None:
    compatibility = sa8_vectors["compatibility"]
    assert isinstance(compatibility, dict)
    assert sa8_vectors["format"] == SA8_SOURCE_VECTOR_FORMAT
    assert compatibility == {
        "referenceCommit": REFERENCE_COMMIT,
        "recoveryVersion": SA8_RECOVERY_VERSION,
        "method": SA8_RECOVERY_METHOD,
    }
    assert sa8_vectors["doctrine"] == SA8_RECOVERY_DOCTRINE
    positives = sa8_vectors["positive"]
    assert isinstance(positives, list)
    assert {item["name"] for item in positives if isinstance(item, dict)} == {
        "RCV1",
        "RCV2",
        "RCV3",
        "RCV4",
        "RCV5",
    }


def test_rcv1_complete_oplog_uses_sa4_without_snapshot_fallback(
    sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    n, _, _ = _states(sa4_source_vectors, sa4_vectors)
    acquisition = _acquire(
        n, sa4_source_vectors, sa5_pages(sa5_vectors, "o1CompleteBatch")
    )
    trace = _decision(
        n,
        sa4_source_vectors,
        _artifact(sa4_source_vectors, sa4_vectors, "n1"),
        acquisition=acquisition,
    )

    assert trace.outcome is RecoveryOutcome.QUALIFIED_TRANSITION
    assert trace.transition_evidence is TransitionEvidenceState.AVAILABLE_CANDIDATE
    assert trace.sa4_attempt is Sa4AttemptDisposition.QUALIFIED
    assert trace.full_repo_role is FullRepoArtifactRole.TRANSITION_TARGET
    assert trace.transition_receipt_id is not None
    provenance = trace.to_provenance()
    assert provenance["operationAcquisition"]["resultId"].startswith("sha256:")
    assert provenance["operationAcquisition"]["missingProvenance"] == ()
    assert provenance["qualifiedEvidence"]["knownSa1ReceiptIds"] == tuple(
        receipt.receipt_id for receipt in n.receipts
    )
    assert provenance["qualifiedEvidence"]["observedSa1ReceiptIds"] == (
        trace.observed_state.qualification_receipt_ids
    )
    assert provenance["qualifiedEvidence"]["sa4TransitionReceiptId"] == (
        trace.transition_receipt_id
    )


def test_rcv2_partial_oplog_recovers_only_a_newer_snapshot(
    sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    _, n1, _ = _states(sa4_source_vectors, sa4_vectors)
    acquisition = _acquire(
        n1, sa4_source_vectors, sa5_pages(sa5_vectors, "o2MultiPage")[:2]
    )
    trace = _decision(
        n1,
        sa4_source_vectors,
        _artifact(sa4_source_vectors, sa4_vectors, "n2"),
        acquisition=acquisition,
    )

    assert trace.outcome is RecoveryOutcome.SNAPSHOT_ONLY
    assert trace.transition_evidence is TransitionEvidenceState.PARTIAL
    assert trace.sa4_attempt is Sa4AttemptDisposition.SKIPPED_NO_TRANSITION
    assert trace.full_repo_role is FullRepoArtifactRole.SNAPSHOT_RECOVERY
    assert trace.transition_receipt_id is None
    assert trace.to_provenance()["operationAcquisition"]["missingProvenance"] == (
        "unretrieved_operation_pages",
        "complete_transition_batch",
    )


def test_rcv3_unavailable_oplog_records_loss_and_recovers_only_snapshot(
    sa4_source_vectors, sa4_vectors
) -> None:
    _, n1, _ = _states(sa4_source_vectors, sa4_vectors)
    trace = _decision(
        n1,
        sa4_source_vectors,
        _artifact(sa4_source_vectors, sa4_vectors, "n2"),
        unavailable_reason=OperationUnavailableReason.COMPACTED_OR_UNAVAILABLE,
    )

    assert trace.outcome is RecoveryOutcome.SNAPSHOT_ONLY
    assert trace.transition_evidence is TransitionEvidenceState.UNAVAILABLE
    assert trace.unavailable_reason is (
        OperationUnavailableReason.COMPACTED_OR_UNAVAILABLE
    )
    assert trace.transition_receipt_id is None


def test_rcv4_partial_oplog_and_equal_snapshot_produce_no_transition_claim(
    sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    _, n1, _ = _states(sa4_source_vectors, sa4_vectors)
    acquisition = _acquire(
        n1, sa4_source_vectors, sa5_pages(sa5_vectors, "o2MultiPage")[:2]
    )
    trace = _decision(
        n1,
        sa4_source_vectors,
        _artifact(sa4_source_vectors, sa4_vectors, "n1"),
        acquisition=acquisition,
    )

    assert trace.outcome is RecoveryOutcome.EQUAL_STATE
    assert trace.transition_receipt_id is None
    assert trace.sa4_attempt is Sa4AttemptDisposition.SKIPPED_NO_TRANSITION


def test_rcv5_sa4_refusal_does_not_poison_independent_snapshot_or_become_transition(
    sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    _, n1, _ = _states(sa4_source_vectors, sa4_vectors)
    pages = list(sa5_pages(sa5_vectors, "o2MultiPage"))
    first_operation = pages[0].operations[0]
    pages[0] = replace(
        pages[0],
        operations=(
            replace(
                first_operation,
                cid=n1.records[0].cid,
            ),
        ),
    )
    acquisition = _acquire(n1, sa4_source_vectors, tuple(pages))
    trace = _decision(
        n1,
        sa4_source_vectors,
        _artifact(sa4_source_vectors, sa4_vectors, "n2"),
        acquisition=acquisition,
    )

    assert trace.outcome is RecoveryOutcome.SNAPSHOT_ONLY
    assert trace.transition_evidence is TransitionEvidenceState.CANDIDATE_REFUSED
    assert trace.sa4_attempt is Sa4AttemptDisposition.REFUSED
    assert trace.sa4_failure_reason_code is not None
    assert trace.full_repo_role is FullRepoArtifactRole.SNAPSHOT_AFTER_REFUSAL
    assert trace.transition_receipt_id is None
    assert trace.to_provenance()["operationAcquisition"]["missingProvenance"] == (
        "qualified_transition_relationship",
    )
