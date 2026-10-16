from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest

from community_model import ValidationError
from communitywatch_spaces_alpha import (
    REFERENCE_COMMIT,
    QualificationSourceContext,
    SpaceIdentity,
    extract_space_repo_evidence,
    qualify_repo_state,
)

_REFERENCE_DIR = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "spaces-alpha"
    / "reference"
)
_MANIFEST = _REFERENCE_DIR / "sa9e-local-pds.json"
_CAR = _REFERENCE_DIR / "sa9e-local-pds.car"


def _load() -> tuple[dict[str, object], bytes]:
    return json.loads(_MANIFEST.read_text(encoding="utf-8")), _CAR.read_bytes()


def _source(manifest: dict[str, object]) -> QualificationSourceContext:
    local = manifest["localQualification"]
    assert isinstance(local, dict)
    raw = local["sourceContext"]
    assert isinstance(raw, dict)
    return QualificationSourceContext(
        repo_host=str(raw["repoHost"]),
        author_key_ref=str(raw["authorKeyRef"]),
        author_key_binding_method=str(raw["authorKeyBindingMethod"]),
        evidence_ref=str(raw["evidenceRef"]),
    )


def _qualify(manifest: dict[str, object], car: bytes):
    local = manifest["localQualification"]
    assert isinstance(local, dict)
    extraction = extract_space_repo_evidence(
        car,
        source_vector_identifier=str(local["sourceVectorIdentifier"]),
    )
    qualified = qualify_repo_state(
        extraction.evidence,
        expected_space=SpaceIdentity.parse(manifest["space"]),
        expected_author_did=str(manifest["authorDid"]),
        author_public_key=base64.b64decode(
            str(manifest["authorPublicKeyB64"]), validate=True
        ),
        signature_algorithm=str(manifest["signatureAlgorithm"]),
        source=_source(manifest),
        verified_at=datetime.fromisoformat(
            str(local["verifiedAt"]).replace("Z", "+00:00")
        ),
    )
    return extraction, qualified


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {str(key).lower() for key in value} | set().union(
            *(_keys(item) for item in value.values()), set()
        )
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value), set())
    return set()


def test_local_reference_pds_car_qualifies_through_unchanged_sa2_sa1() -> None:
    manifest, car = _load()
    upstream = manifest["upstream"]
    acquisition = manifest["acquisition"]
    local = manifest["localQualification"]
    repo_state = manifest["repoState"]
    claims = manifest["claims"]
    assert all(
        isinstance(item, dict)
        for item in (upstream, acquisition, local, repo_state, claims)
    )

    assert manifest["format"] == "spaces-alpha-sa9e-local-pds-v1"
    assert upstream["commit"] == REFERENCE_COMMIT
    assert upstream["package"] == "@atproto/space"
    assert upstream["packageVersion"] == "0.0.1"
    assert acquisition["method"] == "GET"
    assert acquisition["endpoint"] == "com.atproto.space.getRepo"
    assert acquisition["status"] == 200
    assert acquisition["authenticated"] is True
    assert acquisition["credentialsPersisted"] is False
    assert acquisition["bodyLength"] == len(car)
    assert acquisition["bodySha256"] == hashlib.sha256(car).hexdigest()

    extraction, qualified = _qualify(manifest, car)
    assert list(extraction.car.roots) == local["orderedRoots"]
    assert [block.cid for block in extraction.car.blocks] == local["orderedBlocks"]
    assert qualified.space.uri == manifest["space"]
    assert qualified.author_did == manifest["authorDid"]
    assert qualified.commit.rev == repo_state["rev"]
    assert len(qualified.records) == repo_state["recordCount"] == 2
    assert [receipt.receipt_id for receipt in qualified.receipts] == local["receiptIds"]
    assert all(receipt.governance_authority is False for receipt in qualified.receipts)
    assert local["networkSourceIdentityQualified"] is False
    assert claims == {
        "referenceCarVerified": True,
        "governanceAuthority": False,
        "completeHistory": False,
        "currentForever": False,
    }


def test_local_reference_manifest_retains_no_secret_material() -> None:
    manifest, _ = _load()
    assert not (
        _keys(manifest)
        & {
            "access_token",
            "authorization",
            "cookie",
            "credential",
            "delegation_token",
            "dpop_private_key",
            "private_key",
            "refresh_token",
            "set-cookie",
        }
    )


def test_local_reference_car_mutation_is_not_rescued_by_acquisition_claims() -> None:
    manifest, car = _load()
    altered = bytearray(car)
    altered[-1] ^= 1

    with pytest.raises(ValidationError) as caught:
        _qualify(manifest, bytes(altered))

    assert caught.value.reason_code == "spaces_car_block_cid_mismatch"


def test_reference_success_label_cannot_override_wrong_space_binding() -> None:
    manifest, car = _load()
    relabelled = deepcopy(manifest)
    relabelled["space"] = (
        "at://did:plc:kol4ljbu2336zmxh556ukihg/space/com.example.group/another-space"
    )
    claims = relabelled["claims"]
    assert isinstance(claims, dict)
    claims["referenceCarVerified"] = True
    claims["governanceAuthority"] = True

    with pytest.raises(ValidationError) as caught:
        _qualify(relabelled, car)

    assert caught.value.reason_code in {
        "spaces_mac_invalid",
        "spaces_signature_invalid",
    }


def test_live_loopback_location_is_not_promoted_to_source_identity() -> None:
    manifest, car = _load()
    acquisition = manifest["acquisition"]
    local = manifest["localQualification"]
    assert isinstance(acquisition, dict) and isinstance(local, dict)
    source = _source(manifest)
    _, qualified = _qualify(manifest, car)

    assert str(acquisition["requestedUrl"]).startswith("http://localhost:")
    assert source.repo_host == "https://reference-local-pds.invalid"
    assert local["networkSourceIdentityQualified"] is False
    assert all(
        receipt.unverified_context["repoHost"] == source.repo_host
        for receipt in qualified.receipts
    )
