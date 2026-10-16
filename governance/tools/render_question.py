#!/usr/bin/env python3
"""Deterministic human-readable renderer for operator-question packets.

Renders a canonical strict-JSON operator-question packet to Markdown for
human review. The rendering is a review aid, never the source of truth
(GOVERNED-LOOP.md). The output is a pure function of the packet: it neither
adds, drops, nor merges an answer, recommendation, counterevidence,
uncertainty, or consequence.

Usage: render_question.py PACKET_JSON > packet.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gstrict  # noqa: E402
import validators  # noqa: E402


def _evidence_lines(items: list[dict]) -> list[str]:
    if not items:
        return ["(none declared)"]
    lines = []
    for item in items:
        lines.append(
            f"- {item['role']}: `{item['uri']}` "
            f"({item['media_type']}, {item['bytes']} bytes, "
            f"`{item['sha256']}`)"
        )
    return lines


def render(packet: dict) -> str:
    """Render a validated operator-question packet to Markdown."""
    problems = validators.validate_artifact("operator-question-packet", packet)
    if problems:
        raise ValueError("packet is not valid: " + "; ".join(problems))

    out: list[str] = []
    out.append(f"# Operator question {packet['question_id']}")
    out.append("")
    out.append(f"- Packet ID: `{packet['packet_id']}`")
    out.append(f"- Schema: `{packet['schema']}`")
    out.append(f"- Prepared: {packet['prepared_at']} by {packet['preparer']}")
    out.append(f"- Prepared-against base commit: `{packet['base_commit']}`")
    out.append("")

    out.append("## Question")
    out.append("")
    out.append(packet["question"])
    out.append("")
    out.append("## Why now")
    out.append("")
    out.append(packet["why_now"])
    out.append("")
    out.append("## Work blocked")
    out.append("")
    out.append(packet["blocks"])
    out.append("")

    out.append("## Bounded by")
    out.append("")
    for source in packet["bounded_by"]:
        out.append(f"- {source}")
    out.append("")

    out.append("## Governing inputs")
    out.append("")
    for item in packet["governing_inputs"]:
        out.append(
            f"- {item['role']}: `{item['path']}` "
            f"({item['bytes']} bytes, `{item['sha256']}`)"
        )
    if not packet["governing_inputs"]:
        out.append("(none declared)")
    out.append("")

    forcing = packet["forcing_case"]
    out.append("## Forcing case")
    out.append("")
    out.append(f"Sufficiency predicate: {forcing['predicate']}")
    out.append("")
    out.extend(_evidence_lines(forcing["evidence"]))
    out.append("")

    for answer in packet["answers"]:
        out.append(f"## Answer {answer['answer_id']}")
        out.append("")
        out.append(f"- Fit: {answer['fit']}")
        out.append(f"- Basis: {answer['basis']}")
        out.append(f"- Uncertainty: {answer['uncertainty']}")
        out.append("")
        out.append("### Supporting evidence")
        out.append("")
        out.extend(_evidence_lines(answer["supporting"]))
        out.append("")
        out.append("### Opposing evidence")
        out.append("")
        out.extend(_evidence_lines(answer["opposing"]))
        out.append("")
        consequences = answer["consequences"]
        out.append("### Consequences")
        out.append("")
        out.append(f"- Authority deltas: {consequences['authority_deltas']}")
        out.append(f"- Guarantee deltas: {consequences['guarantee_deltas']}")
        for label, key in (
            ("Blockers satisfied", "blockers_satisfied"),
            ("Blockers remaining", "blockers_remaining"),
            ("Tasks eligible", "tasks_eligible"),
            ("Amendments required", "amendments"),
        ):
            values = consequences[key]
            if values:
                out.append(f"- {label}:")
                for value in values:
                    out.append(f"  - {value}")
            else:
                out.append(f"- {label}: none")
        out.append(f"- Replay/fork implications: {consequences['replay_fork']}")
        out.append(f"- Abuse/T&S implications: {consequences['abuse_ts']}")
        out.append("")

    excluded = packet.get("excluded_answers", [])
    if excluded:
        out.append("## Excluded answers")
        out.append("")
        for item in excluded:
            out.append(
                f"- {item['answer_id']}: {item['conflict']} "
                f"(required amendment: {item['required_amendment']})"
            )
        out.append("")

    recommendation = packet["recommendation"]
    out.append("## Recommendation")
    out.append("")
    if recommendation["answer_id"] == "no_recommendation":
        out.append("No recommendation.")
    else:
        out.append(f"Recommended answer: `{recommendation['answer_id']}`")
    out.append("")
    out.append(recommendation["rationale"])
    out.append("")

    out.append("## Novelty condition")
    out.append("")
    out.append(packet["novelty_condition"])
    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path)
    args = parser.parse_args(argv)
    packet = gstrict.strict_loads(args.packet.read_text(encoding="utf-8"))
    try:
        sys.stdout.write(render(packet))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
