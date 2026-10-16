"""Atomic, content-addressed publication of already-compiled public feeds."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from community_space_feed import PublishedProjectionFeed


@dataclass(frozen=True, slots=True)
class PublishedGeneration:
    generation_id: str
    generation_directory: Path
    ordinary_sha256: str
    audit_sha256: str


class AtomicProjectionPublisher:
    """Publish one immutable pair, then swap one local generation pointer."""

    def publish(
        self,
        root: str | Path,
        ordinary: PublishedProjectionFeed,
        audit: PublishedProjectionFeed,
    ) -> PublishedGeneration:
        if not isinstance(ordinary, PublishedProjectionFeed) or not isinstance(
            audit, PublishedProjectionFeed
        ):
            raise TypeError("atomic publisher requires typed public feeds")
        ordinary.validate_integrity()
        audit.validate_integrity()
        if ordinary.community_identity_id != audit.community_identity_id:
            raise ValueError("publication channels belong to different communities")
        ordinary_bytes = ordinary.to_bytes()
        audit_bytes = audit.to_bytes()
        ordinary_sha = _sha(ordinary_bytes)
        audit_sha = _sha(audit_bytes)
        generation_id = _sha(
            f"scv0-live-publication/1\0{ordinary_sha}\0{audit_sha}".encode()
        )
        base = Path(root)
        generations = base / "generations"
        generations.mkdir(parents=True, mode=0o755, exist_ok=True)
        target = generations / generation_id.removeprefix("sha256:")
        if target.exists():
            _verify_existing(target, ordinary_bytes, audit_bytes)
        else:
            temporary = generations / f".{target.name}.{os.getpid()}.tmp"
            temporary.mkdir(mode=0o755)
            try:
                _write(temporary / "ordinary.json", ordinary_bytes)
                _write(temporary / "audit.json", audit_bytes)
                manifest = json.dumps(
                    {
                        "generationId": generation_id,
                        "ordinarySha256": ordinary_sha,
                        "auditSha256": audit_sha,
                        "ordinaryFeedId": ordinary.feed_id,
                        "auditFeedId": audit.feed_id,
                        "claimsUpgraded": False,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                _write(temporary / "manifest.json", manifest)
                _fsync_dir(temporary)
                os.replace(temporary, target)
                _fsync_dir(generations)
            finally:
                if temporary.exists():
                    for child in temporary.iterdir():
                        child.unlink()
                    temporary.rmdir()
        pointer = base / f".current.{os.getpid()}.{target.name}"
        try:
            pointer.symlink_to(Path("generations") / target.name)
            os.replace(pointer, base / "current")
            _fsync_dir(base)
        finally:
            if pointer.exists() or pointer.is_symlink():
                pointer.unlink()
        return PublishedGeneration(generation_id, target, ordinary_sha, audit_sha)


def _write(path: Path, value: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _verify_existing(target: Path, ordinary: bytes, audit: bytes) -> None:
    if (target / "ordinary.json").read_bytes() != ordinary or (
        target / "audit.json"
    ).read_bytes() != audit:
        raise ValueError("content-addressed publication generation conflicts")


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


__all__ = ["AtomicProjectionPublisher", "PublishedGeneration"]
