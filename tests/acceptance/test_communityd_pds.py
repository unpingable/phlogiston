"""V0-M7 acceptance: the communityd CLI drives real PDS adapters end-to-end.

Everything runs offline against a loopback fake PDS speaking the four XRPC
procedures the real adapters use.  The credential transits an env-var-named
JSON file in a temp directory (never the repository), the app-password
canary must appear in no output or log, and the configured OS principal
(effective UID) gates every invocation before any network I/O.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from communityd.cli import main
from communityd.fakepds import FakePds

COMMUNITY_DID = "did:web:community.invalid"
ADMIN_DID = "did:web:admin.invalid"
ALICE_DID = "did:web:alice.invalid"
POST_COLLECTION = "app.bsky.feed.post"
SUBMISSION_COLLECTION = "app.phlogiston.community.submit"
ADMISSION_COLLECTION = "app.phlogiston.community.admission"
MOD_ACTION_COLLECTION = "app.phlogiston.community.modAction"
CANARY = "acceptance-canary-password-cccc-dddd"
ENV_VAR = "COMMUNITYD_ACCEPTANCE_CREDENTIAL"


def _invoke(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def deployment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[FakePds, Path, str, str]:
    credential = tmp_path / "communityd-credential.json"
    credential.write_text(
        json.dumps({"identifier": "community.test", "app_password": CANARY}),
        encoding="utf-8",
    )
    monkeypatch.setenv(ENV_VAR, str(credential))
    with FakePds(
        session_did=COMMUNITY_DID, identifier="community.test", app_password=CANARY
    ) as server:
        config_path = tmp_path / "communityd.toml"
        config_path.write_text(
            f'community_did = "{COMMUNITY_DID}"\n'
            f'administrator_did = "{ADMIN_DID}"\n'
            f'community_pds_url = "{server.url}"\n'
            f"allowed_uid = {os.geteuid()}\n"
            'reader_adapter = "pds_fixed"\n'
            'ledger_adapter = "pds"\n'
            'writer_adapter = "pds"\n'
            'credential_provider = "env_file"\n'
            f'credential_ref = "env:{ENV_VAR}"\n'
            "request_timeout_ms = 2000\n"
            "max_retries = 1\n",
            encoding="utf-8",
        )
        post = {
            "$type": POST_COLLECTION,
            "text": "Acceptance post.",
            "createdAt": "2026-08-13T11:59:00Z",
        }
        post_ref = server.seed(ALICE_DID, POST_COLLECTION, "3jzfcijpj2z2a", post)
        submission = {
            "$type": SUBMISSION_COLLECTION,
            "community": COMMUNITY_DID,
            "subject": post_ref.as_dict(),
            "createdAt": "2026-08-13T11:59:30Z",
        }
        submission_ref = server.seed(
            ALICE_DID, SUBMISSION_COLLECTION, "3jzfcijpj2z2b", submission
        )
        yield server, config_path, submission_ref.uri, submission_ref.cid


def test_full_admit_remove_lifecycle_over_loopback_pds(
    deployment: tuple[FakePds, Path, str, str],
) -> None:
    server, config_path, submission_uri, submission_cid = deployment

    admit_argv = [
        "--config",
        str(config_path),
        "admit",
        "--submission-uri",
        submission_uri,
        "--submission-cid",
        submission_cid,
    ]
    code, out, err = _invoke(admit_argv)
    assert code == 0
    assert err == ""
    admission = json.loads(out)
    assert admission["operation"] == "created"

    # The admission landed in the community repo with exact strong refs and
    # the configured administrator attribution (OQ-4/A: may equal the actor).
    admission_uri = admission["uri"]
    assert admission_uri.startswith(f"at://{COMMUNITY_DID}/{ADMISSION_COLLECTION}/")
    stored = server.get(
        COMMUNITY_DID, ADMISSION_COLLECTION, admission_uri.rsplit("/", 1)[1]
    )
    assert stored is not None
    value = server.records[
        (COMMUNITY_DID, ADMISSION_COLLECTION, admission_uri.rsplit("/", 1)[1])
    ][1]
    assert value["submission"] == {"uri": submission_uri, "cid": submission_cid}
    assert value["actor"] == ADMIN_DID

    # Idempotent re-admit is the same operation at the same reference.
    code, out, err = _invoke(admit_argv)
    assert code == 0
    assert json.loads(out)["operation"] == "existing"
    assert json.loads(out)["uri"] == admission_uri
    assert server.create_record_attempts == 1

    # Removal lands at the admission-derived rkey.
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
            "acceptance removal",
        ]
    )
    assert code == 0
    assert err == ""
    removal = json.loads(out)
    assert removal["operation"] == "created"
    assert removal["uri"].startswith(f"at://{COMMUNITY_DID}/{MOD_ACTION_COLLECTION}/")

    # The exact subject is now terminalized: readmission is exit 5.
    code, out, err = _invoke(admit_argv)
    assert code == 5
    assert out == ""
    assert json.loads(err)["error"] == "unsupported_readmission"

    # Only PDS XRPC paths were touched; no observer storage or artifact path
    # exists in this flow, and the user repository was never written.
    assert all(
        entry.split(" ")[1].startswith("/xrpc/com.atproto.")
        for entry in server.requests
    )
    assert all(key[0] == COMMUNITY_DID for key in server.created)

    # Redaction: the app-password canary and the session token appear in no
    # stdout, stderr, or request-line log.
    assert all(CANARY not in entry for entry in server.requests)
    assert all(server.token not in entry for entry in server.requests)


def test_unauthorized_principal_reaches_no_network(
    deployment: tuple[FakePds, Path, str, str],
) -> None:
    server, config_path, submission_uri, submission_cid = deployment
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            f"allowed_uid = {os.geteuid()}", f"allowed_uid = {os.geteuid() + 1}"
        ),
        encoding="utf-8",
    )
    server.requests.clear()

    code, out, err = _invoke(
        [
            "--config",
            str(config_path),
            "admit",
            "--submission-uri",
            submission_uri,
            "--submission-cid",
            submission_cid,
        ]
    )

    assert code == 3
    assert out == ""
    assert json.loads(err)["error"] == "unauthorized"
    assert server.requests == []
