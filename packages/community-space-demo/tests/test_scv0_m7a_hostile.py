from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from community_space_demo import DemoFile, StaticDemoCompiler


def test_missing_or_reordered_lifecycle_corpus_refuses(m7a: dict[str, object]) -> None:
    sites = m7a["sites"]
    with pytest.raises(ValueError, match="four frozen lifecycle sites"):
        StaticDemoCompiler().compile(
            {key: value for key, value in sites.items() if key != "removed"}
        )
    with pytest.raises(ValueError, match="four frozen lifecycle sites"):
        StaticDemoCompiler().compile(dict(reversed(tuple(sites.items()))))


@pytest.mark.parametrize(
    "path", ("../index.html", "/index.html", "added/../index.html", "a\\b")
)
def test_path_traversal_or_ambiguity_refuses(path: str) -> None:
    with pytest.raises(ValueError, match="path"):
        DemoFile.create(path, "text/plain", b"x")


def test_file_digest_substitution_refuses() -> None:
    with pytest.raises(ValueError, match="digest does not match"):
        DemoFile(
            path="index.html",
            media_type="text/html",
            body=b"one",
            body_sha256="sha256:" + "0" * 64,
        )


def test_existing_nonempty_directory_is_never_overwritten(
    m7a: dict[str, object], tmp_path: Path
) -> None:
    target = tmp_path / "site"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="absent or empty"):
        m7a["bundle"].write_directory(target)
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_postexport_byte_mutation_and_extra_file_refuse(
    m7a: dict[str, object], tmp_path: Path
) -> None:
    first = tmp_path / "mutated"
    m7a["bundle"].write_directory(first)
    (first / "index.html").write_text("different", encoding="utf-8")
    with pytest.raises(ValueError, match="byte mismatch"):
        m7a["bundle"].verify_directory(first)

    second = tmp_path / "extra"
    m7a["bundle"].write_directory(second)
    (second / "unmanifested.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(ValueError, match="file set mismatch"):
        m7a["bundle"].verify_directory(second)


def test_symlink_in_export_refuses(m7a: dict[str, object], tmp_path: Path) -> None:
    target = tmp_path / "site"
    m7a["bundle"].write_directory(target)
    link = target / "link"
    try:
        link.symlink_to(target / "index.html")
    except OSError:
        pytest.skip("fixture filesystem does not permit symlinks")
    with pytest.raises(ValueError, match="symbolic links"):
        m7a["bundle"].verify_directory(target)


def test_demo_claims_cannot_be_relabelled(m7a: dict[str, object]) -> None:
    bundle = m7a["bundle"]
    with pytest.raises(ValueError, match="claims and non-claims are fixed"):
        replace(
            bundle,
            explicit_non_claims=tuple(
                item for item in bundle.explicit_non_claims if item != "human_usability"
            ),
        )


def test_broad_output_directories_refuse(m7a: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="broad demo output"):
        m7a["bundle"].write_directory(Path("/"))
    with pytest.raises(ValueError, match="broad demo output"):
        m7a["bundle"].write_directory(Path.home())
