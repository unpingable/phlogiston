from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from community_model import (
    ADMISSION_COLLECTION,
    REPLY_POLICY_COLLECTION,
    SUBMISSION_COLLECTION,
    RecordRef,
    ValidationError,
)


@dataclass(frozen=True, slots=True)
class ReplyCandidate:
    submission: RecordRef
    subject: RecordRef
    root_admission: RecordRef
    reply_policy: RecordRef

    def __post_init__(self) -> None:
        if self.submission.collection != SUBMISSION_COLLECTION:
            raise ValidationError(
                "schema_invalid", "candidate submission collection is invalid"
            )
        if self.subject.collection != "app.bsky.feed.post":
            raise ValidationError(
                "schema_invalid", "candidate subject collection is invalid"
            )
        if self.root_admission.collection != ADMISSION_COLLECTION:
            raise ValidationError(
                "schema_invalid", "candidate root admission collection is invalid"
            )
        if self.reply_policy.collection != REPLY_POLICY_COLLECTION:
            raise ValidationError(
                "schema_invalid", "candidate reply policy collection is invalid"
            )

    def request(self) -> dict[str, object]:
        return {
            "operationId": operation_id(self),
            "action": "reply_admit",
            "target": self.submission.as_dict(),
            "rootAdmission": self.root_admission.as_dict(),
            "replyPolicy": self.reply_policy.as_dict(),
        }


class CandidateSource(Protocol):
    def fetch(self, community_did: str) -> tuple[ReplyCandidate, ...]: ...


class AuthorityClient(Protocol):
    def send(self, request: Mapping[str, object]) -> Mapping[str, object]: ...


def operation_id(candidate: ReplyCandidate) -> str:
    fields = (
        "pcv0",
        candidate.submission.uri,
        candidate.submission.cid,
        candidate.root_admission.uri,
        candidate.root_admission.cid,
        candidate.reply_policy.uri,
        candidate.reply_policy.cid,
    )
    return (
        "policy-reply-admit-" + hashlib.sha256("\0".join(fields).encode()).hexdigest()
    )


class PolicyState:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS policy_operations (
                operation_id TEXT PRIMARY KEY, request_json TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('prepared','attempted_unknown','committed','refused')),
                result_json TEXT
            )""")

    def prepare(self, candidate: ReplyCandidate) -> str:
        request = candidate.request()
        operation = str(request["operationId"])
        encoded = json.dumps(request, sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            row = connection.execute(
                "SELECT request_json FROM policy_operations WHERE operation_id = ?",
                (operation,),
            ).fetchone()
            if row is not None and row[0] != encoded:
                raise ValidationError(
                    "immutable_conflict", "operation identity changed payload"
                )
            connection.execute(
                "INSERT OR IGNORE INTO policy_operations(operation_id,request_json,state) VALUES(?,?,'prepared')",
                (operation, encoded),
            )
        return operation

    def pending(self) -> tuple[dict[str, object], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT request_json FROM policy_operations WHERE state IN ('prepared','attempted_unknown') ORDER BY operation_id"
            ).fetchall()
        return tuple(json.loads(row[0]) for row in rows)

    def mark_attempted(self, operation: str) -> None:
        self._set(operation, "attempted_unknown", None)

    def finish(self, operation: str, state: str, result: Mapping[str, object]) -> None:
        self._set(
            operation, state, json.dumps(result, sort_keys=True, separators=(",", ":"))
        )

    def state(self, operation: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state FROM policy_operations WHERE operation_id = ?",
                (operation,),
            ).fetchone()
        return None if row is None else str(row[0])

    def _set(self, operation: str, state: str, result: str | None) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE policy_operations SET state = ?, result_json = ? WHERE operation_id = ?",
                (state, result, operation),
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)


class PolicyWorker:
    def __init__(
        self,
        community_did: str,
        source: CandidateSource,
        authority: AuthorityClient,
        state: PolicyState,
    ) -> None:
        self.community_did = community_did
        self.source = source
        self.authority = authority
        self.state = state

    def run_once(self) -> dict[str, int]:
        already_pending = self.state.pending()
        try:
            candidates = self.source.fetch(self.community_did)
        except OSError:
            # Durable ambiguous writes remain retryable during observer downtime.
            if not already_pending:
                raise
            candidates = ()
        for candidate in candidates:
            self.state.prepare(candidate)
        counts = {
            "candidates": len(candidates),
            "committed": 0,
            "refused": 0,
            "pending": 0,
        }
        for request in self.state.pending():
            operation = str(request["operationId"])
            self.state.mark_attempted(operation)
            try:
                response = self.authority.send(request)
            except (OSError, TimeoutError):
                counts["pending"] += 1
                continue
            if response.get("ok") is True:
                self.state.finish(operation, "committed", response)
                counts["committed"] += 1
            elif response.get("error") == "authority_unavailable":
                counts["pending"] += 1
            else:
                self.state.finish(operation, "refused", response)
                counts["refused"] += 1
        return counts
