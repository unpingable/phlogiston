from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from communitywatch_spaces_alpha import (
    SA1_VERIFIER_VERSION,
    SA2_CAR_ADAPTER_VERSION,
    SA4_REFERENCE_ARTIFACT_SHA256,
    SA4_REFERENCE_COMMIT,
    SA4_REFERENCE_DRIVER_SHA256,
    SA4_REFERENCE_IMPLEMENTATION,
    SA4_REFERENCE_MANIFEST_SHA256,
    SA4_REFERENCE_OPERATION_SHA256,
    SA4_REFERENCE_PACKAGE_VERSION,
    SA4_REFERENCE_SOURCE_SHA256,
    SA4_REFERENCE_VECTOR_FORMAT,
    SA4_TRANSITION_METHOD,
    SA4_TRANSITION_RECEIPT_IDS,
    SA4_TRANSITION_VERSION,
    TransitionOperationKind,
    VerifiedTransitionClaim,
    parse_space_car,
    qualify_repo_state,
    qualify_repo_transition,
)
from spaces_support import (
    SA4_FIXTURE,
    SA4_SOURCE_FIXTURE,
    sa4_algorithm,
    sa4_author,
    sa4_car,
    sa4_evidence,
    sa4_manifest_state,
    sa4_public_key,
    sa4_source_context,
    sa4_space,
    sa4_transition_source,
    timestamp,
)

REFERENCE_DRIVER = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "spaces-alpha"
    / "reference"
    / "sa4-generate.mjs"
)


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


def _transition(
    source_state,
    source_vectors: dict[str, object],
    vectors: dict[str, object],
    target_name: str,
    transition_name: str,
    verified_at: str,
):
    return qualify_repo_transition(
        source_state,
        sa4_evidence(
            source_vectors,
            vectors,
            target_name,
            transition_name=transition_name,
        ),
        expected_space=sa4_space(source_vectors),
        expected_author_did=sa4_author(source_vectors),
        author_public_key=sa4_public_key(source_vectors),
        signature_algorithm=sa4_algorithm(source_vectors),
        source=sa4_source_context(source_vectors),
        verified_at=timestamp(verified_at),
    )


def _first_transition(source_vectors: dict[str, object], vectors: dict[str, object]):
    source = _snapshot(source_vectors, vectors, "n", "2026-08-20T15:00:02Z")
    return _transition(
        source,
        source_vectors,
        vectors,
        "n1",
        "n-to-n1",
        "2026-08-20T15:01:02Z",
    )


def test_reference_transition_fixture_pins_generator_and_all_state_cars(
    sa4_source_vectors: dict[str, object], sa4_vectors: dict[str, object]
) -> None:
    generator = sa4_vectors["generator"]
    local = sa4_vectors["localExpectation"]
    assert isinstance(generator, dict) and isinstance(local, dict)
    assert sa4_vectors["format"] == SA4_REFERENCE_VECTOR_FORMAT
    assert generator["implementation"] == SA4_REFERENCE_IMPLEMENTATION
    assert generator["packageVersion"] == SA4_REFERENCE_PACKAGE_VERSION
    assert generator["commit"] == SA4_REFERENCE_COMMIT
    assert generator["pnpmVersion"] == "11.11.0"
    assert generator["driverSha256"] == SA4_REFERENCE_DRIVER_SHA256
    assert generator["sourceSha256"] == SA4_REFERENCE_SOURCE_SHA256
    assert hashlib.sha256(SA4_FIXTURE.read_bytes()).hexdigest() == (
        SA4_REFERENCE_MANIFEST_SHA256
    )
    assert local == {
        "carAdapterVersion": SA2_CAR_ADAPTER_VERSION,
        "qualifierVersion": SA1_VERIFIER_VERSION,
        "transitionQualifierVersion": SA4_TRANSITION_VERSION,
    }
    assert (
        hashlib.sha256(REFERENCE_DRIVER.read_bytes()).hexdigest()
        == generator["driverSha256"]
    )
    assert (
        hashlib.sha256(SA4_SOURCE_FIXTURE.read_bytes()).hexdigest()
        == generator["sourceSha256"]
    )
    for name in ("n", "n1", "n2"):
        expected = sa4_manifest_state(sa4_vectors, name)
        raw = sa4_car(sa4_vectors, name)
        parsed = parse_space_car(
            raw, source_vector_identifier=str(expected["sourceVectorIdentifier"])
        )
        assert hashlib.sha256(raw).hexdigest() == expected["rawSha256"]
        assert expected["rawSha256"] == SA4_REFERENCE_ARTIFACT_SHA256[name]
        assert len(raw) == expected["byteLength"]
        assert parsed.roots == tuple(expected["roots"])
        expected_blocks = expected["blocks"]
        assert isinstance(expected_blocks, list)
        assert tuple(block.cid for block in parsed.blocks) == tuple(
            block["cid"] for block in expected_blocks if isinstance(block, dict)
        )
        assert tuple(block.block_bytes for block in parsed.blocks) == tuple(
            base64.b64decode(block["bytesB64"], validate=True)
            for block in expected_blocks
            if isinstance(block, dict)
        )
        assert expected["regeneration"] == {
            "runs": 2,
            "stability": "byte-identical",
            "firstSha256": expected["rawSha256"],
            "secondSha256": expected["rawSha256"],
        }
    transitions = sa4_vectors["transitions"]
    assert isinstance(transitions, list)
    assert all(
        isinstance(item, dict) and item["referenceReplayMatchesTarget"] is True
        for item in transitions
    )
    for name in ("n-to-n1", "n1-to-n2"):
        transition = sa4_transition_source(sa4_vectors, name)
        assert (
            transition["orderedOperationSha256"]
            == (SA4_REFERENCE_OPERATION_SHA256[name])
        )
        assert (
            transition["expectedTransitionReceiptId"]
            == (SA4_TRANSITION_RECEIPT_IDS[name])
        )


def test_t1_multi_record_add_qualifies_exact_source_and_target(
    sa4_source_vectors: dict[str, object], sa4_vectors: dict[str, object]
) -> None:
    qualified = _first_transition(sa4_source_vectors, sa4_vectors)

    assert len(qualified.source.records) == 2
    assert len(qualified.target.records) == 3
    assert qualified.receipt.source_state.repo_rev == "3mtaaaabbbbbf"
    assert qualified.receipt.target_state.repo_rev == "3mtaaaabbbbbg"
    assert tuple(effect.kind for effect in qualified.receipt.effects) == (
        TransitionOperationKind.ADD,
    )
    assert qualified.receipt.effects[0].rkey == "gamma"
    assert qualified.receipt.receipt_id == SA4_TRANSITION_RECEIPT_IDS["n-to-n1"]
    assert qualified.receipt.verified_claims == frozenset(VerifiedTransitionClaim)


def test_t2_update_changes_exact_record_cid_and_qualifies(
    sa4_source_vectors: dict[str, object], sa4_vectors: dict[str, object]
) -> None:
    first = _first_transition(sa4_source_vectors, sa4_vectors)
    second = _transition(
        first.target,
        sa4_source_vectors,
        sa4_vectors,
        "n2",
        "n1-to-n2",
        "2026-08-20T15:02:02Z",
    )
    update = second.receipt.effects[1]

    assert update.kind is TransitionOperationKind.UPDATE
    assert update.rkey == "beta"
    assert update.prior_cid != update.resulting_cid
    assert {record.identity.rkey: record.cid for record in second.source.records}[
        "beta"
    ] == update.prior_cid
    assert {record.identity.rkey: record.cid for record in second.target.records}[
        "beta"
    ] == update.resulting_cid


def test_t3_reference_mixed_batch_preserves_add_update_remove_order(
    sa4_source_vectors: dict[str, object], sa4_vectors: dict[str, object]
) -> None:
    first = _first_transition(sa4_source_vectors, sa4_vectors)
    second = _transition(
        first.target,
        sa4_source_vectors,
        sa4_vectors,
        "n2",
        "n1-to-n2",
        "2026-08-20T15:02:02Z",
    )

    assert tuple(effect.ordinal for effect in second.receipt.effects) == (0, 1, 2)
    assert tuple(effect.kind for effect in second.receipt.effects) == (
        TransitionOperationKind.ADD,
        TransitionOperationKind.UPDATE,
        TransitionOperationKind.REMOVE,
    )
    assert tuple(effect.rkey for effect in second.receipt.effects) == (
        "delta",
        "beta",
        "gamma",
    )
    assert tuple(record.identity.rkey for record in second.target.records) == (
        "beta",
        "alpha",
        "delta",
    )


def test_t4_two_sequential_revisions_each_have_a_bound_transition_receipt(
    sa4_source_vectors: dict[str, object], sa4_vectors: dict[str, object]
) -> None:
    first = _first_transition(sa4_source_vectors, sa4_vectors)
    second = _transition(
        first.target,
        sa4_source_vectors,
        sa4_vectors,
        "n2",
        "n1-to-n2",
        "2026-08-20T15:02:02Z",
    )

    assert first.receipt.target_state == second.receipt.source_state
    assert first.receipt.receipt_id != second.receipt.receipt_id
    assert second.receipt.receipt_id == SA4_TRANSITION_RECEIPT_IDS["n1-to-n2"]
    assert first.target is second.source
    provenance = second.receipt.to_provenance()
    assert provenance["qualificationMethod"] == SA4_TRANSITION_METHOD
    assert provenance["completeHistory"] is False
    assert provenance["signedAncestry"] is False
    assert provenance["operationLogAuthenticated"] is False
    assert provenance["actorLegitimacy"] is False
    assert provenance["authorization"] is False
    assert provenance["governanceAuthority"] is False
