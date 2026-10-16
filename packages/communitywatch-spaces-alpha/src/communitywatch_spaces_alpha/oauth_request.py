"""SA9d-a fixture-only OAuth/DPoP request-binding qualification.

Authentication binds a credential to a request. It does not bind that request
to governance authority. This module performs no network I/O and deliberately
keeps secret-bearing runtime values out of all receipt serialization.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType

from community_model import ValidationError
from community_model.identifiers import validate_did, validate_nsid, validate_rkey

from .compat import (
    DELEGATION_TOKEN_ENDPOINT,
    SA9D_AUTH_DOCTRINE,
    SA9D_DPOP_METHOD,
    SA9D_DPOP_VERSION,
    SA9D_OAUTH_PROFILE,
)
from .crypto import verify_es256
from .did_binding import DidBindingReceipt, DidInterpretationProfile
from .did_resolution import ResolvedDidDocument
from .model import SpaceIdentity

_P256_FIELD = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_P256_A = _P256_FIELD - 3
_P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_P256_GENERATOR = (
    0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
    0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5,
)
_Point = tuple[int, int] | None
_SCOPE_TOKEN = re.compile(r"^[\x21\x23-\x5b\x5d-\x7e]+$")
_JTI = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
_NON_CLAIMS = frozenset(
    {
        "oauth_ceremony_authentic",
        "live_token_valid",
        "live_server_acceptance",
        "space_credential",
        "space_membership",
        "community_standing",
        "user_intent",
        "governed_authorization",
        "artifact_validity",
        "repository_currentness",
    }
)
_GRANT_CLAIMS = frozenset(
    {
        "token_subject_matches_expected_did",
        "returned_granted_scope_preserved",
        "atproto_profile_scope_present",
        "opaque_token_digest_bound",
        "session_dpop_key_thumbprint_bound",
    }
)


def _fail(reason: str, message: str) -> None:
    raise ValidationError(reason, message)


def _utc(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        _fail("spaces_oauth_invalid", f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _text(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or any(ord(character) < 0x20 for character in value)
    ):
        _fail("spaces_oauth_invalid", f"{field_name} must be nonempty text")
    return value


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _b64url(value: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64url(value: str) -> bytes:
    import base64

    if not isinstance(value, str) or not value or "=" in value:
        _fail("spaces_dpop_invalid", "JWT segment is not unpadded base64url")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise ValidationError("spaces_dpop_invalid", "invalid base64url") from exc


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _receipt_id(kind: str, values: tuple[str, ...]) -> str:
    encoded = "\x00".join((kind, *values)).encode()
    return "sha256:" + _sha256(encoded)


class _DuplicateJsonKey(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


class SecretAccessToken:
    """Runtime-only opaque token whose repr and exceptions never expose bytes."""

    __slots__ = ("__value",)

    def __init__(self, value: str) -> None:
        _text(value, field_name="access token")
        self.__value = value

    @property
    def digest(self) -> str:
        return _sha256(self.__value.encode())

    @property
    def ath(self) -> str:
        return _b64url(hashlib.sha256(self.__value.encode()).digest())

    def authorization_header(self) -> str:
        return f"DPoP {self.__value}"

    def __repr__(self) -> str:
        return "SecretAccessToken(<redacted>)"

    def __reduce__(self) -> object:
        raise TypeError("secret access tokens are runtime-only and not serializable")


def _point_add(left: _Point, right: _Point) -> _Point:
    if left is None:
        return right
    if right is None:
        return left
    x1, y1 = left
    x2, y2 = right
    if x1 == x2 and (y1 != y2 or y1 == 0):
        return None
    if left == right:
        slope = (3 * x1 * x1 + _P256_A) * pow(2 * y1, -1, _P256_FIELD)
    else:
        slope = (y2 - y1) * pow(x2 - x1, -1, _P256_FIELD)
    slope %= _P256_FIELD
    x3 = (slope * slope - x1 - x2) % _P256_FIELD
    return x3, (slope * (x1 - x3) - y1) % _P256_FIELD


def _point_multiply(scalar: int, point: _Point) -> _Point:
    result: _Point = None
    addend = point
    while scalar:
        if scalar & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        scalar >>= 1
    return result


def _rfc6979(private_scalar: int, digest: bytes) -> int:
    x = private_scalar.to_bytes(32, "big")
    h1 = (int.from_bytes(digest, "big") % _P256_ORDER).to_bytes(32, "big")
    value = b"\x01" * 32
    key = b"\x00" * 32
    key = hmac.new(key, value + b"\x00" + x + h1, hashlib.sha256).digest()
    value = hmac.new(key, value, hashlib.sha256).digest()
    key = hmac.new(key, value + b"\x01" + x + h1, hashlib.sha256).digest()
    value = hmac.new(key, value, hashlib.sha256).digest()
    while True:
        value = hmac.new(key, value, hashlib.sha256).digest()
        candidate = int.from_bytes(value, "big")
        if 1 <= candidate < _P256_ORDER:
            return candidate
        key = hmac.new(key, value + b"\x00", hashlib.sha256).digest()
        value = hmac.new(key, value, hashlib.sha256).digest()


class DpopSessionKey:
    """One synthetic session ES256 key; private material is never serializable."""

    __slots__ = ("__private_scalar", "session_ref")

    def __init__(self, private_scalar: int, *, session_ref: str) -> None:
        if (
            isinstance(private_scalar, bool)
            or not isinstance(private_scalar, int)
            or not 1 <= private_scalar < _P256_ORDER
        ):
            _fail("spaces_dpop_key_invalid", "P-256 private scalar is invalid")
        self.__private_scalar = private_scalar
        self.session_ref = _text(session_ref, field_name="DPoP session reference")

    @classmethod
    def from_test_seed(cls, seed: bytes, *, session_ref: str) -> DpopSessionKey:
        if not isinstance(seed, bytes) or not seed:
            _fail("spaces_dpop_key_invalid", "synthetic test seed is required")
        scalar = int.from_bytes(hashlib.sha256(seed).digest(), "big")
        scalar = scalar % (_P256_ORDER - 1) + 1
        return cls(scalar, session_ref=session_ref)

    @property
    def public_point(self) -> tuple[int, int]:
        point = _point_multiply(self.__private_scalar, _P256_GENERATOR)
        assert point is not None
        return point

    @property
    def public_jwk(self) -> MappingProxyType[str, str]:
        x, y = self.public_point
        return MappingProxyType(
            {
                "kty": "EC",
                "crv": "P-256",
                "x": _b64url(x.to_bytes(32, "big")),
                "y": _b64url(y.to_bytes(32, "big")),
            }
        )

    @property
    def thumbprint(self) -> str:
        return _b64url(hashlib.sha256(_canonical_json(dict(self.public_jwk))).digest())

    @property
    def compressed_public_key(self) -> bytes:
        x, y = self.public_point
        return bytes((2 | (y & 1),)) + x.to_bytes(32, "big")

    def _sign_dpop_proof(self, message: bytes) -> bytes:
        digest = hashlib.sha256(message).digest()
        nonce = _rfc6979(self.__private_scalar, digest)
        point = _point_multiply(nonce, _P256_GENERATOR)
        assert point is not None
        r = point[0] % _P256_ORDER
        s = (
            pow(nonce, -1, _P256_ORDER)
            * (int.from_bytes(digest, "big") + r * self.__private_scalar)
            % _P256_ORDER
        )
        if s > _P256_ORDER // 2:
            s = _P256_ORDER - s
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")

    def __repr__(self) -> str:
        return (
            "DpopSessionKey(session_ref="
            f"{self.session_ref!r}, thumbprint={self.thumbprint!r}, <redacted>)"
        )

    def __reduce__(self) -> object:
        raise TypeError("DPoP private keys are runtime-only and not serializable")


@dataclass(frozen=True, slots=True)
class OAuthGrantReceipt:
    receipt_id: str
    expected_account_did: str
    token_subject: str
    authorization_server_issuer: str
    client_id: str
    requested_scope: str | None
    granted_scope: str
    parsed_granted_scopes: tuple[str, ...]
    access_token_sha256: str
    dpop_jwk_thumbprint: str
    observed_at: datetime
    provenance_ref: str
    verified_claims: frozenset[str]
    explicit_non_claims: frozenset[str] = field(default=_NON_CLAIMS)
    profile: str = field(default=SA9D_OAUTH_PROFILE, init=False)
    doctrine: str = field(default=SA9D_AUTH_DOCTRINE, init=False)
    standing: bool = False
    governance_authority: bool = False
    effect_authorized: bool = False

    def __post_init__(self) -> None:
        validate_did(self.expected_account_did)
        validate_did(self.token_subject)
        if self.expected_account_did != self.token_subject:
            _fail("spaces_oauth_subject_mismatch", "token subject is not expected DID")
        _text(self.authorization_server_issuer, field_name="issuer")
        _text(self.client_id, field_name="client id")
        _text(self.granted_scope, field_name="granted scope")
        _text(self.provenance_ref, field_name="grant provenance")
        if self.requested_scope is not None:
            _text(self.requested_scope, field_name="requested scope")
        if tuple(_parse_scope_tokens(self.granted_scope)) != self.parsed_granted_scopes:
            _fail("spaces_oauth_receipt_invalid", "parsed scope is not exact")
        if "atproto" not in self.parsed_granted_scopes:
            _fail("spaces_oauth_atproto_missing", "granted scope lacks atproto")
        if self.verified_claims != _GRANT_CLAIMS:
            _fail("spaces_oauth_receipt_invalid", "grant claim set is not exact")
        if len(self.access_token_sha256) != 64:
            _fail("spaces_oauth_receipt_invalid", "token digest is invalid")
        if not self.dpop_jwk_thumbprint:
            _fail("spaces_oauth_receipt_invalid", "DPoP thumbprint is required")
        object.__setattr__(
            self, "observed_at", _utc(self.observed_at, field_name="observed_at")
        )
        if self.explicit_non_claims != _NON_CLAIMS or any(
            (self.standing, self.governance_authority, self.effect_authorized)
        ):
            _fail("spaces_oauth_receipt_invalid", "OAuth cannot mint governance claims")
        expected = _grant_receipt_id(self)
        if self.receipt_id != expected:
            _fail("spaces_oauth_receipt_invalid", "grant receipt is not bound")

    def to_provenance(self) -> dict[str, object]:
        return {
            "receiptId": self.receipt_id,
            "expectedAccountDid": self.expected_account_did,
            "tokenSubject": self.token_subject,
            "authorizationServerIssuer": self.authorization_server_issuer,
            "clientId": self.client_id,
            "requestedScope": self.requested_scope,
            "grantedScope": self.granted_scope,
            "parsedGrantedScopes": list(self.parsed_granted_scopes),
            "accessTokenSha256": self.access_token_sha256,
            "dpopJwkThumbprint": self.dpop_jwk_thumbprint,
            "observedAt": self.observed_at.isoformat(),
            "provenanceRef": self.provenance_ref,
            "verifiedClaims": sorted(self.verified_claims),
            "explicitNonClaims": sorted(self.explicit_non_claims),
            "standing": False,
            "governanceAuthority": False,
            "effectAuthorized": False,
        }


def _grant_receipt_id(receipt: OAuthGrantReceipt) -> str:
    return _receipt_id(
        "sa9d-a-oauth-grant",
        (
            receipt.expected_account_did,
            receipt.token_subject,
            receipt.authorization_server_issuer,
            receipt.client_id,
            receipt.requested_scope or "",
            receipt.granted_scope,
            *receipt.parsed_granted_scopes,
            receipt.access_token_sha256,
            receipt.dpop_jwk_thumbprint,
            receipt.observed_at.isoformat(),
            receipt.provenance_ref,
            *sorted(receipt.verified_claims),
        ),
    )


@dataclass(frozen=True, slots=True, repr=False)
class OAuthGrantContext:
    receipt: OAuthGrantReceipt
    access_token: SecretAccessToken

    def __post_init__(self) -> None:
        if self.receipt.access_token_sha256 != self.access_token.digest:
            _fail("spaces_oauth_token_mismatch", "runtime token does not match receipt")

    def __repr__(self) -> str:
        return f"OAuthGrantContext(receipt_id={self.receipt.receipt_id!r}, <redacted>)"


def _parse_scope_tokens(scope: str) -> tuple[str, ...]:
    if not isinstance(scope, str) or not scope:
        _fail("spaces_oauth_scope_invalid", "granted scope is required")
    tokens = tuple(scope.split(" "))
    if any(not token or not _SCOPE_TOKEN.fullmatch(token) for token in tokens):
        _fail("spaces_oauth_scope_invalid", "scope string has ambiguous syntax")
    return tokens


def qualify_oauth_grant(
    *,
    expected_account_did: str,
    token_subject: str,
    authorization_server_issuer: str,
    client_id: str,
    requested_scope: str | None,
    granted_scope: str,
    access_token: SecretAccessToken,
    dpop_key: DpopSessionKey,
    observed_at: datetime,
    provenance_ref: str,
) -> OAuthGrantContext:
    """Qualify the exact returned grant, never the requested scope."""

    parsed = _parse_scope_tokens(granted_scope)
    if "atproto" not in parsed:
        _fail("spaces_oauth_atproto_missing", "granted scope lacks atproto")
    if token_subject != expected_account_did:
        _fail("spaces_oauth_subject_mismatch", "token subject is not expected DID")
    fields = dict(
        receipt_id="",
        expected_account_did=expected_account_did,
        token_subject=token_subject,
        authorization_server_issuer=authorization_server_issuer,
        client_id=client_id,
        requested_scope=requested_scope,
        granted_scope=granted_scope,
        parsed_granted_scopes=parsed,
        access_token_sha256=access_token.digest,
        dpop_jwk_thumbprint=dpop_key.thumbprint,
        observed_at=observed_at,
        provenance_ref=provenance_ref,
        verified_claims=_GRANT_CLAIMS,
    )
    probe = OAuthGrantReceipt.__new__(OAuthGrantReceipt)
    for name, value in fields.items():
        object.__setattr__(probe, name, value)
    object.__setattr__(
        probe, "observed_at", _utc(observed_at, field_name="observed_at")
    )
    receipt_id = _grant_receipt_id(probe)
    receipt = OAuthGrantReceipt(
        receipt_id=receipt_id, **{k: v for k, v in fields.items() if k != "receipt_id"}
    )
    return OAuthGrantContext(receipt=receipt, access_token=access_token)


class SpaceAction(StrEnum):
    READ_SELF = "read_self"
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class SpaceManageAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class ParsedSpaceScope:
    raw_scope: str
    space_type: str
    authority: str
    skey: str
    collections: tuple[str, ...] | None
    actions: tuple[SpaceAction, ...]
    manage: tuple[SpaceManageAction, ...]
    collection_default_dynamic: bool


def parse_space_scope(raw_scope: str) -> ParsedSpaceScope:
    _text(raw_scope, field_name="Space scope")
    if not raw_scope.startswith("space:"):
        _fail("spaces_oauth_scope_invalid", "scope is not a Space grant")
    body = raw_scope[len("space:") :]
    space_type, separator, query = body.partition("?")
    if space_type != "*":
        validate_nsid(space_type)
    pairs = urllib.parse.parse_qsl(
        query if separator else "", keep_blank_values=True, strict_parsing=True
    )
    allowed = {"authority", "skey", "collection", "action", "manage"}
    if any(key not in allowed or not value for key, value in pairs):
        _fail("spaces_oauth_scope_invalid", "Space scope parameters are invalid")
    single: dict[str, str] = {}
    multiple: dict[str, list[str]] = {"collection": [], "action": [], "manage": []}
    for key, value in pairs:
        if key in {"authority", "skey"}:
            if key in single:
                _fail("spaces_oauth_scope_invalid", f"duplicate {key} parameter")
            single[key] = value
        else:
            multiple[key].append(value)
    authority = single.get("authority", "self")
    if authority not in {"self", "*"}:
        validate_did(authority)
    skey = single.get("skey", "*")
    if skey != "*":
        validate_rkey(skey)
    collections: tuple[str, ...] | None
    if multiple["collection"]:
        for collection in multiple["collection"]:
            if collection != "*":
                validate_nsid(collection)
        collections = tuple(multiple["collection"])
    else:
        collections = None
    raw_actions = multiple["action"] or ["read", "create", "update", "delete"]
    try:
        actions = tuple(SpaceAction(value) for value in raw_actions)
        manage = tuple(SpaceManageAction(value) for value in multiple["manage"])
    except ValueError as exc:
        raise ValidationError(
            "spaces_oauth_scope_invalid", "unsupported Space action"
        ) from exc
    if len(actions) != len(set(actions)) or len(manage) != len(set(manage)):
        _fail("spaces_oauth_scope_invalid", "duplicate Space actions are ambiguous")
    if collections is not None and len(collections) != len(set(collections)):
        _fail("spaces_oauth_scope_invalid", "duplicate collections are ambiguous")
    return ParsedSpaceScope(
        raw_scope=raw_scope,
        space_type=space_type,
        authority=authority,
        skey=skey,
        collections=collections,
        actions=actions,
        manage=manage,
        collection_default_dynamic=collections is None,
    )


@dataclass(frozen=True, slots=True)
class SpaceProtocolRequest:
    space: SpaceIdentity
    repo_did: str
    action: SpaceAction
    collection: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.space, SpaceIdentity):
            _fail("spaces_oauth_request_invalid", "Space identity is required")
        validate_did(self.repo_did)
        if not isinstance(self.action, SpaceAction):
            _fail("spaces_oauth_request_invalid", "Space action is invalid")
        if self.collection is not None:
            validate_nsid(self.collection)
        if (
            self.action in {SpaceAction.CREATE, SpaceAction.UPDATE, SpaceAction.DELETE}
            and self.collection is None
        ):
            _fail("spaces_oauth_request_invalid", "write action requires collection")


@dataclass(frozen=True, slots=True)
class SpaceScopeEvaluation:
    evaluation_id: str
    oauth_grant_receipt_id: str
    permitted: bool
    matching_scope: str | None
    request: SpaceProtocolRequest
    effective_collections: frozenset[str]
    dynamic_collection_default: bool
    declaration_evidence_ref: str | None
    protocol_authorization_only: bool = True
    governance_authority: bool = False

    def __post_init__(self) -> None:
        if not self.protocol_authorization_only or self.governance_authority:
            _fail(
                "spaces_oauth_scope_invalid", "protocol grant cannot confer governance"
            )
        if self.evaluation_id != _space_evaluation_identifier(self):
            _fail("spaces_oauth_scope_invalid", "Space-scope evaluation is not bound")


def _space_evaluation_identifier(evaluation: SpaceScopeEvaluation) -> str:
    request = evaluation.request
    return _receipt_id(
        "sa9d-a-space-scope-evaluation",
        (
            evaluation.oauth_grant_receipt_id,
            str(evaluation.permitted),
            evaluation.matching_scope or "",
            request.space.uri,
            request.repo_did,
            request.action.value,
            request.collection or "",
            *sorted(evaluation.effective_collections),
            str(evaluation.dynamic_collection_default),
            evaluation.declaration_evidence_ref or "",
        ),
    )


def _make_space_evaluation(
    *,
    grant_receipt_id: str,
    permitted: bool,
    matching_scope: str | None,
    request: SpaceProtocolRequest,
    effective_collections: frozenset[str],
    dynamic_collection_default: bool,
    declaration_evidence_ref: str | None,
) -> SpaceScopeEvaluation:
    fields = {
        "oauth_grant_receipt_id": grant_receipt_id,
        "permitted": permitted,
        "matching_scope": matching_scope,
        "request": request,
        "effective_collections": effective_collections,
        "dynamic_collection_default": dynamic_collection_default,
        "declaration_evidence_ref": declaration_evidence_ref,
    }
    probe = SpaceScopeEvaluation.__new__(SpaceScopeEvaluation)
    for name, value in fields.items():
        object.__setattr__(probe, name, value)
    evaluation_id = _space_evaluation_identifier(probe)
    return SpaceScopeEvaluation(evaluation_id=evaluation_id, **fields)  # type: ignore[arg-type]


def evaluate_space_protocol_grant(
    grant: OAuthGrantReceipt,
    request: SpaceProtocolRequest,
    *,
    declaration_collections: frozenset[str],
    declaration_evidence_ref: str,
) -> SpaceScopeEvaluation:
    """Evaluate the pinned alpha permission; this is not governance authorization."""

    for collection in declaration_collections:
        validate_nsid(collection)
    for token in grant.parsed_granted_scopes:
        if not token.startswith("space:"):
            continue
        scope = parse_space_scope(token)
        if scope.space_type not in {"*", request.space.space_type}:
            continue
        authority = (
            grant.token_subject if scope.authority == "self" else scope.authority
        )
        if authority not in {"*", request.space.authority_did}:
            continue
        if scope.skey not in {"*", request.space.skey}:
            continue
        if scope.collections is None:
            effective = (
                frozenset() if scope.space_type == "*" else declaration_collections
            )
        elif "*" in scope.collections:
            effective = frozenset({"*"})
        else:
            effective = frozenset(scope.collections)
        action_allowed = request.action in scope.actions
        if (
            request.action is SpaceAction.READ_SELF
            and SpaceAction.READ in scope.actions
        ):
            action_allowed = True
        if not action_allowed:
            continue
        if request.action is SpaceAction.READ:
            collection_allowed = True
        elif request.action is SpaceAction.READ_SELF:
            collection_allowed = SpaceAction.READ in scope.actions or (
                request.repo_did == grant.token_subject
                and request.collection is not None
                and ("*" in effective or request.collection in effective)
            )
        else:
            collection_allowed = request.collection is not None and (
                "*" in effective or request.collection in effective
            )
        if collection_allowed:
            return _make_space_evaluation(
                grant_receipt_id=grant.receipt_id,
                permitted=True,
                matching_scope=scope.raw_scope,
                request=request,
                effective_collections=effective,
                dynamic_collection_default=scope.collection_default_dynamic,
                declaration_evidence_ref=declaration_evidence_ref,
            )
    return _make_space_evaluation(
        grant_receipt_id=grant.receipt_id,
        permitted=False,
        matching_scope=None,
        request=request,
        effective_collections=frozenset(),
        dynamic_collection_default=False,
        declaration_evidence_ref=None,
    )


def _space_evaluation_digest(evaluation: SpaceScopeEvaluation) -> str:
    return evaluation.evaluation_id.removeprefix("sha256:")


def _require_space_read_target(url: str, evaluation: SpaceScopeEvaluation) -> None:
    if not evaluation.permitted:
        _fail(
            "spaces_oauth_scope_refused", "granted Space scope does not cover request"
        )
    if evaluation.request.action not in {SpaceAction.READ, SpaceAction.READ_SELF}:
        _fail("spaces_oauth_scope_refused", "SA9d-a constructs read requests only")
    parsed = urllib.parse.urlsplit(url)
    delegation_path = f"/xrpc/{DELEGATION_TOKEN_ENDPOINT}"
    if parsed.path not in {
        "/xrpc/com.atproto.space.getRepo",
        "/xrpc/com.atproto.space.listRepoOps",
        delegation_path,
    }:
        _fail("spaces_oauth_target_invalid", "target is not a pinned Space read RPC")
    raw_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if len(raw_pairs) != len({key for key, _ in raw_pairs}):
        _fail("spaces_oauth_target_invalid", "request query has duplicate parameters")
    pairs = {key: [value] for key, value in raw_pairs}
    if parsed.path == delegation_path:
        if evaluation.request.action is not SpaceAction.READ:
            _fail(
                "spaces_oauth_scope_refused",
                "getDelegationToken requires a whole-Space read grant",
            )
        if set(pairs) != {"space"} or pairs.get("space") != [
            evaluation.request.space.uri
        ]:
            _fail(
                "spaces_oauth_target_invalid",
                "delegation request query does not match Space grant evaluation",
            )
        return
    allowed = {"space", "repo"}
    if parsed.path.endswith("listRepoOps"):
        allowed |= {"since", "cursor", "limit", "excludeValues"}
    if set(pairs) - allowed:
        _fail("spaces_oauth_target_invalid", "request query has unsupported parameters")
    if pairs.get("space") != [evaluation.request.space.uri] or pairs.get("repo") != [
        evaluation.request.repo_did
    ]:
        _fail(
            "spaces_oauth_target_invalid",
            "request query does not match Space grant evaluation",
        )


@dataclass(frozen=True, slots=True, repr=False)
class DpopNonceContext:
    server_origin: str
    session_ref: str
    nonce: str
    observed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "server_origin", canonical_origin(self.server_origin))
        _text(self.session_ref, field_name="nonce session reference")
        _text(self.nonce, field_name="DPoP nonce")
        object.__setattr__(
            self, "observed_at", _utc(self.observed_at, field_name="nonce observed_at")
        )

    @property
    def digest(self) -> str:
        return _sha256(self.nonce.encode())

    def __repr__(self) -> str:
        return f"DpopNonceContext(server_origin={self.server_origin!r}, session_ref={self.session_ref!r}, <redacted>)"


def _normalize_percent(component: str) -> str:
    unreserved = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    result: list[str] = []
    index = 0
    while index < len(component):
        if component[index] != "%":
            result.append(component[index])
            index += 1
            continue
        if index + 2 >= len(component):
            _fail("spaces_dpop_htu_invalid", "invalid percent encoding")
        pair = component[index + 1 : index + 3]
        try:
            character = chr(int(pair, 16))
        except ValueError as exc:
            raise ValidationError(
                "spaces_dpop_htu_invalid", "invalid percent encoding"
            ) from exc
        result.append(character if character in unreserved else "%" + pair.upper())
        index += 3
    return "".join(result)


def canonical_origin(url: str) -> str:
    if (
        not isinstance(url, str)
        or not url
        or any(ord(character) <= 0x20 for character in url)
    ):
        _fail("spaces_dpop_htu_invalid", "request URI contains invalid characters")
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValidationError(
            "spaces_dpop_htu_invalid", "request URI cannot be parsed"
        ) from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        _fail("spaces_dpop_htu_invalid", "protected resource origin must be HTTPS")
    host = parsed.hostname.lower()
    if any(ord(ch) > 127 for ch in host) or host.endswith("."):
        _fail("spaces_dpop_htu_invalid", "ambiguous resource hostname")
    rendered = f"[{host}]" if ":" in host else host
    return f"https://{rendered}" + ("" if port in {None, 443} else f":{port}")


def canonical_dpop_htu(url: str) -> str:
    """RFC 9449 target URI form: normalized, without query or fragment."""

    parsed = urllib.parse.urlsplit(url)
    if parsed.fragment:
        _fail("spaces_dpop_htu_invalid", "HTTP request URI must not contain fragment")
    origin = canonical_origin(url)
    path = _normalize_percent(parsed.path or "/")
    if any(segment in {".", ".."} for segment in path.split("/")):
        _fail("spaces_dpop_htu_invalid", "dot segments are prohibited")
    return origin + path


@dataclass(frozen=True, slots=True)
class DpopEvaluationPolicy:
    maximum_age_seconds: int = 300
    future_skew_seconds: int = 30

    def __post_init__(self) -> None:
        if (
            not 1 <= self.maximum_age_seconds <= 300
            or not 0 <= self.future_skew_seconds <= 60
        ):
            _fail("spaces_dpop_policy_invalid", "DPoP evaluation window is invalid")


@dataclass(slots=True)
class BoundedReplayWindow:
    domain_id: str
    _seen: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        _text(self.domain_id, field_name="replay domain")

    def record(self, jti: str) -> None:
        if jti in self._seen:
            _fail("spaces_dpop_replay", "DPoP jti was reused in this bounded domain")
        self._seen.add(jti)


class VerifiedDpopClaim(StrEnum):
    TYPE = "dpop_jwt_type"
    ALGORITHM = "es256_algorithm"
    PUBLIC_JWK = "public_jwk"
    SIGNATURE = "proof_signature"
    SESSION_KEY = "session_key_thumbprint"
    METHOD = "http_method"
    TARGET = "http_target_without_query_or_fragment"
    ISSUED_AT = "proof_time_window"
    JTI = "bounded_jti_replay"
    NONCE = "server_session_nonce"
    ACCESS_TOKEN = "access_token_hash"


@dataclass(frozen=True, slots=True)
class RequestBindingReceipt:
    receipt_id: str
    method: str
    request_url: str
    canonical_htu: str
    request_url_sha256: str
    access_token_sha256: str
    dpop_jwk_thumbprint: str
    proof_sha256: str
    jti: str
    iat: int
    nonce_sha256: str
    nonce_server_origin: str
    ath: str
    oauth_grant_receipt_id: str
    space_scope_evaluation_sha256: str
    matching_space_scope: str
    subject_did: str
    client_id: str
    evaluated_at: datetime
    verified_claims: frozenset[VerifiedDpopClaim]
    explicit_non_claims: frozenset[str] = field(default=_NON_CLAIMS)
    method_name: str = field(default=SA9D_DPOP_METHOD, init=False)
    verifier_version: str = field(default=SA9D_DPOP_VERSION, init=False)
    doctrine: str = field(default=SA9D_AUTH_DOCTRINE, init=False)
    standing: bool = False
    governance_authority: bool = False
    effect_authorized: bool = False

    def __post_init__(self) -> None:
        if self.method != "GET":
            _fail("spaces_dpop_receipt_invalid", "SA9d-a binds GET only")
        validate_did(self.subject_did)
        if canonical_dpop_htu(self.request_url) != self.canonical_htu:
            _fail("spaces_dpop_receipt_invalid", "receipt target is not canonical")
        if self.request_url_sha256 != _sha256(self.request_url.encode()):
            _fail("spaces_dpop_receipt_invalid", "request URL digest mismatch")
        object.__setattr__(
            self, "evaluated_at", _utc(self.evaluated_at, field_name="evaluated_at")
        )
        if self.verified_claims != frozenset(VerifiedDpopClaim):
            _fail("spaces_dpop_receipt_invalid", "verified claim set is not exact")
        if self.explicit_non_claims != _NON_CLAIMS or any(
            (self.standing, self.governance_authority, self.effect_authorized)
        ):
            _fail(
                "spaces_dpop_receipt_invalid", "request binding cannot mint governance"
            )
        if self.receipt_id != _request_receipt_id(self):
            _fail("spaces_dpop_receipt_invalid", "request receipt is not bound")

    def to_provenance(self) -> dict[str, object]:
        return {
            "receiptId": self.receipt_id,
            "method": self.method,
            "requestUrl": self.request_url,
            "canonicalHtu": self.canonical_htu,
            "requestUrlSha256": self.request_url_sha256,
            "accessTokenSha256": self.access_token_sha256,
            "dpopJwkThumbprint": self.dpop_jwk_thumbprint,
            "proofSha256": self.proof_sha256,
            "jti": self.jti,
            "iat": self.iat,
            "nonceSha256": self.nonce_sha256,
            "nonceServerOrigin": self.nonce_server_origin,
            "ath": self.ath,
            "oauthGrantReceiptId": self.oauth_grant_receipt_id,
            "spaceScopeEvaluationSha256": self.space_scope_evaluation_sha256,
            "matchingSpaceScope": self.matching_space_scope,
            "subjectDid": self.subject_did,
            "clientId": self.client_id,
            "evaluatedAt": self.evaluated_at.isoformat(),
            "verifiedClaims": sorted(claim.value for claim in self.verified_claims),
            "explicitNonClaims": sorted(self.explicit_non_claims),
            "standing": False,
            "governanceAuthority": False,
            "effectAuthorized": False,
        }


def _request_receipt_id(receipt: RequestBindingReceipt) -> str:
    return _receipt_id(
        "sa9d-a-request-binding",
        (
            receipt.method,
            receipt.request_url,
            receipt.canonical_htu,
            receipt.request_url_sha256,
            receipt.access_token_sha256,
            receipt.dpop_jwk_thumbprint,
            receipt.proof_sha256,
            receipt.jti,
            str(receipt.iat),
            receipt.nonce_sha256,
            receipt.nonce_server_origin,
            receipt.ath,
            receipt.oauth_grant_receipt_id,
            receipt.space_scope_evaluation_sha256,
            receipt.matching_space_scope,
            receipt.subject_did,
            receipt.client_id,
            receipt.evaluated_at.isoformat(),
            *(
                claim.value
                for claim in sorted(
                    receipt.verified_claims, key=lambda item: item.value
                )
            ),
        ),
    )


@dataclass(frozen=True, slots=True, repr=False)
class AuthenticatedGetRequest:
    url: str
    proof: str
    grant: OAuthGrantContext
    receipt: RequestBindingReceipt

    @property
    def method(self) -> str:
        return "GET"

    def controlled_headers(self) -> MappingProxyType[str, str]:
        return MappingProxyType(
            {
                "Authorization": self.grant.access_token.authorization_header(),
                "DPoP": self.proof,
                "Accept-Encoding": "identity",
            }
        )

    def __repr__(self) -> str:
        return f"AuthenticatedGetRequest(url={self.url!r}, receipt_id={self.receipt.receipt_id!r}, <redacted>)"


def construct_dpop_get_request(
    *,
    grant: OAuthGrantContext,
    dpop_key: DpopSessionKey,
    url: str,
    nonce: DpopNonceContext,
    jti: str,
    issued_at: datetime,
    evaluated_at: datetime,
    replay_window: BoundedReplayWindow,
    space_evaluation: SpaceScopeEvaluation,
    policy: DpopEvaluationPolicy = DpopEvaluationPolicy(),
) -> AuthenticatedGetRequest:
    if not isinstance(nonce, DpopNonceContext):
        _fail("spaces_dpop_nonce_required", "server-issued DPoP nonce is required")
    if grant.receipt.dpop_jwk_thumbprint != dpop_key.thumbprint:
        _fail("spaces_dpop_key_mismatch", "proof key is not the session-bound key")
    if space_evaluation.oauth_grant_receipt_id != grant.receipt.receipt_id:
        _fail(
            "spaces_oauth_scope_refused",
            "Space evaluation belongs to another OAuth grant",
        )
    if nonce.server_origin != canonical_origin(url):
        _fail("spaces_dpop_nonce_mismatch", "nonce belongs to another server")
    if nonce.session_ref != dpop_key.session_ref:
        _fail("spaces_dpop_nonce_mismatch", "nonce belongs to another session")
    _require_space_read_target(url, space_evaluation)
    _text(jti, field_name="DPoP jti")
    if not _JTI.fullmatch(jti):
        _fail("spaces_dpop_jti_invalid", "DPoP jti is outside fixture bounds")
    issued = _utc(issued_at, field_name="issued_at")
    evaluated = _utc(evaluated_at, field_name="evaluated_at")
    iat = int(issued.timestamp())
    header = {"typ": "dpop+jwt", "alg": "ES256", "jwk": dict(dpop_key.public_jwk)}
    payload = {
        "htm": "GET",
        "htu": canonical_dpop_htu(url),
        "iat": iat,
        "jti": jti,
        "nonce": nonce.nonce,
        "ath": grant.access_token.ath,
    }
    encoded_header = _b64url(_canonical_json(header))
    encoded_payload = _b64url(_canonical_json(payload))
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    proof = (
        f"{encoded_header}.{encoded_payload}."
        f"{_b64url(dpop_key._sign_dpop_proof(signing_input))}"
    )
    request = AuthenticatedGetRequest.__new__(AuthenticatedGetRequest)
    object.__setattr__(request, "url", url)
    object.__setattr__(request, "proof", proof)
    object.__setattr__(request, "grant", grant)
    receipt = verify_dpop_get_request(
        request_url=url,
        method="GET",
        proof=proof,
        grant=grant,
        expected_key=dpop_key,
        expected_nonce=nonce,
        evaluated_at=evaluated,
        replay_window=replay_window,
        space_evaluation=space_evaluation,
        policy=policy,
    )
    object.__setattr__(request, "receipt", receipt)
    return request


def _decode_dpop(
    proof: str,
) -> tuple[dict[str, object], dict[str, object], bytes, bytes]:
    if not isinstance(proof, str) or proof.count(".") != 2:
        _fail("spaces_dpop_invalid", "DPoP proof is not a compact JWT")
    header_segment, payload_segment, signature_segment = proof.split(".")
    try:
        header = json.loads(
            _unb64url(header_segment), object_pairs_hook=_reject_duplicate_keys
        )
        payload = json.loads(
            _unb64url(payload_segment), object_pairs_hook=_reject_duplicate_keys
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValidationError("spaces_dpop_invalid", "DPoP JSON is ambiguous") from exc
    if not isinstance(header, dict) or not isinstance(payload, dict):
        _fail("spaces_dpop_invalid", "DPoP header and payload must be objects")
    return (
        header,
        payload,
        _unb64url(signature_segment),
        f"{header_segment}.{payload_segment}".encode("ascii"),
    )


def verify_dpop_get_request(
    *,
    request_url: str,
    method: str,
    proof: str,
    grant: OAuthGrantContext,
    expected_key: DpopSessionKey,
    expected_nonce: DpopNonceContext,
    evaluated_at: datetime,
    replay_window: BoundedReplayWindow,
    space_evaluation: SpaceScopeEvaluation,
    policy: DpopEvaluationPolicy = DpopEvaluationPolicy(),
) -> RequestBindingReceipt:
    if not isinstance(expected_nonce, DpopNonceContext):
        _fail("spaces_dpop_nonce_required", "server-issued DPoP nonce is required")
    if method != "GET":
        _fail("spaces_dpop_method_mismatch", "proof does not bind this method")
    if space_evaluation.oauth_grant_receipt_id != grant.receipt.receipt_id:
        _fail(
            "spaces_oauth_scope_refused",
            "Space evaluation belongs to another OAuth grant",
        )
    _require_space_read_target(request_url, space_evaluation)
    if expected_nonce.server_origin != canonical_origin(request_url):
        _fail("spaces_dpop_nonce_mismatch", "nonce belongs to another server")
    if expected_nonce.session_ref != expected_key.session_ref:
        _fail("spaces_dpop_nonce_mismatch", "nonce belongs to another session")
    header, payload, signature, signing_input = _decode_dpop(proof)
    if header.get("typ") != "dpop+jwt" or header.get("alg") != "ES256":
        _fail("spaces_dpop_header_mismatch", "DPoP type or algorithm is invalid")
    if set(header) != {"typ", "alg", "jwk"} or not isinstance(header["jwk"], dict):
        _fail("spaces_dpop_header_mismatch", "DPoP header shape is invalid")
    jwk = header["jwk"]
    if (
        set(jwk) != {"kty", "crv", "x", "y"}
        or jwk.get("kty") != "EC"
        or jwk.get("crv") != "P-256"
    ):
        _fail("spaces_dpop_key_invalid", "DPoP JWK is not public P-256")
    try:
        x = _unb64url(str(jwk["x"]))
        y = _unb64url(str(jwk["y"]))
    except (KeyError, TypeError) as exc:
        raise ValidationError(
            "spaces_dpop_key_invalid", "DPoP JWK coordinates are invalid"
        ) from exc
    if len(x) != 32 or len(y) != 32:
        _fail("spaces_dpop_key_invalid", "DPoP JWK coordinate width is invalid")
    thumbprint = _b64url(hashlib.sha256(_canonical_json(jwk)).digest())
    if (
        thumbprint != expected_key.thumbprint
        or thumbprint != grant.receipt.dpop_jwk_thumbprint
    ):
        _fail("spaces_dpop_key_mismatch", "proof key is not the session-bound key")
    compressed = bytes((2 | (int.from_bytes(y, "big") & 1),)) + x
    if compressed != expected_key.compressed_public_key or not verify_es256(
        compressed, signing_input, signature
    ):
        _fail("spaces_dpop_signature_invalid", "DPoP signature is invalid")
    required = {"htm", "htu", "iat", "jti", "nonce", "ath"}
    if set(payload) != required:
        _fail("spaces_dpop_claims_invalid", "DPoP claim set is not exact")
    if payload["htm"] != method:
        _fail("spaces_dpop_method_mismatch", "proof does not bind this method")
    htu = canonical_dpop_htu(request_url)
    if payload["htu"] != htu:
        _fail("spaces_dpop_target_mismatch", "proof does not bind this target")
    if payload["nonce"] != expected_nonce.nonce:
        _fail("spaces_dpop_nonce_mismatch", "proof nonce is stale or wrong")
    if payload["ath"] != grant.access_token.ath:
        _fail("spaces_dpop_token_mismatch", "proof does not bind this access token")
    jti = payload["jti"]
    if not isinstance(jti, str) or not _JTI.fullmatch(jti):
        _fail("spaces_dpop_jti_invalid", "DPoP jti is invalid")
    iat = payload["iat"]
    if isinstance(iat, bool) or not isinstance(iat, int):
        _fail("spaces_dpop_time_invalid", "DPoP iat is invalid")
    evaluated = _utc(evaluated_at, field_name="evaluated_at")
    age = int(evaluated.timestamp()) - iat
    if age > policy.maximum_age_seconds or age < -policy.future_skew_seconds:
        _fail("spaces_dpop_time_invalid", "DPoP iat is outside the bounded window")
    replay_window.record(jti)
    fields = dict(
        receipt_id="",
        method=method,
        request_url=request_url,
        canonical_htu=htu,
        request_url_sha256=_sha256(request_url.encode()),
        access_token_sha256=grant.receipt.access_token_sha256,
        dpop_jwk_thumbprint=thumbprint,
        proof_sha256=_sha256(proof.encode()),
        jti=jti,
        iat=iat,
        nonce_sha256=expected_nonce.digest,
        nonce_server_origin=expected_nonce.server_origin,
        ath=grant.access_token.ath,
        oauth_grant_receipt_id=grant.receipt.receipt_id,
        space_scope_evaluation_sha256=_space_evaluation_digest(space_evaluation),
        matching_space_scope=space_evaluation.matching_scope or "",
        subject_did=grant.receipt.token_subject,
        client_id=grant.receipt.client_id,
        evaluated_at=evaluated,
        verified_claims=frozenset(VerifiedDpopClaim),
    )
    probe = RequestBindingReceipt.__new__(RequestBindingReceipt)
    for name, value in fields.items():
        object.__setattr__(probe, name, value)
    receipt_id = _request_receipt_id(probe)
    return RequestBindingReceipt(
        receipt_id=receipt_id, **{k: v for k, v in fields.items() if k != "receipt_id"}
    )


@dataclass(frozen=True, slots=True)
class IdentityEndpointRequestComposition:
    composition_id: str
    resolution_receipt_id: str
    resolution_method: str
    did_binding_receipt_id: str
    request_binding_receipt_id: str
    selected_origin: str
    request_origin: str
    endpoint_matches: bool
    receipts_remain_independent: bool = True
    governance_authority: bool = False

    def __post_init__(self) -> None:
        if (
            not self.endpoint_matches
            or not self.receipts_remain_independent
            or self.governance_authority
        ):
            _fail(
                "spaces_oauth_endpoint_mismatch",
                "identity/request composition is invalid",
            )
        expected = _receipt_id(
            "sa9d-a-identity-request-composition",
            (
                self.resolution_receipt_id,
                self.resolution_method,
                self.did_binding_receipt_id,
                self.request_binding_receipt_id,
                self.selected_origin,
                self.request_origin,
            ),
        )
        if self.composition_id != expected:
            _fail("spaces_oauth_endpoint_mismatch", "composition receipt is not bound")


def compose_identity_bound_request(
    resolved: ResolvedDidDocument,
    binding: DidBindingReceipt,
    request: AuthenticatedGetRequest,
) -> IdentityEndpointRequestComposition:
    if (
        binding.profile is not DidInterpretationProfile.ACCOUNT_REPO_HOST
        or binding.selected_origin is None
    ):
        _fail(
            "spaces_oauth_endpoint_mismatch", "account PDS service binding is required"
        )
    if (
        binding.expected_did != resolved.expected_did
        or binding.document_provenance_ref != resolved.method_receipt_id
    ):
        _fail(
            "spaces_oauth_endpoint_mismatch",
            "resolution and service receipts do not compose",
        )
    request_origin = canonical_origin(request.url)
    if request_origin != binding.selected_origin:
        _fail(
            "spaces_oauth_endpoint_mismatch",
            "request origin differs from selected service",
        )
    values = (
        resolved.method_receipt_id,
        resolved.method.value,
        binding.receipt_id,
        request.receipt.receipt_id,
        binding.selected_origin,
        request_origin,
    )
    return IdentityEndpointRequestComposition(
        composition_id=_receipt_id("sa9d-a-identity-request-composition", values),
        resolution_receipt_id=resolved.method_receipt_id,
        resolution_method=resolved.method.value,
        did_binding_receipt_id=binding.receipt_id,
        request_binding_receipt_id=request.receipt.receipt_id,
        selected_origin=binding.selected_origin,
        request_origin=request_origin,
        endpoint_matches=True,
    )


__all__ = [
    "AuthenticatedGetRequest",
    "BoundedReplayWindow",
    "DpopEvaluationPolicy",
    "DpopNonceContext",
    "DpopSessionKey",
    "IdentityEndpointRequestComposition",
    "OAuthGrantContext",
    "OAuthGrantReceipt",
    "ParsedSpaceScope",
    "RequestBindingReceipt",
    "SecretAccessToken",
    "SpaceAction",
    "SpaceManageAction",
    "SpaceProtocolRequest",
    "SpaceScopeEvaluation",
    "VerifiedDpopClaim",
    "canonical_dpop_htu",
    "canonical_origin",
    "compose_identity_bound_request",
    "construct_dpop_get_request",
    "evaluate_space_protocol_grant",
    "parse_space_scope",
    "qualify_oauth_grant",
    "verify_dpop_get_request",
]
