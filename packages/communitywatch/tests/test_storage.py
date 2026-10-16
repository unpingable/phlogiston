from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from community_model import IncomingDelivery, RecordRef, ResolveResult, ValidationError
from communitywatch import ObserverStore

FIXTURES = Path(__file__).parents[3] / "tests" / "fixtures" / "v0"
COMMUNITY_DID = "did:web:community.invalid"
ADMIN_DID = "did:web:admin.invalid"
BASE_TIME = datetime(2026, 7, 10, 14, 2, 1, tzinfo=UTC)


def _manifest() -> dict[str, object]:
    with (FIXTURES / "record-vectors.json").open(encoding="utf-8") as handle:
        value = json.load(handle)
    assert isinstance(value, dict)
    return value


def _vector(name: str) -> dict[str, object]:
    records = _manifest()["records"]
    assert isinstance(records, list)
    result = next(item for item in records if item["name"] == name)
    assert isinstance(result, dict)
    return result


def _record(name: str) -> dict[str, object]:
    filename = "mod-action.json" if name == "mod_action" else f"{name}.json"
    with (FIXTURES / "records" / filename).open(encoding="utf-8") as handle:
        value = json.load(handle)
    assert isinstance(value, dict)
    return value


def _delivery(
    name: str,
    *,
    cursor: str,
    rev: str,
    source: str = "fixture-source",
    outcome: str = "verified",
    operation: str = "create",
    record: dict[str, object] | None = None,
    cid: str | None = None,
) -> IncomingDelivery:
    vector = _vector(name)
    dag_cbor = vector["dagCbor"]
    assert isinstance(dag_cbor, dict)
    envelope = {
        "repo": vector["repoDid"],
        "rev": rev,
        "operation": operation,
        "collection": vector["collection"],
        "rkey": vector["rkey"],
        "cid": cid or dag_cbor["cid"],
        "record": record or _record(name),
    }
    return IncomingDelivery(
        source=source,
        cursor=cursor,
        source_event_time=BASE_TIME,
        received_at=BASE_TIME,
        raw_envelope=envelope,
        trust_mode="test_fixture",
        verification_outcome=outcome,
        verification_method="fixture",
        verifier_version="1",
        evidence_ref="fixture:evidence",
    )


def _store(tmp_path: Path, **kwargs: object) -> ObserverStore:
    return ObserverStore(
        tmp_path / "observer.sqlite3",
        community_did=COMMUNITY_DID,
        administrator_did=ADMIN_DID,
        **kwargs,
    )


def _subject() -> RecordRef:
    submission = _record("submit")
    return RecordRef.from_mapping(submission["subject"])


def _resolve(
    *,
    status: str,
    checked_at: datetime,
    outcome: str = "verified",
) -> ResolveResult:
    subject = _subject()
    if status == "exact":
        current_cid = subject.cid
        record = _record("post")
    elif status == "mismatch":
        current_cid = _vector("submit")["dagCbor"]["cid"]  # type: ignore[index]
        record = dict(_record("post"), text="changed")
    else:
        current_cid = None
        record = None
    return ResolveResult(
        status=status,
        requested=subject,
        current_cid=current_cid,
        record=record,
        checked_at=checked_at,
        trust_mode="test_fixture",
        verification_outcome=outcome,
        resolution_method="fixture",
        resolver_version="1",
    )


def _ingest_submit_and_admission(store: ObserverStore) -> str:
    store.ingest(
        _delivery(
            "submit",
            cursor="1",
            rev="3jzfcijpj2z2c",
        )
    )
    admission = store.ingest(
        _delivery(
            "admission",
            cursor="2",
            rev="3jzfcijpj2z2d",
        )
    )
    return admission.key


def test_fresh_schema_sets_wal_constraints_and_archive_seam(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with store.read_connection() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )
        }
    assert {
        "repo_events",
        "event_receipts",
        "quarantined_deliveries",
        "subject_observation_variants",
        "subject_observations",
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
        "projection_builds",
        "ingest_sources",
        "archive_generations",
    } <= tables


def test_newer_schema_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "newer.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(ValidationError) as captured:
        ObserverStore(
            path,
            community_did=COMMUNITY_DID,
            administrator_did=ADMIN_DID,
        )
    assert captured.value.reason_code == "schema_incompatible"


def test_schema_one_is_migrated_and_reprojected_on_restart(tmp_path: Path) -> None:
    store = _store(tmp_path)
    path = store.path
    with sqlite3.connect(path) as connection:
        for table in ("discussion_activity", "discussion_replies", "discussion_roots"):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("PRAGMA user_version = 1")
        connection.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
        connection.execute("UPDATE projection_builds SET schema_version = 1")

    migrated = ObserverStore(
        path, community_did=COMMUNITY_DID, administrator_did=ADMIN_DID
    )
    with migrated.read_connection() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )
        }
    assert {"discussion_roots", "discussion_replies", "discussion_activity"} <= tables


def test_schema_two_is_migrated_with_reply_action_head(tmp_path: Path) -> None:
    store = _store(tmp_path)
    path = store.path
    with sqlite3.connect(path) as connection:
        connection.execute(
            "ALTER TABLE discussion_replies DROP COLUMN controlling_action_uri"
        )
        connection.execute(
            "ALTER TABLE discussion_replies DROP COLUMN controlling_action_cid"
        )
        connection.execute("PRAGMA user_version = 2")
        connection.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
        connection.execute("UPDATE projection_builds SET schema_version = 2")

    migrated = ObserverStore(
        path, community_did=COMMUNITY_DID, administrator_did=ADMIN_DID
    )
    with migrated.read_connection() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(discussion_replies)")
        }
    assert {"controlling_action_uri", "controlling_action_cid"} <= columns


def test_event_receipt_cursor_and_projection_commit_atomically(tmp_path: Path) -> None:
    store = _store(tmp_path)
    delivery = _delivery("submit", cursor="1", rev="3jzfcijpj2z2c")
    result = store.ingest(delivery)
    assert result.kind == "event"
    assert result.observer_sequence == 1
    assert result.duplicate is False
    assert store.counts()["repo_events"] == 1
    assert store.counts()["event_receipts"] == 1

    duplicate = store.ingest(delivery)
    assert duplicate == type(result)(
        kind="event",
        key=result.key,
        observer_sequence=1,
        duplicate=True,
    )
    assert store.counts()["event_receipts"] == 1

    snapshot = store.projection_snapshot()
    assert snapshot["ledger_records"][0]["kind"] == "submission"  # type: ignore[index]
    assert snapshot["community_entries"] == []


def test_injected_failure_rolls_back_custody_sequence_and_cursor(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    delivery = _delivery("submit", cursor="1", rev="3jzfcijpj2z2c")
    with pytest.raises(RuntimeError, match="injected failure"):
        store.ingest(delivery, fail_before_commit=True)
    assert store.counts()["repo_events"] == 0
    assert store.counts()["event_receipts"] == 0

    result = store.ingest(delivery)
    assert result.observer_sequence == 1
    with store.read_connection() as connection:
        source = connection.execute(
            "SELECT committed_cursor FROM ingest_sources"
        ).fetchone()
    assert source[0] == "1"


def test_same_source_batch_has_one_atomic_checkpoint(tmp_path: Path) -> None:
    store = _store(tmp_path)
    deliveries = (
        _delivery("submit", cursor="1", rev="3jzfcijpj2z2c"),
        _delivery("admission", cursor="2", rev="3jzfcijpj2z2d"),
    )
    with pytest.raises(RuntimeError, match="injected failure"):
        store.ingest_batch(deliveries, fail_before_commit=True)
    assert store.counts()["event_receipts"] == 0
    with store.read_connection() as connection:
        assert (
            connection.execute("SELECT count(*) FROM ingest_sources").fetchone()[0] == 0
        )

    results = store.ingest_batch(deliveries)
    assert [result.observer_sequence for result in results] == [1, 2]
    with store.read_connection() as connection:
        cursor = connection.execute(
            "SELECT committed_cursor FROM ingest_sources"
        ).fetchone()[0]
    assert cursor == "2"


def test_malformed_revision_is_quarantined_and_audited(tmp_path: Path) -> None:
    store = _store(tmp_path)
    delivery = _delivery("submit", cursor="bad", rev="3jzfcijpj2z2c")
    raw = dict(delivery.raw_envelope)
    raw["rev"] = "not-a-tid"
    malformed = IncomingDelivery(
        source=delivery.source,
        cursor=delivery.cursor,
        source_event_time=delivery.source_event_time,
        received_at=delivery.received_at,
        raw_envelope=raw,
        trust_mode=delivery.trust_mode,
        verification_outcome=delivery.verification_outcome,
        verification_method=delivery.verification_method,
        verifier_version=delivery.verifier_version,
    )
    result = store.ingest(malformed)
    assert result.kind == "quarantine"
    assert result.key.startswith("quarantine:")
    assert store.counts()["repo_events"] == 0
    assert store.counts()["quarantined_deliveries"] == 1
    audit = store.projection_snapshot()["audit_index"]
    assert audit[0]["kind"] == "quarantine"  # type: ignore[index]
    assert audit[0]["reason_codes"] == ["commit_revision_invalid"]  # type: ignore[index]


def test_two_sources_retain_receipts_but_project_once(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _delivery("submit", cursor="1", rev="3jzfcijpj2z2c")
    second = _delivery(
        "submit",
        cursor="a",
        rev="3jzfcijpj2z2c",
        source="second-source",
    )
    assert store.ingest(first).key == store.ingest(second).key
    counts = store.counts()
    assert counts["repo_events"] == 1
    assert counts["event_receipts"] == 2
    ledger = store.projection_snapshot()["ledger_records"]
    assert len(ledger) == 1
    audit = store.projection_snapshot()["audit_index"]
    event_row = next(row for row in audit if row["kind"] == "submission")
    assert event_row["receipt_count"] == 2
    assert event_row["subject_uri"] == _subject().uri
    assert event_row["subject_cid"] == _subject().cid
    assert event_row["signed_created_at"] == "2026-07-10T14:01:00Z"


def test_unverified_conflict_cannot_suppress_verified_event(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = _delivery("submit", cursor="1", rev="3jzfcijpj2z2c")
    changed = dict(_record("submit"), createdAt="2026-07-10T14:01:01Z")
    unverified = _delivery(
        "submit",
        cursor="2",
        rev="3jzfcijpj2z2c",
        outcome="unverified",
        record=changed,
        cid=_vector("profile")["dagCbor"]["cid"],  # type: ignore[index]
    )
    store.ingest(original)
    store.ingest(unverified)
    ledger = store.projection_snapshot()["ledger_records"]
    assert {row["outcome"] for row in ledger} == {"valid", "unauthorized"}
    assert not any(
        row["reason_code"] == "semantic_event_conflict"
        for row in store.projection_snapshot()["projection_findings"]
    )


def test_accepted_conflicting_variants_fail_closed_and_remain_separate(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    original = _delivery("submit", cursor="1", rev="3jzfcijpj2z2c")
    changed = dict(_record("submit"), createdAt="2026-07-10T14:01:01Z")
    conflict = _delivery(
        "submit",
        cursor="2",
        rev="3jzfcijpj2z2c",
        record=changed,
        cid=_vector("profile")["dagCbor"]["cid"],  # type: ignore[index]
    )
    store.ingest(original)
    store.ingest(conflict)
    ledger = store.projection_snapshot()["ledger_records"]
    assert len(ledger) == 2
    assert {row["outcome"] for row in ledger} == {"conflict"}
    audit = [
        row
        for row in store.projection_snapshot()["audit_index"]
        if row["kind"] == "submission"
    ]
    assert len(audit) == 2
    assert all(row["reason_codes"] == ["semantic_event_conflict"] for row in audit)


def test_subject_variants_deduplicate_while_receipts_keep_global_order(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    admission_key = _ingest_submit_and_admission(store)
    first = _resolve(status="exact", checked_at=BASE_TIME + timedelta(seconds=1))
    second = _resolve(status="exact", checked_at=BASE_TIME + timedelta(seconds=2))
    store.record_subject_observation(first, triggering_event_variant_key=admission_key)
    store.record_subject_observation(second)
    counts = store.counts()
    assert counts["subject_observation_variants"] == 1
    assert counts["subject_observations"] == 2
    entries = store.projection_snapshot()["community_entries"]
    assert entries[0]["status"] == "visible"  # type: ignore[index]
    with store.read_connection() as connection:
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
    assert sequences == [1, 2, 3, 4]


def test_terminal_mismatch_survives_later_exact_and_rebuild(tmp_path: Path) -> None:
    store = _store(tmp_path)
    admission_key = _ingest_submit_and_admission(store)
    store.record_subject_observation(
        _resolve(status="exact", checked_at=BASE_TIME + timedelta(seconds=1)),
        triggering_event_variant_key=admission_key,
    )
    store.record_subject_observation(
        _resolve(status="mismatch", checked_at=BASE_TIME + timedelta(seconds=2))
    )
    store.record_subject_observation(
        _resolve(status="exact", checked_at=BASE_TIME + timedelta(seconds=3))
    )
    before = store.projection_snapshot()
    assert before["community_entries"][0]["status"] == "stale_cid"  # type: ignore[index]
    old_generation = "g1"
    new_generation = store.rebuild()
    assert new_generation == "g2"
    assert store.projection_snapshot(old_generation) == store.projection_snapshot(
        new_generation
    )


def test_unverified_mismatch_is_unavailable_but_not_terminal(tmp_path: Path) -> None:
    store = _store(tmp_path)
    admission_key = _ingest_submit_and_admission(store)
    store.record_subject_observation(
        _resolve(status="exact", checked_at=BASE_TIME + timedelta(seconds=1)),
        triggering_event_variant_key=admission_key,
    )
    store.record_subject_observation(
        _resolve(
            status="mismatch",
            checked_at=BASE_TIME + timedelta(seconds=2),
            outcome="unverified",
        )
    )
    snapshot = store.projection_snapshot()
    assert snapshot["community_entries"][0]["status"] == "subject_unavailable"  # type: ignore[index]
    observation_audit = [
        row for row in snapshot["audit_index"] if row["kind"] == "subject_observation"
    ]
    assert observation_audit[-1]["outcome"] == "invalid"
    assert observation_audit[-1]["reason_codes"] == ["authenticity_unverified"]
    store.record_subject_observation(
        _resolve(status="exact", checked_at=BASE_TIME + timedelta(seconds=3))
    )
    assert store.projection_snapshot()["community_entries"][0]["status"] == "visible"  # type: ignore[index]


def test_valid_removal_masks_visible_entry_and_survives_rebuild(tmp_path: Path) -> None:
    store = _store(tmp_path)
    admission_key = _ingest_submit_and_admission(store)
    store.record_subject_observation(
        _resolve(status="exact", checked_at=BASE_TIME + timedelta(seconds=1)),
        triggering_event_variant_key=admission_key,
    )
    store.ingest(_delivery("mod_action", cursor="3", rev="3jzfcijpj2z2e"))
    before = store.projection_snapshot()
    assert before["community_entries"][0]["status"] == "removed"  # type: ignore[index]
    store.rebuild()
    assert store.projection_snapshot()["community_entries"][0]["status"] == "removed"  # type: ignore[index]


def test_pcv0_submission_update_after_admission_withdraws_root(
    tmp_path: Path,
) -> None:
    # PCV0 supersedes OQ-5 for roots: withdrawing author context closes
    # community discovery while retaining the signed admission history.
    store = _store(tmp_path)
    admission_key = _ingest_submit_and_admission(store)
    store.record_subject_observation(
        _resolve(status="exact", checked_at=BASE_TIME + timedelta(seconds=1)),
        triggering_event_variant_key=admission_key,
    )
    changed = dict(_record("submit"), createdAt="2026-07-10T14:01:01Z")
    store.ingest(
        _delivery(
            "submit",
            cursor="3",
            rev="3jzfcijpj2z2e",
            operation="update",
            record=changed,
            cid=_vector("profile")["dagCbor"]["cid"],  # type: ignore[index]
        )
    )
    snapshot = store.projection_snapshot()
    assert snapshot["community_entries"][0]["status"] == "author_withdrawn"  # type: ignore[index]
    submissions = [
        row
        for row in snapshot["ledger_records"]
        if row["kind"] == "submission"  # type: ignore[index]
    ]
    assert [row["operation"] for row in submissions] == ["create", "update"]  # type: ignore[index]
    assert not any(
        row["reason_code"] == "projection_incomplete"
        for row in snapshot["projection_findings"]
    )


def test_pcv0_submission_delete_after_admission_withdraws_root(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    admission_key = _ingest_submit_and_admission(store)
    store.record_subject_observation(
        _resolve(status="exact", checked_at=BASE_TIME + timedelta(seconds=1)),
        triggering_event_variant_key=admission_key,
    )
    vector = _vector("submit")
    store.ingest(
        IncomingDelivery(
            source="fixture-source",
            cursor="3",
            source_event_time=BASE_TIME,
            received_at=BASE_TIME,
            raw_envelope={
                "repo": vector["repoDid"],
                "rev": "3jzfcijpj2z2e",
                "operation": "delete",
                "collection": vector["collection"],
                "rkey": vector["rkey"],
            },
            trust_mode="test_fixture",
            verification_outcome="verified",
            verification_method="fixture",
            verifier_version="1",
        )
    )
    snapshot = store.projection_snapshot()
    assert snapshot["community_entries"][0]["status"] == "author_withdrawn"  # type: ignore[index]
    submissions = [
        row
        for row in snapshot["ledger_records"]
        if row["kind"] == "submission"  # type: ignore[index]
    ]
    assert [row["operation"] for row in submissions] == ["create", "delete"]  # type: ignore[index]


def test_read_connection_cannot_mutate_observer_database(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with store.read_connection() as connection:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("UPDATE meta SET value = 'x'")
