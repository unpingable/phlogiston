"""Independent authority-side DID-to-PDS resolution for public record reads."""

from __future__ import annotations

import http.client
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from collections.abc import Callable, Mapping

from community_model import PortUnavailableError, ValidationError
from community_model.identifiers import validate_did

MAX_DID_DOCUMENT_BYTES = 1 << 20


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


class AuthorityDidResolver:
    """Resolve did:plc/did:web without consuming observer conclusions."""

    def __init__(
        self,
        *,
        plc_directory_url: str,
        timeout_seconds: float,
        cache_size: int,
        allow_loopback: bool = False,
        bluesky_only: bool = False,
        p0_test_pds_origin: str | None = None,
        p0_hosted_pds_origin: str | None = None,
        p0_allow_bluesky: bool = False,
        address_resolver: Callable[..., list[tuple]] = socket.getaddrinfo,
    ) -> None:
        self.allow_loopback = allow_loopback
        self.bluesky_only = bluesky_only
        if p0_test_pds_origin is not None and (
            not bluesky_only
            or not allow_loopback
            or p0_test_pds_origin != "https://juche.social"
        ):
            raise ValueError("P0 test PDS requires exact isolated Juche configuration")
        if p0_hosted_pds_origin is not None and (
            p0_hosted_pds_origin != "https://phlogiston.social"
            or p0_test_pds_origin is not None
        ):
            raise ValueError("controlled hosted P0 requires exact Phlogiston origin")
        if not isinstance(p0_allow_bluesky, bool) or (
            p0_allow_bluesky and p0_hosted_pds_origin != "https://phlogiston.social"
        ):
            raise ValueError("p0_allow_bluesky requires exact hosted P0 origin")
        self.p0_allow_bluesky = p0_allow_bluesky
        self.p0_hosted_pds_origin = p0_hosted_pds_origin
        self.p0_test_pds_origin = p0_test_pds_origin
        self.plc_directory_url = validate_public_origin(
            plc_directory_url, allow_loopback=allow_loopback
        )
        if not 1 <= cache_size <= 4096:
            raise ValueError("DID cache size must be between 1 and 4096")
        self.timeout_seconds = timeout_seconds
        self.cache_size = cache_size
        self.address_resolver = address_resolver
        self._cache: OrderedDict[str, str] = OrderedDict()

    def pds_origin(self, did: str) -> str:
        validate_did(did)
        if self.bluesky_only and not (
            did.startswith("did:plc:")
            or (self.p0_test_pds_origin is not None and did == "did:web:juche.social")
        ):
            raise ValidationError(
                "pds_unsupported", "P0 requires a Bluesky PLC identity"
            )
        cached = self._cache.get(did)
        if cached is not None:
            self._cache.move_to_end(did)
            return cached
        if did.startswith("did:plc:"):
            url = f"{self.plc_directory_url}/{urllib.parse.quote(did, safe=':')}"
        elif did.startswith("did:web:"):
            url = did_web_document_url(did)
        else:
            raise ValidationError("did_invalid", "unsupported DID method")
        document = self._get_document(url)
        if document.get("id") != did:
            raise PortUnavailableError("DID document id mismatch")
        origin = extract_pds_origin(document, allow_loopback=self.allow_loopback)
        if self.p0_hosted_pds_origin is not None:
            if origin != self.p0_hosted_pds_origin and self.p0_allow_bluesky:
                validate_bluesky_pds_origin(origin)
            elif origin != self.p0_hosted_pds_origin:
                raise ValidationError(
                    "pds_unsupported",
                    "controlled hosted P0 requires configured Phlogiston PDS",
                )
        elif self.bluesky_only and origin != self.p0_test_pds_origin:
            validate_bluesky_pds_origin(origin)
        validate_public_url(
            origin + "/",
            allow_loopback=self.allow_loopback,
            address_resolver=self.address_resolver,
        )
        self._cache[did] = origin
        self._cache.move_to_end(did)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        return origin

    def _get_document(self, url: str) -> Mapping[str, object]:
        validated = validate_public_url(
            url,
            allow_loopback=self.allow_loopback,
            address_resolver=self.address_resolver,
        )
        request = urllib.request.Request(
            validated,
            headers={"Accept": "application/did+json, application/json"},
        )
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect()
        )
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                body = response.read(MAX_DID_DOCUMENT_BYTES + 1)
                status = response.status
        except urllib.error.HTTPError as exc:
            raise PortUnavailableError(
                f"DID resolution returned HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            raise PortUnavailableError("DID resolution failed") from exc
        if status != 200 or len(body) > MAX_DID_DOCUMENT_BYTES:
            raise PortUnavailableError("DID document response is invalid")
        try:
            document = json.loads(body)
        except (UnicodeDecodeError, ValueError) as exc:
            raise PortUnavailableError("DID document is not valid JSON") from exc
        if not isinstance(document, Mapping):
            raise PortUnavailableError("DID document is not an object")
        return document


def did_web_document_url(did: str) -> str:
    body = did.removeprefix("did:web:")
    encoded = body.split(":")
    segments = [urllib.parse.unquote(item) for item in encoded]
    if (
        not segments
        or not segments[0]
        or any(not item or item in {".", ".."} or "/" in item for item in segments)
    ):
        raise ValidationError("did_invalid", "did:web contains an unsafe segment")
    authority = segments[0]
    path = (
        "/.well-known/did.json"
        if len(segments) == 1
        else "/"
        + "/".join(urllib.parse.quote(item, safe="") for item in segments[1:])
        + "/did.json"
    )
    return f"https://{authority}{path}"


def extract_pds_origin(document: Mapping[str, object], *, allow_loopback: bool) -> str:
    services = document.get("service")
    if not isinstance(services, list):
        raise PortUnavailableError("DID document has no service list")
    for service in services:
        if not isinstance(service, Mapping):
            continue
        if service.get("type") != "AtprotoPersonalDataServer" and not str(
            service.get("id", "")
        ).endswith("#atproto_pds"):
            continue
        endpoint = service.get("serviceEndpoint")
        if isinstance(endpoint, str):
            return validate_public_origin(endpoint, allow_loopback=allow_loopback)
    raise PortUnavailableError("DID document has no ATProto PDS endpoint")


def validate_public_origin(value: str, *, allow_loopback: bool) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValidationError("endpoint_invalid", "endpoint must be a bare origin")
    if parsed.path not in {"", "/"} or not parsed.hostname:
        raise ValidationError("endpoint_invalid", "endpoint must be a bare origin")
    if parsed.scheme != "https":
        if not (
            allow_loopback
            and parsed.scheme == "http"
            and _is_loopback_literal(parsed.hostname)
        ):
            raise ValidationError("endpoint_invalid", "endpoint must use HTTPS")
    return value.rstrip("/")


def validate_bluesky_pds_origin(value: str) -> str:
    """P0 source-host boundary, before any repository/proof transport is made."""
    parsed = urllib.parse.urlsplit(value)
    host = parsed.hostname
    suffix = ".host.bsky.network"
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or host is None
        or not host.endswith(suffix)
    ):
        raise ValidationError("pds_unsupported", "P0 requires a Bluesky-hosted PDS")
    prefix = host[: -len(suffix)]
    if not prefix or any(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None
        for label in prefix.split(".")
    ):
        raise ValidationError("pds_unsupported", "P0 requires a Bluesky-hosted PDS")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValidationError(
            "pds_unsupported", "P0 requires the default HTTPS port"
        ) from exc
    if port not in {None, 443}:
        raise ValidationError("pds_unsupported", "P0 requires the default HTTPS port")
    return value.rstrip("/")


def validate_public_url(
    value: str,
    *,
    allow_loopback: bool,
    address_resolver: Callable[..., list[tuple]],
) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        if not (
            allow_loopback
            and parsed.scheme == "http"
            and parsed.hostname is not None
            and _is_loopback_literal(parsed.hostname)
        ):
            raise ValidationError("endpoint_invalid", "public fetch URL is unsafe")
    assert parsed.hostname is not None
    try:
        addresses = address_resolver(
            parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
        )
    except OSError as exc:
        raise PortUnavailableError("endpoint DNS resolution failed") from exc
    if not addresses:
        raise PortUnavailableError("endpoint DNS resolution returned no addresses")
    for result in addresses:
        address = ipaddress.ip_address(result[4][0])
        if not address.is_global and not (allow_loopback and address.is_loopback):
            raise ValidationError(
                "endpoint_invalid", "endpoint resolves to a private address"
            )
    return value


def _is_loopback_literal(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


__all__ = [
    "AuthorityDidResolver",
    "did_web_document_url",
    "extract_pds_origin",
    "validate_public_origin",
    "validate_public_url",
]
