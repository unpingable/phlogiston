"""Read-only ATProto sync fetchers: DID resolution and proof CAR downloads.

Every fetch is an unauthenticated public GET.  Nothing here trusts the
returned bytes; ``repoproof`` verifies them cryptographically before any
receipt may carry ``verification_outcome=verified``.  The observer holds no
credentials, so this module has no concept of one.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from community_model import PortUnavailableError, ValidationError
from community_model.identifiers import validate_did

DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_DOCUMENT_BYTES = 1 << 20
MAX_CAR_BYTES = 16 << 20


class FetchError(PortUnavailableError):
    """A public read endpoint could not be reached or answered badly."""


class RecordNotFoundError(PortUnavailableError):
    """The hosting PDS reports the exact record key as absent."""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes


@runtime_checkable
class HttpGetter(Protocol):
    """One bounded HTTP GET; the only network shape this package needs."""

    def get(self, url: str) -> HttpResponse: ...


@dataclass(slots=True)
class UrllibHttpGetter:
    """Stdlib HTTP GET with a hard timeout and response-size bound."""

    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    p0_bluesky_only: bool = False
    p0_test_pds_origin: str | None = None
    p0_hosted_pds_origin: str | None = None
    p0_allow_bluesky: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.p0_allow_bluesky, bool) or (
            self.p0_allow_bluesky
            and (
                self.p0_hosted_pds_origin != "https://phlogiston.social"
                or self.p0_test_pds_origin is not None
                or self.p0_bluesky_only
            )
        ):
            raise ValueError(
                "p0_allow_bluesky requires separate exact hosted P0 profile"
            )

    def get(self, url: str) -> HttpResponse:
        if self.p0_bluesky_only or self.p0_hosted_pds_origin is not None:
            from .verifying import supported_bluesky_pds

            parts = urllib.parse.urlsplit(url)
            origin = urllib.parse.urlunsplit((parts.scheme, parts.netloc, "", "", ""))
            if self.p0_hosted_pds_origin is not None:
                supported = origin in {
                    "https://plc.directory",
                    self.p0_hosted_pds_origin,
                } or (self.p0_allow_bluesky and supported_bluesky_pds(origin))
            else:
                supported = origin in {
                    "https://plc.directory",
                    self.p0_test_pds_origin,
                } or supported_bluesky_pds(origin)
            if not supported:
                raise FetchError("unsupported P0 public read origin")
        request = urllib.request.Request(url, headers={"Accept": "*/*"})
        try:
            if self.p0_bluesky_only or self.p0_hosted_pds_origin is not None:

                class NoRedirect(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self, req, fp, code, msg, headers, newurl):
                        raise FetchError("P0 public read redirect refused")

                opener = urllib.request.build_opener(NoRedirect())
                reply_context = opener.open(request, timeout=self.timeout_seconds)
            else:
                reply_context = urllib.request.urlopen(
                    request, timeout=self.timeout_seconds
                )
            with reply_context as reply:
                body = reply.read(MAX_CAR_BYTES + 1)
                if len(body) > MAX_CAR_BYTES:
                    raise FetchError("response exceeds the observer size bound")
                return HttpResponse(status=reply.status, body=body)
        except urllib.error.HTTPError as exc:
            body = exc.read(MAX_DOCUMENT_BYTES + 1) if exc.fp is not None else b""
            return HttpResponse(status=exc.code, body=body)
        except (urllib.error.URLError, OSError) as exc:
            raise FetchError(f"public fetch failed: {type(exc).__name__}") from exc


@dataclass(slots=True)
class DidResolver:
    """Resolve did:plc and did:web documents through one HTTP getter."""

    http: HttpGetter
    plc_url: str
    _cache: dict[str, Mapping[str, object]] | None = None

    def __post_init__(self) -> None:
        if self._cache is None:
            self._cache = {}

    def resolve(self, did: str) -> Mapping[str, object]:
        validate_did(did)
        assert self._cache is not None
        cached = self._cache.get(did)
        if cached is not None:
            return cached
        if did.startswith("did:plc:"):
            url = f"{self.plc_url.rstrip('/')}/{did}"
        elif did.startswith("did:web:"):
            url = _did_web_url(did)
        else:
            raise ValidationError("did_invalid", "unsupported DID method")
        response = self.http.get(url)
        if response.status != 200:
            raise FetchError(f"DID resolution returned HTTP {response.status}")
        if len(response.body) > MAX_DOCUMENT_BYTES:
            raise FetchError("DID document exceeds the observer size bound")
        try:
            document = json.loads(response.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise FetchError("DID document is not valid JSON") from exc
        if not isinstance(document, dict):
            raise FetchError("DID document is not an object")
        if document.get("id") != did:
            raise FetchError("DID document id does not match the requested DID")
        self._cache[did] = document
        return document


def _did_web_url(did: str) -> str:
    """Map a did:web identifier to its well-known document URL."""

    body = did.removeprefix("did:web:")
    segments = [urllib.parse.unquote(segment) for segment in body.split(":")]
    host = segments[0]
    if not host:
        raise ValidationError("did_invalid", "did:web host is empty")
    if len(segments) == 1:
        return f"https://{host}/.well-known/did.json"
    path = "/".join(segments[1:])
    return f"https://{host}/{path}/did.json"


@dataclass(slots=True)
class PdsClient:
    """Unauthenticated com.atproto.sync reads against one PDS endpoint."""

    http: HttpGetter

    def get_record_car(
        self, pds_url: str, *, repo: str, collection: str, rkey: str
    ) -> bytes:
        # The sync namespace names the repo parameter "did" on the wire.
        query = urllib.parse.urlencode(
            {"did": repo, "collection": collection, "rkey": rkey}
        )
        url = f"{pds_url}/xrpc/com.atproto.sync.getRecord?{query}"
        response = self.http.get(url)
        if response.status in {400, 404}:
            raise RecordNotFoundError("the PDS reports this record as absent")
        if response.status != 200:
            raise FetchError(f"getRecord returned HTTP {response.status}")
        return response.body

    def get_repo_car(self, pds_url: str, *, repo: str) -> bytes:
        query = urllib.parse.urlencode({"did": repo})
        url = f"{pds_url}/xrpc/com.atproto.sync.getRepo?{query}"
        response = self.http.get(url)
        if response.status != 200:
            raise FetchError(f"getRepo returned HTTP {response.status}")
        return response.body


__all__ = [
    "DidResolver",
    "FetchError",
    "HttpGetter",
    "HttpResponse",
    "PdsClient",
    "RecordNotFoundError",
    "UrllibHttpGetter",
]
