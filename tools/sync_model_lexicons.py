#!/usr/bin/env python3
"""Copy canonical community Lexicons into the Python runtime package."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packages/community-lexicon-publisher/lexicons"
DESTINATION = ROOT / "packages/community-model/src/community_model/schemas"


def canonical(path: Path) -> bytes:
    return (
        json.dumps(json.loads(path.read_text()), sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    sources = sorted(SOURCE.glob("*.json"))
    destinations = sorted(DESTINATION.glob("*.json"))
    if {path.name for path in sources} != {path.name for path in destinations}:
        raise SystemExit("canonical and runtime Lexicon inventories differ")
    drift = [
        source.name
        for source in sources
        if canonical(source) != canonical(DESTINATION / source.name)
    ]
    if args.check:
        if drift:
            raise SystemExit(
                "runtime Lexicons drift from canonical source: " + ", ".join(drift)
            )
        return
    for source in sources:
        shutil.copyfile(source, DESTINATION / source.name)


if __name__ == "__main__":
    main()
