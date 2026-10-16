"""Acceptance, retention, and crash recovery for sealed generations.

Acceptance writes and fsyncs an immutable receipt, atomically switches the
last-good pointer, and idempotently reconciles the SQLite archive-control
row.  Pruning stays forbidden until pointer, receipt, and SQLite state
agree, then deletes exactly the covered occurrence rows and garbage-collects
payload variants only once no retained tail row references them.  Recovery
quarantines abandoned staging and reconciles sealed/accepted state without
silently moving consumers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from community_model import ValidationError

from .export import control_row_check, sealed_manifest
from .gates import verify_query_parity, verify_rebuild_parity
from .layout import (
    RECEIPT_VERSION,
    ArtifactRoot,
    quarantine_staged,
    read_pointer,
    read_receipt,
    validate_generation_id,
    write_pointer,
    write_receipt,
)
from .observerdb import (
    archive_row,
    connect_maintenance,
    connect_readonly,
    upsert_archive_row,
    utc_now,
)

_OCCURRENCE_TABLES = (
    ("receipts", "event_receipts"),
    ("quarantine", "quarantined_deliveries"),
    ("observations", "subject_observations"),
)


@dataclass(frozen=True, slots=True)
class AcceptResult:
    generation_id: str
    receipt_digest: str
    pointer_generation: int


@dataclass(frozen=True, slots=True)
class PruneResult:
    generation_id: str
    pruned_sequence: int
    deleted_rows: dict[str, int]
    already_pruned: bool


@dataclass(frozen=True, slots=True)
class RecoverReport:
    quarantined_staging: tuple[str, ...]
    reconciled_sealed: tuple[str, ...]
    reconciled_accepted: tuple[str, ...]
    disagreements: tuple[str, ...]


def _require_agreement(
    db_path: str | Path, root: ArtifactRoot, generation_id: str
) -> dict[str, object]:
    """Prove pointer, receipt, and SQLite state agree for one generation."""

    manifest = sealed_manifest(root, generation_id)
    row = control_row_check(db_path, generation_id, manifest)
    pointer = read_pointer(root)
    receipt = read_receipt(root, generation_id)
    agreed = (
        row["lifecycle"] == "accepted"
        and row["last_good"] == 1
        and pointer is not None
        and pointer["archiveGenerationId"] == generation_id
        and receipt is not None
        and receipt[0]["archiveGenerationId"] == generation_id
        and receipt[0]["manifestIdentity"] == manifest["manifestIdentity"]
        and receipt[1] == pointer["receiptDigest"]
    )
    if not agreed:
        raise ValidationError(
            "archive_prune_forbidden",
            f"pointer, receipt, and SQLite state disagree for {generation_id}",
        )
    return manifest


def accept_generation(
    db_path: str | Path,
    artifact_root: str | Path,
    generation_id: str,
    *,
    community_did: str,
    administrator_did: str,
    now: str | None = None,
    fail_before_pointer: bool = False,
    fail_before_reconcile: bool = False,
) -> AcceptResult:
    """Prove parity, then durably accept one sealed generation.

    The receipt is written and fsynced before the pointer switches; the
    pointer switches atomically before the SQLite archive-control row is
    reconciled.  A crash at any point is recovered idempotently and never
    permits pruning while the three disagree.
    """

    generation_id = validate_generation_id(generation_id)
    root = ArtifactRoot(artifact_root)
    manifest = sealed_manifest(root, generation_id)
    row = control_row_check(db_path, generation_id, manifest)
    pointer = read_pointer(root)
    receipt = read_receipt(root, generation_id)
    if (
        row["lifecycle"] == "accepted"
        and receipt is not None
        and pointer is not None
        and pointer["archiveGenerationId"] == generation_id
        and pointer["receiptDigest"] == receipt[1]
    ):
        return AcceptResult(
            generation_id=generation_id,
            receipt_digest=receipt[1],
            pointer_generation=int(pointer["pointerGeneration"]),
        )
    if row["lifecycle"] != "sealed":
        raise ValidationError(
            "archive_lifecycle_invalid",
            f"generation {generation_id} is {row['lifecycle']}, not sealed",
        )
    if (
        receipt is not None
        and receipt[0]["manifestIdentity"] == (manifest["manifestIdentity"])
    ):
        # A receipt exists only after the parity gates passed; reuse it so a
        # retried acceptance is byte-identical rather than a rewrite.
        receipt_digest = receipt[1]
    else:
        verify_query_parity(db_path, root, generation_id)
        verify_rebuild_parity(
            db_path,
            root,
            candidate=generation_id,
            community_did=community_did,
            administrator_did=administrator_did,
        )
        receipt_digest = write_receipt(
            root,
            generation_id=generation_id,
            receipt={
                "receiptVersion": RECEIPT_VERSION,
                "archiveGenerationId": generation_id,
                "manifestIdentity": manifest["manifestIdentity"],
                "acceptedAt": now or utc_now(),
                "minObserverSequence": manifest["minObserverSequence"],
                "maxObserverSequence": manifest["maxObserverSequence"],
                "sourceHighWaters": manifest["sourceHighWaters"],
                "queryParity": True,
                "rebuildParity": True,
            },
        )
    if fail_before_pointer:
        raise RuntimeError("injected failure before pointer switch")
    if (
        pointer is not None
        and pointer["archiveGenerationId"] == generation_id
        and pointer["receiptDigest"] == receipt_digest
    ):
        # Pointer already switched by a crashed attempt; keep it unchanged.
        pointer_generation = int(pointer["pointerGeneration"])
    else:
        pointer_generation = (
            1 if pointer is None else int(pointer["pointerGeneration"]) + 1
        )
        write_pointer(
            root,
            generation_id=generation_id,
            receipt_digest=receipt_digest,
            pointer_generation=pointer_generation,
            switched_at=now or utc_now(),
        )
    if fail_before_reconcile:
        raise RuntimeError("injected failure before SQLite reconcile")
    _reconcile_accepted(db_path, generation_id, manifest)
    return AcceptResult(
        generation_id=generation_id,
        receipt_digest=receipt_digest,
        pointer_generation=pointer_generation,
    )


def _reconcile_accepted(
    db_path: str | Path, generation_id: str, manifest: dict[str, object]
) -> None:
    with connect_maintenance(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            UPDATE archive_generations SET lifecycle = 'superseded', last_good = 0
            WHERE lifecycle = 'accepted' AND archive_generation_id != ?
            """,
            (generation_id,),
        )
        upsert_archive_row(
            connection,
            generation_id=generation_id,
            manifest=manifest,
            lifecycle="accepted",
            last_good=1,
        )
        connection.commit()


def prune_generation(
    db_path: str | Path,
    artifact_root: str | Path,
    generation_id: str,
    *,
    fail_before_commit: bool = False,
) -> PruneResult:
    """Delete exactly the covered prefix and record the prune coordinate.

    Refuses unless seal, parity, acceptance receipt, last-good pointer, and
    SQLite archive-control state all agree.  The deletions and the recorded
    coordinate commit or roll back as one transaction; a payload variant is
    deleted only when no retained tail row references it.
    """

    generation_id = validate_generation_id(generation_id)
    root = ArtifactRoot(artifact_root)
    manifest = _require_agreement(db_path, root, generation_id)
    low = int(manifest["minObserverSequence"])
    high = int(manifest["maxObserverSequence"])
    deleted: dict[str, int] = {}
    with connect_maintenance(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = archive_row(connection, generation_id)
        assert row is not None
        if row["verified_prune_sequence"] is not None:
            if int(row["verified_prune_sequence"]) != high:
                raise ValidationError(
                    "archive_prune_conflict",
                    f"recorded prune coordinate disagrees with {generation_id}",
                )
            remaining = sum(
                connection.execute(
                    f"""
                    SELECT count(*) FROM {table}
                    WHERE observer_sequence BETWEEN ? AND ?
                    """,  # noqa: S608
                    (low, high),
                ).fetchone()[0]
                for _, table in _OCCURRENCE_TABLES
            )
            if remaining:
                raise ValidationError(
                    "archive_prune_conflict",
                    "prune coordinate recorded but covered rows remain",
                )
            connection.commit()
            return PruneResult(
                generation_id=generation_id,
                pruned_sequence=high,
                deleted_rows={},
                already_pruned=True,
            )
        for table, sqlite_table in _OCCURRENCE_TABLES:
            expected = int(manifest["tables"][table]["rowCount"])
            present = connection.execute(
                f"""
                SELECT count(*) FROM {sqlite_table}
                WHERE observer_sequence BETWEEN ? AND ?
                """,  # noqa: S608
                (low, high),
            ).fetchone()[0]
            if int(present) != expected:
                raise ValidationError(
                    "archive_count_mismatch",
                    f"{sqlite_table} rows in the covered range drifted",
                )
        for table, sqlite_table in _OCCURRENCE_TABLES:
            cursor = connection.execute(
                f"""
                DELETE FROM {sqlite_table}
                WHERE observer_sequence BETWEEN ? AND ?
                """,  # noqa: S608
                (low, high),
            )
            deleted[sqlite_table] = cursor.rowcount
        cursor = connection.execute(
            """
            DELETE FROM repo_events
            WHERE event_variant_key NOT IN (
                SELECT event_variant_key FROM event_receipts
                UNION
                SELECT triggering_event_variant_key FROM subject_observations
                WHERE triggering_event_variant_key IS NOT NULL
            )
            """
        )
        deleted["repo_events"] = cursor.rowcount
        cursor = connection.execute(
            """
            DELETE FROM subject_observation_variants
            WHERE subject_variant_key NOT IN (
                SELECT subject_variant_key FROM subject_observations
            )
            """
        )
        deleted["subject_observation_variants"] = cursor.rowcount
        connection.execute(
            """
            UPDATE archive_generations SET verified_prune_sequence = ?
            WHERE archive_generation_id = ? AND verified_prune_sequence IS NULL
            """,
            (high, generation_id),
        )
        if fail_before_commit:
            raise RuntimeError("injected failure before prune commit")
        connection.commit()
    return PruneResult(
        generation_id=generation_id,
        pruned_sequence=high,
        deleted_rows=deleted,
        already_pruned=False,
    )


def recover(db_path: str | Path, artifact_root: str | Path) -> RecoverReport:
    """Idempotently recover abandoned or half-published archive state.

    Unsealed staging directories are quarantined.  Sealed generations get
    their archive-control rows reconciled without moving the last-good
    pointer.  A receipt whose gates passed but whose pointer or SQLite row
    was never persisted is completed; disagreement is reported and left
    untouched so pruning stays forbidden.
    """

    root = ArtifactRoot(artifact_root)
    root.ensure()
    quarantined: list[str] = []
    reconciled_sealed: list[str] = []
    reconciled_accepted: list[str] = []
    disagreements: list[str] = []
    for staging in sorted(root.staging.iterdir()):
        if not staging.is_dir():
            continue
        target = quarantine_staged(root, staging.name)
        with connect_maintenance(db_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = archive_row(connection, staging.name)
            if row is not None and row["lifecycle"] in ("staged", "sealed"):
                connection.execute(
                    """
                    UPDATE archive_generations SET lifecycle = 'quarantined',
                        last_good = 0
                    WHERE archive_generation_id = ?
                    """,
                    (staging.name,),
                )
            connection.commit()
        quarantined.append(target.name)
    pointer = read_pointer(root)
    for sealed in sorted(root.sealed.iterdir()):
        if not sealed.is_dir():
            continue
        generation_id = sealed.name
        try:
            manifest = sealed_manifest(root, generation_id)
        except ValidationError:
            disagreements.append(f"sealed generation {generation_id} is invalid")
            continue
        with connect_readonly(db_path) as connection:
            row = archive_row(connection, generation_id)
        lifecycle = None if row is None else str(row["lifecycle"])
        if lifecycle is None or lifecycle in ("staged", "sealed"):
            with connect_maintenance(db_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                upsert_archive_row(
                    connection,
                    generation_id=generation_id,
                    manifest=manifest,
                    lifecycle="sealed",
                )
                connection.commit()
            reconciled_sealed.append(generation_id)
            lifecycle = "sealed"
        if lifecycle == "accepted":
            continue
        receipt = read_receipt(root, generation_id)
        if receipt is None:
            continue
        if receipt[0]["manifestIdentity"] != manifest["manifestIdentity"]:
            disagreements.append(
                f"acceptance receipt for {generation_id} names another manifest"
            )
            continue
        pointer_ok = (
            pointer is not None
            and pointer["archiveGenerationId"] == generation_id
            and pointer["receiptDigest"] == receipt[1]
        )
        if not pointer_ok:
            if pointer is not None and (
                pointer["archiveGenerationId"] == generation_id
            ):
                disagreements.append(
                    f"pointer digest disagrees with the receipt for {generation_id}"
                )
                continue
            # The receipt exists only after its gates passed, so completing
            # the crashed pointer switch is an idempotent redo.
            write_pointer(
                root,
                generation_id=generation_id,
                receipt_digest=receipt[1],
                pointer_generation=(
                    1 if pointer is None else int(pointer["pointerGeneration"]) + 1
                ),
                switched_at=utc_now(),
            )
            pointer = read_pointer(root)
        _reconcile_accepted(db_path, generation_id, manifest)
        reconciled_accepted.append(generation_id)
    return RecoverReport(
        quarantined_staging=tuple(quarantined),
        reconciled_sealed=tuple(reconciled_sealed),
        reconciled_accepted=tuple(reconciled_accepted),
        disagreements=tuple(disagreements),
    )
