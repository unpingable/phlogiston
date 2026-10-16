from __future__ import annotations

from dataclasses import replace

import pytest

from community_model import ValidationError
from communitywatch_spaces_alpha import (
    DurableSyncStore,
    ReconciliationDisposition,
    ReconciliationResult,
    reconcile_qualified_states,
)
from communitywatch_spaces_alpha.transition import identify_qualified_repo_state
from spaces_support import qualified_sa4_snapshot, qualified_sa4_transition, timestamp


def _states(source, vectors):
    n = qualified_sa4_snapshot(source, vectors, "n", "2026-08-21T23:00:00Z")
    n1 = qualified_sa4_transition(
        n, source, vectors, "n1", "n-to-n1", "2026-08-21T23:00:01Z"
    )
    return n, n1


def test_durable_restart_retry_and_explicit_transition_head(
    tmp_path, sa4_source_vectors, sa4_vectors
) -> None:
    n, n1 = _states(sa4_source_vectors, sa4_vectors)
    path = tmp_path / "sync.sqlite"
    store = DurableSyncStore(path)
    identity = identify_qualified_repo_state(n)
    event = store.seed_qualified_state(
        identity, custody_ref="fixture:n", observed_at=timestamp("2026-08-21T23:00:00Z")
    )
    assert (
        store.seed_qualified_state(
            identity,
            custody_ref="fixture:n",
            observed_at=timestamp("2026-08-21T23:00:00Z"),
        )
        == event
    )
    result = reconcile_qualified_states(
        n, n1.target, transition=n1, reconciled_at=timestamp("2026-08-21T23:00:02Z")
    )
    store.record_reconciliation(result)
    head = store.head(identity)
    assert head and head.state["repoRev"] == n1.target.commit.rev
    count = store.event_count()
    store.close()
    reopened = DurableSyncStore(path)
    assert reopened.event_count() == count
    assert reopened.head(identity) == head
    reopened.close()


def test_insufficient_conflict_and_later_timestamp_do_not_replace_head(
    tmp_path, sa4_source_vectors, sa4_vectors
) -> None:
    n, n1 = _states(sa4_source_vectors, sa4_vectors)
    store = DurableSyncStore(tmp_path / "sync.sqlite")
    identity = identify_qualified_repo_state(n)
    store.seed_qualified_state(
        identity, custody_ref="fixture:n", observed_at=timestamp("2026-08-21T23:00:00Z")
    )
    before = store.head(identity)
    conflicting = replace(identity, repo_commit_hash="f" * 64)
    result = ReconciliationResult(
        identity,
        conflicting,
        ReconciliationDisposition.INSUFFICIENT_EVIDENCE,
        "same revision conflict preserved",
        timestamp("2026-08-22T23:00:00Z"),
    )
    store.record_reconciliation(result)
    assert store.head(identity) == before


def test_cursor_acquisition_and_recovery_are_evidence_not_confidence(
    tmp_path, sa4_source_vectors, sa4_vectors
) -> None:
    n, _ = _states(sa4_source_vectors, sa4_vectors)
    identity = identify_qualified_repo_state(n)
    store = DurableSyncStore(tmp_path / "sync.sqlite")
    store.seed_qualified_state(
        identity, custody_ref="fixture:n", observed_at=timestamp("2026-08-21T23:00:00Z")
    )
    store.record_cursor(
        identity,
        "opaque-cursor",
        source_ref="fixture:listRepoOps",
        observed_at=timestamp("2026-08-21T23:00:01Z"),
    )
    store.record_acquisition(
        "sha256:" + "1" * 64,
        {"status": 200, "bodySha256": "2" * 64},
        observed_at=timestamp("2026-08-21T23:00:02Z"),
    )
    store.record_recovery(
        {
            "outcome": "snapshot_only",
            "missingProvenance": ["complete_transition_batch"],
        },
        trace_id="sha256:" + "3" * 64,
        observed_at=timestamp("2026-08-21T23:00:03Z"),
    )
    assert store.event_count() == 4
    with pytest.raises(ValidationError):
        store.record_acquisition(
            "bad",
            {"Authorization": "DPoP secret"},
            observed_at=timestamp("2026-08-21T23:00:04Z"),
        )
