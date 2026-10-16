from __future__ import annotations

import os
from pathlib import Path

from communitywatch_web.history import sha256_file
from communitywatch_web.history_cli import main
from tests.web_support import COMMUNITY_DID


def _config(path: Path, db: Path) -> Path:
    path.write_text(
        "\n".join(
            (
                f'community_did = "{COMMUNITY_DID}"',
                'community_slug = "homelab"',
                f'sqlite_path = "{db}"',
                'event_source_url = "wss://jetstream.invalid"',
                'resolver_url = "https://resolver.invalid"',
                'bind = "127.0.0.1"',
                "port = 8138",
            )
        ),
        encoding="utf-8",
    )
    return path


def test_history_cli_refuses_mutated_store_before_binding_socket(
    seeded_db: Path, refs: dict[str, object], tmp_path: Path, capsys
) -> None:
    config = _config(tmp_path / "config.toml", seeded_db)
    admission = refs["removed_admission"]
    original_environment = os.environ.copy()
    try:
        result = main(
            [
                "--config",
                str(config),
                "--expected-store-sha256",
                "sha256:" + "0" * 64,
                "--captured-at",
                "2026-08-14T12:00:00Z",
                "--admission-rkey",
                admission.uri.rsplit("/", 1)[-1],
                "--source-label",
                "fixture",
            ]
        )
    finally:
        os.environ.clear()
        os.environ.update(original_environment)
    assert result == 2
    stderr = capsys.readouterr().err
    assert "digest mismatch" in stderr
    assert sha256_file(seeded_db) not in stderr
