"""SA9b bounded interpretation of supplied DID-document evidence.

Service binding interprets identity evidence; it does not create identity
evidence.  This module performs no DID-method resolution or network activity.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from community_model import ValidationError
from community_model.identifiers import validate_did

from .compat import (
    ALPHA_LABEL,
    ATPROTO_ACCOUNT_KEY_FRAGMENT,
    ATPROTO_PDS_FRAGMENT,
    ATPROTO_PDS_SERVICE_TYPE,
    ATPROTO_SPACE_HOST_FRAGMENT,
    ATPROTO_SPACE_KEY_FRAGMENT,
    SA9B_BINDING_DOCTRINE,
    SA9B_BINDING_METHOD,
    SA9B_BINDING_VERSION,
)
from .http_acquisition import (
    HttpAcquisitionDisposition,
    HttpAcquisitionReceipt,
)

MAX_DID_DOCUMENT_BYTES = 1 << 20
_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_K256_MULTICODEC = b"\xe7\x01"
_P256_MULTICODEC = b"\x80\x24"
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _fail(reason: str, message: str) -> None:
    raise ValidationError(reason, message)


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        _fail("spaces_did_binding_invalid", "qualification time must be aware")
    return value.astimezone(UTC)


def _nonempty(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(ord(character) < 0x20 for character in value)
    ):
        _fail("spaces_did_binding_invalid", f"{field_name} must be nonempty text")
    return value


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validate_sha256(value: str, *, field_name: str) -> None:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        _fail("spaces_did_binding_receipt_invalid", f"{field_name} is not SHA-256")


def _validate_expected_did(value: str) -> str:
    validate_did(value)
    if not value.startswith(("did:plc:", "did:web:")):
        _fail("spaces_did_method_unsupported", "DID method is not blessed by ATProto")
    return value


class DidDocumentProvenanceKind(StrEnum):
    FIXTURE = "fixture"
    DID_METHOD_RESOLVER_UNVERIFIED = "did_method_resolver_unverified"
    CALLER_SUPPLIED = "caller_supplied"
    FUTURE_VERIFIED_DID_RESOLUTION = "future_verified_did_resolution"


class DidInterpretationProfile(StrEnum):
    ACCOUNT_REPO_HOST = "account_repo_host"
    ACCOUNT_SIGNING_KEY = "account_signing_key"
    SPACE_AUTHORITY_HOST = "space_authority_host"
    SPACE_AUTHORITY_SIGNING_KEY = "space_authority_signing_key"


class DidBindingSelection(StrEnum):
    ACCOUNT_PDS = "account_pds"
    ACCOUNT_KEY = "account_key"
    DEDICATED_SPACE_HOST = "dedicated_space_host"
    FALLBACK_ACCOUNT_PDS = "fallback_account_pds"
    DEDICATED_SPACE_KEY = "dedicated_space_key"
    FALLBACK_ACCOUNT_KEY = "fallback_account_key"


class VerifiedDidBindingClaim(StrEnum):
    DOCUMENT_ID = "document_id_matches_expected_did"
    SERVICE_ENTRY = "ordered_service_entry_selected"
    PDS_SERVICE_TYPE = "atproto_pds_service_type"
    SERVICE_ENDPOINT = "service_endpoint_origin_well_formed"
    SPACE_HOST_FALLBACK = "space_host_fallback_applied"
    VERIFICATION_METHOD = "ordered_verification_method_selected"
    KEY_CONTROLLER = "verification_method_controller_matches_did"
    KEY_MATERIAL = "supported_multikey_public_material"
    SPACE_KEY_FALLBACK = "space_key_fallback_applied"


class EndpointBindingDisposition(StrEnum):
    ENDPOINT_MATCH = "endpoint_match"
    ENDPOINT_MISMATCH = "endpoint_mismatch"
    UNQUALIFIED_HTTP_ACQUISITION = "unqualified_http_acquisition"


@dataclass(frozen=True, slots=True)
class DidDocumentInput:
    expected_did: str
    document_bytes: bytes
    provenance_kind: DidDocumentProvenanceKind
    provenance_ref: str
    media_type: str | None = None
    allow_insecure_loopback_fixture: bool = False

    def __post_init__(self) -> None:
        _validate_expected_did(self.expected_did)
        if (
            not isinstance(self.document_bytes, bytes)
            or not self.document_bytes
            or len(self.document_bytes) > MAX_DID_DOCUMENT_BYTES
        ):
            _fail(
                "spaces_did_document_invalid", "DID document bytes are outside bounds"
            )
        if not isinstance(self.provenance_kind, DidDocumentProvenanceKind):
            _fail("spaces_did_binding_invalid", "document provenance kind is invalid")
        _nonempty(self.provenance_ref, field_name="document provenance reference")
        if self.media_type is not None:
            _nonempty(self.media_type, field_name="document media type")
        if not isinstance(self.allow_insecure_loopback_fixture, bool):
            _fail("spaces_did_binding_invalid", "loopback fixture policy is invalid")
        if self.allow_insecure_loopback_fixture and (
            self.provenance_kind
            not in {
                DidDocumentProvenanceKind.FIXTURE,
                DidDocumentProvenanceKind.FUTURE_VERIFIED_DID_RESOLUTION,
            }
        ):
            _fail(
                "spaces_did_binding_invalid",
                "insecure loopback is restricted to explicit fixtures",
            )


@dataclass(frozen=True, slots=True)
class ServiceOrigin:
    scheme: str
    hostname: str
    port: int
    origin: str
    fixture_loopback_http: bool = False

    def __post_init__(self) -> None:
        if self.scheme not in {"https", "http"}:
            _fail("spaces_service_endpoint_invalid", "service scheme is invalid")
        if (
            not self.hostname
            or not isinstance(self.port, int)
            or isinstance(self.port, bool)
            or not 1 <= self.port <= 65535
        ):
            _fail("spaces_service_endpoint_invalid", "service origin is invalid")
        expected = _format_origin(self.scheme, self.hostname, self.port)
        if self.origin != expected:
            _fail("spaces_service_endpoint_invalid", "service origin is not canonical")
        if (self.scheme == "http") != self.fixture_loopback_http:
            _fail("spaces_service_endpoint_invalid", "HTTP is fixture-only")


def _is_loopback(hostname: str) -> bool:
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _normalize_hostname(hostname: str) -> str:
    try:
        hostname.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValidationError(
            "spaces_service_endpoint_invalid",
            "Unicode hostnames must be supplied in ASCII IDNA form",
        ) from exc
    lowered = hostname.lower()
    if "%" in lowered or lowered.endswith("."):
        _fail("spaces_service_endpoint_invalid", "ambiguous hostname is prohibited")
    try:
        return ipaddress.ip_address(lowered).compressed
    except ValueError:
        pass
    if len(lowered) > 253 or any(
        not _DNS_LABEL.fullmatch(label) for label in lowered.split(".")
    ):
        _fail("spaces_service_endpoint_invalid", "hostname is invalid")
    return lowered


def _format_origin(scheme: str, hostname: str, port: int) -> str:
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if scheme == "https" else 80
    suffix = "" if port == default_port else f":{port}"
    return f"{scheme}://{rendered_host}{suffix}"


def normalize_service_origin(
    value: object, *, allow_insecure_loopback_fixture: bool = False
) -> ServiceOrigin:
    """Parse one conservative origin; this establishes no service ownership."""

    if (
        not isinstance(value, str)
        or not value
        or any(ord(character) < 0x21 for character in value)
    ):
        _fail("spaces_service_endpoint_invalid", "service endpoint is invalid")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValidationError(
            "spaces_service_endpoint_invalid", "service endpoint cannot be parsed"
        ) from exc
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        _fail(
            "spaces_service_endpoint_invalid",
            "service endpoint must contain only an origin",
        )
    scheme = parsed.scheme.lower()
    hostname = _normalize_hostname(parsed.hostname)
    if scheme == "https":
        fixture_http = False
        effective_port = port or 443
    elif (
        scheme == "http" and allow_insecure_loopback_fixture and _is_loopback(hostname)
    ):
        fixture_http = True
        effective_port = port or 80
    else:
        _fail("spaces_service_endpoint_invalid", "HTTPS service endpoint is required")
    return ServiceOrigin(
        scheme=scheme,
        hostname=hostname,
        port=effective_port,
        origin=_format_origin(scheme, hostname, effective_port),
        fixture_loopback_http=fixture_http,
    )


def _decode_base58btc(value: str) -> bytes:
    if not value.startswith("z") or len(value) < 2:
        _fail("spaces_did_key_invalid", "public key is not base58btc multibase")
    integer = 0
    for character in value[1:]:
        index = _B58_ALPHABET.find(character)
        if index < 0:
            _fail("spaces_did_key_invalid", "public key contains invalid base58")
        integer = integer * 58 + index
    leading = len(value[1:]) - len(value[1:].lstrip("1"))
    body = (
        b""
        if integer == 0
        else integer.to_bytes((integer.bit_length() + 7) // 8, "big")
    )
    return b"\x00" * leading + body


def _validate_multikey(value: object) -> tuple[str, str]:
    if not isinstance(value, str):
        _fail("spaces_did_key_invalid", "publicKeyMultibase must be text")
    decoded = _decode_base58btc(value)
    if decoded.startswith(_K256_MULTICODEC) and len(decoded) == 35:
        curve = "k256"
        public_key = decoded[len(_K256_MULTICODEC) :]
    elif decoded.startswith(_P256_MULTICODEC) and len(decoded) == 35:
        curve = "p256"
        public_key = decoded[len(_P256_MULTICODEC) :]
    else:
        _fail("spaces_did_key_invalid", "public key multicodec is unsupported")
    if public_key[0] not in {2, 3}:
        _fail("spaces_did_key_invalid", "public key is not compressed")
    return value, curve


class _DuplicateJsonKey(ValueError):
    pass


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


def _parse_document(value: bytes) -> Mapping[str, object]:
    try:
        parsed = json.loads(
            value.decode("utf-8"), object_pairs_hook=_object_without_duplicates
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValidationError(
            "spaces_did_document_invalid",
            "DID document is not unambiguous UTF-8 JSON",
        ) from exc
    if not isinstance(parsed, Mapping):
        _fail("spaces_did_document_invalid", "DID document must be an object")
    return parsed


def _accepted_identifier(expected_did: str, fragment: str) -> tuple[str, str]:
    return f"#{fragment}", f"{expected_did}#{fragment}"


def _check_foreign_fragments(
    entries: list[object], expected_did: str, fragment: str
) -> None:
    accepted = _accepted_identifier(expected_did, fragment)
    suffix = f"#{fragment}"
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        identifier = entry.get("id")
        if (
            isinstance(identifier, str)
            and identifier.endswith(suffix)
            and identifier not in accepted
        ):
            _fail(
                "spaces_did_foreign_fragment",
                f"{fragment} entry is qualified by another DID",
            )


def _service_entries(document: Mapping[str, object]) -> list[object]:
    entries = document.get("service")
    if not isinstance(entries, list):
        _fail("spaces_did_service_missing", "DID document has no service array")
    return entries


def _verification_methods(document: Mapping[str, object]) -> list[object]:
    entries = document.get("verificationMethod")
    if not isinstance(entries, list):
        _fail("spaces_did_key_missing", "DID document has no verification methods")
    return entries


def _select_pds(
    document: Mapping[str, object], evidence: DidDocumentInput
) -> tuple[Mapping[str, object], ServiceOrigin]:
    entries = _service_entries(document)
    _check_foreign_fragments(entries, evidence.expected_did, ATPROTO_PDS_FRAGMENT)
    accepted = _accepted_identifier(evidence.expected_did, ATPROTO_PDS_FRAGMENT)
    for entry in entries:
        if not isinstance(entry, Mapping) or entry.get("id") not in accepted:
            continue
        if entry.get("type") != ATPROTO_PDS_SERVICE_TYPE:
            continue
        try:
            origin = normalize_service_origin(
                entry.get("serviceEndpoint"),
                allow_insecure_loopback_fixture=evidence.allow_insecure_loopback_fixture,
            )
        except ValidationError:
            continue
        return entry, origin
    _fail("spaces_did_pds_not_found", "no valid ordered ATProto PDS service exists")


def _select_space_host(
    document: Mapping[str, object], evidence: DidDocumentInput
) -> tuple[Mapping[str, object], ServiceOrigin, DidBindingSelection]:
    entries = _service_entries(document)
    _check_foreign_fragments(
        entries, evidence.expected_did, ATPROTO_SPACE_HOST_FRAGMENT
    )
    accepted = _accepted_identifier(evidence.expected_did, ATPROTO_SPACE_HOST_FRAGMENT)
    dedicated = [
        entry
        for entry in entries
        if isinstance(entry, Mapping) and entry.get("id") in accepted
    ]
    if dedicated:
        for entry in dedicated:
            if not isinstance(entry.get("type"), str) or not entry.get("type"):
                continue
            try:
                origin = normalize_service_origin(
                    entry.get("serviceEndpoint"),
                    allow_insecure_loopback_fixture=(
                        evidence.allow_insecure_loopback_fixture
                    ),
                )
            except ValidationError:
                continue
            return entry, origin, DidBindingSelection.DEDICATED_SPACE_HOST
        _fail(
            "spaces_did_dedicated_service_invalid",
            "present dedicated Space host is invalid; fallback is not absence",
        )
    entry, origin = _select_pds(document, evidence)
    return entry, origin, DidBindingSelection.FALLBACK_ACCOUNT_PDS


def _valid_key_entry(
    entry: Mapping[str, object], *, expected_did: str
) -> tuple[str, str] | None:
    if entry.get("controller") != expected_did:
        return None
    if entry.get("type") != "Multikey":
        return None
    try:
        return _validate_multikey(entry.get("publicKeyMultibase"))
    except ValidationError:
        return None


def _select_key_fragment(
    methods: list[object], *, expected_did: str, fragment: str
) -> tuple[Mapping[str, object], str, str] | None:
    _check_foreign_fragments(methods, expected_did, fragment)
    accepted = _accepted_identifier(expected_did, fragment)
    for method in methods:
        if not isinstance(method, Mapping) or method.get("id") not in accepted:
            continue
        selected = _valid_key_entry(method, expected_did=expected_did)
        if selected is not None:
            material, curve = selected
            return method, material, curve
    return None


def _select_space_key(
    document: Mapping[str, object], evidence: DidDocumentInput
) -> tuple[Mapping[str, object], str, str, DidBindingSelection]:
    methods = _verification_methods(document)
    dedicated_ids = _accepted_identifier(
        evidence.expected_did, ATPROTO_SPACE_KEY_FRAGMENT
    )
    dedicated_present = any(
        isinstance(method, Mapping) and method.get("id") in dedicated_ids
        for method in methods
    )
    dedicated = _select_key_fragment(
        methods,
        expected_did=evidence.expected_did,
        fragment=ATPROTO_SPACE_KEY_FRAGMENT,
    )
    if dedicated is not None:
        method, material, curve = dedicated
        return method, material, curve, DidBindingSelection.DEDICATED_SPACE_KEY
    if dedicated_present:
        _fail(
            "spaces_did_dedicated_key_invalid",
            "present dedicated Space key is invalid; fallback is not absence",
        )
    fallback = _select_key_fragment(
        methods,
        expected_did=evidence.expected_did,
        fragment=ATPROTO_ACCOUNT_KEY_FRAGMENT,
    )
    if fallback is None:
        _fail("spaces_did_key_not_found", "no valid account signing key exists")
    method, material, curve = fallback
    return method, material, curve, DidBindingSelection.FALLBACK_ACCOUNT_KEY


def _select_account_key(
    document: Mapping[str, object], evidence: DidDocumentInput
) -> tuple[Mapping[str, object], str, str]:
    methods = _verification_methods(document)
    selected = _select_key_fragment(
        methods,
        expected_did=evidence.expected_did,
        fragment=ATPROTO_ACCOUNT_KEY_FRAGMENT,
    )
    if selected is None:
        _fail("spaces_did_key_not_found", "no valid account signing key exists")
    return selected


def _receipt_identifier(**fields: object) -> str:
    claims = fields["verified_claims"]
    assert isinstance(claims, frozenset)
    values = [
        "spaces-did-binding-receipt-v1",
        SA9B_BINDING_METHOD,
        SA9B_BINDING_VERSION,
        SA9B_BINDING_DOCTRINE,
        *(
            str(fields[name]) if fields[name] is not None else "-"
            for name in (
                "expected_did",
                "document_sha256",
                "document_provenance_kind",
                "document_provenance_ref",
                "document_media_type",
                "profile",
                "selection",
                "selected_identifier",
                "selected_type",
                "selected_origin",
                "selected_key_controller",
                "selected_public_key_multibase",
                "selected_key_curve",
                "endpoint_policy",
            )
        ),
        *(
            f"claim:{claim.value}"
            for claim in sorted(claims, key=lambda item: item.value)
        ),
        str(fields["qualified_at"]),
    ]
    return "sha256:" + hashlib.sha256("\x00".join(values).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class DidBindingReceipt:
    receipt_id: str
    expected_did: str
    document_sha256: str
    document_provenance_kind: DidDocumentProvenanceKind
    document_provenance_ref: str
    document_media_type: str | None
    profile: DidInterpretationProfile
    selection: DidBindingSelection
    selected_identifier: str
    selected_type: str
    selected_origin: str | None
    selected_key_controller: str | None
    selected_public_key_multibase: str | None
    selected_key_curve: str | None
    endpoint_policy: str | None
    verified_claims: frozenset[VerifiedDidBindingClaim]
    qualified_at: datetime
    protocol_assumption: str = field(default=ALPHA_LABEL, init=False)
    binding_method: str = field(default=SA9B_BINDING_METHOD, init=False)
    binding_version: str = field(default=SA9B_BINDING_VERSION, init=False)
    doctrine: str = field(default=SA9B_BINDING_DOCTRINE, init=False)
    did_resolution_verified: bool = False
    did_state_current: bool = False
    remote_service_control_verified: bool = False
    canonical_service: bool = False
    artifact_validity: bool = False
    standing: bool = False
    authorization: bool = False
    governance_authority: bool = False

    def __post_init__(self) -> None:
        _validate_expected_did(self.expected_did)
        _validate_sha256(self.document_sha256, field_name="document digest")
        _nonempty(self.document_provenance_ref, field_name="provenance reference")
        if self.document_media_type is not None:
            _nonempty(self.document_media_type, field_name="document media type")
        if not isinstance(self.document_provenance_kind, DidDocumentProvenanceKind):
            _fail("spaces_did_binding_receipt_invalid", "provenance kind is invalid")
        if not isinstance(self.profile, DidInterpretationProfile) or not isinstance(
            self.selection, DidBindingSelection
        ):
            _fail("spaces_did_binding_receipt_invalid", "selection profile is invalid")
        _nonempty(self.selected_identifier, field_name="selected identifier")
        _nonempty(self.selected_type, field_name="selected type")
        if not isinstance(self.verified_claims, frozenset) or any(
            not isinstance(claim, VerifiedDidBindingClaim)
            for claim in self.verified_claims
        ):
            _fail("spaces_did_binding_receipt_invalid", "claim set is invalid")
        if VerifiedDidBindingClaim.DOCUMENT_ID not in self.verified_claims:
            _fail("spaces_did_binding_receipt_invalid", "document claim is absent")
        key_profiles = {
            DidInterpretationProfile.ACCOUNT_SIGNING_KEY,
            DidInterpretationProfile.SPACE_AUTHORITY_SIGNING_KEY,
        }
        service_profile = self.profile not in key_profiles
        if service_profile:
            if (
                self.selected_origin is None
                or self.selected_key_controller is not None
                or self.selected_public_key_multibase is not None
                or self.selected_key_curve is not None
                or self.endpoint_policy not in {"https_origin", "fixture_loopback_http"}
                or VerifiedDidBindingClaim.SERVICE_ENTRY not in self.verified_claims
                or VerifiedDidBindingClaim.SERVICE_ENDPOINT not in self.verified_claims
            ):
                _fail(
                    "spaces_did_binding_receipt_invalid", "service receipt is invalid"
                )
            allowed_selections = {
                DidInterpretationProfile.ACCOUNT_REPO_HOST: {
                    DidBindingSelection.ACCOUNT_PDS
                },
                DidInterpretationProfile.SPACE_AUTHORITY_HOST: {
                    DidBindingSelection.DEDICATED_SPACE_HOST,
                    DidBindingSelection.FALLBACK_ACCOUNT_PDS,
                },
            }
            if self.selection not in allowed_selections[self.profile]:
                _fail(
                    "spaces_did_binding_receipt_invalid",
                    "service selection does not match interpretation profile",
                )
            fragment = (
                ATPROTO_SPACE_HOST_FRAGMENT
                if self.selection is DidBindingSelection.DEDICATED_SPACE_HOST
                else ATPROTO_PDS_FRAGMENT
            )
            if self.selected_identifier not in _accepted_identifier(
                self.expected_did, fragment
            ):
                _fail(
                    "spaces_did_binding_receipt_invalid",
                    "selected service identifier is not bound to the expected DID",
                )
            if self.selection is not DidBindingSelection.DEDICATED_SPACE_HOST and (
                self.selected_type != ATPROTO_PDS_SERVICE_TYPE
                or VerifiedDidBindingClaim.PDS_SERVICE_TYPE not in self.verified_claims
            ):
                _fail(
                    "spaces_did_binding_receipt_invalid",
                    "PDS selection lacks its exact service-type claim",
                )
            has_host_fallback = (
                VerifiedDidBindingClaim.SPACE_HOST_FALLBACK in self.verified_claims
            )
            if has_host_fallback != (
                self.selection is DidBindingSelection.FALLBACK_ACCOUNT_PDS
            ):
                _fail(
                    "spaces_did_binding_receipt_invalid",
                    "Space-host fallback provenance is inconsistent",
                )
            normalized_origin = normalize_service_origin(
                self.selected_origin,
                allow_insecure_loopback_fixture=(
                    self.endpoint_policy == "fixture_loopback_http"
                ),
            )
            if normalized_origin.origin != self.selected_origin or (
                normalized_origin.fixture_loopback_http
                != (self.endpoint_policy == "fixture_loopback_http")
            ):
                _fail(
                    "spaces_did_binding_receipt_invalid",
                    "selected service origin is not canonical",
                )
        elif (
            self.selected_origin is not None
            or self.endpoint_policy is not None
            or self.selected_key_controller != self.expected_did
            or self.selected_public_key_multibase is None
            or self.selected_key_curve not in {"k256", "p256"}
            or VerifiedDidBindingClaim.VERIFICATION_METHOD not in self.verified_claims
            or VerifiedDidBindingClaim.KEY_CONTROLLER not in self.verified_claims
            or VerifiedDidBindingClaim.KEY_MATERIAL not in self.verified_claims
        ):
            _fail("spaces_did_binding_receipt_invalid", "key receipt is invalid")
        else:
            allowed_key_selections = {
                DidBindingSelection.ACCOUNT_KEY: ATPROTO_ACCOUNT_KEY_FRAGMENT,
                DidBindingSelection.DEDICATED_SPACE_KEY: ATPROTO_SPACE_KEY_FRAGMENT,
                DidBindingSelection.FALLBACK_ACCOUNT_KEY: ATPROTO_ACCOUNT_KEY_FRAGMENT,
            }
            fragment = allowed_key_selections.get(self.selection)
            if fragment is None or self.selected_identifier not in _accepted_identifier(
                self.expected_did, fragment
            ):
                _fail(
                    "spaces_did_binding_receipt_invalid",
                    "selected key identifier is not bound to the expected DID",
                )
            if self.selected_type != "Multikey":
                _fail(
                    "spaces_did_binding_receipt_invalid",
                    "selected key type is unsupported",
                )
            _, curve = _validate_multikey(self.selected_public_key_multibase)
            if curve != self.selected_key_curve:
                _fail(
                    "spaces_did_binding_receipt_invalid",
                    "selected key curve does not match its public material",
                )
            has_key_fallback = (
                VerifiedDidBindingClaim.SPACE_KEY_FALLBACK in self.verified_claims
            )
            if has_key_fallback != (
                self.selection is DidBindingSelection.FALLBACK_ACCOUNT_KEY
            ):
                _fail(
                    "spaces_did_binding_receipt_invalid",
                    "Space-key fallback provenance is inconsistent",
                )
            if (self.profile is DidInterpretationProfile.ACCOUNT_SIGNING_KEY) != (
                self.selection is DidBindingSelection.ACCOUNT_KEY
            ):
                _fail(
                    "spaces_did_binding_receipt_invalid",
                    "account key selection does not match interpretation profile",
                )
        expected_claims = {
            DidBindingSelection.ACCOUNT_PDS: frozenset(
                {
                    VerifiedDidBindingClaim.DOCUMENT_ID,
                    VerifiedDidBindingClaim.SERVICE_ENTRY,
                    VerifiedDidBindingClaim.PDS_SERVICE_TYPE,
                    VerifiedDidBindingClaim.SERVICE_ENDPOINT,
                }
            ),
            DidBindingSelection.DEDICATED_SPACE_HOST: frozenset(
                {
                    VerifiedDidBindingClaim.DOCUMENT_ID,
                    VerifiedDidBindingClaim.SERVICE_ENTRY,
                    VerifiedDidBindingClaim.SERVICE_ENDPOINT,
                }
            ),
            DidBindingSelection.FALLBACK_ACCOUNT_PDS: frozenset(
                {
                    VerifiedDidBindingClaim.DOCUMENT_ID,
                    VerifiedDidBindingClaim.SERVICE_ENTRY,
                    VerifiedDidBindingClaim.PDS_SERVICE_TYPE,
                    VerifiedDidBindingClaim.SERVICE_ENDPOINT,
                    VerifiedDidBindingClaim.SPACE_HOST_FALLBACK,
                }
            ),
            DidBindingSelection.DEDICATED_SPACE_KEY: frozenset(
                {
                    VerifiedDidBindingClaim.DOCUMENT_ID,
                    VerifiedDidBindingClaim.VERIFICATION_METHOD,
                    VerifiedDidBindingClaim.KEY_CONTROLLER,
                    VerifiedDidBindingClaim.KEY_MATERIAL,
                }
            ),
            DidBindingSelection.ACCOUNT_KEY: frozenset(
                {
                    VerifiedDidBindingClaim.DOCUMENT_ID,
                    VerifiedDidBindingClaim.VERIFICATION_METHOD,
                    VerifiedDidBindingClaim.KEY_CONTROLLER,
                    VerifiedDidBindingClaim.KEY_MATERIAL,
                }
            ),
            DidBindingSelection.FALLBACK_ACCOUNT_KEY: frozenset(
                {
                    VerifiedDidBindingClaim.DOCUMENT_ID,
                    VerifiedDidBindingClaim.VERIFICATION_METHOD,
                    VerifiedDidBindingClaim.KEY_CONTROLLER,
                    VerifiedDidBindingClaim.KEY_MATERIAL,
                    VerifiedDidBindingClaim.SPACE_KEY_FALLBACK,
                }
            ),
        }
        if self.verified_claims != expected_claims[self.selection]:
            _fail(
                "spaces_did_binding_receipt_invalid",
                "receipt claim set exceeds or omits the selected interpretation",
            )
        object.__setattr__(self, "qualified_at", _utc(self.qualified_at))
        if any(
            (
                self.did_resolution_verified,
                self.did_state_current,
                self.remote_service_control_verified,
                self.canonical_service,
                self.artifact_validity,
                self.standing,
                self.authorization,
                self.governance_authority,
            )
        ):
            _fail(
                "spaces_did_binding_receipt_invalid",
                "document interpretation cannot create identity or authority",
            )
        expected = _receipt_identifier(
            expected_did=self.expected_did,
            document_sha256=self.document_sha256,
            document_provenance_kind=self.document_provenance_kind.value,
            document_provenance_ref=self.document_provenance_ref,
            document_media_type=self.document_media_type,
            profile=self.profile.value,
            selection=self.selection.value,
            selected_identifier=self.selected_identifier,
            selected_type=self.selected_type,
            selected_origin=self.selected_origin,
            selected_key_controller=self.selected_key_controller,
            selected_public_key_multibase=self.selected_public_key_multibase,
            selected_key_curve=self.selected_key_curve,
            endpoint_policy=self.endpoint_policy,
            verified_claims=self.verified_claims,
            qualified_at=self.qualified_at.isoformat(),
        )
        if self.receipt_id != expected:
            _fail("spaces_did_binding_receipt_invalid", "receipt is not bound")

    def to_provenance(self) -> dict[str, object]:
        return {
            "receiptId": self.receipt_id,
            "expectedDid": self.expected_did,
            "documentSha256": self.document_sha256,
            "documentProvenanceKind": self.document_provenance_kind.value,
            "documentProvenanceRef": self.document_provenance_ref,
            "documentMediaType": self.document_media_type,
            "profile": self.profile.value,
            "selection": self.selection.value,
            "selectedIdentifier": self.selected_identifier,
            "selectedType": self.selected_type,
            "selectedOrigin": self.selected_origin,
            "selectedKeyController": self.selected_key_controller,
            "selectedPublicKeyMultibase": self.selected_public_key_multibase,
            "selectedKeyCurve": self.selected_key_curve,
            "endpointPolicy": self.endpoint_policy,
            "verifiedClaims": sorted(claim.value for claim in self.verified_claims),
            "qualifiedAt": self.qualified_at.isoformat(),
            "bindingMethod": self.binding_method,
            "bindingVersion": self.binding_version,
            "doctrine": self.doctrine,
            "didResolutionVerified": False,
            "didStateCurrent": False,
            "remoteServiceControlVerified": False,
            "canonicalService": False,
            "artifactValidity": False,
            "standing": False,
            "authorization": False,
            "governanceAuthority": False,
        }


def qualify_did_document(
    evidence: DidDocumentInput,
    *,
    profile: DidInterpretationProfile,
    qualified_at: datetime,
) -> DidBindingReceipt:
    """Interpret exact supplied bytes under one pinned profile."""

    if not isinstance(evidence, DidDocumentInput) or not isinstance(
        profile, DidInterpretationProfile
    ):
        _fail("spaces_did_binding_invalid", "DID input or profile is invalid")
    document = _parse_document(evidence.document_bytes)
    if document.get("id") != evidence.expected_did:
        _fail(
            "spaces_did_document_id_mismatch", "document id differs from expected DID"
        )
    claims = {VerifiedDidBindingClaim.DOCUMENT_ID}
    selected_origin: str | None = None
    selected_key_controller: str | None = None
    selected_public_key_multibase: str | None = None
    selected_key_curve: str | None = None
    endpoint_policy: str | None = None
    if profile is DidInterpretationProfile.ACCOUNT_REPO_HOST:
        entry, origin = _select_pds(document, evidence)
        selection = DidBindingSelection.ACCOUNT_PDS
        claims.update(
            {
                VerifiedDidBindingClaim.SERVICE_ENTRY,
                VerifiedDidBindingClaim.PDS_SERVICE_TYPE,
                VerifiedDidBindingClaim.SERVICE_ENDPOINT,
            }
        )
        selected_identifier = str(entry["id"])
        selected_type = str(entry["type"])
        selected_origin = origin.origin
        endpoint_policy = (
            "fixture_loopback_http" if origin.fixture_loopback_http else "https_origin"
        )
    elif profile is DidInterpretationProfile.SPACE_AUTHORITY_HOST:
        entry, origin, selection = _select_space_host(document, evidence)
        claims.update(
            {
                VerifiedDidBindingClaim.SERVICE_ENTRY,
                VerifiedDidBindingClaim.SERVICE_ENDPOINT,
            }
        )
        if selection is DidBindingSelection.FALLBACK_ACCOUNT_PDS:
            claims.update(
                {
                    VerifiedDidBindingClaim.PDS_SERVICE_TYPE,
                    VerifiedDidBindingClaim.SPACE_HOST_FALLBACK,
                }
            )
        selected_identifier = str(entry["id"])
        selected_type = str(entry["type"])
        selected_origin = origin.origin
        endpoint_policy = (
            "fixture_loopback_http" if origin.fixture_loopback_http else "https_origin"
        )
    elif profile is DidInterpretationProfile.SPACE_AUTHORITY_SIGNING_KEY:
        method, material, curve, selection = _select_space_key(document, evidence)
        claims.update(
            {
                VerifiedDidBindingClaim.VERIFICATION_METHOD,
                VerifiedDidBindingClaim.KEY_CONTROLLER,
                VerifiedDidBindingClaim.KEY_MATERIAL,
            }
        )
        if selection is DidBindingSelection.FALLBACK_ACCOUNT_KEY:
            claims.add(VerifiedDidBindingClaim.SPACE_KEY_FALLBACK)
        selected_identifier = str(method["id"])
        selected_type = str(method["type"])
        selected_key_controller = str(method["controller"])
        selected_public_key_multibase = material
        selected_key_curve = curve
    else:
        method, material, curve = _select_account_key(document, evidence)
        selection = DidBindingSelection.ACCOUNT_KEY
        claims.update(
            {
                VerifiedDidBindingClaim.VERIFICATION_METHOD,
                VerifiedDidBindingClaim.KEY_CONTROLLER,
                VerifiedDidBindingClaim.KEY_MATERIAL,
            }
        )
        selected_identifier = str(method["id"])
        selected_type = str(method["type"])
        selected_key_controller = str(method["controller"])
        selected_public_key_multibase = material
        selected_key_curve = curve
    fields = {
        "expected_did": evidence.expected_did,
        "document_sha256": _sha256(evidence.document_bytes),
        "document_provenance_kind": evidence.provenance_kind,
        "document_provenance_ref": evidence.provenance_ref,
        "document_media_type": evidence.media_type,
        "profile": profile,
        "selection": selection,
        "selected_identifier": selected_identifier,
        "selected_type": selected_type,
        "selected_origin": selected_origin,
        "selected_key_controller": selected_key_controller,
        "selected_public_key_multibase": selected_public_key_multibase,
        "selected_key_curve": selected_key_curve,
        "endpoint_policy": endpoint_policy,
        "verified_claims": frozenset(claims),
        "qualified_at": _utc(qualified_at),
    }
    receipt_id = _receipt_identifier(
        **{
            **fields,
            "document_provenance_kind": evidence.provenance_kind.value,
            "profile": profile.value,
            "selection": selection.value,
            "qualified_at": fields["qualified_at"].isoformat(),
        }
    )
    return DidBindingReceipt(receipt_id=receipt_id, **fields)


def require_receipt_document_binding(
    receipt: DidBindingReceipt, evidence: DidDocumentInput
) -> None:
    """Refuse reuse of a receipt with different supplied document evidence."""

    if not isinstance(receipt, DidBindingReceipt) or not isinstance(
        evidence, DidDocumentInput
    ):
        _fail("spaces_did_binding_invalid", "receipt and document input are required")
    if (
        receipt.expected_did != evidence.expected_did
        or receipt.document_sha256 != _sha256(evidence.document_bytes)
        or receipt.document_provenance_kind is not evidence.provenance_kind
        or receipt.document_provenance_ref != evidence.provenance_ref
        or receipt.document_media_type != evidence.media_type
    ):
        _fail(
            "spaces_did_receipt_document_mismatch",
            "receipt is not bound to these DID-document bytes and provenance",
        )


def verification_key_bytes(receipt: DidBindingReceipt) -> bytes:
    """Return the validated compressed public key bound by a key receipt."""

    if not isinstance(receipt, DidBindingReceipt) or receipt.profile not in {
        DidInterpretationProfile.ACCOUNT_SIGNING_KEY,
        DidInterpretationProfile.SPACE_AUTHORITY_SIGNING_KEY,
    }:
        _fail("spaces_did_key_receipt_required", "a qualified key receipt is required")
    if receipt.selected_public_key_multibase is None:
        _fail("spaces_did_key_receipt_required", "key receipt has no public material")
    decoded = _decode_base58btc(receipt.selected_public_key_multibase)
    prefix = (
        _K256_MULTICODEC if receipt.selected_key_curve == "k256" else _P256_MULTICODEC
    )
    if not decoded.startswith(prefix) or len(decoded) != len(prefix) + 33:
        _fail("spaces_did_key_receipt_invalid", "key receipt material is inconsistent")
    return decoded[len(prefix) :]


def _assessment_identifier(
    did_binding_receipt_id: str,
    http_acquisition_receipt_id: str,
    disposition: EndpointBindingDisposition,
    selected_origin: str,
    requested_origin: str | None,
    final_origin: str | None,
    reason: str,
) -> str:
    values = (
        "spaces-http-did-endpoint-assessment-v1",
        did_binding_receipt_id,
        http_acquisition_receipt_id,
        disposition.value,
        selected_origin,
        requested_origin or "-",
        final_origin or "-",
        reason,
    )
    return "sha256:" + hashlib.sha256("\x00".join(values).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class HttpEndpointBindingAssessment:
    assessment_id: str
    did_binding_receipt_id: str
    http_acquisition_receipt_id: str
    disposition: EndpointBindingDisposition
    selected_origin: str
    requested_origin: str | None
    final_origin: str | None
    reason: str
    did_resolution_verified: bool = False
    remote_service_control_verified: bool = False
    artifact_validity: bool = False
    authorization: bool = False
    governance_authority: bool = False

    def __post_init__(self) -> None:
        _nonempty(self.did_binding_receipt_id, field_name="DID binding receipt id")
        _nonempty(
            self.http_acquisition_receipt_id,
            field_name="HTTP acquisition receipt id",
        )
        _nonempty(self.reason, field_name="endpoint assessment reason")
        if not isinstance(self.disposition, EndpointBindingDisposition):
            _fail("spaces_endpoint_binding_invalid", "disposition is invalid")
        selected = normalize_service_origin(
            self.selected_origin, allow_insecure_loopback_fixture=True
        ).origin
        if selected != self.selected_origin:
            _fail("spaces_endpoint_binding_invalid", "selected origin is not canonical")
        for name, origin in (
            ("requested", self.requested_origin),
            ("final", self.final_origin),
        ):
            if origin is not None and (
                normalize_service_origin(
                    origin, allow_insecure_loopback_fixture=True
                ).origin
                != origin
            ):
                _fail(
                    "spaces_endpoint_binding_invalid", f"{name} origin is not canonical"
                )
        if self.disposition is EndpointBindingDisposition.ENDPOINT_MATCH and not (
            self.selected_origin == self.requested_origin == self.final_origin
        ):
            _fail("spaces_endpoint_binding_invalid", "matching origins differ")
        if self.disposition is EndpointBindingDisposition.ENDPOINT_MISMATCH and (
            self.requested_origin is None
            or self.final_origin is None
            or self.selected_origin == self.requested_origin == self.final_origin
        ):
            _fail("spaces_endpoint_binding_invalid", "mismatch is not demonstrated")
        if (
            self.disposition is EndpointBindingDisposition.UNQUALIFIED_HTTP_ACQUISITION
            and (self.requested_origin is not None or self.final_origin is not None)
        ):
            _fail(
                "spaces_endpoint_binding_invalid",
                "unqualified HTTP acquisition cannot assert contacted origins",
            )
        if any(
            (
                self.did_resolution_verified,
                self.remote_service_control_verified,
                self.artifact_validity,
                self.authorization,
                self.governance_authority,
            )
        ):
            _fail(
                "spaces_endpoint_binding_invalid", "endpoint match cannot confer trust"
            )
        expected = _assessment_identifier(
            self.did_binding_receipt_id,
            self.http_acquisition_receipt_id,
            self.disposition,
            self.selected_origin,
            self.requested_origin,
            self.final_origin,
            self.reason,
        )
        if self.assessment_id != expected:
            _fail("spaces_endpoint_binding_invalid", "assessment is not bound")

    def to_provenance(self) -> dict[str, object]:
        return {
            "assessmentId": self.assessment_id,
            "didBindingReceiptId": self.did_binding_receipt_id,
            "httpAcquisitionReceiptId": self.http_acquisition_receipt_id,
            "disposition": self.disposition.value,
            "selectedOrigin": self.selected_origin,
            "requestedOrigin": self.requested_origin,
            "finalOrigin": self.final_origin,
            "reason": self.reason,
            "didResolutionVerified": False,
            "remoteServiceControlVerified": False,
            "artifactValidity": False,
            "authorization": False,
            "governanceAuthority": False,
        }


def assess_http_endpoint_binding(
    receipt: DidBindingReceipt, acquisition: HttpAcquisitionReceipt
) -> HttpEndpointBindingAssessment:
    """Compare selected and contacted origins without upgrading either receipt."""

    if not isinstance(receipt, DidBindingReceipt) or not isinstance(
        acquisition, HttpAcquisitionReceipt
    ):
        _fail(
            "spaces_endpoint_binding_invalid", "binding and HTTP receipts are required"
        )
    if receipt.selected_origin is None:
        _fail(
            "spaces_endpoint_binding_invalid", "key selection has no network endpoint"
        )
    requested_origin: str | None = None
    final_origin: str | None = None
    if acquisition.disposition is not HttpAcquisitionDisposition.ACQUIRED:
        disposition = EndpointBindingDisposition.UNQUALIFIED_HTTP_ACQUISITION
        reason = "HTTP acquisition did not produce an artifact"
    else:
        requested_origin = normalize_service_origin(
            _origin_only(acquisition.requested_url),
            allow_insecure_loopback_fixture=True,
        ).origin
        final_origin = normalize_service_origin(
            _origin_only(acquisition.final_url),
            allow_insecure_loopback_fixture=True,
        ).origin
        if requested_origin == receipt.selected_origin == final_origin:
            disposition = EndpointBindingDisposition.ENDPOINT_MATCH
            reason = "selected, requested, and final origins match"
        else:
            disposition = EndpointBindingDisposition.ENDPOINT_MISMATCH
            reason = "selected origin differs from requested or final origin"
    assessment_id = _assessment_identifier(
        receipt.receipt_id,
        acquisition.receipt_id,
        disposition,
        receipt.selected_origin,
        requested_origin,
        final_origin,
        reason,
    )
    return HttpEndpointBindingAssessment(
        assessment_id=assessment_id,
        did_binding_receipt_id=receipt.receipt_id,
        http_acquisition_receipt_id=acquisition.receipt_id,
        disposition=disposition,
        selected_origin=receipt.selected_origin,
        requested_origin=requested_origin,
        final_origin=final_origin,
        reason=reason,
    )


def _origin_only(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


__all__ = [
    "DidBindingReceipt",
    "DidBindingSelection",
    "DidDocumentInput",
    "DidDocumentProvenanceKind",
    "DidInterpretationProfile",
    "EndpointBindingDisposition",
    "HttpEndpointBindingAssessment",
    "MAX_DID_DOCUMENT_BYTES",
    "ServiceOrigin",
    "VerifiedDidBindingClaim",
    "assess_http_endpoint_binding",
    "normalize_service_origin",
    "qualify_did_document",
    "require_receipt_document_binding",
    "verification_key_bytes",
]
