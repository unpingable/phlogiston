from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from community_model import ValidationError
from communitywatch import ObserverStore
from communitywatch_archive import cold
from communitywatch_archive.cold import ColdReader
from communitywatch_archive.export import export_generation
from communitywatch_archive.observerdb import connect_readonly
from conftest import (
    BASE_TIME,
    make_delivery,
    make_store,
)

PACKAGE_SRC = Path(__file__).parents[1] / "src"


def _sqlite_rows(db_path: Path, table: str) -> dict[int, dict[str, object]]:
    with connect_readonly(db_path) as connection:
        rows = connection.execute(
            f"SELECT * FROM {table} ORDER BY observer_sequence"  # noqa: S608
        ).fetchall()
    return {int(row["observer_sequence"]): dict(row) for row in rows}


def test_cold_scan_matches_sqlite_fixture_rows(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    """Duplicate/conflicting/quarantined/late data agree across the seam."""

    store, db_path, artifacts = populated
    # A second, conflicting variant under one semantic identity.
    store.ingest(
        make_delivery(
            "submit",
            cursor="5",
            rev="3jzfcijpj2z2c",
            record={"$type": "app.phlogiston.community.submit", "text": "forged"},
            received_at=BASE_TIME + timedelta(seconds=5),
        )
    )
    result = export_generation(db_path, artifacts, token="c1")
    with ColdReader(artifacts) as reader:
        for table, sqlite_table in (
            ("receipts", "event_receipts"),
            ("quarantine", "quarantined_deliveries"),
            ("observations", "subject_observations"),
        ):
            scanned = {
                int(row["observer_sequence"]): {
                    key: value for key, value in row.items() if not key.endswith("_day")
                }
                for row in reader.scan(
                    result.generation_id, table, min_sequence=0, max_sequence=100
                )
            }
            assert scanned == _sqlite_rows(db_path, sqlite_table)
        variants = list(
            reader.scan(
                result.generation_id,
                "event_variants",
                min_sequence=0,
                max_sequence=100,
            )
        )
    submit_variants = [
        row
        for row in variants
        if row["collection"] == "app.phlogiston.community.submit"
    ]
    assert len(submit_variants) == 2  # the intentional payload conflict


def test_cold_reader_has_no_sqlite_or_hot_handle() -> None:
    """Cold queries must not import or open the observer SQLite database."""

    source = (PACKAGE_SRC / "communitywatch_archive" / "cold.py").read_text()
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.partition(".")[0])
    assert "sqlite3" not in imported
    assert "observerdb" not in imported
    assert not hasattr(cold, "sqlite3")


def test_cold_scan_is_bounded_and_streaming(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    _, db_path, artifacts = populated
    result = export_generation(db_path, artifacts, token="c2")
    with ColdReader(artifacts, max_horizon=8, max_limit=4) as reader:
        stream = reader.scan(
            result.generation_id, "receipts", min_sequence=0, max_sequence=8, limit=2
        )
        assert isinstance(stream, Iterator)
        assert len(list(stream)) == 2
        with pytest.raises(ValidationError, match="archive_horizon_invalid"):
            list(
                reader.scan(
                    result.generation_id, "receipts", min_sequence=0, max_sequence=99
                )
            )
        with pytest.raises(ValidationError, match="archive_limit_invalid"):
            list(
                reader.scan(
                    result.generation_id,
                    "receipts",
                    min_sequence=0,
                    max_sequence=8,
                    limit=100,
                )
            )
        with pytest.raises(ValidationError, match="archive_table_unknown"):
            list(
                reader.scan(
                    result.generation_id, "meta", min_sequence=0, max_sequence=8
                )
            )


def test_missing_manifest_listed_partition_is_explicit(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    _, db_path, artifacts = populated
    result = export_generation(db_path, artifacts, token="c3")
    next(result.sealed_dir.rglob("*.parquet")).unlink()
    with ColdReader(artifacts) as reader:
        with pytest.raises(ValidationError, match="archive_partition_missing"):
            list(
                reader.scan(
                    result.generation_id, "receipts", min_sequence=0, max_sequence=100
                )
            )


def test_query_cli_streams_under_an_external_memory_ceiling(tmp_path: Path) -> None:
    """The query CLI streams bounded results under an RSS ceiling."""

    store = make_store(tmp_path)
    deliveries = [
        make_delivery("submit", cursor=str(index), rev="3jzfcijpj2z2c")
        for index in range(1, 2001)
    ]
    store.ingest_batch(deliveries)
    artifacts = tmp_path / "artifacts"
    result = export_generation(store.path, artifacts, token="c4")

    def ceiling() -> None:
        import resource

        limit = 768 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_RSS, (limit, limit))

    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        str(path)
        for path in (
            PACKAGE_SRC,
            PACKAGE_SRC.parent.parent / "community-model" / "src",
            PACKAGE_SRC.parent.parent / "communitywatch" / "src",
        )
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "communitywatch_archive",
            "query",
            "--artifacts",
            str(artifacts),
            "--generation",
            result.generation_id,
            "--table",
            "receipts",
            "--from-seq",
            "0",
            "--to-seq",
            "5000",
            "--limit",
            "2000",
        ],
        cwd=tmp_path,
        env=environment,
        preexec_fn=ceiling,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.strip().splitlines()
    assert len(lines) == 2000
    first = json.loads(lines[0])
    assert first["observer_sequence"] == 1
    assert first["received_at_day"] == BASE_TIME.isoformat()[:10]
