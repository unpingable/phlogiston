from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from community_model import IncomingDelivery, RecordRef, ResolveResult
from communitywatch import ObserverStore

FIXTURES = Path(__file__).parents[3] / "tests" / "fixtures" / "v0"
COMMUNITY_DID = "did:web:community.invalid"
ADMIN_DID = "did:web:admin.invalid"
BASE_TIME = datetime(2026, 7, 10, 14, 2, 1, tzinfo=UTC)
SOURCE_A = "fixture-source"
SOURCE_B = "relay-source"


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


def make_delivery(
    name: str,
    *,
    cursor: str,
    rev: str,
    source: str = SOURCE_A,
    outcome: str = "verified",
    operation: str = "create",
    record: dict[str, object] | None = None,
    cid: str | None = None,
    received_at: datetime = BASE_TIME,
    source_event_time: datetime | None = BASE_TIME,
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
        source_event_time=source_event_time,
        received_at=received_at,
        raw_envelope=envelope,
        trust_mode="test_fixture",
        verification_outcome=outcome,
        verification_method="fixture",
        verifier_version="1",
        evidence_ref="fixture:evidence",
    )


def make_quarantined(
    *,
    cursor: str,
    source: str = SOURCE_A,
    received_at: datetime = BASE_TIME,
) -> IncomingDelivery:
    return IncomingDelivery(
        source=source,
        cursor=cursor,
        source_event_time=None,
        received_at=received_at,
        raw_envelope=b'{"repo": 42}',
        trust_mode="test_fixture",
        verification_outcome="failed",
        verification_method="fixture",
        verifier_version="1",
    )


def make_store(tmp_path: Path) -> ObserverStore:
    return ObserverStore(
        tmp_path / "observer.sqlite3",
        community_did=COMMUNITY_DID,
        administrator_did=ADMIN_DID,
    )


def subject_ref() -> RecordRef:
    submission = _record("submit")
    return RecordRef.from_mapping(submission["subject"])


def make_resolve(
    *,
    status: str = "exact",
    checked_at: datetime = BASE_TIME,
    outcome: str = "verified",
) -> ResolveResult:
    subject = subject_ref()
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


def ingest_submission_and_admission(store: ObserverStore) -> None:
    store.ingest(make_delivery("submit", cursor="1", rev="3jzfcijpj2z2c"))
    store.ingest(make_delivery("admission", cursor="2", rev="3jzfcijpj2z2d"))


@pytest.fixture()
def populated(tmp_path: Path) -> tuple[ObserverStore, Path, Path]:
    """A store with receipts from two sources, one observation, one quarantine."""

    store = make_store(tmp_path)
    ingest_submission_and_admission(store)
    store.ingest(
        make_delivery(
            "profile",
            cursor="9",
            rev="3jzfcijpj2z2e",
            source=SOURCE_B,
            received_at=BASE_TIME + timedelta(seconds=1),
        )
    )
    store.record_subject_observation(
        make_resolve(checked_at=BASE_TIME + timedelta(seconds=2))
    )
    store.ingest(
        make_quarantined(cursor="3", received_at=BASE_TIME + timedelta(seconds=3))
    )
    return store, store.path, tmp_path / "artifacts"
