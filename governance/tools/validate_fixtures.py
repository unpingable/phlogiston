#!/usr/bin/env python3
"""Sweep a golden-fixture set and emit a JSON verdict.

Usage: validate_fixtures.py FIXTURE_DIR

FIXTURE_DIR must contain ``valid/`` and ``invalid/`` subdirectories.

- Every ``valid/<kind>__<name>.json`` must validate as <kind>.
- Every ``invalid/<class>__<kind>__<name>.json`` must fail validation as
  <kind>; the recorded problems are reported so callers can assert the
  rejection class.

A valid ``operator-question-packet`` fixture named ``packet`` is used to
cross-check decision receipts. Exit 0 when every expectation holds.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gstrict  # noqa: E402
import validators  # noqa: E402


def _split_valid_name(name: str) -> tuple[str, str] | None:
    stem = name[: -len(".json")]
    if "__" not in stem:
        return None
    kind, short = stem.split("__", 1)
    return kind, short


def _split_invalid_name(name: str) -> tuple[str, str, str] | None:
    stem = name[: -len(".json")]
    parts = stem.split("__", 2)
    if len(parts) != 3:
        return None
    return parts[0], parts[1], parts[2]


def sweep(fixture_dir: Path) -> dict:
    report = {"fixture_dir": str(fixture_dir), "checks": [], "ok": True}

    def record(name: str, ok: bool, detail: object) -> None:
        report["checks"].append({"file": name, "ok": ok, "detail": detail})
        if not ok:
            report["ok"] = False

    packet = None
    valid_dir = fixture_dir / "valid"
    packet_path = valid_dir / "operator-question-packet__packet.json"
    if packet_path.is_file():
        packet = gstrict.strict_loads(packet_path.read_text(encoding="utf-8"))

    for path in sorted(valid_dir.glob("*.json")):
        parsed = _split_valid_name(path.name)
        if parsed is None or parsed[0] not in validators.SCHEMA_FILES:
            record(path.name, False, "unrecognized valid-fixture name")
            continue
        kind, _ = parsed
        _, problems = validators.load_and_validate(kind, path, packet=packet)
        record(path.name, not problems, problems)

    invalid_dir = fixture_dir / "invalid"
    for path in sorted(invalid_dir.glob("*.json")):
        parsed = _split_invalid_name(path.name)
        if parsed is None or parsed[1] not in validators.SCHEMA_FILES:
            record(path.name, False, "unrecognized invalid-fixture name")
            continue
        kind = parsed[1]
        packet_arg = packet if kind == "operator-decision-receipt" else None
        _, problems = validators.load_and_validate(kind, path, packet=packet_arg)
        record(path.name, bool(problems), problems)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture_dir", type=Path)
    args = parser.parse_args(argv)
    report = sweep(args.fixture_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
