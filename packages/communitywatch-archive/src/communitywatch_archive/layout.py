"""Filesystem layout, durability, and custody-pointer primitives.

This module is deliberately stdlib-only so that ``import
communitywatch_archive`` never requires DuckDB or PyArrow.  The heavy
backends are confined to ``export`` (PyArrow) and ``cold`` (DuckDB).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from community_model import ValidationError, canonical_json_bytes, sha256_digest

STAGING_DIR = "staging"
SEALED_DIR = "sealed"
QUARANTINE_DIR = "quarantined"
POINTER_DIR = "pointers"
RECEIPT_DIR = "receipts"
POINTER_FILE = "last-good.json"
MANIFEST_FILE = "manifest.json"

MANIFEST_VERSION = 1
PARTITION_VERSION = 1
SCHEMA_VERSION = 1
RECEIPT_VERSION = 1
POINTER_VERSION = 1


@dataclass(frozen=True, slots=True)
class ArtifactRoot:
    """Root of the observer archive inventory on one filesystem."""

    path: Path

    def __init__(self, path: str | Path | ArtifactRoot) -> None:
        if isinstance(path, ArtifactRoot):
            path = path.path
        object.__setattr__(self, "path", Path(path))

    @property
    def staging(self) -> Path:
        return self.path / STAGING_DIR

    @property
    def sealed(self) -> Path:
        return self.path / SEALED_DIR

    @property
    def quarantined(self) -> Path:
        return self.path / QUARANTINE_DIR

    @property
    def pointers(self) -> Path:
        return self.path / POINTER_DIR

    @property
    def receipts(self) -> Path:
        return self.path / RECEIPT_DIR

    def ensure(self) -> None:
        for directory in (
            self.staging,
            self.sealed,
            self.quarantined,
            self.pointers,
            self.receipts,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def staging_generation(self, generation_id: str) -> Path:
        return self.staging / generation_id

    def sealed_generation(self, generation_id: str) -> Path:
        return self.sealed / generation_id

    def receipt_path(self, generation_id: str) -> Path:
        return self.receipts / f"acceptance-{generation_id}.json"

    @property
    def pointer_path(self) -> Path:
        return self.pointers / POINTER_FILE


def validate_generation_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("gen-")
        or any(part in value for part in ("/", "\x00", ".."))
    ):
        raise ValidationError(
            "archive_generation_invalid", "generation id must be a gen- token"
        )
    return value


def fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def fsync_tree(root: Path) -> None:
    """fsync every file under root, then every directory bottom-up."""

    directories: list[Path] = []
    for current, dirnames, filenames in os.walk(root):
        for filename in filenames:
            fsync_file(Path(current) / filename)
        directories.extend(Path(current) / name for name in dirnames)
    for directory in reversed(directories):
        fsync_dir(directory)
    fsync_dir(root)


def publish_staged(root: ArtifactRoot, generation_id: str) -> Path:
    """Atomically rename a staged generation into the sealed inventory."""

    staging = root.staging_generation(generation_id)
    sealed = root.sealed_generation(generation_id)
    if not staging.is_dir():
        raise ValidationError(
            "archive_staging_missing", f"no staged generation {generation_id}"
        )
    if sealed.exists():
        raise ValidationError(
            "archive_generation_conflict", f"sealed generation {generation_id} exists"
        )
    if os.stat(staging).st_dev != os.stat(root.sealed).st_dev:
        raise ValidationError(
            "archive_cross_filesystem",
            "refusing cross-filesystem publication of a sealed generation",
        )
    os.rename(staging, sealed)
    fsync_dir(root.sealed)
    return sealed


def quarantine_staged(root: ArtifactRoot, name: str) -> Path:
    """Move an abandoned staging directory out of the staging inventory."""

    source = root.staging / name
    target = root.quarantined / name
    if target.exists():
        raise ValidationError(
            "archive_generation_conflict", f"quarantine target {name} exists"
        )
    os.rename(source, target)
    fsync_dir(root.staging)
    fsync_dir(root.quarantined)
    return target


def write_pointer(
    root: ArtifactRoot,
    *,
    generation_id: str,
    receipt_digest: str,
    pointer_generation: int,
    switched_at: str,
) -> None:
    """Durably and atomically switch the accepted last-good pointer."""

    payload = canonical_json_bytes(
        {
            "pointerVersion": POINTER_VERSION,
            "archiveGenerationId": generation_id,
            "receiptDigest": receipt_digest,
            "pointerGeneration": pointer_generation,
            "switchedAt": switched_at,
        }
    )
    temporary = root.pointers / f".{POINTER_FILE}.tmp"
    temporary.write_bytes(payload)
    fsync_file(temporary)
    os.replace(temporary, root.pointer_path)
    fsync_dir(root.pointers)


def read_pointer(root: ArtifactRoot) -> dict[str, object] | None:
    if not root.pointer_path.exists():
        return None
    try:
        value = json.loads(root.pointer_path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "archive_pointer_invalid", "last-good pointer is not readable JSON"
        ) from exc
    if not isinstance(value, dict) or value.get("pointerVersion") != POINTER_VERSION:
        raise ValidationError(
            "archive_pointer_invalid", "last-good pointer has an unknown shape"
        )
    return value


def write_receipt(
    root: ArtifactRoot, *, generation_id: str, receipt: dict[str, object]
) -> str:
    """Write and fsync an immutable acceptance receipt; return its digest."""

    payload = canonical_json_bytes(receipt)
    digest = sha256_digest(payload)
    path = root.receipt_path(generation_id)
    if path.exists():
        existing = path.read_bytes()
        if existing != payload:
            raise ValidationError(
                "archive_receipt_conflict",
                f"acceptance receipt for {generation_id} already exists and differs",
            )
        return digest
    temporary = path.with_suffix(".json.tmp")
    temporary.write_bytes(payload)
    fsync_file(temporary)
    os.rename(temporary, path)
    fsync_dir(root.receipts)
    return digest


def read_receipt(root: ArtifactRoot, generation_id: str) -> tuple[dict, str] | None:
    """Return (receipt, digest) or None when the receipt file is absent."""

    path = root.receipt_path(generation_id)
    if not path.exists():
        return None
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(
            "archive_receipt_invalid", f"acceptance receipt for {generation_id}"
        ) from exc
    if not isinstance(value, dict) or value.get("receiptVersion") != RECEIPT_VERSION:
        raise ValidationError(
            "archive_receipt_invalid",
            f"acceptance receipt for {generation_id} has an unknown shape",
        )
    return value, sha256_digest(raw)


def generation_id_for(max_observer_sequence: int, *, token: str) -> str:
    return f"gen-{max_observer_sequence:020d}-{token}"
