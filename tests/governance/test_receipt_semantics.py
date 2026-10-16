"""Receipt semantics: supersession chains, self-hashing, blocker scoping."""

from __future__ import annotations

import copy

import common
import gstrict
import validators


def _load(fixtures_dir, name):
    return gstrict.strict_loads(
        (fixtures_dir / "valid" / name).read_text(encoding="utf-8")
    )


def test_conflicting_unsuperseded_receipts(fixtures_dir):
    first = _load(fixtures_dir, "operator-decision-receipt__select.json")
    second = copy.deepcopy(first)
    second["receipt_id"] = "OQDR-OQ-99-2026-08-14-A-09"
    problems = validators.check_receipt_set([first, second])
    assert any("conflicting active receipts" in p for p in problems)


def test_supersession_chain_resolves_conflict(fixtures_dir):
    first = _load(fixtures_dir, "operator-decision-receipt__select.json")
    second = _load(fixtures_dir, "operator-decision-receipt__superseding.json")
    assert not validators.check_receipt_set([first, second])


def test_supersession_with_wrong_digest(fixtures_dir):
    first = _load(fixtures_dir, "operator-decision-receipt__select.json")
    second = _load(fixtures_dir, "operator-decision-receipt__superseding.json")
    second = copy.deepcopy(second)
    second["supersedes"]["receipt_sha256"] = "sha256:" + "0" * 64
    problems = validators.check_receipt_set([first, second])
    assert any("supersedes digest" in p for p in problems)


def test_authentication_attests_payload_not_enclosing_bytes(fixtures_dir):
    receipt = _load(fixtures_dir, "operator-decision-receipt__select.json")
    payload_digest = common.canonical_sha256(receipt["decision_payload"])
    receipt_digest = common.canonical_sha256(receipt)
    auth_digest = receipt["authentication"]["payload_sha256"]
    assert auth_digest == payload_digest
    assert auth_digest != receipt_digest


def test_select_satisfies_only_its_declared_question(fixtures_dir):
    receipt = _load(fixtures_dir, "operator-decision-receipt__select.json")
    packet = _load(fixtures_dir, "operator-question-packet__packet.json")
    other_packet = copy.deepcopy(packet)
    other_packet["question_id"] = "OQ-5"
    problems = validators.validate_artifact(
        "operator-decision-receipt", receipt, packet=other_packet
    )
    assert any("question_id disagrees" in p for p in problems)
    # The receipt never asserts anything about other tasks or slices:
    # its payload names exactly one question and one answer.
    assert receipt["decision_payload"]["question_id"] == "OQ-99"
    assert receipt["decision_payload"]["answer_id"] == "A"


def test_procedural_rulings_leave_blocker_open(fixtures_dir):
    for name in (
        "operator-decision-receipt__defer.json",
        "operator-decision-receipt__reject-packet.json",
        "operator-decision-receipt__repack.json",
    ):
        receipt = _load(fixtures_dir, name)
        assert receipt["decision_payload"]["ruling"] != "select"
        _, problems = validators.load_and_validate(
            "operator-decision-receipt", fixtures_dir / "valid" / name
        )
        assert not problems
