"""Strict communitywatch configuration: observer settings, never credentials.

The observer TOML names the community identity, the SQLite path, and public
event-source/resolver endpoints.  It may never carry a token, password,
session, private key, credential, signing, or PDS-write field; the strict
parser rejects every unknown key, including any daemon-side setting.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from community_model import ValidationError
from community_model.identifiers import validate_did

_ALLOWED_KEYS = frozenset(
    {
        "community_did",
        "p0_bluesky_only",
        "p0_hosted_pds_origin",
        "p0_allow_bluesky",
        "p0_test_pds_origin",
        "p0_isolated_test",
        "community_slug",
        "administrator_did",
        "sqlite_path",
        "event_source_url",
        "resolver_url",
        "subject_refresh_seconds",
        "bind",
        "port",
        "page_size",
        "max_page_size",
        "stale_threshold_seconds",
    }
)
_SECRET_KEY_PARTS = (
    "token",
    "password",
    "secret",
    "private_key",
    "credential",
    "signing",
    "session",
)


class ConfigError(ValueError):
    """The observer configuration is missing, malformed, or forbidden."""


def _fail(message: str) -> None:
    raise ConfigError(message)


@dataclass(frozen=True, slots=True)
class ObserverConfig:
    """Validated observer settings; no credential field may appear here."""

    community_did: str
    community_slug: str
    sqlite_path: str
    event_source_url: str
    resolver_url: str
    administrator_did: str | None = None
    subject_refresh_seconds: int = 60
    bind: str = "127.0.0.1"
    port: int = 8080
    page_size: int = 50
    max_page_size: int = 100
    stale_threshold_seconds: int = 180
    p0_bluesky_only: bool = False
    p0_isolated_test: bool = False
    p0_test_pds_origin: str | None = None
    p0_hosted_pds_origin: str | None = None
    p0_allow_bluesky: bool = False


def _text(document: dict[str, object], key: str, default: str | None = None) -> str:
    value = document.get(key, default)
    if not isinstance(value, str) or not value:
        _fail(f"{key} must be a nonempty string")
    assert isinstance(value, str)
    return value


def _bounded_int(
    document: dict[str, object], key: str, default: int, low: int, high: int
) -> int:
    value = document.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(f"{key} must be an integer")
    assert isinstance(value, int)
    if not low <= value <= high:
        _fail(f"{key} must be between {low} and {high}")
    return value


def parse_config(document: object) -> ObserverConfig:
    """Validate one decoded TOML document, rejecting every unknown key."""

    if not isinstance(document, dict):
        _fail("communitywatch configuration must be a TOML table")
    assert isinstance(document, dict)
    unknown = set(document) - _ALLOWED_KEYS
    if unknown:
        _fail(f"unknown communitywatch configuration keys: {sorted(unknown)}")
    for key in document:
        lowered = key.lower()
        if any(part in lowered for part in _SECRET_KEY_PARTS):
            _fail(f"{key} is a credential-bearing field and is forbidden here")

    try:
        community_did = validate_did(_text(document, "community_did"))
    except ValidationError as exc:
        _fail(f"community_did is invalid: {exc}")
    slug = _text(document, "community_slug")
    if "/" in slug or "\x00" in slug:
        _fail("community_slug must be a single path segment")
    administrator_did: str | None = None
    if "administrator_did" in document:
        try:
            administrator_did = validate_did(_text(document, "administrator_did"))
        except ValidationError as exc:
            _fail(f"administrator_did is invalid: {exc}")

    page_size = _bounded_int(document, "page_size", 50, 1, 100)
    max_page_size = _bounded_int(document, "max_page_size", 100, 1, 100)
    if page_size > max_page_size:
        _fail("page_size may not exceed max_page_size")

    if not isinstance(document.get("p0_bluesky_only", False), bool):
        _fail("p0_bluesky_only must be a boolean")
    if not isinstance(document.get("p0_isolated_test", False), bool):
        _fail("p0_isolated_test must be a boolean")
    p0_allow_bluesky = document.get("p0_allow_bluesky", False)
    if not isinstance(p0_allow_bluesky, bool) or (
        p0_allow_bluesky
        and document.get("p0_hosted_pds_origin") != "https://phlogiston.social"
    ):
        _fail("p0_allow_bluesky requires boolean and exact hosted P0 origin")
    hosted_origin = document.get("p0_hosted_pds_origin")
    if hosted_origin is not None and (
        hosted_origin != "https://phlogiston.social"
        or document.get("p0_test_pds_origin") is not None
        or document.get("p0_bluesky_only", False)
    ):
        _fail(
            "controlled hosted P0 requires exact Phlogiston origin and a separate provider profile"
        )
    test_origin = document.get("p0_test_pds_origin")
    if test_origin is not None and (
        test_origin != "https://juche.social"
        or document.get("p0_bluesky_only") is not True
        or document.get("p0_isolated_test") is not True
        or document.get("bind", "127.0.0.1") not in {"127.0.0.1", "::1"}
    ):
        _fail("test PDS override requires the named isolated loopback P0 profile")
    return ObserverConfig(
        p0_bluesky_only=document.get("p0_bluesky_only", False),
        p0_isolated_test=document.get("p0_isolated_test", False),
        p0_test_pds_origin=test_origin,
        p0_hosted_pds_origin=hosted_origin,
        p0_allow_bluesky=p0_allow_bluesky,
        community_did=community_did,
        community_slug=slug,
        sqlite_path=_text(document, "sqlite_path"),
        event_source_url=_text(document, "event_source_url"),
        resolver_url=_text(document, "resolver_url"),
        administrator_did=administrator_did,
        subject_refresh_seconds=_bounded_int(
            document, "subject_refresh_seconds", 60, 1, 86_400
        ),
        bind=_text(document, "bind", "127.0.0.1"),
        port=_bounded_int(document, "port", 8080, 1, 65_535),
        page_size=page_size,
        max_page_size=max_page_size,
        stale_threshold_seconds=_bounded_int(
            document, "stale_threshold_seconds", 180, 1, 86_400
        ),
    )


def load_config(path: str | Path) -> ObserverConfig:
    """Read and strictly validate one observer TOML file."""

    try:
        with Path(path).open("rb") as handle:
            document = tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read configuration: {exc.strerror or exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("configuration is not valid TOML") from exc
    return parse_config(document)
