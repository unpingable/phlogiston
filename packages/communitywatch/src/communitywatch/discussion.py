"""Read-only PCV0 discussion projections over one committed generation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from community_model import ADMISSION_COLLECTION, ValidationError
from community_model.identifiers import validate_did, validate_rkey

from .query import (
    ProjectionQuery,
    ProjectionUnavailableError,
    UnknownEntryError,
    _decode_cursor,
    _encode_cursor,
)


@dataclass(frozen=True, slots=True)
class ProjectionSnapshot:
    """Version actually displayed; safe as a private last-seen boundary."""

    generation: str
    observer_sequence: int

    def as_dict(self) -> dict[str, object]:
        return {
            "generation": self.generation,
            "observerSequence": self.observer_sequence,
        }


@dataclass(frozen=True, slots=True)
class DiscussionPage:
    items: tuple[Mapping[str, object], ...]
    cursor: str | None
    snapshot: ProjectionSnapshot


@dataclass(frozen=True, slots=True)
class DiscussionDetail:
    discussion: Mapping[str, object]
    replies: tuple[Mapping[str, object], ...]
    activity: tuple[Mapping[str, object], ...]
    snapshot: ProjectionSnapshot


@dataclass(frozen=True, slots=True)
class ParticipantActivity:
    discussions: tuple[Mapping[str, object], ...]
    activity: tuple[Mapping[str, object], ...]
    snapshot: ProjectionSnapshot


@dataclass(frozen=True, slots=True)
class ModerationQueue:
    submissions: tuple[Mapping[str, object], ...]
    snapshot: ProjectionSnapshot
    cursor: str | None = None
    coverage: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ReplyCandidates:
    candidates: tuple[Mapping[str, object], ...]
    snapshot: ProjectionSnapshot


@dataclass(slots=True)
class DiscussionQuery:
    """Queries consumed by the separate OAuth/write-capable web backend."""

    projection: ProjectionQuery

    def _snapshot(self, connection, generation: str) -> ProjectionSnapshot:
        row = connection.execute(
            "SELECT value FROM meta WHERE key = 'observer_sequence'"
        ).fetchone()
        return ProjectionSnapshot(generation, 0 if row is None else int(row[0]))

    @staticmethod
    def _record(connection, observation_key: str | None) -> dict[str, object] | None:
        if observation_key is None:
            return None
        row = connection.execute(
            """
            SELECT v.record_json FROM subject_observations AS o
            JOIN subject_observation_variants AS v
              ON v.subject_variant_key = o.subject_variant_key
            WHERE o.observation_key = ?
            """,
            (observation_key,),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        value = json.loads(row[0])
        return value if isinstance(value, dict) else None

    def _root_payload(self, connection, row) -> dict[str, object]:
        record = self._record(connection, row["snapshot_observation_key"])
        if record is None and row["status"] == "visible":
            raise ProjectionUnavailableError(
                "projection_incomplete", "verified discussion root snapshot unavailable"
            )
        return {
            "discussion": {
                "uri": row["root_admission_uri"],
                "cid": row["root_admission_cid"],
            },
            "root": {
                "uri": row["root_subject_uri"],
                "cid": row["root_subject_cid"],
            },
            "authorDid": row["author_did"],
            "admittedAt": row["admitted_at"],
            "status": row["status"],
            "closed": bool(row["closed"]),
            "lastActivitySequence": row["last_activity_sequence"],
            "post": {}
            if record is None
            else {key: record[key] for key in ("text", "createdAt") if key in record},
        }

    def _reply_payload(self, connection, row) -> dict[str, object]:
        removed = row["status"] == "removed"
        record = (
            None
            if removed
            else self._record(connection, row["snapshot_observation_key"])
        )
        return {
            "admission": {"uri": row["admission_uri"], "cid": row["admission_cid"]},
            "subject": {"uri": row["reply_uri"], "cid": row["reply_cid"]},
            "parent": None
            if row["parent_uri"] is None
            else {"uri": row["parent_uri"], "cid": row["parent_cid"]},
            "authorDid": row["author_did"],
            "admittedAt": row["admitted_at"],
            "status": row["status"],
            "reason": row["reason"] if removed else None,
            "controllingAction": {
                "uri": row["controlling_action_uri"],
                "cid": row["controlling_action_cid"],
            }
            if removed
            and row["controlling_action_uri"] is not None
            and row["controlling_action_cid"] is not None
            else None,
            "unavailable": record is None and not removed,
            # Removed text is never selected, decoded, or exposed.
            "post": {}
            if record is None
            else {key: record[key] for key in ("text", "createdAt") if key in record},
        }

    @staticmethod
    def _activity_payload(row) -> dict[str, object]:
        return {
            "key": row["activity_key"],
            "discussion": {
                "uri": row["root_admission_uri"],
                "cid": row["root_admission_cid"],
            },
            "type": row["activity_type"],
            "actorDid": row["actor_did"],
            "target": {"uri": row["target_uri"], "cid": row["target_cid"]},
            "occurredAt": row["occurred_at"],
            "observerSequence": row["observer_sequence"],
        }

    def list_discussions(self, community_did: str) -> DiscussionPage:
        self.projection._check_community(community_did)
        with self.projection.store.read_connection() as connection:
            generation = self.projection._gate(connection, require_fresh=True)
            rows = connection.execute(
                """SELECT * FROM discussion_roots
                   WHERE generation_id = ? AND closed = 0 AND status = 'visible'
                   ORDER BY admitted_at DESC, root_admission_uri DESC""",
                (generation,),
            ).fetchall()
            items = tuple(self._root_payload(connection, row) for row in rows)
            snapshot = self._snapshot(connection, generation)
        return DiscussionPage(items, None, snapshot)

    def discussion(self, community_did: str, admission_rkey: str) -> DiscussionDetail:
        self.projection._check_community(community_did)
        validate_rkey(admission_rkey)
        uri = f"at://{community_did}/{ADMISSION_COLLECTION}/{admission_rkey}"
        with self.projection.store.read_connection() as connection:
            generation = self.projection._gate(connection, require_fresh=True)
            root = connection.execute(
                "SELECT * FROM discussion_roots WHERE generation_id = ? AND root_admission_uri = ?",
                (generation, uri),
            ).fetchone()
            if root is None:
                raise UnknownEntryError("no such discussion in this community")
            reply_rows = connection.execute(
                """SELECT * FROM discussion_replies WHERE generation_id = ?
                   AND root_admission_uri = ? AND root_admission_cid = ?
                   ORDER BY activity_sequence, admission_uri""",
                (generation, root["root_admission_uri"], root["root_admission_cid"]),
            ).fetchall()
            activity_rows = connection.execute(
                """SELECT * FROM discussion_activity WHERE generation_id = ?
                   AND root_admission_uri = ? AND root_admission_cid = ?
                   ORDER BY observer_sequence, activity_key""",
                (generation, root["root_admission_uri"], root["root_admission_cid"]),
            ).fetchall()
            detail = DiscussionDetail(
                self._root_payload(connection, root),
                tuple(self._reply_payload(connection, row) for row in reply_rows),
                tuple(self._activity_payload(row) for row in activity_rows),
                self._snapshot(connection, generation),
            )
        return detail

    def participant_activity(
        self, community_did: str, participant_did: str
    ) -> ParticipantActivity:
        self.projection._check_community(community_did)
        validate_did(participant_did)
        with self.projection.store.read_connection() as connection:
            generation = self.projection._gate(connection, require_fresh=True)
            roots = connection.execute(
                """SELECT DISTINCT r.* FROM discussion_roots AS r
                   LEFT JOIN discussion_replies AS p ON p.generation_id = r.generation_id
                    AND p.root_admission_uri = r.root_admission_uri
                    AND p.root_admission_cid = r.root_admission_cid
                   WHERE r.generation_id = ? AND (r.author_did = ? OR p.author_did = ?)
                   ORDER BY r.last_activity_sequence DESC""",
                (generation, participant_did, participant_did),
            ).fetchall()
            keys = {
                (row["root_admission_uri"], row["root_admission_cid"]) for row in roots
            }
            activity = connection.execute(
                "SELECT * FROM discussion_activity WHERE generation_id = ? ORDER BY observer_sequence DESC",
                (generation,),
            ).fetchall()
            return ParticipantActivity(
                tuple(self._root_payload(connection, row) for row in roots),
                tuple(
                    self._activity_payload(row)
                    for row in activity
                    if (row["root_admission_uri"], row["root_admission_cid"]) in keys
                ),
                self._snapshot(connection, generation),
            )

    def reply_candidates(self, community_did: str) -> ReplyCandidates:
        self.projection._check_community(community_did)
        with self.projection.store.read_connection() as connection:
            generation = self.projection._gate(connection, require_fresh=True)
            open_roots = {
                (row["root_admission_uri"], row["root_admission_cid"])
                for row in connection.execute(
                    "SELECT root_admission_uri, root_admission_cid "
                    "FROM discussion_roots WHERE generation_id = ? "
                    "AND status = 'visible' AND closed = 0",
                    (generation,),
                )
            }
            admitted = {
                row[0]
                for row in connection.execute(
                    "SELECT submission_uri FROM discussion_replies "
                    "WHERE generation_id = ?",
                    (generation,),
                )
            }
            policy_by_root: dict[tuple[str, str], dict[str, str]] = {}
            policies = connection.execute(
                "SELECT record_uri, record_cid, normalized_record_json "
                "FROM ledger_records WHERE generation_id = ? "
                "AND kind = 'reply_policy' AND outcome = 'valid' "
                "AND operation = 'create'",
                (generation,),
            ).fetchall()
            for row in policies:
                record = json.loads(row["normalized_record_json"])
                root = record.get("discussion")
                if isinstance(root, dict):
                    policy_by_root[(root.get("uri"), root.get("cid"))] = {
                        "uri": row["record_uri"],
                        "cid": row["record_cid"],
                    }
            submissions = connection.execute(
                "SELECT record_uri, record_cid, normalized_record_json "
                "FROM ledger_records WHERE generation_id = ? "
                "AND kind = 'submission' AND outcome = 'valid' "
                "AND operation != 'delete'",
                (generation,),
            ).fetchall()
            candidates = []
            for row in submissions:
                record = json.loads(row["normalized_record_json"])
                root = record.get("discussion")
                if not isinstance(root, dict):
                    continue
                root_key = (root.get("uri"), root.get("cid"))
                policy = policy_by_root.get(root_key)
                if (
                    row["record_uri"] in admitted
                    or root_key not in open_roots
                    or policy is None
                ):
                    continue
                candidates.append(
                    {
                        "submission": {
                            "uri": row["record_uri"],
                            "cid": row["record_cid"],
                        },
                        "subject": record["subject"],
                        "rootAdmission": root,
                        "replyPolicy": policy,
                    }
                )
            return ReplyCandidates(
                tuple(candidates), self._snapshot(connection, generation)
            )

    def moderation_queue(
        self,
        community_did: str,
        *,
        limit: int = 25,
        cursor: str | None = None,
        author_did: str | None = None,
    ) -> ModerationQueue:
        """Bounded candidate acquisition; the application owns active capacity.

        Global pages advance by DID, preventing one prolific repository from
        hiding later repositories. Per-author continuation advances by sequence.
        No private decision state is read, and missing candidates are not refusals.
        """
        self.projection._check_community(community_did)
        if isinstance(limit, bool) or not 1 <= limit <= 25:
            raise ValidationError(
                "schema_invalid", "queue limit must be between 1 and 25"
            )
        if author_did is not None:
            validate_did(author_did)
        if cursor is not None and len(cursor) > 2048:
            raise ValidationError(
                "schema_invalid", "candidate cursor exceeds size bound"
            )
        marker = (
            None
            if cursor is None
            else _decode_cursor(
                cursor, frozenset({"authorDid", "sequence", "recordUri"})
            )
        )
        if marker is not None and (
            not marker["sequence"].isdigit() or len(marker["sequence"]) > 20
        ):
            raise ValidationError("schema_invalid", "malformed candidate cursor")
        with self.projection.store.read_connection() as connection:
            generation = self.projection._gate(connection, require_fresh=True)
            if author_did is not None:
                if marker is not None and marker["authorDid"] != author_did:
                    raise ValidationError(
                        "schema_invalid", "cursor author does not match"
                    )
                dids = [(author_did,)]
            else:
                dids = []
                after_did = "" if marker is None else marker["authorDid"]
                for _ in range(26):
                    row = connection.execute(
                        "SELECT repo_did FROM ledger_records "
                        "WHERE generation_id = ? AND kind = 'submission' "
                        "AND repo_did > ? ORDER BY repo_did LIMIT 1",
                        (generation, after_did),
                    ).fetchone()
                    if row is None:
                        break
                    dids.append(row)
                    after_did = row[0]
            pending = []
            continuations = {}
            incomplete = len(dids) > 25
            last_did = None
            dids_inspected = 0
            for did_row in dids[:25]:
                if len(pending) >= limit:
                    incomplete = True
                    break
                did = did_row[0]
                dids_inspected += 1
                last_did = did
                sequence = (
                    0
                    if marker is None or author_did is None
                    else int(marker["sequence"])
                )
                uri = (
                    "" if marker is None or author_did is None else marker["recordUri"]
                )
                rows = connection.execute(
                    """SELECT l.record_uri,l.record_cid,l.event_variant_key,l.normalized_record_json,
                              l.first_observed_sequence
                       FROM ledger_records AS l
                       WHERE l.generation_id = ? AND l.repo_did = ?
                         AND l.kind = 'submission' AND l.outcome = 'valid'
                         AND l.operation != 'delete'
                         AND (l.first_observed_sequence,l.record_uri) > (?,?)
                       ORDER BY l.first_observed_sequence,l.record_uri LIMIT 17""",
                    (generation, did, sequence, uri),
                ).fetchmany(17)
                selected = 0
                seen = set()
                scanned = None
                for row in rows[:16]:
                    scanned = row
                    current = connection.execute(
                        "SELECT event_variant_key,deleted FROM records_current "
                        "WHERE generation_id = ? AND record_uri = ?",
                        (generation, row["record_uri"]),
                    ).fetchone()
                    if (
                        current is None
                        or current["deleted"]
                        or current["event_variant_key"] != row["event_variant_key"]
                    ):
                        continue
                    record = json.loads(row["normalized_record_json"])
                    if record.get("discussion") is not None:
                        continue
                    subject = record["subject"]
                    key = (subject["uri"], subject["cid"])
                    if key in seen:
                        continue
                    seen.add(key)
                    admitted = connection.execute(
                        """SELECT 1 FROM admission_lifecycles
                           WHERE generation_id = ? AND subject_uri = ?
                           AND subject_cid = ? LIMIT 1""",
                        (generation, *key),
                    ).fetchone()
                    if admitted is not None:
                        continue
                    pending.append(
                        {
                            "submission": {
                                "uri": row["record_uri"],
                                "cid": row["record_cid"],
                            },
                            "subject": subject,
                            "authorDid": did,
                            "observerSequence": row["first_observed_sequence"],
                        }
                    )
                    selected += 1
                    if selected == 3 or len(pending) == limit:
                        break
                if scanned is not None and (len(rows) > 16 or scanned != rows[-1]):
                    incomplete = True
                    continuations[did] = _encode_cursor(
                        {
                            "authorDid": did,
                            "sequence": str(scanned["first_observed_sequence"]),
                            "recordUri": scanned["record_uri"],
                        }
                    )
            next_cursor = None
            if author_did is not None:
                next_cursor = continuations.get(author_did)
            elif last_did is not None and (len(dids) > 25 or last_did != dids[-1][0]):
                next_cursor = _encode_cursor(
                    {"authorDid": last_did, "sequence": "0", "recordUri": ""}
                )
            return ModerationQueue(
                tuple(pending),
                self._snapshot(connection, generation),
                next_cursor,
                {
                    "kind": "candidates",
                    "overflow": incomplete,
                    "incomplete": incomplete,
                    "authorCursors": continuations,
                    "didsInspected": dids_inspected,
                    "maxCandidatesPerDid": 16,
                    "historyBounded": False,
                },
            )
