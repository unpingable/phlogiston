from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from communityd.spaces_alpha_cli import main

CID = "bafyreicl6ujc6ncfktctxxroxognfn7d2fqavvrryoc2lv6m4i6hpbkfti"
DIGEST = "sha256:" + "a" * 64
SPACE = "at://did:plc:dddddddddddddddddddddddd/space/net.sp00ky.juniper-pds.authority.juniperCommunity/self"
ACTOR = "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb"


def test_cli_writes_once_and_replay_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime = tmp_path / "oauth"
    runtime.mkdir()
    monkeypatch.setenv("JUNIPER_COMMUNITYD_RUNTIME_DIR", str(runtime))
    program = (
        "import json,sys; v=json.load(sys.stdin); "
        "u=f\"{v['space']}/{v['actorDid']}/{v['collection']}/{v['rkey']}\"; "
        f"print(json.dumps({{'uri':u,'cid':'{CID}','created':True}}))"
    )
    config = tmp_path / "communityd.toml"
    config.write_text(
        "\n".join(
            (
                'space_authority_did = "did:plc:dddddddddddddddddddddddd"',
                'space_type = "net.sp00ky.juniper-pds.authority.juniperCommunity"',
                'space_skey = "self"',
                f'community_actor_did = "{ACTOR}"',
                'administrator_did = "did:plc:cccccccccccccccccccccccc"',
                f"allowed_uid = {os.geteuid()}",
                'credential_ref = "runtime://community-oauth"',
                f"writer_command = {json.dumps([sys.executable, '-c', program])}",
                f'occurrence_store = "{tmp_path / "used.txt"}"',
                "request_timeout_ms = 5000",
            )
        ),
        encoding="utf8",
    )
    request = tmp_path / "request.json"
    request.write_text(json.dumps(admit_request()), encoding="utf8")
    assert main(["--config", str(config), "--request", str(request)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["record"]["uri"].startswith(SPACE + f"/{ACTOR}/")
    authorization = output["authorization"]
    assert authorization["authorizationId"].startswith("sha256:")
    assert authorization["communityIdentityId"].startswith("sha256:")
    assert authorization["action"] == "admit"
    assert authorization["targetOccurrenceId"] == DIGEST
    assert authorization["moderatorDid"] == "did:plc:cccccccccccccccccccccccc"
    assert set(authorization) == {
        "authorizationId",
        "communityIdentityId",
        "decisionId",
        "moderatorDid",
        "action",
        "targetOccurrenceId",
        "authorizationBasisReceiptId",
        "authorizedAt",
        "expiresAt",
        "provenanceReceiptId",
    }

    assert main(["--config", str(config), "--request", str(request)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"error": "communityd_spaces_alpha_refused"}


def test_cli_cross_collection_refuses_without_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime = tmp_path / "oauth"
    runtime.mkdir()
    monkeypatch.setenv("JUNIPER_COMMUNITYD_RUNTIME_DIR", str(runtime))
    marker = tmp_path / "called"
    config = tmp_path / "communityd.toml"
    config.write_text(
        "\n".join(
            (
                'space_authority_did = "did:plc:dddddddddddddddddddddddd"',
                'space_type = "net.sp00ky.juniper-pds.authority.juniperCommunity"',
                'space_skey = "self"',
                f'community_actor_did = "{ACTOR}"',
                'administrator_did = "did:plc:cccccccccccccccccccccccc"',
                f"allowed_uid = {os.geteuid()}",
                'credential_ref = "runtime://community-oauth"',
                f"writer_command = {json.dumps([sys.executable, '-c', f'from pathlib import Path; Path({str(marker)!r}).touch()'])}",
                f'occurrence_store = "{tmp_path / "used.txt"}"',
                "request_timeout_ms = 5000",
            )
        ),
        encoding="utf8",
    )
    value = admit_request()
    value["submission"]["collection"] = "evil.invalid.submission"  # type: ignore[index]
    request = tmp_path / "request.json"
    request.write_text(json.dumps(value), encoding="utf8")
    assert main(["--config", str(config), "--request", str(request)]) == 1
    capsys.readouterr()
    assert not marker.exists()


def admit_request() -> dict[str, object]:
    return {
        "action": "admit",
        "submission": {
            "authorDid": "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa",
            "collection": "net.sp00ky.juniper-pds.authority.juniperSubmission",
            "rkey": "submission",
            "cid": CID,
        },
        "subject": {
            "authorDid": "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa",
            "collection": "net.sp00ky.juniper-pds.authority.juniperPost",
            "rkey": "post",
            "cid": CID,
        },
        "submissionOccurrenceId": DIGEST,
        "sourceObservationReceiptId": DIGEST,
        "decisionId": "decision-1",
        "authorizationBasisReceiptId": DIGEST,
        "authorizationProvenanceReceiptId": DIGEST,
    }
