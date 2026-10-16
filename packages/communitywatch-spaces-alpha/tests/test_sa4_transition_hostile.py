from __future__ import annotations

from dataclasses import replace

import pytest

from community_model import ValidationError
from communitywatch_spaces_alpha import (
    RepoTransition,
    SpaceIdentity,
    qualify_repo_state,
    qualify_repo_transition,
)
from spaces_support import (
    sa4_algorithm,
    sa4_author,
    sa4_evidence,
    sa4_public_key,
    sa4_source_context,
    sa4_space,
    timestamp,
)


def _assert_refusal(reason: str, operation) -> None:
    with pytest.raises(ValidationError) as caught:
        operation()
    assert caught.value.reason_code == reason


def _flatten_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {str(key).lower() for key in value} | set().union(
            *(_flatten_keys(item) for item in value.values()), set()
        )
    if isinstance(value, list | tuple):
        return set().union(*(_flatten_keys(item) for item in value), set())
    return set()


def _snapshot(
    source_vectors: dict[str, object],
    vectors: dict[str, object],
    state_name: str,
    verified_at: str,
):
    return qualify_repo_state(
        sa4_evidence(source_vectors, vectors, state_name),
        expected_space=sa4_space(source_vectors),
        expected_author_did=sa4_author(source_vectors),
        author_public_key=sa4_public_key(source_vectors),
        signature_algorithm=sa4_algorithm(source_vectors),
        source=sa4_source_context(source_vectors),
        verified_at=timestamp(verified_at),
    )


def _qualify_transition(
    source_state,
    target_evidence,
    source_vectors: dict[str, object],
    *,
    space: SpaceIdentity | None = None,
    verified_at: str = "2026-08-20T15:02:02Z",
):
    return qualify_repo_transition(
        source_state,
        target_evidence,
        expected_space=space or sa4_space(source_vectors),
        expected_author_did=sa4_author(source_vectors),
        author_public_key=sa4_public_key(source_vectors),
        signature_algorithm=sa4_algorithm(source_vectors),
        source=sa4_source_context(source_vectors),
        verified_at=timestamp(verified_at),
    )


def _n1_state(source_vectors: dict[str, object], vectors: dict[str, object]):
    n = _snapshot(source_vectors, vectors, "n", "2026-08-20T15:00:02Z")
    return _qualify_transition(
        n,
        sa4_evidence(source_vectors, vectors, "n1", transition_name="n-to-n1"),
        source_vectors,
        verified_at="2026-08-20T15:01:02Z",
    ).target


def test_th1_valid_final_state_with_wrong_parent_state_is_refused(
    sa4_source_vectors: dict[str, object], sa4_vectors: dict[str, object]
) -> None:
    source = _n1_state(sa4_source_vectors, sa4_vectors)
    evidence = sa4_evidence(
        sa4_source_vectors,
        sa4_vectors,
        "n2",
        transition_name="n1-to-n2",
    )
    transition = evidence.transition
    assert isinstance(transition, RepoTransition)
    wrong_parent = bytes([transition.prior_state[0] ^ 1]) + transition.prior_state[1:]

    _assert_refusal(
        "spaces_transition_source_mismatch",
        lambda: _qualify_transition(
            source,
            replace(evidence, transition=replace(transition, prior_state=wrong_parent)),
            sa4_source_vectors,
        ),
    )


def test_th2_missing_intermediate_is_refused_but_final_snapshot_still_qualifies(
    sa4_source_vectors: dict[str, object], sa4_vectors: dict[str, object]
) -> None:
    n = _snapshot(sa4_source_vectors, sa4_vectors, "n", "2026-08-20T15:00:02Z")
    n2_transition = sa4_evidence(
        sa4_source_vectors,
        sa4_vectors,
        "n2",
        transition_name="n1-to-n2",
    )

    _assert_refusal(
        "spaces_transition_source_mismatch",
        lambda: _qualify_transition(n, n2_transition, sa4_source_vectors),
    )
    snapshot = _snapshot(sa4_source_vectors, sa4_vectors, "n2", "2026-08-20T15:02:02Z")
    assert snapshot.commit.rev == "3mtaaaabbbbbh"
    assert all(
        "state_transition_from_supplied_prior"
        not in {claim.value for claim in receipt.verified_claims}
        for receipt in snapshot.receipts
    )


def test_th3_reordered_independent_operations_are_explicitly_equivalent_not_sorted(
    sa4_source_vectors: dict[str, object], sa4_vectors: dict[str, object]
) -> None:
    source = _n1_state(sa4_source_vectors, sa4_vectors)
    evidence = sa4_evidence(
        sa4_source_vectors,
        sa4_vectors,
        "n2",
        transition_name="n1-to-n2",
    )
    transition = evidence.transition
    assert isinstance(transition, RepoTransition)
    reference = _qualify_transition(source, evidence, sa4_source_vectors)
    reordered = _qualify_transition(
        source,
        replace(
            evidence,
            transition=replace(
                transition, operations=tuple(reversed(transition.operations))
            ),
        ),
        sa4_source_vectors,
    )

    assert reference.target == reordered.target
    assert reference.receipt.source_state == reordered.receipt.source_state
    assert reference.receipt.target_state == reordered.receipt.target_state
    assert {effect.to_provenance()["path"] for effect in reference.receipt.effects} == {
        effect.to_provenance()["path"] for effect in reordered.receipt.effects
    }
    assert tuple(effect.rkey for effect in reference.receipt.effects) == (
        "delta",
        "beta",
        "gamma",
    )
    assert tuple(effect.rkey for effect in reordered.receipt.effects) == (
        "gamma",
        "beta",
        "delta",
    )
    assert reference.receipt.receipt_id != reordered.receipt.receipt_id


def test_th4_mutated_operation_with_unchanged_target_is_refused(
    sa4_source_vectors: dict[str, object], sa4_vectors: dict[str, object]
) -> None:
    source = _n1_state(sa4_source_vectors, sa4_vectors)
    evidence = sa4_evidence(
        sa4_source_vectors,
        sa4_vectors,
        "n2",
        transition_name="n1-to-n2",
    )
    transition = evidence.transition
    assert isinstance(transition, RepoTransition)
    changed = replace(transition.operations[1], prev=transition.operations[2].prev)

    _assert_refusal(
        "spaces_transition_invalid",
        lambda: _qualify_transition(
            source,
            replace(
                evidence,
                transition=replace(
                    transition,
                    operations=(
                        transition.operations[0],
                        changed,
                        transition.operations[2],
                    ),
                ),
            ),
            sa4_source_vectors,
        ),
    )


def test_th5_final_state_only_remains_snapshot_not_transition_evidence(
    sa4_source_vectors: dict[str, object], sa4_vectors: dict[str, object]
) -> None:
    source = _n1_state(sa4_source_vectors, sa4_vectors)
    snapshot_evidence = sa4_evidence(sa4_source_vectors, sa4_vectors, "n2")
    snapshot = _snapshot(sa4_source_vectors, sa4_vectors, "n2", "2026-08-20T15:02:02Z")

    assert len(snapshot.records) == 3
    _assert_refusal(
        "spaces_transition_evidence_required",
        lambda: _qualify_transition(source, snapshot_evidence, sa4_source_vectors),
    )


def test_th6_final_accumulator_index_mismatch_is_refused(
    sa4_source_vectors: dict[str, object], sa4_vectors: dict[str, object]
) -> None:
    source = _n1_state(sa4_source_vectors, sa4_vectors)
    target = sa4_evidence(
        sa4_source_vectors,
        sa4_vectors,
        "n2",
        transition_name="n1-to-n2",
    )
    n1_index = sa4_evidence(sa4_source_vectors, sa4_vectors, "n1").index_bytes

    _assert_refusal(
        "spaces_lthash_invalid",
        lambda: _qualify_transition(
            source,
            replace(target, index_bytes=n1_index),
            sa4_source_vectors,
        ),
    )


def test_th7_cross_space_transition_is_refused(
    sa4_source_vectors: dict[str, object], sa4_vectors: dict[str, object]
) -> None:
    source = _n1_state(sa4_source_vectors, sa4_vectors)
    target = sa4_evidence(
        sa4_source_vectors,
        sa4_vectors,
        "n2",
        transition_name="n1-to-n2",
    )
    expected = sa4_space(sa4_source_vectors)
    other = SpaceIdentity(
        authority_did="did:web:other-space.test.invalid",
        space_type=expected.space_type,
        skey=expected.skey,
    )

    _assert_refusal(
        "spaces_mac_invalid",
        lambda: _qualify_transition(source, target, sa4_source_vectors, space=other),
    )


@pytest.mark.parametrize(
    "field_name",
    [
        "complete_history",
        "signed_ancestry",
        "operation_log_authenticated",
        "actor_legitimacy",
        "authorization",
        "governance_authority",
    ],
)
def test_th8_transition_receipt_cannot_be_upgraded_to_authority(
    sa4_source_vectors: dict[str, object],
    sa4_vectors: dict[str, object],
    field_name: str,
) -> None:
    source = _n1_state(sa4_source_vectors, sa4_vectors)
    qualified = _qualify_transition(
        source,
        sa4_evidence(
            sa4_source_vectors,
            sa4_vectors,
            "n2",
            transition_name="n1-to-n2",
        ),
        sa4_source_vectors,
    )

    _assert_refusal(
        "spaces_transition_receipt_invalid",
        lambda: replace(qualified.receipt, **{field_name: True}),
    )


def test_transition_receipt_cannot_relabel_a_mutated_record_effect(
    sa4_source_vectors: dict[str, object], sa4_vectors: dict[str, object]
) -> None:
    source = _n1_state(sa4_source_vectors, sa4_vectors)
    qualified = _qualify_transition(
        source,
        sa4_evidence(
            sa4_source_vectors,
            sa4_vectors,
            "n2",
            transition_name="n1-to-n2",
        ),
        sa4_source_vectors,
    )
    alpha_cid = next(
        record.cid
        for record in qualified.target.records
        if record.identity.rkey == "alpha"
    )
    changed = replace(qualified.receipt.effects[0], resulting_cid=alpha_cid)

    _assert_refusal(
        "spaces_transition_receipt_invalid",
        lambda: replace(
            qualified.receipt,
            effects=(changed, *qualified.receipt.effects[1:]),
        ),
    )


def test_hostile_fixture_contains_no_secret_key_material(
    sa4_source_vectors: dict[str, object],
) -> None:
    assert not (
        _flatten_keys(sa4_source_vectors)
        & {
            "private_key",
            "privatekey",
            "oauth_token",
            "space_credential",
            "delegation_token",
            "dpop_private_key",
            "authorization_header",
            "cookie",
        }
    )
