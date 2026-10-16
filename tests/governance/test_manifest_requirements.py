"""Task manifest, requirement mapping, and schema document tests."""

from __future__ import annotations

import json
from collections import Counter

import gstrict
import validators

EXPECTED_COUNTS = {
    "TP-GOV": 22,
    "TP-SCHEMA": 6,
    "TP-STATE": 19,
    "TP-SQL": 19,
    "TP-WEB": 14,
    "TP-DAEMON": 10,
    "TP-BOUND": 5,
    "TP-ACCEPT": 1,
    "TP-M2A": 16,
}


def test_manifest_matches_contract_task_queue(repo_root):
    manifest = json.loads(
        (repo_root / "governance" / "manifest" / "v0-task-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    problems = validators.validate_artifact("v0-task-manifest", manifest)
    assert not problems
    ids = [t["task_id"] for t in manifest["tasks"]]
    assert ids == validators.V0_TASK_ORDER
    for task in manifest["tasks"]:
        assert task["done_command"] == f"./scripts/v0-gate {task['task_id']}"
        assert task["network_mode"] == "denied"
        assert task["credential_mode"] == "none"
    # Spot-check the contract table's human blockers.
    rows = {t["task_id"]: t for t in manifest["tasks"]}
    assert any("OQ-7" in b for b in rows["V0-G0"]["human_blockers"])
    assert any("OQ-5" in b for b in rows["V0-M4"]["human_blockers"])
    assert any("OQ-2" in b for b in rows["V0-M6"]["human_blockers"])
    assert rows["V0-M7"]["prerequisites"] == ["V0-M6"]


def test_requirement_mapping_complete_and_consistent(repo_root):
    mapping = json.loads(
        (repo_root / "governance" / "requirements" / "test-plan-v0.json").read_text(
            encoding="utf-8"
        )
    )
    requirements = mapping["requirements"]
    ids = [r["requirement_id"] for r in requirements]
    assert len(ids) == len(set(ids))
    counts = Counter(i.rsplit("-", 1)[0] for i in ids)
    assert dict(counts) == EXPECTED_COUNTS
    for requirement in requirements:
        assert requirement["gate"] in validators.V0_TASK_ORDER
        assert requirement["summary"].strip()
        assert not gstrict.is_placeholder(requirement["summary"])
    # Numbering is contiguous per group.
    for prefix, count in EXPECTED_COUNTS.items():
        expected = {f"{prefix}-{n:02d}" for n in range(1, count + 1)}
        assert expected <= set(ids)


def test_every_schema_document_loads(repo_root):
    for name in validators.SCHEMA_FILES.values():
        document = json.loads(
            (repo_root / "governance" / "schemas" / name).read_text(encoding="utf-8")
        )
        gstrict.load_schema(document)


def test_gstrict_rejects_unknown_schema_keys(repo_root):
    document = {
        "schema": "gstrict-v1",
        "id": "bad",
        "version": "1",
        "root": {"type": "object", "fields": {}, "bogus": True},
    }
    try:
        gstrict.load_schema(document)
    except gstrict.SchemaError:
        return
    raise AssertionError("schema with unknown keys was accepted")
