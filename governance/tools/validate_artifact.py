#!/usr/bin/env python3
"""Validate one governance artifact against its strict schema.

Usage: validate_artifact.py KIND FILE [--packet PACKET_JSON]

Prints a JSON verdict to stdout. Exit 0 when valid, 1 when invalid,
2 on usage errors. KIND is one of the artifact kinds registered in
validators.SCHEMA_FILES.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gstrict  # noqa: E402
import validators  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=sorted(validators.SCHEMA_FILES))
    parser.add_argument("file", type=Path)
    parser.add_argument(
        "--packet",
        type=Path,
        help="operator-question packet for decision-receipt cross-checks",
    )
    args = parser.parse_args(argv)

    packet = None
    if args.packet is not None:
        packet = gstrict.strict_loads(args.packet.read_text(encoding="utf-8"))
    obj, problems = validators.load_and_validate(args.kind, args.file, packet=packet)
    verdict = {"kind": args.kind, "file": str(args.file), "valid": not problems}
    if problems:
        verdict["problems"] = problems
    print(json.dumps(verdict, indent=2, sort_keys=True))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
