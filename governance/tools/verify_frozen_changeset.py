#!/usr/bin/env python3
"""Verifier for the frozen OQ-7 bootstrap required-change-set artifacts.

Each frozen change set is a UTF-8 patch artifact whose header has one ASCII
``key = value`` pair per line before one ``--PATCH--`` delimiter: ``schema``,
``change_set_id``, ``packet_id``, ``question_id``, ``answer_id``,
``receipt_id``, ``target_count``, then for every target in application
order ``target.N.path``, ``target.N.base_sha256``, and
``target.N.result_sha256``. Keys and target paths occur only once, indices
are contiguous, values are JSON strings except decimal ``target_count``,
and no value is a placeholder. The remaining bytes are the exact
unified-diff operations.

The verifier parses the header strictly, verifies each target's base digest
against the pinned base commit, applies the patch in a disposable tree, and
verifies every declared result digest. It also proves the patch body
touches exactly the declared target paths.

Usage: verify_frozen_changeset.py PATCH --base-commit COMMIT [--repo DIR]

Prints a JSON report to stdout; exit 0 when the change set verifies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gstrict  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

FROZEN_SCHEMA = "oq7-bootstrap-required-change-set-v1"
DELIMITER = "--PATCH--"
HEADER_KEYS = [
    "schema",
    "change_set_id",
    "packet_id",
    "question_id",
    "answer_id",
    "receipt_id",
    "target_count",
]
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
KEY_VALUE_RE = re.compile(r'^([A-Za-z0-9_.]+) = (".*"|[-0-9]+)$')
PATCH_PATH_RE = re.compile(r"^(?:---|\+\+\+) [ab]/(.+)$")


class ChangeSetError(ValueError):
    """The frozen change set violates its grammar or digests."""


def parse_header(text: str) -> tuple[dict[str, str], list[dict], str]:
    """Parse the frozen header; return (scalars, targets, patch_text)."""
    if DELIMITER not in text:
        raise ChangeSetError("missing --PATCH-- delimiter")
    header_text, patch_text = text.split(DELIMITER, 1)
    scalars: dict[str, str] = {}
    targets: dict[int, dict[str, str]] = {}
    seen_keys: set[str] = set()
    key_sequence: list[str] = []
    for line in header_text.splitlines():
        if not line.strip():
            continue
        match = KEY_VALUE_RE.match(line)
        if not match:
            raise ChangeSetError(f"unparseable header line: {line!r}")
        key, raw = match.groups()
        if key in seen_keys:
            raise ChangeSetError(f"duplicate header key {key!r}")
        seen_keys.add(key)
        key_sequence.append(key)
        target_match = re.match(
            r"^target\.(\d+)\.(path|base_sha256|result_sha256)$", key
        )
        if target_match:
            index = int(target_match.group(1))
            value = json.loads(raw)  # raises on non-JSON-string values
            if not isinstance(value, str) or not value or gstrict.is_placeholder(value):
                raise ChangeSetError(f"empty or placeholder value for {key!r}")
            targets.setdefault(index, {})[target_match.group(2)] = value
            continue
        if key not in HEADER_KEYS:
            raise ChangeSetError(f"unknown header key {key!r}")
        if key == "target_count":
            if not re.fullmatch(r"[0-9]+", raw):
                raise ChangeSetError("target_count must be decimal")
            scalars[key] = raw
        else:
            value = json.loads(raw)
            if not isinstance(value, str) or not value or gstrict.is_placeholder(value):
                raise ChangeSetError(f"empty or placeholder value for {key!r}")
            scalars[key] = value
    missing = [key for key in HEADER_KEYS if key not in scalars]
    if missing:
        raise ChangeSetError(f"missing header keys: {missing}")
    count = int(scalars["target_count"])
    expected_order = list(HEADER_KEYS)
    for index in range(1, count + 1):
        for field in ("path", "base_sha256", "result_sha256"):
            expected_order.append(f"target.{index}.{field}")
    if key_sequence != expected_order:
        raise ChangeSetError("header keys are not in the frozen order")
    if scalars["schema"] != FROZEN_SCHEMA:
        raise ChangeSetError(f"schema must be {FROZEN_SCHEMA}")
    count = int(scalars["target_count"])
    if count < 1 or sorted(targets) != list(range(1, count + 1)):
        raise ChangeSetError("target indices must be contiguous from 1")
    ordered = []
    for index in range(1, count + 1):
        target = targets[index]
        if set(target) != {"path", "base_sha256", "result_sha256"}:
            raise ChangeSetError(f"target {index} is incomplete")
        for field in ("base_sha256", "result_sha256"):
            if not DIGEST_RE.match(target[field]):
                raise ChangeSetError(f"target {index} {field} is not a sha256 digest")
        ordered.append(target)
    paths = [t["path"] for t in ordered]
    if len(set(paths)) != len(paths):
        raise ChangeSetError("duplicate target paths")
    return scalars, ordered, patch_text


def _git_show(repo: Path, commit: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), "show", f"{commit}:{path}"],
        capture_output=True,
        check=True,
    )
    return result.stdout


def _patch_paths(patch_text: str) -> set[str]:
    paths = set()
    for line in patch_text.splitlines():
        match = PATCH_PATH_RE.match(line)
        if match:
            paths.add(match.group(1))
    return paths


def verify(patch_path: Path, base_commit: str, repo: Path = REPO_ROOT) -> dict:
    """Verify one frozen change set against *base_commit*."""
    errors: list[str] = []
    report: dict = {"patch": str(patch_path), "ok": False, "targets": []}
    raw = patch_path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        report["errors"] = ["patch artifact is not UTF-8"]
        return report
    try:
        scalars, targets, patch_text = parse_header(text)
    except (ChangeSetError, json.JSONDecodeError) as exc:
        report["errors"] = [str(exc)]
        return report

    report["change_set_id"] = scalars["change_set_id"]
    report["receipt_id"] = scalars["receipt_id"]

    declared_paths = {t["path"] for t in targets}
    touched = _patch_paths(patch_text)
    if touched != declared_paths:
        errors.append(
            f"patch body touches {sorted(touched)} but header declares "
            f"{sorted(declared_paths)}"
        )

    with tempfile.TemporaryDirectory(prefix="oq7-changeset-") as tmp:
        work = Path(tmp)
        for target in targets:
            path = target["path"]
            try:
                base_bytes = _git_show(repo, base_commit, path)
            except subprocess.CalledProcessError:
                errors.append(f"no such base path at {base_commit}: {path}")
                continue
            base_digest = "sha256:" + hashlib.sha256(base_bytes).hexdigest()
            base_ok = base_digest == target["base_sha256"]
            if not base_ok:
                errors.append(f"base digest mismatch for {path}")
            destination = work / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(base_bytes)
            report["targets"].append(
                {"path": path, "base_ok": base_ok, "result_ok": False}
            )
        if errors:
            report["errors"] = errors
            return report
        applied = subprocess.run(
            ["git", "apply", "--unidiff-zero", "--whitespace=nowarn"],
            cwd=work,
            input=patch_text.encode("utf-8"),
            capture_output=True,
        )
        if applied.returncode != 0:
            errors.append(
                "git apply failed: " + applied.stderr.decode("utf-8", "replace")
            )
            report["errors"] = errors
            return report
        for entry, target in zip(report["targets"], targets, strict=True):
            result_bytes = (work / target["path"]).read_bytes()
            result_digest = "sha256:" + hashlib.sha256(result_bytes).hexdigest()
            entry["result_ok"] = result_digest == target["result_sha256"]
            if not entry["result_ok"]:
                errors.append(f"result digest mismatch for {target['path']}")
    report["errors"] = errors
    report["ok"] = not errors
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("patch", type=Path)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    report = verify(args.patch, args.base_commit, args.repo)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
