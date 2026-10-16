"""Read-only store contract: the web layer can never mutate the database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from community_model import PortUnavailableError, ValidationError
from communitywatch import ObserverStore, ProjectionQuery, ReadOnlyStoreError
from tests.web_support import COMMUNITY_DID, SLUG


def test_read_only_store_serves_reads(seeded_db: Path) -> None:
    store = ObserverStore(seeded_db, community_did=COMMUNITY_DID, read_only=True)
    query = ProjectionQuery(store, slug=SLUG)
    assert len(query.list_visible(COMMUNITY_DID, 100, None).items) == 1
    assert query.projection_state().status == "complete"
    assert store.counts()["audit_index"] == 11
    assert store.projection_snapshot()["community_entries"]


def test_read_only_store_rejects_every_write_path(seeded_db: Path) -> None:
    store = ObserverStore(seeded_db, community_did=COMMUNITY_DID, read_only=True)
    with pytest.raises(ReadOnlyStoreError):
        store.rebuild()
    with pytest.raises(ReadOnlyStoreError):
        store.ingest_batch(())
    with pytest.raises(ReadOnlyStoreError):
        store.ingest(())
    with store.read_connection() as connection:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO meta(key, value) VALUES ('k', 'v')")
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("PRAGMA user_version = 2")
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM audit_index")


def test_read_only_open_never_creates_a_database(tmp_path: Path) -> None:
    with pytest.raises(PortUnavailableError):
        ObserverStore(
            tmp_path / "absent.sqlite3",
            community_did=COMMUNITY_DID,
            read_only=True,
        )
    assert not (tmp_path / "absent.sqlite3").exists()


def test_read_only_open_rejects_a_newer_schema(tmp_path: Path) -> None:
    path = tmp_path / "observer.sqlite3"
    ObserverStore(
        path,
        community_did=COMMUNITY_DID,
        administrator_did="did:web:admin.invalid",
    )
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 99")
        connection.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
    with pytest.raises(ValidationError, match="schema_incompatible"):
        ObserverStore(path, community_did=COMMUNITY_DID, read_only=True)


def test_writable_store_still_requires_the_administrator(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="administrator_did"):
        ObserverStore(tmp_path / "observer.sqlite3", community_did=COMMUNITY_DID)
