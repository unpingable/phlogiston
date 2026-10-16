"""Console entry point: run the canonical AppView as its own process.

The process reads the strict observer configuration, drops every environment
variable outside a small allow-list before opening anything (the web process
never holds credentials, even if it was launched near daemon variables), and
opens the observer database read-only.  It performs no migration and no
network resolution.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence

from community_model import PortError, ValidationError
from communitywatch import ConfigError, ObserverStore, ProjectionQuery, load_config

from .app import WebApp
from .server import make_server

_ENVIRONMENT_ALLOWLIST = (
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "TMPDIR",
    "TZ",
)


def scrub_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """Keep only allow-listed variables; the web process holds no secrets."""

    return {
        key: value for key, value in environ.items() if key in _ENVIRONMENT_ALLOWLIST
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="communitywatch-web",
        description="Read-only canonical web AppView for one community observer.",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="path to the strict communitywatch TOML configuration",
    )
    args = parser.parse_args(argv)

    scrubbed = scrub_environment(os.environ)
    os.environ.clear()
    os.environ.update(scrubbed)

    try:
        config = load_config(args.config)
        store = ObserverStore(
            config.sqlite_path,
            community_did=config.community_did,
            read_only=True,
        )
    except (ConfigError, ValidationError, PortError) as exc:
        print(f"communitywatch-web: {exc}", file=sys.stderr)
        return 2

    query = ProjectionQuery(
        store,
        slug=config.community_slug,
        default_limit=config.page_size,
        max_limit=config.max_page_size,
    )
    app = WebApp(
        query,
        community_did=config.community_did,
        slug=config.community_slug,
        page_size=config.page_size,
        stale_threshold_seconds=config.stale_threshold_seconds,
    )
    server = make_server(app, host=config.bind, port=config.port)
    host, port = server.server_address[:2]
    print(f"communitywatch-web listening on {host}:{port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
