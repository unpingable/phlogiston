"""Frozen OQ-7 change-set verification against the committed patches."""

from __future__ import annotations

import hashlib
import subprocess

import pytest
import verify_frozen_changeset as vfc

from conftest import OQ7_APPLIED_COMMIT, OQ7_BASE_COMMIT


def _git_show(repo_root, commit, path):
    return subprocess.run(
        ["git", "-C", str(repo_root), "show", f"{commit}:{path}"],
        capture_output=True,
        check=True,
    ).stdout


def _patch(repo_root, answer):
    return repo_root / "docs" / f"OQ-7-CHANGESET-{answer}.patch"


class TestCommittedPatches:
    @pytest.mark.parametrize("answer", ["A", "B", "C"])
    def test_patch_verifies(self, repo_root, answer):
        report = vfc.verify(_patch(repo_root, answer), OQ7_BASE_COMMIT, repo_root)
        assert report["ok"], report.get("errors")

    def test_a_and_b_add_identical_build_block(self, repo_root):
        _, targets_a, _ = vfc.parse_header(
            _patch(repo_root, "A").read_text(encoding="utf-8")
        )
        _, targets_b, _ = vfc.parse_header(
            _patch(repo_root, "B").read_text(encoding="utf-8")
        )
        build_a = [t for t in targets_a if t["path"] == "BUILD.md"]
        build_b = [t for t in targets_b if t["path"] == "BUILD.md"]
        assert build_a == build_b and build_a

    def test_c_changes_only_the_register(self, repo_root):
        scalars, targets, _ = vfc.parse_header(
            _patch(repo_root, "C").read_text(encoding="utf-8")
        )
        assert [t["path"] for t in targets] == ["docs/OPEN-QUESTIONS.md"]
        assert scalars["answer_id"] == "C"

    def test_a_result_digests_match_the_applied_commit(self, repo_root):
        _, targets, _ = vfc.parse_header(
            _patch(repo_root, "A").read_text(encoding="utf-8")
        )
        for target in targets:
            applied = _git_show(repo_root, OQ7_APPLIED_COMMIT, target["path"])
            digest = "sha256:" + hashlib.sha256(applied).hexdigest()
            assert digest == target["result_sha256"]

    def test_receipt_ids_match_the_decided_mapping(self, repo_root):
        scalars, _, _ = vfc.parse_header(
            _patch(repo_root, "A").read_text(encoding="utf-8")
        )
        assert scalars["receipt_id"] == "OQDR-OQ-7-2026-07-27-A-02"
        assert scalars["packet_id"] == "OQP-OQ-7-2026-07-27-03"
        assert scalars["question_id"] == "OQ-7"
        assert scalars["answer_id"] == "A"


class TestSubstitutions:
    def _verify_text(self, repo_root, tmp_path, text):
        patch = tmp_path / "candidate.patch"
        patch.write_text(text, encoding="utf-8")
        return vfc.verify(patch, OQ7_BASE_COMMIT, repo_root)

    def test_result_digest_substitution(self, repo_root, tmp_path):
        text = _patch(repo_root, "C").read_text(encoding="utf-8")
        text = text.replace(
            "f83d0f4f832a16e71288171e3dcc373539a7488429bb04174a2f554c42ae3520",
            "0" * 64,
        )
        report = self._verify_text(repo_root, tmp_path, text)
        assert not report["ok"]
        assert any("result digest mismatch" in e for e in report["errors"])

    def test_base_digest_substitution(self, repo_root, tmp_path):
        text = _patch(repo_root, "C").read_text(encoding="utf-8")
        text = text.replace(
            "fc704af74e51a29b29d35c58cc4aa0c295ce11729f12e40b6bf62b4f93986e28",
            "0" * 64,
        )
        report = self._verify_text(repo_root, tmp_path, text)
        assert not report["ok"]
        assert any("base digest mismatch" in e for e in report["errors"])

    def test_patch_byte_substitution(self, repo_root, tmp_path):
        text = _patch(repo_root, "C").read_text(encoding="utf-8")
        text = text.replace("+**Selected answer:** C", "+**Selected answer:** B")
        report = self._verify_text(repo_root, tmp_path, text)
        assert not report["ok"]

    def test_path_substitution(self, repo_root, tmp_path):
        text = _patch(repo_root, "C").read_text(encoding="utf-8")
        text = text.replace(
            'target.1.path = "docs/OPEN-QUESTIONS.md"',
            'target.1.path = "docs/OTHER.md"',
        )
        report = self._verify_text(repo_root, tmp_path, text)
        assert not report["ok"]

    def test_target_ordering_substitution(self, repo_root, tmp_path):
        lines = _patch(repo_root, "A").read_text(encoding="utf-8").splitlines()
        header = lines[: lines.index("--PATCH--")]
        t1 = [line for line in header if line.startswith("target.1.")]
        t2 = [line for line in header if line.startswith("target.2.")]
        reordered = [
            line for line in header if not line.startswith(("target.1.", "target.2."))
        ]
        reordered += t2 + t1
        text = "\n".join(reordered + lines[lines.index("--PATCH--") :]) + "\n"
        report = self._verify_text(repo_root, tmp_path, text)
        assert not report["ok"]
        assert any("frozen order" in e for e in report["errors"])

    def test_receipt_id_substitution_rejected_by_mapping(self, repo_root):
        text = _patch(repo_root, "A").read_text(encoding="utf-8")
        scalars, _, _ = vfc.parse_header(text)
        assert scalars["receipt_id"] != "OQDR-OQ-7-2026-07-27-B-02"

    def test_duplicate_header_key(self, repo_root, tmp_path):
        text = _patch(repo_root, "C").read_text(encoding="utf-8")
        text = text.replace('answer_id = "C"', 'answer_id = "C"\nanswer_id = "C"')
        report = self._verify_text(repo_root, tmp_path, text)
        assert not report["ok"]
        assert any("duplicate header key" in e for e in report["errors"])
