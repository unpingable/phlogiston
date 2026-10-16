from __future__ import annotations

import hashlib
import json
from pathlib import Path

from community_space_demo import DEMO_VERSION
from community_space_demo.__main__ import main


def test_m7a_bundle_identity_and_manifest_are_deterministic(
    m7a: dict[str, object],
) -> None:
    bundle = m7a["bundle"]
    vector = m7a["vector"]
    assert bundle.demo_version == DEMO_VERSION
    assert bundle.bundle_id == vector["expectedBundleId"]
    assert len(bundle.all_files) == vector["expectedFileCount"]
    assert bundle.manifest_bytes == bundle.manifest_bytes
    manifest = json.loads(bundle.manifest_bytes)
    assert manifest["synthetic"] is True
    assert tuple(item["state"] for item in manifest["scenarios"]) == tuple(
        vector["lifecycleCases"]
    )


def test_landing_page_is_static_clear_and_script_free(m7a: dict[str, object]) -> None:
    files = {item.path: item for item in m7a["bundle"].all_files}
    landing = files["index.html"].body.decode("utf-8")
    assert "Synthetic demo" in landing
    assert "community owns inclusion" in landing
    assert "renderer is only the window" in landing
    for state in m7a["vector"]["lifecycleCases"]:
        assert f'href="{state}/"' in landing
    assert "<script" not in landing.lower()
    assert "analytics" not in landing.lower()
    assert "cookie" not in landing.lower()


def test_bundle_embeds_exact_pages_and_feed_bytes(m7a: dict[str, object]) -> None:
    files = {item.path: item for item in m7a["bundle"].all_files}
    for state, site in m7a["sites"].items():
        assert files[f"{state}/index.html"].body == site.ordinary_html.encode()
        assert files[f"{state}/audit.html"].body == site.audit_html.encode()
        assert files[f"{state}/feed.json"].body == site.ordinary_feed.to_bytes()
        assert files[f"{state}/audit-feed.json"].body == site.audit_feed.to_bytes()


def test_bundle_writes_and_reverifies_exact_directory(
    m7a: dict[str, object], tmp_path: Path
) -> None:
    target = tmp_path / "site"
    bundle = m7a["bundle"]
    bundle.write_directory(target)
    assert (target / "index.html").is_file()
    assert (target / ".nojekyll").is_file()
    assert (target / "manifest.json").read_bytes() == bundle.manifest_bytes
    assert bundle.verify_directory(target) == bundle.bundle_id


def test_cli_writes_then_checks_the_same_bundle(tmp_path: Path, capsys) -> None:
    target = tmp_path / "cli-site"
    assert main([str(target)]) == 0
    written = json.loads(capsys.readouterr().out)
    assert written["action"] == "written"
    assert written["fileCount"] == 20
    assert main([str(target), "--check"]) == 0
    checked = json.loads(capsys.readouterr().out)
    assert checked["action"] == "verified"
    assert checked["bundleId"] == written["bundleId"]


def test_manifest_checksum_file_covers_every_published_payload(
    m7a: dict[str, object],
) -> None:
    files = {item.path: item for item in m7a["bundle"].all_files}
    lines = files["checksums.txt"].body.decode("utf-8").splitlines()
    covered = {line.partition("  ")[2] for line in lines}
    assert covered == set(files) - {"checksums.txt"}
    assert "manifest.json" in covered


def test_m7a_fixture_checksum_and_nonsecret_status(m7a: dict[str, object]) -> None:
    assert m7a["vector"]["secretMaterialPresent"] is False
    fixture = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "space-community"
        / "scv0-m7a.json"
    )
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == (
        "6fd31b82b86fdf5bcae3677956810d23f5313420e20ebae034098b3c43d6709a"
    )
