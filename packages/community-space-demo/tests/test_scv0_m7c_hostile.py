from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from community_space_demo import (
    HumanShowcaseCompiler,
    ShowcaseCorpus,
    build_synthetic_demo_sites,
    refuse_showcase_claim_upgrade,
)


def test_missing_or_reordered_lifecycle_story_refuses(m7c: dict[str, object]) -> None:
    corpus = m7c["corpus"]
    with pytest.raises(ValueError, match="frozen order"):
        ShowcaseCorpus(
            community_site=corpus.community_site,
            lifecycle_sites={
                key: value
                for key, value in corpus.lifecycle_sites.items()
                if key != "removed"
            },
        )
    with pytest.raises(ValueError, match="frozen order"):
        ShowcaseCorpus(
            community_site=corpus.community_site,
            lifecycle_sites=dict(reversed(tuple(corpus.lifecycle_sites.items()))),
        )


def test_foreign_lifecycle_community_or_source_refuses(m7c: dict[str, object]) -> None:
    corpus = m7c["corpus"]
    foreign = build_synthetic_demo_sites()["removed"]
    sites = dict(corpus.lifecycle_sites)
    sites["removed"] = foreign
    with pytest.raises(ValueError, match="community mismatch"):
        ShowcaseCorpus(community_site=corpus.community_site, lifecycle_sites=sites)


def test_showcase_claim_relabeling_refuses(m7c: dict[str, object]) -> None:
    bundle = m7c["bundle"]
    with pytest.raises(ValueError, match="claims and non-claims are fixed"):
        replace(
            bundle,
            explicit_non_claims=tuple(
                item for item in bundle.explicit_non_claims if item != "human_usability"
            ),
        )
    with pytest.raises(ValueError, match="cannot add human or authority claims"):
        refuse_showcase_claim_upgrade({"humanUsability": True})


def test_compiler_refuses_untyped_or_substituted_inputs(
    m7a: dict[str, object], m7c: dict[str, object]
) -> None:
    compiler = HumanShowcaseCompiler()
    with pytest.raises(TypeError, match="ShowcaseCorpus"):
        compiler.compile({}, m7a["bundle"])
    with pytest.raises(TypeError, match="exact M7A"):
        compiler.compile(  # type: ignore[arg-type]
            m7c["corpus"],
            object(),
        )


def test_ordinary_showcase_cannot_leak_audit_identifiers(
    m7c: dict[str, object],
) -> None:
    files = {
        item.path: item.body.decode(errors="ignore") for item in m7c["bundle"].all_files
    }
    ordinary_paths = (
        "index.html",
        "states/added/index.html",
        "states/changed-at-source/index.html",
        "states/source-unavailable/index.html",
        "states/removed/index.html",
    )
    receipts = {
        value
        for site in (
            m7c["corpus"].community_site,
            *m7c["corpus"].lifecycle_sites.values(),
        )
        for entry in site.audit_semantics.entries
        for _, value in entry.receipt_references
    }
    for path in ordinary_paths:
        assert all(value not in files[path] for value in receipts)


def test_showcase_mutation_extra_file_and_symlink_refuse(
    m7c: dict[str, object], tmp_path: Path
) -> None:
    bundle = m7c["bundle"]
    mutated = tmp_path / "mutated"
    bundle.write_directory(mutated)
    (mutated / "styles.css").write_text("different", encoding="utf-8")
    with pytest.raises(ValueError, match="byte mismatch"):
        bundle.verify_directory(mutated)

    extra = tmp_path / "extra"
    bundle.write_directory(extra)
    (extra / "authority.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="file set mismatch"):
        bundle.verify_directory(extra)

    linked = tmp_path / "linked"
    bundle.write_directory(linked)
    try:
        (linked / "link").symlink_to(linked / "index.html")
    except OSError:
        pytest.skip("fixture filesystem does not permit symlinks")
    with pytest.raises(ValueError, match="symbolic links"):
        bundle.verify_directory(linked)


def test_showcase_refuses_broad_or_nonempty_output(
    m7c: dict[str, object], tmp_path: Path
) -> None:
    bundle = m7c["bundle"]
    with pytest.raises(ValueError, match="broad showcase output"):
        bundle.write_directory(Path("/"))
    with pytest.raises(ValueError, match="broad showcase output"):
        bundle.write_directory(Path.home())
    target = tmp_path / "existing"
    target.mkdir()
    (target / "keep").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="absent or empty"):
        bundle.write_directory(target)
    assert (target / "keep").read_text(encoding="utf-8") == "keep"


def test_showcase_contains_no_active_or_external_browser_dependencies(
    m7c: dict[str, object],
) -> None:
    files = {
        item.path: item.body.decode(errors="ignore") for item in m7c["bundle"].all_files
    }
    public = "\n".join(
        body for path, body in files.items() if not path.startswith("lab/")
    ).lower()
    assert "<script" not in public
    assert "javascript:" not in public
    assert "http://" not in public
    assert "https://" not in public
    assert "authorization: bearer" not in public
    assert "cookie:" not in public
