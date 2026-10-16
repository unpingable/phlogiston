"""SA9a bounded, unauthenticated HTTP acquisition into the SA7 seam.

Transport success is acquisition evidence, not source authority.  This module
issues only explicit GET requests, performs no retries, carries no credentials,
and makes no artifact, identity, currentness, or governance claim.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType

from community_model import PortUnavailableError, ValidationError

from .artifact_source import (
    FullRepoArtifactRequest,
    ObservedCarArtifact,
    ObservedRepoOpsArtifact,
    RepoOpsArtifactRequest,
    TransportSourceContext,
)
from .compat import (
    SA9A_HTTP_DOCTRINE,
    SA9A_HTTP_METHOD,
    SA9A_HTTP_VERSION,
    XRPC_PATH_PREFIX,
)
from .operations import parse_list_repo_ops_page

DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_CAR_BYTES = 16 << 20
DEFAULT_MAX_JSON_BYTES = 1 << 20
DEFAULT_MAX_REDIRECTS = 3
DEFAULT_MAX_OPERATION_PAGES = 100

_REQUEST_HEADERS = MappingProxyType(
    {
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "User-Agent": f"communitywatch-spaces-alpha/{SA9A_HTTP_VERSION}",
    }
)
_RESPONSE_HEADER_ALLOWLIST = frozenset(
    {
        "content-encoding",
        "content-length",
        "content-type",
        "etag",
        "last-modified",
    }
)
_SECRET_HEADER_NAMES = frozenset(
    {"authorization", "cookie", "dpop", "proxy-authorization", "set-cookie"}
)


def _fail(reason: str, message: str) -> None:
    raise ValidationError(reason, message)


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        _fail("spaces_http_policy_invalid", "HTTP acquisition time must be aware")
    return value.astimezone(UTC)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _check_digest(value: str, *, field_name: str) -> None:
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        _fail("spaces_http_receipt_invalid", f"{field_name} is not SHA-256")


def _origin(url: str) -> tuple[str, str, int]:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        _fail("spaces_http_policy_invalid", "URL must be absolute HTTP(S)")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValidationError(
            "spaces_http_policy_invalid", "URL port is invalid"
        ) from exc
    return (
        parts.scheme,
        parts.hostname.lower(),
        port or (443 if parts.scheme == "https" else 80),
    )


def _is_loopback(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _validate_base_url(url: str) -> str:
    origin = _origin(url)
    parts = urllib.parse.urlsplit(url)
    if parts.username is not None or parts.password is not None:
        _fail("spaces_http_policy_invalid", "URL credentials are prohibited")
    if parts.query or parts.fragment or parts.path not in {"", "/"}:
        _fail("spaces_http_policy_invalid", "base URL must contain only an origin")
    if origin[0] == "http" and not _is_loopback(origin[1]):
        _fail(
            "spaces_http_policy_invalid",
            "plaintext HTTP is permitted only for loopback fixtures",
        )
    return url.rstrip("/")


def _without_url_credentials(url: str) -> str:
    """Remove userinfo before a refused redirect can enter provenance."""

    parts = urllib.parse.urlsplit(url)
    hostname = parts.hostname or "invalid"
    if ":" in hostname:
        hostname = f"[{hostname}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    netloc = f"{hostname}:{port}" if port is not None else hostname
    return urllib.parse.urlunsplit(
        (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
    )


def _selected_headers(headers: Mapping[str, str]) -> MappingProxyType[str, str]:
    selected = {
        name.lower(): value
        for name, value in headers.items()
        if name.lower() in _RESPONSE_HEADER_ALLOWLIST
    }
    if set(selected) & _SECRET_HEADER_NAMES:
        _fail("spaces_http_receipt_invalid", "secret response header was retained")
    return MappingProxyType(dict(sorted(selected.items())))


class HttpArtifactKind(StrEnum):
    FULL_REPO_CAR = "full_repo_car"
    REPO_OPS_PAGE = "repo_ops_page"


class HttpAcquisitionDisposition(StrEnum):
    ACQUIRED = "acquired"
    REFUSED = "refused"


@dataclass(frozen=True, slots=True)
class HttpRedirectHop:
    status: int
    source_url: str
    target_url: str

    def __post_init__(self) -> None:
        if self.status not in {301, 302, 303, 307, 308}:
            _fail("spaces_http_receipt_invalid", "redirect status is invalid")
        _origin(self.source_url)
        _origin(self.target_url)

    def to_provenance(self) -> MappingProxyType[str, object]:
        return MappingProxyType(
            {
                "status": self.status,
                "sourceUrl": self.source_url,
                "targetUrl": self.target_url,
            }
        )


def _receipt_identifier(
    *,
    request_id: str,
    artifact_kind: HttpArtifactKind,
    requested_url: str,
    final_url: str,
    status: int | None,
    response_headers: Mapping[str, str],
    body_sha256: str | None,
    body_length: int,
    body_complete: bool,
    redirects: tuple[HttpRedirectHop, ...],
    disposition: HttpAcquisitionDisposition,
    failure_reason_code: str | None,
    observed_at: datetime,
    timeout_seconds: float,
    maximum_body_bytes: int,
) -> str:
    fields = [
        "spaces-http-acquisition-receipt-v1",
        SA9A_HTTP_METHOD,
        SA9A_HTTP_VERSION,
        SA9A_HTTP_DOCTRINE,
        request_id,
        artifact_kind.value,
        "GET",
        requested_url,
        final_url,
        str(status) if status is not None else "-",
        body_sha256 or "-",
        str(body_length),
        "complete" if body_complete else "incomplete",
        disposition.value,
        failure_reason_code or "-",
        observed_at.astimezone(UTC).isoformat(),
        repr(timeout_seconds),
        str(maximum_body_bytes),
        *(
            f"request:{name.lower()}={value}"
            for name, value in _REQUEST_HEADERS.items()
        ),
        *(f"response:{name}={value}" for name, value in response_headers.items()),
        *(
            f"redirect:{hop.status}:{hop.source_url}:{hop.target_url}"
            for hop in redirects
        ),
    ]
    return "sha256:" + hashlib.sha256("\x00".join(fields).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class HttpAcquisitionReceipt:
    receipt_id: str
    request_id: str
    artifact_kind: HttpArtifactKind
    requested_url: str
    final_url: str
    status: int | None
    response_headers: Mapping[str, str]
    body_sha256: str | None
    body_length: int
    body_complete: bool
    redirects: tuple[HttpRedirectHop, ...]
    disposition: HttpAcquisitionDisposition
    failure_reason_code: str | None
    observed_at: datetime
    timeout_seconds: float
    maximum_body_bytes: int
    method: str = field(default="GET", init=False)
    request_headers: Mapping[str, str] = field(default=_REQUEST_HEADERS, init=False)
    redirect_policy: str = field(default="same-origin-only", init=False)
    automatic_retries: int = field(default=0, init=False)
    content_transformation: str = field(default="identity-only", init=False)
    implementation: str = field(default=SA9A_HTTP_METHOD, init=False)
    implementation_version: str = field(default=SA9A_HTTP_VERSION, init=False)
    doctrine: str = field(default=SA9A_HTTP_DOCTRINE, init=False)
    did_service_binding_verified: bool = False
    source_authority: bool = False
    artifact_validity: bool = False
    currentness: bool = False
    authorization: bool = False
    governance_authority: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_kind, HttpArtifactKind) or not isinstance(
            self.disposition, HttpAcquisitionDisposition
        ):
            _fail("spaces_http_receipt_invalid", "receipt enums are invalid")
        if not self.request_id or any(ch.isspace() for ch in self.request_id):
            _fail("spaces_http_receipt_invalid", "request ID is invalid")
        _origin(self.requested_url)
        _origin(self.final_url)
        object.__setattr__(self, "observed_at", _utc(self.observed_at))
        if self.status is not None and (
            isinstance(self.status, bool)
            or not isinstance(self.status, int)
            or not 100 <= self.status <= 599
        ):
            _fail("spaces_http_receipt_invalid", "HTTP status is invalid")
        if not isinstance(self.response_headers, Mapping):
            _fail("spaces_http_receipt_invalid", "response headers are invalid")
        normalized_headers = _selected_headers(self.response_headers)
        object.__setattr__(self, "response_headers", normalized_headers)
        if self.body_sha256 is not None:
            _check_digest(self.body_sha256, field_name="body digest")
        if (
            isinstance(self.body_length, bool)
            or not isinstance(self.body_length, int)
            or self.body_length < 0
        ):
            _fail("spaces_http_receipt_invalid", "body length is invalid")
        if not isinstance(self.redirects, tuple) or any(
            not isinstance(hop, HttpRedirectHop) for hop in self.redirects
        ):
            _fail("spaces_http_receipt_invalid", "redirect chain is invalid")
        if self.disposition is HttpAcquisitionDisposition.ACQUIRED:
            if (
                self.status != 200
                or self.failure_reason_code is not None
                or not self.body_complete
                or self.body_sha256 is None
                or self.body_length == 0
            ):
                _fail("spaces_http_receipt_invalid", "successful receipt is incomplete")
        elif self.failure_reason_code is None:
            _fail("spaces_http_receipt_invalid", "refusal reason is required")
        if (
            not isinstance(self.timeout_seconds, int | float)
            or isinstance(self.timeout_seconds, bool)
            or not 0 < self.timeout_seconds <= 60
            or isinstance(self.maximum_body_bytes, bool)
            or not 1 <= self.maximum_body_bytes <= (64 << 20)
        ):
            _fail("spaces_http_receipt_invalid", "receipt bounds are invalid")
        if set(name.lower() for name in self.request_headers) & _SECRET_HEADER_NAMES:
            _fail("spaces_http_receipt_invalid", "secret request header was retained")
        if any(
            (
                self.did_service_binding_verified,
                self.source_authority,
                self.artifact_validity,
                self.currentness,
                self.authorization,
                self.governance_authority,
            )
        ):
            _fail(
                "spaces_http_receipt_invalid", "HTTP cannot confer trust or authority"
            )
        expected = _receipt_identifier(
            request_id=self.request_id,
            artifact_kind=self.artifact_kind,
            requested_url=self.requested_url,
            final_url=self.final_url,
            status=self.status,
            response_headers=self.response_headers,
            body_sha256=self.body_sha256,
            body_length=self.body_length,
            body_complete=self.body_complete,
            redirects=self.redirects,
            disposition=self.disposition,
            failure_reason_code=self.failure_reason_code,
            observed_at=self.observed_at,
            timeout_seconds=float(self.timeout_seconds),
            maximum_body_bytes=self.maximum_body_bytes,
        )
        if self.receipt_id != expected:
            _fail("spaces_http_receipt_invalid", "HTTP receipt is not bound")

    def to_provenance(self) -> MappingProxyType[str, object]:
        return MappingProxyType(
            {
                "receiptId": self.receipt_id,
                "requestId": self.request_id,
                "artifactKind": self.artifact_kind.value,
                "requestedUrl": self.requested_url,
                "finalUrl": self.final_url,
                "method": self.method,
                "requestHeaders": MappingProxyType(dict(self.request_headers)),
                "status": self.status,
                "responseHeaders": self.response_headers,
                "bodySha256": self.body_sha256,
                "bodyLength": self.body_length,
                "bodyComplete": self.body_complete,
                "redirectChain": tuple(hop.to_provenance() for hop in self.redirects),
                "redirectPolicy": self.redirect_policy,
                "timeoutSeconds": self.timeout_seconds,
                "maximumBodyBytes": self.maximum_body_bytes,
                "automaticRetries": 0,
                "contentTransformation": self.content_transformation,
                "disposition": self.disposition.value,
                "failureReasonCode": self.failure_reason_code,
                "observedAt": self.observed_at.isoformat(),
                "implementation": self.implementation,
                "implementationVersion": self.implementation_version,
                "doctrine": self.doctrine,
                "trustClassification": "unverified_http_acquisition_context",
                "didServiceBindingVerified": False,
                "sourceAuthority": False,
                "artifactValidity": False,
                "currentness": False,
                "authorization": False,
                "governanceAuthority": False,
            }
        )


class HttpAcquisitionError(PortUnavailableError):
    """One visible HTTP acquisition attempt was refused or failed."""

    def __init__(self, receipt: HttpAcquisitionReceipt) -> None:
        self.receipt = receipt
        self.reason_code = receipt.failure_reason_code
        super().__init__(f"{self.reason_code}: HTTP artifact acquisition failed")


class _RedirectRefusal(Exception):
    def __init__(
        self,
        reason_code: str,
        *,
        status: int,
        current_url: str,
        target_url: str,
        headers: Mapping[str, str],
    ) -> None:
        self.reason_code = reason_code
        self.status = status
        self.current_url = current_url
        self.target_url = target_url
        self.headers = headers
        super().__init__(reason_code)


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, *, requested_url: str, maximum_redirects: int) -> None:
        super().__init__()
        self.request_origin = _origin(requested_url)
        self.maximum_redirects = maximum_redirects
        self.visited = {requested_url}
        self.chain: list[HttpRedirectHop] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        target_parts = urllib.parse.urlsplit(target)
        if target_parts.username is not None or target_parts.password is not None:
            raise _RedirectRefusal(
                "spaces_http_redirect_credentials",
                status=code,
                current_url=req.full_url,
                target_url=_without_url_credentials(target),
                headers=headers,
            )
        if _origin(target) != self.request_origin:
            raise _RedirectRefusal(
                "spaces_http_cross_origin_redirect",
                status=code,
                current_url=req.full_url,
                target_url=target,
                headers=headers,
            )
        if target in self.visited:
            raise _RedirectRefusal(
                "spaces_http_redirect_loop",
                status=code,
                current_url=req.full_url,
                target_url=target,
                headers=headers,
            )
        if len(self.chain) >= self.maximum_redirects:
            raise _RedirectRefusal(
                "spaces_http_redirect_limit",
                status=code,
                current_url=req.full_url,
                target_url=target,
                headers=headers,
            )
        redirected = super().redirect_request(req, fp, code, msg, headers, target)
        if redirected is None:
            return None
        self.visited.add(target)
        self.chain.append(HttpRedirectHop(code, req.full_url, target))
        return redirected


@dataclass(slots=True)
class HttpSpaceArtifactProvider:
    """Replaceable SA7 provider for explicit unauthenticated GET acquisitions."""

    base_url: str
    source_endpoint: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    maximum_car_bytes: int = DEFAULT_MAX_CAR_BYTES
    maximum_json_bytes: int = DEFAULT_MAX_JSON_BYTES
    maximum_redirects: int = DEFAULT_MAX_REDIRECTS
    maximum_operation_pages: int = DEFAULT_MAX_OPERATION_PAGES
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    _receipts: dict[str, HttpAcquisitionReceipt] = field(
        default_factory=dict, init=False
    )
    _artifact_receipts: dict[str, tuple[str, ...]] = field(
        default_factory=dict, init=False
    )

    def __post_init__(self) -> None:
        self.base_url = _validate_base_url(self.base_url)
        if self.source_endpoint is None:
            if _origin(self.base_url)[0] != "https":
                _fail(
                    "spaces_http_policy_invalid",
                    "loopback HTTP needs an explicit unverified HTTPS source context",
                )
            self.source_endpoint = self.base_url
        if not isinstance(self.source_endpoint, str):
            _fail("spaces_http_policy_invalid", "source endpoint is invalid")
        # Reuse SA7's source-context validation without retaining a dummy value.
        TransportSourceContext(
            transport_name=SA9A_HTTP_METHOD,
            source_endpoint=self.source_endpoint,
            artifact_ref="sa9a-policy-validation",
            observed_at=datetime(2000, 1, 1, tzinfo=UTC),
        )
        if (
            not isinstance(self.timeout_seconds, int | float)
            or isinstance(self.timeout_seconds, bool)
            or not 0 < self.timeout_seconds <= 60
        ):
            _fail("spaces_http_policy_invalid", "timeout is outside bounds")
        for value, name, ceiling in (
            (self.maximum_car_bytes, "CAR body", 64 << 20),
            (self.maximum_json_bytes, "JSON body", 16 << 20),
            (self.maximum_redirects, "redirect", 20),
            (self.maximum_operation_pages, "operation page", 1000),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= ceiling
            ):
                _fail("spaces_http_policy_invalid", f"{name} bound is invalid")

    @property
    def automatic_retries(self) -> int:
        return 0

    def receipt(self, receipt_id: str) -> HttpAcquisitionReceipt:
        try:
            return self._receipts[receipt_id]
        except KeyError as exc:
            raise KeyError("unknown HTTP acquisition receipt") from exc

    def receipts_for(self, artifact_ref: str) -> tuple[HttpAcquisitionReceipt, ...]:
        try:
            receipt_ids = self._artifact_receipts[artifact_ref]
        except KeyError as exc:
            raise KeyError("unknown SA7 artifact reference") from exc
        return tuple(self._receipts[item] for item in receipt_ids)

    def get_repo(self, request: FullRepoArtifactRequest) -> ObservedCarArtifact:
        if not isinstance(request, FullRepoArtifactRequest):
            _fail("spaces_http_request_invalid", "full-repo request is required")
        url = self._xrpc_url(
            request.endpoint,
            {
                "space": request.identity.space.uri,
                "repo": request.identity.repo_did,
            },
        )
        body, receipt = self._perform(
            request_id=request.identity.request_id,
            artifact_kind=HttpArtifactKind.FULL_REPO_CAR,
            url=url,
            maximum_body_bytes=self.maximum_car_bytes,
        )
        source = self._source(receipt, (receipt.receipt_id,))
        return ObservedCarArtifact(request=request, source=source, car_bytes=body)

    def list_repo_ops(self, request: RepoOpsArtifactRequest) -> ObservedRepoOpsArtifact:
        if not isinstance(request, RepoOpsArtifactRequest):
            _fail("spaces_http_request_invalid", "operation request is required")
        pages = []
        receipt_ids: list[str] = []
        cursor = request.cursor
        for ordinal in range(self.maximum_operation_pages):
            parameters: dict[str, object] = {
                "space": request.identity.space.uri,
                "repo": request.identity.repo_did,
                "since": request.since,
                "limit": request.limit,
                "excludeValues": str(request.exclude_values).lower(),
            }
            if cursor is not None:
                parameters["cursor"] = cursor
            url = self._xrpc_url(request.endpoint, parameters)
            body, receipt = self._perform(
                request_id=f"{request.identity.request_id}:page:{ordinal}",
                artifact_kind=HttpArtifactKind.REPO_OPS_PAGE,
                url=url,
                maximum_body_bytes=self.maximum_json_bytes,
            )
            receipt_ids.append(receipt.receipt_id)
            try:
                response = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise ValidationError(
                    "spaces_http_json_invalid",
                    "acquired operation page is not JSON",
                ) from exc
            if not isinstance(response, Mapping):
                _fail("spaces_http_json_invalid", "operation response is not an object")
            page = parse_list_repo_ops_page(
                response,
                ordinal=ordinal,
                request_since=request.since,
                request_cursor=cursor,
                received_at=receipt.observed_at,
            )
            pages.append(page)
            cursor = page.response_cursor
            if cursor is None:
                break
        artifact_ref = self._artifact_reference(tuple(receipt_ids))
        source = self._source(
            self._receipts[receipt_ids[-1]], tuple(receipt_ids), artifact_ref
        )
        return ObservedRepoOpsArtifact(
            request=request,
            source=source,
            pages=tuple(pages),
        )

    def _xrpc_url(self, endpoint: str, parameters: Mapping[str, object]) -> str:
        query = urllib.parse.urlencode(parameters)
        return f"{self.base_url}{XRPC_PATH_PREFIX}{endpoint}?{query}"

    def _artifact_reference(self, receipt_ids: tuple[str, ...]) -> str:
        return (
            "sha256:"
            + hashlib.sha256(
                "\x00".join(("spaces-http-artifact-v1", *receipt_ids)).encode()
            ).hexdigest()
        )

    def _source(
        self,
        receipt: HttpAcquisitionReceipt,
        receipt_ids: tuple[str, ...],
        artifact_ref: str | None = None,
    ) -> TransportSourceContext:
        reference = artifact_ref or receipt.receipt_id
        self._artifact_receipts[reference] = receipt_ids
        assert self.source_endpoint is not None
        return TransportSourceContext(
            transport_name=SA9A_HTTP_METHOD,
            source_endpoint=self.source_endpoint,
            artifact_ref=reference,
            observed_at=receipt.observed_at,
        )

    def _perform(
        self,
        *,
        request_id: str,
        artifact_kind: HttpArtifactKind,
        url: str,
        maximum_body_bytes: int,
    ) -> tuple[bytes, HttpAcquisitionReceipt]:
        redirects = _SameOriginRedirectHandler(
            requested_url=url,
            maximum_redirects=self.maximum_redirects,
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), redirects)
        request = urllib.request.Request(
            url, headers=dict(_REQUEST_HEADERS), method="GET"
        )
        status: int | None = None
        final_url = url
        response_headers: Mapping[str, str] = {}
        body = b""
        body_complete = False
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                status = response.status
                final_url = response.geturl()
                response_headers = _selected_headers(dict(response.headers.items()))
                body = response.read(maximum_body_bytes + 1)
                if len(body) > maximum_body_bytes:
                    self._refuse(
                        request_id=request_id,
                        artifact_kind=artifact_kind,
                        requested_url=url,
                        final_url=final_url,
                        status=status,
                        response_headers=response_headers,
                        body=body,
                        body_complete=False,
                        redirects=tuple(redirects.chain),
                        reason="spaces_http_body_too_large",
                        maximum_body_bytes=maximum_body_bytes,
                    )
                body_complete = True
        except _RedirectRefusal as exc:
            refused_chain = (
                *redirects.chain,
                HttpRedirectHop(exc.status, exc.current_url, exc.target_url),
            )
            self._refuse(
                request_id=request_id,
                artifact_kind=artifact_kind,
                requested_url=url,
                final_url=exc.current_url,
                status=exc.status,
                response_headers=_selected_headers(exc.headers),
                body=b"",
                body_complete=False,
                redirects=refused_chain,
                reason=exc.reason_code,
                maximum_body_bytes=maximum_body_bytes,
            )
        except urllib.error.HTTPError as exc:
            error_body = exc.read(maximum_body_bytes + 1) if exc.fp is not None else b""
            self._refuse(
                request_id=request_id,
                artifact_kind=artifact_kind,
                requested_url=url,
                final_url=exc.geturl(),
                status=exc.code,
                response_headers=_selected_headers(dict(exc.headers.items())),
                body=error_body,
                body_complete=len(error_body) <= maximum_body_bytes,
                redirects=tuple(redirects.chain),
                reason="spaces_http_status_refused",
                maximum_body_bytes=maximum_body_bytes,
            )
        except http.client.IncompleteRead as exc:
            self._refuse(
                request_id=request_id,
                artifact_kind=artifact_kind,
                requested_url=url,
                final_url=final_url,
                status=status,
                response_headers=response_headers,
                body=exc.partial,
                body_complete=False,
                redirects=tuple(redirects.chain),
                reason="spaces_http_truncated_body",
                maximum_body_bytes=maximum_body_bytes,
            )
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            reason = (
                "spaces_http_timeout"
                if self._is_timeout(exc)
                else "spaces_http_unavailable"
            )
            self._refuse(
                request_id=request_id,
                artifact_kind=artifact_kind,
                requested_url=url,
                final_url=final_url,
                status=status,
                response_headers=response_headers,
                body=body,
                body_complete=False,
                redirects=tuple(redirects.chain),
                reason=reason,
                maximum_body_bytes=maximum_body_bytes,
            )

        content_encoding = response_headers.get("content-encoding", "identity").lower()
        if content_encoding != "identity":
            self._refuse(
                request_id=request_id,
                artifact_kind=artifact_kind,
                requested_url=url,
                final_url=final_url,
                status=status,
                response_headers=response_headers,
                body=body,
                body_complete=body_complete,
                redirects=tuple(redirects.chain),
                reason="spaces_http_content_encoding_unsupported",
                maximum_body_bytes=maximum_body_bytes,
            )
        declared_length = response_headers.get("content-length")
        if declared_length is not None:
            try:
                expected_length = int(declared_length)
            except ValueError:
                expected_length = -1
            if expected_length < 0 or expected_length != len(body):
                self._refuse(
                    request_id=request_id,
                    artifact_kind=artifact_kind,
                    requested_url=url,
                    final_url=final_url,
                    status=status,
                    response_headers=response_headers,
                    body=body,
                    body_complete=False,
                    redirects=tuple(redirects.chain),
                    reason="spaces_http_content_length_mismatch",
                    maximum_body_bytes=maximum_body_bytes,
                )
        if status != 200:
            self._refuse(
                request_id=request_id,
                artifact_kind=artifact_kind,
                requested_url=url,
                final_url=final_url,
                status=status,
                response_headers=response_headers,
                body=body,
                body_complete=body_complete,
                redirects=tuple(redirects.chain),
                reason="spaces_http_status_refused",
                maximum_body_bytes=maximum_body_bytes,
            )
        if not body:
            self._refuse(
                request_id=request_id,
                artifact_kind=artifact_kind,
                requested_url=url,
                final_url=final_url,
                status=status,
                response_headers=response_headers,
                body=body,
                body_complete=True,
                redirects=tuple(redirects.chain),
                reason="spaces_http_empty_body",
                maximum_body_bytes=maximum_body_bytes,
            )
        receipt = self._make_receipt(
            request_id=request_id,
            artifact_kind=artifact_kind,
            requested_url=url,
            final_url=final_url,
            status=status,
            response_headers=response_headers,
            body=body,
            body_complete=True,
            redirects=tuple(redirects.chain),
            disposition=HttpAcquisitionDisposition.ACQUIRED,
            failure_reason_code=None,
            maximum_body_bytes=maximum_body_bytes,
        )
        return body, receipt

    @staticmethod
    def _is_timeout(exc: BaseException) -> bool:
        if isinstance(exc, TimeoutError):
            return True
        return isinstance(getattr(exc, "reason", None), TimeoutError)

    def _refuse(
        self,
        *,
        request_id: str,
        artifact_kind: HttpArtifactKind,
        requested_url: str,
        final_url: str,
        status: int | None,
        response_headers: Mapping[str, str],
        body: bytes,
        body_complete: bool,
        redirects: tuple[HttpRedirectHop, ...],
        reason: str,
        maximum_body_bytes: int,
    ) -> None:
        receipt = self._make_receipt(
            request_id=request_id,
            artifact_kind=artifact_kind,
            requested_url=requested_url,
            final_url=final_url,
            status=status,
            response_headers=response_headers,
            body=body,
            body_complete=body_complete,
            redirects=redirects,
            disposition=HttpAcquisitionDisposition.REFUSED,
            failure_reason_code=reason,
            maximum_body_bytes=maximum_body_bytes,
        )
        raise HttpAcquisitionError(receipt)

    def _make_receipt(
        self,
        *,
        request_id: str,
        artifact_kind: HttpArtifactKind,
        requested_url: str,
        final_url: str,
        status: int | None,
        response_headers: Mapping[str, str],
        body: bytes,
        body_complete: bool,
        redirects: tuple[HttpRedirectHop, ...],
        disposition: HttpAcquisitionDisposition,
        failure_reason_code: str | None,
        maximum_body_bytes: int,
    ) -> HttpAcquisitionReceipt:
        observed_at = _utc(self.now())
        normalized_headers = _selected_headers(response_headers)
        fields = {
            "request_id": request_id,
            "artifact_kind": artifact_kind,
            "requested_url": requested_url,
            "final_url": final_url,
            "status": status,
            "response_headers": normalized_headers,
            "body_sha256": _sha256(body) if body else None,
            "body_length": len(body),
            "body_complete": body_complete,
            "redirects": redirects,
            "disposition": disposition,
            "failure_reason_code": failure_reason_code,
            "observed_at": observed_at,
            "timeout_seconds": float(self.timeout_seconds),
            "maximum_body_bytes": maximum_body_bytes,
        }
        receipt_id = _receipt_identifier(**fields)
        receipt = HttpAcquisitionReceipt(receipt_id=receipt_id, **fields)
        self._receipts[receipt.receipt_id] = receipt
        return receipt


__all__ = [
    "DEFAULT_MAX_CAR_BYTES",
    "DEFAULT_MAX_JSON_BYTES",
    "DEFAULT_MAX_OPERATION_PAGES",
    "DEFAULT_MAX_REDIRECTS",
    "DEFAULT_TIMEOUT_SECONDS",
    "HttpAcquisitionDisposition",
    "HttpAcquisitionError",
    "HttpAcquisitionReceipt",
    "HttpArtifactKind",
    "HttpRedirectHop",
    "HttpSpaceArtifactProvider",
]
