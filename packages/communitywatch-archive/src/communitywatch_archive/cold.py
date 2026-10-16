"""Bounded read-only DuckDB access to sealed, manifest-listed history.

This module opens no SQLite handle.  It queries only the Parquet partitions
listed in a sealed generation's manifest, inside explicit observer-sequence
horizons and row limits, and streams rows in bounded batches rather than
materializing an unbounded in-memory identity map.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import duckdb

from community_model import ValidationError

from .export import expected_columns, sealed_manifest, table_names
from .layout import ArtifactRoot, validate_generation_id

DEFAULT_BATCH_SIZE = 2048
DEFAULT_MAX_LIMIT = 10_000
DEFAULT_MAX_HORIZON = 1_000_000
DEFAULT_MEMORY_LIMIT = "256MB"

_OCCURRENCE_TABLES = ("receipts", "quarantine", "observations")


def _quote(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


class ColdReader:
    """Read-only bounded queries over manifest-listed sealed partitions."""

    def __init__(
        self,
        artifact_root: str | Path,
        *,
        memory_limit: str = DEFAULT_MEMORY_LIMIT,
        max_horizon: int = DEFAULT_MAX_HORIZON,
        max_limit: int = DEFAULT_MAX_LIMIT,
    ) -> None:
        self.root = ArtifactRoot(artifact_root)
        if not 1 <= max_horizon <= DEFAULT_MAX_HORIZON:
            raise ValidationError(
                "archive_horizon_invalid", "max_horizon out of bounds"
            )
        if not 1 <= max_limit <= DEFAULT_MAX_LIMIT:
            raise ValidationError("archive_limit_invalid", "max_limit out of bounds")
        self.max_horizon = max_horizon
        self.max_limit = max_limit
        self._connection = duckdb.connect(":memory:")
        self._connection.execute(f"SET memory_limit = '{memory_limit}'")

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> ColdReader:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def manifest(self, generation_id: str) -> dict[str, object]:
        """Validate a sealed generation and return its manifest."""

        return sealed_manifest(self.root, validate_generation_id(generation_id))

    def _files(self, generation_id: str, table: str) -> list[Path]:
        manifest = self.manifest(generation_id)
        entry = manifest["tables"][table]
        paths = []
        for file_entry in entry["files"]:
            path = self.root.sealed_generation(generation_id) / file_entry["path"]
            if not path.is_file():
                raise ValidationError(
                    "archive_partition_missing",
                    f"manifest-listed partition {file_entry['path']} is absent",
                )
            paths.append(path)
        return paths

    def scan(
        self,
        generation_id: str,
        table: str,
        *,
        min_sequence: int,
        max_sequence: int,
        limit: int | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> Iterator[dict[str, object]]:
        """Stream manifest-listed rows inside one bounded sequence horizon.

        Variant tables carry no observer sequence; they accept the full
        horizon.  At most ``limit`` rows are produced, in bounded batches.
        """

        if table not in table_names():
            raise ValidationError(
                "archive_table_unknown", f"unknown archive table {table!r}"
            )
        if not 0 <= min_sequence <= max_sequence:
            raise ValidationError(
                "archive_horizon_invalid", "observer-sequence horizon is inverted"
            )
        if max_sequence - min_sequence > self.max_horizon:
            raise ValidationError(
                "archive_horizon_invalid", "observer-sequence horizon is too wide"
            )
        effective_limit = self.max_limit if limit is None else limit
        if not 1 <= effective_limit <= self.max_limit:
            raise ValidationError(
                "archive_limit_invalid", f"limit must be within 1..{self.max_limit}"
            )
        files = self._files(generation_id, table)
        if not files:
            return
        listed = ", ".join(_quote(path) for path in files)
        columns = ", ".join(expected_columns(table))
        where = ""
        order = ""
        if table in _OCCURRENCE_TABLES:
            where = (
                f"WHERE observer_sequence >= {min_sequence} "
                f"AND observer_sequence <= {max_sequence}"
            )
            order = "ORDER BY observer_sequence"
        query = (
            f"SELECT {columns} FROM read_parquet([{listed}], union_by_name = true, "
            f"hive_partitioning = false) {where} {order} LIMIT {effective_limit}"
        )  # noqa: S608
        result = self._connection.execute(query)
        names = [column[0] for column in result.description]
        produced = 0
        while produced < effective_limit:
            batch = result.fetchmany(min(batch_size, effective_limit - produced))
            if not batch:
                return
            for row in batch:
                produced += 1
                yield dict(zip(names, row, strict=True))
