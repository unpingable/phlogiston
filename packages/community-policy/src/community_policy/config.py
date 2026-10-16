from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from community_model import ValidationError
from community_model.identifiers import validate_did


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    community_did: str
    observer_origin: str
    authority_socket: Path
    state_path: Path
    poll_interval_seconds: float = 5.0
    request_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        validate_did(self.community_did)
        parsed = urlsplit(self.observer_origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValidationError(
                "schema_invalid", "observer_origin must be an HTTP(S) origin"
            )
        if not self.authority_socket.is_absolute() or not self.state_path.is_absolute():
            raise ValidationError(
                "schema_invalid", "socket and state paths must be absolute"
            )
        if self.poll_interval_seconds <= 0 or self.request_timeout_seconds <= 0:
            raise ValidationError("schema_invalid", "policy timeouts must be positive")

    @classmethod
    def load(cls, path: Path) -> PolicyConfig:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        expected = {
            "community_did",
            "observer_origin",
            "authority_socket",
            "state_path",
            "poll_interval_seconds",
            "request_timeout_seconds",
        }
        if set(raw) != expected:
            raise ValidationError(
                "schema_invalid", "policy configuration fields differ"
            )
        return cls(
            community_did=str(raw["community_did"]),
            observer_origin=str(raw["observer_origin"]).rstrip("/"),
            authority_socket=Path(str(raw["authority_socket"])),
            state_path=Path(str(raw["state_path"])),
            poll_interval_seconds=float(raw["poll_interval_seconds"]),
            request_timeout_seconds=float(raw["request_timeout_seconds"]),
        )
