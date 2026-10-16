"""CLI surface: exit codes, human vocabulary, and credential handling."""

from __future__ import annotations

import json
from pathlib import Path

from community_submit import cli
from community_submit.transport import AuthorizationFailed, Credential
from submit_support import (
    ALICE,
    COMMUNITY,
    MALLORY,
    POST_RKEY,
    FakePds,
    _pds_with_post,
)

CREDENTIAL = Credential(identifier="alice.test", app_password="app-pass")


def _run(pds, *, post: str | None = None, extra: list[str] | None = None):
    argv = [
        post or f"https://bsky.app/profile/{ALICE}/post/{POST_RKEY}",
        "--community",
        COMMUNITY,
        "--pds",
        "https://pds.invalid",
        "--credential",
        "env:UNUSED",
    ]
    argv.extend(extra or [])
    return cli.run(
        argv, pds_factory=lambda _url: pds, credential_loader=lambda _ref: CREDENTIAL
    )


def test_success_says_submitted_and_not_yet_added() -> None:
    code, out, err = _run(_pds_with_post())
    assert code == cli.EXIT_OK
    assert err == ""
    assert "Submitted to" in out
    assert "does not add it to the community yet" in out
    assert "moderator still has to add it" in out
    # No protocol vocabulary in the default human output.
    for token in ("cid", "CID", "rkey", "NSID", "MST", "CAR", "at://", "$type"):
        assert token not in out, token


def test_verbose_reveals_exact_coordinates() -> None:
    code, out, _ = _run(_pds_with_post(), extra=["--verbose"])
    assert code == cli.EXIT_OK
    assert "at://" in out
    assert "exact version" in out


def test_repeat_run_reports_already_submitted_and_still_not_added() -> None:
    pds = _pds_with_post()
    _run(pds)
    code, out, _ = _run(pds)
    assert code == cli.EXIT_OK
    assert "already submitted" in out
    assert "does not add it to the community yet" in out


def test_foreign_post_exits_refused_with_plain_language() -> None:
    code, out, err = _run(
        _pds_with_post(author=MALLORY),
        post=f"https://bsky.app/profile/{MALLORY}/post/{POST_RKEY}",
    )
    assert code == cli.EXIT_REFUSED
    assert out == ""
    assert "belongs to someone else" in err


def test_malformed_link_exits_usage() -> None:
    code, _, err = _run(_pds_with_post(), post="nonsense")
    assert code == cli.EXIT_USAGE
    assert "does not look like a Bluesky post link" in err


def test_missing_post_exits_read_unavailable() -> None:
    code, _, err = _run(FakePds())
    assert code == cli.EXIT_READ_UNAVAILABLE
    assert "not in its author's repository" in err


def test_authorization_failure_exits_credential_unavailable() -> None:
    pds = _pds_with_post(
        session_error=AuthorizationFailed("authorization_failed", "rejected")
    )
    code, _, err = _run(pds)
    assert code == cli.EXIT_CREDENTIAL_UNAVAILABLE
    assert "rejected" in err


def test_credential_loader_reads_a_file_outside_the_repository(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "cred.json"
    path.write_text(
        json.dumps({"identifier": "alice.test", "app_password": "secret-value"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("COMMUNITY_SUBMIT_CREDENTIAL", str(path))
    credential = cli.load_credential("env:COMMUNITY_SUBMIT_CREDENTIAL")
    assert credential.identifier == "alice.test"
    assert credential.app_password == "secret-value"
    assert "secret-value" not in repr(credential)


def test_credential_errors_never_echo_the_path_or_contents(
    tmp_path: Path, monkeypatch
) -> None:
    secret_path = tmp_path / "very-secret-location.json"
    secret_path.write_text('{"identifier": "a"}', encoding="utf-8")
    monkeypatch.setenv("COMMUNITY_SUBMIT_CREDENTIAL", str(secret_path))
    try:
        cli.load_credential("env:COMMUNITY_SUBMIT_CREDENTIAL")
    except AuthorizationFailed as exc:
        assert str(secret_path) not in exc.message
        assert "very-secret-location" not in exc.message
    else:  # pragma: no cover - the malformed file must be rejected
        raise AssertionError("a malformed credential file must be refused")


def test_unset_credential_variable_is_reported_without_a_value(monkeypatch) -> None:
    monkeypatch.delenv("COMMUNITY_SUBMIT_CREDENTIAL", raising=False)
    try:
        cli.load_credential("env:COMMUNITY_SUBMIT_CREDENTIAL")
    except AuthorizationFailed as exc:
        assert "COMMUNITY_SUBMIT_CREDENTIAL" in exc.message
    else:  # pragma: no cover
        raise AssertionError("an unset credential variable must be refused")


def test_non_env_credential_reference_is_refused() -> None:
    try:
        cli.load_credential("/etc/passwd")
    except AuthorizationFailed as exc:
        assert "env:VARNAME" in exc.message
    else:  # pragma: no cover
        raise AssertionError("only env: references are accepted")
