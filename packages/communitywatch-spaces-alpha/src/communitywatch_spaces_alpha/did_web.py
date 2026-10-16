"""SA9c-web: bounded hostname-level did:web resolution provenance."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType

from community_model import PortUnavailableError, ValidationError

from .compat import (
    SA9C_AUTHORITY_DOCTRINE,
    SA9C_RESOLUTION_DOCTRINE,
    SA9C_WEB_METHOD,
    SA9C_WEB_VERSION,
)
from .did_resolution import (
    DidResolutionMethod,
    DidResolutionProvenance,
    ResolvedDidDocument,
)

DEFAULT_WEB_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_DID_DOCUMENT_BYTES = 1 << 20
DEFAULT_WEB_REDIRECTS = 3
_HEADERS = MappingProxyType(
    {
        "Accept": "application/did+ld+json, application/json",
        "Accept-Encoding": "identity",
        "User-Agent": f"communitywatch-spaces-alpha/{SA9C_WEB_VERSION}",
    }
)
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _fail(reason: str, message: str) -> None:
    raise ValidationError(reason, message)


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        _fail("spaces_did_web_invalid", "resolution time must be aware")
    return value.astimezone(UTC)


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urllib.parse.urlsplit(url)
    if not parsed.hostname:
        _fail("spaces_did_web_invalid", "DID document URL has no hostname")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValidationError("spaces_did_web_invalid", "invalid URL port") from exc
    return (
        parsed.scheme,
        parsed.hostname.lower(),
        port or (443 if parsed.scheme == "https" else 80),
    )


def _is_loopback(hostname: str) -> bool:
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def derive_atproto_did_web_url(did: str, *, development_loopback: bool = False) -> str:
    """Derive the one hostname-level document URL supported by ATProto."""

    if not isinstance(did, str) or not did.startswith("did:web:"):
        _fail("spaces_did_web_invalid", "expected a did:web identifier")
    method_id = did[len("did:web:") :]
    if not method_id or ":" in method_id or "/" in method_id:
        _fail("spaces_did_web_path_unsupported", "ATProto forbids path did:web DIDs")
    if "%" in method_id and "%3A" not in method_id:
        _fail("spaces_did_web_invalid", "did:web escaping is not canonical")
    try:
        decoded = urllib.parse.unquote(method_id, errors="strict")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            "spaces_did_web_invalid", "invalid did:web escape"
        ) from exc
    if decoded != method_id.replace("%3A", ":"):
        _fail("spaces_did_web_invalid", "only encoded port separators are supported")
    parsed = urllib.parse.urlsplit(f"https://{decoded}")
    if (
        parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.hostname
    ):
        _fail("spaces_did_web_invalid", "did:web authority is invalid")
    hostname = parsed.hostname.lower()
    try:
        hostname.encode("ascii")
        port = parsed.port
    except (UnicodeEncodeError, ValueError) as exc:
        raise ValidationError(
            "spaces_did_web_invalid", "did:web host is invalid"
        ) from exc
    if hostname.endswith(".") or (
        not _is_loopback(hostname)
        and any(not _DNS_LABEL.fullmatch(label) for label in hostname.split("."))
    ):
        _fail("spaces_did_web_invalid", "did:web hostname is noncanonical")
    is_development = _is_loopback(hostname) or port is not None
    if is_development and not development_loopback:
        _fail(
            "spaces_did_web_development_only",
            "localhost and encoded ports require explicit development mode",
        )
    if development_loopback and not _is_loopback(hostname):
        _fail(
            "spaces_did_web_development_only",
            "development mode permits only loopback hosts",
        )
    scheme = "http" if development_loopback else "https"
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = rendered_host + (f":{port}" if port is not None else "")
    return f"{scheme}://{netloc}/.well-known/did.json"


@dataclass(frozen=True, slots=True)
class DidWebRedirect:
    status: int
    source_url: str
    target_url: str


class _RedirectPolicy(urllib.request.HTTPRedirectHandler):
    def __init__(self, *, maximum: int) -> None:
        self.maximum = maximum
        self.hops: list[DidWebRedirect] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        target = urllib.parse.urljoin(req.full_url, newurl)
        if _origin(target)[0] != _origin(req.full_url)[0]:
            raise _WebRedirectRefusal("spaces_did_web_http_downgrade")
        if _origin(req.full_url) != _origin(target):
            raise _WebRedirectRefusal("spaces_did_web_cross_origin_redirect")
        if len(self.hops) >= self.maximum:
            raise _WebRedirectRefusal("spaces_did_web_redirect_limit")
        self.hops.append(DidWebRedirect(code, req.full_url, target))
        return super().redirect_request(req, fp, code, msg, headers, target)


class _WebRedirectRefusal(Exception):
    pass


class _DuplicateKey(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _document_id(body: bytes) -> str:
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValidationError(
            "spaces_did_web_document_invalid",
            "response is not unambiguous UTF-8 DID JSON",
        ) from exc
    if not isinstance(value, Mapping) or not isinstance(value.get("id"), str):
        _fail("spaces_did_web_document_invalid", "response is not a DID document")
    return value["id"]


def _receipt_id(
    *,
    expected_did: str,
    document_url: str,
    final_url: str,
    http_status: int,
    document_sha256: str,
    document_length: int,
    redirects: tuple[DidWebRedirect, ...],
    observed_at: datetime,
    timeout_seconds: float,
    maximum_document_bytes: int,
    development_loopback: bool,
    verified_claims: frozenset[str],
) -> str:
    fields = (
        "spaces-did-web-resolution-v1",
        SA9C_WEB_METHOD,
        SA9C_WEB_VERSION,
        expected_did,
        document_url,
        final_url,
        str(http_status),
        document_sha256,
        str(document_length),
        observed_at.isoformat(),
        repr(timeout_seconds),
        str(maximum_document_bytes),
        "development" if development_loopback else "webpki",
        *(f"{hop.status}:{hop.source_url}:{hop.target_url}" for hop in redirects),
        *(sorted(verified_claims)),
    )
    return "sha256:" + hashlib.sha256("\x00".join(fields).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class DidWebResolutionReceipt:
    receipt_id: str
    expected_did: str
    document_url: str
    final_url: str
    http_status: int
    document_sha256: str
    document_length: int
    redirects: tuple[DidWebRedirect, ...]
    observed_at: datetime
    timeout_seconds: float
    maximum_document_bytes: int
    development_loopback: bool
    verified_claims: frozenset[str]
    method: DidResolutionMethod = field(default=DidResolutionMethod.WEB, init=False)
    request_method: str = field(default="GET", init=False)
    request_headers: Mapping[str, str] = field(default=_HEADERS, init=False)
    automatic_retries: int = field(default=0, init=False)
    doctrine: str = field(default=SA9C_RESOLUTION_DOCTRINE, init=False)
    authority_doctrine: str = field(default=SA9C_AUTHORITY_DOCTRINE, init=False)
    historical_continuity: bool = False
    perpetual_control: bool = False
    globally_current: bool = False
    governance_authority: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", _utc(self.observed_at))
        expected_claims = {
            "did_syntax_valid",
            "document_url_derived",
            "https_acquisition_succeeded",
            "document_id_matches_requested_did",
            "exact_document_digest",
        }
        if self.development_loopback:
            expected_claims.remove("https_acquisition_succeeded")
            expected_claims.add("development_loopback_acquisition_succeeded")
        else:
            expected_claims.add("webpki_hostname_verified")
        if self.verified_claims != frozenset(expected_claims):
            _fail("spaces_did_web_receipt_invalid", "web claim set is invalid")
        if self.http_status != 200 or self.document_length <= 0:
            _fail("spaces_did_web_receipt_invalid", "web acquisition was not complete")
        if (
            _receipt_id(
                expected_did=self.expected_did,
                document_url=self.document_url,
                final_url=self.final_url,
                http_status=self.http_status,
                document_sha256=self.document_sha256,
                document_length=self.document_length,
                redirects=self.redirects,
                observed_at=self.observed_at,
                timeout_seconds=self.timeout_seconds,
                maximum_document_bytes=self.maximum_document_bytes,
                development_loopback=self.development_loopback,
                verified_claims=self.verified_claims,
            )
            != self.receipt_id
        ):
            _fail("spaces_did_web_receipt_invalid", "web receipt is not bound")
        if any(
            (
                self.historical_continuity,
                self.perpetual_control,
                self.globally_current,
                self.governance_authority,
            )
        ):
            _fail("spaces_did_web_receipt_invalid", "web receipt overclaims")


@dataclass(frozen=True, slots=True)
class DidWebResolution:
    resolved_document: ResolvedDidDocument
    receipt: DidWebResolutionReceipt

    def __post_init__(self) -> None:
        if (
            self.resolved_document.method is not DidResolutionMethod.WEB
            or self.resolved_document.method_receipt_id != self.receipt.receipt_id
            or self.resolved_document.document_sha256 != self.receipt.document_sha256
        ):
            _fail("spaces_did_web_receipt_invalid", "web output is not bound")


class DidWebResolutionError(PortUnavailableError):
    pass


class DidWebResolver:
    """One-request, zero-retry did:web resolver with a closed redirect policy."""

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_WEB_TIMEOUT_SECONDS,
        maximum_document_bytes: int = DEFAULT_MAX_DID_DOCUMENT_BYTES,
        maximum_redirects: int = DEFAULT_WEB_REDIRECTS,
        development_loopback: bool = False,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not 0 < timeout_seconds <= 60:
            _fail("spaces_did_web_policy_invalid", "timeout is outside bounds")
        if not 1 <= maximum_document_bytes <= (4 << 20):
            _fail("spaces_did_web_policy_invalid", "body limit is outside bounds")
        if not 0 <= maximum_redirects <= 10:
            _fail("spaces_did_web_policy_invalid", "redirect limit is outside bounds")
        self.timeout_seconds = float(timeout_seconds)
        self.maximum_document_bytes = maximum_document_bytes
        self.maximum_redirects = maximum_redirects
        self.development_loopback = development_loopback
        self._now = now or (lambda: datetime.now(UTC))

    def resolve(self, did: str) -> DidWebResolution:
        url = derive_atproto_did_web_url(
            did, development_loopback=self.development_loopback
        )
        redirects = _RedirectPolicy(maximum=self.maximum_redirects)
        opener = urllib.request.build_opener(redirects)
        request = urllib.request.Request(url, headers=dict(_HEADERS), method="GET")
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                final_url = response.geturl()
                if _origin(final_url) != _origin(url):
                    raise _WebRedirectRefusal("spaces_did_web_cross_origin_redirect")
                content_encoding = response.headers.get("Content-Encoding", "identity")
                if content_encoding.lower() not in {"", "identity"}:
                    _fail(
                        "spaces_did_web_content_encoding",
                        "transformed DID document bodies are prohibited",
                    )
                body = response.read(self.maximum_document_bytes + 1)
                if len(body) > self.maximum_document_bytes:
                    _fail("spaces_did_web_oversized", "DID document exceeds limit")
                declared = response.headers.get("Content-Length")
                if declared is not None:
                    try:
                        declared_length = int(declared)
                    except ValueError as exc:
                        raise ValidationError(
                            "spaces_did_web_truncated",
                            "DID document length is malformed",
                        ) from exc
                    if declared_length != len(body):
                        _fail(
                            "spaces_did_web_truncated",
                            "DID document length mismatched",
                        )
                status = response.status
        except ValidationError:
            raise
        except _WebRedirectRefusal as exc:
            raise ValidationError(str(exc), "did:web redirect was refused") from exc
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            TimeoutError,
            OSError,
        ) as exc:
            raise DidWebResolutionError(f"did:web acquisition failed: {exc}") from exc
        if status != 200:
            _fail(
                "spaces_did_web_http_status", "DID document response was not HTTP 200"
            )
        if _document_id(body) != did:
            _fail("spaces_did_web_document_id_mismatch", "returned DID differs")
        observed_at = _utc(self._now())
        digest = hashlib.sha256(body).hexdigest()
        claims = {
            "did_syntax_valid",
            "document_url_derived",
            "document_id_matches_requested_did",
            "exact_document_digest",
        }
        if self.development_loopback:
            claims.add("development_loopback_acquisition_succeeded")
            provenance = DidResolutionProvenance.DEVELOPMENT_LOOPBACK
        else:
            claims.update({"https_acquisition_succeeded", "webpki_hostname_verified"})
            provenance = DidResolutionProvenance.WEBPKI_HTTPS
        receipt_fields = {
            "expected_did": did,
            "document_url": url,
            "final_url": final_url,
            "http_status": status,
            "document_sha256": digest,
            "document_length": len(body),
            "redirects": tuple(redirects.hops),
            "observed_at": observed_at,
            "timeout_seconds": self.timeout_seconds,
            "maximum_document_bytes": self.maximum_document_bytes,
            "development_loopback": self.development_loopback,
            "verified_claims": frozenset(claims),
        }
        receipt = DidWebResolutionReceipt(
            **receipt_fields,
            receipt_id=_receipt_id(**receipt_fields),
        )
        resolved = ResolvedDidDocument(
            expected_did=did,
            document_bytes=body,
            document_sha256=digest,
            method=DidResolutionMethod.WEB,
            method_receipt_id=receipt.receipt_id,
            provenance=provenance,
            verified_claims=receipt.verified_claims,
            observed_at=observed_at,
        )
        return DidWebResolution(resolved, receipt)


__all__ = [
    "DEFAULT_MAX_DID_DOCUMENT_BYTES",
    "DEFAULT_WEB_REDIRECTS",
    "DEFAULT_WEB_TIMEOUT_SECONDS",
    "DidWebRedirect",
    "DidWebResolution",
    "DidWebResolutionError",
    "DidWebResolutionReceipt",
    "DidWebResolver",
    "derive_atproto_did_web_url",
]
