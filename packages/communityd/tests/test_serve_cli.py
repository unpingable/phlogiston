from __future__ import annotations

import socket
from dataclasses import replace

import pytest

from communityd.authority_server import _remove_stale_socket
from communityd.config import ConfigError
from communityd.serve_cli import build_server
from fakes_support import make_config


def test_supervised_server_requires_journal_socket_and_distinct_peers(tmp_path) -> None:
    with pytest.raises(ConfigError, match="operation_journal_path"):
        build_server(make_config())
    config = replace(
        make_config(),
        operation_journal_path=str(tmp_path / "authority.sqlite3"),
        authority_socket_path=str(tmp_path / "authority.sock"),
        web_peer_uid=1001,
        policy_peer_uid=1002,
    )
    server = build_server(config)
    assert server.path == str(tmp_path / "authority.sock")


def test_stale_socket_is_removed_but_regular_file_is_preserved(tmp_path) -> None:
    path = tmp_path / "authority.sock"
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(path))
    stale.close()
    _remove_stale_socket(path)
    assert not path.exists()

    path.write_text("do not delete", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not a socket"):
        _remove_stale_socket(path)
    assert path.read_text(encoding="utf-8") == "do not delete"


def test_live_socket_is_not_stolen(tmp_path) -> None:
    path = tmp_path / "authority.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        listener.listen(1)
        with pytest.raises(RuntimeError, match="already running"):
            _remove_stale_socket(path)
    path.unlink()
