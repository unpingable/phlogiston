"""Offline prefix export, manifest validation, and durable sealing.

Exports a closed observer-sequence prefix of delivery receipts, quarantined
deliveries, and subject observations to Parquet, partitioned principally by
trusted observer time, with bulky payload variants in separate files
referenced by stable keys.  Stages one uniquely named generation, validates
schema/counts/byte-hashes/ranges against its manifest, fsyncs everything,
and atomically renames it into the sealed inventory.  Sealing never moves
the accepted last-good pointer.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from community_model import ValidationError, canonical_json_bytes, sha256_digest

from .layout import (
    MANIFEST_FILE,
    MANIFEST_VERSION,
    PARTITION_VERSION,
    SCHEMA_VERSION,
    ArtifactRoot,
    fsync_tree,
    generation_id_for,
    publish_staged,
    validate_generation_id,
)
from .observerdb import (
    archive_row,
    check_observer_schema,
    committed_high_waters,
    connect_maintenance,
    connect_readonly,
    covered_prefix,
    upsert_archive_row,
    utc_now,
)

# Compact occurrence tables: partitioned by trusted observer time and keyed
# by observer_sequence.  `time_column` is the partition/ordering coordinate;
# it is always observer-recorded time, never actor or source time.
_TABLES: dict[str, dict[str, object]] = {
    "receipts": {
        "directory": "receipts",
        "time_column": "received_at",
        "partition_column": "received_at_day",
        "columns": (
            "source",
            "cursor",
            "event_variant_key",
            "raw_envelope_hash",
            "source_event_time",
            "received_at",
            "observer_sequence",
            "trust_mode",
            "verification_outcome",
            "verification_method",
            "verifier_version",
            "evidence_ref",
            "evidence_hash",
        ),
    },
    "quarantine": {
        "directory": "quarantine",
        "time_column": "received_at",
        "partition_column": "received_at_day",
        "columns": (
            "quarantine_key",
            "source",
            "cursor",
            "raw_envelope",
            "raw_envelope_hash",
            "source_event_time",
            "received_at",
            "observer_sequence",
            "trust_mode",
            "verification_outcome",
            "verification_method",
            "verifier_version",
            "evidence_ref",
            "evidence_hash",
            "reason_code",
        ),
    },
    "observations": {
        "directory": "observations",
        "time_column": "checked_at",
        "partition_column": "checked_at_day",
        "columns": (
            "observation_key",
            "subject_variant_key",
            "triggering_event_variant_key",
            "checked_at",
            "observer_sequence",
            "trust_mode",
            "verification_outcome",
            "resolution_method",
            "resolver_version",
            "evidence_ref",
            "evidence_hash",
        ),
    },
    "event_variants": {
        "directory": "event_variants",
        "time_column": None,
        "partition_column": None,
        "columns": (
            "event_variant_key",
            "semantic_event_key",
            "event_schema_version",
            "commit_identity",
            "repo_order",
            "repo_did",
            "operation",
            "collection",
            "rkey",
            "record_uri",
            "record_cid",
            "record_json",
            "record_bytes",
            "commit_rev",
            "commit_cid",
            "payload_hash",
            "payload_hash_scope",
        ),
    },
    "subject_variants": {
        "directory": "subject_variants",
        "time_column": None,
        "partition_column": None,
        "columns": (
            "subject_variant_key",
            "requested_uri",
            "requested_cid",
            "status",
            "current_cid",
            "record_json",
            "payload_hash",
            "payload_hash_scope",
        ),
    },
}

_OCCURRENCE_TABLES = ("receipts", "quarantine", "observations")

_BINARY_COLUMNS = {"raw_envelope", "record_bytes"}
_INT_COLUMNS = {"observer_sequence", "event_schema_version"}

_OCCURRENCE_SQL = {
    "receipts": """
        SELECT * FROM event_receipts
        WHERE observer_sequence > ? AND observer_sequence <= ?
        ORDER BY observer_sequence
    """,
    "quarantine": """
        SELECT * FROM quarantined_deliveries
        WHERE observer_sequence > ? AND observer_sequence <= ?
        ORDER BY observer_sequence
    """,
    "observations": """
        SELECT * FROM subject_observations
        WHERE observer_sequence > ? AND observer_sequence <= ?
        ORDER BY observer_sequence
    """,
}


@dataclass(frozen=True, slots=True)
class PrefixPlan:
    """One closed observer-sequence prefix with explicit source high-waters."""

    previous_max: int
    max_sequence: int
    source_high_waters: dict[str, str]


@dataclass(frozen=True, slots=True)
class ExportResult:
    generation_id: str
    manifest: dict[str, object]
    sealed_dir: Path


def _arrow_schema(table: str) -> pa.Schema:
    spec = _TABLES[table]
    fields: list[pa.Field] = []
    for column in spec["columns"]:  # type: ignore[union-attr]
        if column in _BINARY_COLUMNS:
            fields.append(pa.field(column, pa.binary()))
        elif column in _INT_COLUMNS:
            fields.append(pa.field(column, pa.int64()))
        else:
            fields.append(pa.field(column, pa.string()))
    partition_column = spec["partition_column"]
    if partition_column is not None:
        fields.append(pa.field(str(partition_column), pa.string()))
    return pa.schema(fields)


def expected_columns(table: str) -> tuple[str, ...]:
    """Manifest-listed column order for one exported table."""

    spec = _TABLES[table]
    columns: tuple[str, ...] = spec["columns"]  # type: ignore[assignment]
    partition_column = spec["partition_column"]
    if partition_column is not None:
        return (*columns, str(partition_column))
    return columns


def table_names() -> tuple[str, ...]:
    return tuple(_TABLES)


def plan_prefix(
    connection: sqlite3.Connection,
    high_waters: dict[str, str] | None = None,
) -> PrefixPlan:
    """Close the observer-sequence prefix at the committed source high-waters.

    Declared high-waters must equal the durably committed per-source cursors:
    the tool never holds an ingest read snapshot, so it refuses anything but
    the committed custody boundary.
    """

    check_observer_schema(connection)
    committed = committed_high_waters(connection)
    declared = committed if high_waters is None else dict(high_waters)
    if declared != committed:
        raise ValidationError(
            "archive_high_water_mismatch",
            "declared high-waters must equal committed per-source cursors",
        )
    pending = connection.execute(
        """
        SELECT archive_generation_id FROM archive_generations
        WHERE lifecycle IN ('staged', 'sealed')
        """
    ).fetchone()
    if pending is not None:
        raise ValidationError(
            "archive_pending_generation",
            f"generation {pending[0]} awaits acceptance or recovery",
        )
    source_sequences: dict[str, int] = {}
    for source, cursor in declared.items():
        row = connection.execute(
            """
            SELECT observer_sequence FROM (
                SELECT observer_sequence FROM event_receipts
                WHERE source = ? AND cursor = ?
                UNION ALL
                SELECT observer_sequence FROM quarantined_deliveries
                WHERE source = ? AND cursor = ?
            )
            """,
            (source, cursor, source, cursor),
        ).fetchone()
        if row is None:
            raise ValidationError(
                "archive_high_water_unknown",
                f"committed cursor for source {source} has no custody row",
            )
        source_sequences[source] = int(row[0])
    placeholders = ",".join("?" for _ in declared) or "''"
    stray = connection.execute(
        f"""
        SELECT DISTINCT source FROM (
            SELECT source FROM event_receipts
            UNION SELECT source FROM quarantined_deliveries
        ) WHERE source NOT IN ({placeholders})
        """,  # noqa: S608
        tuple(declared),
    ).fetchall()
    if stray:
        raise ValidationError(
            "archive_high_water_mismatch",
            f"sources without declared high-water: {sorted(row[0] for row in stray)}",
        )
    previous_max = covered_prefix(connection)
    max_sequence = max(source_sequences.values(), default=previous_max)
    if max_sequence <= previous_max:
        raise ValidationError(
            "archive_nothing_to_export",
            "no occurrence rows beyond the accepted sealed prefix",
        )
    return PrefixPlan(
        previous_max=previous_max,
        max_sequence=max_sequence,
        source_high_waters=dict(declared),
    )


def _load_occurrences(
    connection: sqlite3.Connection, table: str, plan: PrefixPlan
) -> list[sqlite3.Row]:
    return connection.execute(
        _OCCURRENCE_SQL[table], (plan.previous_max, plan.max_sequence)
    ).fetchall()


def _load_event_variants(
    connection: sqlite3.Connection, plan: PrefixPlan
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT * FROM repo_events WHERE event_variant_key IN (
            SELECT event_variant_key FROM event_receipts
            WHERE observer_sequence > ? AND observer_sequence <= ?
            UNION
            SELECT triggering_event_variant_key FROM subject_observations
            WHERE observer_sequence > ? AND observer_sequence <= ?
              AND triggering_event_variant_key IS NOT NULL
        ) ORDER BY event_variant_key
        """,
        (
            plan.previous_max,
            plan.max_sequence,
            plan.previous_max,
            plan.max_sequence,
        ),
    ).fetchall()


def _load_subject_variants(
    connection: sqlite3.Connection, plan: PrefixPlan
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT * FROM subject_observation_variants WHERE subject_variant_key IN (
            SELECT subject_variant_key FROM subject_observations
            WHERE observer_sequence > ? AND observer_sequence <= ?
        ) ORDER BY subject_variant_key
        """,
        (plan.previous_max, plan.max_sequence),
    ).fetchall()


def _write_table(
    staging: Path,
    table: str,
    rows: list[sqlite3.Row],
) -> list[dict[str, object]]:
    """Write one table's rows partitioned by observer-time day."""

    spec = _TABLES[table]
    columns: tuple[str, ...] = spec["columns"]  # type: ignore[assignment]
    partition_column = spec["partition_column"]
    time_column = spec["time_column"]
    partitions: dict[str, list[sqlite3.Row]] = {}
    if partition_column is None:
        partitions[""] = rows
    else:
        for row in rows:
            day = str(row[time_column])[:10]  # type: ignore[index]
            partitions.setdefault(f"{partition_column}={day}", []).append(row)
    files: list[dict[str, object]] = []
    for partition, partition_rows in sorted(partitions.items()):
        directory = Path(spec["directory"])  # type: ignore[arg-type]
        if partition:
            directory = directory / partition
        target = staging / directory
        target.mkdir(parents=True, exist_ok=True)
        path = target / "part-0.parquet"
        data: dict[str, list[object]] = {column: [] for column in columns}
        if partition_column is not None:
            day_value = partition.partition("=")[2]
            data[str(partition_column)] = [day_value] * len(partition_rows)
        for row in partition_rows:
            for column in columns:
                data[column].append(row[column])
        frame = pa.table(data, schema=_arrow_schema(table))
        pq.write_table(frame, path)
        payload = path.read_bytes()
        relative = path.relative_to(staging).as_posix()
        files.append(
            {
                "path": relative,
                "bytes": len(payload),
                "sha256": sha256_digest(payload),
                "rows": len(partition_rows),
            }
        )
    return files


def _build_manifest(
    *,
    generation_id: str,
    plan: PrefixPlan,
    created_at: str,
    supersedes: str | None,
    occurrences: dict[str, list[sqlite3.Row]],
    files: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    tables: dict[str, object] = {}
    observer_times: list[str] = []
    sequences: list[int] = []
    for table in _TABLES:
        rows = occurrences.get(table, [])
        table_files = files[table]
        tables[table] = {
            "rowCount": sum(f["rows"] for f in table_files),
            "files": table_files,
        }
        if table in _OCCURRENCE_TABLES:
            spec = _TABLES[table]
            time_column = str(spec["time_column"])
            observer_times.extend(str(row[time_column]) for row in rows)
            sequences.extend(int(row["observer_sequence"]) for row in rows)
    if not sequences:
        raise ValidationError(
            "archive_nothing_to_export", "the closed prefix contains no occurrences"
        )
    manifest: dict[str, object] = {
        "manifestVersion": MANIFEST_VERSION,
        "partitionVersion": PARTITION_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "archiveGenerationId": generation_id,
        "createdAt": created_at,
        "supersedes": supersedes,
        "previousMaxObserverSequence": plan.previous_max,
        "minObserverSequence": min(sequences),
        "maxObserverSequence": max(sequences),
        "minReceivedAt": min(observer_times),
        "maxReceivedAt": max(observer_times),
        "sourceHighWaters": plan.source_high_waters,
        "exclusions": [],
        "cannotTestify": [],
        "tables": tables,
    }
    manifest["manifestIdentity"] = manifest_identity(manifest)
    return manifest


def manifest_identity(manifest: dict[str, object]) -> str:
    """Digest of the canonical manifest with the identity field excluded."""

    body = {key: value for key, value in manifest.items() if key != "manifestIdentity"}
    return sha256_digest(canonical_json_bytes(body))


def validate_generation(generation_dir: str | Path) -> dict[str, object]:
    """Re-read a staged/sealed generation and prove manifest agreement.

    Checks manifest identity, per-file byte size and hash, Parquet schema,
    row counts, min/max observer time and sequence, and per-source
    high-waters.  Completeness is never inferred from file presence: every
    fact comes from the manifest and is recomputed from the bytes.
    """

    generation_dir = Path(generation_dir)
    manifest_path = generation_dir / MANIFEST_FILE
    if not manifest_path.is_file():
        raise ValidationError(
            "archive_manifest_missing", f"no manifest in {generation_dir}"
        )
    try:
        manifest = json.loads(manifest_path.read_bytes())
    except json.JSONDecodeError as exc:
        raise ValidationError(
            "archive_manifest_invalid", f"manifest in {generation_dir} is not JSON"
        ) from exc
    if not isinstance(manifest, dict):
        raise ValidationError(
            "archive_manifest_invalid", f"manifest in {generation_dir} is not an object"
        )
    if (
        manifest.get("manifestVersion") != MANIFEST_VERSION
        or manifest.get("partitionVersion") != PARTITION_VERSION
        or manifest.get("schemaVersion") != SCHEMA_VERSION
    ):
        raise ValidationError(
            "archive_schema_rejected",
            f"manifest in {generation_dir} has unsupported versions",
        )
    if manifest.get("manifestIdentity") != manifest_identity(manifest):
        raise ValidationError(
            "archive_manifest_invalid",
            f"manifest identity mismatch in {generation_dir}",
        )
    tables = manifest.get("tables")
    if not isinstance(tables, dict) or set(tables) != set(_TABLES):
        raise ValidationError(
            "archive_manifest_invalid", f"manifest tables mismatch in {generation_dir}"
        )
    total_rows = 0
    sequences: list[int] = []
    observer_times: list[str] = []
    for table, spec in _TABLES.items():
        entry = tables[table]
        files = entry.get("files")
        if not isinstance(files, list):
            raise ValidationError(
                "archive_manifest_invalid", f"manifest files for {table} malformed"
            )
        seen_rows = 0
        for file_entry in files:
            relative = Path(file_entry["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValidationError(
                    "archive_manifest_invalid", f"unsafe path {relative} in manifest"
                )
            path = generation_dir / relative
            if not path.is_file():
                raise ValidationError(
                    "archive_partition_missing",
                    f"manifest-listed partition {relative} is absent",
                )
            payload = path.read_bytes()
            if len(payload) != file_entry["bytes"] or (
                sha256_digest(payload) != file_entry["sha256"]
            ):
                raise ValidationError(
                    "archive_hash_mismatch",
                    f"partition {relative} disagrees with the manifest",
                )
            frame = pq.read_table(path)
            if tuple(frame.column_names) != expected_columns(table):
                raise ValidationError(
                    "archive_schema_rejected",
                    f"partition {relative} has an unexpected schema",
                )
            if frame.num_rows != file_entry["rows"]:
                raise ValidationError(
                    "archive_count_mismatch",
                    f"partition {relative} row count disagrees with the manifest",
                )
            seen_rows += frame.num_rows
            if table in _OCCURRENCE_TABLES and frame.num_rows:
                time_column = str(spec["time_column"])
                observer_times.extend(
                    str(v) for v in frame.column(time_column).to_pylist()
                )
                sequences.extend(
                    int(v) for v in frame.column("observer_sequence").to_pylist()
                )
        if seen_rows != entry.get("rowCount"):
            raise ValidationError(
                "archive_count_mismatch",
                f"table {table} row count disagrees with the manifest",
            )
        total_rows += seen_rows
    if not sequences or total_rows != sum(int(tables[t]["rowCount"]) for t in _TABLES):
        raise ValidationError(
            "archive_count_mismatch", f"manifest totals mismatch in {generation_dir}"
        )
    expected = {
        "minObserverSequence": min(sequences),
        "maxObserverSequence": max(sequences),
        "minReceivedAt": min(observer_times),
        "maxReceivedAt": max(observer_times),
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValidationError(
                "archive_range_mismatch",
                f"manifest {key} disagrees with the partition bytes",
            )
    return manifest


def export_generation(
    db_path: str | Path,
    artifact_root: str | Path,
    *,
    high_waters: dict[str, str] | None = None,
    token: str | None = None,
    now: str | None = None,
    fail_before_rename: bool = False,
) -> ExportResult:
    """Stage, validate, and durably seal one export generation.

    Sealing never moves the accepted last-good pointer.  Any failure before
    the rename leaves prior sealed generations and SQLite source detail
    untouched; the abandoned staging directory is recovered by
    ``lifecycle.recover``.
    """

    root = ArtifactRoot(artifact_root)
    root.ensure()
    with connect_readonly(db_path) as connection:
        plan = plan_prefix(connection, high_waters)
        occurrences = {
            table: _load_occurrences(connection, table, plan)
            for table in _OCCURRENCE_TABLES
        }
        event_variants = _load_event_variants(connection, plan)
        subject_variants = _load_subject_variants(connection, plan)
        superseded = connection.execute(
            """
            SELECT archive_generation_id FROM archive_generations
            WHERE lifecycle = 'accepted' AND last_good = 1
            """
        ).fetchone()
    generation_id = generation_id_for(
        plan.max_sequence, token=token or secrets.token_hex(6)
    )
    validate_generation_id(generation_id)
    staging = root.staging_generation(generation_id)
    if staging.exists() or root.sealed_generation(generation_id).exists():
        raise ValidationError(
            "archive_generation_conflict", f"generation {generation_id} exists"
        )
    staging.mkdir(parents=True)
    rows_by_table: dict[str, list[sqlite3.Row]] = {
        **occurrences,
        "event_variants": event_variants,
        "subject_variants": subject_variants,
    }
    files = {
        table: _write_table(staging, table, rows_by_table[table]) for table in _TABLES
    }
    manifest = _build_manifest(
        generation_id=generation_id,
        plan=plan,
        created_at=now or utc_now(),
        supersedes=None if superseded is None else str(superseded[0]),
        occurrences=occurrences,
        files=files,
    )
    (staging / MANIFEST_FILE).write_bytes(canonical_json_bytes(manifest))
    validate_generation(staging)
    fsync_tree(staging)
    with connect_maintenance(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        upsert_archive_row(
            connection,
            generation_id=generation_id,
            manifest=manifest,
            lifecycle="staged",
        )
        connection.commit()
    if fail_before_rename:
        raise RuntimeError("injected failure before seal rename")
    sealed_dir = publish_staged(root, generation_id)
    with connect_maintenance(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        upsert_archive_row(
            connection,
            generation_id=generation_id,
            manifest=manifest,
            lifecycle="sealed",
        )
        connection.commit()
    return ExportResult(
        generation_id=generation_id, manifest=manifest, sealed_dir=sealed_dir
    )


def sealed_manifest(root: ArtifactRoot, generation_id: str) -> dict[str, object]:
    """Validate and return the manifest of one sealed generation."""

    sealed = root.sealed_generation(validate_generation_id(generation_id))
    if not sealed.is_dir():
        raise ValidationError(
            "archive_generation_missing", f"no sealed generation {generation_id}"
        )
    manifest = validate_generation(sealed)
    if manifest["archiveGenerationId"] != generation_id:
        raise ValidationError(
            "archive_manifest_invalid", f"sealed directory {generation_id} mismatched"
        )
    return manifest


def control_row_check(
    db_path: str | Path, generation_id: str, manifest: dict[str, object]
) -> dict[str, object]:
    """Return the archive-control row after proving it names this manifest."""

    with connect_readonly(db_path) as connection:
        row = archive_row(connection, generation_id)
    if row is None:
        raise ValidationError(
            "archive_control_missing",
            f"archive-control row for {generation_id} is absent",
        )
    result = dict(row)
    if result["manifest_identity"] != manifest["manifestIdentity"]:
        raise ValidationError(
            "archive_manifest_conflict",
            f"archive-control row for {generation_id} names another manifest",
        )
    return result
