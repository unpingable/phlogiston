from __future__ import annotations

from pathlib import Path

import pytest

from community_model import ValidationError
from communitywatch import ObserverStore
from communitywatch_archive.export import export_generation, sealed_manifest
from communitywatch_archive.gates import (
    covered_sequence_max,
    load_hot_facts,
    load_merged_facts,
    reduce_facts,
)
from communitywatch_archive.layout import ArtifactRoot, read_pointer, read_receipt
from communitywatch_archive.lifecycle import (
    accept_generation,
    prune_generation,
    recover,
)
from communitywatch_archive.observerdb import (
    connect_maintenance,
    connect_readonly,
)
from conftest import (
    ADMIN_DID,
    COMMUNITY_DID,
    SOURCE_B,
    make_delivery,
    make_quarantined,
    make_store,
)

CONFIG = {"community_did": COMMUNITY_DID, "administrator_did": ADMIN_DID}


def _export_accept(db_path: Path, artifacts: Path, token: str) -> str:
    result = export_generation(db_path, artifacts, token=token)
    accept_generation(db_path, artifacts, result.generation_id, **CONFIG)
    return result.generation_id


def _archive_lifecycle(db_path: Path, generation_id: str) -> str:
    with connect_readonly(db_path) as connection:
        row = connection.execute(
            """
            SELECT lifecycle FROM archive_generations
            WHERE archive_generation_id = ?
            """,
            (generation_id,),
        ).fetchone()
    assert row is not None
    return str(row["lifecycle"])


def test_accept_and_prune_require_sealing_first(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    _, db_path, artifacts = populated
    ArtifactRoot(artifacts).ensure()
    with pytest.raises(ValidationError, match="archive_generation_missing"):
        accept_generation(db_path, artifacts, "gen-00000000000000000005-nope", **CONFIG)
    with pytest.raises(ValidationError, match="archive_generation_missing"):
        prune_generation(db_path, artifacts, "gen-00000000000000000005-nope")


def test_prune_refused_before_acceptance(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    _, db_path, artifacts = populated
    result = export_generation(db_path, artifacts, token="g1")
    with pytest.raises(ValidationError, match="archive_prune_forbidden"):
        prune_generation(db_path, artifacts, result.generation_id)


def test_acceptance_writes_receipt_pointer_and_sqlite(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    _, db_path, artifacts = populated
    generation_id = _export_accept(db_path, artifacts, "g1")
    root = ArtifactRoot(artifacts)
    pointer = read_pointer(root)
    receipt = read_receipt(root, generation_id)
    assert pointer is not None and receipt is not None
    assert pointer["archiveGenerationId"] == generation_id
    assert pointer["receiptDigest"] == receipt[1]
    assert pointer["pointerGeneration"] == 1
    assert (
        receipt[0]["manifestIdentity"]
        == (sealed_manifest(root, generation_id)["manifestIdentity"])
    )
    assert _archive_lifecycle(db_path, generation_id) == "accepted"
    # Retry is idempotent and returns the same receipt digest.
    again = accept_generation(db_path, artifacts, generation_id, **CONFIG)
    assert again.receipt_digest == receipt[1]
    assert again.pointer_generation == 1


def test_acceptance_refuses_a_tampered_artifact(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    _, db_path, artifacts = populated
    result = export_generation(db_path, artifacts, token="g1")
    target = next(result.sealed_dir.rglob("*.parquet"))
    payload = bytearray(target.read_bytes())
    payload[-10] ^= 0xFF
    target.write_bytes(bytes(payload))
    with pytest.raises(ValidationError, match="archive_hash_mismatch"):
        accept_generation(db_path, artifacts, result.generation_id, **CONFIG)
    assert read_pointer(ArtifactRoot(artifacts)) is None
    assert _archive_lifecycle(db_path, result.generation_id) == "sealed"


def test_sealed_but_unaccepted_recovers_with_prior_pointer_unchanged(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    store, db_path, artifacts = populated
    first = _export_accept(db_path, artifacts, "g1")
    store.ingest(make_delivery("mod_action", cursor="4", rev="3jzfcijpj2z2f"))
    second = export_generation(db_path, artifacts, token="g2")
    assert _archive_lifecycle(db_path, second.generation_id) == "sealed"

    report = recover(db_path, artifacts)
    assert report.disagreements == ()
    assert report.reconciled_accepted == ()
    pointer = read_pointer(ArtifactRoot(artifacts))
    assert pointer is not None
    assert pointer["archiveGenerationId"] == first
    assert pointer["pointerGeneration"] == 1


def test_crash_after_receipt_is_recovered_idempotently(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    _, db_path, artifacts = populated
    result = export_generation(db_path, artifacts, token="g1")
    with pytest.raises(RuntimeError, match="injected failure"):
        accept_generation(
            db_path, artifacts, result.generation_id, fail_before_pointer=True, **CONFIG
        )
    root = ArtifactRoot(artifacts)
    receipt = read_receipt(root, result.generation_id)
    assert receipt is not None
    assert read_pointer(root) is None
    with pytest.raises(ValidationError, match="archive_prune_forbidden"):
        prune_generation(db_path, artifacts, result.generation_id)

    report = recover(db_path, artifacts)
    assert report.reconciled_accepted == (result.generation_id,)
    pointer = read_pointer(root)
    assert pointer is not None and pointer["receiptDigest"] == receipt[1]
    # A second recovery is a no-op and pruning now passes every gate.
    assert recover(db_path, artifacts).reconciled_accepted == ()
    pruned = prune_generation(db_path, artifacts, result.generation_id)
    assert pruned.pruned_sequence == 5


def test_crash_after_pointer_switch_is_recovered_idempotently(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    _, db_path, artifacts = populated
    result = export_generation(db_path, artifacts, token="g1")
    with pytest.raises(RuntimeError, match="injected failure"):
        accept_generation(
            db_path,
            artifacts,
            result.generation_id,
            fail_before_reconcile=True,
            **CONFIG,
        )
    root = ArtifactRoot(artifacts)
    pointer = read_pointer(root)
    assert pointer is not None
    assert pointer["archiveGenerationId"] == result.generation_id
    assert _archive_lifecycle(db_path, result.generation_id) == "sealed"
    with pytest.raises(ValidationError, match="archive_prune_forbidden"):
        prune_generation(db_path, artifacts, result.generation_id)

    report = recover(db_path, artifacts)
    assert report.reconciled_accepted == (result.generation_id,)
    assert _archive_lifecycle(db_path, result.generation_id) == "accepted"
    assert prune_generation(db_path, artifacts, result.generation_id).deleted_rows


def test_prune_refused_while_receipt_is_missing(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    _, db_path, artifacts = populated
    generation_id = _export_accept(db_path, artifacts, "g1")
    root = ArtifactRoot(artifacts)
    root.receipt_path(generation_id).unlink()
    with pytest.raises(ValidationError, match="archive_prune_forbidden"):
        prune_generation(db_path, artifacts, generation_id)
    # Recovery must not silently paper over the missing receipt.
    report = recover(db_path, artifacts)
    assert report.reconciled_accepted == ()
    assert read_pointer(root) is not None
    with pytest.raises(ValidationError, match="archive_prune_forbidden"):
        prune_generation(db_path, artifacts, generation_id)


def test_prune_failure_rolls_back_and_retry_is_idempotent(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    store, db_path, artifacts = populated
    generation_id = _export_accept(db_path, artifacts, "g1")
    before = store.counts()
    with pytest.raises(RuntimeError, match="injected failure"):
        prune_generation(db_path, artifacts, generation_id, fail_before_commit=True)
    assert store.counts() == before
    with connect_readonly(db_path) as connection:
        row = connection.execute(
            """
            SELECT verified_prune_sequence FROM archive_generations
            WHERE archive_generation_id = ?
            """,
            (generation_id,),
        ).fetchone()
        assert row is not None and row["verified_prune_sequence"] is None

    pruned = prune_generation(db_path, artifacts, generation_id)
    assert not pruned.already_pruned
    assert pruned.deleted_rows["event_receipts"] == 3
    assert pruned.deleted_rows["quarantined_deliveries"] == 1
    assert pruned.deleted_rows["subject_observations"] == 1
    retry = prune_generation(db_path, artifacts, generation_id)
    assert retry.already_pruned
    assert retry.deleted_rows == {}


def test_prune_deletes_only_covered_rows_and_gcs_unreferenced_variants(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    artifacts = tmp_path / "artifacts"
    shared = make_delivery("submit", cursor="1", rev="3jzfcijpj2z2c")
    store.ingest(shared)
    store.ingest(make_delivery("admission", cursor="2", rev="3jzfcijpj2z2d"))
    generation_id = _export_accept(store.path, artifacts, "g1")

    # Re-delivery of the identical envelope by a second source: one stable
    # variant, with receipts on both sides of the cut.
    duplicate = make_delivery(
        "submit", cursor="10", rev="3jzfcijpj2z2c", source=SOURCE_B
    )
    result = store.ingest(duplicate)
    assert result.duplicate is False
    shared_variant = result.key

    prune_generation(store.path, artifacts, generation_id)
    with connect_readonly(store.path) as connection:
        receipts = connection.execute(
            "SELECT source, cursor, event_variant_key FROM event_receipts"
        ).fetchall()
        assert [(row["source"], row["cursor"]) for row in receipts] == [
            (SOURCE_B, "10")
        ]
        variants = {
            row["event_variant_key"]
            for row in connection.execute("SELECT event_variant_key FROM repo_events")
        }
        # The variant referenced by the retained tail row survives; the
        # fully covered admission variant is garbage-collected.
        assert variants == {shared_variant}


def test_rebuild_from_accepted_history_plus_tail_matches_pre_prune(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    store, db_path, artifacts = populated
    pre_export = load_hot_facts(db_path)
    pre_projection = reduce_facts(pre_export, **CONFIG)
    pre_snapshot = store.projection_snapshot()

    generation_id = _export_accept(db_path, artifacts, "g1")
    prune_generation(db_path, artifacts, generation_id)
    with connect_readonly(db_path) as connection:
        assert (
            connection.execute("SELECT count(*) FROM event_receipts").fetchone()[0] == 0
        )

    merged = load_merged_facts(db_path, artifacts)
    assert merged.quarantines == pre_export.quarantines
    post_projection = reduce_facts(merged, **CONFIG)
    assert post_projection == pre_projection
    # Pruning must not disturb the committed current projection.
    assert store.projection_snapshot() == pre_snapshot


def test_rebuild_rejects_a_gap_in_accepted_tiling(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    store, db_path, artifacts = populated
    first = _export_accept(db_path, artifacts, "g1")
    store.ingest(make_delivery("mod_action", cursor="4", rev="3jzfcijpj2z2f"))
    second = _export_accept(db_path, artifacts, "g2")
    assert covered_sequence_max(db_path, ArtifactRoot(artifacts)) == 6
    # Accepting the successor supersedes the prior last-good generation.
    assert _archive_lifecycle(db_path, first) == "superseded"

    with connect_maintenance(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            UPDATE archive_generations SET lifecycle = 'quarantined'
            WHERE archive_generation_id = ?
            """,
            (first,),
        )
        connection.commit()
    with pytest.raises(ValidationError, match="archive_sequence_gap"):
        load_merged_facts(db_path, artifacts)
    assert _archive_lifecycle(db_path, second) == "accepted"


def test_quarantine_and_duplicate_and_conflict_fixture_parity(
    tmp_path: Path,
) -> None:
    """Duplicate/conflicting/quarantined/late data agree across the seam."""

    store = make_store(tmp_path)
    artifacts = tmp_path / "artifacts"
    store.ingest(make_delivery("submit", cursor="1", rev="3jzfcijpj2z2c"))
    # Same envelope from a second source: duplicate testimony, one variant.
    store.ingest(
        make_delivery("submit", cursor="7", rev="3jzfcijpj2z2c", source=SOURCE_B)
    )
    # Conflicting payload under one semantic identity: two variants.
    store.ingest(
        make_delivery(
            "submit",
            cursor="2",
            rev="3jzfcijpj2z2c",
            record={"$type": "app.phlogiston.community.submit", "text": "forged"},
        )
    )
    store.ingest(make_quarantined(cursor="3"))
    generation_id = _export_accept(store.path, artifacts, "g1")

    hot = load_hot_facts(store.path)
    merged = load_merged_facts(store.path, artifacts)
    assert merged.events == hot.events
    assert merged.quarantines == hot.quarantines
    assert len([event for event in hot.events if "submit" in event.collection]) == 2
    assert len(hot.quarantines) == 1
    prune_generation(store.path, artifacts, generation_id)
    assert load_merged_facts(store.path, artifacts) == merged
