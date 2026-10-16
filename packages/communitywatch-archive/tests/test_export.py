from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

import pytest

from community_model import ValidationError
from communitywatch import ObserverStore
from communitywatch_archive.export import (
    export_generation,
    sealed_manifest,
    validate_generation,
)
from communitywatch_archive.layout import ArtifactRoot
from communitywatch_archive.observerdb import connect_readonly
from conftest import (
    ADMIN_DID,
    BASE_TIME,
    COMMUNITY_DID,
    SOURCE_A,
    SOURCE_B,
    make_delivery,
    make_store,
)


def test_export_closes_prefix_and_late_arrival_enters_later_generation(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    store, db_path, artifacts = populated
    result = export_generation(db_path, artifacts, token="a1", now=str(BASE_TIME))
    manifest = result.manifest
    assert manifest["minObserverSequence"] == 1
    assert manifest["maxObserverSequence"] == 5
    assert manifest["sourceHighWaters"] == {SOURCE_A: "3", SOURCE_B: "9"}
    assert (result.sealed_dir / "manifest.json").is_file()
    assert not (artifacts / "staging" / result.generation_id).exists()

    # A late arrival has an older source/signed time but a later observer
    # sequence, so it stays in the SQLite tail and enters a later generation.
    store.ingest(
        make_delivery(
            "mod_action",
            cursor="4",
            rev="3jzfcijpj2z2f",
            source_event_time=BASE_TIME - timedelta(days=30),
            received_at=BASE_TIME + timedelta(seconds=4),
        )
    )
    with pytest.raises(ValidationError, match="archive_pending_generation"):
        export_generation(db_path, artifacts, token="b2")

    from communitywatch_archive.lifecycle import accept_generation

    accept_generation(
        db_path,
        artifacts,
        result.generation_id,
        community_did=COMMUNITY_DID,
        administrator_did=ADMIN_DID,
    )
    later = export_generation(db_path, artifacts, token="b2", now=str(BASE_TIME))
    assert later.manifest["minObserverSequence"] == 6
    assert later.manifest["maxObserverSequence"] == 6
    assert later.manifest["previousMaxObserverSequence"] == 5
    assert later.manifest["supersedes"] == result.generation_id


def test_export_partitions_by_observer_received_time(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    store.ingest(
        make_delivery(
            "submit",
            cursor="1",
            rev="3jzfcijpj2z2c",
            source_event_time=BASE_TIME - timedelta(days=10),
            received_at=BASE_TIME,
        )
    )
    result = export_generation(store.path, tmp_path / "artifacts", token="p1")
    partition_day = BASE_TIME.isoformat()[:10]
    source_day = (BASE_TIME - timedelta(days=10)).isoformat()[:10]
    receipt_files = [
        entry["path"] for entry in result.manifest["tables"]["receipts"]["files"]
    ]
    assert receipt_files == [f"receipts/received_at_day={partition_day}/part-0.parquet"]
    assert source_day not in receipt_files[0]


def test_export_refuses_mismatched_declared_high_waters(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    _, db_path, artifacts = populated
    with pytest.raises(ValidationError, match="archive_high_water_mismatch"):
        export_generation(db_path, artifacts, high_waters={SOURCE_A: "1"})
    with pytest.raises(ValidationError, match="archive_high_water_mismatch"):
        export_generation(
            db_path,
            artifacts,
            high_waters={SOURCE_A: "3", SOURCE_B: "unknown-cursor"},
        )


def test_export_refuses_when_committed_cursor_lacks_custody(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    """A committed cursor with no custody row fails explicitly, not silently."""

    _, db_path, artifacts = populated
    from communitywatch_archive.observerdb import connect_maintenance

    with connect_maintenance(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM event_receipts WHERE source = ? AND cursor = ?",
            (SOURCE_B, "9"),
        )
        connection.commit()
    with pytest.raises(ValidationError, match="archive_high_water_unknown"):
        export_generation(db_path, artifacts)


def test_export_without_new_occurrences_refused(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    _, db_path, artifacts = populated
    result = export_generation(db_path, artifacts, token="e1")
    from communitywatch_archive.lifecycle import accept_generation

    accept_generation(
        db_path,
        artifacts,
        result.generation_id,
        community_did=COMMUNITY_DID,
        administrator_did=ADMIN_DID,
    )
    with pytest.raises(ValidationError, match="archive_nothing_to_export"):
        export_generation(db_path, artifacts, token="e2")


def test_manifest_validation_catches_partition_tampering(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    _, db_path, artifacts = populated
    result = export_generation(db_path, artifacts, token="t1")
    sealed = result.sealed_dir

    receipt_file = sealed / "receipts" / f"received_at_day={BASE_TIME.isoformat()[:10]}"
    target = receipt_file / "part-0.parquet"
    payload = bytearray(target.read_bytes())
    payload[-10] ^= 0xFF
    target.write_bytes(bytes(payload))
    with pytest.raises(ValidationError, match="archive_hash_mismatch"):
        validate_generation(sealed)


def test_manifest_validation_rejects_unknown_schema_version(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    _, db_path, artifacts = populated
    result = export_generation(db_path, artifacts, token="t2")
    manifest_path = result.sealed_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["manifestVersion"] = 99
    manifest_path.write_bytes(json.dumps(manifest).encode())
    with pytest.raises(ValidationError, match="archive_schema_rejected"):
        validate_generation(result.sealed_dir)


def test_manifest_validation_rejects_identity_mismatch(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    _, db_path, artifacts = populated
    result = export_generation(db_path, artifacts, token="t3")
    manifest_path = result.sealed_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["tables"]["receipts"]["rowCount"] += 1
    manifest_path.write_bytes(json.dumps(manifest).encode())
    with pytest.raises(ValidationError, match="archive_manifest_invalid"):
        validate_generation(result.sealed_dir)


def test_seal_failure_preserves_state_and_recovery_quarantines(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    store, db_path, artifacts = populated
    first = export_generation(db_path, artifacts, token="s1")
    from communitywatch_archive.lifecycle import accept_generation, recover

    accept_generation(
        db_path,
        artifacts,
        first.generation_id,
        community_did=COMMUNITY_DID,
        administrator_did=ADMIN_DID,
    )
    store.ingest(make_delivery("mod_action", cursor="4", rev="3jzfcijpj2z2f"))
    before = store.counts()

    with pytest.raises(RuntimeError, match="injected failure"):
        export_generation(db_path, artifacts, token="s2", fail_before_rename=True)
    # The prior sealed generation and all SQLite source detail are untouched.
    assert sealed_manifest(ArtifactRoot(artifacts), first.generation_id)
    assert store.counts() == before
    staging = artifacts / "staging" / "gen-00000000000000000006-s2"
    assert staging.is_dir()

    report = recover(db_path, artifacts)
    assert report.quarantined_staging == ("gen-00000000000000000006-s2",)
    assert not staging.exists()
    assert (artifacts / "quarantined" / "gen-00000000000000000006-s2").is_dir()
    assert store.counts() == before
    with connect_readonly(db_path) as connection:
        row = connection.execute(
            """
            SELECT lifecycle FROM archive_generations
            WHERE archive_generation_id = 'gen-00000000000000000006-s2'
            """
        ).fetchone()
        assert row is not None and row["lifecycle"] == "quarantined"


def test_cross_filesystem_publication_rejected(
    populated: tuple[ObserverStore, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, db_path, artifacts = populated
    real_stat = os.stat

    def fake_stat(path: object, *args: object, **kwargs: object) -> os.stat_result:
        result = real_stat(path, *args, **kwargs)  # type: ignore[arg-type]
        if "staging" in str(path):
            fields = tuple(result)
            return os.stat_result((fields[0], fields[1], fields[2] + 1) + fields[3:])
        return result

    monkeypatch.setattr(
        "communitywatch_archive.layout.os.stat",
        fake_stat,  # type: ignore[attr-defined]
    )
    with pytest.raises(ValidationError, match="archive_cross_filesystem"):
        export_generation(db_path, artifacts, token="x1")


def test_rename_crash_semantics_are_exercised_on_the_target_filesystem(
    populated: tuple[ObserverStore, Path, Path],
) -> None:
    """A real rename on the target filesystem is atomic and recoverable."""

    _, db_path, artifacts = populated
    result = export_generation(db_path, artifacts, token="r1")
    sealed = result.sealed_dir
    assert sealed.is_dir()
    # A second rename of the same name is refused rather than overwriting.
    staging = ArtifactRoot(artifacts).staging_generation(result.generation_id)
    staging.mkdir(parents=True)
    from communitywatch_archive.layout import publish_staged

    with pytest.raises(ValidationError, match="archive_generation_conflict"):
        publish_staged(ArtifactRoot(artifacts), result.generation_id)
    staging.rmdir()
