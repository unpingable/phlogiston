"""Narrow synchronous ports owned by the detect-only observer package."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from community_model import EventBatch, IncomingDelivery, Page, RecordRef, ResolveResult


@runtime_checkable
class EventSource(Protocol):
    """Read a durable batch after an opaque source cursor.

    Async transports remain an adapter detail; the indexer's model boundary is
    deliberately synchronous and batch-shaped.
    """

    def read(self, after_cursor: str | None) -> EventBatch[IncomingDelivery]: ...


@runtime_checkable
class SubjectResolver(Protocol):
    """Resolve exactly one URI+CID without exposing a write-capable client."""

    def resolve_exact(self, ref: RecordRef) -> ResolveResult: ...


@runtime_checkable
class CommunityQuery(Protocol):
    """Read immutable current/audit projections for one community."""

    def list_visible(
        self, community_did: str, limit: int, cursor: str | None
    ) -> Page[Mapping[str, object]]: ...

    def list_audit(
        self, community_did: str, limit: int, cursor: str | None
    ) -> Page[Mapping[str, object]]: ...
