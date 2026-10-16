from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag

from community_space_demo import COMMUNITY_NAME, SHOWCASE_VERSION
from community_space_demo.showcase_cli import main


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"a", "link"}:
            return
        for key, value in attrs:
            if key == "href" and value is not None:
                self.links.append(value)


def test_showcase_corpus_is_exact_typed_projection_input(
    m7c: dict[str, object],
) -> None:
    corpus = m7c["corpus"]
    vector = m7c["vector"]
    assert corpus.corpus_id == vector["expectedCorpusId"]
    entries = corpus.community_site.canonical_semantics.entries
    assert len(entries) == 3
    assert tuple(item.lifecycle_state for item in entries) == ("added",) * 3
    assert tuple(corpus.lifecycle_sites) == tuple(vector["lifecycleCases"])


def test_showcase_home_is_human_facing_and_script_free(m7c: dict[str, object]) -> None:
    files = {item.path: item.body for item in m7c["bundle"].all_files}
    page = files["index.html"].decode()
    assert COMMUNITY_NAME in page
    assert "A community feed that doesn’t own the posts it displays" in page
    assert "The free tool shelf is open this Saturday" in page
    assert "A tiny guide to balcony tomatoes" in page
    assert "What we learned from repairing six lamps" in page
    assert "Their authors still own them" in page
    assert "bounded presentations" not in page
    assert page.count("Why is this here?") == 3
    assert page.count("the admission and moderation authorization are synthetic") == 3
    assert "Designed for clarity, but not yet user-tested." in page
    assert "SCV0" not in page
    assert "sha256:" not in page
    assert "<script" not in page.lower()
    assert "analytics" not in page.lower()
    assert "cookie" not in page.lower()


def test_showcase_ordinary_and_audit_disclosure_remain_separate(
    m7c: dict[str, object],
) -> None:
    corpus = m7c["corpus"]
    files = {item.path: item.body for item in m7c["bundle"].all_files}
    ordinary = files["index.html"].decode()
    audit = files["audit.html"].decode()
    for entry in corpus.community_site.audit_semantics.entries:
        for _, receipt_id in entry.receipt_references:
            assert receipt_id not in ordinary
            assert receipt_id in audit
    assert "evidence pointers—not proof" in audit


def test_showcase_lifecycle_pages_preserve_exact_meanings(
    m7c: dict[str, object],
) -> None:
    files = {item.path: item.body.decode() for item in m7c["bundle"].all_files}
    changed = files["states/changed-at-source/index.html"]
    unavailable = files["states/source-unavailable/index.html"]
    removed = files["states/removed/index.html"]
    assert "does not silently substitute the new version" in changed
    assert "does not invent replacement content" in unavailable
    assert "does not delete or rewrite the author’s original record" in removed
    assert "The free tool shelf is open this Saturday" not in changed
    assert "The free tool shelf is open this Saturday" not in unavailable
    assert "The free tool shelf is open this Saturday" not in removed


def test_original_m7a_boundary_bundle_is_embedded_exactly(
    m7a: dict[str, object], m7c: dict[str, object]
) -> None:
    files = {item.path: item.body for item in m7c["bundle"].all_files}
    base = m7a["bundle"]
    assert m7c["bundle"].embedded_m7a_bundle_id == base.bundle_id
    for item in base.all_files:
        assert files[f"lab/{item.path}"] == item.body


def test_showcase_bundle_manifest_and_checksums_are_deterministic(
    m7c: dict[str, object],
) -> None:
    bundle = m7c["bundle"]
    vector = m7c["vector"]
    assert bundle.showcase_version == SHOWCASE_VERSION
    assert bundle.bundle_id == vector["expectedBundleId"]
    assert len(bundle.all_files) == vector["expectedFileCount"]
    manifest = json.loads(bundle.manifest_bytes)
    assert manifest["synthetic"] is True
    assert manifest["communityName"] == COMMUNITY_NAME
    checksums = {
        line.partition("  ")[2]
        for line in next(
            item for item in bundle.all_files if item.path == "checksums.txt"
        )
        .body.decode()
        .splitlines()
    }
    assert checksums == {item.path for item in bundle.all_files} - {"checksums.txt"}


def test_showcase_writes_reverifies_and_cli_replays(
    m7c: dict[str, object], tmp_path: Path, capsys
) -> None:
    direct = tmp_path / "direct"
    bundle = m7c["bundle"]
    bundle.write_directory(direct)
    assert bundle.verify_directory(direct) == bundle.bundle_id

    cli = tmp_path / "cli"
    assert main([str(cli)]) == 0
    written = json.loads(capsys.readouterr().out)
    assert written["bundleId"] == bundle.bundle_id
    assert main([str(cli), "--check"]) == 0
    checked = json.loads(capsys.readouterr().out)
    assert checked["action"] == "verified"


def test_showcase_fixture_is_explicitly_synthetic_and_nonsecret(
    m7c: dict[str, object],
) -> None:
    vector = m7c["vector"]
    assert vector["synthetic"] is True
    assert vector["liveAtprotoData"] is False
    assert vector["secretMaterialPresent"] is False
    assert vector["humanUsabilityClaim"] is False


def test_showcase_explains_synthetic_authority_without_weakening_nonclaims(
    m7c: dict[str, object],
) -> None:
    files = {item.path: item.body.decode() for item in m7c["bundle"].all_files}
    assert "one specific moderation authorization" in files["index.html"]
    assert "Designed for clarity, but not yet user-tested." in files["about.html"]
    assert "human_comprehension" in files["manifest.json"]
    assert "human_usability" in files["manifest.json"]


def test_every_showcase_navigation_target_is_internal_and_present(
    m7c: dict[str, object], tmp_path: Path
) -> None:
    root = tmp_path / "site"
    m7c["bundle"].write_directory(root)
    for page in root.rglob("*.html"):
        parser = _LinkParser()
        parser.feed(page.read_text(encoding="utf-8"))
        for href in parser.links:
            target, _ = urldefrag(href)
            if not target:
                continue
            assert "://" not in target
            resolved = page.parent / target
            if target.endswith("/") or resolved.is_dir():
                resolved /= "index.html"
            assert resolved.resolve().is_relative_to(root.resolve())
            assert resolved.is_file(), f"broken link from {page}: {href}"
