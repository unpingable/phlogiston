"""SA10b durable, observer-only evidence ledger; no scheduler or transport."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from community_model import ValidationError

from .compat import SA10B_SYNC_STORE_DOCTRINE, SA10B_SYNC_STORE_VERSION
from .reconciliation import ReconciliationDisposition, ReconciliationResult
from .recovery import RecoveryDecisionTrace, RecoveryOutcome
from .transition import TransitionStateIdentity

_SECRET_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "accesstoken",
    "rawaccesstoken",
    "privatekey",
    "dpopproof",
    "refreshtoken",
}


def _fail(reason: str, message: str) -> None:
    raise ValidationError(reason, message)


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


def _canonical(value: object) -> str:
    return json.dumps(
        _plain(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _check_no_secrets(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in _SECRET_KEYS and item not in {None, False, ""}:
                _fail(
                    "spaces_sync_secret_refused",
                    "secret-bearing field cannot be persisted",
                )
            _check_no_secrets(item)
    elif isinstance(value, list | tuple):
        for item in value:
            _check_no_secrets(item)


def _repo_key(state: TransitionStateIdentity) -> str:
    return hashlib.sha256(f"{state.space.uri}\0{state.author_did}".encode()).hexdigest()


def _state_key(state: TransitionStateIdentity) -> str:
    return hashlib.sha256(_canonical(dict(state.to_provenance())).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class DurableHead:
    repo_key: str
    state_key: str
    state: Mapping[str, object]
    establishing_event_id: str


class DurableSyncStore:
    def __init__(self, path: str | Path) -> None:
        self._db = sqlite3.connect(str(path))
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript("""
        CREATE TABLE IF NOT EXISTS sync_events(event_id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,payload_sha256 TEXT NOT NULL,observed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS repo_heads(repo_key TEXT PRIMARY KEY,state_key TEXT NOT NULL,state_payload TEXT NOT NULL,establishing_event_id TEXT NOT NULL REFERENCES sync_events(event_id));
        """)
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def _event(
        self, kind: str, payload: Mapping[str, object], observed_at: datetime
    ) -> str:
        if observed_at.utcoffset() is None:
            _fail("spaces_sync_time_invalid", "time must be aware")
        _check_no_secrets(payload)
        encoded = _canonical(payload)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        event_id = (
            "sha256:"
            + hashlib.sha256(
                f"{SA10B_SYNC_STORE_VERSION}\0{kind}\0{digest}".encode()
            ).hexdigest()
        )
        self._db.execute(
            "INSERT OR IGNORE INTO sync_events VALUES(?,?,?,?,?)",
            (event_id, kind, encoded, digest, observed_at.astimezone(UTC).isoformat()),
        )
        self._db.commit()
        return event_id

    def seed_qualified_state(
        self, state: TransitionStateIdentity, *, custody_ref: str, observed_at: datetime
    ) -> str:
        payload = {
            "state": dict(state.to_provenance()),
            "custodyRef": custody_ref,
            "doctrine": SA10B_SYNC_STORE_DOCTRINE,
            "claimsUpgraded": False,
        }
        event = self._event("qualified_state_seed", payload, observed_at)
        repo = _repo_key(state)
        key = _state_key(state)
        existing = self._db.execute(
            "SELECT state_key FROM repo_heads WHERE repo_key=?", (repo,)
        ).fetchone()
        if existing and existing[0] != key:
            _fail(
                "spaces_sync_seed_conflict",
                "different state cannot replace an established head by seeding",
            )
        self._db.execute(
            "INSERT OR IGNORE INTO repo_heads VALUES(?,?,?,?)",
            (repo, key, _canonical(dict(state.to_provenance())), event),
        )
        self._db.commit()
        return event

    def record_acquisition(
        self,
        receipt_id: str,
        provenance: Mapping[str, object],
        *,
        observed_at: datetime,
    ) -> str:
        return self._event(
            "acquisition_attempt",
            {
                "receiptId": receipt_id,
                "provenance": dict(provenance),
                "authority": False,
                "currentness": False,
            },
            observed_at,
        )

    def record_cursor(
        self,
        repo: TransitionStateIdentity,
        cursor: str | None,
        *,
        source_ref: str,
        observed_at: datetime,
    ) -> str:
        return self._event(
            "cursor_observation",
            {
                "repoKey": _repo_key(repo),
                "cursor": cursor,
                "sourceRef": source_ref,
                "completeHistory": False,
            },
            observed_at,
        )

    def record_reconciliation(self, result: ReconciliationResult) -> str:
        payload = dict(result.to_provenance())
        payload["claimsUpgraded"] = False
        event = self._event("reconciliation", payload, result.reconciled_at)
        if result.disposition in {
            ReconciliationDisposition.QUALIFIED_TRANSITION,
            ReconciliationDisposition.SNAPSHOT_ONLY,
        }:
            repo = _repo_key(result.observed_state)
            state = _state_key(result.observed_state)
            self._db.execute(
                "INSERT INTO repo_heads VALUES(?,?,?,?) ON CONFLICT(repo_key) DO UPDATE SET state_key=excluded.state_key,state_payload=excluded.state_payload,establishing_event_id=excluded.establishing_event_id",
                (
                    repo,
                    state,
                    _canonical(dict(result.observed_state.to_provenance())),
                    event,
                ),
            )
            self._db.commit()
        return event

    def record_recovery(
        self,
        trace_provenance: Mapping[str, object],
        *,
        trace_id: str,
        observed_at: datetime,
    ) -> str:
        return self._event(
            "recovery_trace",
            {
                "traceId": trace_id,
                "trace": dict(trace_provenance),
                "missingProvenancePreserved": True,
            },
            observed_at,
        )

    def apply_qualified_recovery(self, trace: RecoveryDecisionTrace) -> str:
        """Persist one SA8 trace and advance only from its qualified outcome."""

        if not isinstance(trace, RecoveryDecisionTrace):
            _fail("spaces_sync_recovery_invalid", "an SA8 recovery trace is required")
        event = self.record_recovery(
            trace.to_provenance(),
            trace_id=trace.trace_id,
            observed_at=trace.decided_at,
        )
        if trace.outcome not in {
            RecoveryOutcome.QUALIFIED_TRANSITION,
            RecoveryOutcome.SNAPSHOT_ONLY,
        }:
            return event
        if trace.observed_state is None:
            _fail(
                "spaces_sync_recovery_invalid",
                "qualified recovery has no observed state identity",
            )
        repo = _repo_key(trace.observed_state)
        state = _state_key(trace.observed_state)
        self._db.execute(
            "INSERT INTO repo_heads VALUES(?,?,?,?) ON CONFLICT(repo_key) DO UPDATE SET state_key=excluded.state_key,state_payload=excluded.state_payload,establishing_event_id=excluded.establishing_event_id",
            (
                repo,
                state,
                _canonical(dict(trace.observed_state.to_provenance())),
                event,
            ),
        )
        self._db.commit()
        return event

    def head(self, state: TransitionStateIdentity) -> DurableHead | None:
        row = self._db.execute(
            "SELECT state_key,state_payload,establishing_event_id FROM repo_heads WHERE repo_key=?",
            (_repo_key(state),),
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[1])
        return DurableHead(_repo_key(state), row[0], payload, row[2])

    def event_count(self) -> int:
        return int(self._db.execute("SELECT count(*) FROM sync_events").fetchone()[0])


__all__ = ["DurableHead", "DurableSyncStore"]
