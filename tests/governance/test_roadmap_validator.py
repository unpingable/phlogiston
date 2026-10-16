"""Roadmap/authorization validator tests: real repo and golden fixtures."""

from __future__ import annotations

import validate_roadmap


def _validate(fixtures_dir, name, mode):
    directory = fixtures_dir / "roadmap" / name
    return validate_roadmap.validate(
        directory / "ROADMAP.md",
        directory / "BUILD.md",
        directory / "GOVERNED-LOOP.md",
        directory / "OPEN-QUESTIONS.md",
        mode=mode,
    )


class TestRealRepository:
    def _report(self, repo_root, mode="v0"):
        return validate_roadmap.validate(
            repo_root / "ROADMAP.md",
            repo_root / "BUILD.md",
            repo_root / "docs" / "GOVERNED-LOOP.md",
            repo_root / "docs" / "OPEN-QUESTIONS.md",
            mode=mode,
        )

    def test_v0_lane_clean(self, repo_root):
        report = self._report(repo_root)
        assert report["ok"]
        assert report["v0_errors"] == []

    def test_known_defects_reported_not_repaired(self, repo_root):
        report = self._report(repo_root)
        codes = {(d["slice"], d["code"]) for d in report["slice_defects"]}
        assert ("S16", "status_qualifier") in codes
        assert ("S2", "type_authority_mismatch") in codes
        assert ("S8", "dependency_inconsistency") in codes
        # The descriptive qualifiers are reported wholesale.
        assert any(c == "type_qualifier" for _, c in codes)
        # The roadmap bytes are untouched by validation.
        s8 = [
            d
            for d in report["slice_defects"]
            if d["slice"] == "S8" and d["code"] == "dependency_inconsistency"
        ]
        assert any("S10" in d["detail"] for d in s8)

    def test_slice_mode_fails_on_known_defects(self, repo_root):
        report = self._report(repo_root, mode="slice")
        assert not report["ok"]


class TestFixtures:
    def test_valid_fixture_passes_both_modes(self, fixtures_dir):
        assert _validate(fixtures_dir, "valid", "v0")["ok"]
        assert _validate(fixtures_dir, "valid", "slice")["ok"]

    def test_valid_consumed_record_passes_both_modes(self, fixtures_dir):
        assert _validate(fixtures_dir, "valid-consumed", "v0")["ok"]
        assert _validate(fixtures_dir, "valid-consumed", "slice")["ok"]

    def test_consumed_record_with_foreign_receipt_fails_v0(self, fixtures_dir):
        report = _validate(fixtures_dir, "invalid-consumed-receipt", "v0")
        assert not report["ok"]
        assert any(f["code"] == "consumed_receipt_id" for f in report["v0_errors"])

    def test_block_and_consumed_record_together_fail_v0(self, fixtures_dir):
        report = _validate(fixtures_dir, "invalid-consumed-and-block", "v0")
        assert not report["ok"]
        assert any(f["code"] == "build_block_count" for f in report["v0_errors"])

    def test_contract_digest_mismatch_fails_v0(self, fixtures_dir):
        report = _validate(fixtures_dir, "invalid-build-digest", "v0")
        assert not report["ok"]
        assert any(
            f["code"] == "build_block_contract_digest" for f in report["v0_errors"]
        )

    def test_two_blocks_fail_v0(self, fixtures_dir):
        report = _validate(fixtures_dir, "invalid-two-blocks", "v0")
        assert not report["ok"]
        assert any(f["code"] == "build_block_count" for f in report["v0_errors"])

    def test_unknown_blocking_oq_is_slice_lane_only(self, fixtures_dir):
        assert _validate(fixtures_dir, "invalid-slice-blocking", "v0")["ok"]
        report = _validate(fixtures_dir, "invalid-slice-blocking", "slice")
        assert not report["ok"]
        assert any(d["code"] == "unknown_blocking_oq" for d in report["slice_defects"])
