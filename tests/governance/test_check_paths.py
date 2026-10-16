"""Protected-path and allowed-path check tests over synthetic git repos."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import check_paths

ALLOWED = check_paths.G0_ALLOWED_PATTERNS


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "BUILD.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    return repo


def _commit_all(repo: Path, message: str = "candidate") -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)


class TestPatternMatching:
    def test_exact_and_descendant(self):
        assert check_paths.pattern_matches("scripts/v0-gate", "scripts/v0-gate")
        assert check_paths.pattern_matches("governance/**", "governance/tools/x.py")
        assert check_paths.pattern_matches("governance/**", "governance/a/b/c.json")

    def test_non_matches(self):
        assert not check_paths.pattern_matches("governance/**", "governance")
        assert not check_paths.pattern_matches("governance/**", "governancex/y")
        assert not check_paths.pattern_matches(
            "scripts/v0-gate", "scripts/v0-gate-extra"
        )
        assert not check_paths.pattern_matches("governance/**", "tests/x.py")


class TestDiffChecks:
    def test_allowed_addition_passes(self, tmp_path):
        repo = _make_repo(tmp_path)
        base = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        target = repo / "governance" / "tools"
        target.mkdir(parents=True)
        (target / "x.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo)
        report = check_paths.check_diff(repo, base, "HEAD", ALLOWED)
        assert report["ok"], report["violations"]

    def test_protected_modification_rejected(self, tmp_path):
        repo = _make_repo(tmp_path)
        base = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        (repo / "BUILD.md").write_text("modified\n", encoding="utf-8")
        _commit_all(repo)
        report = check_paths.check_diff(repo, base, "HEAD", ALLOWED)
        assert not report["ok"]
        assert any(
            v["path"] == "BUILD.md" and "not an addition" in v["reason"]
            for v in report["violations"]
        )

    def test_addition_outside_allowed_rejected(self, tmp_path):
        repo = _make_repo(tmp_path)
        base = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        (repo / "stray.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo)
        report = check_paths.check_diff(repo, base, "HEAD", ALLOWED)
        assert not report["ok"]
        assert any("outside allowed" in v["reason"] for v in report["violations"])

    def test_symlink_rejected(self, tmp_path):
        repo = _make_repo(tmp_path)
        base = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        target_dir = repo / "governance"
        target_dir.mkdir()
        os.symlink("BUILD.md", repo / "governance" / "link.md")
        _commit_all(repo)
        report = check_paths.check_diff(repo, base, "HEAD", ALLOWED)
        assert not report["ok"]
        assert any("symlink" in v["reason"] for v in report["violations"])


class TestGeneralMode:
    ALLOWED = ["packages/**", "tests/**"]
    PROTECTED = ["BUILD.md", "docs/GOVERNED-LOOP.md"]

    def _base(self, repo: Path) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def test_modification_within_allowed_passes(self, tmp_path):
        repo = _make_repo(tmp_path)
        pkg = repo / "packages" / "pkg"
        pkg.mkdir(parents=True)
        (pkg / "mod.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "seed package")
        base = self._base(repo)
        (pkg / "mod.py").write_text("x = 2\n", encoding="utf-8")
        (pkg / "new.py").write_text("y = 3\n", encoding="utf-8")
        _commit_all(repo)
        report = check_paths.check_diff(
            repo, base, "HEAD", self.ALLOWED, self.PROTECTED
        )
        assert report["ok"], report["violations"]
        assert report["mode"] == "general"

    def test_protected_path_modification_rejected(self, tmp_path):
        repo = _make_repo(tmp_path)
        base = self._base(repo)
        (repo / "BUILD.md").write_text("modified\n", encoding="utf-8")
        _commit_all(repo)
        report = check_paths.check_diff(
            repo, base, "HEAD", self.ALLOWED, self.PROTECTED
        )
        assert not report["ok"]
        assert any(
            v["path"] == "BUILD.md" and v["reason"] == "protected path"
            for v in report["violations"]
        )

    def test_unprotected_path_outside_allowed_rejected(self, tmp_path):
        repo = _make_repo(tmp_path)
        base = self._base(repo)
        (repo / "stray.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo)
        report = check_paths.check_diff(
            repo, base, "HEAD", self.ALLOWED, self.PROTECTED
        )
        assert not report["ok"]
        assert any("outside allowed" in v["reason"] for v in report["violations"])

    def test_deletion_within_allowed_rejected(self, tmp_path):
        repo = _make_repo(tmp_path)
        pkg = repo / "packages" / "pkg"
        pkg.mkdir(parents=True)
        (pkg / "mod.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "seed package")
        base = self._base(repo)
        (pkg / "mod.py").unlink()
        _commit_all(repo)
        report = check_paths.check_diff(
            repo, base, "HEAD", self.ALLOWED, self.PROTECTED
        )
        assert not report["ok"]
        assert any(
            "not an addition or modification" in v["reason"]
            for v in report["violations"]
        )
