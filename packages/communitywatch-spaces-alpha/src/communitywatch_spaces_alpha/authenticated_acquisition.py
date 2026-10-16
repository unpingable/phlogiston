"""SA9d-d explicit-attempt authenticated HTTP adapter ending at SA7."""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from community_model import ValidationError

from .artifact_source import (
    FullRepoArtifactRequest,
    ObservedCarArtifact,
    ObservedRepoOpsArtifact,
    RepoOpsArtifactRequest,
    TransportSourceContext,
)
from .compat import (
    SA9DD_AUTHENTICATED_ACQUISITION_DOCTRINE,
    SA9DD_AUTHENTICATED_ACQUISITION_METHOD,
    SA9DD_AUTHENTICATED_ACQUISITION_VERSION,
)
from .credential_request import CredentialAuthenticatedRequest, CredentialNonce
from .operations import parse_list_repo_ops_page


def _fail(reason: str, message: str) -> None:
    raise ValidationError(reason, message)


def _sha(v: bytes) -> str:
    return hashlib.sha256(v).hexdigest()


class AuthenticatedAttemptDisposition(StrEnum):
    ACQUIRED = "acquired"
    NONCE_CHALLENGE = "nonce_challenge"
    REFUSED = "refused"


@dataclass(frozen=True, slots=True)
class AuthenticatedAttemptReceipt:
    receipt_id: str
    request_binding_receipt_id: str
    attempt_id: str
    artifact_request_id: str
    requested_url: str
    status: int
    body_sha256: str
    body_length: int
    observed_at: datetime
    disposition: AuthenticatedAttemptDisposition
    response_nonce_sha256: str | None
    content_type: str | None
    credential_sha256: str
    explicit_non_claims: frozenset[str] = field(
        default=frozenset(
            {
                "artifact_validity",
                "source_authority",
                "identity",
                "currentness",
                "complete_history",
                "standing",
                "governance_authority",
            }
        )
    )
    automatic_retries: int = 0
    redirects_followed: int = 0

    def __post_init__(self) -> None:
        if (
            self.receipt_id != _rid(self)
            or self.automatic_retries
            or self.redirects_followed
        ):
            _fail(
                "spaces_authenticated_receipt_invalid", "attempt receipt is not bound"
            )

    def to_provenance(self) -> dict[str, object]:
        return {
            "receiptId": self.receipt_id,
            "requestBindingReceiptId": self.request_binding_receipt_id,
            "attemptId": self.attempt_id,
            "artifactRequestId": self.artifact_request_id,
            "requestedUrl": self.requested_url,
            "status": self.status,
            "bodySha256": self.body_sha256,
            "bodyLength": self.body_length,
            "observedAt": self.observed_at.isoformat(),
            "disposition": self.disposition.value,
            "responseNonceSha256": self.response_nonce_sha256,
            "contentType": self.content_type,
            "credentialSha256": self.credential_sha256,
            "explicitNonClaims": sorted(self.explicit_non_claims),
            "automaticRetries": 0,
            "redirectsFollowed": 0,
        }


def _rid(r: AuthenticatedAttemptReceipt) -> str:
    vals = (
        SA9DD_AUTHENTICATED_ACQUISITION_METHOD,
        SA9DD_AUTHENTICATED_ACQUISITION_VERSION,
        SA9DD_AUTHENTICATED_ACQUISITION_DOCTRINE,
        r.request_binding_receipt_id,
        r.attempt_id,
        r.artifact_request_id,
        r.requested_url,
        str(r.status),
        r.body_sha256,
        str(r.body_length),
        r.observed_at.isoformat(),
        r.disposition.value,
        r.response_nonce_sha256 or "-",
        r.content_type or "-",
        r.credential_sha256,
    )
    return "sha256:" + _sha("\x00".join(vals).encode())


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


class AuthenticatedNonceChallenge(Exception):
    def __init__(
        self, receipt: AuthenticatedAttemptReceipt, nonce: CredentialNonce
    ) -> None:
        super().__init__(
            "server supplied a new DPoP nonce; construct a fresh request attempt"
        )
        self.receipt = receipt
        self.nonce = nonce


@dataclass(slots=True)
class AuthenticatedSpaceArtifactProvider:
    source_endpoint: str
    timeout_seconds: float = 5.0
    maximum_car_bytes: int = 16 << 20
    maximum_json_bytes: int = 1 << 20
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC), repr=False)
    _receipts: dict[str, AuthenticatedAttemptReceipt] = field(
        default_factory=dict, init=False, repr=False
    )

    @property
    def automatic_retries(self) -> int:
        return 0

    def receipt(self, receipt_id: str) -> AuthenticatedAttemptReceipt:
        return self._receipts[receipt_id]

    def _perform(
        self, request: CredentialAuthenticatedRequest, maximum: int
    ) -> tuple[bytes, AuthenticatedAttemptReceipt]:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect()
        )
        req = urllib.request.Request(
            request.url, method="GET", headers=request.controlled_headers()
        )
        observed = self.clock()
        if not isinstance(observed, datetime) or observed.utcoffset() is None:
            _fail(
                "spaces_authenticated_time_invalid",
                "authenticated acquisition clock must return an aware time",
            )
        observed = observed.astimezone(UTC)
        try:
            response = opener.open(req, timeout=self.timeout_seconds)
            status = response.status
            headers = response.headers
            body = response.read(maximum + 1)
        except urllib.error.HTTPError as exc:
            status = exc.code
            headers = exc.headers
            body = exc.read(maximum + 1)
        except Exception as exc:
            raise ValidationError(
                "spaces_authenticated_http_failure", "authenticated HTTP attempt failed"
            ) from exc
        if status in {301, 302, 303, 307, 308}:
            _fail(
                "spaces_authenticated_redirect_refused",
                "authenticated redirects are prohibited",
            )
        if len(body) > maximum:
            _fail(
                "spaces_authenticated_body_oversized",
                "authenticated response exceeds bound",
            )
        content_length = headers.get("Content-Length")
        if content_length is not None and int(content_length) != len(body):
            _fail("spaces_authenticated_body_truncated", "response length mismatch")
        nonce = headers.get("DPoP-Nonce")
        disposition = (
            AuthenticatedAttemptDisposition.ACQUIRED
            if status == 200
            else (
                AuthenticatedAttemptDisposition.NONCE_CHALLENGE
                if nonce
                else AuthenticatedAttemptDisposition.REFUSED
            )
        )
        fields = dict(
            receipt_id="",
            request_binding_receipt_id=request.receipt.receipt_id,
            attempt_id=request.receipt.attempt_id,
            artifact_request_id=request.receipt.artifact_request_id,
            requested_url=request.url,
            status=status,
            body_sha256=_sha(body),
            body_length=len(body),
            observed_at=observed,
            disposition=disposition,
            response_nonce_sha256=_sha(nonce.encode()) if nonce else None,
            content_type=headers.get("Content-Type"),
            credential_sha256=request.receipt.credential_sha256,
        )
        provisional = AuthenticatedAttemptReceipt.__new__(AuthenticatedAttemptReceipt)
        for k, v in fields.items():
            object.__setattr__(provisional, k, v)
        object.__setattr__(
            provisional,
            "explicit_non_claims",
            AuthenticatedAttemptReceipt.__dataclass_fields__[
                "explicit_non_claims"
            ].default,
        )
        object.__setattr__(provisional, "automatic_retries", 0)
        object.__setattr__(provisional, "redirects_followed", 0)
        fields["receipt_id"] = _rid(provisional)
        receipt = AuthenticatedAttemptReceipt(**fields)
        self._receipts[receipt.receipt_id] = receipt
        if disposition is AuthenticatedAttemptDisposition.NONCE_CHALLENGE:
            assert nonce is not None
            from .credential_request import _origin_htu

            origin, _ = _origin_htu(request.url, True)
            raise AuthenticatedNonceChallenge(
                receipt,
                CredentialNonce(nonce, origin, request.credential.dpop_key.session_ref),
            )
        if disposition is not AuthenticatedAttemptDisposition.ACQUIRED:
            _fail(
                "spaces_authenticated_http_status",
                "authenticated endpoint refused request",
            )
        return body, receipt

    def _source(self, r: AuthenticatedAttemptReceipt) -> TransportSourceContext:
        return TransportSourceContext(
            transport_name=SA9DD_AUTHENTICATED_ACQUISITION_METHOD,
            source_endpoint=self.source_endpoint,
            artifact_ref=r.receipt_id,
            observed_at=r.observed_at,
            asserted_transport_security="credential-dpop-request-observed",
            asserted_service_identity=None,
        )

    def get_repo(
        self,
        artifact_request: FullRepoArtifactRequest,
        request: CredentialAuthenticatedRequest,
    ) -> ObservedCarArtifact:
        if request.receipt.artifact_request_id != artifact_request.identity.request_id:
            _fail("spaces_authenticated_request_mismatch", "artifact request mismatch")
        body, r = self._perform(request, self.maximum_car_bytes)
        return ObservedCarArtifact(artifact_request, self._source(r), body)

    def list_repo_ops(
        self,
        artifact_request: RepoOpsArtifactRequest,
        request: CredentialAuthenticatedRequest,
    ) -> ObservedRepoOpsArtifact:
        if request.receipt.artifact_request_id != artifact_request.identity.request_id:
            _fail("spaces_authenticated_request_mismatch", "artifact request mismatch")
        body, r = self._perform(request, self.maximum_json_bytes)
        try:
            raw = json.loads(body)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValidationError(
                "spaces_authenticated_json_invalid", "response is not JSON"
            ) from exc
        if not isinstance(raw, Mapping):
            _fail("spaces_authenticated_json_invalid", "response is not an object")
        page = parse_list_repo_ops_page(
            raw,
            ordinal=0,
            request_since=artifact_request.since,
            request_cursor=artifact_request.cursor,
            received_at=r.observed_at,
        )
        return ObservedRepoOpsArtifact(artifact_request, self._source(r), (page,))


__all__ = [
    "AuthenticatedAttemptDisposition",
    "AuthenticatedAttemptReceipt",
    "AuthenticatedNonceChallenge",
    "AuthenticatedSpaceArtifactProvider",
]
