from __future__ import annotations

import json
from pathlib import Path

import pytest

from communitywatch import ObserverStore
from communitywatch_archive.cli import main
from conftest import ADMIN_DID, COMMUNITY_DID, make_delivery


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, object]:
    code = main(list(argv))
    captured = capsys.readouterr()
    if code == 0:
        return code, json.loads(captured.out.strip().splitlines()[-1])
    return code, json.loads(captured.err.strip())


def test_cli_export_accept_prune_query_round_trip(
    populated: tuple[ObserverStore, Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    store, db_path, artifacts = populated
    code, exported = _run(
        capsys, "export", "--db", str(db_path), "--artifacts", str(artifacts)
    )
    assert code == 0
    generation = exported["generation"]  # type: ignore[index]

    code, accepted = _run(
        capsys,
        "accept",
        "--db",
        str(db_path),
        "--artifacts",
        str(artifacts),
        "--generation",
        generation,
        "--community-did",
        COMMUNITY_DID,
        "--administrator-did",
        ADMIN_DID,
    )
    assert code == 0
    assert accepted["receiptDigest"].startswith("sha256:")  # type: ignore[index]

    code, pruned = _run(
        capsys,
        "prune",
        "--db",
        str(db_path),
        "--artifacts",
        str(artifacts),
        "--generation",
        generation,
    )
    assert code == 0
    assert pruned["alreadyPruned"] is False  # type: ignore[index]

    code, retried = _run(
        capsys,
        "prune",
        "--db",
        str(db_path),
        "--artifacts",
        str(artifacts),
        "--generation",
        generation,
    )
    assert code == 0
    assert retried["alreadyPruned"] is True  # type: ignore[index]

    # The tail still accepts new observations after pruning.
    store.ingest(make_delivery("mod_action", cursor="4", rev="3jzfcijpj2z2f"))

    code = main(
        [
            "query",
            "--artifacts",
            str(artifacts),
            "--generation",
            generation,
            "--table",
            "receipts",
            "--from-seq",
            "0",
            "--to-seq",
            "100",
        ]
    )
    assert code == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 3
    assert all(json.loads(line)["observer_sequence"] <= 5 for line in lines)


def test_cli_errors_are_json_on_stderr_with_exit_2(
    populated: tuple[ObserverStore, Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, db_path, artifacts = populated
    code, error = _run(
        capsys,
        "export",
        "--db",
        str(db_path),
        "--artifacts",
        str(artifacts),
        "--high-water",
        "fixture-source=bogus",
    )
    assert code == 2
    assert error["error"] == "archive_high_water_mismatch"  # type: ignore[index]

    code, error = _run(
        capsys,
        "prune",
        "--db",
        str(db_path),
        "--artifacts",
        str(artifacts),
        "--generation",
        "gen-00000000000000000005-nope",
    )
    assert code == 2
    assert error["error"] == "archive_generation_missing"  # type: ignore[index]


def test_cli_recovers_abandoned_staging(
    populated: tuple[ObserverStore, Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, db_path, artifacts = populated
    abandoned = artifacts / "staging" / "gen-00000000000000000009-dead"
    abandoned.mkdir(parents=True)
    (abandoned / "junk").write_bytes(b"partial")
    code, report = _run(
        capsys, "recover", "--db", str(db_path), "--artifacts", str(artifacts)
    )
    assert code == 0
    assert report["quarantinedStaging"] == [  # type: ignore[index]
        "gen-00000000000000000009-dead"
    ]
    assert not abandoned.exists()
