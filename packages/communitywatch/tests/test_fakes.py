from __future__ import annotations

from datetime import UTC, datetime

import pytest

from community_model import IncomingDelivery, RecordRef, ResolveResult, ValidationError
from communitywatch import FakeEventSource, FakeSubjectResolver


def _delivery(cursor: str) -> IncomingDelivery:
    return IncomingDelivery(
        source="fixture",
        cursor=cursor,
        source_event_time=None,
        received_at=datetime(2026, 7, 10, tzinfo=UTC),
        raw_envelope={"cursor": cursor},
        trust_mode="test_fixture",
        verification_outcome="verified",
        verification_method="fixture",
        verifier_version="1",
    )


def test_fake_event_source_pages_by_opaque_cursor() -> None:
    source = FakeEventSource(
        deliveries=(_delivery("a"), _delivery("b"), _delivery("c")),
        batch_size=2,
    )
    first = source.read(None)
    assert [item.cursor for item in first.items] == ["a", "b"]
    assert first.next_cursor == "b"
    second = source.read(first.next_cursor)
    assert [item.cursor for item in second.items] == ["c"]
    assert source.calls == [None, "b"]
    with pytest.raises(ValidationError):
        source.read("unknown")


def test_fake_subject_resolver_is_exact_and_scripted() -> None:
    reference = RecordRef(
        uri="at://did:web:alice.invalid/app.bsky.feed.post/3jzfcijpj2z2a",
        cid="bafyreic7cldbweyx7ta42gvymb5xkglmqauaawvyxsoqmtxfowrudsavli",
    )
    result = ResolveResult(
        status="missing",
        requested=reference,
        current_cid=None,
        record=None,
        checked_at=datetime(2026, 7, 10, tzinfo=UTC),
        trust_mode="test_fixture",
        verification_outcome="verified",
        resolution_method="fixture",
        resolver_version="1",
    )
    resolver = FakeSubjectResolver({reference: [result]})
    assert resolver.resolve_exact(reference) == result
    assert resolver.calls == [reference]
    with pytest.raises(ValidationError):
        resolver.resolve_exact(reference)
