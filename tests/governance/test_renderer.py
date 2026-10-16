"""Golden and mutation tests for the deterministic question renderer."""

from __future__ import annotations

import copy

import gstrict
import render_question


def _packet(fixtures_dir):
    return gstrict.strict_loads(
        (fixtures_dir / "valid" / "operator-question-packet__packet.json").read_text(
            encoding="utf-8"
        )
    )


def test_golden(fixtures_dir):
    golden = (fixtures_dir / "renderer" / "packet.golden.md").read_text(
        encoding="utf-8"
    )
    assert render_question.render(_packet(fixtures_dir)) == golden


def test_deterministic_under_key_reordering(fixtures_dir):
    packet = _packet(fixtures_dir)
    shuffled = gstrict.strict_loads(__import__("json").dumps(packet, sort_keys=True))
    assert render_question.render(packet) == render_question.render(shuffled)


def test_every_answer_rendered_exactly_once(fixtures_dir):
    output = render_question.render(_packet(fixtures_dir))
    for answer_id in ("A", "B"):
        assert output.count(f"## Answer {answer_id}\n") == 1


def test_recommendation_and_uncertainty_present(fixtures_dir):
    packet = _packet(fixtures_dir)
    output = render_question.render(packet)
    assert "Recommended answer: `A`" in output
    for answer in packet["answers"]:
        assert answer["uncertainty"] in output
        for role in ("supporting", "opposing"):
            for item in answer[role]:
                assert item["sha256"] in output
        for value in answer["consequences"].values():
            if isinstance(value, str):
                assert value in output
            else:
                for entry in value:
                    assert entry in output


def test_dropping_an_answer_changes_output(fixtures_dir):
    packet = _packet(fixtures_dir)
    mutated = copy.deepcopy(packet)
    mutated["answers"] = mutated["answers"][:1]
    assert render_question.render(packet) != render_question.render(mutated)
    assert "## Answer B" not in render_question.render(mutated)


def test_adding_an_answer_changes_output(fixtures_dir):
    packet = _packet(fixtures_dir)
    mutated = copy.deepcopy(packet)
    extra = copy.deepcopy(mutated["answers"][0])
    extra["answer_id"] = "C"
    mutated["answers"].append(extra)
    assert "## Answer C" in render_question.render(mutated)


def test_changing_recommendation_changes_output(fixtures_dir):
    packet = _packet(fixtures_dir)
    mutated = copy.deepcopy(packet)
    mutated["recommendation"] = {
        "answer_id": "no_recommendation",
        "rationale": "No admissible answer stands out.",
    }
    output = render_question.render(mutated)
    assert "No recommendation." in output
    assert "Recommended answer: `A`" not in output


def test_excluded_answers_rendered_when_present(fixtures_dir):
    output = render_question.render(_packet(fixtures_dir))
    assert "## Excluded answers" in output
    assert "Z" in output


def test_invalid_packet_refused(fixtures_dir):
    packet = _packet(fixtures_dir)
    del packet["question"]
    try:
        render_question.render(packet)
    except ValueError:
        return
    raise AssertionError("renderer accepted an invalid packet")
