#!/usr/bin/env python3
"""Digest-verified external evidence write/readback with retention checks.

Evidence lives outside the Git worktree. Before any PASS, the writer is
closed and every retained file is read back and rechecked by byte length
and SHA-256. Any mismatch fails closed: altered or unavailable storage can
never produce a passing verdict.

CLI:

- ``evidence_store.py write SRC_DIR DST_DIR`` — copy a regular-file tree
  and verify the readback; prints the manifest as JSON.
- ``evidence_store.py verify MANIFEST_JSON DST_DIR`` — re-verify a stored
  tree against a previously emitted manifest.
- ``evidence_store.py check-policy POLICY_JSON`` — validate retention
  policy fields (absolute destination URI, RFC 3339 UTC retention, and
  readback_required true).

Exit 0 on success, 1 on any verification failure, 2 on usage errors.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE_MANIFEST_SCHEMA = "evidence-store-manifest-v1"


def _digest(path: Path) -> tuple[int, str]:
    data = path.read_bytes()
    return len(data), "sha256:" + hashlib.sha256(data).hexdigest()


def _list_regular_files(root: Path) -> tuple[list[Path], list[str]]:
    files = []
    problems = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            problems.append(f"symlink not permitted: {path}")
        elif path.is_file():
            files.append(path)
        elif not path.is_dir():
            problems.append(f"special file not permitted: {path}")
    return files, problems


def build_manifest(src: Path) -> tuple[dict, list[str]]:
    files, problems = _list_regular_files(src)
    entries = []
    for path in files:
        size, digest = _digest(path)
        entries.append(
            {
                "path": path.relative_to(src).as_posix(),
                "bytes": size,
                "sha256": digest,
            }
        )
    manifest = {"schema": EVIDENCE_MANIFEST_SCHEMA, "files": entries}
    return manifest, problems


def write_tree(src: Path, dst: Path) -> dict:
    """Copy *src* into *dst*, then read back and verify every byte."""
    problems = []
    if dst.exists() and any(dst.iterdir()):
        problems.append(f"destination {dst} is not empty; refusing to mix")
        return {"ok": False, "problems": problems}
    manifest, problems = build_manifest(src)
    if problems:
        return {"ok": False, "problems": problems}
    dst.mkdir(parents=True, exist_ok=True)
    for entry in manifest["files"]:
        source = src / entry["path"]
        target = dst / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    report = verify_tree(manifest, dst)
    report["manifest"] = manifest
    return report


def verify_tree(manifest: dict, dst: Path) -> dict:
    """Read back every manifest file from *dst* and verify it."""
    problems = []
    if manifest.get("schema") != EVIDENCE_MANIFEST_SCHEMA:
        problems.append("unknown evidence manifest schema")
        return {"ok": False, "problems": problems}
    seen = set()
    for entry in manifest.get("files", []):
        path = entry.get("path", "")
        if not path or path.startswith("/") or ".." in path.split("/") or "\\" in path:
            problems.append(f"unsafe manifest path {path!r}")
            continue
        if path in seen:
            problems.append(f"duplicate manifest path {path!r}")
            continue
        seen.add(path)
        target = dst / path
        if not target.is_file() or target.is_symlink():
            problems.append(f"missing or non-regular retained file {path!r}")
            continue
        size, digest = _digest(target)
        if size != entry.get("bytes"):
            problems.append(f"byte-length mismatch on {path!r}")
        if digest != entry.get("sha256"):
            problems.append(f"sha256 mismatch on {path!r}")
    extras, extra_problems = _list_regular_files(dst)
    problems.extend(extra_problems)
    for path in extras:
        relative = path.relative_to(dst).as_posix()
        if relative not in seen:
            problems.append(f"unexpected extra retained file {relative!r}")
    return {"ok": not problems, "problems": problems}


def check_retention_policy(policy: object, now: datetime | None = None) -> dict:
    """Validate evidence retention policy fields; fail closed."""
    problems = []
    if not isinstance(policy, dict):
        return {"ok": False, "problems": ["policy must be an object"]}
    unknown = set(policy) - {
        "destination_uri",
        "retention_until",
        "readback_required",
    }
    if unknown:
        problems.append(f"unknown policy fields {sorted(unknown)}")
    uri = policy.get("destination_uri")
    if not isinstance(uri, str) or not uri:
        problems.append("destination_uri must be a nonempty string")
    elif "://" not in uri:
        problems.append("destination_uri must be absolute")
    retention = policy.get("retention_until")
    parsed = None
    if isinstance(retention, str):
        try:
            parsed = datetime.strptime(retention, "%Y-%m-%dT%H:%M:%SZ")
            parsed = parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            parsed = None
    if parsed is None:
        problems.append("retention_until must be an RFC 3339 UTC timestamp")
    elif now is not None and parsed <= now:
        problems.append("retention_until is not in the future")
    if policy.get("readback_required") is not True:
        problems.append("readback_required must be true")
    return {"ok": not problems, "problems": problems}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    write_cmd = sub.add_parser("write")
    write_cmd.add_argument("src", type=Path)
    write_cmd.add_argument("dst", type=Path)
    verify_cmd = sub.add_parser("verify")
    verify_cmd.add_argument("manifest", type=Path)
    verify_cmd.add_argument("dst", type=Path)
    policy_cmd = sub.add_parser("check-policy")
    policy_cmd.add_argument("policy", type=Path)
    args = parser.parse_args(argv)

    if args.command == "write":
        report = write_tree(args.src, args.dst)
    elif args.command == "verify":
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        report = verify_tree(manifest, args.dst)
    else:
        policy = json.loads(args.policy.read_text(encoding="utf-8"))
        report = check_retention_policy(policy, now=datetime.now(timezone.utc))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
