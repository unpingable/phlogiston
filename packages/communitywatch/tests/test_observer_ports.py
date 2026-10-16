from __future__ import annotations

import inspect

from communitywatch import CommunityQuery, EventSource, SubjectResolver


def _public_callables(protocol: type[object]) -> set[str]:
    return {
        name
        for name, value in vars(protocol).items()
        if not name.startswith("_") and callable(value)
    }


def test_observer_ports_expose_reads_only() -> None:
    assert _public_callables(CommunityQuery) == {"list_visible", "list_audit"}
    assert _public_callables(EventSource) == {"read"}
    assert _public_callables(SubjectResolver) == {"resolve_exact"}

    assert tuple(inspect.signature(EventSource.read).parameters) == (
        "self",
        "after_cursor",
    )
    assert tuple(inspect.signature(SubjectResolver.resolve_exact).parameters) == (
        "self",
        "ref",
    )
    assert tuple(inspect.signature(CommunityQuery.list_visible).parameters) == (
        "self",
        "community_did",
        "limit",
        "cursor",
    )
    assert inspect.signature(CommunityQuery.list_audit) == inspect.signature(
        CommunityQuery.list_visible
    )
