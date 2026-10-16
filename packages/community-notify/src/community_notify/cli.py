from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .adapters import HttpProjectionSource, HttpsWebhookSender
from .config import NotifyConfig
from .worker import Cursor, NotifyWorker


def _log(message: str) -> None:
    sys.stderr.write(json.dumps({"community_notify": message}) + "\n")
    sys.stderr.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="community-notify")
    parser.add_argument("--config", required=True)
    parser.add_argument(
        "--once", action="store_true", help="poll once, print counts, and exit"
    )
    arguments = parser.parse_args(argv)
    try:
        config = NotifyConfig.load(Path(arguments.config))
        worker = NotifyWorker(
            community_did=config.community_did,
            community_name=config.community_name,
            public_base_url=config.public_base_url,
            payload_key=config.webhook_payload_key,
            source=HttpProjectionSource(config.projection_origin),
            sender=HttpsWebhookSender(config.webhook_url),
            cursor=Cursor(config.cursor_path),
            log=_log,
        )
    except (OSError, ValueError) as exc:
        _log(f"not started: {exc}")
        return 1
    while True:
        try:
            counts = worker.run_once()
        except OSError as exc:
            # A cursor write failure: nothing was lost that a later poll
            # cannot find again, so log and keep polling.
            _log(f"cursor unavailable: {type(exc).__name__}")
            if arguments.once:
                return 1
            counts = None
        if arguments.once:
            sys.stdout.write(json.dumps(counts, sort_keys=True) + "\n")
            return 0
        time.sleep(config.poll_interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
