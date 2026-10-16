from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest

from community_model import ValidationError
from community_model.dag_cbor import encode_dag_cbor
from communitywatch_spaces_alpha import (
    DidInterpretationProfile,
    OperationSourceContext,
    PlcAuditEntry,
    PlcHistoryEvidence,
    QualificationSourceContext,
    SpaceIdentity,
    acquire_repo_transition_candidate,
    extract_space_repo_evidence,
    parse_list_repo_ops_page,
    qualify_did_document,
    qualify_plc_history,
    qualify_repo_state,
    verification_key_bytes,
)

_FIXTURE_DIR = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "spaces-alpha"
    / "reference"
)
_MANIFEST = _FIXTURE_DIR / "sa9e-hosted-alpha.json"


def _load() -> tuple[dict[str, object], bytes, bytes]:
    manifest = json.loads(_MANIFEST.read_bytes())
    get_repo = manifest["getRepo"]
    list_ops = manifest["listRepoOps"]
    assert isinstance(get_repo, dict) and isinstance(list_ops, dict)
    car = base64.b64decode(
        (_FIXTURE_DIR / str(get_repo["bodyFile"])).read_bytes().strip(), validate=True
    )
    ops = base64.b64decode(
        (_FIXTURE_DIR / str(list_ops["bodyFile"])).read_bytes().strip(), validate=True
    )
    return manifest, car, ops


def _identity(manifest: dict[str, object]):
    raw_entries = manifest["plcAudit"]
    assert isinstance(raw_entries, list)
    entries = []
    for value in raw_entries:
        assert isinstance(value, dict) and isinstance(value["operation"], dict)
        entries.append(
            PlcAuditEntry(
                encode_dag_cbor(value["operation"]),
                str(value["cid"]),
                datetime.fromisoformat(str(value["createdAt"]).replace("Z", "+00:00")),
                bool(value["nullified"]),
            )
        )
    identity = manifest["identity"]
    qualification = manifest["identityQualification"]
    assert isinstance(identity, dict) and isinstance(qualification, dict)
    observed = datetime.fromisoformat(
        str(manifest["observedAt"]).replace("Z", "+00:00")
    )
    qualified_at = datetime.fromisoformat(
        str(qualification["qualifiedAt"]).replace("Z", "+00:00")
    )
    plc = qualify_plc_history(
        PlcHistoryEvidence(
            str(identity["did"]),
            tuple(entries),
            "hosted-smoke:plc-directory-audit",
        ),
        evaluated_at=qualified_at,
    )
    assert plc.resolved_document is not None
    host = qualify_did_document(
        plc.resolved_document.to_sa9b_input(),
        profile=DidInterpretationProfile.ACCOUNT_REPO_HOST,
        qualified_at=qualified_at,
    )
    key = qualify_did_document(
        plc.resolved_document.to_sa9b_input(),
        profile=DidInterpretationProfile.ACCOUNT_SIGNING_KEY,
        qualified_at=qualified_at,
    )
    return plc, host, key, observed


def _state(manifest: dict[str, object], car: bytes):
    identity = manifest["identity"]
    get_repo = manifest["getRepo"]
    qualification = manifest["identityQualification"]
    assert all(isinstance(value, dict) for value in (identity, get_repo, qualification))
    plc, host, key, observed = _identity(manifest)
    acquisition_ref = str(get_repo["acquisitionReceiptId"])
    extraction = extract_space_repo_evidence(
        car, source_vector_identifier=acquisition_ref
    )
    source = QualificationSourceContext(
        repo_host=str(identity["repoHost"]),
        author_key_ref=str(qualification["accountKeyBindingReceiptId"]),
        author_key_binding_method="sa9c:did:plc+sa9b:account-key",
        evidence_ref=acquisition_ref,
        writer_discovery_ref="explicit-writer-claim-required-for-admission",
    )
    state = qualify_repo_state(
        extraction.evidence,
        expected_space=SpaceIdentity.parse(str(identity["space"])),
        expected_author_did=str(identity["did"]),
        author_public_key=verification_key_bytes(key),
        signature_algorithm="ES256K",
        source=source,
        verified_at=observed,
    )
    return plc, host, key, extraction, state, observed


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {str(key).lower() for key in value} | set().union(
            *(_keys(item) for item in value.values()), set()
        )
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value), set())
    return set()


def test_hosted_get_repo_replays_through_unchanged_sa9c_sa9b_sa2_sa1() -> None:
    manifest, car, _ = _load()
    get_repo = manifest["getRepo"]
    qualification = manifest["identityQualification"]
    assert isinstance(get_repo, dict) and isinstance(qualification, dict)

    assert len(car) == get_repo["bodyLength"]
    assert hashlib.sha256(car).hexdigest() == get_repo["bodySha256"]
    plc, host, key, extraction, state, _ = _state(manifest, car)
    assert plc.receipt.receipt_id == qualification["plcReceiptId"]
    assert host.receipt_id == qualification["repoHostBindingReceiptId"]
    assert key.receipt_id == qualification["accountKeyBindingReceiptId"]
    assert list(extraction.car.roots) == get_repo["orderedRoots"]
    assert [block.cid for block in extraction.car.blocks] == get_repo["orderedBlocks"]
    assert state.commit.rev == get_repo["repoRev"]
    assert state.commit.state_hash.hex() == get_repo["stateHash"]
    assert len(state.records) == get_repo["recordCount"] == 1
    assert state.records[0].identity.uri == get_repo["recordUri"]
    assert state.records[0].cid == get_repo["recordCid"]
    assert state.receipts[0].receipt_id == get_repo["sa1ReceiptId"]
    assert state.receipts[0].governance_authority is False


def test_hosted_list_repo_ops_replays_through_unchanged_sa5_without_history() -> None:
    manifest, car, ops_bytes = _load()
    list_ops = manifest["listRepoOps"]
    identity = manifest["identity"]
    assert isinstance(list_ops, dict) and isinstance(identity, dict)
    assert len(ops_bytes) == list_ops["bodyLength"]
    assert hashlib.sha256(ops_bytes).hexdigest() == list_ops["bodySha256"]
    _, _, _, _, state, observed = _state(manifest, car)
    page = parse_list_repo_ops_page(
        json.loads(ops_bytes),
        ordinal=0,
        request_since=state.commit.rev,
        request_cursor=None,
        received_at=observed,
    )
    acquisition = acquire_repo_transition_candidate(
        (page,),
        source_state=state,
        context=OperationSourceContext(
            SpaceIdentity.parse(str(identity["space"])),
            str(identity["did"]),
            str(identity["repoHost"]),
            "hosted-smoke:authenticated-listRepoOps",
            observed,
        ),
    )

    assert acquisition.status.value == list_ops["sa5Status"]
    assert acquisition.status.value == "empty_terminal_page"
    assert acquisition.transition is None
    assert acquisition.pagination_chain_closed is True
    assert acquisition.complete_history is False
    assert acquisition.authorization is False
    assert list_ops["transitionQualified"] is False


def test_hosted_live_receipts_preserve_claim_boundaries_and_no_secrets() -> None:
    manifest, _, _ = _load()
    claims = manifest["claims"]
    authentication = manifest["authenticationQualification"]
    compatibility = manifest["oauthCompatibility"]
    get_repo = manifest["getRepo"]
    assert all(
        isinstance(value, dict)
        for value in (claims, authentication, compatibility, get_repo)
    )

    assert manifest["secretMaterialPresent"] is False
    assert authentication["liveHostAcceptedBoundedRequests"] is True
    assert str(authentication["delegationRequestBindingReceiptId"]).startswith(
        "sha256:"
    )
    assert authentication["communityStanding"] is False
    assert authentication["governanceAuthority"] is False
    assert compatibility["pinnedBulletinDefaultObservedCurve"] == "secp256k1"
    assert compatibility["sa9dAQualifiedCurve"] == "P-256"
    assert get_repo["endpointBindingEstablished"] is True
    assert str(get_repo["requestBindingReceiptId"]).startswith("sha256:")
    assert get_repo["admissionCount"] == 0
    assert claims["completeHistory"] is False
    assert claims["effectAuthorized"] is False
    assert not (
        _keys(manifest)
        & {
            "access_token",
            "authorization",
            "cookie",
            "delegation_token",
            "dpop_private_key",
            "private_key",
            "refresh_token",
            "set-cookie",
        }
    )


def test_hosted_car_mutation_and_success_relabel_do_not_bypass_sa2_sa1() -> None:
    manifest, car, _ = _load()
    altered = bytearray(car)
    altered[-1] ^= 1
    with pytest.raises(ValidationError) as error:
        _state(manifest, bytes(altered))
    assert error.value.reason_code == "spaces_car_block_cid_mismatch"

    relabelled = deepcopy(manifest)
    claims = relabelled["claims"]
    identity = relabelled["identity"]
    assert isinstance(claims, dict) and isinstance(identity, dict)
    claims["governanceAuthority"] = True
    identity["space"] = (
        "at://did:plc:ccqpqqfk4ihtbimtbomhnjle/space/my.bulletin.board/other"
    )
    with pytest.raises(ValidationError) as error:
        _state(relabelled, car)
    assert error.value.reason_code in {"spaces_mac_invalid", "spaces_signature_invalid"}
