from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

_DID = re.compile(r"^did:(?:plc|web):[A-Za-z0-9._:%-]{1,512}$")
PAYLOAD_KEYS = frozenset({"content", "text"})
_FIELDS = frozenset(
    {
        "projection_origin",
        "community_did",
        "community_name",
        "public_base_url",
        "webhook_url",
        "webhook_payload_key",
        "poll_interval_seconds",
        "cursor_path",
    }
)


class ConfigError(ValueError):
    """The notifier configuration is invalid; the message never echoes values."""


@dataclass(frozen=True, slots=True)
class NotifyConfig:
    projection_origin: str
    community_did: str
    community_name: str
    public_base_url: str
    webhook_url: str
    webhook_payload_key: str
    poll_interval_seconds: float
    cursor_path: Path

    def __post_init__(self) -> None:
        if not _is_origin(self.projection_origin, {"http", "https"}):
            raise ConfigError("projection_origin must be an HTTP(S) origin")
        if not _DID.fullmatch(self.community_did):
            raise ConfigError("community_did must be a did:plc or did:web DID")
        name = self.community_name
        if not name.strip() or len(name) > 100 or not name.isprintable():
            raise ConfigError("community_name must be 1-100 printable characters")
        if not _is_origin(self.public_base_url, {"https"}):
            raise ConfigError("public_base_url must be an https origin")
        webhook = urlsplit(self.webhook_url)
        if (
            webhook.scheme != "https"
            or not webhook.hostname
            or webhook.username is not None
            or webhook.password is not None
            or webhook.fragment
        ):
            raise ConfigError("webhook_url must be a credential-free https URL")
        if self.webhook_payload_key not in PAYLOAD_KEYS:
            raise ConfigError('webhook_payload_key must be "content" or "text"')
        if not 1 <= self.poll_interval_seconds <= 3600:
            raise ConfigError("poll_interval_seconds must be between 1 and 3600")
        if not self.cursor_path.is_absolute():
            raise ConfigError("cursor_path must be absolute")

    @classmethod
    def load(cls, path: Path) -> NotifyConfig:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        if set(raw) != _FIELDS:
            raise ConfigError("notifier configuration fields differ")
        interval = raw["poll_interval_seconds"]
        if isinstance(interval, bool) or not isinstance(interval, int | float):
            raise ConfigError("poll_interval_seconds must be a number")
        for key in _FIELDS - {"poll_interval_seconds"}:
            if not isinstance(raw[key], str):
                raise ConfigError(f"{key} must be a string")
        return cls(
            projection_origin=raw["projection_origin"].rstrip("/"),
            community_did=raw["community_did"],
            community_name=raw["community_name"],
            public_base_url=raw["public_base_url"].rstrip("/"),
            webhook_url=raw["webhook_url"],
            webhook_payload_key=raw["webhook_payload_key"],
            poll_interval_seconds=float(interval),
            cursor_path=Path(raw["cursor_path"]),
        )


def _is_origin(value: str, schemes: set[str]) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme in schemes
        and bool(parsed.hostname)
        and parsed.path in {"", "/"}
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )
