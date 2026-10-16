from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from community_model import (
    CursorError,
    IncomingDelivery,
    RecordRef,
    ResolveResult,
    ValidationError,
    admission_rkey,
    canonical_json_bytes,
    cid_for_dag_cbor,
)
from communitywatch import (
    ObserverStore,
    ProjectionQuery,
    ProjectionUnavailableError,
    UnknownCommunityError,
)

COMMUNITY_DID = "did:web:community.invalid"
ADMIN_DID = "did:web:admin.invalid"
SLUG = "homelab"
BASE_TIME = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)
SOURCE = "fixture-source"
_TID_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"

PROFILE_COLLECTION = "app.phlogiston.community.profile"
SUBMISSION_COLLECTION = "app.phlogiston.community.submit"
ADMISSION_COLLECTION = "app.phlogiston.community.admission"
POST_COLLECTION = "app.bsky.feed.post"


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


def _delivery(
    *,
    repo: str,
    collection: str,
    rkey: str,
    cursor: str,
    rev: str,
    record: dict[str, object] | None,
    operation: str = "create",
    cid: str | None = None,
    outcome: str = "verified",
    received_at: datetime,
) -> IncomingDelivery:
    envelope: dict[str, object] = {
        "repo": repo,
        "rev": rev,
        "operation": operation,
        "collection": collection,
        "rkey": rkey,
    }
    if operation != "delete":
        envelope["cid"] = cid or _cid(record or {})
        envelope["record"] = record
    return IncomingDelivery(
        source=SOURCE,
        cursor=cursor,
        source_event_time=received_at,
        received_at=received_at,
        raw_envelope=envelope,
        trust_mode="test_fixture",
        verification_outcome=outcome,
        verification_method="fixture",
        verifier_version="1",
    )


class _Sequencer:
    def __init__(self) -> None:
        self.cursor = 0
        self.revs: dict[str, int] = {}

    def next_cursor(self) -> str:
        self.cursor += 1
        return str(self.cursor)

    def next_rev(self, repo: str) -> str:
        self.revs[repo] = self.revs.get(repo, 0) + 1
        return _tid(self.revs[repo])


def _visible_entry(
    store: ObserverStore,
    sequencer: _Sequencer,
    *,
    author_did: str,
    post_rkey: str,
    submission_rkey: str,
    text: str,
    admitted_at: str,
    observed_at: datetime,
) -> RecordRef:
    """Drive one submission/admission/exact-observation flow; return subject."""

    post = {"$type": POST_COLLECTION, "text": text, "createdAt": admitted_at}
    subject = RecordRef(
        uri=f"at://{author_did}/{POST_COLLECTION}/{post_rkey}", cid=_cid(post)
    )
    submission_record = {
        "$type": SUBMISSION_COLLECTION,
        "community": COMMUNITY_DID,
        "subject": subject.as_dict(),
        "createdAt": admitted_at,
    }
    submission = RecordRef(
        uri=f"at://{author_did}/{SUBMISSION_COLLECTION}/{submission_rkey}",
        cid=_cid(submission_record),
    )
    store.ingest(
        _delivery(
            repo=author_did,
            collection=SUBMISSION_COLLECTION,
            rkey=submission_rkey,
            cursor=sequencer.next_cursor(),
            rev=sequencer.next_rev(author_did),
            record=submission_record,
            received_at=observed_at,
        )
    )
    admission_record = {
        "$type": ADMISSION_COLLECTION,
        "submission": submission.as_dict(),
        "subject": subject.as_dict(),
        "actor": ADMIN_DID,
        "createdAt": admitted_at,
    }
    admission_cid = _cid(admission_record)
    result = store.ingest(
        _delivery(
            repo=COMMUNITY_DID,
            collection=ADMISSION_COLLECTION,
            rkey=admission_rkey(submission),
            cursor=sequencer.next_cursor(),
            rev=sequencer.next_rev(COMMUNITY_DID),
            record=admission_record,
            cid=admission_cid,
            received_at=observed_at + timedelta(seconds=1),
        )
    )
    store.record_subject_observation(
        ResolveResult(
            status="exact",
            requested=subject,
            current_cid=subject.cid,
            record=post,
            checked_at=observed_at + timedelta(seconds=2),
            trust_mode="test_fixture",
            verification_outcome="verified",
            resolution_method="fixture",
            resolver_version="1",
        ),
        triggering_event_variant_key=result.key,
    )
    return subject


def _store(tmp_path: Path) -> ObserverStore:
    return ObserverStore(
        tmp_path / "observer.sqlite3",
        community_did=COMMUNITY_DID,
        administrator_did=ADMIN_DID,
    )


def _query(store: ObserverStore) -> ProjectionQuery:
    return ProjectionQuery(store, slug=SLUG)


def test_projection_query_satisfies_the_community_query_port(tmp_path: Path) -> None:
    from communitywatch.ports import CommunityQuery

    assert isinstance(_query(_store(tmp_path)), CommunityQuery)


def test_visible_entries_paginate_in_reverse_admission_chronology(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    sequencer = _Sequencer()
    for index, admitted_at in enumerate(
        (
            "2026-08-13T12:01:00Z",
            "2026-08-13T12:03:00Z",
            "2026-08-13T12:02:00Z",
        )
    ):
        _visible_entry(
            store,
            sequencer,
            author_did=f"did:web:author{index}.invalid",
            post_rkey=f"3jzfcijpj2z2{chr(ord('a') + index)}",
            submission_rkey=f"3jzfcijpj2z2{chr(ord('k') + index)}",
            text=f"post number {index}",
            admitted_at=admitted_at,
            observed_at=BASE_TIME + timedelta(minutes=index),
        )
    query = _query(store)

    first = query.list_visible(COMMUNITY_DID, 2, None)
    assert len(first.items) == 2
    assert first.cursor is not None
    assert [item["admittedAt"] for item in first.items] == [
        "2026-08-13T12:03:00Z",
        "2026-08-13T12:02:00Z",
    ]
    second = query.list_visible(COMMUNITY_DID, 2, first.cursor)
    assert second.cursor is None
    assert [item["admittedAt"] for item in second.items] == ["2026-08-13T12:01:00Z"]
    uris = [item["subject"]["uri"] for item in (*first.items, *second.items)]
    assert len(set(uris)) == 3


def test_equal_admission_times_break_ties_by_admission_uri_descending(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    sequencer = _Sequencer()
    for index in range(2):
        _visible_entry(
            store,
            sequencer,
            author_did=f"did:web:tie{index}.invalid",
            post_rkey=f"3jzfcijpj2z2{chr(ord('a') + index)}",
            submission_rkey=f"3jzfcijpj2z2{chr(ord('k') + index)}",
            text=f"tie {index}",
            admitted_at="2026-08-13T12:05:00Z",
            observed_at=BASE_TIME + timedelta(minutes=index),
        )
    query = _query(store)

    page = query.list_visible(COMMUNITY_DID, 10, None)
    uris = [item["admission"]["uri"] for item in page.items]
    assert uris == sorted(uris, reverse=True)


def test_entry_payload_shape_and_bounded_limits(tmp_path: Path) -> None:
    store = _store(tmp_path)
    sequencer = _Sequencer()
    subject = _visible_entry(
        store,
        sequencer,
        author_did="did:web:alice.invalid",
        post_rkey="3jzfcijpj2z2a",
        submission_rkey="3jzfcijpj2z2k",
        text="hello community",
        admitted_at="2026-08-13T12:01:00Z",
        observed_at=BASE_TIME,
    )
    query = _query(store)

    page = query.list_visible(COMMUNITY_DID, 50, None)
    assert len(page.items) == 1
    entry = page.items[0]
    assert entry["subject"] == subject.as_dict()
    assert entry["authorDid"] == "did:web:alice.invalid"
    assert entry["post"]["text"] == "hello community"
    assert entry["sourceUrl"] == (
        "https://bsky.app/profile/did:web:alice.invalid/post/3jzfcijpj2z2a"
    )

    for bad_limit in (0, 101, -1):
        with pytest.raises(ValidationError):
            query.list_visible(COMMUNITY_DID, bad_limit, None)
    with pytest.raises(CursorError):
        query.list_visible(COMMUNITY_DID, 50, "not a cursor")


def test_only_visible_entries_render(tmp_path: Path) -> None:
    store = _store(tmp_path)
    sequencer = _Sequencer()
    subject = _visible_entry(
        store,
        sequencer,
        author_did="did:web:alice.invalid",
        post_rkey="3jzfcijpj2z2a",
        submission_rkey="3jzfcijpj2z2k",
        text="will go stale",
        admitted_at="2026-08-13T12:01:00Z",
        observed_at=BASE_TIME,
    )
    query = _query(store)
    assert len(query.list_visible(COMMUNITY_DID, 50, None).items) == 1

    store.record_subject_observation(
        ResolveResult(
            status="mismatch",
            requested=subject,
            current_cid=_cid({"text": "changed"}),
            record=None,
            checked_at=BASE_TIME + timedelta(minutes=5),
            trust_mode="test_fixture",
            verification_outcome="verified",
            resolution_method="fixture",
            resolver_version="1",
        )
    )
    assert query.list_visible(COMMUNITY_DID, 50, None).items == ()


def test_unknown_community_is_rejected(tmp_path: Path) -> None:
    query = _query(_store(tmp_path))
    with pytest.raises(UnknownCommunityError):
        query.list_visible("did:web:other.invalid", 50, None)
    with pytest.raises(UnknownCommunityError):
        query.list_audit("did:web:other.invalid", 50, None)
    with pytest.raises(UnknownCommunityError):
        query.community_identity("did:web:other.invalid")


def _ingest_profile(
    store: ObserverStore,
    sequencer: _Sequencer,
    *,
    record: dict[str, object] | None,
    operation: str = "create",
    outcome: str = "verified",
    received_at: datetime,
) -> None:
    store.ingest(
        _delivery(
            repo=COMMUNITY_DID,
            collection=PROFILE_COLLECTION,
            rkey="self",
            cursor=sequencer.next_cursor(),
            rev=sequencer.next_rev(COMMUNITY_DID),
            record=record,
            operation=operation,
            outcome=outcome,
            received_at=received_at,
        )
    )


def _profile(display_name: str = "Homelab") -> dict[str, object]:
    return {
        "$type": PROFILE_COLLECTION,
        "displayName": display_name,
        "description": "Tiny computers, loud fans.",
        "createdAt": "2026-08-13T12:00:00Z",
    }


def test_profile_fallback_when_absent(tmp_path: Path) -> None:
    query = _query(_store(tmp_path))
    assert query.community_identity(COMMUNITY_DID) == {
        "did": COMMUNITY_DID,
        "slug": SLUG,
        "displayName": SLUG,
        "description": None,
    }


def test_valid_profile_decorates_identity(tmp_path: Path) -> None:
    store = _store(tmp_path)
    sequencer = _Sequencer()
    _ingest_profile(store, sequencer, record=_profile(), received_at=BASE_TIME)
    identity = _query(store).community_identity(COMMUNITY_DID)
    assert identity["displayName"] == "Homelab"
    assert identity["description"] == "Tiny computers, loud fans."


def test_bad_cases_fall_back_to_slug(tmp_path: Path) -> None:
    for label in ("invalid", "deleted", "unverified", "superseded"):
        store = _store(tmp_path / label)
        sequencer = _Sequencer()
        if label == "invalid":
            broken = _profile()
            del broken["displayName"]
            _ingest_profile(store, sequencer, record=broken, received_at=BASE_TIME)
        elif label == "deleted":
            _ingest_profile(store, sequencer, record=_profile(), received_at=BASE_TIME)
            _ingest_profile(
                store,
                sequencer,
                record=None,
                operation="delete",
                received_at=BASE_TIME + timedelta(seconds=1),
            )
        elif label == "unverified":
            _ingest_profile(
                store,
                sequencer,
                record=_profile(),
                outcome="unverified",
                received_at=BASE_TIME,
            )
        else:
            _ingest_profile(store, sequencer, record=_profile(), received_at=BASE_TIME)
            broken = _profile()
            del broken["displayName"]
            _ingest_profile(
                store,
                sequencer,
                record=broken,
                received_at=BASE_TIME + timedelta(seconds=1),
            )
        identity = _query(store).community_identity(COMMUNITY_DID)
        assert identity["displayName"] == SLUG, label
        assert identity["description"] is None, label


def test_audit_pagination_covers_every_row_without_repeats(tmp_path: Path) -> None:
    store = _store(tmp_path)
    sequencer = _Sequencer()
    _visible_entry(
        store,
        sequencer,
        author_did="did:web:alice.invalid",
        post_rkey="3jzfcijpj2z2a",
        submission_rkey="3jzfcijpj2z2k",
        text="audit me",
        admitted_at="2026-08-13T12:01:00Z",
        observed_at=BASE_TIME,
    )
    query = _query(store)

    seen: list[str] = []
    cursor = None
    while True:
        page = query.list_audit(COMMUNITY_DID, 2, cursor)
        seen.extend(str(item["auditRowKey"]) for item in page.items)
        cursor = page.cursor
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 3
    with pytest.raises(CursorError):
        query.list_audit(COMMUNITY_DID, 2, "bogus")
    with pytest.raises(ValidationError):
        query.list_audit(COMMUNITY_DID, 0, None)


def _tamper_high_water(store: ObserverStore) -> None:
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE projection_builds SET source_high_waters_json = '{}'"
        )


def test_current_view_refuses_a_stale_projection_but_audit_serves(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    sequencer = _Sequencer()
    _visible_entry(
        store,
        sequencer,
        author_did="did:web:alice.invalid",
        post_rkey="3jzfcijpj2z2a",
        submission_rkey="3jzfcijpj2z2k",
        text="fresh until tampered",
        admitted_at="2026-08-13T12:01:00Z",
        observed_at=BASE_TIME,
    )
    _tamper_high_water(store)
    query = _query(store)

    with pytest.raises(ProjectionUnavailableError) as caught:
        query.list_visible(COMMUNITY_DID, 50, None)
    assert caught.value.reason_code == "ingest_stale"
    assert len(query.list_audit(COMMUNITY_DID, 50, None).items) == 3


def test_incomplete_projection_refuses_both_views(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE projection_builds SET status = 'building'")
    query = _query(store)

    with pytest.raises(ProjectionUnavailableError) as visible_error:
        query.list_visible(COMMUNITY_DID, 50, None)
    assert visible_error.value.reason_code == "projection_incomplete"
    with pytest.raises(ProjectionUnavailableError):
        query.list_audit(COMMUNITY_DID, 50, None)
    with pytest.raises(ProjectionUnavailableError):
        query.community_identity(COMMUNITY_DID)
