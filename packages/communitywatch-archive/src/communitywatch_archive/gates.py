"""Hot/cold parity gates over sealed history plus the SQLite tail.

Query parity compares exported rows against their pre-export SQLite source.
Rebuild parity feeds manifest-listed sealed occurrences plus the
sequence-disjoint SQLite tail through the unchanged deterministic reducer and
compares against the projection reduced from SQLite alone.  Payload variants
that intentionally occur on both sides are stable-key-deduplicated.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

from community_model import RecordRef, ValidationError
from communitywatch.reducer import (
    EventFact,
    ObservationFact,
    ProjectionResult,
    ReducerConfig,
    reduce_projection,
)

from .export import sealed_manifest
from .layout import ArtifactRoot
from .observerdb import (
    accepted_generations,
    connect_readonly,
    parse_observer_time,
)

_OCCURRENCE_SQL = {
    "receipts": "SELECT * FROM event_receipts WHERE observer_sequence > ? "
    "AND observer_sequence <= ? ORDER BY observer_sequence",
    "quarantine": "SELECT * FROM quarantined_deliveries WHERE observer_sequence > ? "
    "AND observer_sequence <= ? ORDER BY observer_sequence",
    "observations": "SELECT * FROM subject_observations WHERE observer_sequence > ? "
    "AND observer_sequence <= ? ORDER BY observer_sequence",
}

_DAY_COLUMNS = {"received_at_day", "checked_at_day"}


@dataclass(frozen=True, slots=True)
class CustodyFacts:
    """Reducer-ready facts plus quarantine rows from one custody view."""

    events: tuple[EventFact, ...]
    observations: tuple[ObservationFact, ...]
    quarantines: tuple[dict[str, object], ...]


def _rows(connection: sqlite3.Connection, sql: str, parameters: tuple) -> list[dict]:
    return [dict(row) for row in connection.execute(sql, parameters).fetchall()]


def _sqlite_receipts(
    connection: sqlite3.Connection, min_sequence: int, max_sequence: int
) -> list[dict]:
    return _rows(
        connection,
        _OCCURRENCE_SQL["receipts"],
        (min_sequence, max_sequence),
    )


def _sqlite_quarantines(
    connection: sqlite3.Connection, min_sequence: int, max_sequence: int
) -> list[dict]:
    return _rows(
        connection,
        _OCCURRENCE_SQL["quarantine"],
        (min_sequence, max_sequence),
    )


def _sqlite_observations(
    connection: sqlite3.Connection, min_sequence: int, max_sequence: int
) -> list[dict]:
    return _rows(
        connection,
        """
        SELECT o.*, v.requested_uri, v.requested_cid, v.status, v.current_cid,
               v.record_json, v.payload_hash, v.payload_hash_scope
        FROM subject_observations AS o
        JOIN subject_observation_variants AS v
          ON v.subject_variant_key = o.subject_variant_key
        WHERE o.observer_sequence > ? AND o.observer_sequence <= ?
        ORDER BY o.observer_sequence, o.observation_key
        """,
        (min_sequence, max_sequence),
    )


def _sqlite_event_variants(
    connection: sqlite3.Connection, min_sequence: int, max_sequence: int
) -> dict[str, dict]:
    rows = _rows(
        connection,
        """
        SELECT * FROM repo_events WHERE event_variant_key IN (
            SELECT event_variant_key FROM event_receipts
            WHERE observer_sequence > ? AND observer_sequence <= ?
            UNION
            SELECT triggering_event_variant_key FROM subject_observations
            WHERE observer_sequence > ? AND observer_sequence <= ?
              AND triggering_event_variant_key IS NOT NULL
        )
        """,
        (min_sequence, max_sequence, min_sequence, max_sequence),
    )
    # The local surrogate event_id is never portable identity; drop it.
    for row in rows:
        del row["event_id"]
    return {row["event_variant_key"]: row for row in rows}


def _sqlite_subject_variants(
    connection: sqlite3.Connection, min_sequence: int, max_sequence: int
) -> dict[str, dict]:
    rows = _rows(
        connection,
        """
        SELECT * FROM subject_observation_variants WHERE subject_variant_key IN (
            SELECT subject_variant_key FROM subject_observations
            WHERE observer_sequence > ? AND observer_sequence <= ?
        )
        """,
        (min_sequence, max_sequence),
    )
    return {row["subject_variant_key"]: row for row in rows}


def _cold_table(root: ArtifactRoot, generation_id: str, table: str) -> list[dict]:
    manifest = sealed_manifest(root, generation_id)
    rows: list[dict] = []
    for file_entry in manifest["tables"][table]["files"]:
        path = root.sealed_generation(generation_id) / file_entry["path"]
        frame = pq.read_table(path)
        for record in frame.to_pylist():
            rows.append(
                {key: value for key, value in record.items() if key not in _DAY_COLUMNS}
            )
    return rows


def _event_facts(
    variants: Mapping[str, dict],
    receipts: Iterable[dict],
    accepted_delivery_outcomes: frozenset[str],
) -> tuple[EventFact, ...]:
    by_variant: dict[str, list[dict]] = defaultdict(list)
    for receipt in receipts:
        by_variant[receipt["event_variant_key"]].append(receipt)
    facts: list[EventFact] = []
    for key in sorted(variants):
        variant_receipts = sorted(
            by_variant.get(key, []), key=lambda row: row["observer_sequence"]
        )
        if not variant_receipts:
            continue
        variant = variants[key]
        accepted = [
            receipt
            for receipt in variant_receipts
            if receipt["verification_outcome"] in accepted_delivery_outcomes
        ]
        facts.append(
            EventFact(
                semantic_event_key=variant["semantic_event_key"],
                event_variant_key=key,
                repo_did=variant["repo_did"],
                repo_order=variant["repo_order"],
                operation=variant["operation"],
                collection=variant["collection"],
                rkey=variant["rkey"],
                record_uri=variant["record_uri"],
                record_cid=variant["record_cid"],
                record=(
                    None
                    if variant["record_json"] is None
                    else json.loads(variant["record_json"])
                ),
                payload_hash=variant["payload_hash"],
                payload_hash_scope=variant["payload_hash_scope"],
                first_observed_sequence=min(
                    receipt["observer_sequence"] for receipt in variant_receipts
                ),
                first_received_at=min(
                    parse_observer_time(receipt["received_at"])
                    for receipt in variant_receipts
                ),
                first_accepted_at=(
                    None
                    if not accepted
                    else min(
                        parse_observer_time(receipt["received_at"])
                        for receipt in accepted
                    )
                ),
                receipt_count=len(variant_receipts),
                verification_outcomes=tuple(
                    sorted(
                        {
                            receipt["verification_outcome"]
                            for receipt in variant_receipts
                        }
                    )
                ),
            )
        )
    return tuple(facts)


def _observation_facts(
    observations: Iterable[dict],
    accepted_resolution_outcomes: frozenset[str],
) -> tuple[ObservationFact, ...]:
    ordered = sorted(
        observations,
        key=lambda row: (row["observer_sequence"], row["observation_key"]),
    )
    return tuple(
        ObservationFact(
            observation_key=row["observation_key"],
            subject_variant_key=row["subject_variant_key"],
            requested=RecordRef(uri=row["requested_uri"], cid=row["requested_cid"]),
            status=row["status"],
            current_cid=row["current_cid"],
            record=(
                None if row["record_json"] is None else json.loads(row["record_json"])
            ),
            payload_hash=row["payload_hash"],
            payload_hash_scope=row["payload_hash_scope"],
            triggering_event_variant_key=row["triggering_event_variant_key"],
            checked_at=parse_observer_time(row["checked_at"]),
            observer_sequence=row["observer_sequence"],
            trust_mode=row["trust_mode"],
            verification_outcome=row["verification_outcome"],
            resolution_method=row["resolution_method"],
            resolver_version=row["resolver_version"],
            evidence_ref=row["evidence_ref"],
            evidence_hash=row["evidence_hash"],
            accepted=row["verification_outcome"] in accepted_resolution_outcomes,
        )
        for row in ordered
    )


def _assemble(
    *,
    event_variants: Mapping[str, dict],
    receipts: Iterable[dict],
    quarantines: Iterable[dict],
    observations: Iterable[dict],
    accepted_delivery_outcomes: frozenset[str],
    accepted_resolution_outcomes: frozenset[str],
) -> CustodyFacts:
    return CustodyFacts(
        events=_event_facts(event_variants, receipts, accepted_delivery_outcomes),
        observations=_observation_facts(observations, accepted_resolution_outcomes),
        quarantines=tuple(
            sorted(quarantines, key=lambda row: row["observer_sequence"])
        ),
    )


def load_hot_facts(
    db_path: str | Path,
    *,
    accepted_delivery_outcomes: Iterable[str] = ("verified",),
    accepted_resolution_outcomes: Iterable[str] = ("verified",),
) -> CustodyFacts:
    """Facts reduced from the full pre-export/pre-prune SQLite custody."""

    upper = 2**63 - 1
    with connect_readonly(db_path) as connection:
        return _assemble(
            event_variants=_sqlite_event_variants(connection, 0, upper),
            receipts=_sqlite_receipts(connection, 0, upper),
            quarantines=_sqlite_quarantines(connection, 0, upper),
            observations=_sqlite_observations(connection, 0, upper),
            accepted_delivery_outcomes=frozenset(accepted_delivery_outcomes),
            accepted_resolution_outcomes=frozenset(accepted_resolution_outcomes),
        )


def covered_sequence_max(db_path: str | Path, root: ArtifactRoot) -> int:
    """Prove accepted generations tile [1..max] without gaps or overlap."""

    expected = 1
    with connect_readonly(db_path) as connection:
        rows = accepted_generations(connection)
    covered_max = 0
    for row in rows:
        manifest = sealed_manifest(root, row["archive_generation_id"])
        low = int(manifest["minObserverSequence"])
        high = int(manifest["maxObserverSequence"])
        if row["archive_generation_id"] != manifest["archiveGenerationId"]:
            raise ValidationError(
                "archive_manifest_invalid", "archive-control row names another manifest"
            )
        if low != expected:
            raise ValidationError(
                "archive_sequence_gap",
                f"accepted history has a gap or overlap at sequence {expected}",
            )
        expected = high + 1
        covered_max = high
    return covered_max


def _merge_cold_generation(
    root: ArtifactRoot,
    generation_id: str,
    *,
    event_variants: dict[str, dict],
    subject_variants: dict[str, dict],
    seen_sequences: set[int],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Merge one sealed generation, deduplicating variants by stable key."""

    for variant in _cold_table(root, generation_id, "event_variants"):
        existing = event_variants.setdefault(variant["event_variant_key"], variant)
        if existing != variant:
            raise ValidationError(
                "archive_variant_conflict",
                "overlapping event variants disagree under one stable key",
            )
    for variant in _cold_table(root, generation_id, "subject_variants"):
        existing = subject_variants.setdefault(variant["subject_variant_key"], variant)
        if existing != variant:
            raise ValidationError(
                "archive_variant_conflict",
                "overlapping subject variants disagree under one stable key",
            )
    receipts = _cold_table(root, generation_id, "receipts")
    quarantines = _cold_table(root, generation_id, "quarantine")
    observations = []
    for observation in _cold_table(root, generation_id, "observations"):
        variant = subject_variants.get(observation["subject_variant_key"])
        if variant is None:
            raise ValidationError(
                "archive_manifest_invalid",
                "exported observation references an unexported variant",
            )
        observations.append({**variant, **observation})
    for occurrence in (*receipts, *quarantines, *observations):
        sequence = occurrence["observer_sequence"]
        if sequence in seen_sequences:
            raise ValidationError(
                "archive_sequence_overlap",
                f"observer sequence {sequence} occurs in two generations",
            )
        seen_sequences.add(sequence)
    return receipts, quarantines, observations


def load_merged_facts(
    db_path: str | Path,
    artifact_root: str | Path,
    *,
    extra_sealed: Iterable[str] = (),
    accepted_delivery_outcomes: Iterable[str] = ("verified",),
    accepted_resolution_outcomes: Iterable[str] = ("verified",),
) -> CustodyFacts:
    """Facts from the accepted sealed prefix plus the disjoint SQLite tail.

    ``extra_sealed`` names sealed-but-unaccepted generations being evaluated
    for acceptance; each must continue the accepted tiling contiguously.
    Overlapping payload variants are stable-key-deduplicated; occurrence
    sequences must be disjoint by construction of the accepted ranges.
    """

    root = ArtifactRoot(artifact_root)
    upper = 2**63 - 1
    with connect_readonly(db_path) as connection:
        accepted = accepted_generations(connection)
        event_variants: dict[str, dict] = {}
        subject_variants: dict[str, dict] = {}
        receipts: list[dict] = []
        quarantines: list[dict] = []
        observations: list[dict] = []
        seen_sequences: set[int] = set()
        cold_ids = [row["archive_generation_id"] for row in accepted]
        cold_ids.extend(extra_sealed)
        expected_min = 1
        covered_max = 0
        for generation_id in cold_ids:
            manifest = sealed_manifest(root, generation_id)
            low = int(manifest["minObserverSequence"])
            if low != expected_min:
                raise ValidationError(
                    "archive_sequence_gap",
                    f"accepted history has a gap or overlap at sequence {expected_min}",
                )
            expected_min = int(manifest["maxObserverSequence"]) + 1
            covered_max = int(manifest["maxObserverSequence"])
            merged = _merge_cold_generation(
                root,
                generation_id,
                event_variants=event_variants,
                subject_variants=subject_variants,
                seen_sequences=seen_sequences,
            )
            receipts.extend(merged[0])
            quarantines.extend(merged[1])
            observations.extend(merged[2])
        tail_receipts = _sqlite_receipts(connection, covered_max, upper)
        tail_quarantines = _sqlite_quarantines(connection, covered_max, upper)
        tail_observations = _sqlite_observations(connection, covered_max, upper)
        tail_event_variants = _sqlite_event_variants(connection, covered_max, upper)
        tail_subject_variants = _sqlite_subject_variants(connection, covered_max, upper)
    for key, variant in tail_event_variants.items():
        existing = event_variants.setdefault(key, variant)
        if existing != variant:
            raise ValidationError(
                "archive_variant_conflict",
                "hot/cold event variants disagree under one stable key",
            )
    for key, variant in tail_subject_variants.items():
        existing = subject_variants.setdefault(key, variant)
        if existing != variant:
            raise ValidationError(
                "archive_variant_conflict",
                "hot/cold subject variants disagree under one stable key",
            )
    return _assemble(
        event_variants=event_variants,
        receipts=[*receipts, *tail_receipts],
        quarantines=[*quarantines, *tail_quarantines],
        observations=[*observations, *tail_observations],
        accepted_delivery_outcomes=frozenset(accepted_delivery_outcomes),
        accepted_resolution_outcomes=frozenset(accepted_resolution_outcomes),
    )


def reduce_facts(
    facts: CustodyFacts,
    *,
    community_did: str,
    administrator_did: str,
) -> ProjectionResult:
    return reduce_projection(
        list(facts.events),
        list(facts.observations),
        config=ReducerConfig(
            community_did=community_did,
            administrator_did=administrator_did,
        ),
    )


def verify_query_parity(
    db_path: str | Path,
    artifact_root: str | Path,
    generation_id: str,
) -> None:
    """Prove exported rows equal their pre-export SQLite source rows."""

    root = ArtifactRoot(artifact_root)
    manifest = sealed_manifest(root, generation_id)
    low = int(manifest["previousMaxObserverSequence"])
    high = int(manifest["maxObserverSequence"])
    with connect_readonly(db_path) as connection:
        sqlite_rows = {
            "receipts": _sqlite_receipts(connection, low, high),
            "quarantine": _sqlite_quarantines(connection, low, high),
            "observations": _rows(
                connection,
                """
                SELECT * FROM subject_observations
                WHERE observer_sequence > ? AND observer_sequence <= ?
                ORDER BY observer_sequence
                """,
                (low, high),
            ),
        }
        sqlite_event_variants = _sqlite_event_variants(connection, low, high)
        sqlite_subject_variants = _sqlite_subject_variants(connection, low, high)
    for table, rows in sqlite_rows.items():
        expected = {row["observer_sequence"]: row for row in rows}
        exported = {
            row["observer_sequence"]: row
            for row in _cold_table(root, generation_id, table)
        }
        if len(exported) != int(manifest["tables"][table]["rowCount"]):
            raise ValidationError(
                "archive_count_mismatch",
                f"exported {table} count disagrees with the manifest",
            )
        if expected != exported:
            raise ValidationError(
                "archive_parity_failed",
                f"exported {table} rows differ from their SQLite source",
            )
    cold_event_variants = {
        row["event_variant_key"]: row
        for row in _cold_table(root, generation_id, "event_variants")
    }
    cold_subject_variants = {
        row["subject_variant_key"]: row
        for row in _cold_table(root, generation_id, "subject_variants")
    }
    if sqlite_event_variants != cold_event_variants:
        raise ValidationError(
            "archive_parity_failed",
            "exported event variants differ from their SQLite source",
        )
    if sqlite_subject_variants != cold_subject_variants:
        raise ValidationError(
            "archive_parity_failed",
            "exported subject variants differ from their SQLite source",
        )


def verify_rebuild_parity(
    db_path: str | Path,
    artifact_root: str | Path,
    *,
    candidate: str | None = None,
    community_did: str,
    administrator_did: str,
    accepted_delivery_outcomes: Iterable[str] = ("verified",),
    accepted_resolution_outcomes: Iterable[str] = ("verified",),
) -> None:
    """Prove sealed-prefix-plus-tail rebuild equals pre-export reduction.

    ``candidate`` names the sealed-but-unaccepted generation under
    evaluation; it is treated as part of the cold side so the proof covers
    its bytes, not just previously accepted history.
    """

    hot = load_hot_facts(
        db_path,
        accepted_delivery_outcomes=accepted_delivery_outcomes,
        accepted_resolution_outcomes=accepted_resolution_outcomes,
    )
    merged = load_merged_facts(
        db_path,
        artifact_root,
        extra_sealed=() if candidate is None else (candidate,),
        accepted_delivery_outcomes=accepted_delivery_outcomes,
        accepted_resolution_outcomes=accepted_resolution_outcomes,
    )
    if hot.quarantines != merged.quarantines:
        raise ValidationError(
            "archive_parity_failed", "quarantined custody differs hot versus cold"
        )
    hot_projection = reduce_facts(
        hot, community_did=community_did, administrator_did=administrator_did
    )
    merged_projection = reduce_facts(
        merged, community_did=community_did, administrator_did=administrator_did
    )
    if hot_projection != merged_projection:
        raise ValidationError(
            "archive_parity_failed",
            "rebuild from sealed history plus tail differs from pre-export SQLite",
        )
