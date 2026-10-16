"""Private, durable P0 subject decisions; never an ATProto record or observer input."""

from __future__ import annotations

import os
import sqlite3
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from community_model import RecordRef, ValidationError

from .journal import JournalConflictError


@dataclass(frozen=True, slots=True)
class SubjectDecision:
    community_did: str
    author_did: str
    actor_did: str
    subject: RecordRef
    submission: RecordRef
    state: str
    operation_id: str
    admission: RecordRef | None
    reason: str | None
    decided_at: str

    def response(self, submission: RecordRef) -> dict[str, object]:
        return {
            "decision": self.state,
            "submission": submission.as_dict(),
            "subject": self.subject.as_dict(),
            "admission": None if self.admission is None else self.admission.as_dict(),
            "reason": self.reason,
            "operationId": self.operation_id,
            "actorDid": self.actor_did,
            "decidedAt": None if self.state == "admit_pending" else self.decided_at,
        }


class P0DecisionStore:
    """One SQLite transaction serializes admit and decline for an exact subject."""

    def __init__(self, path: str | Path, *, test_origin: str | None = None) -> None:
        self.path = Path(path)
        self.test_origin = test_origin or ""
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS p0_profile_meta (
                    singleton INTEGER PRIMARY KEY CHECK (singleton=1),
                    test_origin TEXT NOT NULL
                )
            """)
            existing = connection.execute(
                "SELECT test_origin FROM p0_profile_meta WHERE singleton=1"
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO p0_profile_meta(singleton,test_origin) VALUES (1,?)",
                    (self.test_origin,),
                )
            elif existing["test_origin"] != self.test_origin:
                raise ValueError("P0 decision custody belongs to another provider mode")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS p0_subject_decisions (
                    community_did TEXT NOT NULL,
                    author_did TEXT NOT NULL,
                    actor_did TEXT NOT NULL,
                    subject_uri TEXT NOT NULL,
                    subject_cid TEXT NOT NULL,
                    submission_uri TEXT NOT NULL,
                    submission_cid TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('admit_pending','admitted','declined')),
                    operation_id TEXT NOT NULL UNIQUE,
                    admission_uri TEXT,
                    admission_cid TEXT,
                    reason TEXT,
                    decided_at TEXT NOT NULL,
                    PRIMARY KEY (community_did,author_did,subject_uri,subject_cid)
                )
            """)
            connection.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS p0_submission_decision
                ON p0_subject_decisions (community_did,submission_uri,submission_cid)
            """)
        self.path.chmod(0o600)

    @staticmethod
    def _row(row: sqlite3.Row | None) -> SubjectDecision | None:
        if row is None:
            return None
        admission = (
            None
            if row["admission_uri"] is None
            else RecordRef(uri=row["admission_uri"], cid=row["admission_cid"])
        )
        return SubjectDecision(
            community_did=row["community_did"],
            author_did=row["author_did"],
            actor_did=row["actor_did"],
            subject=RecordRef(uri=row["subject_uri"], cid=row["subject_cid"]),
            submission=RecordRef(uri=row["submission_uri"], cid=row["submission_cid"]),
            state=row["state"],
            operation_id=row["operation_id"],
            admission=admission,
            reason=row["reason"],
            decided_at=row["decided_at"],
        )

    def find(
        self, community_did: str, author_did: str, subject: RecordRef
    ) -> SubjectDecision | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM p0_subject_decisions WHERE community_did=? AND author_did=?
                    AND subject_uri=? AND subject_cid=?
            """,
                (community_did, author_did, subject.uri, subject.cid),
            ).fetchone()
        return self._row(row)

    def find_submission(
        self, community_did: str, submission: RecordRef
    ) -> SubjectDecision | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM p0_subject_decisions WHERE community_did=?
                    AND submission_uri=? AND submission_cid=?
            """,
                (community_did, submission.uri, submission.cid),
            ).fetchone()
        return self._row(row)

    def reserve(
        self,
        *,
        community_did: str,
        author_did: str,
        actor_did: str,
        subject: RecordRef,
        submission: RecordRef,
        operation_id: str,
        state: str,
        decided_at: str,
        reason: str | None = None,
    ) -> SubjectDecision:
        if state not in {"admit_pending", "declined"}:
            raise ValueError("unsupported initial P0 decision")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._row(
                connection.execute(
                    """
                SELECT * FROM p0_subject_decisions WHERE community_did=? AND author_did=?
                    AND subject_uri=? AND subject_cid=?
            """,
                    (community_did, author_did, subject.uri, subject.cid),
                ).fetchone()
            )
            if existing is not None:
                if state == "declined" and existing.state == "declined":
                    if existing.operation_id != operation_id:
                        raise JournalConflictError(
                            "exact subject has already been declined"
                        )
                    if existing.reason != reason or existing.submission != submission:
                        raise JournalConflictError("decline operation input differs")
                    if existing.actor_did != actor_did:
                        raise JournalConflictError("decline actor differs")
                    return existing
                if state == "admit_pending" and existing.state in {
                    "admit_pending",
                    "admitted",
                }:
                    if (
                        existing.operation_id != operation_id
                        and existing.state == "admit_pending"
                    ):
                        raise JournalConflictError("exact subject admission is pending")
                    if (
                        existing.operation_id == operation_id
                        and existing.submission != submission
                    ):
                        raise JournalConflictError("admission operation input differs")
                    if (
                        existing.operation_id == operation_id
                        and existing.actor_did != actor_did
                    ):
                        raise JournalConflictError("admission actor differs")
                    return existing
                raise JournalConflictError(
                    "exact subject already has an incompatible decision"
                )
            try:
                connection.execute(
                    """
                    INSERT INTO p0_subject_decisions
                    (community_did,author_did,actor_did,subject_uri,subject_cid,
                     submission_uri,submission_cid,state,operation_id,reason,decided_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                    (
                        community_did,
                        author_did,
                        actor_did,
                        subject.uri,
                        subject.cid,
                        submission.uri,
                        submission.cid,
                        state,
                        operation_id,
                        reason,
                        decided_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise JournalConflictError(
                    "operation id already belongs to another decision"
                ) from exc
            return SubjectDecision(
                community_did,
                author_did,
                actor_did,
                subject,
                submission,
                state,
                operation_id,
                None,
                reason,
                decided_at,
            )

    def committed(
        self, decision: SubjectDecision, admission: RecordRef
    ) -> SubjectDecision:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM p0_subject_decisions WHERE community_did=? AND author_did=?
                    AND subject_uri=? AND subject_cid=?
            """,
                (
                    decision.community_did,
                    decision.author_did,
                    decision.subject.uri,
                    decision.subject.cid,
                ),
            ).fetchone()
            current = self._row(row)
            if current is None or current.operation_id != decision.operation_id:
                raise JournalConflictError("P0 admission reservation changed")
            if current.state == "admitted":
                if current.admission != admission:
                    raise JournalConflictError("P0 admission result changed")
                return current
            if current.state != "admit_pending":
                raise JournalConflictError("P0 admission reservation is terminal")
            terminal_at = datetime.now(UTC).isoformat()
            connection.execute(
                """
                UPDATE p0_subject_decisions SET state='admitted',admission_uri=?,admission_cid=?,decided_at=?
                WHERE community_did=? AND author_did=? AND subject_uri=? AND subject_cid=?
            """,
                (
                    admission.uri,
                    admission.cid,
                    terminal_at,
                    decision.community_did,
                    decision.author_did,
                    decision.subject.uri,
                    decision.subject.cid,
                ),
            )
            return SubjectDecision(
                decision.community_did,
                decision.author_did,
                decision.actor_did,
                decision.subject,
                decision.submission,
                "admitted",
                decision.operation_id,
                admission,
                None,
                terminal_at,
            )

    def release_unattempted(self, decision: SubjectDecision) -> None:
        """Retire a reservation after a known refusal before provider dispatch.

        The caller must establish that the operation journal is absent or only
        prepared. The single authority server serializes this with dispatch.
        """
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """DELETE FROM p0_subject_decisions
                   WHERE community_did=? AND author_did=? AND subject_uri=?
                     AND subject_cid=? AND submission_uri=? AND submission_cid=?
                     AND operation_id=? AND state='admit_pending'""",
                (
                    decision.community_did,
                    decision.author_did,
                    decision.subject.uri,
                    decision.subject.cid,
                    decision.submission.uri,
                    decision.submission.cid,
                    decision.operation_id,
                ),
            )


def admission_open(path: str | Path) -> bool:
    """Mandatory operator-owned control file; ambiguity fails closed."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o022:
                raise ValidationError(
                    "admission_paused", "admission control has unsafe permissions"
                )
            value = os.read(descriptor, 17)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ValidationError(
            "admission_paused", "admission control is unavailable"
        ) from exc
    if value == b"open\n":
        return True
    if value == b"paused\n":
        return False
    raise ValidationError("admission_paused", "admission control is invalid")
