"""Offline observer adapters used by M2 fixtures and later vertical tests."""

from __future__ import annotations

from dataclasses import dataclass, field

from community_model import (
    EventBatch,
    IncomingDelivery,
    RecordRef,
    ResolveResult,
    ValidationError,
)


@dataclass(slots=True)
class FakeEventSource:
    """Finite cursor-addressed delivery source with deterministic batches."""

    deliveries: tuple[IncomingDelivery, ...]
    batch_size: int = 100
    calls: list[str | None] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.deliveries = tuple(self.deliveries)
        if self.batch_size < 1:
            raise ValueError("batch_size must be positive")
        cursors = [delivery.cursor for delivery in self.deliveries]
        if len(cursors) != len(set(cursors)):
            raise ValueError("fake source cursors must be unique")

    def read(self, after_cursor: str | None) -> EventBatch[IncomingDelivery]:
        self.calls.append(after_cursor)
        start = 0
        if after_cursor is not None:
            try:
                start = next(
                    index + 1
                    for index, delivery in enumerate(self.deliveries)
                    if delivery.cursor == after_cursor
                )
            except StopIteration as exc:
                raise ValidationError(
                    "schema_invalid", "unknown fake source cursor"
                ) from exc
        items = self.deliveries[start : start + self.batch_size]
        next_cursor = items[-1].cursor if items else after_cursor
        return EventBatch(items=items, next_cursor=next_cursor)


@dataclass(slots=True)
class FakeSubjectResolver:
    """Exact-reference resolver whose results are supplied by the fixture."""

    results: dict[RecordRef, list[ResolveResult]]
    calls: list[RecordRef] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.results = {
            reference: list(values) for reference, values in self.results.items()
        }

    def resolve_exact(self, ref: RecordRef) -> ResolveResult:
        self.calls.append(ref)
        queue = self.results.get(ref)
        if not queue:
            raise ValidationError(
                "reference_missing", "fake resolver has no result for exact reference"
            )
        result = queue.pop(0)
        if result.requested != ref:
            raise AssertionError(
                "fake resolver result does not match requested reference"
            )
        return result
