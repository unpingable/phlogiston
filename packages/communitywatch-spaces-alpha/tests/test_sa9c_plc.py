from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from communitywatch_spaces_alpha import (
    SA9C_PLC_REFERENCE_COMMIT,
    SA9C_PLC_REFERENCE_DRIVER_SHA256,
    SA9C_PLC_REFERENCE_FIXTURE_SHA256,
    DidDocumentProvenanceKind,
    DidInterpretationProfile,
    DidResolutionMethod,
    PlcAuditEntry,
    PlcHistoryEvidence,
    qualify_did_document,
    qualify_plc_history,
)

_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests/fixtures/spaces-alpha/reference/sa9c-plc-reference.json"
)
_DRIVER = _FIXTURE.with_name("sa9c-plc-verify.mjs")
_EVALUATED = datetime.fromisoformat("2026-08-21T18:00:00+00:00")


@pytest.fixture(scope="module")
def plc_vectors() -> dict[str, object]:
    raw = _FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SA9C_PLC_REFERENCE_FIXTURE_SHA256
    assert hashlib.sha256(_DRIVER.read_bytes()).hexdigest() == (
        SA9C_PLC_REFERENCE_DRIVER_SHA256
    )
    value = json.loads(raw)
    assert value["generator"]["commit"] == SA9C_PLC_REFERENCE_COMMIT
    return value


def _entry(value: dict[str, object]) -> PlcAuditEntry:
    return PlcAuditEntry(
        operation_bytes=base64.b64decode(str(value["operationDagCborBase64"])),
        claimed_cid=str(value["cid"]),
        directory_created_at=datetime.fromisoformat(
            str(value["createdAt"]).replace("Z", "+00:00")
        ),
        directory_nullified=bool(value["nullified"]),
    )


def history(
    plc_vectors: dict[str, object], name: str
) -> tuple[dict, PlcHistoryEvidence]:
    histories = plc_vectors["histories"]
    assert isinstance(histories, dict)
    vector = histories[name]
    assert isinstance(vector, dict)
    entries = vector["entries"]
    assert isinstance(entries, list)
    return vector, PlcHistoryEvidence(
        expected_did=str(vector["did"]),
        entries=tuple(_entry(item) for item in entries),
        acquisition_ref=f"reference:{name}:{SA9C_PLC_REFERENCE_COMMIT}",
    )


def test_plc1_genesis_derives_identifier_and_document(plc_vectors) -> None:
    vector, evidence = history(plc_vectors, "modern")
    result = qualify_plc_history(
        PlcHistoryEvidence(
            evidence.expected_did,
            evidence.entries[:1],
            "reference:modern-genesis",
        ),
        evaluated_at=_EVALUATED,
    )

    assert result.resolved_document is not None
    assert result.resolved_document.method is DidResolutionMethod.PLC
    assert "plc_identifier_matches_genesis" in result.receipt.verified_claims
    assert result.receipt.active_operation_cids == (evidence.entries[0].claimed_cid,)
    assert vector["did"] == result.resolved_document.expected_did


def test_plc2_and_plc3_updates_and_rotation_qualify(plc_vectors) -> None:
    _, evidence = history(plc_vectors, "modern")
    result = qualify_plc_history(evidence, evaluated_at=_EVALUATED)

    assert result.resolved_document is not None
    document = json.loads(result.resolved_document.document_bytes)
    assert document["service"][0]["serviceEndpoint"] == ("https://final.invalid.test")
    assert result.receipt.authorized_operations[-1].signer != (
        result.receipt.authorized_operations[0].signer
    )
    assert len(result.receipt.active_operation_cids) == 3


def test_plc4_higher_priority_recovery_retains_nullified_branch(plc_vectors) -> None:
    _, evidence = history(plc_vectors, "recovery")
    result = qualify_plc_history(evidence, evaluated_at=_EVALUATED)

    assert result.receipt.used_recovery is True
    assert len(result.receipt.nullified_operation_cids) == 2
    assert len(result.receipt.active_operation_cids) == 2
    assert "recovery_rules_applied_with_directory_time_context" in (
        result.receipt.verified_claims
    )
    assert result.receipt.directory_timestamps_controller_authenticated is False


def test_plc5_p256_rotation_signatures_are_verified(plc_vectors) -> None:
    _, evidence = history(plc_vectors, "p256")
    result = qualify_plc_history(evidence, evaluated_at=_EVALUATED)

    assert result.receipt.used_p256_rotation is True
    assert {item.signer_curve for item in result.receipt.authorized_operations} == {
        "p256"
    }


def test_plc6_exact_bytes_flow_to_unchanged_sa9b(plc_vectors) -> None:
    _, evidence = history(plc_vectors, "modern")
    result = qualify_plc_history(evidence, evaluated_at=_EVALUATED)
    assert result.resolved_document is not None

    sa9b_input = result.resolved_document.to_sa9b_input()
    binding = qualify_did_document(
        sa9b_input,
        profile=DidInterpretationProfile.ACCOUNT_REPO_HOST,
        qualified_at=_EVALUATED,
    )

    assert sa9b_input.document_bytes is result.resolved_document.document_bytes
    assert binding.document_sha256 == result.resolved_document.document_sha256
    assert binding.document_provenance_kind is (
        DidDocumentProvenanceKind.FUTURE_VERIFIED_DID_RESOLUTION
    )
    assert binding.document_provenance_ref == result.receipt.receipt_id
    assert binding.did_resolution_verified is False


def test_legacy_genesis_is_supported_and_explicit(plc_vectors) -> None:
    _, evidence = history(plc_vectors, "legacy")
    result = qualify_plc_history(evidence, evaluated_at=_EVALUATED)

    assert result.receipt.used_legacy_genesis is True
    assert result.resolved_document is not None
    assert "legacy_create_genesis_normalized" in result.receipt.verified_claims


def test_valid_tombstone_derives_deactivated_state_not_document(plc_vectors) -> None:
    _, evidence = history(plc_vectors, "tombstone")
    result = qualify_plc_history(evidence, evaluated_at=_EVALUATED)

    assert result.receipt.deactivated is True
    assert result.resolved_document is None
    assert "active_state_deactivated_by_tombstone" in result.receipt.verified_claims


@pytest.mark.parametrize("name", ["modern", "p256", "recovery", "legacy"])
def test_local_rendering_has_reference_semantic_parity(plc_vectors, name: str) -> None:
    vector, evidence = history(plc_vectors, name)
    result = qualify_plc_history(evidence, evaluated_at=_EVALUATED)
    assert result.resolved_document is not None

    assert (
        json.loads(result.resolved_document.document_bytes)
        == vector["expectedDocument"]
    )
