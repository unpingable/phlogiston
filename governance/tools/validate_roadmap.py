#!/usr/bin/env python3
"""Roadmap/authorization validator ("roadmap linter").

Parses ROADMAP.md slice entries (ID/Status, Type, Blocking OQs, the literal
``Authorized:`` line), cross-checks blocking OQ handles against
docs/OPEN-QUESTIONS.md and the OQ-R register, verifies ``Authorized``
agreement with BUILD.md, and strictly parses BUILD.md's governed-execution
authorization state (recomputing the pinned contract digest). The state is
either the single-use authorization block or, after the accepted bootstrap
outputs, the consumption record that replaces it per the ratified contract.

Modes:

- ``v0`` (default): V0-lane findings (authorization block problems) fail the
  run; slice-lane defects are reported but do not fail V0 task selection.
- ``slice``: every finding fails the run; used at the V0-to-slice
  transition, which requires a completely valid roadmap AST.

The validator reports the roadmap's known normalization defects. It never
repairs, reinterprets, or rewrites them.

Usage: validate_roadmap.py [--mode v0|slice] [--roadmap PATH]
       [--build PATH] [--contract PATH] [--open-questions PATH]

Prints a JSON report to stdout; exit 0 when the selected lane is clean.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

STATUS_ENUM = ("parked", "candidate", "ratified", "done")
BASE_TYPE_ENUM = ("testimony", "guarantee", "mixed")
ALLOWED_TYPE_SPELLINGS = BASE_TYPE_ENUM + ("testimony · thesis-experiment",)

# Field labels every slice entry must carry, in the contract's fixed order.
REQUIRED_FIELDS = [
    "ID / Status",
    "Type",
    "Thesis line",
    "Adds",
    "Still excludes",
    "Entry gate (HUMAN)",
    "Blocking OQs",
    "Donor assets",
    "Replay seam obligation",
    "Deliverables",
    "Task ladder (MACHINE)",
    "Exit review (HUMAN)",
    "Evidence log",
]

BLOCK_KEYS = {
    "authorization_id",
    "task",
    "decision",
    "scope",
    "contract_sha256",
    "single_use",
}

# Keys of the consumption record that replaces the single-use block once the
# bootstrap-output human-acceptance receipt exists (contract: the block is
# removed in the governance commit recording that receipt).
CONSUMED_BLOCK_KEYS = {
    "authorization_id",
    "task",
    "receipt_id",
    "contract_sha256",
}
CONSUMED_RECEIPT_RE = re.compile(r"^HAR-V0-G0-\d{4}-\d{2}-\d{2}-\d{2}$")

OQ_TOKEN_RE = re.compile(r"\bOQ-(?:R)?\d+\b")
SECTION_RE = re.compile(r"^### (S\d+) — ")
FIELD_RE = re.compile(r"^- \*\*(.+?):\*\*\s?(.*)$")
AUTHORIZED_RE = re.compile(r"^Authorized: (yes|no)\s*$", re.MULTILINE)
REQUIRES_RE = re.compile(r"[Rr]equires?\s+((?:S\d+[^.\n]*)?)")
SLICE_REF_RE = re.compile(r"\bS\d+\b")
AUTHORITY_SIGNAL_RE = re.compile(
    r"`app\.bsky\.(?!feed\.post`)[^`]+`|emitted by `communityd`"
)
PARENS_RE = re.compile(r"\([^()]*\)")


def _finding(lane: str, code: str, slice_id: str | None, detail: str) -> dict:
    return {"lane": lane, "code": code, "slice": slice_id, "detail": detail}


def base_type_of(text: str) -> str | None:
    """Extract the strict base type enum from a possibly qualified spelling."""
    text = text.strip()
    for base in BASE_TYPE_ENUM:
        if (
            text == base
            or text.startswith(base + " ")
            or text.startswith(base + ",")
            or text.startswith(base + "-")
        ):
            return base
    return None


class SliceEntry:
    def __init__(self, slice_id: str, body: str) -> None:
        self.slice_id = slice_id
        self.body = body
        self.fields: dict[str, str] = {}
        self.field_order: list[str] = []
        self.authorized: str | None = None
        self._parse()

    def _parse(self) -> None:
        current: str | None = None
        for line in self.body.splitlines():
            match = FIELD_RE.match(line)
            if match:
                label, value = match.group(1), match.group(2)
                if label in self.fields:
                    self.field_order.append(label + " ")  # mark duplicate
                    current = None
                else:
                    self.fields[label] = value.strip()
                    self.field_order.append(label)
                    current = label
                continue
            if AUTHORIZED_RE.match(line) or line.startswith(("---", "#")):
                current = None
                continue
            if current is not None and line.strip():
                self.fields[current] += " " + line.strip()
        authorized = AUTHORIZED_RE.search(self.body)
        if authorized:
            self.authorized = authorized.group(1)

    @property
    def duplicates(self) -> list[str]:
        return [label.strip() for label in self.field_order if label.endswith(" ")]

    @property
    def status_text(self) -> str:
        raw = self.fields.get("ID / Status", "")
        if " — " in raw:
            return raw.split(" — ", 1)[1].strip()
        return raw.strip()

    @property
    def type_text(self) -> str:
        return self.fields.get("Type", "").strip()

    @property
    def base_type(self) -> str | None:
        return base_type_of(self.type_text)


def parse_roadmap(text: str) -> tuple[list[SliceEntry], dict[str, dict]]:
    """Return (slice sections in document order, overview table rows)."""
    sections: list[SliceEntry] = []
    current_id = None
    current_lines: list[str] = []
    for line in text.splitlines():
        match = SECTION_RE.match(line)
        if match or (current_id is not None and line.startswith("## ")):
            if current_id is not None:
                sections.append(SliceEntry(current_id, "\n".join(current_lines)))
            current_lines = []
            current_id = match.group(1) if match else None
        elif current_id is not None:
            current_lines.append(line)
    if current_id is not None:
        sections.append(SliceEntry(current_id, "\n".join(current_lines)))

    overview: dict[str, dict] = {}
    in_table = False
    for line in text.splitlines():
        if line.startswith("| ID | Name |"):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                in_table = False
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) == 6 and cells[0].startswith("S") and cells[0][1:].isdigit():
                overview[cells[0]] = {
                    "name": cells[1],
                    "tier": cells[2],
                    "type": cells[3],
                    "status": cells[4],
                    "blocking": cells[5],
                }
    return sections, overview


def _parse_blocks(
    text: str, open_marker: str, close_marker: str, allowed_keys: set[str]
) -> tuple[list[dict], list[str]]:
    """Parse one governed-execution block family; return (blocks, problems)."""
    problems = []
    blocks = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if lines[index].strip() == open_marker:
            block: dict[str, str] = {}
            closed = False
            index += 1
            while index < len(lines):
                line = lines[index].strip()
                if line == close_marker:
                    closed = True
                    break
                if not line:
                    index += 1
                    continue
                match = re.match(r'^([a-z0-9_]+) = "(.*)"$', line)
                if not match:
                    match_bool = re.match(r"^([a-z0-9_]+) = (true|false)$", line)
                    if match_bool:
                        key, value = match_bool.groups()
                    else:
                        problems.append(f"unparseable block line: {line!r}")
                        index += 1
                        continue
                else:
                    key, value = match.groups()
                if key in block:
                    problems.append(f"duplicate block key {key!r}")
                if key not in allowed_keys:
                    problems.append(f"unknown block key {key!r}")
                block[key] = value
                index += 1
            if not closed:
                problems.append("unterminated governed-execution block")
            blocks.append(block)
        index += 1
    return blocks, problems


def parse_build_block(text: str) -> tuple[list[dict], list[str]]:
    """Parse governed-execution authorization blocks."""
    return _parse_blocks(
        text,
        "<!-- governed-execution:v1 -->",
        "<!-- /governed-execution -->",
        BLOCK_KEYS,
    )


def parse_consumed_block(text: str) -> tuple[list[dict], list[str]]:
    """Parse governed-execution consumption records."""
    return _parse_blocks(
        text,
        "<!-- governed-execution-consumed:v1 -->",
        "<!-- /governed-execution-consumed -->",
        CONSUMED_BLOCK_KEYS,
    )


def _strip_parens(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = PARENS_RE.sub("", text)
    return text


def _blocking_tokens(text: str) -> list[str]:
    return OQ_TOKEN_RE.findall(_strip_parens(text))


def validate(
    roadmap_path: Path,
    build_path: Path,
    contract_path: Path,
    open_questions_path: Path,
    mode: str = "v0",
) -> dict:
    findings: list[dict] = []

    build_text = build_path.read_text(encoding="utf-8")
    roadmap_text = roadmap_path.read_text(encoding="utf-8")
    oq_text = open_questions_path.read_text(encoding="utf-8")
    contract_digest = hashlib.sha256(contract_path.read_bytes()).hexdigest()

    # --- V0 lane: the BUILD.md governed-execution authorization state ------
    # Exactly one of the single-use authorization block (pre-acceptance) or
    # the consumption record (post-acceptance, per the ratified contract)
    # must be present.
    blocks, block_problems = parse_build_block(build_text)
    consumed, consumed_problems = parse_consumed_block(build_text)
    for problem in block_problems + consumed_problems:
        findings.append(_finding("v0", "build_block_syntax", None, problem))
    if len(blocks) + len(consumed) != 1:
        findings.append(
            _finding(
                "v0",
                "build_block_count",
                None,
                f"expected exactly one governed-execution block or consumption "
                f"record, found {len(blocks)} block(s) and {len(consumed)} "
                f"consumption record(s)",
            )
        )
    for block in blocks:
        missing = BLOCK_KEYS - set(block)
        if missing:
            findings.append(
                _finding(
                    "v0",
                    "build_block_missing_keys",
                    None,
                    f"missing keys {sorted(missing)}",
                )
            )
        if block.get("decision") != "authorized":
            findings.append(
                _finding("v0", "build_block_decision", None, "decision != authorized")
            )
        if block.get("single_use") != "true":
            findings.append(
                _finding("v0", "build_block_single_use", None, "single_use != true")
            )
        pinned = block.get("contract_sha256", "")
        if pinned != f"sha256:{contract_digest}":
            findings.append(
                _finding(
                    "v0",
                    "build_block_contract_digest",
                    None,
                    "contract_sha256 does not match the contract file digest",
                )
            )
    for record in consumed:
        missing = CONSUMED_BLOCK_KEYS - set(record)
        if missing:
            findings.append(
                _finding(
                    "v0",
                    "build_block_missing_keys",
                    None,
                    f"consumption record missing keys {sorted(missing)}",
                )
            )
        if not CONSUMED_RECEIPT_RE.match(record.get("receipt_id", "")):
            findings.append(
                _finding(
                    "v0",
                    "consumed_receipt_id",
                    None,
                    "consumption record receipt_id is not a V0-G0 "
                    "human-acceptance receipt ID",
                )
            )
        pinned = record.get("contract_sha256", "")
        if pinned != f"sha256:{contract_digest}":
            findings.append(
                _finding(
                    "v0",
                    "build_block_contract_digest",
                    None,
                    "consumption record contract_sha256 does not match the "
                    "contract file digest",
                )
            )
    build_names_g0 = any(block.get("task") == "V0-G0" for block in blocks) or any(
        record.get("task") == "V0-G0" for record in consumed
    )

    # --- slice lane -------------------------------------------------------
    sections, overview = parse_roadmap(roadmap_text)
    oq_register = set(re.findall(r"^## (OQ-\d+) ", oq_text, re.MULTILINE))
    oq_r_register = set(re.findall(r"\*\*(OQ-R\d+) —", roadmap_text))

    section_ids = [s.slice_id for s in sections]
    if len(set(section_ids)) != len(section_ids):
        findings.append(
            _finding("slice", "duplicate_slice_section", None, "duplicate sections")
        )
    for slice_id in sorted(set(overview) - set(section_ids)):
        findings.append(
            _finding("slice", "overview_without_section", slice_id, "no slice section")
        )
    for slice_id in sorted(set(section_ids) - set(overview)):
        findings.append(
            _finding("slice", "section_without_overview", slice_id, "no overview row")
        )

    for entry in sections:
        sid = entry.slice_id
        for duplicate in entry.duplicates:
            findings.append(
                _finding("slice", "duplicate_field", sid, f"field {duplicate!r}")
            )
        for label in entry.fields:
            if label not in REQUIRED_FIELDS:
                findings.append(
                    _finding("slice", "unknown_field", sid, f"field {label!r}")
                )
        for label in REQUIRED_FIELDS:
            if label not in entry.fields:
                findings.append(
                    _finding("slice", "missing_field", sid, f"field {label!r}")
                )

        status = entry.status_text
        if status not in STATUS_ENUM:
            base = status.split(" ", 1)[0]
            code = "status_qualifier" if base in STATUS_ENUM else "unknown_status"
            findings.append(
                _finding("slice", code, sid, f"status {status!r} is not canonical")
            )

        type_text = entry.type_text
        base_type = entry.base_type
        if base_type is None:
            findings.append(
                _finding(
                    "slice", "unknown_type", sid, f"type {type_text!r} unparseable"
                )
            )
        elif type_text not in ALLOWED_TYPE_SPELLINGS:
            findings.append(
                _finding(
                    "slice",
                    "type_qualifier",
                    sid,
                    f"type {type_text!r} is not a canonical spelling",
                )
            )

        if base_type == "testimony" and AUTHORITY_SIGNAL_RE.search(entry.body):
            findings.append(
                _finding(
                    "slice",
                    "type_authority_mismatch",
                    sid,
                    "testimony slice describes an authority-bearing write",
                )
            )

        if entry.authorized is None:
            findings.append(
                _finding(
                    "slice", "missing_authorized", sid, "no literal Authorized: line"
                )
            )
        elif entry.authorized == "yes":
            findings.append(
                _finding(
                    "slice",
                    "authorized_without_build_row",
                    sid,
                    "Authorized: yes but BUILD.md names no positive slice row",
                )
            )

        blocking_field = entry.fields.get("Blocking OQs", "")
        for token in _blocking_tokens(blocking_field):
            if token.startswith("OQ-R"):
                if token == "OQ-R13":
                    findings.append(
                        _finding(
                            "slice",
                            "blocking_promoted_alias",
                            sid,
                            "OQ-R13 is a historical alias and must not appear",
                        )
                    )
                elif token not in oq_r_register:
                    findings.append(
                        _finding(
                            "slice",
                            "unknown_blocking_oq",
                            sid,
                            f"{token} not in the OQ-R register",
                        )
                    )
            elif token not in oq_register:
                findings.append(
                    _finding(
                        "slice",
                        "unknown_blocking_oq",
                        sid,
                        f"{token} not in docs/OPEN-QUESTIONS.md",
                    )
                )

        # Dependency consistency: entry-gate requirements vs body claims.
        gate_text = entry.fields.get("Entry gate (HUMAN)", "")
        gate_requires: set[str] = set()
        for match in REQUIRES_RE.finditer(gate_text):
            gate_requires.update(SLICE_REF_RE.findall(match.group(1)))
        body_requires: set[str] = set()
        for match in REQUIRES_RE.finditer(entry.body):
            body_requires.update(SLICE_REF_RE.findall(match.group(1)))
        unlisted = body_requires - gate_requires - {sid}
        for dep in sorted(unlisted):
            later = ""
            if dep in section_ids and section_ids.index(dep) > section_ids.index(sid):
                later = " (later on the ladder)"
            findings.append(
                _finding(
                    "slice",
                    "dependency_inconsistency",
                    sid,
                    f"requires {dep} outside the entry gate{later}",
                )
            )

        # Overview table agreement (base enums only; spellings are defects).
        row = overview.get(sid)
        if row is not None:
            row_status_base = row["status"].split(" ", 1)[0]
            if row_status_base != status.split(" ", 1)[0]:
                findings.append(
                    _finding(
                        "slice",
                        "overview_status_mismatch",
                        sid,
                        f"overview {row['status']!r} vs section {status!r}",
                    )
                )
            row_type_base = base_type_of(row["type"])
            if base_type is not None and row_type_base != base_type:
                findings.append(
                    _finding(
                        "slice",
                        "overview_type_mismatch",
                        sid,
                        f"overview {row['type']!r} vs section {type_text!r}",
                    )
                )
            row_blocking = set(_blocking_tokens(row["blocking"]))
            section_blocking = set(_blocking_tokens(blocking_field))
            if row_blocking != section_blocking:
                findings.append(
                    _finding(
                        "slice",
                        "overview_blocking_mismatch",
                        sid,
                        f"overview {sorted(row_blocking)} vs section "
                        f"{sorted(section_blocking)}",
                    )
                )

    if not build_names_g0:
        findings.append(
            _finding(
                "v0",
                "build_block_task",
                None,
                "no governed-execution block or consumption record names task V0-G0",
            )
        )

    v0_errors = [f for f in findings if f["lane"] == "v0"]
    slice_defects = [f for f in findings if f["lane"] == "slice"]
    if mode == "v0":
        ok = not v0_errors
    else:
        ok = not findings
    return {
        "mode": mode,
        "ok": ok,
        "v0_errors": v0_errors,
        "slice_defects": slice_defects,
        "slices_parsed": section_ids,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["v0", "slice"], default="v0")
    parser.add_argument("--roadmap", type=Path, default=REPO_ROOT / "ROADMAP.md")
    parser.add_argument("--build", type=Path, default=REPO_ROOT / "BUILD.md")
    parser.add_argument(
        "--contract", type=Path, default=REPO_ROOT / "docs" / "GOVERNED-LOOP.md"
    )
    parser.add_argument(
        "--open-questions",
        type=Path,
        default=REPO_ROOT / "docs" / "OPEN-QUESTIONS.md",
    )
    args = parser.parse_args(argv)
    report = validate(
        args.roadmap, args.build, args.contract, args.open_questions, args.mode
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
