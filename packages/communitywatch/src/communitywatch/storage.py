"""Transactional SQLite custody and projection for the V0 observer."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from community_model import (
    PayloadHashScope,
    PortError,
    PortUnavailableError,
    RecordRef,
    RepoEvent,
    RepositoryOperation,
    ResolveResult,
    ValidationError,
    VerificationOutcome,
    canonical_json_bytes,
    event_variant_key,
    payload_hash,
    quarantine_audit_key,
    semantic_event_key,
    sha256_digest,
)
from community_model.identifiers import (
    normalize_commit_identity,
    validate_did,
    validate_tid,
)
from community_model.immutable import deep_thaw
from community_model.values import IncomingDelivery

from .reducer import (
    EventFact,
    ObservationFact,
    ProjectionResult,
    ReducerConfig,
    reduce_projection,
)

SCHEMA_VERSION = 3
PROJECTION_VERSION = "v0"
DEFAULT_BUSY_TIMEOUT_MS = 5_000


_SCHEMA = """
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

CREATE TABLE ingest_sources (
    source TEXT PRIMARY KEY,
    committed_cursor TEXT,
    last_success_at TEXT,
    last_error TEXT
) STRICT;

CREATE TABLE repo_events (
    event_id INTEGER PRIMARY KEY,
    event_variant_key TEXT NOT NULL UNIQUE,
    semantic_event_key TEXT NOT NULL,
    event_schema_version INTEGER NOT NULL CHECK (event_schema_version = 1),
    commit_identity TEXT NOT NULL,
    repo_order TEXT NOT NULL,
    repo_did TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('create', 'update', 'delete')),
    collection TEXT NOT NULL,
    rkey TEXT NOT NULL,
    record_uri TEXT NOT NULL,
    record_cid TEXT,
    record_json TEXT,
    record_bytes BLOB,
    commit_rev TEXT NOT NULL,
    commit_cid TEXT,
    payload_hash TEXT NOT NULL,
    payload_hash_scope TEXT NOT NULL CHECK (
        payload_hash_scope IN (
            'dag_cbor', 'observer_json_v0', 'delete_envelope_v0'
        )
    )
) STRICT;
CREATE INDEX repo_events_semantic_idx
    ON repo_events(semantic_event_key, event_variant_key);
CREATE INDEX repo_events_record_idx
    ON repo_events(record_uri, repo_order);

CREATE TABLE event_receipts (
    source TEXT NOT NULL,
    cursor TEXT NOT NULL,
    event_variant_key TEXT NOT NULL REFERENCES repo_events(event_variant_key),
    raw_envelope_hash TEXT NOT NULL,
    source_event_time TEXT,
    received_at TEXT NOT NULL,
    observer_sequence INTEGER NOT NULL UNIQUE CHECK (observer_sequence > 0),
    trust_mode TEXT NOT NULL,
    verification_outcome TEXT NOT NULL,
    verification_method TEXT NOT NULL,
    verifier_version TEXT NOT NULL,
    evidence_ref TEXT,
    evidence_hash TEXT,
    PRIMARY KEY (source, cursor)
) STRICT;
CREATE INDEX event_receipts_variant_idx
    ON event_receipts(event_variant_key, observer_sequence);
CREATE INDEX event_receipts_received_idx
    ON event_receipts(received_at, observer_sequence);

CREATE TABLE quarantined_deliveries (
    quarantine_key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    cursor TEXT NOT NULL,
    raw_envelope BLOB NOT NULL,
    raw_envelope_hash TEXT NOT NULL,
    source_event_time TEXT,
    received_at TEXT NOT NULL,
    observer_sequence INTEGER NOT NULL UNIQUE CHECK (observer_sequence > 0),
    trust_mode TEXT NOT NULL,
    verification_outcome TEXT NOT NULL,
    verification_method TEXT NOT NULL,
    verifier_version TEXT NOT NULL,
    evidence_ref TEXT,
    evidence_hash TEXT,
    reason_code TEXT NOT NULL,
    UNIQUE (source, cursor)
) STRICT;
CREATE INDEX quarantined_received_idx
    ON quarantined_deliveries(received_at, observer_sequence);

CREATE TABLE subject_observation_variants (
    subject_variant_key TEXT PRIMARY KEY,
    requested_uri TEXT NOT NULL,
    requested_cid TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('exact', 'mismatch', 'missing', 'error')),
    current_cid TEXT,
    record_json TEXT,
    payload_hash TEXT NOT NULL,
    payload_hash_scope TEXT NOT NULL
) STRICT;

CREATE TABLE subject_observations (
    observation_key TEXT PRIMARY KEY,
    subject_variant_key TEXT NOT NULL
        REFERENCES subject_observation_variants(subject_variant_key),
    triggering_event_variant_key TEXT
        REFERENCES repo_events(event_variant_key),
    checked_at TEXT NOT NULL,
    observer_sequence INTEGER NOT NULL UNIQUE CHECK (observer_sequence > 0),
    trust_mode TEXT NOT NULL,
    verification_outcome TEXT NOT NULL,
    resolution_method TEXT NOT NULL,
    resolver_version TEXT NOT NULL,
    evidence_ref TEXT,
    evidence_hash TEXT
) STRICT;
CREATE INDEX subject_observations_ref_idx
    ON subject_observations(subject_variant_key, observer_sequence);

CREATE TABLE projection_builds (
    generation_id TEXT PRIMARY KEY,
    reducer_version TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('building', 'complete', 'failed')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    source_high_waters_json TEXT NOT NULL,
    immutable_row_count INTEGER NOT NULL DEFAULT 0,
    derived_row_count INTEGER NOT NULL DEFAULT 0,
    failure_reason TEXT
) STRICT;

CREATE TABLE records_current (
    generation_id TEXT NOT NULL REFERENCES projection_builds(generation_id),
    record_uri TEXT NOT NULL,
    event_variant_key TEXT NOT NULL,
    repo_order TEXT NOT NULL,
    record_cid TEXT,
    deleted INTEGER NOT NULL CHECK (deleted IN (0, 1)),
    PRIMARY KEY (generation_id, record_uri)
) STRICT;

CREATE TABLE community_profiles (
    generation_id TEXT NOT NULL REFERENCES projection_builds(generation_id),
    community_did TEXT NOT NULL,
    record_uri TEXT NOT NULL,
    record_cid TEXT NOT NULL,
    display_name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (generation_id, community_did)
) STRICT;

CREATE TABLE ledger_records (
    generation_id TEXT NOT NULL REFERENCES projection_builds(generation_id),
    event_variant_key TEXT NOT NULL,
    record_uri TEXT NOT NULL,
    record_cid TEXT,
    kind TEXT NOT NULL,
    repo_did TEXT NOT NULL,
    repo_order TEXT NOT NULL,
    operation TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    normalized_record_json TEXT,
    first_observed_sequence INTEGER NOT NULL,
    PRIMARY KEY (generation_id, event_variant_key)
) STRICT;

CREATE TABLE subject_current (
    generation_id TEXT NOT NULL REFERENCES projection_builds(generation_id),
    subject_uri TEXT NOT NULL,
    subject_cid TEXT NOT NULL,
    observation_key TEXT NOT NULL,
    status TEXT NOT NULL,
    current_cid TEXT,
    observer_sequence INTEGER NOT NULL,
    accepted INTEGER NOT NULL CHECK (accepted IN (0, 1)),
    PRIMARY KEY (generation_id, subject_uri, subject_cid)
) STRICT;

CREATE TABLE admission_lifecycles (
    generation_id TEXT NOT NULL REFERENCES projection_builds(generation_id),
    admission_uri TEXT NOT NULL,
    admission_cid TEXT NOT NULL,
    admission_event_variant_key TEXT NOT NULL,
    submission_uri TEXT NOT NULL,
    submission_cid TEXT NOT NULL,
    subject_uri TEXT NOT NULL,
    subject_cid TEXT NOT NULL,
    logical_lifecycle_key TEXT NOT NULL,
    admitted_at TEXT NOT NULL,
    admission_first_observed_sequence INTEGER NOT NULL,
    start_observation_key TEXT,
    start_sequence INTEGER,
    terminal_observation_key TEXT,
    terminal_sequence INTEGER,
    removal_uri TEXT,
    removal_cid TEXT,
    status TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    eligible INTEGER NOT NULL CHECK (eligible IN (0, 1)),
    PRIMARY KEY (generation_id, admission_uri, admission_cid)
) STRICT;

CREATE TABLE community_entries (
    generation_id TEXT NOT NULL REFERENCES projection_builds(generation_id),
    community_did TEXT NOT NULL,
    subject_uri TEXT NOT NULL,
    subject_cid TEXT NOT NULL,
    submission_uri TEXT NOT NULL,
    submission_cid TEXT NOT NULL,
    admission_uri TEXT NOT NULL,
    admission_cid TEXT NOT NULL,
    admitted_at TEXT NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (generation_id, community_did, subject_uri, subject_cid)
) STRICT;
CREATE INDEX community_entries_visible_idx
    ON community_entries(generation_id, community_did, status, admitted_at);

-- PCV0 discussion projection. These rows are derived and replaceable; the
-- signed records and exact subject observations remain the evidence source.
CREATE TABLE discussion_roots (
    generation_id TEXT NOT NULL REFERENCES projection_builds(generation_id),
    root_admission_uri TEXT NOT NULL,
    root_admission_cid TEXT NOT NULL,
    root_subject_uri TEXT NOT NULL,
    root_subject_cid TEXT NOT NULL,
    author_did TEXT NOT NULL,
    admitted_at TEXT NOT NULL,
    status TEXT NOT NULL,
    closed INTEGER NOT NULL CHECK (closed IN (0, 1)),
    snapshot_observation_key TEXT,
    last_activity_sequence INTEGER NOT NULL,
    PRIMARY KEY (generation_id, root_admission_uri, root_admission_cid)
) STRICT;
CREATE INDEX discussion_roots_discovery_idx
    ON discussion_roots(generation_id, closed, admitted_at);

CREATE TABLE discussion_replies (
    generation_id TEXT NOT NULL REFERENCES projection_builds(generation_id),
    logical_moderation_key TEXT NOT NULL,
    root_admission_uri TEXT NOT NULL,
    root_admission_cid TEXT NOT NULL,
    reply_uri TEXT NOT NULL,
    reply_cid TEXT NOT NULL,
    author_did TEXT NOT NULL,
    parent_uri TEXT,
    parent_cid TEXT,
    submission_uri TEXT NOT NULL,
    submission_cid TEXT NOT NULL,
    admission_uri TEXT NOT NULL,
    admission_cid TEXT NOT NULL,
    admitted_at TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    controlling_action_uri TEXT,
    controlling_action_cid TEXT,
    snapshot_observation_key TEXT,
    activity_sequence INTEGER NOT NULL,
    PRIMARY KEY (generation_id, admission_uri, admission_cid)
) STRICT;
CREATE INDEX discussion_replies_thread_idx
    ON discussion_replies(generation_id, root_admission_uri,
                          root_admission_cid, activity_sequence);
CREATE INDEX discussion_replies_logical_idx
    ON discussion_replies(generation_id, logical_moderation_key,
                          activity_sequence);

CREATE TABLE discussion_activity (
    generation_id TEXT NOT NULL REFERENCES projection_builds(generation_id),
    activity_key TEXT NOT NULL,
    root_admission_uri TEXT NOT NULL,
    root_admission_cid TEXT NOT NULL,
    actor_did TEXT,
    activity_type TEXT NOT NULL CHECK (
        activity_type IN ('root_admitted', 'reply_admitted',
                          'reply_removed', 'reply_restored', 'root_closed')
    ),
    target_uri TEXT NOT NULL,
    target_cid TEXT,
    occurred_at TEXT NOT NULL,
    observer_sequence INTEGER NOT NULL,
    PRIMARY KEY (generation_id, activity_key)
) STRICT;
CREATE INDEX discussion_activity_thread_idx
    ON discussion_activity(generation_id, root_admission_uri,
                           root_admission_cid, observer_sequence);
CREATE INDEX discussion_activity_actor_idx
    ON discussion_activity(generation_id, actor_did, observer_sequence);

CREATE TABLE projection_findings (
    generation_id TEXT NOT NULL REFERENCES projection_builds(generation_id),
    finding_key TEXT NOT NULL,
    event_variant_key TEXT,
    subject_uri TEXT,
    subject_cid TEXT,
    reason_code TEXT NOT NULL,
    PRIMARY KEY (generation_id, finding_key)
) STRICT;

CREATE TABLE audit_index (
    generation_id TEXT NOT NULL REFERENCES projection_builds(generation_id),
    audit_row_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    semantic_event_key TEXT,
    event_variant_key TEXT,
    record_uri TEXT,
    record_cid TEXT,
    subject_uri TEXT,
    subject_cid TEXT,
    actor TEXT,
    reason TEXT,
    signed_created_at TEXT,
    payload_hash TEXT NOT NULL,
    payload_hash_scope TEXT NOT NULL,
    first_received_at TEXT NOT NULL,
    observer_sequence INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    receipt_count INTEGER NOT NULL,
    verification_outcomes_json TEXT NOT NULL,
    PRIMARY KEY (generation_id, audit_row_key)
) STRICT;
CREATE INDEX audit_index_order_idx
    ON audit_index(generation_id, first_received_at, audit_row_key);

CREATE TABLE archive_generations (
    archive_generation_id TEXT PRIMARY KEY,
    manifest_identity TEXT NOT NULL UNIQUE,
    lifecycle TEXT NOT NULL CHECK (
        lifecycle IN ('staged', 'sealed', 'accepted', 'superseded', 'quarantined')
    ),
    partition_version INTEGER NOT NULL,
    schema_version INTEGER NOT NULL,
    row_counts_json TEXT NOT NULL,
    byte_hashes_json TEXT NOT NULL,
    min_received_at TEXT,
    max_received_at TEXT,
    min_observer_sequence INTEGER,
    max_observer_sequence INTEGER,
    source_high_waters_json TEXT NOT NULL,
    exclusions_json TEXT NOT NULL,
    cannot_testify_json TEXT NOT NULL,
    last_good INTEGER NOT NULL DEFAULT 0 CHECK (last_good IN (0, 1)),
    verified_prune_sequence INTEGER
) STRICT;
"""


_PCV0_SCHEMA = _SCHEMA[
    _SCHEMA.index("CREATE TABLE discussion_roots") : _SCHEMA.index(
        "CREATE TABLE projection_findings"
    )
]

_DERIVED_TABLES = (
    "audit_index",
    "records_current",
    "community_profiles",
    "ledger_records",
    "subject_current",
    "admission_lifecycles",
    "community_entries",
    "discussion_roots",
    "discussion_replies",
    "discussion_activity",
    "projection_findings",
)


class ReadOnlyStoreError(PortError):
    """A write was attempted through a read-only observer store."""


@dataclass(frozen=True, slots=True)
class IngestResult:
    kind: str
    key: str
    observer_sequence: int
    duplicate: bool


def _utc_wire(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _json(value: object) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _raw_bytes(raw_envelope: bytes | Mapping[str, object]) -> bytes:
    if isinstance(raw_envelope, bytes):
        return raw_envelope
    return canonical_json_bytes(raw_envelope)


def _thawed_mapping(value: Mapping[str, object]) -> dict[str, object]:
    thawed = deep_thaw(value)
    assert isinstance(thawed, dict)
    return thawed


class ObserverStore:
    """One-community observer custody and deterministic V0 projection."""

    def __init__(
        self,
        path: str | Path,
        *,
        community_did: str,
        administrator_did: str | None = None,
        accepted_delivery_outcomes: Iterable[str] = (
            VerificationOutcome.VERIFIED.value,
        ),
        accepted_resolution_outcomes: Iterable[str] = (
            VerificationOutcome.VERIFIED.value,
        ),
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
        read_only: bool = False,
    ) -> None:
        self.path = Path(path)
        self.community_did = validate_did(community_did)
        if administrator_did is None and not read_only:
            raise ValueError("administrator_did is required for a writable store")
        self.administrator_did = (
            None if administrator_did is None else validate_did(administrator_did)
        )
        self.accepted_delivery_outcomes = frozenset(
            VerificationOutcome(outcome).value for outcome in accepted_delivery_outcomes
        )
        self.accepted_resolution_outcomes = frozenset(
            VerificationOutcome(outcome).value
            for outcome in accepted_resolution_outcomes
        )
        if (
            isinstance(busy_timeout_ms, bool)
            or not isinstance(busy_timeout_ms, int)
            or not 1 <= busy_timeout_ms <= 60_000
        ):
            raise ValueError("busy_timeout_ms must be between 1 and 60000")
        self.busy_timeout_ms = busy_timeout_ms
        self.read_only = read_only
        self._initialize()

    def _require_writable(self) -> None:
        if self.read_only:
            raise ReadOnlyStoreError("this observer store was opened read-only")

    def _connect(self) -> sqlite3.Connection:
        self._require_writable()
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        return connection

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection]:
        uri = f"file:{self.path.resolve()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA query_only = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        # One deferred read transaction per logical read: without it every
        # SELECT would auto-commit its own snapshot, and a concurrent ingest
        # commit could interleave mixed-generation rows (or a stale/fresh
        # high-water pair) into one logical query.
        connection.execute("BEGIN")
        try:
            yield connection
        finally:
            connection.rollback()
            connection.close()

    def _initialize(self) -> None:
        if self.read_only:
            self._check_schema_read_only()
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise ValidationError(
                    "schema_incompatible",
                    "observer database schema is newer than this process",
                )
            if version == 0:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(_SCHEMA)
                now = _utc_wire(datetime.now(UTC))
                assert now is not None
                connection.executemany(
                    "INSERT INTO meta(key, value) VALUES (?, ?)",
                    (
                        ("schema_version", str(SCHEMA_VERSION)),
                        ("projection_version", PROJECTION_VERSION),
                        ("active_projection_generation", "g1"),
                        ("observer_sequence", "0"),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO projection_builds(
                        generation_id, reducer_version, schema_version, status,
                        started_at, completed_at, source_high_waters_json
                    ) VALUES ('g1', ?, ?, 'complete', ?, ?, '{}')
                    """,
                    (PROJECTION_VERSION, SCHEMA_VERSION, now, now),
                )
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            elif version == 1:
                stored = connection.execute(
                    "SELECT value FROM meta WHERE key = 'schema_version'"
                ).fetchone()
                if stored is None or int(stored[0]) != 1:
                    raise ValidationError(
                        "schema_incompatible",
                        "observer schema metadata disagrees with SQLite version",
                    )
                connection.executescript(
                    _PCV0_SCHEMA.replace(
                        "CREATE TABLE ", "CREATE TABLE IF NOT EXISTS "
                    ).replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ")
                )
                connection.execute(
                    "UPDATE meta SET value = ? WHERE key = 'schema_version'",
                    (str(SCHEMA_VERSION),),
                )
                connection.execute(
                    "UPDATE projection_builds SET schema_version = ?",
                    (SCHEMA_VERSION,),
                )
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                self._materialize_projection(
                    connection, self._active_generation(connection)
                )
            elif version == 2:
                stored = connection.execute(
                    "SELECT value FROM meta WHERE key = 'schema_version'"
                ).fetchone()
                if stored is None or int(stored[0]) != 2:
                    raise ValidationError(
                        "schema_incompatible",
                        "observer schema metadata disagrees with SQLite version",
                    )
                connection.execute(
                    "ALTER TABLE discussion_replies ADD COLUMN controlling_action_uri TEXT"
                )
                connection.execute(
                    "ALTER TABLE discussion_replies ADD COLUMN controlling_action_cid TEXT"
                )
                connection.execute(
                    "UPDATE meta SET value = ? WHERE key = 'schema_version'",
                    (str(SCHEMA_VERSION),),
                )
                connection.execute(
                    "UPDATE projection_builds SET schema_version = ?",
                    (SCHEMA_VERSION,),
                )
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                self._materialize_projection(
                    connection, self._active_generation(connection)
                )
            else:
                stored = connection.execute(
                    "SELECT value FROM meta WHERE key = 'schema_version'"
                ).fetchone()
                if stored is None or int(stored[0]) != SCHEMA_VERSION:
                    raise ValidationError(
                        "schema_incompatible",
                        "observer schema metadata disagrees with SQLite version",
                    )

            connection.execute(
                "CREATE INDEX IF NOT EXISTS p0_candidates_did_idx ON ledger_records(generation_id,kind,repo_did,first_observed_sequence,record_uri)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS p0_pending_candidates_idx ON ledger_records(generation_id,repo_did,first_observed_sequence,record_uri) WHERE kind = 'submission' AND outcome = 'valid' AND operation != 'delete'"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS p0_admitted_subject_idx ON admission_lifecycles(generation_id,subject_uri,subject_cid)"
            )

    def _check_schema_read_only(self) -> None:
        """Validate an existing database without ever opening a write handle."""

        try:
            with self.read_connection() as connection:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if version != SCHEMA_VERSION:
                    raise ValidationError(
                        "schema_incompatible",
                        "observer database schema does not match this process",
                    )
                stored = connection.execute(
                    "SELECT value FROM meta WHERE key = 'schema_version'"
                ).fetchone()
                if stored is None or int(stored[0]) != SCHEMA_VERSION:
                    raise ValidationError(
                        "schema_incompatible",
                        "observer schema metadata disagrees with SQLite version",
                    )
        except sqlite3.Error as exc:
            raise PortUnavailableError("observer database is unavailable") from exc

    def _next_sequence(self, connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT value FROM meta WHERE key = 'observer_sequence'"
        ).fetchone()
        assert row is not None
        sequence = int(row[0]) + 1
        connection.execute(
            "UPDATE meta SET value = ? WHERE key = 'observer_sequence'",
            (str(sequence),),
        )
        return sequence

    def _delivery_collision(
        self, connection: sqlite3.Connection, delivery: IncomingDelivery
    ) -> sqlite3.Row | None:
        event = connection.execute(
            """
            SELECT 'event' AS kind, event_variant_key AS key, observer_sequence,
                   raw_envelope_hash
            FROM event_receipts WHERE source = ? AND cursor = ?
            """,
            (delivery.source, delivery.cursor),
        ).fetchone()
        quarantine = connection.execute(
            """
            SELECT 'quarantine' AS kind, quarantine_key AS key, observer_sequence,
                   raw_envelope_hash
            FROM quarantined_deliveries WHERE source = ? AND cursor = ?
            """,
            (delivery.source, delivery.cursor),
        ).fetchone()
        return event or quarantine

    def ingest(
        self,
        delivery: IncomingDelivery,
        *,
        fail_before_commit: bool = False,
    ) -> IngestResult:
        """Atomically retain one delivery, project it, and checkpoint its cursor."""

        return self.ingest_batch((delivery,), fail_before_commit=fail_before_commit)[0]

    def ingest_batch(
        self,
        deliveries: Sequence[IncomingDelivery],
        *,
        fail_before_commit: bool = False,
    ) -> tuple[IngestResult, ...]:
        """Commit one same-source batch and its final cursor as one transaction."""

        self._require_writable()
        if not deliveries:
            return ()
        sources = {delivery.source for delivery in deliveries}
        if len(sources) != 1:
            raise ValidationError(
                "schema_invalid", "one ingest batch may contain only one source"
            )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            results = tuple(
                self._ingest_delivery(connection, delivery) for delivery in deliveries
            )
            final = deliveries[-1]
            connection.execute(
                """
                INSERT INTO ingest_sources(source, committed_cursor, last_success_at)
                VALUES (?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    committed_cursor = excluded.committed_cursor,
                    last_success_at = excluded.last_success_at,
                    last_error = NULL
                """,
                (final.source, final.cursor, _utc_wire(final.received_at)),
            )
            active = self._active_generation(connection)
            self._materialize_projection(connection, active)
            if fail_before_commit:
                raise RuntimeError("injected failure before commit")
            connection.commit()
            return results

    def _ingest_delivery(
        self,
        connection: sqlite3.Connection,
        delivery: IncomingDelivery,
    ) -> IngestResult:
        raw = _raw_bytes(delivery.raw_envelope)
        raw_hash = sha256_digest(raw)
        existing = self._delivery_collision(connection, delivery)
        if existing is not None:
            if existing["raw_envelope_hash"] != raw_hash:
                raise ValidationError(
                    "semantic_event_conflict",
                    "a source cursor was reused for different envelope bytes",
                )
            return IngestResult(
                kind=existing["kind"],
                key=existing["key"],
                observer_sequence=existing["observer_sequence"],
                duplicate=True,
            )

        sequence = self._next_sequence(connection)
        try:
            event = self._normalize_delivery(delivery)
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            reason = (
                exc.reason_code
                if isinstance(exc, ValidationError)
                else "schema_invalid"
            )
            key = quarantine_audit_key(
                source=delivery.source,
                cursor=delivery.cursor,
                raw_envelope_hash=raw_hash,
            )
            connection.execute(
                """
                INSERT INTO quarantined_deliveries(
                    quarantine_key, source, cursor, raw_envelope,
                    raw_envelope_hash, source_event_time, received_at,
                    observer_sequence, trust_mode, verification_outcome,
                    verification_method, verifier_version, evidence_ref,
                    evidence_hash, reason_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    delivery.source,
                    delivery.cursor,
                    raw,
                    raw_hash,
                    _utc_wire(delivery.source_event_time),
                    _utc_wire(delivery.received_at),
                    sequence,
                    delivery.trust_mode.value,
                    delivery.verification_outcome.value,
                    delivery.verification_method,
                    delivery.verifier_version,
                    delivery.evidence_ref,
                    delivery.evidence_hash,
                    reason,
                ),
            )
            kind = "quarantine"
        else:
            key = event.event_variant_key
            connection.execute(
                """
                INSERT INTO repo_events(
                    event_variant_key, semantic_event_key,
                    event_schema_version, commit_identity, repo_order,
                    repo_did, operation, collection, rkey, record_uri,
                    record_cid, record_json, record_bytes, commit_rev,
                    commit_cid, payload_hash, payload_hash_scope
                ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_variant_key) DO NOTHING
                """,
                (
                    event.event_variant_key,
                    event.semantic_event_key,
                    event.commit_identity,
                    event.repo_order,
                    event.repo_did,
                    event.operation.value,
                    event.collection,
                    event.rkey,
                    event.record_uri,
                    event.record_cid,
                    None
                    if event.record is None
                    else _json(_thawed_mapping(event.record)),
                    event.record_bytes,
                    event.commit_rev,
                    event.commit_cid,
                    event.payload_hash,
                    event.payload_hash_scope.value,
                ),
            )
            connection.execute(
                """
                INSERT INTO event_receipts(
                    source, cursor, event_variant_key, raw_envelope_hash,
                    source_event_time, received_at, observer_sequence,
                    trust_mode, verification_outcome, verification_method,
                    verifier_version, evidence_ref, evidence_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    delivery.source,
                    delivery.cursor,
                    key,
                    raw_hash,
                    _utc_wire(delivery.source_event_time),
                    _utc_wire(delivery.received_at),
                    sequence,
                    delivery.trust_mode.value,
                    delivery.verification_outcome.value,
                    delivery.verification_method,
                    delivery.verifier_version,
                    delivery.evidence_ref,
                    delivery.evidence_hash,
                ),
            )
            kind = "event"
        return IngestResult(
            kind=kind,
            key=key,
            observer_sequence=sequence,
            duplicate=False,
        )

    def ingest_many(
        self, deliveries: Sequence[IncomingDelivery]
    ) -> tuple[IngestResult, ...]:
        return self.ingest_batch(deliveries)

    def source_cursor(self, source: str) -> str | None:
        """Return the durably committed cursor for one ingest source."""

        with self.read_connection() as connection:
            row = connection.execute(
                "SELECT committed_cursor FROM ingest_sources WHERE source = ?",
                (source,),
            ).fetchone()
        return None if row is None else str(row["committed_cursor"])

    def record_source_error(self, source: str, error: str) -> None:
        """Note one source failure without touching its committed cursor."""

        self._require_writable()
        if not source or not error or "\x00" in source or "\x00" in error:
            raise ValidationError(
                "schema_invalid", "source and error must be nonempty NUL-free text"
            )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # Only existing source rows carry a durable cursor; a source that
            # has never committed one must not appear in high-water
            # comparisons with a null cursor.
            connection.execute(
                "UPDATE ingest_sources SET last_error = ? WHERE source = ?",
                (error[:500], source),
            )
            connection.commit()

    def _normalize_delivery(self, delivery: IncomingDelivery) -> RepoEvent:
        if isinstance(delivery.raw_envelope, bytes):
            decoded = json.loads(delivery.raw_envelope)
        else:
            decoded = _thawed_mapping(delivery.raw_envelope)
        if not isinstance(decoded, Mapping):
            raise ValidationError("schema_invalid", "event envelope must be an object")

        required = {"repo", "rev", "operation", "collection", "rkey"}
        allowed = required | {
            "cid",
            "record",
            "recordBytesHex",
            "commitCid",
        }
        if set(decoded) - allowed or required - set(decoded):
            raise ValidationError(
                "schema_invalid", "event envelope fields do not match V0"
            )
        repo_did = decoded["repo"]
        revision = validate_tid(decoded["rev"])
        operation = RepositoryOperation(decoded["operation"])
        collection = decoded["collection"]
        rkey = decoded["rkey"]
        if not all(isinstance(value, str) for value in (repo_did, collection, rkey)):
            raise ValidationError(
                "schema_invalid", "event identity fields must be text"
            )
        commit_identity = normalize_commit_identity(revision)
        semantic_key = semantic_event_key(
            repo_did=repo_did,
            commit_identity=commit_identity,
            collection=collection,
            rkey=rkey,
            operation=operation,
        )
        record_uri = f"at://{repo_did}/{collection}/{rkey}"
        record_cid = decoded.get("cid")
        record = decoded.get("record")
        record_bytes_hex = decoded.get("recordBytesHex")
        record_bytes = None
        if record_bytes_hex is not None:
            if not isinstance(record_bytes_hex, str):
                raise ValidationError(
                    "payload_evidence_invalid", "recordBytesHex must be text"
                )
            try:
                record_bytes = bytes.fromhex(record_bytes_hex)
            except ValueError as exc:
                raise ValidationError(
                    "payload_evidence_invalid", "recordBytesHex is not hexadecimal"
                ) from exc
        if operation is RepositoryOperation.DELETE:
            scope = PayloadHashScope.DELETE_ENVELOPE_V0
            evidence: object = {
                "collection": collection,
                "commitIdentity": commit_identity,
                "operation": operation.value,
                "repoDid": repo_did,
                "rkey": rkey,
            }
        elif record_bytes is not None:
            scope = PayloadHashScope.DAG_CBOR
            evidence = record_bytes
        else:
            scope = PayloadHashScope.OBSERVER_JSON_V0
            evidence = record
        digest = payload_hash(scope, evidence)
        variant_key = event_variant_key(
            semantic_event_key=semantic_key,
            record_cid=record_cid,
            payload_hash_scope=scope,
            payload_hash=digest,
        )
        return RepoEvent(
            semantic_event_key=semantic_key,
            event_variant_key=variant_key,
            commit_identity=commit_identity,
            repo_order=revision,
            repo_did=repo_did,
            operation=operation,
            collection=collection,
            rkey=rkey,
            record_uri=record_uri,
            record_cid=record_cid,
            commit_rev=revision,
            commit_cid=decoded.get("commitCid"),
            record=record,
            record_bytes=record_bytes,
            payload_hash=digest,
            payload_hash_scope=scope,
        )

    def record_subject_observation(
        self,
        result: ResolveResult,
        *,
        triggering_event_variant_key: str | None = None,
        fail_before_commit: bool = False,
    ) -> str:
        self._require_writable()
        record = None if result.record is None else _thawed_mapping(result.record)
        variant_material = {
            "requested": result.requested.as_dict(),
            "status": result.status.value,
            "currentCid": result.current_cid,
            "record": record,
        }
        digest = payload_hash(PayloadHashScope.OBSERVER_JSON_V0, variant_material)
        variant_key = sha256_digest(
            b"v0\x00subject-variant\x00" + canonical_json_bytes(variant_material)
        )
        checked_at = _utc_wire(result.checked_at)
        assert checked_at is not None
        observation_material = {
            "subjectVariantKey": variant_key,
            "triggeringEventVariantKey": triggering_event_variant_key,
            "checkedAt": checked_at,
            "trustMode": result.trust_mode.value,
            "verificationOutcome": result.verification_outcome.value,
            "resolutionMethod": result.resolution_method,
            "resolverVersion": result.resolver_version,
            "evidenceRef": result.evidence_ref,
            "evidenceHash": result.evidence_hash,
        }
        observation_key = sha256_digest(
            b"v0\x00subject-observation\x00"
            + canonical_json_bytes(observation_material)
        )

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT observation_key FROM subject_observations
                WHERE observation_key = ?
                """,
                (observation_key,),
            ).fetchone()
            if existing is not None:
                return observation_key
            if triggering_event_variant_key is not None:
                trigger = connection.execute(
                    "SELECT 1 FROM repo_events WHERE event_variant_key = ?",
                    (triggering_event_variant_key,),
                ).fetchone()
                if trigger is None:
                    raise ValidationError(
                        "reference_missing",
                        "triggering event variant is not in observer custody",
                    )
            connection.execute(
                """
                INSERT INTO subject_observation_variants(
                    subject_variant_key, requested_uri, requested_cid, status,
                    current_cid, record_json, payload_hash, payload_hash_scope
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(subject_variant_key) DO NOTHING
                """,
                (
                    variant_key,
                    result.requested.uri,
                    result.requested.cid,
                    result.status.value,
                    result.current_cid,
                    None if record is None else _json(record),
                    digest,
                    PayloadHashScope.OBSERVER_JSON_V0.value,
                ),
            )
            sequence = self._next_sequence(connection)
            connection.execute(
                """
                INSERT INTO subject_observations(
                    observation_key, subject_variant_key,
                    triggering_event_variant_key, checked_at, observer_sequence,
                    trust_mode, verification_outcome, resolution_method,
                    resolver_version, evidence_ref, evidence_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_key,
                    variant_key,
                    triggering_event_variant_key,
                    checked_at,
                    sequence,
                    result.trust_mode.value,
                    result.verification_outcome.value,
                    result.resolution_method,
                    result.resolver_version,
                    result.evidence_ref,
                    result.evidence_hash,
                ),
            )
            active = self._active_generation(connection)
            self._materialize_projection(connection, active)
            if fail_before_commit:
                raise RuntimeError("injected failure before commit")
            connection.commit()
        return observation_key

    def _active_generation(self, connection: sqlite3.Connection) -> str:
        row = connection.execute(
            """
            SELECT value FROM meta
            WHERE key = 'active_projection_generation'
            """
        ).fetchone()
        assert row is not None
        return str(row[0])

    def _load_events(self, connection: sqlite3.Connection) -> list[EventFact]:
        rows = connection.execute(
            "SELECT * FROM repo_events ORDER BY event_variant_key"
        ).fetchall()
        result: list[EventFact] = []
        for row in rows:
            receipts = connection.execute(
                """
                SELECT * FROM event_receipts
                WHERE event_variant_key = ?
                ORDER BY observer_sequence
                """,
                (row["event_variant_key"],),
            ).fetchall()
            if not receipts:
                continue
            accepted = [
                receipt
                for receipt in receipts
                if receipt["verification_outcome"] in self.accepted_delivery_outcomes
            ]
            result.append(
                EventFact(
                    semantic_event_key=row["semantic_event_key"],
                    event_variant_key=row["event_variant_key"],
                    repo_did=row["repo_did"],
                    repo_order=row["repo_order"],
                    operation=row["operation"],
                    collection=row["collection"],
                    rkey=row["rkey"],
                    record_uri=row["record_uri"],
                    record_cid=row["record_cid"],
                    record=(
                        None
                        if row["record_json"] is None
                        else json.loads(row["record_json"])
                    ),
                    payload_hash=row["payload_hash"],
                    payload_hash_scope=row["payload_hash_scope"],
                    first_observed_sequence=min(
                        receipt["observer_sequence"] for receipt in receipts
                    ),
                    first_received_at=min(
                        _parse_time(receipt["received_at"]) for receipt in receipts
                    ),
                    first_accepted_at=(
                        None
                        if not accepted
                        else min(
                            _parse_time(receipt["received_at"]) for receipt in accepted
                        )
                    ),
                    receipt_count=len(receipts),
                    verification_outcomes=tuple(
                        sorted(
                            {receipt["verification_outcome"] for receipt in receipts}
                        )
                    ),
                )
            )
        return result

    def _load_observations(
        self, connection: sqlite3.Connection
    ) -> list[ObservationFact]:
        rows = connection.execute(
            """
            SELECT o.*, v.requested_uri, v.requested_cid, v.status,
                   v.current_cid, v.record_json, v.payload_hash,
                   v.payload_hash_scope
            FROM subject_observations AS o
            JOIN subject_observation_variants AS v
              ON v.subject_variant_key = o.subject_variant_key
            ORDER BY o.observer_sequence, o.observation_key
            """
        ).fetchall()
        return [
            ObservationFact(
                observation_key=row["observation_key"],
                subject_variant_key=row["subject_variant_key"],
                requested=RecordRef(uri=row["requested_uri"], cid=row["requested_cid"]),
                status=row["status"],
                current_cid=row["current_cid"],
                record=(
                    None
                    if row["record_json"] is None
                    else json.loads(row["record_json"])
                ),
                payload_hash=row["payload_hash"],
                payload_hash_scope=row["payload_hash_scope"],
                triggering_event_variant_key=row["triggering_event_variant_key"],
                checked_at=_parse_time(row["checked_at"]),
                observer_sequence=row["observer_sequence"],
                trust_mode=row["trust_mode"],
                verification_outcome=row["verification_outcome"],
                resolution_method=row["resolution_method"],
                resolver_version=row["resolver_version"],
                evidence_ref=row["evidence_ref"],
                evidence_hash=row["evidence_hash"],
                accepted=(
                    row["verification_outcome"] in self.accepted_resolution_outcomes
                ),
            )
            for row in rows
        ]

    def _source_high_waters(self, connection: sqlite3.Connection) -> str:
        rows = connection.execute(
            "SELECT source, committed_cursor FROM ingest_sources ORDER BY source"
        ).fetchall()
        return _json({row["source"]: row["committed_cursor"] for row in rows})

    def _materialize_projection(
        self, connection: sqlite3.Connection, generation_id: str
    ) -> None:
        assert self.administrator_did is not None  # writable stores require it
        result = reduce_projection(
            self._load_events(connection),
            self._load_observations(connection),
            config=ReducerConfig(
                community_did=self.community_did,
                administrator_did=self.administrator_did,
            ),
        )
        for table in _DERIVED_TABLES:
            connection.execute(
                f"DELETE FROM {table} WHERE generation_id = ?",  # noqa: S608
                (generation_id,),
            )
        self._insert_projection(connection, generation_id, result)
        self._insert_quarantine_audit(connection, generation_id)
        immutable_count = connection.execute(
            """
            SELECT
              (SELECT count(*) FROM event_receipts)
              + (SELECT count(*) FROM quarantined_deliveries)
              + (SELECT count(*) FROM subject_observations)
            """
        ).fetchone()[0]
        derived_count = sum(
            connection.execute(
                f"SELECT count(*) FROM {table} WHERE generation_id = ?",  # noqa: S608
                (generation_id,),
            ).fetchone()[0]
            for table in _DERIVED_TABLES
        )
        now = _utc_wire(datetime.now(UTC))
        connection.execute(
            """
            UPDATE projection_builds SET
                status = 'complete',
                completed_at = ?,
                source_high_waters_json = ?,
                immutable_row_count = ?,
                derived_row_count = ?,
                failure_reason = NULL
            WHERE generation_id = ?
            """,
            (
                now,
                self._source_high_waters(connection),
                immutable_count,
                derived_count,
                generation_id,
            ),
        )

    def _insert_projection(
        self,
        connection: sqlite3.Connection,
        generation_id: str,
        result: ProjectionResult,
    ) -> None:
        for row in result.records_current:
            connection.execute(
                """
                INSERT INTO records_current VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    generation_id,
                    row["record_uri"],
                    row["event_variant_key"],
                    row["repo_order"],
                    row["record_cid"],
                    int(bool(row["deleted"])),
                ),
            )
        for row in result.community_profiles:
            connection.execute(
                "INSERT INTO community_profiles VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    generation_id,
                    row["community_did"],
                    row["record_uri"],
                    row["record_cid"],
                    row["display_name"],
                    row["description"],
                    row["created_at"],
                ),
            )
        for row in result.ledger_records:
            connection.execute(
                """
                INSERT INTO ledger_records VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    generation_id,
                    row["event_variant_key"],
                    row["record_uri"],
                    row["record_cid"],
                    row["kind"],
                    row["repo_did"],
                    row["repo_order"],
                    row["operation"],
                    row["outcome"],
                    _json(row["reason_codes"]),
                    (
                        None
                        if row["normalized_record"] is None
                        else _json(row["normalized_record"])
                    ),
                    row["first_observed_sequence"],
                ),
            )
        for row in result.subject_current:
            connection.execute(
                "INSERT INTO subject_current VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    generation_id,
                    row["subject_uri"],
                    row["subject_cid"],
                    row["observation_key"],
                    row["status"],
                    row["current_cid"],
                    row["observer_sequence"],
                    int(bool(row["accepted"])),
                ),
            )
        for row in result.admission_lifecycles:
            connection.execute(
                """
                INSERT INTO admission_lifecycles VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    generation_id,
                    row["admission_uri"],
                    row["admission_cid"],
                    row["admission_event_variant_key"],
                    row["submission_uri"],
                    row["submission_cid"],
                    row["subject_uri"],
                    row["subject_cid"],
                    row["logical_lifecycle_key"],
                    row["admitted_at"],
                    row["admission_first_observed_sequence"],
                    row["start_observation_key"],
                    row["start_sequence"],
                    row["terminal_observation_key"],
                    row["terminal_sequence"],
                    row["removal_uri"],
                    row["removal_cid"],
                    row["status"],
                    _json(row["reason_codes"]),
                    int(bool(row["eligible"])),
                ),
            )
        for row in result.community_entries:
            connection.execute(
                """
                INSERT INTO community_entries VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    generation_id,
                    row["community_did"],
                    row["subject_uri"],
                    row["subject_cid"],
                    row["submission_uri"],
                    row["submission_cid"],
                    row["admission_uri"],
                    row["admission_cid"],
                    row["admitted_at"],
                    row["status"],
                ),
            )
        for row in result.discussion_roots:
            connection.execute(
                "INSERT INTO discussion_roots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    generation_id,
                    row["root_admission_uri"],
                    row["root_admission_cid"],
                    row["root_subject_uri"],
                    row["root_subject_cid"],
                    row["author_did"],
                    row["admitted_at"],
                    row["status"],
                    int(bool(row["closed"])),
                    row["snapshot_observation_key"],
                    row["last_activity_sequence"],
                ),
            )
        for row in result.discussion_replies:
            connection.execute(
                "INSERT INTO discussion_replies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    generation_id,
                    row["logical_moderation_key"],
                    row["root_admission_uri"],
                    row["root_admission_cid"],
                    row["reply_uri"],
                    row["reply_cid"],
                    row["author_did"],
                    row["parent_uri"],
                    row["parent_cid"],
                    row["submission_uri"],
                    row["submission_cid"],
                    row["admission_uri"],
                    row["admission_cid"],
                    row["admitted_at"],
                    row["status"],
                    row["reason"],
                    row["controlling_action_uri"],
                    row["controlling_action_cid"],
                    row["snapshot_observation_key"],
                    row["activity_sequence"],
                ),
            )
        for row in result.discussion_activity:
            connection.execute(
                "INSERT INTO discussion_activity VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    generation_id,
                    row["activity_key"],
                    row["root_admission_uri"],
                    row["root_admission_cid"],
                    row["actor_did"],
                    row["activity_type"],
                    row["target_uri"],
                    row["target_cid"],
                    row["occurred_at"],
                    row["observer_sequence"],
                ),
            )
        for row in result.projection_findings:
            connection.execute(
                "INSERT INTO projection_findings VALUES (?, ?, ?, ?, ?, ?)",
                (
                    generation_id,
                    row["finding_key"],
                    row["event_variant_key"],
                    row["subject_uri"],
                    row["subject_cid"],
                    row["reason_code"],
                ),
            )
        for row in result.audit_index:
            self._insert_audit_row(connection, generation_id, row)

    def _insert_audit_row(
        self,
        connection: sqlite3.Connection,
        generation_id: str,
        row: Mapping[str, object],
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_index VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                generation_id,
                row["audit_row_key"],
                row["kind"],
                row["semantic_event_key"],
                row["event_variant_key"],
                row["record_uri"],
                row["record_cid"],
                row["subject_uri"],
                row["subject_cid"],
                row["actor"],
                row["reason"],
                row["signed_created_at"],
                row["payload_hash"],
                row["payload_hash_scope"],
                row["first_received_at"],
                row["observer_sequence"],
                row["outcome"],
                _json(row["reason_codes"]),
                row["receipt_count"],
                _json(row["verification_outcomes"]),
            ),
        )

    def _insert_quarantine_audit(
        self, connection: sqlite3.Connection, generation_id: str
    ) -> None:
        rows = connection.execute(
            """
            SELECT * FROM quarantined_deliveries
            ORDER BY quarantine_key
            """
        ).fetchall()
        for row in rows:
            self._insert_audit_row(
                connection,
                generation_id,
                {
                    "audit_row_key": row["quarantine_key"],
                    "kind": "quarantine",
                    "semantic_event_key": None,
                    "event_variant_key": None,
                    "record_uri": None,
                    "record_cid": None,
                    "subject_uri": None,
                    "subject_cid": None,
                    "actor": None,
                    "reason": None,
                    "signed_created_at": None,
                    "payload_hash": row["raw_envelope_hash"],
                    "payload_hash_scope": "observer_json_v0",
                    "first_received_at": row["received_at"],
                    "observer_sequence": row["observer_sequence"],
                    "outcome": "invalid",
                    "reason_codes": (row["reason_code"],),
                    "receipt_count": 1,
                    "verification_outcomes": (row["verification_outcome"],),
                },
            )

    def rebuild(self) -> str:
        """Build and atomically activate a new projection generation."""

        self._require_writable()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            generations = [
                int(row[0][1:])
                for row in connection.execute(
                    "SELECT generation_id FROM projection_builds"
                )
                if str(row[0]).startswith("g") and str(row[0])[1:].isdigit()
            ]
            generation_id = f"g{max(generations, default=0) + 1}"
            now = _utc_wire(datetime.now(UTC))
            connection.execute(
                """
                INSERT INTO projection_builds(
                    generation_id, reducer_version, schema_version, status,
                    started_at, source_high_waters_json
                ) VALUES (?, ?, ?, 'building', ?, ?)
                """,
                (
                    generation_id,
                    PROJECTION_VERSION,
                    SCHEMA_VERSION,
                    now,
                    self._source_high_waters(connection),
                ),
            )
            self._materialize_projection(connection, generation_id)
            connection.execute(
                """
                UPDATE meta SET value = ?
                WHERE key = 'active_projection_generation'
                """,
                (generation_id,),
            )
            connection.commit()
            return generation_id

    def projection_snapshot(
        self, generation_id: str | None = None
    ) -> dict[str, object]:
        """Return semantic generation content, excluding operational coordinates."""

        with self.read_connection() as connection:
            selected = generation_id or self._active_generation(connection)
            snapshot: dict[str, object] = {}
            for table in _DERIVED_TABLES:
                # The audit trail reads in observation order; every other
                # derived table keys on its second column.
                order_by = (
                    "observer_sequence, audit_row_key"
                    if table == "audit_index"
                    else "1, 2"
                )
                rows = connection.execute(
                    f"""
                    SELECT * FROM {table}
                    WHERE generation_id = ?
                    ORDER BY {order_by}
                    """,  # noqa: S608
                    (selected,),
                ).fetchall()
                normalized: list[dict[str, object]] = []
                for row in rows:
                    item = {
                        key: row[key] for key in row.keys() if key != "generation_id"
                    }
                    for key in tuple(item):
                        if key.endswith("_json") and item[key] is not None:
                            item[key.removesuffix("_json")] = json.loads(
                                str(item.pop(key))
                            )
                    normalized.append(item)
                snapshot[table] = normalized
            return snapshot

    def counts(self) -> dict[str, int]:
        with self.read_connection() as connection:
            return {
                table: int(
                    connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608
                )
                for table in (
                    "repo_events",
                    "event_receipts",
                    "quarantined_deliveries",
                    "subject_observation_variants",
                    "subject_observations",
                    *_DERIVED_TABLES,
                )
            }
