"""Durable, serialized authority-operation journal.

The journal is private communityd state.  It is deliberately independent of
observer databases: a projection can neither authorize nor settle a write.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from community_model import canonical_json_bytes

OperationState = Literal[
    "prepared", "attempted_unknown", "committed", "conflict", "refused"
]
_STATES = frozenset(
    {"prepared", "attempted_unknown", "committed", "conflict", "refused"}
)
_TERMINAL = frozenset({"committed", "conflict", "refused"})


class JournalConflictError(RuntimeError):
    """An operation id was reused for different authority-defining input."""


@dataclass(frozen=True, slots=True)
class JournalEntry:
    operation_id: str
    action: str
    repo_did: str
    collection: str
    rkey: str
    intended_record: Mapping[str, object]
    state: OperationState
    result_uri: str | None
    result_cid: str | None
    refusal_code: str | None

    @property
    def record_uri(self) -> str:
        return f"at://{self.repo_did}/{self.collection}/{self.rkey}"


class SQLiteOperationJournal:
    """SQLite journal using ``BEGIN IMMEDIATE`` to serialize authority writes."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS authority_operations (
                    operation_id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    repo_did TEXT NOT NULL,
                    collection TEXT NOT NULL,
                    rkey TEXT NOT NULL,
                    intended_json BLOB NOT NULL,
                    state TEXT NOT NULL CHECK (state IN
                        ('prepared','attempted_unknown','committed','conflict','refused')),
                    result_uri TEXT,
                    result_cid TEXT,
                    refusal_code TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE (repo_did, collection, rkey)
                )
                """
            )
        self.path.chmod(0o600)

    def prepare(
        self,
        *,
        operation_id: str,
        action: str,
        repo_did: str,
        collection: str,
        rkey: str,
        intended_record: Mapping[str, object],
    ) -> JournalEntry:
        intended = canonical_json_bytes(intended_record)
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM authority_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                occupant = connection.execute(
                    """SELECT operation_id FROM authority_operations
                       WHERE repo_did = ? AND collection = ? AND rkey = ?""",
                    (repo_did, collection, rkey),
                ).fetchone()
                if occupant is not None:
                    raise JournalConflictError(
                        "authority rkey is reserved by another operation"
                    )
                connection.execute(
                    """INSERT INTO authority_operations
                       (operation_id, action, repo_did, collection, rkey,
                        intended_json, state, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, 'prepared', ?)""",
                    (
                        operation_id,
                        action,
                        repo_did,
                        collection,
                        rkey,
                        intended,
                        now,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM authority_operations WHERE operation_id = ?",
                    (operation_id,),
                ).fetchone()
            assert row is not None
            defining = (
                row["action"],
                row["repo_did"],
                row["collection"],
                row["rkey"],
                bytes(row["intended_json"]),
            )
            expected = (action, repo_did, collection, rkey, intended)
            if defining != expected:
                raise JournalConflictError(
                    "operation id was reused for different authority input"
                )
            connection.execute("COMMIT")
            return _entry(row)

    def get(self, operation_id: str) -> JournalEntry | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM authority_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        return None if row is None else _entry(row)

    def discard_prepared(self, operation_id: str) -> bool:
        """Discard an operation that has never reached provider dispatch.

        P0 callers retain attempted_unknown on readback retry, so prepared
        means there has been no attempt for that operation.
        """
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            deleted = connection.execute(
                "DELETE FROM authority_operations WHERE operation_id=? AND state='prepared'",
                (operation_id,),
            ).rowcount
            return deleted == 1

    def transition(
        self,
        operation_id: str,
        state: OperationState,
        *,
        result_uri: str | None = None,
        result_cid: str | None = None,
        refusal_code: str | None = None,
    ) -> JournalEntry:
        if state not in _STATES:
            raise ValueError("unsupported authority operation state")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM authority_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(operation_id)
            current = str(row["state"])
            if current in _TERMINAL and current != state:
                raise JournalConflictError("terminal authority state cannot change")
            connection.execute(
                """UPDATE authority_operations
                   SET state = ?, result_uri = COALESCE(?, result_uri),
                       result_cid = COALESCE(?, result_cid),
                       refusal_code = COALESCE(?, refusal_code), updated_at = ?
                   WHERE operation_id = ?""",
                (
                    state,
                    result_uri,
                    result_cid,
                    refusal_code,
                    datetime.now(UTC).isoformat(),
                    operation_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM authority_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            connection.execute("COMMIT")
        assert updated is not None
        return _entry(updated)


def _entry(row: sqlite3.Row) -> JournalEntry:
    state = str(row["state"])
    assert state in _STATES
    return JournalEntry(
        operation_id=str(row["operation_id"]),
        action=str(row["action"]),
        repo_did=str(row["repo_did"]),
        collection=str(row["collection"]),
        rkey=str(row["rkey"]),
        intended_record=json.loads(bytes(row["intended_json"])),
        state=state,  # type: ignore[arg-type]
        result_uri=row["result_uri"],
        result_cid=row["result_cid"],
        refusal_code=row["refusal_code"],
    )


__all__ = [
    "JournalConflictError",
    "JournalEntry",
    "OperationState",
    "SQLiteOperationJournal",
]
