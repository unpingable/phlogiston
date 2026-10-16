from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from community_model import ValidationError, canonical_json_bytes
from community_model.dag_cbor import encode_dag_cbor
from community_space_model import SpaceIdentity
from communitywatch_live import QualifiedRepoIdentity, QualifiedSpaceAuthority
from communitywatch_live.supervisor import (
    LiveSupervisor,
    SupervisorConfig,
    _credential_exchange_origin,
    _discover_authors,
    _l8_receipt,
    _qualified_history,
    _retain_receipt,
)
from communitywatch_spaces_alpha import (
    DidInterpretationProfile,
    PlcAuditEntry,
    PlcHistoryEvidence,
    qualify_did_document,
    qualify_plc_history,
    verification_key_bytes,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests/fixtures/spaces-alpha/reference"
MANIFEST = FIXTURES / "sa9e-hosted-alpha.json"
DIGEST = "sha256:" + "a" * 64


def _load() -> tuple[dict[str, object], bytes]:
    manifest = json.loads(MANIFEST.read_bytes())
    assert isinstance(manifest, dict)
    get_repo = manifest["getRepo"]
    assert isinstance(get_repo, dict)
    body = base64.b64decode(
        (FIXTURES / str(get_repo["bodyFile"])).read_bytes().strip(), validate=True
    )
    return manifest, body


def _space(uri: str) -> SpaceIdentity:
    parts = uri.removeprefix("at://").split("/")
    assert parts[1] == "space"
    return SpaceIdentity(parts[0], parts[2], parts[3])


def _config(tmp_path: Path, space: SpaceIdentity, actor: str) -> SupervisorConfig:
    return SupervisorConfig(
        space,
        actor,
        tmp_path / "actions.json",
        tmp_path / "spool",
        tmp_path / "authority",
        tmp_path / "evidence",
        tmp_path / "projection",
        ("false",),
    )


def _receipt(
    manifest: dict[str, object], body: bytes, body_file: str
) -> dict[str, object]:
    identity = manifest["identity"]
    get_repo = manifest["getRepo"]
    assert isinstance(identity, dict) and isinstance(get_repo, dict)
    authority = str(identity["repoHost"])
    without_id: dict[str, object] = {
        "method": "juniper-communitywatch-alpha/1",
        "requestId": "hosted-retained-1",
        "artifactKind": "get_repo",
        "space": identity["space"],
        "repoDid": identity["did"],
        "requestedUrl": get_repo["requestedUrl"],
        "observedAt": manifest["observedAt"],
        "status": 200,
        "contentType": "application/vnd.ipld.car",
        "bodySha256": hashlib.sha256(body).hexdigest(),
        "bodyLength": len(body),
        "bodyFile": body_file,
        "delegationSha256": "1" * 64,
        "credentialSha256": "2" * 64,
        "dpopKeyThumbprint": "fixture-public-thumbprint",
        "credentialExchangeProofSha256": "3" * 64,
        "artifactProofSha256": "4" * 64,
        "proofClaimsSelfVerified": True,
        "attempts": [
            {
                "ordinal": 0,
                "method": "POST",
                "url": "https://oauth.invalid/token",
                "status": 200,
                "purpose": "oauth-library",
            },
            {
                "ordinal": 1,
                "method": "POST",
                "url": f"{authority}/xrpc/com.atproto.space.getSpaceCredential",
                "status": 200,
                "purpose": "credential-exchange",
            },
            {
                "ordinal": 2,
                "method": "GET",
                "url": get_repo["requestedUrl"],
                "status": 200,
                "purpose": "artifact",
            },
        ],
        "automaticArtifactRetries": 0,
        "redirectsFollowed": 0,
        "verifiedClaims": [
            "exact_http_response_bytes",
            "credential_bound_dpop_request",
        ],
        "explicitNonClaims": [
            "artifact_validity",
            "source_authority",
            "did_resolution",
            "space_admission",
            "community_standing",
            "governance_authority",
            "currentness",
            "complete_history",
        ],
    }
    return {
        "receiptId": "sha256:"
        + hashlib.sha256(canonical_json_bytes(without_id)).hexdigest(),
        **without_id,
    }


def _qualified_bindings(
    manifest: dict[str, object],
) -> tuple[QualifiedRepoIdentity, QualifiedSpaceAuthority]:
    identity = manifest["identity"]
    raw_entries = manifest["plcAudit"]
    assert isinstance(identity, dict) and isinstance(raw_entries, list)
    entries = tuple(
        PlcAuditEntry(
            encode_dag_cbor(item["operation"]),
            str(item["cid"]),
            datetime.fromisoformat(str(item["createdAt"]).replace("Z", "+00:00")),
            bool(item["nullified"]),
        )
        for item in raw_entries
        if isinstance(item, dict) and isinstance(item.get("operation"), dict)
    )
    when = datetime.fromisoformat(str(manifest["observedAt"]).replace("Z", "+00:00"))
    plc = qualify_plc_history(
        PlcHistoryEvidence(str(identity["did"]), entries, "fixture:plc"),
        evaluated_at=when,
    )
    assert plc.resolved_document is not None
    key = qualify_did_document(
        plc.resolved_document.to_sa9b_input(),
        profile=DidInterpretationProfile.ACCOUNT_SIGNING_KEY,
        qualified_at=when,
    )
    repo = QualifiedRepoIdentity(
        str(identity["did"]),
        str(identity["repoHost"]),
        verification_key_bytes(key),
        "ES256K",
        DIGEST,
        DIGEST,
        DIGEST,
        DIGEST,
    )
    authority = QualifiedSpaceAuthority(
        str(identity["did"]),
        str(identity["repoHost"]),
        DIGEST,
        DIGEST,
        DIGEST,
    )
    return repo, authority


def test_retained_hosted_l8_spool_replays_through_sa2_sa1(
    tmp_path: Path,
) -> None:
    manifest, body = _load()
    identity = manifest["identity"]
    qualification = manifest["identityQualification"]
    assert isinstance(identity, dict) and isinstance(qualification, dict)
    config = _config(tmp_path, _space(str(identity["space"])), str(identity["did"]))
    config.artifact_spool.mkdir()
    body_file = "hosted-retained-1.car"
    (config.artifact_spool / body_file).write_bytes(body)
    receipt = _receipt(manifest, body, body_file)
    (config.artifact_spool / "hosted-retained-1.receipt.json").write_bytes(
        canonical_json_bytes(receipt) + b"\n"
    )

    # Key material is independently selected from retained PLC evidence before
    # the history path below performs unchanged SA2 and SA1 qualification.
    repo, authority = _qualified_bindings(manifest)
    history = _qualified_history(config, repo, authority, expected_space=config.space)
    assert len(history.snapshots) == 1
    assert history.latest.state.commit.rev == manifest["getRepo"]["repoRev"]
    assert history.latest.state.receipts[0].governance_authority is False


def test_l8_receipt_refuses_body_authority_and_space_substitution(
    tmp_path: Path,
) -> None:
    manifest, body = _load()
    identity = manifest["identity"]
    assert isinstance(identity, dict)
    config = _config(tmp_path, _space(str(identity["space"])), str(identity["did"]))
    config.artifact_spool.mkdir()
    body_file = "artifact.car"
    (config.artifact_spool / body_file).write_bytes(body)
    receipt = _receipt(manifest, body, body_file)
    receipt_path = config.artifact_spool / "artifact.receipt.json"
    receipt_path.write_bytes(canonical_json_bytes(receipt) + b"\n")
    assert (
        _l8_receipt(receipt_path, config.artifact_spool)["space"] == identity["space"]
    )

    (config.artifact_spool / body_file).write_bytes(body + b"x")
    with pytest.raises(ValidationError, match="spool bytes differ"):
        _l8_receipt(receipt_path, config.artifact_spool)

    changed = _receipt(manifest, body, body_file)
    attempts = changed["attempts"]
    assert isinstance(attempts, list) and isinstance(attempts[1], dict)
    attempts[1]["url"] = "https://substitute.invalid/xrpc/getCredential"
    without_id = dict(changed)
    without_id.pop("receiptId")
    changed["receiptId"] = (
        "sha256:" + hashlib.sha256(canonical_json_bytes(without_id)).hexdigest()
    )
    assert _credential_exchange_origin(changed) == "https://substitute.invalid"

    (config.artifact_spool / body_file).write_bytes(body)
    receipt_path.write_bytes(canonical_json_bytes(changed) + b"\n")
    repo, expected_authority = _qualified_bindings(manifest)
    with pytest.raises(ValidationError, match="credential exchange origin differs"):
        _qualified_history(
            config, repo, expected_authority, expected_space=config.space
        )


def test_receipt_custody_is_immutable_and_non_authoritative(tmp_path: Path) -> None:
    payload = {
        "version": "juniper-live-supervisor/1",
        "classification": "snapshot_seed",
        "completeHistory": False,
        "governanceAuthority": False,
    }
    receipt_id = _retain_receipt(tmp_path, payload)
    assert _retain_receipt(tmp_path, payload) == receipt_id
    retained = json.loads(next(tmp_path.glob("*.json")).read_bytes())
    assert retained["completeHistory"] is False
    assert retained["governanceAuthority"] is False


def test_l8_receipt_refuses_symlink_and_duplicate_json(tmp_path: Path) -> None:
    manifest, body = _load()
    identity = manifest["identity"]
    assert isinstance(identity, dict)
    config = _config(tmp_path, _space(str(identity["space"])), str(identity["did"]))
    config.artifact_spool.mkdir()
    outside = tmp_path / "outside.car"
    outside.write_bytes(body)
    body_file = "linked.car"
    (config.artifact_spool / body_file).symlink_to(outside)
    receipt = _receipt(manifest, body, body_file)
    receipt_path = config.artifact_spool / "linked.receipt.json"
    receipt_path.write_bytes(canonical_json_bytes(receipt) + b"\n")
    with pytest.raises(ValidationError, match="not regular"):
        _l8_receipt(receipt_path, config.artifact_spool)

    receipt_path.write_bytes(b'{"receiptId":"a","receiptId":"b"}')
    with pytest.raises(ValidationError, match="ambiguous JSON"):
        _l8_receipt(receipt_path, config.artifact_spool)


def test_empty_discovery_is_a_bounded_no_publication_run(tmp_path: Path) -> None:
    manifest, _ = _load()
    identity = manifest["identity"]
    assert isinstance(identity, dict)
    config = _config(tmp_path, _space(str(identity["space"])), str(identity["did"]))

    class _Unused:
        def qualify(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("identity qualification must not run without authors")

        def qualify_space_authority(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("identity qualification must not run without authors")

        def acquire(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("acquisition must not run without authors")

    result = LiveSupervisor(  # type: ignore[arg-type]
        config,
        _Unused(),
        _Unused(),
        clock=lambda: datetime(2026, 8, 24, 12, tzinfo=UTC),
    ).run_once()
    assert result.published is False
    assert result.discovered_authors == ()
    assert result.qualified_repositories == ()
    assert result.explicit_non_claims[-1] == "human_comprehension"
    assert not config.projection_directory.exists()


def test_author_discovery_is_hint_only_and_refuses_ambiguous_shape(
    tmp_path: Path,
) -> None:
    actions = tmp_path / "actions.json"
    actions.write_text(
        json.dumps(
            {
                "version": "juniper-author-actions/1",
                "items": [
                    {"authorDid": "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb"},
                    {"authorDid": "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa"},
                    {"authorDid": "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb"},
                ],
            }
        )
    )
    assert _discover_authors(actions) == (
        "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa",
        "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb",
    )

    actions.write_text(
        json.dumps(
            {
                "version": "juniper-author-actions/1",
                "items": [],
                "completeHistory": True,
            }
        )
    )
    with pytest.raises(ValidationError, match="fields differ"):
        _discover_authors(actions)
