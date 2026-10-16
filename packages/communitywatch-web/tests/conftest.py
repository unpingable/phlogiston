"""Pytest fixtures for the web AppView package tests.

Helpers live in ``web_support`` (imported under a unique module name so the
flat pytest ``sys.path`` namespace never collides with sibling packages).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from communitywatch import ObserverStore, ProjectionQuery
from communitywatch_web.app import WebApp
from tests.web_support import (
    APP_TIME,
    COMMUNITY_DID,
    SLUG,
    seed_observer_db,
)

_REFS: dict[Path, dict[str, object]] = {}


@pytest.fixture()
def seeded_db(tmp_path: Path) -> Path:
    path = tmp_path / "observer.sqlite3"
    _REFS[path] = seed_observer_db(path)
    return path


@pytest.fixture()
def refs(seeded_db: Path) -> dict[str, object]:
    """Record refs the seeder produced, for permalink assertions."""

    return _REFS[seeded_db]


@pytest.fixture()
def app(seeded_db: Path) -> WebApp:
    store = ObserverStore(seeded_db, community_did=COMMUNITY_DID, read_only=True)
    query = ProjectionQuery(store, slug=SLUG)
    return WebApp(
        query,
        community_did=COMMUNITY_DID,
        slug=SLUG,
        stale_threshold_seconds=0,
        now=lambda: APP_TIME,
    )
