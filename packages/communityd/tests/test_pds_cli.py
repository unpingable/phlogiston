from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from community_model import RecordRef, admission_rkey
from communityd.cli import main
from communityd.fakepds import FakePds
from fakes_support import (
    ADMIN_DID,
    ALICE_DID,
    COMMUNITY_DID,
    POST_COLLECTION,
    SUBMISSION_COLLECTION,
    make_post,
    make_submission,
)

CANARY = "canary-app-password-eeee-ffff"
ENV_VAR = "COMMUNITYD_CLI_TEST_CREDENTIAL"


def _write_credential(tmp_path: Path, *, password: str = CANARY) -> Path:
    path = tmp_path / "credential.json"
    path.write_text(
        json.dumps({"identifier": "community.test", "app_password": password}),
        encoding="utf-8",
    )
    return path


def _write_config(tmp_path: Path, pds_url: str, *, allowed_uid: int) -> Path:
    path = tmp_path / "communityd.toml"
    path.write_text(
        f'community_did = "{COMMUNITY_DID}"\n'
        f'administrator_did = "{ADMIN_DID}"\n'
        f'community_pds_url = "{pds_url}"\n'
        f"allowed_uid = {allowed_uid}\n"
        'reader_adapter = "pds_fixed"\n'
        'ledger_adapter = "pds"\n'
        'writer_adapter = "pds"\n'
        'credential_provider = "env_file"\n'
        f'credential_ref = "env:{ENV_VAR}"\n'
        "request_timeout_ms = 2000\n"
        "max_retries = 1\n",
        encoding="utf-8",
    )
    return path


def _invoke(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _admit_argv(
    config_path: Path, submission_uri: str, submission_cid: str
) -> list[str]:
    return [
        "--config",
        str(config_path),
        "admit",
        "--submission-uri",
        submission_uri,
        "--submission-cid",
        submission_cid,
    ]


@pytest.fixture
def server() -> FakePds:
    with FakePds(
        session_did=COMMUNITY_DID, identifier="community.test", app_password=CANARY
    ) as pds:
        yield pds


@pytest.fixture
def wired(
    server: FakePds, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[FakePds, Path, tuple[str, str]]:
    credential = _write_credential(tmp_path)
    monkeypatch.setenv(ENV_VAR, str(credential))
    config_path = _write_config(tmp_path, server.url, allowed_uid=os.geteuid())
    post_ref = server.seed(ALICE_DID, POST_COLLECTION, "3jzfcijpj2z2a", make_post())
    submission_ref = server.seed(
        ALICE_DID, SUBMISSION_COLLECTION, "3jzfcijpj2z2b", make_submission(post_ref)
    )
    return server, config_path, (submission_ref.uri, submission_ref.cid)


def test_cli_admit_end_to_end_success(
    wired: tuple[FakePds, Path, tuple[str, str]],
) -> None:
    server, config_path, (uri, cid) = wired
    code, out, err = _invoke(_admit_argv(config_path, uri, cid))

    assert code == 0
    assert err == ""
    payload = json.loads(out)
    assert payload["operation"] == "created"
    assert payload["uri"].startswith(f"at://{COMMUNITY_DID}/")
    # Secret material never reaches either stream or the server request log.
    assert CANARY not in out + err
    assert server.token not in out + err
    assert all(CANARY not in entry for entry in server.requests)


def test_cli_readmit_returns_existing(
    wired: tuple[FakePds, Path, tuple[str, str]],
) -> None:
    _, config_path, (uri, cid) = wired
    first = _invoke(_admit_argv(config_path, uri, cid))
    second = _invoke(_admit_argv(config_path, uri, cid))

    assert first[0] == 0 and second[0] == 0
    first_payload = json.loads(first[1])
    second_payload = json.loads(second[1])
    assert second_payload["operation"] == "existing"
    assert (second_payload["uri"], second_payload["cid"]) == (
        first_payload["uri"],
        first_payload["cid"],
    )


def test_cli_remove_then_readmission_is_exit_5(
    wired: tuple[FakePds, Path, tuple[str, str]],
) -> None:
    server, config_path, (uri, cid) = wired
    code, out, _ = _invoke(_admit_argv(config_path, uri, cid))
    assert code == 0
    admission = json.loads(out)

    code, out, err = _invoke(
        [
            "--config",
            str(config_path),
            "remove",
            "--admission-uri",
            admission["uri"],
            "--admission-cid",
            admission["cid"],
            "--reason",
            "off-topic",
        ]
    )
    assert code == 0
    assert json.loads(out)["operation"] == "created"

    server.requests.clear()
    code, out, err = _invoke(_admit_argv(config_path, uri, cid))
    assert code == 5
    assert out == ""
    assert json.loads(err)["error"] == "unsupported_readmission"
    # The ledger reader paginated both authority collections over the PDS.
    assert any("listRecords" in entry for entry in server.requests)
    assert all(
        entry.split(" ")[1].startswith("/xrpc/com.atproto.")
        for entry in server.requests
    )


def test_cli_incompatible_rkey_occupant_is_exit_5(
    wired: tuple[FakePds, Path, tuple[str, str]],
) -> None:
    server, config_path, (uri, cid) = wired
    rkey = admission_rkey(RecordRef(uri=uri, cid=cid))
    server.seed(
        COMMUNITY_DID,
        "app.phlogiston.community.admission",
        rkey,
        {
            "$type": "app.phlogiston.community.admission",
            "submission": {"uri": uri, "cid": cid},
            "subject": {
                "uri": "at://did:web:eve.invalid/app.bsky.feed.post/3jxfaaaaaaa",
                "cid": cid,
            },
            "actor": ADMIN_DID,
            "createdAt": "2026-08-13T11:00:00Z",
        },
    )

    code, out, err = _invoke(_admit_argv(config_path, uri, cid))
    assert code == 5
    assert out == ""
    assert json.loads(err)["error"] == "immutable_conflict"


def test_cli_uid_mismatch_is_exit_3_with_zero_network(
    server: FakePds, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    credential = _write_credential(tmp_path)
    monkeypatch.setenv(ENV_VAR, str(credential))
    config_path = _write_config(tmp_path, server.url, allowed_uid=os.geteuid() + 1)

    code, out, err = _invoke(
        _admit_argv(
            config_path,
            f"at://{ALICE_DID}/{SUBMISSION_COLLECTION}/3jzfcijpj2z2b",
            "bafyreic7cldbweyx7ta42gvymb5xkglmqauaawvyxsoqmtxfowrudsavli",
        )
    )

    assert code == 3
    assert out == ""
    assert json.loads(err)["error"] == "unauthorized"
    assert server.requests == []


def test_cli_credential_env_unset_is_exit_7_with_zero_network(
    server: FakePds, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    config_path = _write_config(tmp_path, server.url, allowed_uid=os.geteuid())

    code, out, err = _invoke(
        _admit_argv(
            config_path,
            f"at://{ALICE_DID}/{SUBMISSION_COLLECTION}/3jzfcijpj2z2b",
            "bafyreic7cldbweyx7ta42gvymb5xkglmqauaawvyxsoqmtxfowrudsavli",
        )
    )

    assert code == 7
    assert out == ""
    assert json.loads(err)["error"] == "credential_unavailable"
    assert server.requests == []


def test_cli_malformed_credential_file_redacts_secret(
    server: FakePds, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text(
        '{"identifier": "community.test", "app_password": "' + CANARY, encoding="utf-8"
    )
    monkeypatch.setenv(ENV_VAR, str(broken))
    config_path = _write_config(tmp_path, server.url, allowed_uid=os.geteuid())

    code, out, err = _invoke(
        _admit_argv(
            config_path,
            f"at://{ALICE_DID}/{SUBMISSION_COLLECTION}/3jzfcijpj2z2b",
            "bafyreic7cldbweyx7ta42gvymb5xkglmqauaawvyxsoqmtxfowrudsavli",
        )
    )

    assert code == 7
    assert out == ""
    assert CANARY not in err
    assert server.requests == []


def test_cli_rejected_session_is_exit_7_and_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with FakePds(
        session_did=COMMUNITY_DID,
        identifier="community.test",
        app_password="server-side-different",
    ) as server:
        credential = _write_credential(tmp_path)
        monkeypatch.setenv(ENV_VAR, str(credential))
        config_path = _write_config(tmp_path, server.url, allowed_uid=os.geteuid())
        post_ref = server.seed(ALICE_DID, POST_COLLECTION, "3jzfcijpj2z2a", make_post())
        submission_ref = server.seed(
            ALICE_DID, SUBMISSION_COLLECTION, "3jzfcijpj2z2b", make_submission(post_ref)
        )
        code, out, err = _invoke(
            _admit_argv(config_path, submission_ref.uri, submission_ref.cid)
        )

    assert code == 7
    assert out == ""
    assert CANARY not in err
    assert server.token not in err


def test_cli_bad_reference_is_exit_4_with_zero_network(
    wired: tuple[FakePds, Path, tuple[str, str]],
) -> None:
    server, config_path, (uri, _) = wired
    code, out, err = _invoke(_admit_argv(config_path, uri, "not-a-cid"))
    assert code == 4
    assert out == ""
    assert server.requests == []


def test_cli_unreachable_pds_is_exit_6(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    credential = _write_credential(tmp_path)
    monkeypatch.setenv(ENV_VAR, str(credential))
    config_path = _write_config(
        tmp_path, "http://127.0.0.1:9", allowed_uid=os.geteuid()
    )

    code, out, err = _invoke(
        _admit_argv(
            config_path,
            f"at://{ALICE_DID}/{SUBMISSION_COLLECTION}/3jzfcijpj2z2b",
            "bafyreic7cldbweyx7ta42gvymb5xkglmqauaawvyxsoqmtxfowrudsavli",
        )
    )

    assert code == 6
    assert out == ""
    assert json.loads(err)["error"] == "read_unavailable"


def test_cli_ambiguous_write_resolves_to_created(
    wired: tuple[FakePds, Path, tuple[str, str]],
) -> None:
    server, config_path, (uri, cid) = wired
    server.drop_mode = "after_commit"

    code, out, err = _invoke(_admit_argv(config_path, uri, cid))

    assert code == 0
    assert err == ""
    assert json.loads(out)["operation"] == "created"
    assert server.create_record_attempts == 1


def test_cli_ambiguous_write_without_commit_is_exit_8(
    wired: tuple[FakePds, Path, tuple[str, str]],
) -> None:
    server, config_path, (uri, cid) = wired
    server.drop_mode = "before_commit"

    code, out, err = _invoke(_admit_argv(config_path, uri, cid))

    assert code == 8
    assert out == ""
    assert json.loads(err)["error"] == "write_failed"
    assert server.create_record_attempts == 1
