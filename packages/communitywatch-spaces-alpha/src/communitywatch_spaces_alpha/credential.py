"""SA9d-c fixture-only Spaces credential qualification.

A qualified credential has bounded alpha whole-Space read/sync semantics.  It
does not establish community standing, governance authority, or live host
acceptance.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from community_model import ValidationError
from community_model.identifiers import validate_did

from .compat import (
    SA9D_SPACES_PROPOSAL_COMMIT,
    SA9DC_CREDENTIAL_DOCTRINE,
    SA9DC_CREDENTIAL_LIFETIME_SECONDS,
    SA9DC_CREDENTIAL_METHOD,
    SA9DC_CREDENTIAL_TYP,
    SA9DC_CREDENTIAL_VERSION,
)
from .crypto import verify_es256, verify_es256k
from .delegation import DelegationTokenReceipt
from .did_binding import (
    DidBindingReceipt,
    DidBindingSelection,
    DidInterpretationProfile,
    normalize_service_origin,
    verification_key_bytes,
)
from .did_resolution import ResolvedDidDocument, require_resolved_document_binding
from .model import SpaceIdentity
from .oauth_request import DpopSessionKey

_JTI = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
_B64URL = re.compile(r"^[A-Za-z0-9_-]+$")
_NON_CLAIMS = frozenset(
    {
        "authority_admission_policy_or_reason",
        "credential_payload_names_applicant",
        "current_did_state",
        "live_host_acceptance",
        "repo_host_identity",
        "complete_history",
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
        _fail("spaces_credential_invalid", f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64url(value: str) -> bytes:
    if not isinstance(value, str) or not _B64URL.fullmatch(value):
        _fail("spaces_credential_jwt_invalid", "JWT segment is not unpadded base64url")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise ValidationError(
            "spaces_credential_jwt_invalid", "JWT segment is invalid base64url"
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
        _fail("spaces_credential_jwt_invalid", "credential is not a compact JWT")
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
            "spaces_credential_jwt_invalid", "credential JWT JSON is ambiguous"
        ) from exc
    if not isinstance(header, dict) or not isinstance(payload, dict):
        _fail("spaces_credential_jwt_invalid", "JWT header and payload must be objects")
    return (
        header,
        payload,
        signature,
        f"{header_segment}.{payload_segment}".encode("ascii"),
    )


@dataclass(frozen=True, slots=True, repr=False)
class SecretSpaceCredential:
    """Runtime-only credential; persistent receipts retain only digests."""

    __raw: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.__raw, str)
            or not self.__raw
            or any(not 0x21 <= ord(character) <= 0x7E for character in self.__raw)
        ):
            _fail("spaces_credential_invalid", "Space credential is invalid")

    @property
    def digest(self) -> str:
        return _sha256(self.__raw.encode("ascii"))

    @property
    def ath(self) -> str:
        return _b64url(hashlib.sha256(self.__raw.encode("ascii")).digest())

    def _for_authenticated_request(self) -> str:
        return self.__raw

    def __repr__(self) -> str:
        return f"SecretSpaceCredential(sha256={self.digest!r}, <redacted>)"

    def __reduce__(self) -> object:
        raise TypeError("Space credentials are runtime-only and not serializable")


@dataclass(frozen=True, slots=True)
class SpaceCredentialEvaluationPolicy:
    required_lifetime_seconds: int = SA9DC_CREDENTIAL_LIFETIME_SECONDS

    def __post_init__(self) -> None:
        if self.required_lifetime_seconds != SA9DC_CREDENTIAL_LIFETIME_SECONDS:
            _fail(
                "spaces_credential_policy_invalid",
                "SA9d-c is pinned to the alpha credential lifetime",
            )


@dataclass(slots=True)
class BoundedCredentialIssuanceReplayWindow:
    """Finite duplicate-result guard, not a credential-use replay database."""

    domain_id: str
    _seen: set[tuple[str, str]] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.domain_id, str) or not self.domain_id:
            _fail("spaces_credential_replay_invalid", "replay domain is required")

    def record(self, issuer: str, jti: str) -> None:
        key = (issuer, jti)
        if key in self._seen:
            _fail(
                "spaces_credential_issuance_replay",
                "credential issuance jti was reused in this bounded result domain",
            )
        self._seen.add(key)


class CredentialAccessSemantics(StrEnum):
    WHOLE_SPACE_READ_SYNC = "whole_space_read_sync"


class CredentialAudienceSemantics(StrEnum):
    NO_JWT_AUDIENCE_ANY_SPACE_REPO_HOST = "no_jwt_audience_any_space_repo_host"


class VerifiedSpaceCredentialClaim(StrEnum):
    TYPE = "space_credential_jwt_type"
    ALGORITHM = "space_authority_key_algorithm"
    KEY_ID = "selected_space_signing_key_identifier"
    ISSUER = "issuer_matches_space_authority"
    SPACE_SUBJECT = "exact_space_subject"
    NO_AUDIENCE = "jwt_audience_absent"
    DPOP_KEY = "cnf_jkt_matches_credential_dpop_key"
    TIME_WINDOW = "alpha_time_window"
    JTI = "bounded_issuance_jti"
    SIGNATURE = "space_authority_key_signature"
    KEY_PROVENANCE = "resolved_document_space_key_selection"
    HOST_CONTEXT = "resolved_document_space_host_selection"
    DELEGATION_CONTEXT = "matching_qualified_delegation_context"
    ACCESS_SEMANTICS = "whole_space_read_sync_semantics"


def _receipt_id(receipt: SpaceCredentialReceipt) -> str:
    values = (
        "spaces-credential-receipt-v1",
        SA9DC_CREDENTIAL_METHOD,
        SA9DC_CREDENTIAL_VERSION,
        SA9DC_CREDENTIAL_DOCTRINE,
        SA9D_SPACES_PROPOSAL_COMMIT,
        receipt.credential_sha256,
        receipt.credential_ath,
        receipt.authority_did,
        receipt.space.uri,
        receipt.applicant_context_did,
        receipt.algorithm,
        receipt.key_id,
        str(receipt.issued_at),
        str(receipt.expires_at),
        receipt.jti,
        receipt.cnf_jkt,
        receipt.access_semantics.value,
        receipt.audience_semantics.value,
        receipt.issuance_host_origin,
        receipt.authority_key_receipt_id,
        receipt.authority_host_receipt_id,
        receipt.did_resolution_receipt_id,
        receipt.did_resolution_method,
        receipt.delegation_receipt_id,
        receipt.delegation_token_sha256,
        receipt.issuance_replay_domain_id,
        receipt.evaluated_at.isoformat(),
        *(
            claim.value
            for claim in sorted(receipt.verified_claims, key=lambda x: x.value)
        ),
    )
    return "sha256:" + _sha256("\x00".join(values).encode())


@dataclass(frozen=True, slots=True)
class SpaceCredentialReceipt:
    receipt_id: str
    credential_sha256: str
    credential_ath: str
    authority_did: str
    space: SpaceIdentity
    applicant_context_did: str
    algorithm: str
    key_id: str
    issued_at: int
    expires_at: int
    jti: str
    cnf_jkt: str
    access_semantics: CredentialAccessSemantics
    audience_semantics: CredentialAudienceSemantics
    issuance_host_origin: str
    authority_key_receipt_id: str
    authority_host_receipt_id: str
    did_resolution_receipt_id: str
    did_resolution_method: str
    delegation_receipt_id: str
    delegation_token_sha256: str
    issuance_replay_domain_id: str
    evaluated_at: datetime
    verified_claims: frozenset[VerifiedSpaceCredentialClaim]
    explicit_non_claims: frozenset[str] = field(default=_NON_CLAIMS)
    qualification_method: str = field(default=SA9DC_CREDENTIAL_METHOD, init=False)
    qualifier_version: str = field(default=SA9DC_CREDENTIAL_VERSION, init=False)
    doctrine: str = field(default=SA9DC_CREDENTIAL_DOCTRINE, init=False)
    protocol_whole_space_read_sync: bool = True
    protocol_write: bool = False
    live_host_acceptance: bool = False
    space_membership: bool = False
    community_standing: bool = False
    governance_authority: bool = False
    effect_authorized: bool = False

    def __post_init__(self) -> None:
        validate_did(self.authority_did)
        validate_did(self.applicant_context_did)
        if not isinstance(self.space, SpaceIdentity) or (
            self.space.authority_did != self.authority_did
        ):
            _fail("spaces_credential_receipt_invalid", "Space authority is invalid")
        if (
            not isinstance(self.algorithm, str)
            or self.algorithm
            not in {
                "ES256",
                "ES256K",
            }
            or self.key_id
            not in {
                "#atproto_space",
                "#atproto",
            }
        ):
            _fail("spaces_credential_receipt_invalid", "algorithm or kid is invalid")
        if self.expires_at - self.issued_at != SA9DC_CREDENTIAL_LIFETIME_SECONDS:
            _fail("spaces_credential_receipt_invalid", "lifetime is not pinned")
        if (
            not _JTI.fullmatch(self.jti)
            or not _B64URL.fullmatch(self.cnf_jkt)
            or len(_unb64url(self.cnf_jkt)) != 32
        ):
            _fail("spaces_credential_receipt_invalid", "jti or cnf.jkt is invalid")
        if len(self.credential_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.credential_sha256
        ):
            _fail("spaces_credential_receipt_invalid", "credential digest is invalid")
        if self.credential_ath != _b64url(bytes.fromhex(self.credential_sha256)):
            _fail("spaces_credential_receipt_invalid", "credential ath is invalid")
        if self.access_semantics is not CredentialAccessSemantics.WHOLE_SPACE_READ_SYNC:
            _fail("spaces_credential_receipt_invalid", "access semantics are invalid")
        if (
            self.audience_semantics
            is not CredentialAudienceSemantics.NO_JWT_AUDIENCE_ANY_SPACE_REPO_HOST
        ):
            _fail("spaces_credential_receipt_invalid", "audience semantics are invalid")
        normalized_host = normalize_service_origin(
            self.issuance_host_origin,
            allow_insecure_loopback_fixture=self.issuance_host_origin.startswith(
                "http://"
            ),
        )
        if normalized_host.origin != self.issuance_host_origin:
            _fail("spaces_credential_receipt_invalid", "issuance host is invalid")
        for value in (
            self.authority_key_receipt_id,
            self.authority_host_receipt_id,
            self.did_resolution_receipt_id,
            self.delegation_receipt_id,
        ):
            if (
                not isinstance(value, str)
                or not value.startswith("sha256:")
                or len(value) != 71
            ):
                _fail(
                    "spaces_credential_receipt_invalid", "receipt reference is invalid"
                )
        if len(self.delegation_token_sha256) != 64:
            _fail("spaces_credential_receipt_invalid", "delegation digest is invalid")
        if not self.did_resolution_method or not self.issuance_replay_domain_id:
            _fail("spaces_credential_receipt_invalid", "provenance is incomplete")
        object.__setattr__(
            self, "evaluated_at", _utc(self.evaluated_at, field_name="evaluated_at")
        )
        if self.verified_claims != frozenset(VerifiedSpaceCredentialClaim):
            _fail("spaces_credential_receipt_invalid", "claim set is not exact")
        if (
            self.explicit_non_claims != _NON_CLAIMS
            or not self.protocol_whole_space_read_sync
            or any(
                (
                    self.protocol_write,
                    self.live_host_acceptance,
                    self.space_membership,
                    self.community_standing,
                    self.governance_authority,
                    self.effect_authorized,
                )
            )
        ):
            _fail(
                "spaces_credential_receipt_invalid",
                "credential access semantics cannot mint stronger claims",
            )
        if self.receipt_id != _receipt_id(self):
            _fail("spaces_credential_receipt_invalid", "receipt is not bound")

    def to_provenance(self) -> dict[str, object]:
        return {
            "receiptId": self.receipt_id,
            "credentialSha256": self.credential_sha256,
            "credentialAth": self.credential_ath,
            "authorityDid": self.authority_did,
            "space": self.space.uri,
            "applicantContextDid": self.applicant_context_did,
            "algorithm": self.algorithm,
            "keyId": self.key_id,
            "issuedAt": self.issued_at,
            "expiresAt": self.expires_at,
            "jti": self.jti,
            "cnfJkt": self.cnf_jkt,
            "accessSemantics": self.access_semantics.value,
            "audienceSemantics": self.audience_semantics.value,
            "issuanceHostOrigin": self.issuance_host_origin,
            "authorityKeyReceiptId": self.authority_key_receipt_id,
            "authorityHostReceiptId": self.authority_host_receipt_id,
            "didResolutionReceiptId": self.did_resolution_receipt_id,
            "didResolutionMethod": self.did_resolution_method,
            "delegationReceiptId": self.delegation_receipt_id,
            "delegationTokenSha256": self.delegation_token_sha256,
            "issuanceReplayDomainId": self.issuance_replay_domain_id,
            "evaluatedAt": self.evaluated_at.isoformat(),
            "verifiedClaims": sorted(claim.value for claim in self.verified_claims),
            "explicitNonClaims": sorted(self.explicit_non_claims),
            "protocolWholeSpaceReadSync": True,
            "protocolWrite": False,
            "liveHostAcceptance": False,
            "spaceMembership": False,
            "communityStanding": False,
            "governanceAuthority": False,
            "effectAuthorized": False,
        }


@dataclass(frozen=True, slots=True, repr=False)
class QualifiedSpaceCredential:
    credential: SecretSpaceCredential
    dpop_key: DpopSessionKey
    receipt: SpaceCredentialReceipt

    def __post_init__(self) -> None:
        if (
            self.credential.digest != self.receipt.credential_sha256
            or self.credential.ath != self.receipt.credential_ath
            or self.dpop_key.thumbprint != self.receipt.cnf_jkt
        ):
            _fail(
                "spaces_credential_runtime_mismatch",
                "runtime credential or DPoP key differs from receipt",
            )

    def __repr__(self) -> str:
        return f"QualifiedSpaceCredential(receipt_id={self.receipt.receipt_id!r}, <redacted>)"

    def __reduce__(self) -> object:
        raise TypeError("qualified Space credentials are runtime-only")


def _require_authority_context(
    *,
    resolved_authority: ResolvedDidDocument,
    authority_key: DidBindingReceipt,
    authority_host: DidBindingReceipt,
    expected_space: SpaceIdentity,
) -> None:
    require_resolved_document_binding(
        resolved_authority, resolved_authority.document_bytes
    )
    if resolved_authority.expected_did != expected_space.authority_did:
        _fail("spaces_credential_authority_mismatch", "resolved authority is wrong")
    for binding in (authority_key, authority_host):
        if (
            binding.expected_did != resolved_authority.expected_did
            or binding.document_sha256 != resolved_authority.document_sha256
            or binding.document_provenance_ref != resolved_authority.method_receipt_id
        ):
            _fail(
                "spaces_credential_authority_provenance_mismatch",
                "authority binding is not from the supplied resolution",
            )
    if (
        authority_key.profile
        is not DidInterpretationProfile.SPACE_AUTHORITY_SIGNING_KEY
    ):
        _fail(
            "spaces_credential_authority_key_required",
            "Space-authority signing-key receipt is required",
        )
    if authority_host.profile is not DidInterpretationProfile.SPACE_AUTHORITY_HOST:
        _fail(
            "spaces_credential_authority_host_required",
            "Space-authority host receipt is required",
        )


def qualify_space_credential(
    *,
    credential: SecretSpaceCredential,
    expected_space: SpaceIdentity,
    expected_applicant_did: str,
    delegation: DelegationTokenReceipt,
    resolved_authority: ResolvedDidDocument,
    authority_key: DidBindingReceipt,
    authority_host: DidBindingReceipt,
    credential_dpop_key: DpopSessionKey,
    evaluated_at: datetime,
    replay_window: BoundedCredentialIssuanceReplayWindow,
    policy: SpaceCredentialEvaluationPolicy = SpaceCredentialEvaluationPolicy(),
) -> QualifiedSpaceCredential:
    """Verify one alpha Space credential against bounded supplied evidence."""

    if not isinstance(credential, SecretSpaceCredential):
        _fail("spaces_credential_invalid", "runtime Space credential is required")
    if not isinstance(expected_space, SpaceIdentity):
        _fail("spaces_credential_space_mismatch", "expected Space is required")
    validate_did(expected_applicant_did)
    if not isinstance(delegation, DelegationTokenReceipt):
        _fail("spaces_credential_delegation_required", "delegation receipt is required")
    if not isinstance(credential_dpop_key, DpopSessionKey):
        _fail("spaces_credential_dpop_key_required", "credential DPoP key is required")
    if not isinstance(replay_window, BoundedCredentialIssuanceReplayWindow):
        _fail("spaces_credential_replay_invalid", "issuance replay window is required")
    if not isinstance(policy, SpaceCredentialEvaluationPolicy):
        _fail("spaces_credential_policy_invalid", "credential policy is invalid")
    _require_authority_context(
        resolved_authority=resolved_authority,
        authority_key=authority_key,
        authority_host=authority_host,
        expected_space=expected_space,
    )
    if delegation.space != expected_space:
        _fail(
            "spaces_credential_delegation_mismatch",
            "delegation receipt is for another Space",
        )
    if delegation.issuer_did != expected_applicant_did:
        _fail(
            "spaces_credential_applicant_mismatch",
            "delegation applicant differs from expected user",
        )
    raw = credential._for_authenticated_request()
    header, payload, signature, signing_input = _decode_compact_jwt(raw)
    if set(header) != {"typ", "alg", "kid"}:
        _fail("spaces_credential_header_mismatch", "credential header shape is invalid")
    if header.get("typ") != SA9DC_CREDENTIAL_TYP:
        _fail("spaces_credential_header_mismatch", "credential token type is invalid")
    algorithm = header.get("alg")
    if not isinstance(algorithm, str) or algorithm not in {"ES256", "ES256K"}:
        _fail("spaces_credential_algorithm_unsupported", "algorithm is unsupported")
    selection_to_kid = {
        DidBindingSelection.DEDICATED_SPACE_KEY: "#atproto_space",
        DidBindingSelection.FALLBACK_ACCOUNT_KEY: "#atproto",
    }
    expected_kid = selection_to_kid.get(authority_key.selection)
    if expected_kid is None or header.get("kid") != expected_kid:
        _fail(
            "spaces_credential_signing_key_mismatch",
            "credential kid differs from selected authority key",
        )
    if set(payload) != {"iss", "sub", "cnf", "iat", "exp", "jti"}:
        _fail(
            "spaces_credential_payload_mismatch",
            "credential payload must contain only pinned claims and no aud",
        )
    issuer = payload.get("iss")
    if issuer != expected_space.authority_did:
        _fail("spaces_credential_authority_mismatch", "issuer is another authority")
    assert isinstance(issuer, str)
    validate_did(issuer)
    if payload.get("sub") != expected_space.uri:
        _fail("spaces_credential_space_mismatch", "credential is for another Space")
    confirmation = payload.get("cnf")
    if (
        not isinstance(confirmation, dict)
        or set(confirmation) != {"jkt"}
        or confirmation.get("jkt") != credential_dpop_key.thumbprint
    ):
        _fail(
            "spaces_credential_dpop_key_mismatch",
            "credential cnf.jkt differs from supplied DPoP key",
        )
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
        _fail("spaces_credential_time_invalid", "credential lifetime is invalid")
    if not delegation.issued_at <= issued_at < delegation.expires_at:
        _fail(
            "spaces_credential_delegation_time_mismatch",
            "credential issuance is outside delegation validity",
        )
    evaluated = _utc(evaluated_at, field_name="evaluated_at")
    evaluation_second = int(evaluated.timestamp())
    if evaluation_second < issued_at or evaluation_second >= expires_at:
        _fail("spaces_credential_expired", "credential is outside validity window")
    if not isinstance(jti, str) or not _JTI.fullmatch(jti):
        _fail("spaces_credential_jti_invalid", "credential jti is outside bounds")
    curve = authority_key.selected_key_curve
    if (algorithm, curve) not in {("ES256", "p256"), ("ES256K", "k256")}:
        _fail(
            "spaces_credential_signing_key_mismatch",
            "JWT algorithm differs from selected authority key",
        )
    public_key = verification_key_bytes(authority_key)
    verifier = verify_es256 if algorithm == "ES256" else verify_es256k
    if not verifier(public_key, signing_input, signature):
        _fail("spaces_credential_signature_invalid", "credential signature is invalid")
    replay_window.record(issuer, jti)
    assert authority_host.selected_origin is not None
    fields = dict(
        receipt_id="",
        credential_sha256=credential.digest,
        credential_ath=credential.ath,
        authority_did=issuer,
        space=expected_space,
        applicant_context_did=expected_applicant_did,
        algorithm=algorithm,
        key_id=expected_kid,
        issued_at=issued_at,
        expires_at=expires_at,
        jti=jti,
        cnf_jkt=credential_dpop_key.thumbprint,
        access_semantics=CredentialAccessSemantics.WHOLE_SPACE_READ_SYNC,
        audience_semantics=(
            CredentialAudienceSemantics.NO_JWT_AUDIENCE_ANY_SPACE_REPO_HOST
        ),
        issuance_host_origin=authority_host.selected_origin,
        authority_key_receipt_id=authority_key.receipt_id,
        authority_host_receipt_id=authority_host.receipt_id,
        did_resolution_receipt_id=resolved_authority.method_receipt_id,
        did_resolution_method=resolved_authority.method.value,
        delegation_receipt_id=delegation.receipt_id,
        delegation_token_sha256=delegation.token_sha256,
        issuance_replay_domain_id=replay_window.domain_id,
        evaluated_at=evaluated,
        verified_claims=frozenset(VerifiedSpaceCredentialClaim),
    )
    probe = SpaceCredentialReceipt.__new__(SpaceCredentialReceipt)
    for name, value in fields.items():
        object.__setattr__(probe, name, value)
    receipt_id = _receipt_id(probe)
    receipt = SpaceCredentialReceipt(
        receipt_id=receipt_id,
        **{key: value for key, value in fields.items() if key != "receipt_id"},
    )
    return QualifiedSpaceCredential(
        credential=credential,
        dpop_key=credential_dpop_key,
        receipt=receipt,
    )


__all__ = [
    "BoundedCredentialIssuanceReplayWindow",
    "CredentialAccessSemantics",
    "CredentialAudienceSemantics",
    "QualifiedSpaceCredential",
    "SecretSpaceCredential",
    "SpaceCredentialEvaluationPolicy",
    "SpaceCredentialReceipt",
    "VerifiedSpaceCredentialClaim",
    "qualify_space_credential",
]
