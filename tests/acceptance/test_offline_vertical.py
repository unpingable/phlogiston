"""The single offline vertical-phase acceptance test (TEST-PLAN V0-M3).

One named end-to-end test over fake transports and one temporary observer
SQLite database: submit -> hidden -> admit -> visible -> CID mismatch hides
-> remove keeps hidden -> audit retains everything -> no side ever mutates
the author's post.  It then proves the rebuild requirement twice: from the
SQLite tail alone, and from sealed history plus the sequence-disjoint tail
after a verified export/accept/prune cycle.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from community_model import (
    ADMISSION_COLLECTION,
    MOD_ACTION_COLLECTION,
    POST_COLLECTION,
    SUBMISSION_COLLECTION,
    IncomingDelivery,
    ResolveResult,
    canonical_json_bytes,
    cid_for_dag_cbor,
)
from communityd.config import DaemonConfig
from communityd.fakes import (
    FakeAdminAuthorizer,
    FakeAuthorityLedgerReader,
    FakeAuthorityWriter,
    FakeCredentialProvider,
    FakeRecordReader,
    FakeRepoState,
)
from communityd.operations import DaemonPorts, admit, remove
from communitywatch import ObserverStore, ProjectionQuery
from communitywatch.fakes import FakeSubjectResolver
from communitywatch_archive.export import export_generation
from communitywatch_archive.gates import load_merged_facts, reduce_facts
from communitywatch_archive.lifecycle import accept_generation, prune_generation

COMMUNITY_DID = "did:web:community.invalid"
ADMIN_DID = "did:web:admin.invalid"
ALICE_DID = "did:web:alice.invalid"
POST_RKEY = "3jzfcijpj2z2a"
SUBMISSION_RKEY = "3jzfcijpj2z2b"
ALLOWED_UID = 4242
CREDENTIAL_REF = "fake://communityd-admin"
SOURCE = "fake-relay"
T0 = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)

_DERIVED_TABLES = (
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
    "audit_index",
)


def _cid(record: dict[str, object]) -> str:
    return cid_for_dag_cbor(canonical_json_bytes(record))


def _delivery(
    envelope: dict[str, object], *, cursor: str, received_at: datetime
) -> IncomingDelivery:
    return IncomingDelivery(
        source=SOURCE,
        cursor=cursor,
        source_event_time=received_at,
        received_at=received_at,
        raw_envelope=envelope,
        trust_mode="test_fixture",
        verification_outcome="verified",
        verification_method="fixture",
        verifier_version="1",
    )


def _bools_to_ints(value: object) -> object:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, dict):
        return {key: _bools_to_ints(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_bools_to_ints(item) for item in value]
    return value


def _canonical_tables(tables: dict[str, object]) -> dict[str, list[str]]:
    """Render derived-table rows as comparable canonical JSON, order-free."""

    rendered: dict[str, list[str]] = {}
    for name, rows in tables.items():
        assert isinstance(rows, list | tuple)
        rendered[name] = sorted(
            canonical_json_bytes(_bools_to_ints(row)).decode("utf-8") for row in rows
        )
    return rendered


def _rebuilt_tables(db_path: Path, artifacts: Path) -> dict[str, list[str]]:
    merged = load_merged_facts(db_path, artifacts)
    rebuilt = reduce_facts(
        merged, community_did=COMMUNITY_DID, administrator_did=ADMIN_DID
    )
    return _canonical_tables({name: getattr(rebuilt, name) for name in _DERIVED_TABLES})


def test_offline_vertical_acceptance(tmp_path: Path) -> None:
    # --- setup: observer store, query layer, and daemon fakes ---------------
    store = ObserverStore(
        tmp_path / "observer.sqlite3",
        community_did=COMMUNITY_DID,
        administrator_did=ADMIN_DID,
    )
    query = ProjectionQuery(store, slug="homelab")
    state = FakeRepoState()
    ports = DaemonPorts(
        reader=FakeRecordReader(state),
        ledger=FakeAuthorityLedgerReader(state),
        authorizer=FakeAdminAuthorizer(
            administrator_did=ADMIN_DID,
            allowed_uid=ALLOWED_UID,
            effective_uid=ALLOWED_UID,
        ),
        writer=FakeAuthorityWriter(state),
        credentials=FakeCredentialProvider({CREDENTIAL_REF: "fake-handle"}),
    )
    daemon_config = DaemonConfig(
        community_did=COMMUNITY_DID,
        administrator_did=ADMIN_DID,
        community_pds_url="https://pds.invalid",
        allowed_uid=ALLOWED_UID,
        reader_adapter="fake",
        ledger_adapter="fake",
        writer_adapter="fake",
        credential_provider="fake",
        credential_ref=CREDENTIAL_REF,
    )

    # --- step 1: author-owned post at CID A plus an exact self-submission ---
    post_a = {
        "$type": POST_COLLECTION,
        "text": "Tiny computers, loud fans.",
        "createdAt": "2026-08-13T12:00:00Z",
    }
    post_ref = state.seed(ALICE_DID, POST_COLLECTION, POST_RKEY, post_a)
    assert post_ref.cid == _cid(post_a)
    submission_record = {
        "$type": SUBMISSION_COLLECTION,
        "community": COMMUNITY_DID,
        "subject": post_ref.as_dict(),
        "createdAt": "2026-08-13T12:00:30Z",
    }
    submission_ref = state.seed(
        ALICE_DID, SUBMISSION_COLLECTION, SUBMISSION_RKEY, submission_record
    )

    # --- step 2: ingest + project; audit sees it, the page does not ---------
    store.ingest(
        _delivery(
            {
                "repo": ALICE_DID,
                "rev": "3jzfcijpj2z2c",
                "operation": "create",
                "collection": SUBMISSION_COLLECTION,
                "rkey": SUBMISSION_RKEY,
                "cid": submission_ref.cid,
                "record": submission_record,
            },
            cursor="1",
            received_at=datetime(2026, 8, 13, 12, 0, 31, tzinfo=UTC),
        )
    )
    audit = query.list_audit(COMMUNITY_DID, 100, None)
    submissions = [row for row in audit.items if row["kind"] == "submission"]
    assert len(submissions) == 1
    assert submissions[0]["record"] == submission_ref.as_dict()
    assert submissions[0]["subject"] == post_ref.as_dict()
    assert submissions[0]["outcome"] == "valid"
    assert query.list_visible(COMMUNITY_DID, 100, None).items == ()

    # --- step 3: communityd admit; ingest the emitted event; visible once ---
    admission_time = datetime(2026, 8, 13, 12, 1, tzinfo=UTC)
    admission = admit(ports, daemon_config, submission_ref, now=admission_time)
    assert admission.operation == "created"
    admission_result = store.ingest(
        _delivery(
            state.emitted[-1],
            cursor="2",
            received_at=datetime(2026, 8, 13, 12, 1, 1, tzinfo=UTC),
        )
    )
    resolver = FakeSubjectResolver(
        {
            post_ref: [
                ResolveResult(
                    status="exact",
                    requested=post_ref,
                    current_cid=post_ref.cid,
                    record=post_a,
                    checked_at=datetime(2026, 8, 13, 12, 1, 2, tzinfo=UTC),
                    trust_mode="test_fixture",
                    verification_outcome="verified",
                    resolution_method="fixture",
                    resolver_version="1",
                )
            ]
        }
    )
    store.record_subject_observation(
        resolver.resolve_exact(post_ref),
        triggering_event_variant_key=admission_result.key,
    )
    page = query.list_visible(COMMUNITY_DID, 100, None)
    assert len(page.items) == 1
    entry = page.items[0]
    assert entry["subject"] == post_ref.as_dict()
    assert entry["admission"] == admission.record.as_dict()
    assert entry["post"]["text"] == "Tiny computers, loud fans."

    # --- step 4: the post moves to CID B; the entry goes stale and hides ----
    post_b = dict(post_a, text="Tiny computers, louder fans.")
    cid_b = _cid(post_b)
    state.move(ALICE_DID, POST_COLLECTION, POST_RKEY, cid_b)
    resolver.results[post_ref].append(
        ResolveResult(
            status="mismatch",
            requested=post_ref,
            current_cid=cid_b,
            record=None,
            checked_at=datetime(2026, 8, 13, 12, 2, tzinfo=UTC),
            trust_mode="test_fixture",
            verification_outcome="verified",
            resolution_method="fixture",
            resolver_version="1",
        )
    )
    store.record_subject_observation(resolver.resolve_exact(post_ref))
    snapshot = store.projection_snapshot()
    assert [row["status"] for row in snapshot["admission_lifecycles"]] == ["stale_cid"]
    assert [row["status"] for row in snapshot["community_entries"]] == ["stale_cid"]
    assert query.list_visible(COMMUNITY_DID, 100, None).items == ()

    # --- step 5: communityd remove against the exact admission; stays gone --
    removal = remove(
        ports,
        daemon_config,
        admission.record,
        "off-topic",
        now=datetime(2026, 8, 13, 12, 3, tzinfo=UTC),
    )
    assert removal.operation == "created"
    store.ingest(
        _delivery(
            state.emitted[-1],
            cursor="3",
            received_at=datetime(2026, 8, 13, 12, 3, 1, tzinfo=UTC),
        )
    )
    snapshot = store.projection_snapshot()
    assert [row["status"] for row in snapshot["admission_lifecycles"]] == ["removed"]
    assert [row["status"] for row in snapshot["community_entries"]] == ["removed"]
    assert query.list_visible(COMMUNITY_DID, 100, None).items == ()

    # --- step 6: compact audit retains the whole history with exact refs ----
    audit = query.list_audit(COMMUNITY_DID, 100, None)
    by_kind: dict[str, list[object]] = {}
    for row in audit.items:
        by_kind.setdefault(str(row["kind"]), []).append(row)
    assert sorted(by_kind) == [
        "admission",
        "removal",
        "subject_observation",
        "submission",
    ]
    (admission_row,) = by_kind["admission"]
    assert admission_row["record"] == admission.record.as_dict()  # type: ignore[index]
    assert admission_row["outcome"] == "valid"  # type: ignore[index]
    assert admission_row["actor"] == ADMIN_DID  # type: ignore[index]
    (removal_row,) = by_kind["removal"]
    assert removal_row["record"] == removal.record.as_dict()  # type: ignore[index]
    assert removal_row["reason"] == "off-topic"  # type: ignore[index]
    assert removal_row["outcome"] == "valid"  # type: ignore[index]
    for row in audit.items:
        assert str(row["payloadHash"]).startswith("sha256:")
        assert str(row["auditRowKey"]).startswith(
            ("event:sha256:", "observation:sha256:")
        )
    mismatch_rows = [
        row
        for row in by_kind["subject_observation"]
        if "subject_cid_mismatch" in row["reasonCodes"]  # type: ignore[operator]
    ]
    assert len(mismatch_rows) == 1
    assert mismatch_rows[0]["subject"] == post_ref.as_dict()  # type: ignore[index]

    # --- step 7: call logs prove custody and authority invariants -----------
    assert ports.writer.calls == [
        ("create_immutable", COMMUNITY_DID, ADMISSION_COLLECTION),
        ("create_immutable", COMMUNITY_DID, MOD_ACTION_COLLECTION),
    ]
    # The writer port exposes no update/delete at all, and no call ever
    # targeted the author's repository or the post collection.
    assert not hasattr(ports.writer, "update")
    assert not hasattr(ports.writer, "delete")
    # The author's own edit stands; neither side rewrote the user record.
    assert state.records[(ALICE_DID, POST_COLLECTION, POST_RKEY)].cid == cid_b
    # The observer side never held or invoked the authority writer: the only
    # two writer calls are the daemon operations asserted above.
    assert len(state.emitted) == 2
    # The daemon only ever saw its ports; the observer database path never
    # reached any daemon adapter.
    logs = (
        ports.reader.calls,
        ports.ledger.calls,
        ports.writer.calls,
        ports.authorizer.calls,
        ports.credentials.calls,
    )
    assert str(store.path) not in repr(logs)

    # --- rebuild requirement (a): the SQLite tail alone ----------------------
    final_tables = _canonical_tables(store.projection_snapshot())
    store.rebuild()
    assert _canonical_tables(store.projection_snapshot()) == final_tables

    # --- rebuild requirement (b): sealed history + sequence-disjoint tail ---
    artifacts = tmp_path / "artifacts"
    export = export_generation(store.path, artifacts)
    accept_generation(
        store.path,
        artifacts,
        export.generation_id,
        community_did=COMMUNITY_DID,
        administrator_did=ADMIN_DID,
    )
    pruned = prune_generation(store.path, artifacts, export.generation_id)
    assert sum(pruned.deleted_rows.values()) > 0
    # Derived state is untouched by pruning, and the merged cold+hot custody
    # rebuilds byte-identical audit and current projection content.
    assert _canonical_tables(store.projection_snapshot()) == final_tables
    assert _rebuilt_tables(store.path, artifacts) == final_tables
