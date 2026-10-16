"""Supervised Unix-socket entrypoint for communityd authority requests."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .authority_server import (
    AuthorityRequestBoundary,
    CommunityAuthorityHandler,
    UnixAuthorityServer,
    UnixPeerRolePolicy,
)
from .cli import build_runtime
from .config import ConfigError, DaemonConfig, load_config


def build_server(config: DaemonConfig) -> UnixAuthorityServer:
    if config.operation_journal_path is None:
        raise ConfigError("communityd-serve requires operation_journal_path")
    if config.authority_socket_path is None:
        raise ConfigError("communityd-serve requires authority_socket_path")
    if config.web_peer_uid is None or (
        config.p0_profile is None and config.policy_peer_uid is None
    ):
        raise ConfigError("communityd-serve requires trusted peer UIDs")
    ports = build_runtime(config)
    roles = UnixPeerRolePolicy(
        web_uid=config.web_peer_uid, policy_uid=config.policy_peer_uid
    )
    handler = CommunityAuthorityHandler(
        ports=ports,
        reply_ledger=ports.ledger,  # both real and fake direct ledgers implement it
        config=config,
    )
    boundary = AuthorityRequestBoundary(
        administrator_did=config.administrator_did,
        handler=handler,
        peer_identifier=roles.identify,
    )
    return UnixAuthorityServer(config.authority_socket_path, boundary)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="communityd-serve")
    parser.add_argument("--config", required=True)
    arguments = parser.parse_args(argv)
    try:
        server = build_server(load_config(arguments.config))
    except ConfigError as exc:
        parser.error(str(exc))
    server.serve_forever()
    return 0


__all__ = ["build_server", "main"]
