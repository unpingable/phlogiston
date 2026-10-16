"""Observer index runner: source -> verify -> ingest, plus resolve stage.

The ingest stage reads one bounded batch from the (verifying) event source,
starting at the durably committed cursor, and ingests each delivery in its
own atomic transaction — event variant, receipt, projection, and cursor
checkpoint commit together or not at all.  Source failures are recorded as
the source's ``last_error`` without moving its cursor.

The resolve stage performs admission-triggered start checks for pending
lifecycles and scheduled refreshes for active subjects through the
configured resolver, recording immutable observations whose ``checked_at``
feeds the existing health surface (``lastResolveAt``), exactly as ingest
receipts feed ``lastIngestAt`` and per-source cursors.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from community_model import (
    PortError,
    RecordRef,
    ResolveResult,
    ValidationError,
)

from .ports import EventSource, SubjectResolver
from .storage import ObserverStore

_ACTIVE_STATUSES = frozenset({"visible", "subject_unavailable"})


@dataclass(slots=True)
class ObserverRunner:
    """One observer pipeline: ingest and resolve stages over one store."""

    store: ObserverStore
    event_source: EventSource
    source_name: str
    resolver: SubjectResolver | None = None
    subject_refresh_seconds: int = 60
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    def run_ingest_once(self) -> int:
        """Read one batch and ingest it as one atomic transaction.

        Event variants, receipts, projection, and the final cursor commit
        together, so a crash can never strand a verified resync whose
        historical claim already checkpointed; replay stays idempotent.
        """

        cursor = self.store.source_cursor(self.source_name)
        try:
            batch = self.event_source.read(cursor)
        except (PortError, OSError, ValidationError) as exc:
            self.store.record_source_error(self.source_name, type(exc).__name__)
            return 0
        if not batch.items:
            return 0
        return len(self.store.ingest_batch(batch.items))

    def run_resolve_once(self) -> int:
        """Record observations for every due subject check; return count."""

        if self.resolver is None:
            return 0
        count = 0
        for ref, trigger in self._due_checks():
            try:
                result = self.resolver.resolve_exact(ref)
            except Exception:  # a resolver fault must not stop the stage
                result = ResolveResult(
                    status="error",
                    requested=ref,
                    current_cid=None,
                    record=None,
                    checked_at=self.now(),
                    trust_mode="verify_repo",
                    verification_outcome="unverified",
                    resolution_method="runner-guard",
                    resolver_version="1",
                )
            self.store.record_subject_observation(
                result, triggering_event_variant_key=trigger
            )
            count += 1
        return count

    def _due_checks(self) -> tuple[tuple[RecordRef, str | None], ...]:
        """Pending admission-triggered starts plus stale active subjects."""

        moment = self.now()
        horizon = moment - timedelta(seconds=self.subject_refresh_seconds)
        with self.store.read_connection() as connection:
            generation = connection.execute(
                "SELECT value FROM meta WHERE key = 'active_projection_generation'"
            ).fetchone()[0]
            lifecycle_rows = connection.execute(
                """
                SELECT admission_event_variant_key, subject_uri, subject_cid,
                       status, start_observation_key
                FROM admission_lifecycles WHERE generation_id = ?
                """,
                (generation,),
            ).fetchall()
            observation_rows = connection.execute(
                """
                SELECT v.requested_uri, v.requested_cid,
                       o.triggering_event_variant_key, o.checked_at
                FROM subject_observations AS o
                JOIN subject_observation_variants AS v
                  ON v.subject_variant_key = o.subject_variant_key
                """,
            ).fetchall()

        latest_any: dict[tuple[str, str], datetime] = {}
        latest_triggered: dict[tuple[str, str, str], datetime] = {}
        for row in observation_rows:
            ref_key = (row["requested_uri"], row["requested_cid"])
            checked_at = _parse(row["checked_at"])
            if checked_at > latest_any.get(ref_key, datetime.min.replace(tzinfo=UTC)):
                latest_any[ref_key] = checked_at
            trigger = row["triggering_event_variant_key"]
            if trigger is not None:
                triggered_key = (*ref_key, trigger)
                if checked_at > latest_triggered.get(
                    triggered_key, datetime.min.replace(tzinfo=UTC)
                ):
                    latest_triggered[triggered_key] = checked_at

        due: dict[tuple[str, str, str | None], None] = {}
        for row in lifecycle_rows:
            ref_key = (row["subject_uri"], row["subject_cid"])
            if row["start_observation_key"] is None and row["status"] == "pending":
                trigger = row["admission_event_variant_key"]
                checked = latest_triggered.get((*ref_key, trigger))
                if checked is None or checked <= horizon:
                    due[(*ref_key, trigger)] = None
            if row["status"] in _ACTIVE_STATUSES:
                checked = latest_any.get(ref_key)
                if checked is None or checked <= horizon:
                    due[(*ref_key, None)] = None
        return tuple(
            (RecordRef(uri=uri, cid=cid), trigger) for uri, cid, trigger in sorted(due)
        )


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


__all__ = ["ObserverRunner"]
