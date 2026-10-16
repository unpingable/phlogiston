from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

from community_space_model import SpaceIdentity

from .identity import PlcDirectoryIdentityQualifier
from .supervisor import CommandArtifactAcquirer, LiveSupervisor, SupervisorConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="communitywatch-live")
    parser.add_argument("--config", required=True)
    parser.add_argument("command", choices=("run-once", "run-forever"))
    args = parser.parse_args(argv)
    try:
        config, interval, plc_origin = _config(Path(args.config))
        identities = PlcDirectoryIdentityQualifier(
            config.evidence_directory / "identity", directory_origin=plc_origin
        )
        supervisor = LiveSupervisor(config, identities, CommandArtifactAcquirer(config))
        if args.command == "run-forever":
            supervisor.run_forever(interval)
            return 0
        result = supervisor.run_once()
        sys.stdout.write(
            json.dumps(
                {
                    "runReceiptId": result.run_receipt_id,
                    "generationId": (
                        result.generation.generation_id if result.generation else None
                    ),
                    "published": result.published,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        return 0
    except Exception:
        sys.stderr.write('{"error":"communitywatch_live_refused"}\n')
        return 1


def _config(path: Path) -> tuple[SupervisorConfig, float, str]:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    expected = {
        "space_authority_did",
        "space_type",
        "space_skey",
        "community_actor_did",
        "author_action_store",
        "artifact_spool",
        "authority_receipt_directory",
        "evidence_directory",
        "projection_directory",
        "acquisition_command",
        "acquisition_timeout_seconds",
        "poll_interval_seconds",
        "plc_directory_origin",
    }
    if set(raw) != expected:
        raise ValueError("live supervisor configuration fields differ")
    command = raw["acquisition_command"]
    if not isinstance(command, list) or any(
        not isinstance(item, str) for item in command
    ):
        raise ValueError("live acquisition command is invalid")
    config = SupervisorConfig(
        SpaceIdentity(
            str(raw["space_authority_did"]),
            str(raw["space_type"]),
            str(raw["space_skey"]),
        ),
        str(raw["community_actor_did"]),
        Path(str(raw["author_action_store"])),
        Path(str(raw["artifact_spool"])),
        Path(str(raw["authority_receipt_directory"])),
        Path(str(raw["evidence_directory"])),
        Path(str(raw["projection_directory"])),
        tuple(command),
        float(raw["acquisition_timeout_seconds"]),
    )
    return config, float(raw["poll_interval_seconds"]), str(raw["plc_directory_origin"])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
