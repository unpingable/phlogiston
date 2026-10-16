"""Strict communityd configuration: authority-side settings, never secrets.

The TOML document names the community actor, the single administrator DID, the
local ``allowed_uid`` authorization boundary, fake/real adapter selection, and
an external credential *reference*.  Secret values are never stored here; the
parser rejects unknown keys outright, including any observer-storage field.
"""

from __future__ import annotations

import re
import tomllib
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from community_model import ValidationError
from community_model.identifiers import validate_did

from .identity import validate_bluesky_pds_origin, validate_public_origin

_ADAPTERS = frozenset({"fake", "pds"})
_READER_ADAPTERS = frozenset({"fake", "pds", "pds_fixed"})
_CREDENTIAL_PROVIDERS = frozenset({"fake", "env_file"})
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_ALLOWED_KEYS = frozenset(
    {
        "community_did",
        "administrator_did",
        "community_pds_url",
        "allowed_uid",
        "reader_adapter",
        "ledger_adapter",
        "writer_adapter",
        "credential_provider",
        "credential_ref",
        "request_timeout_ms",
        "max_retries",
        "operation_journal_path",
        "authority_socket_path",
        "web_peer_uid",
        "policy_peer_uid",
        "plc_directory_url",
        "did_cache_size",
        "allow_loopback_public_endpoints",
        "integration_fault_directory",
        "p0_profile",
        "p0_hosted_pds_origin",
        "p0_allow_bluesky",
        "p0_admission_pause_path",
        "p0_test_pds_origin",
    }
)
_SECRET_KEY_PARTS = ("token", "password", "secret", "private_key")
_CREDENTIAL_REF_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*://\S+|env:[A-Z][A-Z0-9_]*)$")


class ConfigError(ValueError):
    """The daemon configuration is missing, malformed, or forbidden."""


def _fail(message: str) -> None:
    raise ConfigError(message)


def _required_text(document: dict[str, object], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        _fail(f"{key} must be a nonempty string")
    assert isinstance(value, str)
    return value


def _optional_int(document: dict[str, object], key: str, default: int) -> int:
    value = document.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(f"{key} must be an integer")
    assert isinstance(value, int)
    return value


def _validate_pds_url(value: str) -> str:
    """Require a bare HTTPS origin, or loopback HTTP for offline tests."""

    try:
        parts = urllib.parse.urlsplit(value)
    except ValueError:
        _fail("community_pds_url is not a parseable URL")
    assert parts is not None
    if parts.username is not None or parts.password is not None:
        _fail("community_pds_url must not embed userinfo")
    if parts.query or parts.fragment:
        _fail("community_pds_url must be a bare origin without query/fragment")
    host = parts.hostname
    if not host:
        _fail("community_pds_url must name a host")
    if parts.scheme == "https":
        pass
    elif parts.scheme == "http" and host in _LOOPBACK_HOSTS:
        pass
    else:
        _fail("community_pds_url must be https (loopback http only for tests)")
    if parts.path not in ("", "/"):
        _fail("community_pds_url must not carry a path")
    return value


@dataclass(frozen=True, slots=True)
class DaemonConfig:
    """Validated daemon settings; no observer path may appear here."""

    community_did: str
    administrator_did: str
    community_pds_url: str
    allowed_uid: int
    reader_adapter: str
    ledger_adapter: str
    writer_adapter: str
    credential_provider: str
    credential_ref: str
    request_timeout_ms: int = 5_000
    max_retries: int = 2
    operation_journal_path: str | None = None
    authority_socket_path: str | None = None
    web_peer_uid: int | None = None
    policy_peer_uid: int | None = None
    plc_directory_url: str = "https://plc.directory"
    did_cache_size: int = 256
    allow_loopback_public_endpoints: bool = False
    integration_fault_directory: str | None = None
    p0_profile: str | None = None
    p0_admission_pause_path: str | None = None
    p0_test_pds_origin: str | None = None
    p0_hosted_pds_origin: str | None = None
    p0_allow_bluesky: bool = False


def parse_config(document: object) -> DaemonConfig:
    """Validate one decoded TOML document, rejecting every unknown key."""

    if not isinstance(document, dict):
        _fail("communityd configuration must be a TOML table")
    assert isinstance(document, dict)
    unknown = set(document) - _ALLOWED_KEYS
    if unknown:
        _fail(f"unknown communityd configuration keys: {sorted(unknown)}")
    for key in document:
        lowered = key.lower()
        if any(part in lowered for part in _SECRET_KEY_PARTS):
            _fail(f"{key} looks like a secret value; store a reference instead")

    try:
        community_did = validate_did(_required_text(document, "community_did"))
        administrator_did = validate_did(_required_text(document, "administrator_did"))
    except ValidationError as exc:
        _fail(f"community/administrator DID is invalid: {exc}")

    community_pds_url = _validate_pds_url(_required_text(document, "community_pds_url"))

    allowed_uid = document.get("allowed_uid")
    if isinstance(allowed_uid, bool) or not isinstance(allowed_uid, int):
        _fail("allowed_uid is required and must be an integer")
    if allowed_uid < 0:
        _fail("allowed_uid must be nonnegative")

    reader_adapter = _required_text(document, "reader_adapter")
    ledger_adapter = _required_text(document, "ledger_adapter")
    writer_adapter = _required_text(document, "writer_adapter")
    if reader_adapter not in _READER_ADAPTERS:
        _fail(f"reader_adapter {reader_adapter!r} is not a supported adapter")
    for name, adapter in (
        ("ledger_adapter", ledger_adapter),
        ("writer_adapter", writer_adapter),
    ):
        if adapter not in _ADAPTERS:
            _fail(f"{name} {adapter!r} is not a supported adapter")
    if reader_adapter == "pds_fixed" and not community_pds_url.startswith(
        ("http://127.0.0.1:", "http://[::1]:", "http://localhost:")
    ):
        _fail("pds_fixed reader is allowed only for loopback tests")

    credential_provider = _required_text(document, "credential_provider")
    if credential_provider not in _CREDENTIAL_PROVIDERS:
        _fail("credential_provider must name a supported provider")
    credential_ref = _required_text(document, "credential_ref")
    if not _CREDENTIAL_REF_RE.fullmatch(credential_ref):
        _fail("credential_ref must be an external reference, never a secret value")
    if credential_provider == "env_file" and not credential_ref.startswith("env:"):
        _fail("the env_file credential provider requires an env:VARNAME reference")
    if writer_adapter == "pds" and credential_provider != "env_file":
        _fail("the pds writer adapter requires the env_file credential provider")

    request_timeout_ms = _optional_int(document, "request_timeout_ms", 5_000)
    if not 1 <= request_timeout_ms <= 60_000:
        _fail("request_timeout_ms must be between 1 and 60000")
    max_retries = _optional_int(document, "max_retries", 2)
    if not 0 <= max_retries <= 10:
        _fail("max_retries must be between 0 and 10")
    operation_journal_path = document.get("operation_journal_path")
    if operation_journal_path is not None:
        if not isinstance(operation_journal_path, str) or not operation_journal_path:
            _fail("operation_journal_path must be a nonempty absolute path")
        if not Path(operation_journal_path).is_absolute():
            _fail("operation_journal_path must be an absolute path")
    authority_socket_path = document.get("authority_socket_path")
    if authority_socket_path is not None:
        if not isinstance(authority_socket_path, str) or not authority_socket_path:
            _fail("authority_socket_path must be a nonempty absolute path")
        if not Path(authority_socket_path).is_absolute():
            _fail("authority_socket_path must be an absolute path")
    web_peer_uid = document.get("web_peer_uid")
    policy_peer_uid = document.get("policy_peer_uid")
    for name, value in (
        ("web_peer_uid", web_peer_uid),
        ("policy_peer_uid", policy_peer_uid),
    ):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            _fail(f"{name} must be a nonnegative integer")
    if web_peer_uid is not None and web_peer_uid == policy_peer_uid:
        _fail("web_peer_uid and policy_peer_uid must be distinct")
    plc_directory_url = document.get("plc_directory_url", "https://plc.directory")
    if not isinstance(plc_directory_url, str):
        _fail("plc_directory_url must be a string")
    allow_loopback = document.get("allow_loopback_public_endpoints", False)
    if not isinstance(allow_loopback, bool):
        _fail("allow_loopback_public_endpoints must be a boolean")
    try:
        plc_directory_url = validate_public_origin(
            plc_directory_url, allow_loopback=allow_loopback
        )
    except ValidationError as exc:
        _fail(f"plc_directory_url is invalid: {exc}")
    did_cache_size = _optional_int(document, "did_cache_size", 256)
    if not 1 <= did_cache_size <= 4096:
        _fail("did_cache_size must be between 1 and 4096")
    integration_fault_directory = document.get("integration_fault_directory")
    if integration_fault_directory is not None:
        if (
            not isinstance(integration_fault_directory, str)
            or not integration_fault_directory
            or not Path(integration_fault_directory).is_absolute()
            or integration_fault_directory == "/"
        ):
            _fail("integration_fault_directory must be a bounded absolute path")
        if writer_adapter != "pds" or operation_journal_path is None:
            _fail("integration faults require the PDS writer and durable journal")
    p0_profile = document.get("p0_profile")
    if p0_profile not in (None, "root_only"):
        _fail("p0_profile must be root_only when set")
    p0_allow_bluesky = document.get("p0_allow_bluesky", False)
    if not isinstance(p0_allow_bluesky, bool) or (
        p0_allow_bluesky
        and document.get("p0_hosted_pds_origin") != "https://phlogiston.social"
    ):
        _fail("p0_allow_bluesky requires boolean and exact hosted P0 origin")
    p0_hosted_pds_origin = document.get("p0_hosted_pds_origin")
    if p0_hosted_pds_origin is not None and (
        p0_hosted_pds_origin != "https://phlogiston.social"
        or p0_profile != "root_only"
        or document.get("p0_test_pds_origin") is not None
    ):
        _fail(
            "controlled hosted P0 requires exact Phlogiston origin and no test override"
        )
    p0_test_pds_origin = document.get("p0_test_pds_origin")
    if p0_test_pds_origin is not None and (
        p0_profile != "root_only"
        or not allow_loopback
        or p0_test_pds_origin != "https://juche.social"
    ):
        _fail("P0 test PDS requires the exact Juche origin and isolated test mode")
    p0_admission_pause_path = document.get("p0_admission_pause_path")
    if p0_profile == "root_only":
        if writer_adapter == "pds":
            if reader_adapter != "pds" or ledger_adapter != "pds":
                _fail("P0 real writer requires DID-resolving reader and PDS ledger")
            if p0_hosted_pds_origin is not None:
                if community_pds_url != p0_hosted_pds_origin:
                    _fail(
                        "controlled hosted community actor must use the exact configured origin"
                    )
            elif community_pds_url != p0_test_pds_origin:
                try:
                    validate_bluesky_pds_origin(community_pds_url)
                except ValidationError as exc:
                    _fail(f"P0 community actor PDS is unsupported: {exc.reason_code}")
        if operation_journal_path is None:
            _fail("P0 requires a durable operation journal")
        if (
            not isinstance(p0_admission_pause_path, str)
            or not Path(p0_admission_pause_path).is_absolute()
            or p0_admission_pause_path == "/"
        ):
            _fail("P0 requires an absolute admission pause path")
    elif p0_admission_pause_path is not None:
        _fail("P0 admission pause path requires the P0 profile")

    assert isinstance(allowed_uid, int)
    return DaemonConfig(
        community_did=community_did,
        administrator_did=administrator_did,
        community_pds_url=community_pds_url,
        allowed_uid=allowed_uid,
        reader_adapter=reader_adapter,
        ledger_adapter=ledger_adapter,
        writer_adapter=writer_adapter,
        credential_provider=credential_provider,
        credential_ref=credential_ref,
        request_timeout_ms=request_timeout_ms,
        max_retries=max_retries,
        operation_journal_path=operation_journal_path,
        authority_socket_path=authority_socket_path,
        web_peer_uid=web_peer_uid,
        policy_peer_uid=policy_peer_uid,
        plc_directory_url=plc_directory_url,
        did_cache_size=did_cache_size,
        allow_loopback_public_endpoints=allow_loopback,
        integration_fault_directory=integration_fault_directory,
        p0_profile=p0_profile,
        p0_admission_pause_path=p0_admission_pause_path,
        p0_test_pds_origin=p0_test_pds_origin,
        p0_hosted_pds_origin=p0_hosted_pds_origin,
        p0_allow_bluesky=p0_allow_bluesky,
    )


def load_config(path: str | Path) -> DaemonConfig:
    """Read and strictly validate one daemon TOML file."""

    try:
        with Path(path).open("rb") as handle:
            document = tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read configuration: {exc.strerror or exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("configuration is not valid TOML") from exc
    return parse_config(document)
