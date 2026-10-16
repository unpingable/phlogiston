"""SA9d-b fixture-only Spaces delegation-token qualification.

A qualified token establishes a bounded user/PDS delegation to ask a Space
authority for access.  It is not a Space admission decision, credential,
membership statement, or governance authorization.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from community_model import ValidationError
from community_model.identifiers import validate_did

from .compat import (
    ATPROTO_SPACE_HOST_FRAGMENT,
    DELEGATION_TOKEN_ENDPOINT,
    SA9D_SPACES_PROPOSAL_COMMIT,
    SA9DB_DELEGATION_DOCTRINE,
    SA9DB_DELEGATION_KEY_ID,
    SA9DB_DELEGATION_LIFETIME_SECONDS,
    SA9DB_DELEGATION_METHOD,
    SA9DB_DELEGATION_TOKEN_TYP,
    SA9DB_DELEGATION_VERSION,
)
from .crypto import verify_es256, verify_es256k
from .did_binding import (
    DidBindingReceipt,
    DidBindingSelection,
    DidInterpretationProfile,
    verification_key_bytes,
)
from .did_resolution import ResolvedDidDocument, require_resolved_document_binding
from .model import SpaceIdentity
from .oauth_request import (
    AuthenticatedGetRequest,
    OAuthGrantContext,
    SpaceAction,
    SpaceScopeEvaluation,
)

_JTI = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
_B64URL = re.compile(r"^[A-Za-z0-9_-]+$")
_NON_CLAIMS = frozenset(
    {
        "oauth_ceremony_authentic",
        "client_application_identity",
        "space_authority_admission",
        "space_credential",
        "space_access",
        "space_membership",
        "community_standing",
        "user_intent",
        "governed_authorization",
        "artifact_validity",
        "repository_currentness",
    }
)


def _fail(reason: str, message: str) -> None:
    raise ValidationError(reason, message)


def _utc(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        _fail("spaces_delegation_invalid", f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _unb64url(value: str) -> bytes:
    if not isinstance(value, str) or not _B64URL.fullmatch(value):
        _fail("spaces_delegation_jwt_invalid", "JWT segment is not unpadded base64url")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise ValidationError(
            "spaces_delegation_jwt_invalid", "JWT segment is invalid base64url"
        ) from exc


class _DuplicateJsonKey(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


def _decode_compact_jwt(
    token: str,
) -> tuple[dict[str, object], dict[str, object], bytes, bytes]:
    if not isinstance(token, str) or token.count(".") != 2:
        _fail("spaces_delegation_jwt_invalid", "delegation token is not a compact JWT")
    header_segment, payload_segment, signature_segment = token.split(".")
    try:
        header = json.loads(
            _unb64url(header_segment), object_pairs_hook=_reject_duplicate_keys
        )
        payload = json.loads(
            _unb64url(payload_segment), object_pairs_hook=_reject_duplicate_keys
        )
        signature = _unb64url(signature_segment)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValidationError(
            "spaces_delegation_jwt_invalid", "delegation JWT JSON is ambiguous"
        ) from exc
    if not isinstance(header, dict) or not isinstance(payload, dict):
        _fail("spaces_delegation_jwt_invalid", "JWT header and payload must be objects")
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    return header, payload, signature, signing_input


@dataclass(frozen=True, slots=True, repr=False)
class SecretDelegationToken:
    """Runtime-only delegation credential; receipts retain only its digest."""

    __raw: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.__raw, str)
            or not self.__raw
            or any(not 0x21 <= ord(character) <= 0x7E for character in self.__raw)
        ):
            _fail("spaces_delegation_token_invalid", "delegation token is invalid")

    @property
    def digest(self) -> str:
        return _sha256(self.__raw.encode("ascii"))

    def _for_qualification(self) -> str:
        return self.__raw

    def __repr__(self) -> str:
        return f"SecretDelegationToken(sha256={self.digest!r}, <redacted>)"

    def __reduce__(self) -> object:
        raise TypeError("delegation tokens are runtime-only and not serializable")


@dataclass(frozen=True, slots=True)
class DelegationEvaluationPolicy:
    required_lifetime_seconds: int = SA9DB_DELEGATION_LIFETIME_SECONDS

    def __post_init__(self) -> None:
        if self.required_lifetime_seconds != SA9DB_DELEGATION_LIFETIME_SECONDS:
            _fail(
                "spaces_delegation_policy_invalid",
                "SA9d-b is pinned to the alpha delegation lifetime",
            )


@dataclass(slots=True)
class BoundedDelegationReplayWindow:
    domain_id: str
    _seen: set[tuple[str, str]] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.domain_id, str) or not self.domain_id:
            _fail("spaces_delegation_replay_invalid", "replay domain is required")

    def record(self, issuer: str, jti: str) -> None:
        replay_key = (issuer, jti)
        if replay_key in self._seen:
            _fail(
                "spaces_delegation_replay",
                "delegation jti was reused in this bounded domain",
            )
        self._seen.add(replay_key)


class VerifiedDelegationClaim(StrEnum):
    TYPE = "delegation_jwt_type"
    ALGORITHM = "account_key_algorithm"
    KEY_ID = "account_signing_key_identifier"
    ISSUER = "issuer_matches_oauth_subject"
    SPACE_SUBJECT = "exact_space_subject"
    SPACE_HOST_AUDIENCE = "exact_space_host_audience"
    TIME_WINDOW = "alpha_time_window"
    JTI = "bounded_single_use_jti"
    SIGNATURE = "account_key_signature"
    KEY_PROVENANCE = "resolved_document_account_key_selection"
    OAUTH_READ = "covering_oauth_read_grant"
    DPOP_REQUEST = "bound_get_delegation_token_request"


def _receipt_id(receipt: DelegationTokenReceipt) -> str:
    values = (
        "spaces-delegation-receipt-v1",
        SA9DB_DELEGATION_METHOD,
        SA9DB_DELEGATION_VERSION,
        SA9DB_DELEGATION_DOCTRINE,
        SA9D_SPACES_PROPOSAL_COMMIT,
        receipt.token_sha256,
        receipt.issuer_did,
        receipt.space.uri,
        receipt.audience,
        receipt.algorithm,
        receipt.key_id,
        str(receipt.issued_at),
        str(receipt.expires_at),
        receipt.jti,
        receipt.account_key_receipt_id,
        receipt.did_resolution_receipt_id,
        receipt.did_resolution_method,
        receipt.oauth_grant_receipt_id,
        receipt.dpop_request_receipt_id,
        receipt.dpop_jwk_thumbprint,
        receipt.space_scope_evaluation_id,
        receipt.replay_domain_id,
        receipt.evaluated_at.isoformat(),
        *(
            claim.value
            for claim in sorted(receipt.verified_claims, key=lambda x: x.value)
        ),
    )
    return "sha256:" + _sha256("\x00".join(values).encode())


@dataclass(frozen=True, slots=True)
class DelegationTokenReceipt:
    receipt_id: str
    token_sha256: str
    issuer_did: str
    space: SpaceIdentity
    audience: str
    algorithm: str
    key_id: str
    issued_at: int
    expires_at: int
    jti: str
    account_key_receipt_id: str
    did_resolution_receipt_id: str
    did_resolution_method: str
    oauth_grant_receipt_id: str
    dpop_request_receipt_id: str
    dpop_jwk_thumbprint: str
    space_scope_evaluation_id: str
    replay_domain_id: str
    evaluated_at: datetime
    verified_claims: frozenset[VerifiedDelegationClaim]
    explicit_non_claims: frozenset[str] = field(default=_NON_CLAIMS)
    qualification_method: str = field(default=SA9DB_DELEGATION_METHOD, init=False)
    qualifier_version: str = field(default=SA9DB_DELEGATION_VERSION, init=False)
    doctrine: str = field(default=SA9DB_DELEGATION_DOCTRINE, init=False)
    space_authority_admission: bool = False
    space_credential: bool = False
    space_access: bool = False
    standing: bool = False
    governance_authority: bool = False
    effect_authorized: bool = False

    def __post_init__(self) -> None:
        validate_did(self.issuer_did)
        if not isinstance(self.space, SpaceIdentity):
            _fail("spaces_delegation_receipt_invalid", "Space identity is invalid")
        expected_audience = f"{self.space.authority_did}#{ATPROTO_SPACE_HOST_FRAGMENT}"
        if self.audience != expected_audience:
            _fail("spaces_delegation_receipt_invalid", "audience is not exact")
        if self.algorithm not in {"ES256", "ES256K"}:
            _fail("spaces_delegation_receipt_invalid", "algorithm is unsupported")
        if self.key_id != SA9DB_DELEGATION_KEY_ID:
            _fail("spaces_delegation_receipt_invalid", "key identifier is invalid")
        if self.expires_at - self.issued_at != SA9DB_DELEGATION_LIFETIME_SECONDS:
            _fail("spaces_delegation_receipt_invalid", "lifetime is not pinned")
        if not _JTI.fullmatch(self.jti):
            _fail("spaces_delegation_receipt_invalid", "jti is outside bounds")
        if len(self.token_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.token_sha256
        ):
            _fail("spaces_delegation_receipt_invalid", "token digest is invalid")
        for value in (
            self.account_key_receipt_id,
            self.did_resolution_receipt_id,
            self.oauth_grant_receipt_id,
            self.dpop_request_receipt_id,
            self.space_scope_evaluation_id,
        ):
            if not isinstance(value, str) or not value.startswith("sha256:"):
                _fail(
                    "spaces_delegation_receipt_invalid", "receipt reference is invalid"
                )
        if not self.did_resolution_method or not self.dpop_jwk_thumbprint:
            _fail("spaces_delegation_receipt_invalid", "provenance is incomplete")
        if not self.replay_domain_id:
            _fail("spaces_delegation_receipt_invalid", "replay domain is absent")
        object.__setattr__(
            self, "evaluated_at", _utc(self.evaluated_at, field_name="evaluated_at")
        )
        if self.verified_claims != frozenset(VerifiedDelegationClaim):
            _fail("spaces_delegation_receipt_invalid", "claim set is not exact")
        if self.explicit_non_claims != _NON_CLAIMS or any(
            (
                self.space_authority_admission,
                self.space_credential,
                self.space_access,
                self.standing,
                self.governance_authority,
                self.effect_authorized,
            )
        ):
            _fail(
                "spaces_delegation_receipt_invalid",
                "delegation cannot mint access or governance claims",
            )
        if self.receipt_id != _receipt_id(self):
            _fail("spaces_delegation_receipt_invalid", "receipt is not bound")

    def to_provenance(self) -> dict[str, object]:
        return {
            "receiptId": self.receipt_id,
            "tokenSha256": self.token_sha256,
            "issuerDid": self.issuer_did,
            "space": self.space.uri,
            "audience": self.audience,
            "algorithm": self.algorithm,
            "keyId": self.key_id,
            "issuedAt": self.issued_at,
            "expiresAt": self.expires_at,
            "jti": self.jti,
            "accountKeyReceiptId": self.account_key_receipt_id,
            "didResolutionReceiptId": self.did_resolution_receipt_id,
            "didResolutionMethod": self.did_resolution_method,
            "oauthGrantReceiptId": self.oauth_grant_receipt_id,
            "dpopRequestReceiptId": self.dpop_request_receipt_id,
            "dpopJwkThumbprint": self.dpop_jwk_thumbprint,
            "spaceScopeEvaluationId": self.space_scope_evaluation_id,
            "replayDomainId": self.replay_domain_id,
            "evaluatedAt": self.evaluated_at.isoformat(),
            "verifiedClaims": sorted(claim.value for claim in self.verified_claims),
            "explicitNonClaims": sorted(self.explicit_non_claims),
            "spaceAuthorityAdmission": False,
            "spaceCredential": False,
            "spaceAccess": False,
            "standing": False,
            "governanceAuthority": False,
            "effectAuthorized": False,
        }


@dataclass(frozen=True, slots=True, repr=False)
class QualifiedDelegationToken:
    token: SecretDelegationToken
    receipt: DelegationTokenReceipt

    def __post_init__(self) -> None:
        if self.token.digest != self.receipt.token_sha256:
            _fail(
                "spaces_delegation_token_mismatch", "runtime token differs from receipt"
            )

    def __repr__(self) -> str:
        return f"QualifiedDelegationToken(receipt_id={self.receipt.receipt_id!r}, <redacted>)"

    def __reduce__(self) -> object:
        raise TypeError("qualified delegation credentials are runtime-only")


def _require_composition(
    *,
    resolved_user: ResolvedDidDocument,
    account_key: DidBindingReceipt,
    oauth_grant: OAuthGrantContext,
    oauth_request: AuthenticatedGetRequest,
    scope_evaluation: SpaceScopeEvaluation,
    space: SpaceIdentity,
) -> None:
    require_resolved_document_binding(resolved_user, resolved_user.document_bytes)
    if (
        account_key.profile is not DidInterpretationProfile.ACCOUNT_SIGNING_KEY
        or account_key.selection is not DidBindingSelection.ACCOUNT_KEY
        or account_key.expected_did != resolved_user.expected_did
        or account_key.document_sha256 != resolved_user.document_sha256
        or account_key.document_provenance_ref != resolved_user.method_receipt_id
    ):
        _fail(
            "spaces_delegation_key_provenance_mismatch",
            "account key is not bound to the supplied DID resolution",
        )
    grant = oauth_grant.receipt
    request = oauth_request.receipt
    if (
        grant.receipt_id != request.oauth_grant_receipt_id
        or oauth_request.grant.receipt.receipt_id != grant.receipt_id
        or oauth_request.grant.access_token.digest != grant.access_token_sha256
        or oauth_request.url != request.request_url
        or grant.receipt_id != scope_evaluation.oauth_grant_receipt_id
        or grant.token_subject != resolved_user.expected_did
        or grant.dpop_jwk_thumbprint != request.dpop_jwk_thumbprint
        or request.subject_did != grant.token_subject
        or request.client_id != grant.client_id
        or request.space_scope_evaluation_sha256
        != scope_evaluation.evaluation_id.removeprefix("sha256:")
    ):
        _fail(
            "spaces_delegation_oauth_binding_mismatch",
            "OAuth, DPoP request, and identity receipts do not compose",
        )
    if (
        not scope_evaluation.permitted
        or scope_evaluation.request.action is not SpaceAction.READ
        or scope_evaluation.request.space != space
    ):
        _fail(
            "spaces_delegation_oauth_read_required",
            "delegation requires a covering whole-Space read grant",
        )
    parsed_url = urllib.parse.urlsplit(oauth_request.url)
    pairs = urllib.parse.parse_qsl(
        parsed_url.query, keep_blank_values=True, strict_parsing=True
    )
    if parsed_url.path != f"/xrpc/{DELEGATION_TOKEN_ENDPOINT}" or pairs != [
        ("space", space.uri)
    ]:
        _fail(
            "spaces_delegation_request_mismatch",
            "DPoP receipt is not for getDelegationToken",
        )


def qualify_delegation_token(
    *,
    token: SecretDelegationToken,
    expected_space: SpaceIdentity,
    resolved_user: ResolvedDidDocument,
    account_key: DidBindingReceipt,
    oauth_grant: OAuthGrantContext,
    oauth_request: AuthenticatedGetRequest,
    scope_evaluation: SpaceScopeEvaluation,
    evaluated_at: datetime,
    replay_window: BoundedDelegationReplayWindow,
    policy: DelegationEvaluationPolicy = DelegationEvaluationPolicy(),
) -> QualifiedDelegationToken:
    """Verify one alpha delegation token and its bounded acquisition context."""

    if not isinstance(token, SecretDelegationToken):
        _fail("spaces_delegation_token_invalid", "runtime delegation token is required")
    if not isinstance(expected_space, SpaceIdentity):
        _fail("spaces_delegation_space_mismatch", "expected Space is required")
    if not isinstance(replay_window, BoundedDelegationReplayWindow):
        _fail("spaces_delegation_replay_invalid", "bounded replay window is required")
    if not isinstance(policy, DelegationEvaluationPolicy):
        _fail("spaces_delegation_policy_invalid", "delegation policy is invalid")
    _require_composition(
        resolved_user=resolved_user,
        account_key=account_key,
        oauth_grant=oauth_grant,
        oauth_request=oauth_request,
        scope_evaluation=scope_evaluation,
        space=expected_space,
    )
    raw = token._for_qualification()
    header, payload, signature, signing_input = _decode_compact_jwt(raw)
    if set(header) != {"typ", "alg", "kid"}:
        _fail("spaces_delegation_header_mismatch", "delegation header shape is invalid")
    if header.get("typ") != SA9DB_DELEGATION_TOKEN_TYP:
        _fail("spaces_delegation_header_mismatch", "delegation token type is invalid")
    algorithm = header.get("alg")
    if not isinstance(algorithm, str) or algorithm not in {"ES256", "ES256K"}:
        _fail(
            "spaces_delegation_algorithm_unsupported",
            "delegation algorithm is unsupported",
        )
    if header.get("kid") != SA9DB_DELEGATION_KEY_ID:
        _fail("spaces_delegation_key_mismatch", "delegation kid must be #atproto")
    if set(payload) != {"iss", "sub", "aud", "iat", "exp", "jti"}:
        _fail(
            "spaces_delegation_payload_mismatch",
            "delegation payload must contain only the pinned claims and no lxm",
        )
    issuer = payload.get("iss")
    if (
        issuer != oauth_grant.receipt.token_subject
        or issuer != resolved_user.expected_did
    ):
        _fail("spaces_delegation_issuer_mismatch", "issuer differs from OAuth subject")
    assert isinstance(issuer, str)
    validate_did(issuer)
    if payload.get("sub") != expected_space.uri:
        _fail("spaces_delegation_space_mismatch", "delegation subject is another Space")
    audience = f"{expected_space.authority_did}#{ATPROTO_SPACE_HOST_FRAGMENT}"
    if payload.get("aud") != audience:
        _fail("spaces_delegation_audience_mismatch", "delegation audience is not exact")
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    jti = payload.get("jti")
    if (
        not isinstance(issued_at, int)
        or isinstance(issued_at, bool)
        or not isinstance(expires_at, int)
        or isinstance(expires_at, bool)
        or expires_at - issued_at != policy.required_lifetime_seconds
    ):
        _fail("spaces_delegation_time_invalid", "delegation lifetime is invalid")
    evaluated = _utc(evaluated_at, field_name="evaluated_at")
    evaluation_second = int(evaluated.timestamp())
    if evaluation_second < issued_at or evaluation_second >= expires_at:
        _fail("spaces_delegation_expired", "delegation is outside its validity window")
    if not isinstance(jti, str) or not _JTI.fullmatch(jti):
        _fail("spaces_delegation_jti_invalid", "delegation jti is outside bounds")
    curve = account_key.selected_key_curve
    if (algorithm, curve) not in {("ES256", "p256"), ("ES256K", "k256")}:
        _fail(
            "spaces_delegation_key_mismatch", "JWT algorithm differs from account key"
        )
    public_key = verification_key_bytes(account_key)
    verifier = verify_es256 if algorithm == "ES256" else verify_es256k
    if not verifier(public_key, signing_input, signature):
        _fail("spaces_delegation_signature_invalid", "delegation signature is invalid")
    replay_window.record(issuer, jti)
    fields = dict(
        receipt_id="",
        token_sha256=token.digest,
        issuer_did=issuer,
        space=expected_space,
        audience=audience,
        algorithm=algorithm,
        key_id=SA9DB_DELEGATION_KEY_ID,
        issued_at=issued_at,
        expires_at=expires_at,
        jti=jti,
        account_key_receipt_id=account_key.receipt_id,
        did_resolution_receipt_id=resolved_user.method_receipt_id,
        did_resolution_method=resolved_user.method.value,
        oauth_grant_receipt_id=oauth_grant.receipt.receipt_id,
        dpop_request_receipt_id=oauth_request.receipt.receipt_id,
        dpop_jwk_thumbprint=oauth_request.receipt.dpop_jwk_thumbprint,
        space_scope_evaluation_id=scope_evaluation.evaluation_id,
        replay_domain_id=replay_window.domain_id,
        evaluated_at=evaluated,
        verified_claims=frozenset(VerifiedDelegationClaim),
    )
    probe = DelegationTokenReceipt.__new__(DelegationTokenReceipt)
    for name, value in fields.items():
        object.__setattr__(probe, name, value)
    receipt_id = _receipt_id(probe)
    receipt = DelegationTokenReceipt(
        receipt_id=receipt_id,
        **{key: value for key, value in fields.items() if key != "receipt_id"},
    )
    return QualifiedDelegationToken(token=token, receipt=receipt)


__all__ = [
    "BoundedDelegationReplayWindow",
    "DelegationEvaluationPolicy",
    "DelegationTokenReceipt",
    "QualifiedDelegationToken",
    "SecretDelegationToken",
    "VerifiedDelegationClaim",
    "qualify_delegation_token",
]
