from __future__ import annotations

from communitywatch_spaces_alpha import (
    ENDPOINTS,
    REFERENCE_COMMIT,
    SA5_ADAPTER_VERSION,
    SA5_SOURCE_VECTOR_FORMAT,
    ObservedOperationClaim,
    OperationAcquisitionStatus,
    OperationSourceContext,
    SpaceRepoEvidence,
    acquire_repo_transition_candidate,
    qualify_repo_transition,
)
from spaces_support import (
    qualified_sa4_snapshot,
    qualified_sa4_transition,
    sa4_algorithm,
    sa4_author,
    sa4_evidence,
    sa4_public_key,
    sa4_source_context,
    sa4_space,
    sa5_pages,
    timestamp,
)


def _context(document: dict[str, object], source_vectors: dict[str, object]):
    raw = document["source"]
    assert isinstance(raw, dict)
    return OperationSourceContext(
        space=sa4_space(source_vectors),
        repo_did=str(raw["repoDid"]),
        repo_host=str(raw["repoHost"]),
        source_ref=str(raw["sourceRef"]),
        acquired_at=timestamp(str(raw["acquiredAt"])),
    )


def _qualify_candidate(
    source_state,
    result,
    source_vectors: dict[str, object],
    vectors: dict[str, object],
    target_name: str,
    verified_at: str,
):
    target = sa4_evidence(source_vectors, vectors, target_name)
    evidence = SpaceRepoEvidence(
        source_vector_identifier=target.source_vector_identifier,
        proof_kind=target.proof_kind,
        protocol_assumption=target.protocol_assumption,
        commit_bytes=target.commit_bytes,
        index_bytes=target.index_bytes,
        record_blocks=target.record_blocks,
        transition=result.transition,
    )
    return qualify_repo_transition(
        source_state,
        evidence,
        expected_space=sa4_space(source_vectors),
        expected_author_did=sa4_author(source_vectors),
        author_public_key=sa4_public_key(source_vectors),
        signature_algorithm=sa4_algorithm(source_vectors),
        source=sa4_source_context(source_vectors),
        verified_at=timestamp(verified_at),
    )


def test_sa5_fixture_and_endpoint_are_pinned(sa5_vectors: dict[str, object]) -> None:
    compatibility = sa5_vectors["compatibility"]
    assert isinstance(compatibility, dict)
    assert sa5_vectors["format"] == SA5_SOURCE_VECTOR_FORMAT
    assert compatibility["endpoint"] == ENDPOINTS["incremental"]
    assert compatibility["referenceCommit"] == REFERENCE_COMMIT
    assert compatibility["adapterVersion"] == SA5_ADAPTER_VERSION


def test_o1_complete_operation_response_constructs_sa4_candidate(
    sa4_source_vectors: dict[str, object],
    sa4_vectors: dict[str, object],
    sa5_vectors: dict[str, object],
) -> None:
    source = qualified_sa4_snapshot(
        sa4_source_vectors, sa4_vectors, "n", "2026-08-20T15:00:02Z"
    )
    result = acquire_repo_transition_candidate(
        sa5_pages(sa5_vectors, "o1CompleteBatch"),
        source_state=source,
        context=_context(sa5_vectors, sa4_source_vectors),
    )

    assert result.status is OperationAcquisitionStatus.TRANSITION_CANDIDATE
    assert (
        result.transition
        == sa4_evidence(
            sa4_source_vectors, sa4_vectors, "n1", transition_name="n-to-n1"
        ).transition
    )
    assert ObservedOperationClaim.CANDIDATE_CONSTRUCTION in result.verified_claims
    qualified = _qualify_candidate(
        source,
        result,
        sa4_source_vectors,
        sa4_vectors,
        "n1",
        "2026-08-20T15:01:02Z",
    )
    assert qualified.target.commit.rev == "3mtaaaabbbbbg"
    assert result.to_provenance()["completeHistory"] is False


def test_o2_three_pages_preserve_page_operation_and_value_presence_order(
    sa4_source_vectors: dict[str, object],
    sa4_vectors: dict[str, object],
    sa5_vectors: dict[str, object],
) -> None:
    n = qualified_sa4_snapshot(
        sa4_source_vectors, sa4_vectors, "n", "2026-08-20T15:00:02Z"
    )
    n1 = qualified_sa4_transition(
        n,
        sa4_source_vectors,
        sa4_vectors,
        "n1",
        "n-to-n1",
        "2026-08-20T15:01:02Z",
    ).target
    pages = sa5_pages(sa5_vectors, "o2MultiPage")
    result = acquire_repo_transition_candidate(
        pages,
        source_state=n1,
        context=_context(sa5_vectors, sa4_source_vectors),
    )

    assert tuple(page.ordinal for page in result.pages) == (0, 1, 2)
    assert tuple(op.rkey for op in result.transition.operations) == (
        "delta",
        "beta",
        "gamma",
    )
    assert tuple(present for page in pages for present in page.value_presence) == (
        True,
        False,
        False,
    )
    assert result.pages[-1].terminal_commit_sha256 is not None
    qualified = _qualify_candidate(
        n1,
        result,
        sa4_source_vectors,
        sa4_vectors,
        "n2",
        "2026-08-20T15:02:02Z",
    )
    assert qualified.target.commit.rev == "3mtaaaabbbbbh"


def test_o3_empty_terminal_page_is_explicit_and_not_a_transition(
    sa4_source_vectors: dict[str, object],
    sa4_vectors: dict[str, object],
    sa5_vectors: dict[str, object],
) -> None:
    n = qualified_sa4_snapshot(
        sa4_source_vectors, sa4_vectors, "n", "2026-08-20T15:00:02Z"
    )
    n1_transition = qualified_sa4_transition(
        n,
        sa4_source_vectors,
        sa4_vectors,
        "n1",
        "n-to-n1",
        "2026-08-20T15:01:02Z",
    )
    n2 = qualified_sa4_transition(
        n1_transition.target,
        sa4_source_vectors,
        sa4_vectors,
        "n2",
        "n1-to-n2",
        "2026-08-20T15:02:02Z",
    ).target
    result = acquire_repo_transition_candidate(
        sa5_pages(sa5_vectors, "o3EmptyTerminal"),
        source_state=n2,
        context=_context(sa5_vectors, sa4_source_vectors),
    )

    assert result.status is OperationAcquisitionStatus.EMPTY_TERMINAL_PAGE
    assert result.pagination_chain_closed is True
    assert result.transition is None
    assert result.ordered_operation_sha256 is None
