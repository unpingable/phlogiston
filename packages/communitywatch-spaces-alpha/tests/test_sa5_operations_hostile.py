from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from community_model import ValidationError
from communitywatch_spaces_alpha import (
    OperationAcquisitionStatus,
    OperationSourceContext,
    SpaceRepoEvidence,
    acquire_repo_transition_candidate,
    parse_list_repo_ops_page,
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
    sa5_case,
    sa5_pages,
    timestamp,
)


def _refuses(reason: str, operation) -> None:
    with pytest.raises(ValidationError) as caught:
        operation()
    assert caught.value.reason_code == reason


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


def _n1(source_vectors: dict[str, object], vectors: dict[str, object]):
    n = qualified_sa4_snapshot(source_vectors, vectors, "n", "2026-08-20T15:00:02Z")
    return qualified_sa4_transition(
        n,
        source_vectors,
        vectors,
        "n1",
        "n-to-n1",
        "2026-08-20T15:01:02Z",
    ).target


def test_oh1_reordered_pages_are_refused(
    sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    pages = sa5_pages(sa5_vectors, "o2MultiPage")
    _refuses(
        "spaces_operation_page_order_invalid",
        lambda: acquire_repo_transition_candidate(
            (pages[1], pages[0], pages[2]),
            source_state=_n1(sa4_source_vectors, sa4_vectors),
            context=_context(sa5_vectors, sa4_source_vectors),
        ),
    )


def test_oh2_missing_terminal_page_remains_partial_not_transition_candidate(
    sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    result = acquire_repo_transition_candidate(
        sa5_pages(sa5_vectors, "o2MultiPage")[:2],
        source_state=_n1(sa4_source_vectors, sa4_vectors),
        context=_context(sa5_vectors, sa4_source_vectors),
    )
    assert result.status is OperationAcquisitionStatus.PARTIAL_RETRIEVAL
    assert result.pagination_chain_closed is False
    assert result.transition is None


def test_oh3_duplicate_operation_is_refused_not_deduplicated(
    sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    page = sa5_pages(sa5_vectors, "o1CompleteBatch")[0]
    duplicate = replace(
        page,
        operations=(page.operations[0], page.operations[0]),
        value_presence=(False, False),
    )
    source = qualified_sa4_snapshot(
        sa4_source_vectors, sa4_vectors, "n", "2026-08-20T15:00:02Z"
    )
    _refuses(
        "spaces_operation_duplicate",
        lambda: acquire_repo_transition_candidate(
            (duplicate,),
            source_state=source,
            context=_context(sa5_vectors, sa4_source_vectors),
        ),
    )


def test_oh4_cursor_mismatch_is_refused(
    sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    pages = sa5_pages(sa5_vectors, "o2MultiPage")
    changed = (pages[0], replace(pages[1], request_cursor="wrong/7"), pages[2])
    _refuses(
        "spaces_operation_cursor_mismatch",
        lambda: acquire_repo_transition_candidate(
            changed,
            source_state=_n1(sa4_source_vectors, sa4_vectors),
            context=_context(sa5_vectors, sa4_source_vectors),
        ),
    )


def test_oh5_operation_mutation_constructs_candidate_but_sa4_refuses(
    sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    source = _n1(sa4_source_vectors, sa4_vectors)
    pages = sa5_pages(sa5_vectors, "o2MultiPage")
    alpha_cid = next(
        record.cid for record in source.records if record.identity.rkey == "alpha"
    )
    mutated_first = replace(
        pages[0], operations=(replace(pages[0].operations[0], cid=alpha_cid),)
    )
    result = acquire_repo_transition_candidate(
        (mutated_first, pages[1], pages[2]),
        source_state=source,
        context=_context(sa5_vectors, sa4_source_vectors),
    )
    target = sa4_evidence(sa4_source_vectors, sa4_vectors, "n2")
    evidence = SpaceRepoEvidence(
        source_vector_identifier=target.source_vector_identifier,
        proof_kind=target.proof_kind,
        protocol_assumption=target.protocol_assumption,
        commit_bytes=target.commit_bytes,
        index_bytes=target.index_bytes,
        record_blocks=target.record_blocks,
        transition=result.transition,
    )

    _refuses(
        "spaces_transition_invalid",
        lambda: qualify_repo_transition(
            source,
            evidence,
            expected_space=sa4_space(sa4_source_vectors),
            expected_author_did=sa4_author(sa4_source_vectors),
            author_public_key=sa4_public_key(sa4_source_vectors),
            signature_algorithm=sa4_algorithm(sa4_source_vectors),
            source=sa4_source_context(sa4_source_vectors),
            verified_at=timestamp("2026-08-20T15:02:02Z"),
        ),
    )


@pytest.mark.parametrize(
    "claim",
    [
        "complete_history",
        "authenticated_history",
        "source_authority",
        "authorization",
        "governance_authority",
    ],
)
def test_oh6_operation_result_cannot_be_relabelled_as_stronger_claim(
    sa4_source_vectors, sa4_vectors, sa5_vectors, claim
) -> None:
    source = qualified_sa4_snapshot(
        sa4_source_vectors, sa4_vectors, "n", "2026-08-20T15:00:02Z"
    )
    result = acquire_repo_transition_candidate(
        sa5_pages(sa5_vectors, "o1CompleteBatch"),
        source_state=source,
        context=_context(sa5_vectors, sa4_source_vectors),
    )
    _refuses(
        "spaces_operation_acquisition_invalid",
        lambda: replace(result, **{claim: True}),
    )


def test_oh6_caller_claim_added_to_wire_response_is_refused(sa5_vectors) -> None:
    case = sa5_case(sa5_vectors, "o1CompleteBatch")
    pages = case["pages"]
    assert isinstance(pages, list) and isinstance(pages[0], dict)
    raw = deepcopy(pages[0]["response"])
    assert isinstance(raw, dict)
    raw["completeHistory"] = True

    _refuses(
        "spaces_operation_response_invalid",
        lambda: parse_list_repo_ops_page(
            raw,
            ordinal=0,
            request_since=str(pages[0]["requestSince"]),
            request_cursor=None,
            received_at=timestamp(str(pages[0]["receivedAt"])),
        ),
    )
