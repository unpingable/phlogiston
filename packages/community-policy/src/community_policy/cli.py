from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .adapters import HttpCandidateSource, UnixAuthorityClient
from .config import PolicyConfig
from .worker import PolicyState, PolicyWorker


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="community-policy")
    parser.add_argument("--config", required=True)
    parser.add_argument("command", choices=("run-once", "run-forever"))
    arguments = parser.parse_args(argv)
    try:
        config = PolicyConfig.load(Path(arguments.config))
        worker = PolicyWorker(
            config.community_did,
            HttpCandidateSource(config.observer_origin, config.request_timeout_seconds),
            UnixAuthorityClient(
                str(config.authority_socket), config.request_timeout_seconds
            ),
            PolicyState(config.state_path),
        )
        while True:
            result = worker.run_once()
            if arguments.command == "run-once":
                sys.stdout.write(
                    json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
                )
                return 0
            time.sleep(config.poll_interval_seconds)
    except (OSError, ValueError) as exc:
        _ = exc
        sys.stderr.write('{"error":"community_policy_unavailable"}\n')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
