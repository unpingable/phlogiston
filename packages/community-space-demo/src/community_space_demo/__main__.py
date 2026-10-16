from __future__ import annotations

import argparse
import json
from pathlib import Path

from .demo import StaticDemoCompiler, build_synthetic_demo_sites


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify an existing export instead of writing it",
    )
    args = parser.parse_args(argv)
    bundle = StaticDemoCompiler().compile(build_synthetic_demo_sites())
    if args.check:
        bundle.verify_directory(args.output)
        action = "verified"
    else:
        bundle.write_directory(args.output)
        action = "written"
    print(
        json.dumps(
            {
                "action": action,
                "bundleId": bundle.bundle_id,
                "fileCount": len(bundle.all_files),
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
