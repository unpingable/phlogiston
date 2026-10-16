"""Per-kind semantic validators for governance artifacts.

Schema validation (gstrict) covers structure; this module enforces the
cross-field rules from ``docs/GOVERNED-LOOP.md`` that a schema cannot
express: ruling-conditional fields, recommendation/selection membership in
the admissible answer set, forbidden consequence wording, authentication
envelope self-consistency, receipt supersession chains, mode combinations,
path ordering rules, and live-exercise packet/receipt consistency.

Every validator returns a list of human-readable problems; an empty list
means the artifact is valid. Validators never mutate the artifact and never
touch the network, credentials, or donor repositories.

Cross-checking an exercise receipt against its controller-entry packet
(contacted targets a subset of the allow-list, counters within ceilings,
packet/harness digest equality, receipt-schema pin) is controller business
performed at run time; the static checks below deliberately do not attempt
it here.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import common
import gstrict

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"

SCHEMA_FILES = {
    "v0-task-manifest": "task-manifest.schema.json",
    "operator-trust-policy": "operator-trust-policy.schema.json",
    "operator-question-packet": "operator-question-packet.schema.json",
    "operator-decision-receipt": "operator-decision-receipt.schema.json",
    "required-change-set": "required-change-set.schema.json",
    "slice-ratification-packet": "slice-ratification-packet.schema.json",
    "slice-ratification-receipt": "slice-ratification-receipt.schema.json",
    "controller-entry-packet": "controller-entry-packet.schema.json",
    "human-acceptance-receipt": "human-acceptance-receipt.schema.json",
    "execution-evidence-bundle": "execution-evidence-bundle.schema.json",
    "exercise-receipt": "exercise-receipt.schema.json",
}

FORBIDDEN_CONSEQUENCE_WORDING = ("task authorized", "authority gained")

V0_TASK_ORDER = [
    "V0-G0",
    "V0-D1",
    "V0-M1",
    "V0-D2",
    "V0-M2",
    "V0-M2A",
    "V0-M3",
    "V0-M4",
    "V0-M5",
    "V0-M6",
    "V0-M7",
    "V0-M8",
]

ALLOWED_MODE_COMBINATIONS = {
    ("denied", "none"),
    ("public_read", "none"),
    ("nonproduction_write", "nonproduction_external_ref"),
}

AUTHENTICATED_PAYLOAD_FIELDS = {
    "operator-decision-receipt": "decision_payload",
    "slice-ratification-receipt": "ratification_payload",
    "controller-entry-packet": "launch_payload",
    "human-acceptance-receipt": "acceptance_payload",
}

# Contract operation table: each controlled live exercise pins exactly one
# network/credential mode combination.
OPERATION_MODE_REQUIREMENTS = {
    "V0-X6-READ-SMOKE": ("public_read", "none"),
    "V0-X7-WRITE-SMOKE": ("nonproduction_write", "nonproduction_external_ref"),
    "V0-X8-HUMAN-TRIAL": ("nonproduction_write", "nonproduction_external_ref"),
}

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def load_schema_root(kind: str, schema_dir: Path = SCHEMA_DIR) -> dict:
    path = schema_dir / SCHEMA_FILES[kind]
    document = json.loads(path.read_text(encoding="utf-8"))
    return gstrict.load_schema(document)


def validate_artifact(
    kind: str,
    obj: object,
    schema_dir: Path = SCHEMA_DIR,
    packet: dict | None = None,
) -> list[str]:
    """Validate a parsed artifact of *kind*; return a list of problems.

    For ``operator-decision-receipt`` a ``select`` ruling is additionally
    checked against *packet* (the parsed operator-question packet it pins)
    when one is supplied: the packet digest must match and the selected
    answer must be admissible.
    """
    if kind not in SCHEMA_FILES:
        return [f"unknown artifact kind {kind!r}"]
    root = load_schema_root(kind, schema_dir)
    problems = gstrict.validate(obj, root)
    if problems or not isinstance(obj, dict):
        return problems
    semantic = _SEMANTIC_CHECKS.get(kind)
    if semantic is not None:
        problems.extend(semantic(obj))
    if kind == "operator-decision-receipt" and packet is not None:
        problems.extend(_check_receipt_against_packet(obj, packet))
    return problems


def load_and_validate(
    kind: str,
    path: Path,
    schema_dir: Path = SCHEMA_DIR,
    packet: dict | None = None,
) -> tuple[object | None, list[str]]:
    """Strict-load a JSON artifact file and validate it."""
    try:
        obj = gstrict.strict_loads(path.read_text(encoding="utf-8"))
    except gstrict.StrictJsonError as exc:
        return None, [str(exc)]
    return obj, validate_artifact(kind, obj, schema_dir, packet)


# --- shared semantic helpers ------------------------------------------------


def _check_authentication(obj: dict, payload_field: str) -> list[str]:
    problems = []
    payload = obj.get(payload_field)
    auth = obj.get("authentication")
    if not isinstance(payload, dict) or not isinstance(auth, dict):
        return problems  # structural problems already reported by the schema
    expected = common.canonical_sha256(payload)
    if auth.get("payload_sha256") != expected:
        problems.append(
            "authentication.payload_sha256 does not equal the canonical "
            f"{payload_field} digest"
        )
    if expected == common.canonical_sha256(obj):
        problems.append("authentication must not hash its own enclosing bytes")
    operator = payload.get("operator_id")
    if operator is not None and operator != auth.get("attested_principal"):
        problems.append("payload operator_id must equal attested_principal")
    return problems


def _check_path_list(values: object, where: str, allow_globs: bool) -> list[str]:
    problems = []
    if not isinstance(values, list):
        return problems
    paths = [v for v in values if isinstance(v, str)]
    if paths != sorted(paths):
        problems.append(f"{where} must be lexically sorted")
    for path in values:
        if not isinstance(path, str):
            continue
        core = path[:-3] if allow_globs and path.endswith("/**") else path
        if allow_globs and "**" in core:
            problems.append(f"{where} entry {path!r}: '**' only as trailing")
        if core.startswith("/") or "\\" in core or "//" in core:
            problems.append(f"{where} entry {path!r}: not repository-relative")
        if any(seg in ("", ".", "..") for seg in core.split("/")):
            problems.append(f"{where} entry {path!r}: traversal or empty")
    return problems


def _check_sorted_strings(values: object, where: str) -> list[str]:
    problems = []
    if not isinstance(values, list):
        return problems
    strings = [v for v in values if isinstance(v, str)]
    if strings != sorted(strings):
        problems.append(f"{where} must be lexically sorted")
    return problems


def _check_origin(value: object, where: str) -> list[str]:
    """An origin is exactly ``scheme://host[:port]`` — nothing else."""
    if not isinstance(value, str):
        return []
    try:
        parts = urlsplit(value)
        parts.port  # accessing .port raises ValueError on an invalid port
    except ValueError:
        return [f"{where} entry {value!r}: not a valid origin"]
    problems = []
    host = parts.hostname
    if parts.scheme in ("http", "ws"):
        if host not in LOOPBACK_HOSTS:
            problems.append(
                f"{where} entry {value!r}: http/ws allowed only for "
                "loopback hosts (127.0.0.1, ::1, localhost)"
            )
    elif parts.scheme not in ("https", "wss"):
        problems.append(f"{where} entry {value!r}: scheme must be https or wss")
    if not host:
        problems.append(f"{where} entry {value!r}: missing host")
    if parts.username is not None or parts.password is not None:
        problems.append(f"{where} entry {value!r}: userinfo is not permitted")
    if parts.path or parts.query or parts.fragment:
        problems.append(
            f"{where} entry {value!r}: path, query, and fragment are not permitted"
        )
    return problems


# --- per-kind semantic checks ------------------------------------------------


def _check_task_manifest(obj: dict) -> list[str]:
    problems = []
    tasks = obj.get("tasks", [])
    ids = [t.get("task_id") for t in tasks if isinstance(t, dict)]
    if ids != V0_TASK_ORDER:
        problems.append(
            "tasks must list exactly the contract V0 order: " + ", ".join(V0_TASK_ORDER)
        )
        return problems
    seen: set[str] = set()
    for task in tasks:
        task_id = task["task_id"]
        for prereq in task.get("prerequisites", []):
            if prereq not in seen:
                problems.append(
                    f"{task_id}: prerequisite {prereq} is not an earlier task"
                )
        expected = f"./scripts/v0-gate {task_id}"
        if task.get("done_command") != expected:
            problems.append(f"{task_id}: done_command must be {expected!r}")
        seen.add(task_id)
    return problems


def _check_trust_policy(obj: dict) -> list[str]:
    return []


def _check_question_packet(obj: dict) -> list[str]:
    problems = []
    answers = obj.get("answers", [])
    answer_ids = [a.get("answer_id") for a in answers if isinstance(a, dict)]
    if len(set(answer_ids)) != len(answer_ids):
        problems.append("duplicate answer IDs")
    excluded = obj.get("excluded_answers", [])
    for item in excluded:
        if isinstance(item, dict) and item.get("answer_id") in answer_ids:
            problems.append(
                f"excluded answer {item.get('answer_id')!r} is also admissible"
            )
    recommendation = obj.get("recommendation", {})
    if isinstance(recommendation, dict):
        choice = recommendation.get("answer_id")
        if choice != "no_recommendation" and choice not in answer_ids:
            problems.append("recommendation names an answer outside the admissible set")
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        for text in common.collect_strings(answer.get("consequences", {})):
            lowered = text.lower()
            for wording in FORBIDDEN_CONSEQUENCE_WORDING:
                if wording in lowered:
                    problems.append(
                        f"answer {answer.get('answer_id')!r} consequence uses "
                        f"forbidden wording {wording!r}"
                    )
    return problems


_RULING_FIELDS = {
    "select": {
        "required": [
            "answer_id",
            "required_change_set_id",
            "required_change_set_sha256",
        ],
        "allowed": [
            "answer_id",
            "required_change_set_id",
            "required_change_set_sha256",
        ],
    },
    "defer": {
        "required": [],
        "allowed": ["revisit_trigger", "revisit_deadline", "requested_evidence"],
    },
    "reject_packet": {
        "required": ["reason_class", "replacement_packet"],
        "allowed": ["reason_class", "replacement_packet"],
    },
    "repack_required": {
        "required": ["novel_evidence"],
        "allowed": ["novel_evidence"],
    },
}

_ALL_CONDITIONAL = sorted(
    {field for rule in _RULING_FIELDS.values() for field in rule["allowed"]}
)


def _check_decision_receipt(obj: dict) -> list[str]:
    problems = _check_authentication(obj, "decision_payload")
    payload = obj.get("decision_payload")
    if not isinstance(payload, dict):
        return problems
    ruling = payload.get("ruling")
    rule = _RULING_FIELDS.get(ruling)
    if rule is None:
        return problems  # enum problem already reported by the schema
    for field in rule["required"]:
        if field not in payload:
            problems.append(f"{ruling} ruling requires {field!r}")
    for field in _ALL_CONDITIONAL:
        if field not in rule["allowed"] and field in payload:
            problems.append(f"{ruling} ruling forbids {field!r}")
    if ruling == "select":
        cs_id = payload.get("required_change_set_id")
        cs_digest = payload.get("required_change_set_sha256")
        if (cs_id == "not_applicable") != (cs_digest == "not_applicable"):
            problems.append(
                "required_change_set id and digest must agree on not_applicable"
            )
    if ruling == "defer" and not (
        payload.get("revisit_trigger") or payload.get("revisit_deadline")
    ):
        problems.append("defer ruling requires a revisit trigger or deadline")
    return problems


def _check_receipt_against_packet(receipt: dict, packet: dict) -> list[str]:
    problems = []
    payload = receipt.get("decision_payload", {})
    if not isinstance(payload, dict):
        return problems
    packet_digest = common.canonical_sha256(packet)
    if payload.get("packet_sha256") != packet_digest:
        problems.append("receipt packet_sha256 does not match the packet")
    if payload.get("ruling") == "select":
        answer_ids = [
            a.get("answer_id") for a in packet.get("answers", []) if isinstance(a, dict)
        ]
        if payload.get("answer_id") not in answer_ids:
            problems.append("selected answer is outside the admissible set")
        if payload.get("question_id") != packet.get("question_id"):
            problems.append("receipt question_id disagrees with the packet")
    return problems


def check_receipt_set(receipts: list[dict]) -> list[str]:
    """Check a set of decision receipts for supersession conflicts.

    Two receipts over the same question conflict unless one names the other
    in its ``supersedes`` field with the exact digest. Returns problems.
    """
    problems = []
    by_question: dict[str, list[dict]] = {}
    for receipt in receipts:
        payload = receipt.get("decision_payload", {})
        if isinstance(payload, dict):
            by_question.setdefault(payload.get("question_id", ""), []).append(receipt)
    for question, group in by_question.items():
        if len(group) < 2:
            continue
        digests = {r.get("receipt_id"): common.canonical_sha256(r) for r in group}
        superseded = set()
        for receipt in group:
            sup = receipt.get("supersedes")
            if isinstance(sup, dict):
                target = sup.get("receipt_id")
                if digests.get(target) != sup.get("receipt_sha256"):
                    problems.append(
                        f"{receipt.get('receipt_id')}: supersedes digest does "
                        f"not match receipt {target!r}"
                    )
                superseded.add(target)
        active = [r for r in group if r.get("receipt_id") not in superseded]
        if len(active) > 1:
            ids = sorted(r.get("receipt_id", "") for r in active)
            problems.append(
                f"{question}: conflicting active receipts without an "
                f"explicit supersession chain: {ids}"
            )
    return problems


def _check_change_set(obj: dict) -> list[str]:
    problems = []
    targets = obj.get("targets", [])
    paths = [t.get("path") for t in targets if isinstance(t, dict)]
    if len(set(paths)) != len(paths):
        problems.append("duplicate target paths")
    for key in ("packet_sha256", "receipt_sha256"):
        for where in common.find_key_paths(obj, key):
            problems.append(f"change set must not embed a descendant digest ({where})")
    return problems


def _check_slice_ratification_packet(obj: dict) -> list[str]:
    problems = []
    amendments = obj.get("amendments", [])
    paths = [a.get("path") for a in amendments if isinstance(a, dict)]
    if len(set(paths)) != len(paths):
        problems.append("duplicate amendment paths")
    return problems


def _check_slice_ratification_receipt(obj: dict) -> list[str]:
    return _check_authentication(obj, "ratification_payload")


def _check_controller_entry(obj: dict) -> list[str]:
    problems = _check_authentication(obj, "launch_payload")
    payload = obj.get("launch_payload")
    if not isinstance(payload, dict):
        return problems
    problems.extend(
        _check_path_list(payload.get("allowed_paths"), "allowed_paths", True)
    )
    problems.extend(
        _check_path_list(payload.get("protected_paths"), "protected_paths", False)
    )
    inputs = payload.get("governance_inputs", [])
    paths = [i.get("path") for i in inputs if isinstance(i, dict)]
    if paths != sorted(paths):
        problems.append("governance_inputs must be lexically path-sorted")
    if len(set(paths)) != len(paths):
        problems.append("duplicate governance_inputs paths")
    policy = payload.get("evidence_policy", {})
    if isinstance(policy, dict) and policy.get("readback_required") is not True:
        problems.append("evidence_policy.readback_required must be true")
    combination = (payload.get("network_mode"), payload.get("credential_mode"))
    if combination not in ALLOWED_MODE_COMBINATIONS:
        problems.append(f"network/credential mode combination {combination} is invalid")
    for task_id in payload.get("task_ids", []):
        if task_id != "next" and task_id not in V0_TASK_ORDER:
            problems.append(f"unknown task id {task_id!r}")
    problems.extend(_check_live_exercise(payload))
    return problems


def _check_live_exercise(payload: dict) -> list[str]:
    problems = []
    live = payload.get("live_exercise")
    network_mode = payload.get("network_mode")
    if live is None:
        if network_mode != "denied":
            problems.append(
                "live_exercise is required when network_mode is not 'denied'"
            )
        return problems
    if not isinstance(live, dict):
        return problems  # structural problems already reported by the schema
    if network_mode == "denied":
        problems.append("live_exercise is forbidden when network_mode is 'denied'")
        return problems
    operation = live.get("operation_id")
    required_modes = OPERATION_MODE_REQUIREMENTS.get(operation)
    if required_modes is not None:
        actual = (network_mode, payload.get("credential_mode"))
        if actual != required_modes:
            problems.append(
                f"{operation} requires network/credential modes "
                f"{required_modes}, not {actual}"
            )
    if operation == "V0-X6-READ-SMOKE":
        ceilings = live.get("ceilings", {})
        if isinstance(ceilings, dict) and ceilings.get("max_writes") != 0:
            problems.append("V0-X6-READ-SMOKE requires ceilings.max_writes == 0")
    for field in ("target_allow_list", "subject_allow_list", "allowed_record_kinds"):
        problems.extend(
            _check_sorted_strings(live.get(field), f"live_exercise.{field}")
        )
    for origin in live.get("target_allow_list", []):
        problems.extend(_check_origin(origin, "live_exercise.target_allow_list"))
    return problems


def _check_human_acceptance(obj: dict) -> list[str]:
    problems = _check_authentication(obj, "acceptance_payload")
    payload = obj.get("acceptance_payload")
    if not isinstance(payload, dict):
        return problems
    purpose = payload.get("purpose")
    verdict = payload.get("verdict")
    if purpose in ("bootstrap_outputs", "contract_freeze"):
        if verdict not in ("accepted", "rejected"):
            problems.append(f"{purpose} verdict must be accepted or rejected")
    subjects = payload.get("subjects", [])
    seen_paths = [
        s.get("path") for s in subjects if isinstance(s, dict) and "path" in s
    ]
    if len(set(seen_paths)) != len(seen_paths):
        problems.append("duplicate subject paths")
    return problems


def _check_evidence_bundle(obj: dict) -> list[str]:
    problems = []
    if obj.get("clean_tree") is not True:
        problems.append("clean_tree must be true")
    topology = obj.get("commit_topology", {})
    if isinstance(topology, dict) and topology.get("commit_count") != 1:
        problems.append("a task candidate must be exactly one commit")
    outputs = obj.get("candidate_outputs", [])
    paths = [o.get("path") for o in outputs if isinstance(o, dict)]
    if len(set(paths)) != len(paths):
        problems.append("duplicate candidate_outputs paths")
    if obj.get("outcome") == "PASS":
        coverage = obj.get("requirement_coverage", [])
        failing = [
            c.get("requirement_id")
            for c in coverage
            if isinstance(c, dict) and c.get("status") == "fail"
        ]
        if failing:
            problems.append(f"PASS outcome with failing requirements: {failing}")
    return problems


def _check_exercise_receipt(obj: dict) -> list[str]:
    problems = []
    counters = obj.get("counters", {})
    if (
        obj.get("outcome") == "PASS"
        and obj.get("operation_id") == "V0-X6-READ-SMOKE"
        and isinstance(counters, dict)
        and counters.get("writes") not in (0, None)
    ):
        problems.append("V0-X6-READ-SMOKE PASS outcome with counters.writes > 0")
    started = obj.get("started_at")
    ended = obj.get("ended_at")
    if isinstance(started, str) and isinstance(ended, str) and ended < started:
        problems.append("ended_at must be at or after started_at")
    problems.extend(
        _check_sorted_strings(obj.get("targets_contacted"), "targets_contacted")
    )
    return problems


_SEMANTIC_CHECKS = {
    "v0-task-manifest": _check_task_manifest,
    "operator-trust-policy": _check_trust_policy,
    "operator-question-packet": _check_question_packet,
    "operator-decision-receipt": _check_decision_receipt,
    "required-change-set": _check_change_set,
    "slice-ratification-packet": _check_slice_ratification_packet,
    "slice-ratification-receipt": _check_slice_ratification_receipt,
    "controller-entry-packet": _check_controller_entry,
    "human-acceptance-receipt": _check_human_acceptance,
    "execution-evidence-bundle": _check_evidence_bundle,
    "exercise-receipt": _check_exercise_receipt,
}
