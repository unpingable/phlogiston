"""V0-M4 SQLite, ingestion, and rebuild hardening tests (TEST-PLAN).

Covers the "SQLite, ingestion, and rebuild tests" section of
``docs/TEST-PLAN.md``: quarantine and cursor atomicity, trust-policy
eligibility, receipt/observation provenance, crash and busy backpressure
through the store's failure-injection seams, immutable-custody boundaries,
projection-generation gating, rebuild equivalence, and concurrent
read/write behavior.
"""

from __future__ import annotations

import base64
import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from community_model import (
    ADMISSION_COLLECTION,
    POST_COLLECTION,
    SUBMISSION_COLLECTION,
    IncomingDelivery,
    RecordRef,
    ResolveResult,
    ValidationError,
    admission_rkey,
    canonical_json_bytes,
    cid_for_dag_cbor,
)
from communitywatch import ObserverStore, ProjectionQuery, ProjectionUnavailableError

COMMUNITY_DID = "did:web:community.invalid"
ADMIN_DID = "did:web:admin.invalid"
ALICE_DID = "did:web:alice.invalid"
T0 = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)
SIGNED_PAST = "2026-08-14T11:00:00Z"
_TID_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"


def _tid(sequence: int) -> str:
    digits = ""
    value = sequence
    while True:
        digits = _TID_ALPHABET[value % 32] + digits
        value //= 32
        if not value:
            break
    return digits.rjust(13, "2")


def _cid(record: dict[str, object]) -> str:
    return cid_for_dag_cbor(canonical_json_bytes(record))


def _subject() -> RecordRef:
    post = {"$type": POST_COLLECTION, "text": "hello", "createdAt": SIGNED_PAST}
    return RecordRef(
        uri=f"at://{ALICE_DID}/{POST_COLLECTION}/3jzfcijpj2z2a", cid=_cid(post)
    )


def _submission_record(subject: RecordRef) -> dict[str, object]:
    return {
        "$type": SUBMISSION_COLLECTION,
        "community": COMMUNITY_DID,
        "subject": subject.as_dict(),
        "createdAt": SIGNED_PAST,
    }


def _submission_delivery(
    subject: RecordRef,
    *,
    cursor: str,
    rev: str,
    source: str = "relay-a",
    outcome: str = "verified",
    received_at: datetime = T0,
    trust_mode: str = "test_fixture",
    method: str = "fixture",
    version: str = "1",
    evidence_ref: str | None = None,
    evidence_hash: str | None = None,
) -> IncomingDelivery:
    record = _submission_record(subject)
    return IncomingDelivery(
        source=source,
        cursor=cursor,
        source_event_time=received_at,
        received_at=received_at,
        raw_envelope={
            "repo": ALICE_DID,
            "rev": rev,
            "operation": "create",
            "collection": SUBMISSION_COLLECTION,
            "rkey": "3jzfcijpj2z2k",
            "cid": _cid(record),
            "record": record,
        },
        trust_mode=trust_mode,
        verification_outcome=outcome,
        verification_method=method,
        verifier_version=version,
        evidence_ref=evidence_ref,
        evidence_hash=evidence_hash,
    )


def _admission_delivery(
    subject: RecordRef,
    *,
    cursor: str,
    rev: str,
    outcome: str = "verified",
    received_at: datetime = T0,
) -> IncomingDelivery:
    submission_record = _submission_record(subject)
    submission = RecordRef(
        uri=f"at://{ALICE_DID}/{SUBMISSION_COLLECTION}/3jzfcijpj2z2k",
        cid=_cid(submission_record),
    )
    record = {
        "$type": ADMISSION_COLLECTION,
        "submission": submission.as_dict(),
        "subject": subject.as_dict(),
        "actor": ADMIN_DID,
        "createdAt": SIGNED_PAST,
    }
    return IncomingDelivery(
        source="relay-a",
        cursor=cursor,
        source_event_time=received_at,
        received_at=received_at,
        raw_envelope={
            "repo": COMMUNITY_DID,
            "rev": rev,
            "operation": "create",
            "collection": ADMISSION_COLLECTION,
            "rkey": admission_rkey(submission),
            "cid": _cid(record),
            "record": record,
        },
        trust_mode="test_fixture",
        verification_outcome=outcome,
        verification_method="fixture",
        verifier_version="1",
    )


def _observation(
    subject: RecordRef,
    status: str,
    *,
    outcome: str = "verified",
    trust_mode: str = "test_fixture",
    method: str = "fixture",
    version: str = "1",
    evidence_ref: str | None = None,
    evidence_hash: str | None = None,
    checked_at: datetime = T0,
) -> ResolveResult:
    if status == "exact":
        current_cid: str | None = subject.cid
        record: dict[str, object] | None = {
            "$type": POST_COLLECTION,
            "text": "hello",
            "createdAt": SIGNED_PAST,
        }
    elif status == "mismatch":
        current_cid = _cid({"$type": POST_COLLECTION, "text": "changed"})
        record = None
    else:
        current_cid = None
        record = None
    return ResolveResult(
        status=status,
        requested=subject,
        current_cid=current_cid,
        record=record,
        checked_at=checked_at,
        trust_mode=trust_mode,
        verification_outcome=outcome,
        resolution_method=method,
        resolver_version=version,
        evidence_ref=evidence_ref,
        evidence_hash=evidence_hash,
    )


def _store(path: Path, **kwargs: object) -> ObserverStore:
    return ObserverStore(
        path / "observer.sqlite3",
        community_did=COMMUNITY_DID,
        administrator_did=ADMIN_DID,
        **kwargs,
    )


# --- construction and connection discipline ----------------------------------


def test_busy_timeout_bounds_are_validated(tmp_path: Path) -> None:
    for bad in (0, -1, 60_001, True, 1.5, "100"):
        with pytest.raises(ValueError, match="busy_timeout_ms"):
            _store(tmp_path / str(bad), busy_timeout_ms=bad)
    store = _store(tmp_path / "ok", busy_timeout_ms=1)
    assert store.busy_timeout_ms == 1


def test_schema_metadata_disagreement_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")
    with pytest.raises(ValidationError) as captured:
        _store(tmp_path)
    assert captured.value.reason_code == "schema_incompatible"


def test_read_connections_are_query_only_for_every_table(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.ingest(_submission_delivery(_subject(), cursor="1", rev=_tid(1)))
    with store.read_connection() as connection:
        for table in (
            "repo_events",
            "event_receipts",
            "quarantined_deliveries",
            "subject_observations",
            "audit_index",
        ):
            with pytest.raises(sqlite3.OperationalError):
                connection.execute(f"DELETE FROM {table}")  # noqa: S608


def test_application_surface_exposes_no_mutation_of_immutable_custody(
    tmp_path: Path,
) -> None:
    public = {
        name
        for name, value in vars(ObserverStore).items()
        if not name.startswith("_") and callable(value)
    }
    assert public == {
        "ingest",
        "ingest_batch",
        "ingest_many",
        "record_subject_observation",
        "rebuild",
        "projection_snapshot",
        "counts",
        "read_connection",
        # M6: committed-cursor lookup (read-only) and operational source
        # error notes (ingest_sources is an operational control table, not
        # immutable custody).
        "source_cursor",
        "record_source_error",
    }


# --- quarantine and cursor atomicity -----------------------------------------


def test_missing_revision_is_quarantined_and_checkpointed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    subject = _subject()
    admission = _admission_delivery(subject, cursor="7", rev=_tid(1))
    envelope = dict(admission.raw_envelope)
    del envelope["rev"]
    result = store.ingest(
        IncomingDelivery(
            source=admission.source,
            cursor=admission.cursor,
            source_event_time=admission.source_event_time,
            received_at=admission.received_at,
            raw_envelope=envelope,
            trust_mode=admission.trust_mode,
            verification_outcome=admission.verification_outcome,
            verification_method=admission.verification_method,
            verifier_version=admission.verifier_version,
        )
    )
    assert result.kind == "quarantine"
    # The source cursor advanced atomically with the quarantine, and the
    # malformed authority-shaped bytes had no authority effect.
    with store.read_connection() as connection:
        cursor = connection.execute(
            "SELECT committed_cursor FROM ingest_sources WHERE source = 'relay-a'"
        ).fetchone()[0]
    assert cursor == "7"
    assert store.counts()["repo_events"] == 0
    assert store.projection_snapshot()["admission_lifecycles"] == []


def test_quarantine_audit_rows_have_stable_keys_and_null_identity(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    bad = store.ingest(
        IncomingDelivery(
            source="relay-a",
            cursor="1",
            source_event_time=T0,
            received_at=T0,
            raw_envelope=b'{"not": "an event"}',
            trust_mode="test_fixture",
            verification_outcome="verified",
            verification_method="fixture",
            verifier_version="1",
        )
    )
    store.ingest(_submission_delivery(_subject(), cursor="2", rev=_tid(1)))
    query = ProjectionQuery(store, slug="test")

    seen = []
    cursor = None
    while True:
        page = query.list_audit(COMMUNITY_DID, 1, cursor)
        seen.extend(page.items)
        cursor = page.cursor
        if cursor is None:
            break
        # Opaque cursors carry receipt time plus row key only: no rowid.
        decoded = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        assert set(decoded) == {"receivedAt", "rowKey"}
    assert len(seen) == 2
    (row,) = [item for item in seen if item["kind"] == "quarantine"]
    assert row["auditRowKey"] == bad.key
    assert row["auditRowKey"].startswith("quarantine:")
    assert len(str(row["auditRowKey"]).removeprefix("quarantine:")) == 64
    assert row["semanticEventKey"] is None
    assert row["eventVariantKey"] is None
    assert row["record"] is None
    assert row["outcome"] == "invalid"
    assert tuple(row["reasonCodes"]) == ("schema_invalid",)
    assert str(row["payloadHash"]).startswith("sha256:")


# --- trust policy and provenance ---------------------------------------------


def test_failed_delivery_is_ineligible_and_cannot_suppress_verified(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    subject = _subject()
    store.ingest(_submission_delivery(subject, cursor="1", rev=_tid(1)))
    # Same semantic identity, different payload, failed verification: the
    # unverified testimony cannot suppress or conflict the verified event.
    changed = _submission_record(subject) | {"createdAt": "2026-08-14T11:00:01Z"}
    store.ingest(
        IncomingDelivery(
            source="relay-a",
            cursor="2",
            source_event_time=T0,
            received_at=T0,
            raw_envelope={
                "repo": ALICE_DID,
                "rev": _tid(1),
                "operation": "create",
                "collection": SUBMISSION_COLLECTION,
                "rkey": "3jzfcijpj2z2k",
                "cid": _cid(changed),
                "record": changed,
            },
            trust_mode="test_fixture",
            verification_outcome="failed",
            verification_method="fixture",
            verifier_version="1",
        )
    )
    snapshot = store.projection_snapshot()
    ledger = snapshot["ledger_records"]
    assert isinstance(ledger, list)
    assert {row["outcome"] for row in ledger} == {"valid", "unauthorized"}
    failed = next(row for row in ledger if row["outcome"] == "unauthorized")
    assert failed["reason_codes"] == ["authenticity_failed"]
    assert not any(
        row["reason_code"] == "semantic_event_conflict"
        for row in snapshot["projection_findings"]  # type: ignore[index]
    )


def test_trust_policy_selects_eligible_delivery_outcomes(tmp_path: Path) -> None:
    subject = _subject()
    default = _store(tmp_path / "default")
    default.ingest(
        _submission_delivery(subject, cursor="1", rev=_tid(1), outcome="attested")
    )
    ledger = default.projection_snapshot()["ledger_records"]
    assert ledger[0]["outcome"] == "unauthorized"  # type: ignore[index]
    assert ledger[0]["reason_codes"] == ["authenticity_unverified"]  # type: ignore[index]

    attesting = _store(
        tmp_path / "attesting",
        accepted_delivery_outcomes=("verified", "attested"),
    )
    attesting.ingest(
        _submission_delivery(subject, cursor="1", rev=_tid(1), outcome="attested")
    )
    ledger = attesting.projection_snapshot()["ledger_records"]
    assert ledger[0]["outcome"] == "valid"  # type: ignore[index]


def test_trust_policy_selects_eligible_resolution_outcomes(tmp_path: Path) -> None:
    subject = _subject()
    for label, accepted, expected in (
        ("default", ("verified",), "pending"),
        ("attesting", ("attested",), "visible"),
    ):
        store = _store(tmp_path / label, accepted_resolution_outcomes=accepted)
        store.ingest(_submission_delivery(subject, cursor="1", rev=_tid(1)))
        admission = store.ingest(_admission_delivery(subject, cursor="2", rev=_tid(1)))
        store.record_subject_observation(
            _observation(subject, "exact", outcome="attested"),
            triggering_event_variant_key=admission.key,
        )
        entries = store.projection_snapshot()["community_entries"]
        assert entries[0]["status"] == expected, label  # type: ignore[index]


def test_two_sources_retain_full_receipt_provenance_and_ordering(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    subject = _subject()
    later_time = T0 + timedelta(minutes=3)
    earlier_time = T0 + timedelta(minutes=1)
    first = store.ingest(
        _submission_delivery(
            subject,
            cursor="1",
            rev=_tid(1),
            source="relay-a",
            received_at=later_time,
            trust_mode="verify_repo",
            method="repo-commit-proof",
            version="2",
            evidence_ref="evidence:a",
            evidence_hash="sha256:" + "0" * 64,
        )
    )
    # A later-arriving receipt from a second source with an earlier receipt
    # time must not bump audit ordering or identity.
    second = store.ingest(
        _submission_delivery(
            subject,
            cursor="9",
            rev=_tid(1),
            source="relay-b",
            received_at=earlier_time,
            trust_mode="trust_relay",
            method="relay-attestation",
            version="7",
            evidence_ref="evidence:b",
            evidence_hash="sha256:" + "1" * 64,
        )
    )
    assert first.key == second.key
    with store.read_connection() as connection:
        receipts = connection.execute(
            """
            SELECT source, cursor, trust_mode, verification_method,
                   verifier_version, evidence_ref, evidence_hash, received_at,
                   observer_sequence
            FROM event_receipts ORDER BY observer_sequence
            """
        ).fetchall()
    assert [tuple(row) for row in receipts] == [
        (
            "relay-a",
            "1",
            "verify_repo",
            "repo-commit-proof",
            "2",
            "evidence:a",
            "sha256:" + "0" * 64,
            "2026-08-14T12:03:00Z",
            1,
        ),
        (
            "relay-b",
            "9",
            "trust_relay",
            "relay-attestation",
            "7",
            "evidence:b",
            "sha256:" + "1" * 64,
            "2026-08-14T12:01:00Z",
            2,
        ),
    ]
    (row,) = [
        item
        for item in store.projection_snapshot()["audit_index"]  # type: ignore[index]
        if item["kind"] == "submission"
    ]
    assert row["receipt_count"] == 2
    assert row["observer_sequence"] == 1
    assert row["first_received_at"] == "2026-08-14T12:01:00+00:00"


def test_subject_observation_provenance_is_preserved_without_relabeling(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    subject = _subject()
    cases = (
        ("exact", "verified", "verify_repo", "repo-proof", "1"),
        ("mismatch", "attested", "trust_pds", "pds-resolution", "2"),
        ("missing", "unverified", "test_fixture", "fixture", "3"),
        ("error", "failed", "verify_repo", "repo-proof", "4"),
    )
    for index, (status, outcome, trust_mode, method, version) in enumerate(cases):
        store.record_subject_observation(
            _observation(
                subject,
                status,
                outcome=outcome,
                trust_mode=trust_mode,
                method=method,
                version=version,
                evidence_ref=f"evidence:{index}",
                evidence_hash="sha256:" + "abcd"[index] * 64,
                checked_at=T0 + timedelta(minutes=index),
            )
        )
    with store.read_connection() as connection:
        rows = connection.execute(
            """
            SELECT trust_mode, verification_outcome, resolution_method,
                   resolver_version, evidence_ref, evidence_hash
            FROM subject_observations ORDER BY observer_sequence
            """
        ).fetchall()
    assert [tuple(row) for row in rows] == [
        (
            trust_mode,
            outcome,
            method,
            version,
            f"evidence:{index}",
            "sha256:" + "abcd"[index] * 64,
        )
        for index, (_, outcome, trust_mode, method, version) in enumerate(cases)
    ]
    observations = [
        row
        for row in store.projection_snapshot()["audit_index"]  # type: ignore[index]
        if row["kind"] == "subject_observation"
    ]
    assert sorted(row["verification_outcomes"] for row in observations) == sorted(
        [outcome] for _, outcome, _, _, _ in cases
    )


# --- crash and queue-pressure seams ------------------------------------------


def test_observation_crash_rolls_back_and_never_flashes_visible(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    subject = _subject()
    store.ingest(_submission_delivery(subject, cursor="1", rev=_tid(1)))
    admission = store.ingest(_admission_delivery(subject, cursor="2", rev=_tid(1)))

    # The crash lands after resolver I/O but before the observation commits.
    with pytest.raises(RuntimeError, match="injected failure"):
        store.record_subject_observation(
            _observation(subject, "exact"),
            triggering_event_variant_key=admission.key,
            fail_before_commit=True,
        )
    assert store.counts()["subject_observations"] == 0
    entries = store.projection_snapshot()["community_entries"]
    assert entries[0]["status"] == "pending"  # type: ignore[index]
    assert (
        ProjectionQuery(store, slug="test").list_visible(COMMUNITY_DID, 100, None).items
        == ()
    )

    # A restarted process repeats the check; the rolled-back attempt consumed
    # no observer sequence and nothing was skipped or double-applied.
    reopened = _store(tmp_path)
    key = reopened.record_subject_observation(
        _observation(subject, "exact"),
        triggering_event_variant_key=admission.key,
    )
    assert isinstance(key, str)
    entries = reopened.projection_snapshot()["community_entries"]
    assert entries[0]["status"] == "visible"  # type: ignore[index]
    with reopened.read_connection() as connection:
        sequences = [
            row[0]
            for row in connection.execute(
                """
                SELECT observer_sequence FROM event_receipts
                UNION ALL
                SELECT observer_sequence FROM subject_observations
                ORDER BY observer_sequence
                """
            )
        ]
    assert sequences == [1, 2, 3]


def test_busy_database_applies_backpressure_without_dropping(tmp_path: Path) -> None:
    store = _store(tmp_path, busy_timeout_ms=1)
    subject = _subject()
    holder = sqlite3.connect(store.path)
    try:
        holder.execute("BEGIN IMMEDIATE")
        holder.execute(
            "INSERT INTO ingest_sources(source, committed_cursor) VALUES ('x', '0')"
        )
        # Queue pressure: the writer cannot acquire the database inside its
        # bounded busy timeout, so the delivery fails loudly instead of being
        # dropped or checkpointed.
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            store.ingest(_submission_delivery(subject, cursor="1", rev=_tid(1)))
    finally:
        holder.rollback()
        holder.close()
    assert store.counts()["repo_events"] == 0
    with store.read_connection() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM ingest_sources WHERE source = 'relay-a'"
            ).fetchone()[0]
            == 0
        )
    # After the pressure clears the same delivery ingests cleanly.
    result = store.ingest(_submission_delivery(subject, cursor="1", rev=_tid(1)))
    assert result.kind == "event"
    assert result.observer_sequence == 1


def test_restart_after_failed_batch_replays_exactly(tmp_path: Path) -> None:
    subject = _subject()
    deliveries = (
        _submission_delivery(subject, cursor="1", rev=_tid(1)),
        _admission_delivery(subject, cursor="2", rev=_tid(1)),
    )
    crashed = _store(tmp_path / "crashed")
    with pytest.raises(RuntimeError, match="injected failure"):
        crashed.ingest_batch(deliveries, fail_before_commit=True)
    assert crashed.counts()["repo_events"] == 0

    reopened = _store(tmp_path / "crashed")
    results = reopened.ingest_batch(deliveries)
    assert [result.observer_sequence for result in results] == [1, 2]

    clean = _store(tmp_path / "clean")
    clean.ingest_batch(deliveries)
    assert reopened.projection_snapshot() == clean.projection_snapshot()
    assert reopened.counts() == clean.counts()


# --- identity, rebuild, and generation gating ---------------------------------


def test_semantic_identity_ignores_arrival_order_time_and_source(
    tmp_path: Path,
) -> None:
    subject = _subject()
    first = _submission_delivery(subject, cursor="1", rev=_tid(1), received_at=T0)
    second = _admission_delivery(
        subject, cursor="2", rev=_tid(1), received_at=T0 + timedelta(minutes=1)
    )

    def keys(store: ObserverStore) -> set[tuple[str, str]]:
        with store.read_connection() as connection:
            return {
                (row[0], row[1])
                for row in connection.execute(
                    "SELECT semantic_event_key, event_variant_key FROM repo_events"
                )
            }

    in_order = _store(tmp_path / "in-order")
    in_order.ingest(first)
    in_order.ingest(second)
    shuffled = _store(tmp_path / "shuffled")
    shuffled.ingest(second)
    shuffled.ingest(first)
    replayed = _store(tmp_path / "replayed")
    replayed.ingest(
        _submission_delivery(
            subject,
            cursor="9",
            rev=_tid(1),
            source="relay-b",
            received_at=T0 + timedelta(hours=2),
        )
    )
    assert keys(in_order) == keys(shuffled)
    # Source replay at a different arrival time lands on the same variant.
    assert len(keys(replayed)) == 1
    assert keys(replayed) <= keys(in_order)


def test_rebuild_is_content_equivalent_with_hostile_history(tmp_path: Path) -> None:
    store = _store(tmp_path)
    subject = _subject()
    store.ingest(_submission_delivery(subject, cursor="1", rev=_tid(1)))
    admission = store.ingest(_admission_delivery(subject, cursor="2", rev=_tid(1)))
    store.record_subject_observation(
        _observation(subject, "exact"),
        triggering_event_variant_key=admission.key,
    )
    # Add one quarantine and one accepted semantic conflict to the history.
    store.ingest(
        IncomingDelivery(
            source="relay-a",
            cursor="3",
            source_event_time=T0,
            received_at=T0,
            raw_envelope=b"garbage",
            trust_mode="test_fixture",
            verification_outcome="verified",
            verification_method="fixture",
            verifier_version="1",
        )
    )
    changed = _submission_record(subject) | {"createdAt": "2026-08-14T11:00:01Z"}
    store.ingest(
        IncomingDelivery(
            source="relay-a",
            cursor="4",
            source_event_time=T0,
            received_at=T0,
            raw_envelope={
                "repo": ALICE_DID,
                "rev": _tid(1),
                "operation": "create",
                "collection": SUBMISSION_COLLECTION,
                "rkey": "3jzfcijpj2z2k",
                "cid": _cid(changed),
                "record": changed,
            },
            trust_mode="test_fixture",
            verification_outcome="verified",
            verification_method="fixture",
            verifier_version="1",
        )
    )
    before = store.projection_snapshot()
    assert store.rebuild() == "g2"
    assert store.projection_snapshot() == before
    assert store.rebuild() == "g3"
    assert store.projection_snapshot() == before


def test_projection_gating_rejects_failed_incompatible_and_missing_generations(
    tmp_path: Path,
) -> None:
    for label, statement, reason in (
        (
            "failed",
            "UPDATE projection_builds SET status = 'failed'",
            "projection_incomplete",
        ),
        (
            "reducer",
            "UPDATE projection_builds SET reducer_version = 'other'",
            "schema_incompatible",
        ),
        (
            "schema",
            "UPDATE projection_builds SET schema_version = 999",
            "schema_incompatible",
        ),
        (
            "missing",
            "UPDATE meta SET value = 'g99' WHERE key = 'active_projection_generation'",
            "projection_incomplete",
        ),
    ):
        store = _store(tmp_path / label)
        with sqlite3.connect(store.path) as connection:
            connection.execute(statement)
        query = ProjectionQuery(store, slug="test")
        with pytest.raises(ProjectionUnavailableError) as captured:
            query.list_audit(COMMUNITY_DID, 50, None)
        assert captured.value.reason_code == reason, label


def test_concurrent_ingest_and_readonly_queries_see_complete_generations(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    query = ProjectionQuery(store, slug="test")
    subject = _subject()
    store.ingest(_submission_delivery(subject, cursor="1", rev=_tid(1)))
    errors: list[Exception] = []
    done = threading.Event()

    def reader() -> None:
        while not done.is_set():
            try:
                query.list_visible(COMMUNITY_DID, 50, None)
                query.list_audit(COMMUNITY_DID, 50, None)
                query.community_identity(COMMUNITY_DID)
            except Exception as exc:  # noqa: BLE001 - collected and asserted
                errors.append(exc)

    thread = threading.Thread(target=reader)
    thread.start()
    try:
        for index in range(2, 12):
            store.ingest(
                _submission_delivery(
                    subject,
                    cursor=str(index),
                    rev=_tid(index),
                )
            )
    finally:
        done.set()
        thread.join()
    assert errors == []
    assert store.counts()["event_receipts"] == 11
