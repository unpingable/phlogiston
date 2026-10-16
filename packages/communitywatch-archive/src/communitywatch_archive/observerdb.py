"""Observer SQLite access for the offline archive tool.

The archive tool opens the observer database only in explicit offline
maintenance mode.  Reads always use URI read-only mode with
``PRAGMA query_only``; writes are limited to the ``archive_generations``
control table and gated retention deletions.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from community_model import ValidationError, canonical_json_bytes

DEFAULT_BUSY_TIMEOUT_MS = 5_000
SUPPORTED_OBSERVER_SCHEMA_VERSIONS = frozenset({1, 2, 3})


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_observer_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def canonical_json(value: object) -> str:
    return canonical_json_bytes(value).decode("utf-8")


@contextmanager
def connect_readonly(path: str | Path) -> Iterator[sqlite3.Connection]:
    resolved = Path(path).resolve()
    if not resolved.exists():
        raise ValidationError(
            "archive_database_missing", f"observer database {resolved} is absent"
        )
    connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA query_only = ON")
    connection.execute(f"PRAGMA busy_timeout = {DEFAULT_BUSY_TIMEOUT_MS}")
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def connect_maintenance(path: str | Path) -> Iterator[sqlite3.Connection]:
    """Open the offline maintenance writer for archive-control/retention state."""

    resolved = Path(path).resolve()
    if not resolved.exists():
        raise ValidationError(
            "archive_database_missing", f"observer database {resolved} is absent"
        )
    connection = sqlite3.connect(resolved)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {DEFAULT_BUSY_TIMEOUT_MS}")
    try:
        yield connection
    finally:
        connection.close()


def check_observer_schema(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    if row is None or int(row[0]) not in SUPPORTED_OBSERVER_SCHEMA_VERSIONS:
        raise ValidationError(
            "schema_incompatible",
            "observer database schema is not supported by this archive reader",
        )


def committed_high_waters(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute(
        """
        SELECT source, committed_cursor FROM ingest_sources
        WHERE committed_cursor IS NOT NULL ORDER BY source
        """
    ).fetchall()
    return {row["source"]: row["committed_cursor"] for row in rows}


def archive_row(
    connection: sqlite3.Connection, generation_id: str
) -> Mapping[str, object] | None:
    return connection.execute(
        "SELECT * FROM archive_generations WHERE archive_generation_id = ?",
        (generation_id,),
    ).fetchone()


def upsert_archive_row(
    connection: sqlite3.Connection,
    *,
    generation_id: str,
    manifest: Mapping[str, object],
    lifecycle: str,
    last_good: int = 0,
) -> None:
    """Idempotently reconcile one archive-control row with a manifest."""

    row_counts = {
        table: int(spec["rowCount"]) for table, spec in manifest["tables"].items()
    }
    byte_hashes = {
        file["path"]: file["sha256"]
        for spec in manifest["tables"].values()
        for file in spec["files"]
    }
    existing = archive_row(connection, generation_id)
    values = {
        "archive_generation_id": generation_id,
        "manifest_identity": manifest["manifestIdentity"],
        "lifecycle": lifecycle,
        "partition_version": manifest["partitionVersion"],
        "schema_version": manifest["schemaVersion"],
        "row_counts_json": canonical_json(row_counts),
        "byte_hashes_json": canonical_json(byte_hashes),
        "min_received_at": manifest["minReceivedAt"],
        "max_received_at": manifest["maxReceivedAt"],
        "min_observer_sequence": manifest["minObserverSequence"],
        "max_observer_sequence": manifest["maxObserverSequence"],
        "source_high_waters_json": canonical_json(manifest["sourceHighWaters"]),
        "exclusions_json": canonical_json(manifest["exclusions"]),
        "cannot_testify_json": canonical_json(manifest["cannotTestify"]),
        "last_good": last_good,
    }
    if existing is not None:
        if existing["manifest_identity"] != values["manifest_identity"]:
            raise ValidationError(
                "archive_manifest_conflict",
                f"archive-control row for {generation_id} names another manifest",
            )
        connection.execute(
            """
            UPDATE archive_generations SET lifecycle = ?, last_good = ?
            WHERE archive_generation_id = ?
            """,
            (lifecycle, last_good, generation_id),
        )
        return
    connection.execute(
        """
        INSERT INTO archive_generations(
            archive_generation_id, manifest_identity, lifecycle,
            partition_version, schema_version, row_counts_json, byte_hashes_json,
            min_received_at, max_received_at, min_observer_sequence,
            max_observer_sequence, source_high_waters_json, exclusions_json,
            cannot_testify_json, last_good
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            values["archive_generation_id"],
            values["manifest_identity"],
            values["lifecycle"],
            values["partition_version"],
            values["schema_version"],
            values["row_counts_json"],
            values["byte_hashes_json"],
            values["min_received_at"],
            values["max_received_at"],
            values["min_observer_sequence"],
            values["max_observer_sequence"],
            values["source_high_waters_json"],
            values["exclusions_json"],
            values["cannot_testify_json"],
            values["last_good"],
        ),
    )


def accepted_generations(connection: sqlite3.Connection) -> list[Mapping[str, object]]:
    """Generations whose sealed bytes remain valid custody.

    ``superseded`` generations are no longer last-good but still hold their
    covered prefix; pruning never removes them, so both states participate.
    """

    return connection.execute(
        """
        SELECT * FROM archive_generations
        WHERE lifecycle IN ('accepted', 'superseded')
        ORDER BY min_observer_sequence
        """
    ).fetchall()


def covered_prefix(connection: sqlite3.Connection) -> int:
    """Highest observer sequence covered by an accepted generation."""

    row = connection.execute(
        """
        SELECT max(max_observer_sequence) FROM archive_generations
        WHERE lifecycle IN ('accepted', 'superseded')
        """
    ).fetchone()
    value = row[0] if row is not None else None
    return 0 if value is None else int(value)
