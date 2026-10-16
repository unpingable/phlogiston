"""Authority-side process adapter and finite occurrence custody.

The child command owns OAuth/DPoP session material.  This module sends only a
validated authority record over stdin and accepts one redacted JSON result.
It never retries a write.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from community_model import AuthorizationError, ValidationError, WriteFailedError
from community_model.canonical import canonical_json_bytes, validate_sha256

from .spaces_alpha import SpacesAlphaAuthorityWriter, SpacesAlphaWriteOutcome

_MAX_OUTPUT = 64 * 1024


class FileAuthorizationOccurrenceStore:
    """Append-only local consumption set; authority state, never observation."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def consume(self, authorization_id: str) -> None:
        identifier = validate_sha256(authorization_id)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        with self.path.open("a+", encoding="ascii") as handle:
            os.chmod(self.path, 0o600)
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.seek(0)
            used = {line.strip() for line in handle if line.strip()}
            if identifier in used:
                raise AuthorizationError("authorization occurrence replay")
            handle.seek(0, os.SEEK_END)
            handle.write(identifier + "\n")
            handle.flush()
            os.fsync(handle.fileno())


class RuntimeCredentialReference:
    """Require an authority-side runtime directory without reading its secrets."""

    def __init__(self, *, expected_reference: str, environment_key: str) -> None:
        self.expected_reference = expected_reference
        self.environment_key = environment_key

    def require(self, reference: str) -> str:
        if reference != self.expected_reference:
            raise ValidationError(
                "credential_reference_mismatch", "unexpected credential reference"
            )
        path = os.environ.get(self.environment_key)
        if not path or not Path(path).is_dir():
            raise ValidationError(
                "credential_reference_unavailable", "credential runtime is unavailable"
            )
        return reference


class CommandSpacesAlphaWriter(SpacesAlphaAuthorityWriter):
    def __init__(
        self, command: Sequence[str], *, timeout_seconds: float = 20.0
    ) -> None:
        if not command or any(
            not isinstance(item, str) or not item for item in command
        ):
            raise ValueError("writer command must be a nonempty argument vector")
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds

    def create_immutable(
        self,
        *,
        space_uri: str,
        repo_did: str,
        collection: str,
        rkey: str,
        record: Mapping[str, object],
    ) -> SpacesAlphaWriteOutcome:
        payload = canonical_json_bytes(
            {
                "space": space_uri,
                "actorDid": repo_did,
                "collection": collection,
                "rkey": rkey,
                "record": record,
            }
        )
        try:
            result = subprocess.run(
                self.command,
                input=payload,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise WriteFailedError("Spaces authority writer unavailable") from exc
        if result.returncode != 0 or len(result.stdout) > _MAX_OUTPUT:
            raise WriteFailedError("Spaces authority writer refused")
        try:
            decoded = json.loads(result.stdout)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise WriteFailedError(
                "Spaces authority writer returned invalid output"
            ) from exc
        if not isinstance(decoded, dict) or set(decoded) != {"uri", "cid", "created"}:
            raise WriteFailedError("Spaces authority writer returned invalid output")
        uri, cid, created = decoded["uri"], decoded["cid"], decoded["created"]
        if (
            not isinstance(uri, str)
            or not isinstance(cid, str)
            or not isinstance(created, bool)
        ):
            raise WriteFailedError("Spaces authority writer returned invalid output")
        return SpacesAlphaWriteOutcome(uri, cid, created)


__all__ = [
    "CommandSpacesAlphaWriter",
    "FileAuthorizationOccurrenceStore",
    "RuntimeCredentialReference",
]
