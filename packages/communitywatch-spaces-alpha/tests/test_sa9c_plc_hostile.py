from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from community_model import ValidationError
from community_model.canonical import cid_for_dag_cbor
from community_model.dag_cbor import decode_dag_cbor, encode_dag_cbor
from communitywatch_spaces_alpha import (
    DidResolutionMethod,
    PlcAuditEntry,
    PlcHistoryEvidence,
    qualify_plc_history,
    require_resolution_method,
)

_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests/fixtures/spaces-alpha/reference/sa9c-plc-reference.json"
)
_NOW = datetime.fromisoformat("2026-08-21T18:00:00+00:00")


@pytest.fixture(scope="module")
def vectors() -> dict[str, object]:
    return json.loads(_FIXTURE.read_bytes())


def _entry(value: dict[str, object]) -> PlcAuditEntry:
    return PlcAuditEntry(
        base64.b64decode(str(value["operationDagCborBase64"])),
        str(value["cid"]),
        datetime.fromisoformat(str(value["createdAt"]).replace("Z", "+00:00")),
        bool(value["nullified"]),
    )


def _history(vectors, name: str) -> PlcHistoryEvidence:
    vector = vectors["histories"][name]
    return PlcHistoryEvidence(
        str(vector["did"]),
        tuple(_entry(item) for item in vector["entries"]),
        f"fixture:{name}",
    )


def _hostile(vectors, name: str) -> PlcAuditEntry:
    return _entry(vectors["hostileOperations"][name])


def _with_operation(
    entry: PlcAuditEntry,
    operation: dict[str, object],
    *,
    retain_claimed_cid: bool = False,
) -> PlcAuditEntry:
    raw = encode_dag_cbor(operation)
    return PlcAuditEntry(
        raw,
        entry.claimed_cid if retain_claimed_cid else cid_for_dag_cbor(raw),
        entry.directory_created_at,
        entry.directory_nullified,
    )


def _reason(caught: pytest.ExceptionInfo[ValidationError]) -> str:
    return caught.value.reason_code


def test_plc_h1_genesis_did_mismatch_refuses(vectors) -> None:
    evidence = _history(vectors, "modern")
    with pytest.raises(ValidationError) as caught:
        qualify_plc_history(
            replace(evidence, expected_did="did:plc:aaaaaaaaaaaaaaaaaaaaaaaa"),
            evaluated_at=_NOW,
        )
    assert _reason(caught) == "spaces_plc_genesis_did_mismatch"


def test_plc_h2_operation_cid_mutation_refuses(vectors) -> None:
    evidence = _history(vectors, "modern")
    operation = dict(decode_dag_cbor(evidence.entries[1].operation_bytes))
    operation["alsoKnownAs"] = ("at://mutated.invalid.test",)
    altered = _with_operation(evidence.entries[1], operation, retain_claimed_cid=True)
    with pytest.raises(ValidationError) as caught:
        qualify_plc_history(
            replace(evidence, entries=(evidence.entries[0], altered)),
            evaluated_at=_NOW,
        )
    assert _reason(caught) == "spaces_plc_operation_cid_mismatch"


def test_plc_h3_broken_prev_link_refuses(vectors) -> None:
    evidence = _history(vectors, "modern")
    operation = dict(decode_dag_cbor(evidence.entries[1].operation_bytes))
    operation["prev"] = "bafyreiaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    altered = _with_operation(evidence.entries[1], operation)
    with pytest.raises(ValidationError) as caught:
        qualify_plc_history(
            replace(evidence, entries=(evidence.entries[0], altered)),
            evaluated_at=_NOW,
        )
    assert _reason(caught) == "spaces_plc_prev_unqualified"


def test_plc_h4_valid_but_unauthorized_signer_refuses(vectors) -> None:
    evidence = _history(vectors, "modern")
    altered = _hostile(vectors, "verificationKeyUpdate")
    with pytest.raises(ValidationError) as caught:
        qualify_plc_history(
            replace(evidence, entries=(*evidence.entries[:2], altered)),
            evaluated_at=_NOW,
        )
    assert _reason(caught) == "spaces_plc_unauthorized_signer"


def test_plc_h5_removed_rotation_key_cannot_authorize_later_update(vectors) -> None:
    evidence = _history(vectors, "modern")
    candidate = _hostile(vectors, "oldRemovedKeyUpdate")
    with pytest.raises(ValidationError) as caught:
        qualify_plc_history(
            replace(evidence, entries=(*evidence.entries[:2], candidate)),
            evaluated_at=_NOW,
        )
    assert _reason(caught) == "spaces_plc_unauthorized_signer"


def test_plc_h6_verification_method_key_is_not_rotation_authority(vectors) -> None:
    evidence = _history(vectors, "modern")
    candidate = _hostile(vectors, "verificationKeyUpdate")
    with pytest.raises(ValidationError) as caught:
        qualify_plc_history(
            replace(evidence, entries=(*evidence.entries[:2], candidate)),
            evaluated_at=_NOW,
        )
    assert _reason(caught) == "spaces_plc_unauthorized_signer"


def test_plc_h7_lower_priority_key_cannot_nullify_higher_branch(vectors) -> None:
    evidence = _history(vectors, "recovery")
    entries = (
        evidence.entries[0],
        _hostile(vectors, "recoveryHighBranch"),
        _hostile(vectors, "recoveryLowFork"),
    )
    with pytest.raises(ValidationError) as caught:
        qualify_plc_history(replace(evidence, entries=entries), evaluated_at=_NOW)
    assert _reason(caught) == "spaces_plc_recovery_priority"


def test_plc_h8_recovery_outside_directory_time_window_refuses(vectors) -> None:
    evidence = _history(vectors, "recovery")
    late = replace(
        evidence.entries[-1],
        directory_created_at=evidence.entries[1].directory_created_at
        + timedelta(hours=73),
    )
    with pytest.raises(ValidationError) as caught:
        qualify_plc_history(
            replace(evidence, entries=(*evidence.entries[:-1], late)),
            evaluated_at=_NOW,
        )
    assert _reason(caught) == "spaces_plc_recovery_window"


def test_plc_h9_directory_current_document_cannot_override_history(vectors) -> None:
    evidence = _history(vectors, "modern")
    summary = json.dumps(
        {"id": evidence.expected_did, "service": []}, separators=(",", ":")
    ).encode()
    with pytest.raises(ValidationError) as caught:
        qualify_plc_history(
            replace(evidence, current_document_bytes=summary), evaluated_at=_NOW
        )
    assert _reason(caught) == "spaces_plc_current_document_disagreement"


def test_directory_nullification_labels_are_checked_not_trusted(vectors) -> None:
    evidence = _history(vectors, "recovery")
    mislabeled = replace(evidence.entries[1], directory_nullified=False)
    with pytest.raises(ValidationError) as caught:
        qualify_plc_history(
            replace(
                evidence,
                entries=(evidence.entries[0], mislabeled, *evidence.entries[2:]),
            ),
            evaluated_at=_NOW,
        )
    assert _reason(caught) == "spaces_plc_nullification_mismatch"


def test_plc_h10_omitted_required_operation_refuses(vectors) -> None:
    evidence = _history(vectors, "modern")
    with pytest.raises(ValidationError) as caught:
        qualify_plc_history(
            replace(evidence, entries=(evidence.entries[0], evidence.entries[2])),
            evaluated_at=_NOW,
        )
    assert _reason(caught) == "spaces_plc_prev_unqualified"


def test_plc_h11_supplied_array_order_is_provenance_not_ancestry(vectors) -> None:
    evidence = _history(vectors, "modern")
    reversed_evidence = replace(evidence, entries=tuple(reversed(evidence.entries)))
    result = qualify_plc_history(reversed_evidence, evaluated_at=_NOW)

    assert result.receipt.supplied_operation_cids == tuple(
        reversed(result.receipt.active_operation_cids)
    )
    assert tuple(
        item.supplied_ordinal for item in result.receipt.authorized_operations
    ) == (
        2,
        1,
        0,
    )


def test_plc_h12_tombstone_cannot_be_extended(vectors) -> None:
    evidence = _history(vectors, "tombstone")
    bypass = _hostile(vectors, "tombBypass")
    with pytest.raises(ValidationError) as caught:
        qualify_plc_history(
            replace(evidence, entries=(*evidence.entries, bypass)), evaluated_at=_NOW
        )
    assert _reason(caught) == "spaces_plc_tombstone_bypass"


def test_plc_h13_legacy_genesis_fails_closed_or_qualifies_explicitly(vectors) -> None:
    evidence = _history(vectors, "legacy")
    result = qualify_plc_history(evidence, evaluated_at=_NOW)

    assert result.receipt.used_legacy_genesis is True
    assert "legacy_create_genesis_normalized" in result.receipt.verified_claims


@pytest.mark.parametrize(
    "field_name",
    [
        "complete_history",
        "directory_honest",
        "globally_current",
        "governance_authority",
    ],
)
def test_plc_h14_authority_relabeling_refuses(vectors, field_name: str) -> None:
    result = qualify_plc_history(_history(vectors, "modern"), evaluated_at=_NOW)
    with pytest.raises(ValidationError) as caught:
        replace(result.receipt, **{field_name: True})
    assert _reason(caught) == "spaces_plc_receipt_invalid"


def test_plc_h14_caller_claim_label_cannot_enter_verified_claims(vectors) -> None:
    result = qualify_plc_history(_history(vectors, "modern"), evaluated_at=_NOW)
    with pytest.raises(ValidationError) as caught:
        replace(
            result.receipt,
            verified_claims=result.receipt.verified_claims | {"complete_history"},
        )
    assert _reason(caught) == "spaces_plc_receipt_invalid"


def test_cross_h1_method_receipts_are_not_interchangeable(vectors) -> None:
    result = qualify_plc_history(_history(vectors, "modern"), evaluated_at=_NOW)
    assert result.resolved_document is not None
    with pytest.raises(ValidationError) as caught:
        require_resolution_method(result.resolved_document, DidResolutionMethod.WEB)
    assert _reason(caught) == "spaces_did_resolution_method_mismatch"
