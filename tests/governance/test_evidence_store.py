"""Evidence write/readback and retention-policy failure cases."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import evidence_store


def _populate(src: Path) -> None:
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_bytes(b"alpha")
    (src / "sub" / "b.bin").write_bytes(b"\x00\x01\x02")


def test_write_readback_roundtrip(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    _populate(src)
    report = evidence_store.write_tree(src, dst)
    assert report["ok"], report["problems"]
    manifest = report["manifest"]
    assert len(manifest["files"]) == 2
    again = evidence_store.verify_tree(manifest, dst)
    assert again["ok"]


def test_altered_byte_fails_closed(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    _populate(src)
    manifest = evidence_store.write_tree(src, dst)["manifest"]
    target = dst / "a.txt"
    data = bytearray(target.read_bytes())
    data[0] ^= 0xFF
    target.write_bytes(bytes(data))
    report = evidence_store.verify_tree(manifest, dst)
    assert not report["ok"]
    assert any("sha256 mismatch" in p for p in report["problems"])


def test_truncated_file_fails_closed(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    _populate(src)
    manifest = evidence_store.write_tree(src, dst)["manifest"]
    (dst / "a.txt").write_bytes(b"a")
    report = evidence_store.verify_tree(manifest, dst)
    assert not report["ok"]
    assert any("byte-length mismatch" in p for p in report["problems"])


def test_missing_file_fails_closed(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    _populate(src)
    manifest = evidence_store.write_tree(src, dst)["manifest"]
    (dst / "sub" / "b.bin").unlink()
    report = evidence_store.verify_tree(manifest, dst)
    assert not report["ok"]
    assert any("missing" in p for p in report["problems"])


def test_extra_file_fails_closed(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    _populate(src)
    manifest = evidence_store.write_tree(src, dst)["manifest"]
    (dst / "extra.txt").write_bytes(b"extra")
    report = evidence_store.verify_tree(manifest, dst)
    assert not report["ok"]
    assert any("extra retained file" in p for p in report["problems"])


def test_symlink_in_source_rejected(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    _populate(src)
    (src / "link").symlink_to("a.txt")
    report = evidence_store.write_tree(src, dst)
    assert not report["ok"]
    assert any("symlink" in p for p in report["problems"])


def test_unavailable_storage_fails_closed(tmp_path):
    report = evidence_store.verify_tree(
        {"schema": "evidence-store-manifest-v1", "files": []},
        tmp_path / "does-not-exist",
    )
    assert report["ok"]  # empty manifest over empty store is consistent
    manifest = {
        "schema": "evidence-store-manifest-v1",
        "files": [{"path": "a.txt", "bytes": 5, "sha256": "sha256:" + "0" * 64}],
    }
    report = evidence_store.verify_tree(manifest, tmp_path / "absent")
    assert not report["ok"]


class TestRetentionPolicy:
    GOOD = {
        "destination_uri": "file:///evidence/run-01",
        "retention_until": "2027-01-01T00:00:00Z",
        "readback_required": True,
    }

    def test_valid_policy(self):
        now = datetime(2026, 8, 14, tzinfo=timezone.utc)
        assert evidence_store.check_retention_policy(self.GOOD, now=now)["ok"]

    def test_relative_destination_rejected(self):
        policy = dict(self.GOOD, destination_uri="evidence/run-01")
        assert not evidence_store.check_retention_policy(policy)["ok"]

    def test_non_utc_retention_rejected(self):
        policy = dict(self.GOOD, retention_until="2027-01-01T00:00:00+01:00")
        assert not evidence_store.check_retention_policy(policy)["ok"]

    def test_past_retention_rejected(self):
        policy = dict(self.GOOD, retention_until="2020-01-01T00:00:00Z")
        now = datetime(2026, 8, 14, tzinfo=timezone.utc)
        assert not evidence_store.check_retention_policy(policy, now=now)["ok"]

    def test_readback_not_required_rejected(self):
        policy = dict(self.GOOD, readback_required=False)
        assert not evidence_store.check_retention_policy(policy)["ok"]

    def test_unknown_field_rejected(self):
        policy = dict(self.GOOD, extra="field")
        assert not evidence_store.check_retention_policy(policy)["ok"]
