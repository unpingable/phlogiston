from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from community_model import (
    AuthoritySubjectState,
    AuthorizedAdmin,
    CurrentRecordResult,
    EventBatch,
    EventReceipt,
    IncomingDelivery,
    Page,
    RecordRef,
    RepoEvent,
    ResolveResult,
    ValidationError,
    event_variant_key,
    payload_hash,
    semantic_event_key,
)
from community_model.immutable import FrozenDict, deep_freeze, deep_thaw

POST_REF = RecordRef(
    uri="at://did:web:alice.invalid/app.bsky.feed.post/3jzfcijpj2z2a",
    cid="bafyreidfayvfuwqa7qlnopdjiqrxzs6blmoeu4rujcjtnci5beludirz2a",
)
NOW = datetime(2026, 7, 10, 14, tzinfo=UTC)


def test_deep_freeze_copies_nested_inputs_and_is_order_insensitive() -> None:
    nested = {"b": [1, {"inside": "original"}], "a": True}
    frozen = deep_freeze(nested)
    assert isinstance(frozen, FrozenDict)
    assert frozen == deep_freeze({"a": True, "b": [1, {"inside": "original"}]})
    assert hash(frozen) == hash(
        deep_freeze({"a": True, "b": [1, {"inside": "original"}]})
    )

    nested["b"][1]["inside"] = "changed"  # type: ignore[index]
    assert deep_thaw(frozen)["b"][1]["inside"] == "original"  # type: ignore[index]
    with pytest.raises(TypeError):
        frozen["new"] = "value"  # type: ignore[index]


def test_frozen_dict_private_storage_cannot_be_mutated() -> None:
    frozen = FrozenDict({"nested": [1]})
    private_storage = object.__getattribute__(frozen, "_data")

    with pytest.raises(TypeError):
        private_storage["nested"] = (2,)
    assert deep_thaw(frozen) == {"nested": [1]}


def test_delivery_freezes_envelope_and_normalizes_times() -> None:
    envelope = {"record": {"subject": ["exact"]}}
    source_time = datetime(2026, 7, 10, 9, tzinfo=timezone(-timedelta(hours=4)))
    received_time = datetime(2026, 7, 10, 10, tzinfo=timezone(-timedelta(hours=4)))
    delivery = IncomingDelivery(
        source="fixture",
        cursor="1",
        source_event_time=source_time,
        received_at=received_time,
        raw_envelope=envelope,
        trust_mode="test_fixture",
        verification_outcome="verified",
        verification_method="fixture",
        verifier_version="1",
    )
    envelope["record"] = {"subject": ["changed"]}
    assert delivery.source_event_time == datetime(2026, 7, 10, 13, tzinfo=UTC)
    assert delivery.received_at == datetime(2026, 7, 10, 14, tzinfo=UTC)
    assert delivery.source_event_time != delivery.received_at
    assert deep_thaw(delivery.raw_envelope) == {"record": {"subject": ["exact"]}}


def test_exact_resolution_requires_exact_cid_and_frozen_record() -> None:
    result = ResolveResult(
        status="exact",
        requested=POST_REF,
        current_cid=POST_REF.cid,
        record={"text": "hello"},
        checked_at=NOW,
        trust_mode="test_fixture",
        verification_outcome="verified",
        resolution_method="fixture",
        resolver_version="1",
    )
    assert deep_thaw(result.record) == {"text": "hello"}

    with pytest.raises(ValidationError, match="strong_ref_mismatch"):
        ResolveResult(
            status="exact",
            requested=POST_REF,
            current_cid=None,
            record=None,
            checked_at=NOW,
            trust_mode="test_fixture",
            verification_outcome="verified",
            resolution_method="fixture",
            resolver_version="1",
        )


def test_current_record_status_controls_nullable_content() -> None:
    present = CurrentRecordResult(
        status="present",
        uri=POST_REF.uri,
        current_cid=POST_REF.cid,
        record={"text": "hello"},
        checked_at=NOW,
        trust_mode="test_fixture",
        verification_outcome="verified",
        resolution_method="fixture",
        resolver_version="1",
    )
    assert present.current_cid == POST_REF.cid

    with pytest.raises(ValidationError, match="missing/error"):
        CurrentRecordResult(
            status="missing",
            uri=POST_REF.uri,
            current_cid=POST_REF.cid,
            record={"text": "stale"},
            checked_at=NOW,
            trust_mode="test_fixture",
            verification_outcome="verified",
            resolution_method="fixture",
            resolver_version="1",
        )


def test_batches_and_pages_copy_collections_and_freeze_mapping_items() -> None:
    items = [{"nested": [1]}]
    page = Page(items=items, cursor=None)
    items[0]["nested"].append(2)
    assert deep_thaw(page.items[0]) == {"nested": [1]}

    deliveries = [
        IncomingDelivery(
            source="fixture",
            cursor="1",
            source_event_time=None,
            received_at=NOW,
            raw_envelope=b"envelope",
            trust_mode="test_fixture",
            verification_outcome="verified",
            verification_method="fixture",
            verifier_version="1",
        )
    ]
    batch = EventBatch(items=deliveries, next_cursor="1")
    deliveries.clear()
    assert len(batch.items) == 1


@pytest.mark.parametrize("bad_cursor", ["", "\x00", 1, b"cursor"])
def test_batches_and_pages_require_optional_nul_free_string_cursors(
    bad_cursor: object,
) -> None:
    with pytest.raises(ValidationError, match="cursor"):
        Page(items=(), cursor=bad_cursor)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="next_cursor"):
        EventBatch(items=(), next_cursor=bad_cursor)  # type: ignore[arg-type]


def test_resolution_and_authority_carriers_require_exact_reference_types() -> None:
    with pytest.raises(ValidationError, match="requested"):
        ResolveResult(
            status="missing",
            requested=POST_REF.as_dict(),  # type: ignore[arg-type]
            current_cid=None,
            record=None,
            checked_at=NOW,
            trust_mode="test_fixture",
            verification_outcome="verified",
            resolution_method="fixture",
            resolver_version="1",
        )

    with pytest.raises(ValidationError, match="valid_admissions"):
        AuthoritySubjectState(
            subject=POST_REF,
            valid_admissions=(POST_REF.as_dict(),),  # type: ignore[arg-type]
            valid_removals=(),
            community_repo_high_water="3jzfcijpj2z2c",
        )

    with pytest.raises(ValidationError, match="effective UID"):
        AuthorizedAdmin(did="did:web:admin.invalid", effective_uid=True)


def test_repo_event_derives_and_checks_all_identity_and_evidence_fields() -> None:
    record = {
        "$type": "app.phlogiston.community.submit",
        "createdAt": "2026-07-10T14:00:00Z",
    }
    semantic_key = semantic_event_key(
        repo_did="did:web:alice.invalid",
        commit_identity="rev:3jzfcijpj2z2c",
        collection="app.phlogiston.community.submit",
        rkey="3jzfcijpj2z2b",
        operation="create",
    )
    digest = payload_hash("observer_json_v0", record)
    variant_key = event_variant_key(
        semantic_event_key=semantic_key,
        record_cid=POST_REF.cid,
        payload_hash_scope="observer_json_v0",
        payload_hash=digest,
    )
    event = RepoEvent(
        semantic_event_key=semantic_key,
        event_variant_key=variant_key,
        commit_identity="rev:3jzfcijpj2z2c",
        repo_order="3jzfcijpj2z2c",
        repo_did="did:web:alice.invalid",
        operation="create",
        collection="app.phlogiston.community.submit",
        rkey="3jzfcijpj2z2b",
        record_uri=(
            "at://did:web:alice.invalid/app.phlogiston.community.submit/3jzfcijpj2z2b"
        ),
        record_cid=POST_REF.cid,
        commit_rev="3jzfcijpj2z2c",
        commit_cid=None,
        record=record,
        record_bytes=None,
        payload_hash=digest,
        payload_hash_scope="observer_json_v0",
    )
    record["createdAt"] = "changed"
    assert deep_thaw(event.record)["createdAt"] == "2026-07-10T14:00:00Z"  # type: ignore[index]

    with pytest.raises(ValidationError, match="semantic event key"):
        RepoEvent(
            semantic_event_key="sha256:" + "0" * 64,
            event_variant_key=variant_key,
            commit_identity=event.commit_identity,
            repo_order=event.repo_order,
            repo_did=event.repo_did,
            operation=event.operation,
            collection=event.collection,
            rkey=event.rkey,
            record_uri=event.record_uri,
            record_cid=event.record_cid,
            commit_rev=event.commit_rev,
            commit_cid=None,
            record=event.record,
            record_bytes=None,
            payload_hash=event.payload_hash,
            payload_hash_scope=event.payload_hash_scope,
        )

    list_record = ["not", "a", "mapping"]
    list_digest = payload_hash("observer_json_v0", list_record)
    list_variant = event_variant_key(
        semantic_event_key=event.semantic_event_key,
        record_cid=event.record_cid,
        payload_hash_scope=event.payload_hash_scope,
        payload_hash=list_digest,
    )
    with pytest.raises(ValidationError, match="record must be a mapping"):
        replace(
            event,
            record=list_record,  # type: ignore[arg-type]
            payload_hash=list_digest,
            event_variant_key=list_variant,
        )

    with pytest.raises(ValidationError, match="record_bytes"):
        replace(event, record_bytes=1)  # type: ignore[arg-type]


def test_event_receipt_validates_local_sequence_and_freezes_provenance() -> None:
    receipt = EventReceipt(
        event_variant_key="sha256:" + "1" * 64,
        source="fixture",
        cursor="cursor-1",
        source_event_time=None,
        received_at=NOW,
        observer_sequence=1,
        trust_mode="test_fixture",
        verification_outcome="verified",
        verification_method="fixture",
        verifier_version="1",
    )
    assert receipt.observer_sequence == 1

    with pytest.raises(ValidationError, match="observer_sequence"):
        EventReceipt(
            event_variant_key=receipt.event_variant_key,
            source=receipt.source,
            cursor=receipt.cursor,
            source_event_time=None,
            received_at=NOW,
            observer_sequence=True,
            trust_mode=receipt.trust_mode,
            verification_outcome=receipt.verification_outcome,
            verification_method=receipt.verification_method,
            verifier_version=receipt.verifier_version,
        )
