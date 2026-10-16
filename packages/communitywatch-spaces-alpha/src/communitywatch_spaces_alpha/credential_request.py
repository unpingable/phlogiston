"""SA9d-d credential-bound DPoP GET requests; no network or artifact claims."""

from __future__ import annotations

import base64
import hashlib
import json
import urllib.parse
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from community_model import ValidationError

from .artifact_source import FullRepoArtifactRequest, RepoOpsArtifactRequest
from .compat import (
    SA9DD_AUTHENTICATED_ACQUISITION_DOCTRINE,
    SA9DD_AUTHENTICATED_ACQUISITION_METHOD,
    SA9DD_AUTHENTICATED_ACQUISITION_VERSION,
    XRPC_PATH_PREFIX,
)
from .credential import QualifiedSpaceCredential
from .crypto import verify_es256
from .oauth_request import BoundedReplayWindow, DpopEvaluationPolicy

ArtifactRequest = FullRepoArtifactRequest | RepoOpsArtifactRequest
_NON_CLAIMS = frozenset(
    {
        "artifact_validity",
        "source_authority",
        "currentness",
        "membership",
        "standing",
        "governance_authority",
        "effect_authorized",
    }
)


def _fail(reason: str, message: str) -> None:
    raise ValidationError(reason, message)


def _b64(v: bytes) -> str:
    return base64.urlsafe_b64encode(v).rstrip(b"=").decode("ascii")


def _unb64(v: str) -> bytes:
    return base64.urlsafe_b64decode(v + "=" * (-len(v) % 4))


def _json(v: object) -> bytes:
    return json.dumps(v, sort_keys=True, separators=(",", ":")).encode("ascii")


def _sha(v: bytes) -> str:
    return hashlib.sha256(v).hexdigest()


def _origin_htu(url: str, allow_loopback: bool) -> tuple[str, str]:
    try:
        p = urllib.parse.urlsplit(url)
        port = p.port
    except ValueError as exc:
        raise ValidationError(
            "spaces_credential_dpop_target_invalid", "invalid URL"
        ) from exc
    if p.fragment or not p.hostname or p.username or p.password:
        _fail(
            "spaces_credential_dpop_target_invalid", "ambiguous protected-resource URL"
        )
    host = p.hostname.lower()
    loopback = host in {"localhost", "127.0.0.1", "::1"}
    if p.scheme != "https" and not (allow_loopback and p.scheme == "http" and loopback):
        _fail(
            "spaces_credential_dpop_target_invalid",
            "HTTPS is required outside loopback fixtures",
        )
    rendered = f"[{host}]" if ":" in host else host
    default = 443 if p.scheme == "https" else 80
    origin = f"{p.scheme}://{rendered}" + (
        "" if port in {None, default} else f":{port}"
    )
    path = p.path or "/"
    if any(x in {".", ".."} for x in path.split("/")):
        _fail("spaces_credential_dpop_target_invalid", "dot segments are prohibited")
    return origin, origin + path


def artifact_request_url(base_url: str, request: ArtifactRequest) -> str:
    params = [
        ("space", request.identity.space.uri),
        ("repo", request.identity.repo_did),
    ]
    if isinstance(request, RepoOpsArtifactRequest):
        params += [
            ("since", request.since),
            ("limit", str(request.limit)),
            ("excludeValues", str(request.exclude_values).lower()),
        ]
        if request.cursor is not None:
            params.append(("cursor", request.cursor))
    return f"{base_url.rstrip('/')}{XRPC_PATH_PREFIX}{request.endpoint}?{urllib.parse.urlencode(params)}"


@dataclass(frozen=True, slots=True, repr=False)
class CredentialNonce:
    value: str
    server_origin: str
    session_ref: str

    def __post_init__(self) -> None:
        if not self.value or any(ord(c) < 0x21 for c in self.value):
            _fail("spaces_credential_dpop_nonce_invalid", "nonce is invalid")

    @property
    def digest(self) -> str:
        return _sha(self.value.encode())

    def __repr__(self) -> str:
        return f"CredentialNonce(sha256={self.digest!r}, server_origin={self.server_origin!r})"


class CredentialRequestClaim(StrEnum):
    TYPE = "dpop_jwt_type"
    ALGORITHM = "es256_algorithm"
    SIGNATURE = "proof_signature"
    CREDENTIAL_KEY = "credential_cnf_jkt_key"
    METHOD = "exact_http_method"
    TARGET = "exact_http_target_without_query"
    TIME = "bounded_proof_time"
    JTI = "bounded_jti_replay"
    ATH = "space_credential_hash"


@dataclass(frozen=True, slots=True)
class CredentialRequestReceipt:
    receipt_id: str
    attempt_id: str
    artifact_request_id: str
    request_url: str
    canonical_htu: str
    credential_receipt_id: str
    credential_sha256: str
    dpop_jwk_thumbprint: str
    proof_sha256: str
    jti: str
    iat: int
    nonce_sha256: str | None
    evaluated_at: datetime
    verified_claims: frozenset[CredentialRequestClaim]
    explicit_non_claims: frozenset[str] = field(default=_NON_CLAIMS)
    method: str = "GET"
    automatic_retries: int = 0
    redirects_allowed: bool = False
    governance_authority: bool = False

    def __post_init__(self) -> None:
        if self.receipt_id != _receipt_id(self):
            _fail("spaces_credential_request_receipt_invalid", "receipt binding failed")
        if (
            self.verified_claims != frozenset(CredentialRequestClaim)
            or self.explicit_non_claims != _NON_CLAIMS
            or self.governance_authority
        ):
            _fail(
                "spaces_credential_request_receipt_invalid", "claim boundary is invalid"
            )

    def to_provenance(self) -> dict[str, object]:
        return {
            "receiptId": self.receipt_id,
            "attemptId": self.attempt_id,
            "artifactRequestId": self.artifact_request_id,
            "requestUrl": self.request_url,
            "canonicalHtu": self.canonical_htu,
            "credentialReceiptId": self.credential_receipt_id,
            "credentialSha256": self.credential_sha256,
            "dpopJwkThumbprint": self.dpop_jwk_thumbprint,
            "proofSha256": self.proof_sha256,
            "jti": self.jti,
            "iat": self.iat,
            "nonceSha256": self.nonce_sha256,
            "evaluatedAt": self.evaluated_at.isoformat(),
            "verifiedClaims": sorted(x.value for x in self.verified_claims),
            "explicitNonClaims": sorted(self.explicit_non_claims),
            "automaticRetries": 0,
            "redirectsAllowed": False,
            "governanceAuthority": False,
        }


def _receipt_id(r: CredentialRequestReceipt) -> str:
    values = (
        SA9DD_AUTHENTICATED_ACQUISITION_METHOD,
        SA9DD_AUTHENTICATED_ACQUISITION_VERSION,
        SA9DD_AUTHENTICATED_ACQUISITION_DOCTRINE,
        r.attempt_id,
        r.artifact_request_id,
        r.request_url,
        r.canonical_htu,
        r.credential_receipt_id,
        r.credential_sha256,
        r.dpop_jwk_thumbprint,
        r.proof_sha256,
        r.jti,
        str(r.iat),
        r.nonce_sha256 or "-",
        r.evaluated_at.isoformat(),
        *(x.value for x in sorted(r.verified_claims, key=lambda x: x.value)),
    )
    return "sha256:" + _sha("\x00".join(values).encode())


@dataclass(frozen=True, slots=True, repr=False)
class CredentialAuthenticatedRequest:
    url: str
    proof: str
    credential: QualifiedSpaceCredential
    receipt: CredentialRequestReceipt

    def controlled_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"DPoP {self.credential.credential._for_authenticated_request()}",
            "DPoP": self.proof,
            "Accept-Encoding": "identity",
        }

    def __repr__(self) -> str:
        return f"CredentialAuthenticatedRequest(url={self.url!r}, receipt_id={self.receipt.receipt_id!r}, <redacted>)"


def construct_credential_get_request(
    *,
    credential: QualifiedSpaceCredential,
    artifact_request: ArtifactRequest,
    base_url: str,
    attempt_id: str,
    jti: str,
    issued_at: datetime,
    evaluated_at: datetime,
    replay_window: BoundedReplayWindow,
    nonce: CredentialNonce | None = None,
    allow_insecure_loopback_fixture: bool = False,
    policy: DpopEvaluationPolicy = DpopEvaluationPolicy(),
) -> CredentialAuthenticatedRequest:
    if credential.receipt.space != artifact_request.identity.space:
        _fail(
            "spaces_credential_request_space_mismatch",
            "credential is for another Space",
        )
    now = int(evaluated_at.astimezone(UTC).timestamp())
    if not credential.receipt.issued_at <= now < credential.receipt.expires_at:
        _fail("spaces_credential_request_expired", "credential is outside validity")
    url = artifact_request_url(base_url, artifact_request)
    origin, htu = _origin_htu(url, allow_insecure_loopback_fixture)
    if nonce and (
        nonce.server_origin != origin
        or nonce.session_ref != credential.dpop_key.session_ref
    ):
        _fail(
            "spaces_credential_dpop_nonce_mismatch",
            "nonce belongs to another server/session",
        )
    iat = int(issued_at.astimezone(UTC).timestamp())
    payload = {
        "htm": "GET",
        "htu": htu,
        "iat": iat,
        "jti": jti,
        "ath": credential.credential.ath,
    }
    if nonce:
        payload["nonce"] = nonce.value
    header = {
        "typ": "dpop+jwt",
        "alg": "ES256",
        "jwk": dict(credential.dpop_key.public_jwk),
    }
    h, p = _b64(_json(header)), _b64(_json(payload))
    signing = f"{h}.{p}".encode()
    proof = f"{h}.{p}.{_b64(credential.dpop_key._sign_dpop_proof(signing))}"
    receipt = verify_credential_get_request(
        credential=credential,
        artifact_request=artifact_request,
        request_url=url,
        method="GET",
        proof=proof,
        attempt_id=attempt_id,
        expected_nonce=nonce,
        evaluated_at=evaluated_at,
        replay_window=replay_window,
        allow_insecure_loopback_fixture=allow_insecure_loopback_fixture,
        policy=policy,
    )
    return CredentialAuthenticatedRequest(url, proof, credential, receipt)


def verify_credential_get_request(
    *,
    credential: QualifiedSpaceCredential,
    artifact_request: ArtifactRequest,
    request_url: str,
    method: str,
    proof: str,
    attempt_id: str,
    expected_nonce: CredentialNonce | None,
    evaluated_at: datetime,
    replay_window: BoundedReplayWindow,
    allow_insecure_loopback_fixture: bool = False,
    policy: DpopEvaluationPolicy = DpopEvaluationPolicy(),
) -> CredentialRequestReceipt:
    if credential.receipt.space != artifact_request.identity.space:
        _fail(
            "spaces_credential_request_space_mismatch",
            "credential is for another Space",
        )
    if (
        method != "GET"
        or artifact_request_url(
            request_url.split(XRPC_PATH_PREFIX)[0], artifact_request
        )
        != request_url
    ):
        _fail(
            "spaces_credential_dpop_target_mismatch",
            "request does not match artifact target",
        )
    origin, htu = _origin_htu(request_url, allow_insecure_loopback_fixture)
    if expected_nonce and (
        expected_nonce.server_origin != origin
        or expected_nonce.session_ref != credential.dpop_key.session_ref
    ):
        _fail("spaces_credential_dpop_nonce_mismatch", "nonce context mismatch")
    try:
        hs, ps, ss = proof.split(".")
        header = json.loads(_unb64(hs))
        payload = json.loads(_unb64(ps))
        signature = _unb64(ss)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "spaces_credential_dpop_invalid", "invalid DPoP JWT"
        ) from exc
    if header != {
        "alg": "ES256",
        "jwk": dict(credential.dpop_key.public_jwk),
        "typ": "dpop+jwt",
    }:
        _fail("spaces_credential_dpop_key_mismatch", "proof header/key mismatch")
    required = {"htm", "htu", "iat", "jti", "ath"} | (
        {"nonce"} if expected_nonce else set()
    )
    if (
        set(payload) != required
        or payload.get("htm") != method
        or payload.get("htu") != htu
        or payload.get("ath") != credential.credential.ath
    ):
        _fail(
            "spaces_credential_dpop_claim_mismatch",
            "proof request/token claims mismatch",
        )
    if expected_nonce and payload.get("nonce") != expected_nonce.value:
        _fail("spaces_credential_dpop_nonce_mismatch", "proof nonce mismatch")
    if not verify_es256(
        credential.dpop_key.compressed_public_key, f"{hs}.{ps}".encode(), signature
    ):
        _fail("spaces_credential_dpop_signature_invalid", "proof signature invalid")
    iat, jti = payload.get("iat"), payload.get("jti")
    if (
        isinstance(iat, bool)
        or not isinstance(iat, int)
        or not isinstance(jti, str)
        or not jti
    ):
        _fail("spaces_credential_dpop_claim_mismatch", "proof time/jti invalid")
    age = int(evaluated_at.astimezone(UTC).timestamp()) - iat
    if age > policy.maximum_age_seconds or age < -policy.future_skew_seconds:
        _fail("spaces_credential_dpop_time_invalid", "proof time outside window")
    replay_window.record(jti)
    fields = dict(
        receipt_id="",
        attempt_id=attempt_id,
        artifact_request_id=artifact_request.identity.request_id,
        request_url=request_url,
        canonical_htu=htu,
        credential_receipt_id=credential.receipt.receipt_id,
        credential_sha256=credential.receipt.credential_sha256,
        dpop_jwk_thumbprint=credential.dpop_key.thumbprint,
        proof_sha256=_sha(proof.encode()),
        jti=jti,
        iat=iat,
        nonce_sha256=expected_nonce.digest if expected_nonce else None,
        evaluated_at=evaluated_at.astimezone(UTC),
        verified_claims=frozenset(CredentialRequestClaim),
    )
    provisional = CredentialRequestReceipt.__new__(CredentialRequestReceipt)
    for k, v in fields.items():
        object.__setattr__(provisional, k, v)
    object.__setattr__(provisional, "explicit_non_claims", _NON_CLAIMS)
    object.__setattr__(provisional, "method", "GET")
    object.__setattr__(provisional, "automatic_retries", 0)
    object.__setattr__(provisional, "redirects_allowed", False)
    object.__setattr__(provisional, "governance_authority", False)
    fields["receipt_id"] = _receipt_id(provisional)
    return CredentialRequestReceipt(**fields)


__all__ = [
    "CredentialAuthenticatedRequest",
    "CredentialNonce",
    "CredentialRequestClaim",
    "CredentialRequestReceipt",
    "artifact_request_url",
    "construct_credential_get_request",
    "verify_credential_get_request",
]
