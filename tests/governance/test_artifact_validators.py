"""Golden-fixture sweep: valid fixtures validate, invalid ones reject."""

from __future__ import annotations

import gstrict
import pytest
import validators


@pytest.fixture()
def packet(fixtures_dir):
    return gstrict.strict_loads(
        (fixtures_dir / "valid" / "operator-question-packet__packet.json").read_text(
            encoding="utf-8"
        )
    )


def test_valid_fixtures_all_validate(fixtures_dir, packet):
    paths = sorted((fixtures_dir / "valid").glob("*.json"))
    assert paths, "no valid fixtures found"
    for path in paths:
        kind = path.name.split("__", 1)[0]
        _, problems = validators.load_and_validate(kind, path, packet=packet)
        assert not problems, f"{path.name}: {problems}"


def test_invalid_fixtures_all_rejected(fixtures_dir, packet):
    paths = sorted((fixtures_dir / "invalid").glob("*.json"))
    assert paths, "no invalid fixtures found"
    for path in paths:
        _, kind, _ = path.name[: -len(".json")].split("__", 2)
        _, problems = validators.load_and_validate(kind, path, packet=packet)
        assert problems, f"{path.name} unexpectedly validated"


class TestRejectionClasses:
    """Assert the specific rejection reason for key invalid classes."""

    def _problems(self, fixtures_dir, name, packet):
        _, kind, _ = name[: -len(".json")].split("__", 2)
        _, problems = validators.load_and_validate(
            kind, fixtures_dir / "invalid" / name, packet=packet
        )
        assert problems
        return problems

    def test_hybrid_ruling(self, fixtures_dir, packet):
        problems = self._problems(
            fixtures_dir,
            "hybrid-ruling__operator-decision-receipt__hybrid.json",
            packet,
        )
        assert any("forbids 'revisit_trigger'" in p for p in problems)

    def test_digest_substitution(self, fixtures_dir, packet):
        problems = self._problems(
            fixtures_dir,
            "digest-substitution__operator-decision-receipt__bad-auth-digest.json",
            packet,
        )
        assert any("does not equal the canonical" in p for p in problems)

    def test_packet_digest_substitution(self, fixtures_dir, packet):
        problems = self._problems(
            fixtures_dir,
            "packet-digest-substitution__operator-decision-receipt__bad-packet.json",
            packet,
        )
        assert any("does not match the packet" for p in problems)

    def test_selection_outside_set(self, fixtures_dir, packet):
        problems = self._problems(
            fixtures_dir,
            "selection-outside-set__operator-decision-receipt__answer-z.json",
            packet,
        )
        assert any("outside the admissible set" in p for p in problems)

    def test_duplicate_key_rejected_at_load(self, fixtures_dir):
        path = (
            fixtures_dir
            / "invalid"
            / "duplicate-key__operator-question-packet__dup.json"
        )
        with pytest.raises(gstrict.StrictJsonError):
            gstrict.strict_loads(path.read_text(encoding="utf-8"))

    def test_changed_consequences_wording(self, fixtures_dir, packet):
        problems = self._problems(
            fixtures_dir,
            "changed-consequences__operator-question-packet__bad-wording.json",
            packet,
        )
        assert any("forbidden wording" in p for p in problems)

    def test_descendant_digest_in_change_set(self, fixtures_dir, packet):
        problems = self._problems(
            fixtures_dir,
            "descendant-digest__required-change-set__embeds-receipt.json",
            packet,
        )
        # Rejected either as an unknown field by the strict schema or by
        # the semantic no-descendant-digest rule.
        assert any("unknown field" in p or "descendant digest" in p for p in problems)

    def test_manifest_itself_validates(self, repo_root):
        _, problems = validators.load_and_validate(
            "v0-task-manifest",
            repo_root / "governance" / "manifest" / "v0-task-manifest.json",
        )
        assert not problems

    def test_live_exercise_on_denied_network(self, fixtures_dir, packet):
        problems = self._problems(
            fixtures_dir,
            "live-exercise-denied__controller-entry-packet__live-on-denied.json",
            packet,
        )
        assert any("live_exercise is forbidden" in p for p in problems)

    def test_x6_with_writes_rejected(self, fixtures_dir, packet):
        problems = self._problems(
            fixtures_dir,
            "live-exercise-writes__controller-entry-packet__x6-writes.json",
            packet,
        )
        assert any("ceilings.max_writes == 0" in p for p in problems)

    def test_unsorted_target_allow_list(self, fixtures_dir, packet):
        problems = self._problems(
            fixtures_dir,
            "unsorted-allow-list__controller-entry-packet__unsorted-targets.json",
            packet,
        )
        assert any("target_allow_list must be lexically sorted" in p for p in problems)

    def test_pass_receipt_with_writes(self, fixtures_dir, packet):
        problems = self._problems(
            fixtures_dir,
            "exercise-receipt-writes__exercise-receipt__pass-with-writes.json",
            packet,
        )
        assert any("PASS outcome with counters.writes > 0" in p for p in problems)
