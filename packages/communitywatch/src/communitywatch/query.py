"""In-process committed-projection query layer for the V0 observer.

This is the query half of the read API; the HTTP subprocess is a later
milestone.  It reads only committed rows of the active projection generation
through the store's read-only connection, serves ``visible`` entries in
reverse admission chronology with an opaque cursor, serves the compact audit
index in first-receipt order, and fails closed whenever the active projection
is incomplete, incompatible, or (for the current view) stale.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from community_model import (
    ADMISSION_COLLECTION,
    CursorError,
    Page,
    PortError,
    ValidationError,
    canonical_json_bytes,
)
from community_model.identifiers import parse_at_uri, validate_did

from .storage import PROJECTION_VERSION, SCHEMA_VERSION, ObserverStore


class UnknownCommunityError(PortError):
    """The requested community DID is not this observer's community."""


class UnknownEntryError(PortError):
    """No entry with the requested admission key exists in this community."""


class ProjectionUnavailableError(PortError):
    """No compatible, complete, fresh-enough projection may be served."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class SourceFreshness:
    """Committed versus projected ingest cursor for one event source."""

    name: str
    committed_cursor: str | None
    projected_cursor: str | None
    matches: bool


@dataclass(frozen=True, slots=True)
class ProjectionStatus:
    """Committed view of the active projection for freshness/health reads."""

    generation: str | None
    status: str
    compatible: bool
    high_water_matches: bool
    sources: tuple[SourceFreshness, ...]
    last_ingest_at: str | None
    last_resolve_at: str | None
    reason_codes: tuple[str, ...]

    @property
    def fresh(self) -> bool:
        """Whether the current view may serve without a degraded marker."""

        return self.status == "complete" and self.compatible and self.high_water_matches


def _parse_stored_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _encode_cursor(payload: Mapping[str, str]) -> str:
    return base64.urlsafe_b64encode(canonical_json_bytes(payload)).decode("ascii")


def _decode_cursor(cursor: str, expected_keys: frozenset[str]) -> dict[str, str]:
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii"))
        value = json.loads(decoded)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise CursorError("malformed opaque cursor") from exc
    if (
        not isinstance(value, dict)
        or set(value) != expected_keys
        or any(not isinstance(item, str) for item in value.values())
    ):
        raise CursorError("malformed opaque cursor")
    return value


@dataclass(frozen=True, slots=True)
class VisibleEntry:
    """Sortable pagination material for one visible community entry."""

    admitted_at: datetime
    admitted_at_wire: str
    admission_uri: str
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class EntryDetail:
    """One community entry, its projected status, and its audit rows.

    ``entry`` uses exactly the payload shape ``list_visible`` returns.  The
    status is read from the committed projection; nothing here recomputes it.
    """

    entry: Mapping[str, object]
    status: str
    events: tuple[Mapping[str, object], ...]


@dataclass(slots=True)
class ProjectionQuery:
    """Committed-projection reads for the one configured community."""

    store: ObserverStore
    slug: str
    default_limit: int = 50
    max_limit: int = 100

    def _check_community(self, community_did: str) -> str:
        validate_did(community_did)
        if community_did != self.store.community_did:
            raise UnknownCommunityError("unknown community for this observer")
        return community_did

    def _check_limit(self, limit: int) -> int:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= self.max_limit
        ):
            raise ValidationError(
                "schema_invalid", f"limit must be between 1 and {self.max_limit}"
            )
        return limit

    def _current_high_waters(self, connection) -> dict[str, object]:
        rows = connection.execute(
            "SELECT source, committed_cursor FROM ingest_sources ORDER BY source"
        ).fetchall()
        return {row["source"]: row["committed_cursor"] for row in rows}

    def _read_state(self, connection) -> ProjectionStatus:
        row = connection.execute(
            "SELECT value FROM meta WHERE key = 'active_projection_generation'"
        ).fetchone()
        generation = None if row is None else str(row[0])
        build = (
            None
            if generation is None
            else connection.execute(
                """
                SELECT status, reducer_version, schema_version,
                       source_high_waters_json
                FROM projection_builds WHERE generation_id = ?
                """,
                (generation,),
            ).fetchone()
        )
        committed = self._current_high_waters(connection)
        projected: dict[str, object] = (
            {} if build is None else json.loads(build["source_high_waters_json"])
        )
        status = "missing" if build is None else str(build["status"])
        compatible = (
            build is not None
            and build["reducer_version"] == PROJECTION_VERSION
            and build["schema_version"] == SCHEMA_VERSION
        )
        high_water_matches = build is not None and projected == committed
        reason_codes: list[str] = []
        if build is None:
            reason_codes.append(
                "projection_incomplete"
                if generation is not None
                else "projection_missing"
            )
        else:
            if status != "complete":
                reason_codes.append("projection_incomplete")
            if not compatible:
                reason_codes.append("schema_incompatible")
            if status == "complete" and compatible and not high_water_matches:
                reason_codes.append("ingest_stale")
        last_ingest_at = connection.execute(
            "SELECT MAX(last_success_at) FROM ingest_sources"
        ).fetchone()[0]
        last_resolve_at = connection.execute(
            "SELECT MAX(checked_at) FROM subject_observations"
        ).fetchone()[0]
        return ProjectionStatus(
            generation=generation,
            status=status,
            compatible=compatible,
            high_water_matches=high_water_matches,
            sources=tuple(
                SourceFreshness(
                    name=source,
                    committed_cursor=cursor,
                    projected_cursor=projected.get(source),
                    matches=projected.get(source) == cursor,
                )
                for source, cursor in sorted(committed.items())
            ),
            last_ingest_at=last_ingest_at,
            last_resolve_at=last_resolve_at,
            reason_codes=tuple(reason_codes),
        )

    def projection_state(self) -> ProjectionStatus:
        """Describe the active projection, source cursors, and heartbeats."""

        with self.store.read_connection() as connection:
            return self._read_state(connection)

    def _gate(self, connection, *, require_fresh: bool) -> str:
        state = self._read_state(connection)
        if state.status != "complete":
            raise ProjectionUnavailableError(
                "projection_incomplete", "no complete active projection generation"
            )
        if not state.compatible:
            raise ProjectionUnavailableError(
                "schema_incompatible", "active projection predates this process"
            )
        if require_fresh and not state.high_water_matches:
            raise ProjectionUnavailableError(
                "ingest_stale", "projection high-water lags committed ingest"
            )
        assert state.generation is not None
        return state.generation

    def community_identity(self, community_did: str) -> dict[str, object]:
        """Decorate with the accepted current profile or the slug fallback."""

        self._check_community(community_did)
        with self.store.read_connection() as connection:
            generation = self._gate(connection, require_fresh=False)
            row = connection.execute(
                """
                SELECT display_name, description FROM community_profiles
                WHERE generation_id = ? AND community_did = ?
                """,
                (generation, community_did),
            ).fetchone()
        if row is None:
            return {
                "did": community_did,
                "slug": self.slug,
                "displayName": self.slug,
                "description": None,
            }
        return {
            "did": community_did,
            "slug": self.slug,
            "displayName": row["display_name"],
            "description": row["description"],
        }

    def has_profile_record(self, community_did: str) -> bool:
        """Whether an accepted profile record backs the rendered identity.

        Kept out of ``community_identity`` so the JSON wire shape is unchanged;
        the page uses it only to avoid claiming a signed self-description that
        does not exist.
        """

        self._check_community(community_did)
        with self.store.read_connection() as connection:
            generation = self._gate(connection, require_fresh=False)
            row = connection.execute(
                """
                SELECT 1 FROM community_profiles
                WHERE generation_id = ? AND community_did = ?
                """,
                (generation, community_did),
            ).fetchone()
        return row is not None

    def list_members(self, community_did: str) -> tuple[Mapping[str, object], ...]:
        """Reduce accepted authority membership actions from the active ledger.

        The projection owns this read.  The application never infers membership
        from participation, PDS accounts, or OAuth sessions.
        """

        self._check_community(community_did)
        with self.store.read_connection() as connection:
            generation = self._gate(connection, require_fresh=True)
            rows = connection.execute(
                """
                SELECT normalized_record_json, record_uri, record_cid,
                       first_observed_sequence
                FROM ledger_records
                WHERE generation_id = ? AND kind = 'member_action'
                  AND outcome = 'valid' AND normalized_record_json IS NOT NULL
                ORDER BY first_observed_sequence, record_uri
                """,
                (generation,),
            ).fetchall()
        current: dict[str, dict[str, object]] = {}
        for row in rows:
            record = json.loads(row["normalized_record_json"])
            subject = record.get("subject")
            action = record.get("action")
            if not isinstance(subject, str) or action not in {"add", "remove"}:
                raise ProjectionUnavailableError(
                    "projection_incomplete",
                    "membership projection contains an invalid action",
                )
            current[subject] = {
                "did": subject,
                "status": "active" if action == "add" else "removed",
                "action": action,
                "actor": record.get("actor"),
                "reason": record.get("reason"),
                "createdAt": record.get("createdAt"),
                "record": {"uri": row["record_uri"], "cid": row["record_cid"]},
            }
        return tuple(current[did] for did in sorted(current))

    def _visible_rows(self, connection, generation: str) -> list[VisibleEntry]:
        rows = connection.execute(
            """
            SELECT e.subject_uri, e.subject_cid, e.submission_uri,
                   e.submission_cid, e.admission_uri, e.admission_cid,
                   e.admitted_at, l.start_observation_key
            FROM community_entries AS e
            JOIN admission_lifecycles AS l
              ON l.generation_id = e.generation_id
             AND l.admission_uri = e.admission_uri
             AND l.admission_cid = e.admission_cid
            WHERE e.generation_id = ? AND e.community_did = ?
              AND e.status = 'visible'
            """,
            (generation, self.store.community_did),
        ).fetchall()
        entries: list[VisibleEntry] = []
        for row in rows:
            snapshot = connection.execute(
                """
                SELECT v.record_json
                FROM subject_observations AS o
                JOIN subject_observation_variants AS v
                  ON v.subject_variant_key = o.subject_variant_key
                WHERE o.observation_key = ?
                """,
                (row["start_observation_key"],),
            ).fetchone()
            record = (
                None
                if snapshot is None or snapshot["record_json"] is None
                else json.loads(snapshot["record_json"])
            )
            if not isinstance(record, dict):
                raise ProjectionUnavailableError(
                    "projection_incomplete",
                    "a visible entry lacks its exact subject snapshot",
                )
            payload = self._entry_payload(row, record)
            entries.append(
                VisibleEntry(
                    admitted_at=_parse_stored_time(row["admitted_at"]),
                    admitted_at_wire=row["admitted_at"],
                    admission_uri=row["admission_uri"],
                    payload=payload,
                )
            )
        entries.sort(
            key=lambda entry: (entry.admitted_at, entry.admission_uri),
            reverse=True,
        )
        return entries

    def list_visible(
        self, community_did: str, limit: int, cursor: str | None
    ) -> Page[Mapping[str, object]]:
        """Page visible entries by signed admission time, URI tie-break."""

        self._check_community(community_did)
        self._check_limit(limit)
        marker = (
            None
            if cursor is None
            else _decode_cursor(cursor, frozenset({"admittedAt", "admissionUri"}))
        )
        with self.store.read_connection() as connection:
            generation = self._gate(connection, require_fresh=True)
            entries = self._visible_rows(connection, generation)
        if marker is not None:
            boundary = (
                _parse_stored_time(marker["admittedAt"]),
                marker["admissionUri"],
            )
            entries = [
                entry
                for entry in entries
                if (entry.admitted_at, entry.admission_uri) < boundary
            ]
        page = entries[:limit]
        next_cursor = None
        if len(entries) > limit and page:
            last = page[-1]
            next_cursor = _encode_cursor(
                {
                    "admittedAt": last.admitted_at_wire,
                    "admissionUri": last.admission_uri,
                }
            )
        return Page(items=tuple(entry.payload for entry in page), cursor=next_cursor)

    def hidden_entry_count(self, community_did: str) -> int:
        """How many entries exist that the current view deliberately omits.

        Read straight from the committed projection so an empty page can tell
        "nothing was ever added here" apart from "everything here was removed
        or changed at the source" without guessing.
        """

        self._check_community(community_did)
        with self.store.read_connection() as connection:
            generation = self._gate(connection, require_fresh=True)
            row = connection.execute(
                """
                SELECT COUNT(*) FROM community_entries
                WHERE generation_id = ? AND community_did = ? AND status != ?
                """,
                (generation, community_did, "visible"),
            ).fetchone()
        return int(row[0])

    def entry_detail(self, community_did: str, admission_rkey: str) -> EntryDetail:
        """Look up one community entry by its deterministic admission rkey.

        This is a lookup, not a new rule: it applies the same freshness gate as
        the current view and reuses the same entry payload and audit payload
        builders.  Unlike ``list_visible`` it does not filter on ``visible``,
        so a permalink keeps explaining an item after it is removed or its
        subject changes, and it tolerates a missing subject snapshot instead of
        failing the whole projection — absence is expected once a subject is
        deleted.
        """

        self._check_community(community_did)
        admission_uri = f"at://{community_did}/{ADMISSION_COLLECTION}/{admission_rkey}"
        with self.store.read_connection() as connection:
            generation = self._gate(connection, require_fresh=True)
            row = connection.execute(
                """
                SELECT e.subject_uri, e.subject_cid, e.submission_uri,
                       e.submission_cid, e.admission_uri, e.admission_cid,
                       e.admitted_at, e.status, l.start_observation_key
                FROM community_entries AS e
                LEFT JOIN admission_lifecycles AS l
                  ON l.generation_id = e.generation_id
                 AND l.admission_uri = e.admission_uri
                 AND l.admission_cid = e.admission_cid
                WHERE e.generation_id = ? AND e.community_did = ?
                  AND e.admission_uri = ?
                """,
                (generation, community_did, admission_uri),
            ).fetchone()
            if row is None:
                raise UnknownEntryError("no such entry in this community")
            record = None
            if row["start_observation_key"] is not None:
                snapshot = connection.execute(
                    """
                    SELECT v.record_json
                    FROM subject_observations AS o
                    JOIN subject_observation_variants AS v
                      ON v.subject_variant_key = o.subject_variant_key
                    WHERE o.observation_key = ?
                    """,
                    (row["start_observation_key"],),
                ).fetchone()
                if snapshot is not None and snapshot["record_json"] is not None:
                    decoded = json.loads(snapshot["record_json"])
                    record = decoded if isinstance(decoded, dict) else None
            audit_rows = connection.execute(
                """
                SELECT * FROM audit_index
                WHERE generation_id = ?
                  AND (record_uri IN (?, ?) OR subject_uri = ?)
                ORDER BY first_received_at, audit_row_key
                """,
                (
                    generation,
                    row["submission_uri"],
                    row["admission_uri"],
                    row["subject_uri"],
                ),
            ).fetchall()
            operations = {
                item["event_variant_key"]: item["operation"]
                for item in connection.execute(
                    "SELECT event_variant_key, operation FROM repo_events"
                )
            }
        events = tuple(self._audit_payload(item, operations) for item in audit_rows)
        return EntryDetail(
            entry=self._entry_payload(row, record),
            status=str(row["status"]),
            events=events,
        )

    @staticmethod
    def _entry_payload(row, record: Mapping[str, object] | None) -> dict[str, object]:
        """Build the wire payload shared by the list and detail surfaces."""

        subject_uri = row["subject_uri"]
        parsed = parse_at_uri(subject_uri)
        return {
            "subject": {"uri": subject_uri, "cid": row["subject_cid"]},
            "submission": {
                "uri": row["submission_uri"],
                "cid": row["submission_cid"],
            },
            "admission": {
                "uri": row["admission_uri"],
                "cid": row["admission_cid"],
            },
            "authorDid": parsed.authority,
            "admittedAt": row["admitted_at"],
            "post": (
                {}
                if record is None
                else {
                    key: record[key] for key in ("text", "createdAt") if key in record
                }
            ),
            "sourceUrl": (
                f"https://bsky.app/profile/{parsed.authority}/post/{parsed.rkey}"
            ),
        }

    def list_audit(
        self, community_did: str, limit: int, cursor: str | None
    ) -> Page[Mapping[str, object]]:
        """Page the compact audit index by first receipt, row-key tie-break."""

        self._check_community(community_did)
        self._check_limit(limit)
        marker = (
            None
            if cursor is None
            else _decode_cursor(cursor, frozenset({"receivedAt", "rowKey"}))
        )
        with self.store.read_connection() as connection:
            generation = self._gate(connection, require_fresh=False)
            rows = connection.execute(
                "SELECT * FROM audit_index WHERE generation_id = ?",
                (generation,),
            ).fetchall()
            operations = {
                row["event_variant_key"]: row["operation"]
                for row in connection.execute(
                    "SELECT event_variant_key, operation FROM repo_events"
                )
            }
        items = [
            (
                (_parse_stored_time(row["first_received_at"]), row["audit_row_key"]),
                self._audit_payload(row, operations),
            )
            for row in rows
        ]
        items.sort(key=lambda item: item[0], reverse=True)
        if marker is not None:
            boundary = (_parse_stored_time(marker["receivedAt"]), marker["rowKey"])
            items = [item for item in items if item[0] < boundary]
        page = items[:limit]
        next_cursor = None
        if len(items) > limit and page:
            (last_time, last_key), _ = page[-1]
            next_cursor = _encode_cursor(
                {"receivedAt": last_time.isoformat(), "rowKey": last_key}
            )
        return Page(items=tuple(payload for _, payload in page), cursor=next_cursor)

    def _audit_payload(self, row, operations: Mapping[str, str]) -> dict[str, object]:
        record = None
        if row["record_uri"] is not None:
            record = {"uri": row["record_uri"], "cid": row["record_cid"]}
        subject = None
        if row["subject_uri"] is not None:
            subject = {"uri": row["subject_uri"], "cid": row["subject_cid"]}
        # Only repository-event rows carry an operation; quarantine rows and
        # subject observations are not repository operations at all.
        operation = None
        if row["semantic_event_key"] is not None:
            operation = operations.get(row["event_variant_key"])
        return {
            "auditRowKey": row["audit_row_key"],
            "semanticEventKey": row["semantic_event_key"],
            "eventVariantKey": row["event_variant_key"],
            "payloadHash": row["payload_hash"],
            "payloadHashScope": row["payload_hash_scope"],
            "record": record,
            "operation": operation,
            "kind": row["kind"],
            "subject": subject,
            "actor": row["actor"],
            "reason": row["reason"],
            "createdAt": row["signed_created_at"],
            "firstReceivedAt": row["first_received_at"],
            "verificationOutcomes": json.loads(row["verification_outcomes_json"]),
            "receiptCount": row["receipt_count"],
            "outcome": row["outcome"],
            "reasonCodes": json.loads(row["reason_codes_json"]),
        }
