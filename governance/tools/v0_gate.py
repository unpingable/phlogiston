"""Root V0 gate: ./scripts/v0-gate TASK_ID (implementation module).

The gate is a probe, never an action: it runs the cumulative check suite,
the governance test suite, the fixture validators, and the roadmap
validator in V0-lane mode, then emits a machine-readable requirement
coverage report. It exits zero only on PASS.

Offline preflight: every V0 done gate runs with the manifest-declared
``network_mode: denied`` and ``credential_mode: none``. The suite uses
fixtures, fake adapters, and temporary directories, so no network route is
required by construction; the gate additionally strips proxy environment
variables from child processes and refuses to run any task whose manifest
row declares a live mode. Live exercises are a separate controller-owned
harness (``scripts/v0-exercise``), never this gate.

Candidate path protection is controller business: when
``V0_GATE_BASE_COMMIT`` is set, the gate also runs the protected-path check
against that base using the colon-separated ``V0_GATE_ALLOWED_PATHS``
patterns; without a base it reports that check as not_applicable. When
``V0_GATE_PROTECTED_PATHS`` is additionally set (colon-separated literal
paths from the controller-entry packet), the check runs in general mode:
additions and modifications of regular files within the allowed patterns
are permitted, deletions are rejected, and protected paths must not appear
in the diff. Without it the check keeps the bootstrap add-only shape.

Exercise receipts: for ``V0-M6`` and ``V0-M7`` the gate additionally
requires ``V0_GATE_EXERCISE_RECEIPT`` (colon-separated paths to
exercise-receipt JSON files emitted by the separately authorized,
controller-owned ``scripts/v0-exercise`` harness). Each receipt must
strict-load, validate against the exercise-receipt schema, name the
operation mapped to the task (``V0-X6-READ-SMOKE`` for M6,
``V0-X7-WRITE-SMOKE`` for M7), and record outcome ``PASS``. The gate
validates the receipts only; it never replays the network action. For
every other task the check is not_applicable.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent.parent
sys.path.insert(0, str(TOOLS_DIR))

import check_paths  # noqa: E402
import gstrict  # noqa: E402
import validate_fixtures  # noqa: E402
import validate_roadmap  # noqa: E402
import validators  # noqa: E402

MANIFEST_PATH = REPO_ROOT / "governance" / "manifest" / "v0-task-manifest.json"
REQUIREMENTS_PATH = REPO_ROOT / "governance" / "requirements" / "test-plan-v0.json"
FIXTURES_DIR = REPO_ROOT / "tests" / "governance" / "fixtures"

_PROXY_VARS = [
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "all_proxy",
]


def _python() -> str:
    venv = REPO_ROOT / ".venv" / "bin" / "python3"
    return str(venv) if venv.exists() else "python3"


def _clean_env() -> dict:
    env = dict(os.environ)
    for name in _PROXY_VARS:
        env.pop(name, None)
    return env


def _run(argv: list[str]) -> dict:
    result = subprocess.run(
        argv,
        cwd=REPO_ROOT,
        env=_clean_env(),
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        print(f"| {line}", file=sys.stderr)
    for line in result.stderr.splitlines():
        print(f"| {line}", file=sys.stderr)
    return {
        "argv": argv,
        "exit_code": result.returncode,
        "ok": result.returncode == 0,
    }


def _load_manifest() -> tuple[dict | None, list[str]]:
    try:
        obj = gstrict.strict_loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except gstrict.StrictJsonError as exc:
        return None, [str(exc)]
    problems = validators.validate_artifact("v0-task-manifest", obj)
    return (obj if not problems else None), problems


def _preflight(task_id: str, report: dict) -> bool:
    """Manifest, task-id, and offline-mode checks. False = stop now."""
    manifest, problems = _load_manifest()
    report["checks"].append(
        {
            "id": "task_manifest_valid",
            "ok": not problems,
            "detail": problems,
        }
    )
    if manifest is None:
        return False
    rows = {t["task_id"]: t for t in manifest["tasks"]}
    if task_id not in rows:
        report["checks"].append(
            {
                "id": "task_known",
                "ok": False,
                "detail": [f"unknown task id {task_id!r}"],
            }
        )
        return False
    report["checks"].append({"id": "task_known", "ok": True, "detail": []})
    row = rows[task_id]
    ok = row["network_mode"] == "denied" and row["credential_mode"] == "none"
    report["checks"].append(
        {
            "id": "offline_preflight",
            "ok": ok,
            "detail": [
                "suite runs offline by construction (fixtures, fake "
                "adapters, temporary directories); proxy environment is "
                "stripped from child processes; live modes are refused"
            ]
            if ok
            else [
                "task declares a live network/credential mode; this gate "
                "runs offline modes only"
            ],
        }
    )
    return ok


def run_gate(task_id: str, preflight_only: bool = False) -> dict:
    report: dict = {"task": task_id, "checks": [], "outcome": None}
    if not _preflight(task_id, report):
        report["outcome"] = "CONTRACT_INVALID"
        _attach_requirements(report, task_id)
        return report
    if preflight_only:
        report["outcome"] = "PASS"
        _attach_requirements(report, task_id)
        return report

    checks = [
        ("cumulative_check_suite", ["./scripts/check"]),
        ("governance_tests", [_python(), "-m", "pytest", "tests/governance"]),
    ]
    for check_id, argv in checks:
        result = _run(argv)
        result["id"] = check_id
        report["checks"].append(result)

    fixture_report = validate_fixtures.sweep(FIXTURES_DIR)
    report["checks"].append(
        {
            "id": "governance_fixture_sweep",
            "ok": fixture_report["ok"],
            "detail": [c for c in fixture_report["checks"] if not c["ok"]],
        }
    )

    roadmap_report = validate_roadmap.validate(
        REPO_ROOT / "ROADMAP.md",
        REPO_ROOT / "BUILD.md",
        REPO_ROOT / "docs" / "GOVERNED-LOOP.md",
        REPO_ROOT / "docs" / "OPEN-QUESTIONS.md",
        mode="v0",
    )
    report["checks"].append(
        {
            "id": "roadmap_v0_lane",
            "ok": roadmap_report["ok"],
            "detail": roadmap_report["v0_errors"],
            "reported_slice_defects": roadmap_report["slice_defects"],
        }
    )

    base = os.environ.get("V0_GATE_BASE_COMMIT")
    if base:
        allowed = os.environ.get("V0_GATE_ALLOWED_PATHS", "").split(":")
        allowed = [p for p in allowed if p]
        protected_env = os.environ.get("V0_GATE_PROTECTED_PATHS", "").split(":")
        protected = [p for p in protected_env if p]
        if not allowed:
            report["checks"].append(
                {
                    "id": "protected_paths",
                    "ok": False,
                    "detail": ["base set but V0_GATE_ALLOWED_PATHS is empty"],
                }
            )
        else:
            path_report = check_paths.check_diff(
                REPO_ROOT, base, "HEAD", allowed, protected or None
            )
            report["checks"].append(
                {
                    "id": "protected_paths",
                    "ok": path_report["ok"],
                    "detail": path_report["violations"],
                }
            )
    else:
        report["checks"].append(
            {
                "id": "protected_paths",
                "ok": True,
                "status": "not_applicable",
                "detail": [
                    "no V0_GATE_BASE_COMMIT supplied; the controller runs "
                    "check_paths.py on the candidate commit"
                ],
            }
        )

    report["checks"].append(_check_exercise_receipts(task_id))

    passed = all(c["ok"] for c in report["checks"])
    report["outcome"] = "PASS" if passed else "CHECK_FAILED"
    _attach_requirements(report, task_id)
    return report


# Task -> live-exercise operation whose PASS receipt the done gate requires.
EXERCISE_OPERATIONS = {
    "V0-M6": "V0-X6-READ-SMOKE",
    "V0-M7": "V0-X7-WRITE-SMOKE",
}


def _check_exercise_receipts(task_id: str) -> dict:
    """Validate controller-supplied exercise receipts (M6/M7 only).

    The gate validates receipts emitted by the separately authorized
    exercise harness; it never replays the network action.
    """
    operation = EXERCISE_OPERATIONS.get(task_id)
    if operation is None:
        return {
            "id": "exercise_receipts",
            "ok": True,
            "status": "not_applicable",
            "detail": ["exercise receipts are required only at V0-M6 and V0-M7"],
        }
    problems = []
    raw = os.environ.get("V0_GATE_EXERCISE_RECEIPT", "")
    paths = [p for p in raw.split(":") if p]
    if not paths:
        problems.append(
            f"{task_id} requires V0_GATE_EXERCISE_RECEIPT naming at least one "
            f"PASS receipt from a {operation} exercise"
        )
    for name in paths:
        path = Path(name)
        if not path.is_file():
            problems.append(f"{name}: receipt file not found")
            continue
        obj, errs = validators.load_and_validate("exercise-receipt", path)
        if errs:
            problems.extend(f"{name}: {e}" for e in errs)
            continue
        if obj.get("operation_id") != operation:
            problems.append(
                f"{name}: operation_id must be {operation}, "
                f"got {obj.get('operation_id')!r}"
            )
        if obj.get("outcome") != "PASS":
            problems.append(f"{name}: outcome must be PASS, got {obj.get('outcome')!r}")
    return {"id": "exercise_receipts", "ok": not problems, "detail": problems}


def _attach_requirements(report: dict, task_id: str) -> None:
    mapping = json.loads(REQUIREMENTS_PATH.read_text(encoding="utf-8"))
    order = validators.V0_TASK_ORDER
    try:
        task_index = order.index(task_id)
    except ValueError:
        task_index = -1
    passed = report.get("outcome") == "PASS"
    coverage = []
    for requirement in mapping["requirements"]:
        gate = requirement["gate"]
        applicable = task_index >= 0 and order.index(gate) <= task_index
        if not applicable:
            status = "not_applicable"
        else:
            status = "pass" if passed else "fail"
        coverage.append(
            {
                "requirement_id": requirement["requirement_id"],
                "gate": gate,
                "status": status,
            }
        )
    report["requirement_coverage"] = coverage
    report["requirements_source"] = mapping["source"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="v0-gate",
        description="Root V0 task gate; exits 0 only on PASS.",
    )
    parser.add_argument("task_id")
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="write the JSON report here instead of stdout",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="run manifest/task/offline checks only",
    )
    args = parser.parse_args(argv)
    report = run_gate(args.task_id, args.preflight_only)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.report is not None:
        args.report.write_text(text + "\n", encoding="utf-8")
        print(f"{report['outcome']} (report written to {args.report})")
    else:
        print(text)
    if report["outcome"] == "PASS":
        return 0
    if report["outcome"] == "CONTRACT_INVALID":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
