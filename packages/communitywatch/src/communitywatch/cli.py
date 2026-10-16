"""Console entry point: run the observer index pipeline as its own process.

The process reads the strict observer configuration (which can never carry
credentials), opens the observer store writable, and runs the ingest and
resolve stages.  It is detect-only: it performs public unauthenticated reads
and never holds signing material or a write-capable client.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence

from community_model import PortError, ValidationError
from communitywatch import (
    ConfigError,
    ObserverStore,
    load_config,
)
from communitywatch.config import ObserverConfig

from .builder import build_runner


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="communitywatch-index",
        description="Detect-only observer index pipeline for one community.",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="path to the strict communitywatch TOML configuration",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="run one ingest and one resolve pass, then exit",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=5.0,
        help="delay between ingest passes when looping (default 5)",
    )
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if config.administrator_did is None:
            raise ConfigError("administrator_did is required for the index pipeline")
        _run(config, once=args.once, poll_seconds=args.poll_seconds)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except (ValidationError, PortError) as exc:
        print(f"index error: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


def _run(config: ObserverConfig, *, once: bool, poll_seconds: float) -> None:
    assert config.administrator_did is not None
    store = ObserverStore(
        config.sqlite_path,
        community_did=config.community_did,
        administrator_did=config.administrator_did,
    )
    runner = build_runner(config, store)
    while True:
        runner.run_ingest_once()
        runner.run_resolve_once()
        if once:
            return
        time.sleep(max(poll_seconds, 0.1))


if __name__ == "__main__":
    raise SystemExit(main())
