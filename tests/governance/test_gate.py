"""Smoke tests for the root gate.

The full gate run is performed by the controller's task transaction (and
manually before candidate submission); these tests cover the cheap,
deterministic failure and preflight modes in temporary directories.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

GATE = Path(__file__).resolve().parents[2] / "scripts" / "v0-gate"


def _run_gate(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("V0_GATE_BASE_COMMIT", None)
    return subprocess.run(
        [sys.executable, str(GATE), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_gate_is_executable():
    assert os.access(GATE, os.X_OK)


def test_unknown_task_id_rejected():
    result = _run_gate("V0-BOGUS")
    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert report["outcome"] == "CONTRACT_INVALID"
    assert any(c["id"] == "task_known" and not c["ok"] for c in report["checks"])


def test_preflight_only_passes_for_g0():
    result = _run_gate("V0-G0", "--preflight-only")
    assert result.returncode == 0, result.stderr[-2000:]
    report = json.loads(result.stdout)
    assert report["outcome"] == "PASS"
    check_ids = {c["id"] for c in report["checks"]}
    assert {
        "task_manifest_valid",
        "task_known",
        "offline_preflight",
    } <= check_ids


def test_preflight_covers_g0_requirements_only():
    result = _run_gate("V0-G0", "--preflight-only")
    report = json.loads(result.stdout)
    applicable = [
        c for c in report["requirement_coverage"] if c["status"] != "not_applicable"
    ]
    assert applicable
    assert all(c["gate"] == "V0-G0" for c in applicable)


def test_preflight_for_later_task_marks_g0_applicable():
    result = _run_gate("V0-M2", "--preflight-only")
    assert result.returncode == 0, result.stderr[-2000:]
    report = json.loads(result.stdout)
    statuses = {
        c["requirement_id"]: c["status"] for c in report["requirement_coverage"]
    }
    assert statuses["TP-GOV-01"] == "pass"
    assert statuses["TP-M2A-01"] == "not_applicable"


def test_report_flag_writes_machine_readable_file(tmp_path):
    report_path = tmp_path / "report.json"
    result = _run_gate("V0-G0", "--preflight-only", "--report", str(report_path))
    assert result.returncode == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["task"] == "V0-G0"
    assert report["outcome"] == "PASS"
