#!/usr/bin/env python3
"""Protected-path and allowed-path check for a candidate diff.

Two modes:

- Bootstrap (add-only): verify that the candidate diff (base..head) touches
  only allowed paths and no protected path. Allowed patterns are exact paths
  (``scripts/v0-gate``) or ``dir/**`` patterns whose ``**`` matches
  descendant regular files only. Every change must be an addition; the
  protected set is every path tracked at base. This is the V0-G0 shape.
- General (modify-within-allowed): the controller-entry packet names
  allowed patterns plus an explicit literal protected path list. Additions
  and modifications of regular files are permitted within the allowed
  patterns; deletions, renames, and any change to a protected path or a path
  outside the allowed set are rejected. This is the post-bootstrap V0 task
  shape; the contract requires product tasks to modify existing files while
  leaving the pinned governance inputs untouched.

Symlinks, gitlinks, special files, and path traversal are rejected in both
modes.

Usage: check_paths.py --base COMMIT [--head COMMIT] --allow PATTERN
       [--allow PATTERN ...] [--protect PATH ...] [--repo DIR]

Prints a JSON report to stdout; exit 0 when the diff is clean.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

G0_ALLOWED_PATTERNS = ["governance/**", "scripts/v0-gate", "tests/governance/**"]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def pattern_matches(pattern: str, path: str) -> bool:
    """Match an allowed pattern: exact path or ``dir/**`` descendants."""
    if pattern.endswith("/**"):
        prefix = pattern[: -len("/**")]
        return path.startswith(prefix + "/") and len(path) > len(prefix) + 1
    if "**" in pattern:
        raise ValueError(f"'**' is only permitted as a trailing /**: {pattern}")
    return pattern == path


def check_diff(
    repo: Path,
    base: str,
    head: str,
    allowed: list[str],
    protected: list[str] | None = None,
) -> dict:
    """Check the candidate diff against allowed/protected paths.

    Without ``protected`` (bootstrap mode) every change must be an addition
    and every base-tracked path is protected. With ``protected`` (general
    mode) additions and modifications of regular files within the allowed
    patterns are permitted, deletions are rejected, and the literal
    protected paths must not appear in the diff at all.
    """
    add_only = protected is None
    violations = []
    protected_set = (
        set(_git(repo, "ls-tree", "-r", "--name-only", base).splitlines())
        if add_only
        else set(protected)
    )

    entries = []
    raw = _git(repo, "diff", "--name-status", "--no-renames", base, head)
    for line in raw.splitlines():
        if not line:
            continue
        status, _, path = line.partition("\t")
        entries.append((status, path))

    modes = {}
    if entries:
        listing = _git(repo, "ls-tree", "-r", head, "--", *[p for _, p in entries])
        for line in listing.splitlines():
            meta, _, path = line.partition("\t")
            mode = meta.split(" ", 1)[0]
            modes[path] = mode

    for status, path in entries:
        if add_only and status != "A":
            violations.append(
                {"path": path, "reason": f"status {status} is not an addition"}
            )
            continue
        if not add_only and status not in ("A", "M"):
            violations.append(
                {
                    "path": path,
                    "reason": f"status {status} is not an addition or modification",
                }
            )
            continue
        if path in protected_set:
            violations.append({"path": path, "reason": "protected path"})
        segments = path.split("/")
        if (
            path.startswith("/")
            or "\\" in path
            or any(seg in ("", ".", "..") for seg in segments)
        ):
            violations.append(
                {"path": path, "reason": "path traversal or invalid segments"}
            )
            continue
        mode = modes.get(path, "")
        if mode == "120000":
            violations.append({"path": path, "reason": "symlink not allowed"})
            continue
        if mode == "160000":
            violations.append({"path": path, "reason": "gitlink not allowed"})
            continue
        if mode and mode != "100644" and mode != "100755":
            violations.append({"path": path, "reason": f"special file mode {mode}"})
            continue
        if not any(pattern_matches(p, path) for p in allowed):
            violations.append({"path": path, "reason": "outside allowed path patterns"})
    return {
        "repo": str(repo),
        "base": base,
        "head": head,
        "mode": "bootstrap" if add_only else "general",
        "allowed_patterns": allowed,
        "protected_paths": sorted(protected_set),
        "changed_paths": [p for _, p in entries],
        "violations": violations,
        "ok": not violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--allow", action="append", default=None)
    parser.add_argument(
        "--protect",
        action="append",
        default=None,
        help="literal protected path (general mode); repeatable",
    )
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    allowed = args.allow if args.allow is not None else list(G0_ALLOWED_PATTERNS)
    report = check_diff(args.repo, args.base, args.head, allowed, args.protect)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
