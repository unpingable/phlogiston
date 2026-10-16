from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from community_space_comprehension import (
    ComprehensionVerdict,
    SyntheticComprehensionInstrument,
)


@pytest.mark.parametrize(
    ("state", "expected"),
    (
        ("added", "The admitted bounded presentation is displayed."),
        (
            "changed_at_source",
            "The source changed; this is not a new admission or replacement.",
        ),
        (
            "source_unavailable",
            "The source is unavailable; the community did not remove it.",
        ),
        (
            "removed",
            "The community projection was removed; the source was not deleted.",
        ),
    ),
)
def test_synthetic_lifecycle_questions_are_answerable(
    m6c: dict[str, object], state: str, expected: str
) -> None:
    report = SyntheticComprehensionInstrument().qualify(m6c["sites"][state])
    assert report.verdict is ComprehensionVerdict.INFORMATION_SUFFICIENT
    assert not report.unanswerable_question_ids
    assert len(report.answerable_question_ids) == 6
    state_result = next(
        item
        for item in report.outcomes
        if item.question_id.endswith("state-distinction")
    )
    assert state_result.expected_interpretation == expected


def test_synthetic_answers_keep_ownership_inclusion_and_visibility_distinct(
    m6c: dict[str, object],
) -> None:
    report = SyntheticComprehensionInstrument().qualify(m6c["sites"]["added"])
    answers = {item.question_id.rpartition(":")[2]: item for item in report.outcomes}
    assert answers["source-ownership"].expected_interpretation == (
        "No. The author still owns the source."
    )
    assert answers["community-inclusion"].expected_interpretation == (
        "The community published its inclusion/lifecycle decision."
    )
    assert answers["disclosure-separation"].expected_interpretation == (
        "No. Ordinary and audit disclosures remain separate."
    )
    assert "reader_authorization" in report.explicit_non_claims


def test_synthetic_audit_answer_uses_references_without_authority(
    m6c: dict[str, object],
) -> None:
    report = SyntheticComprehensionInstrument().qualify(m6c["sites"]["removed"])
    audit = next(
        item for item in report.outcomes if item.question_id.endswith("auditability")
    )
    assert audit.answerable
    assert audit.expected_interpretation == (
        "Yes. The audit page exposes identifiers, not authority."
    )
    assert "governance_authority" in report.explicit_non_claims


def test_synthetic_report_replays_deterministically(m6c: dict[str, object]) -> None:
    site = m6c["sites"]["added"]
    first = SyntheticComprehensionInstrument().qualify(site)
    second = SyntheticComprehensionInstrument().qualify(site)
    assert first == second
    assert first.report_id == second.report_id
    assert first.validate_against(site) == first.report_id


def test_m6c_fixture_checksum_and_nonsecret_status(m6c: dict[str, object]) -> None:
    assert m6c["vector"]["secretMaterialPresent"] is False
    fixture = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "space-community"
        / "scv0-m6c.json"
    )
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == (
        "d386cee2165aa255b980d4397ad3cad263d5d1a0ccb091720274ed713aa9770f"
    )
