from __future__ import annotations

import sys

import pytest

from community_model import AuthorizationError, WriteFailedError
from communityd.spaces_alpha_transport import (
    CommandSpacesAlphaWriter,
    FileAuthorizationOccurrenceStore,
    RuntimeCredentialReference,
)

DIGEST = "sha256:" + "a" * 64
CID = "bafyreicl6ujc6ncfktctxxroxognfn7d2fqavvrryoc2lv6m4i6hpbkfti"
SPACE = "at://did:plc:authority/space/type/self"
ACTOR = "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb"
COLLECTION = "net.sp00ky.juniper-pds.authority.juniperAdmission"


def test_consumption_store_persists_replay_refusal(tmp_path) -> None:
    path = tmp_path / "authority" / "used.txt"
    FileAuthorizationOccurrenceStore(path).consume(DIGEST)
    with pytest.raises(AuthorizationError, match="replay"):
        FileAuthorizationOccurrenceStore(path).consume(DIGEST)
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_command_writer_sends_one_bounded_record_and_accepts_redacted_result() -> None:
    program = (
        "import json,sys; v=json.load(sys.stdin); "
        "u=f\"{v['space']}/{v['actorDid']}/{v['collection']}/{v['rkey']}\"; "
        f"print(json.dumps({{'uri':u,'cid':'{CID}','created':True}}))"
    )
    writer = CommandSpacesAlphaWriter((sys.executable, "-c", program))
    outcome = writer.create_immutable(
        space_uri=SPACE,
        repo_did=ACTOR,
        collection=COLLECTION,
        rkey="a" * 64,
        record={"$type": COLLECTION},
    )
    assert outcome.created is True
    assert outcome.uri == f"{SPACE}/{ACTOR}/{COLLECTION}/{'a' * 64}"


def test_command_failure_and_secret_shaped_extra_output_refuse() -> None:
    failed = CommandSpacesAlphaWriter((sys.executable, "-c", "raise SystemExit(1)"))
    with pytest.raises(WriteFailedError):
        failed.create_immutable(
            space_uri=SPACE,
            repo_did=ACTOR,
            collection=COLLECTION,
            rkey="a" * 64,
            record={"$type": COLLECTION},
        )
    extra = CommandSpacesAlphaWriter(
        (
            sys.executable,
            "-c",
            "import json; print(json.dumps({'uri':'x','cid':'y','created':True,'access_token':'no'}))",
        )
    )
    with pytest.raises(WriteFailedError, match="invalid output"):
        extra.create_immutable(
            space_uri=SPACE,
            repo_did=ACTOR,
            collection=COLLECTION,
            rkey="a" * 64,
            record={"$type": COLLECTION},
        )


def test_runtime_reference_checks_presence_without_reading_session_files(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "oauth"
    runtime.mkdir()
    (runtime / "opaque").write_text("synthetic-secret", encoding="utf8")
    monkeypatch.setenv("JUNIPER_COMMUNITYD_RUNTIME_DIR", str(runtime))
    provider = RuntimeCredentialReference(
        expected_reference="runtime://community-oauth",
        environment_key="JUNIPER_COMMUNITYD_RUNTIME_DIR",
    )
    assert provider.require("runtime://community-oauth") == "runtime://community-oauth"
    assert (runtime / "opaque").read_text(encoding="utf8") == "synthetic-secret"
