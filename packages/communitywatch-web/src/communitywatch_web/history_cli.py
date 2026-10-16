"""Launch the byte-pinned, read-only historical V0 evidence demo."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from community_model import PortError, ValidationError
from communitywatch import ConfigError, ObserverStore, ProjectionQuery, load_config

from .cli import scrub_environment
from .history import HistoricalEvidenceDemo, sha256_file
from .server import make_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--expected-store-sha256", required=True)
    parser.add_argument("--captured-at", required=True)
    parser.add_argument("--admission-rkey", required=True)
    parser.add_argument("--source-label", required=True)
    args = parser.parse_args(argv)

    scrubbed = scrub_environment(os.environ)
    os.environ.clear()
    os.environ.update(scrubbed)
    try:
        config = load_config(args.config)
        observed_digest = sha256_file(Path(config.sqlite_path))
        if observed_digest != args.expected_store_sha256:
            raise ConfigError("historical observer store digest mismatch")
        store = ObserverStore(
            config.sqlite_path,
            community_did=config.community_did,
            read_only=True,
        )
        query = ProjectionQuery(
            store,
            slug=config.community_slug,
            default_limit=config.page_size,
            max_limit=config.max_page_size,
        )
        app = HistoricalEvidenceDemo(
            query=query,
            community_did=config.community_did,
            slug=config.community_slug,
            admission_rkey=args.admission_rkey,
            captured_at=args.captured_at,
            expected_store_sha256=args.expected_store_sha256,
            source_label=args.source_label,
        )
        app.document()
    except (ConfigError, ValidationError, PortError, OSError, ValueError) as exc:
        print(f"communitywatch-history-demo: {exc}", file=sys.stderr)
        return 2

    server = make_server(app, host=config.bind, port=config.port)
    host, port = server.server_address[:2]
    print(f"communitywatch-history-demo listening on {host}:{port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
