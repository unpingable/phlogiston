from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path

from community_model import RecordRef
from communityd.cli import main
from communityd.fakes import FakeRepoState
from communityd.operations import DaemonPorts, admit, remove
from fakes_support import (
    make_config,
    make_ports,
    seed_author_repo,
    write_config,
)

NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)


def _invoke(
    argv: list[str], *, runtime: DaemonPorts | None = None
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, runtime=runtime, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _seeded_runtime() -> tuple[FakeRepoState, DaemonPorts, RecordRef]:
    state = FakeRepoState()
    _, submission_ref = seed_author_repo(state)
    return state, make_ports(state), submission_ref


def test_cli_admit_success_writes_json_to_stdout_only(tmp_path: Path) -> None:
    _, ports, submission_ref = _seeded_runtime()
    config_path = write_config(tmp_path)

    code, out, err = _invoke(
        [
            "--config",
            str(config_path),
            "admit",
            "--submission-uri",
            submission_ref.uri,
            "--submission-cid",
            submission_ref.cid,
        ],
        runtime=ports,
    )

    assert code == 0
    assert err == ""
    payload = json.loads(out)
    assert payload["operation"] == "created"
    assert payload["uri"].startswith("at://did:web:community.invalid/")
    assert payload["cid"].startswith("b")


def test_p0_cli_refuses_before_runtime_or_writer_access(tmp_path: Path) -> None:
    _, ports, submission_ref = _seeded_runtime()
    config_path = write_config(
        tmp_path,
        body=(
            f'community_did = "did:web:community.invalid"\n'
            f'administrator_did = "did:web:admin.invalid"\n'
            'community_pds_url = "https://pds.invalid"\n'
            'allowed_uid = 4242\nreader_adapter = "fake"\nledger_adapter = "fake"\n'
            'writer_adapter = "fake"\ncredential_provider = "fake"\n'
            'credential_ref = "fake://communityd-admin"\n'
            f'operation_journal_path = "{tmp_path / "journal.sqlite3"}"\n'
            f'p0_admission_pause_path = "{tmp_path / "admission.state"}"\n'
            'p0_profile = "root_only"\n'
        ),
    )
    code, out, err = _invoke(
        [
            "--config",
            str(config_path),
            "admit",
            "--submission-uri",
            submission_ref.uri,
            "--submission-cid",
            submission_ref.cid,
        ],
        runtime=ports,
    )
    assert code == 2 and out == ""
    assert json.loads(err)["error"] == "p0_socket_required"
    assert ports.writer.calls == []


def test_cli_usage_failure_is_exit_2_with_empty_stdout(tmp_path: Path) -> None:
    config_path = write_config(tmp_path)
    code, out, _ = _invoke(["--config", str(config_path), "admit"])
    assert code == 2
    assert out == ""


def test_cli_rejects_actor_override_flag(tmp_path: Path) -> None:
    _, ports, submission_ref = _seeded_runtime()
    config_path = write_config(tmp_path)
    code, out, _ = _invoke(
        [
            "--config",
            str(config_path),
            "admit",
            "--submission-uri",
            submission_ref.uri,
            "--submission-cid",
            submission_ref.cid,
            "--actor-did",
            "did:web:mallory.invalid",
        ],
        runtime=ports,
    )
    assert code == 2
    assert out == ""


def test_cli_missing_config_is_exit_2(tmp_path: Path) -> None:
    code, out, err = _invoke(
        [
            "--config",
            str(tmp_path / "absent.toml"),
            "admit",
            "--submission-uri",
            "at://did:web:alice.invalid/app.phlogiston.community.submit/3jzfcijpj2z2b",
            "--submission-cid",
            "bafyreic7cldbweyx7ta42gvymb5xkglmqauaawvyxsoqmtxfowrudsavli",
        ]
    )
    assert code == 2
    assert out == ""
    assert json.loads(err)["error"] == "config_invalid"


def test_cli_unknown_config_key_is_exit_2(tmp_path: Path) -> None:
    config_path = write_config(tmp_path, 'sqlite_path = "observer.sqlite3"\n')
    code, _, err = _invoke(
        [
            "--config",
            str(config_path),
            "admit",
            "--submission-uri",
            "at://did:web:alice.invalid/app.phlogiston.community.submit/3jzfcijpj2z2b",
            "--submission-cid",
            "bafyreic7cldbweyx7ta42gvymb5xkglmqauaawvyxsoqmtxfowrudsavli",
        ]
    )
    assert code == 2
    assert json.loads(err)["error"] == "config_invalid"


def test_cli_unauthorized_is_exit_3(tmp_path: Path) -> None:
    state = FakeRepoState()
    _, submission_ref = seed_author_repo(state)
    ports = make_ports(state, effective_uid=9999)
    config_path = write_config(tmp_path)

    code, out, err = _invoke(
        [
            "--config",
            str(config_path),
            "admit",
            "--submission-uri",
            submission_ref.uri,
            "--submission-cid",
            submission_ref.cid,
        ],
        runtime=ports,
    )

    assert code == 3
    assert out == ""
    assert json.loads(err)["error"] == "unauthorized"


def test_cli_bad_reference_is_exit_4(tmp_path: Path) -> None:
    config_path = write_config(tmp_path)
    code, out, err = _invoke(
        [
            "--config",
            str(config_path),
            "admit",
            "--submission-uri",
            "at://did:web:alice.invalid/app.phlogiston.community.submit/3jzfcijpj2z2b",
            "--submission-cid",
            "not-a-cid",
        ]
    )
    assert code == 4
    assert out == ""
    assert json.loads(err)["error"] == "cid_invalid"


def test_cli_readmission_after_removal_is_exit_5(tmp_path: Path) -> None:
    state, ports, submission_ref = _seeded_runtime()
    config_path = write_config(tmp_path)
    config = make_config()

    admission = admit(ports, config, submission_ref, now=NOW)
    remove(ports, config, admission.record, None, now=NOW)

    code, out, err = _invoke(
        [
            "--config",
            str(config_path),
            "admit",
            "--submission-uri",
            submission_ref.uri,
            "--submission-cid",
            submission_ref.cid,
        ],
        runtime=ports,
    )
    assert code == 5
    assert out == ""
    assert json.loads(err)["error"] == "unsupported_readmission"


def test_cli_read_unavailable_is_exit_6(tmp_path: Path) -> None:
    state, ports, submission_ref = _seeded_runtime()
    ports.reader.unavailable = True
    config_path = write_config(tmp_path)

    code, out, err = _invoke(
        [
            "--config",
            str(config_path),
            "admit",
            "--submission-uri",
            submission_ref.uri,
            "--submission-cid",
            submission_ref.cid,
        ],
        runtime=ports,
    )
    assert code == 6
    assert out == ""
    assert json.loads(err)["error"] == "read_unavailable"


def test_cli_credential_unavailable_is_exit_7(tmp_path: Path) -> None:
    state, _, submission_ref = _seeded_runtime()
    ports = make_ports(state, credentials={})
    config_path = write_config(tmp_path)

    code, out, err = _invoke(
        [
            "--config",
            str(config_path),
            "admit",
            "--submission-uri",
            submission_ref.uri,
            "--submission-cid",
            submission_ref.cid,
        ],
        runtime=ports,
    )
    assert code == 7
    assert out == ""
    assert json.loads(err)["error"] == "credential_unavailable"


def test_cli_writer_unavailable_is_exit_8(tmp_path: Path) -> None:
    state, ports, submission_ref = _seeded_runtime()
    ports.writer.unavailable = True
    config_path = write_config(tmp_path)

    code, out, err = _invoke(
        [
            "--config",
            str(config_path),
            "admit",
            "--submission-uri",
            submission_ref.uri,
            "--submission-cid",
            submission_ref.cid,
        ],
        runtime=ports,
    )
    assert code == 8
    assert out == ""
    assert json.loads(err)["error"] == "write_failed"


def test_cli_remove_success(tmp_path: Path) -> None:
    state, ports, submission_ref = _seeded_runtime()
    config_path = write_config(tmp_path)
    admission = admit(
        ports,
        make_config(),
        submission_ref,
        now=NOW,
    )

    code, out, err = _invoke(
        [
            "--config",
            str(config_path),
            "remove",
            "--admission-uri",
            admission.record.uri,
            "--admission-cid",
            admission.record.cid,
            "--reason",
            "off-topic",
        ],
        runtime=ports,
    )
    assert code == 0
    assert err == ""
    assert json.loads(out)["operation"] == "created"
