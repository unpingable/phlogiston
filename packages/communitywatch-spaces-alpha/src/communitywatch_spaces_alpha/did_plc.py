"""SA9c-plc: fixture/reference PLC v0.3.0 operation-history qualification."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from community_model import ValidationError
from community_model.canonical import cid_for_dag_cbor
from community_model.dag_cbor import decode_dag_cbor, encode_dag_cbor

from .compat import (
    SA9C_AUTHORITY_DOCTRINE,
    SA9C_PLC_METHOD,
    SA9C_PLC_REFERENCE_COMMIT,
    SA9C_PLC_SPEC_VERSION,
    SA9C_PLC_VERSION,
    SA9C_RESOLUTION_DOCTRINE,
)
from .crypto import verify_es256, verify_es256k
from .did_resolution import (
    DidResolutionMethod,
    DidResolutionProvenance,
    ResolvedDidDocument,
)

PLC_OPERATION_MAX_BYTES = 7500
PLC_RECOVERY_WINDOW = timedelta(hours=72)
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_K256_PREFIX = b"\xe7\x01"
_P256_PREFIX = b"\x80\x24"
_PLC_DID = re.compile(r"^did:plc:[a-z2-7]{24}$")


def _fail(reason: str, message: str) -> None:
    raise ValidationError(reason, message)


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        _fail("spaces_plc_evidence_invalid", "directory time must be aware")
    return value.astimezone(UTC)


def _base58_decode(value: str) -> bytes:
    if not value.startswith("z"):
        _fail("spaces_plc_key_unsupported", "PLC key is not base58btc")
    integer = 0
    for character in value[1:]:
        position = _B58.find(character)
        if position < 0:
            _fail("spaces_plc_key_unsupported", "PLC key is malformed")
        integer = integer * 58 + position
    leading = len(value[1:]) - len(value[1:].lstrip("1"))
    body = (
        b""
        if integer == 0
        else integer.to_bytes((integer.bit_length() + 7) // 8, "big")
    )
    return b"\x00" * leading + body


def _rotation_key(value: object) -> tuple[str, str, bytes]:
    if not isinstance(value, str) or not value.startswith("did:key:z"):
        _fail("spaces_plc_key_unsupported", "rotation authority must be did:key")
    decoded = _base58_decode(value[len("did:key:") :])
    if decoded.startswith(_K256_PREFIX) and len(decoded) == 35:
        return value, "k256", decoded[len(_K256_PREFIX) :]
    if decoded.startswith(_P256_PREFIX) and len(decoded) == 35:
        return value, "p256", decoded[len(_P256_PREFIX) :]
    _fail("spaces_plc_key_unsupported", "rotation key must be k256 or P-256")


def _verification_key(value: str) -> None:
    if not value.startswith("did:key:z"):
        _fail("spaces_plc_operation_invalid", "verification method must be did:key")
    if len(_base58_decode(value[len("did:key:") :])) < 3:
        _fail("spaces_plc_operation_invalid", "verification did:key is malformed")


def _signature(value: object) -> bytes:
    if not isinstance(value, str) or not value or "=" in value:
        _fail("spaces_plc_signature_invalid", "signature is not unpadded base64url")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * ((4 - len(value) % 4) % 4))
    except (ValueError, base64.binascii.Error) as exc:
        raise ValidationError(
            "spaces_plc_signature_invalid", "signature is malformed"
        ) from exc
    if len(raw) != 64:
        _fail("spaces_plc_signature_invalid", "signature must be compact 64-byte ECDSA")
    return raw


def _mapping(value: object, *, reason: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        _fail(reason, "PLC value must be a map")
    return value


def _string_map(value: object, *, reason: str) -> dict[str, str]:
    source = _mapping(value, reason=reason)
    if not all(
        isinstance(key, str) and key and isinstance(item, str) and item
        for key, item in source.items()
    ):
        _fail(reason, "PLC map must contain nonempty text keys and values")
    return dict(source)  # type: ignore[arg-type]


def _string_list(value: object, *, reason: str) -> tuple[str, ...]:
    if not isinstance(value, tuple | list) or not all(
        isinstance(item, str) and item for item in value
    ):
        _fail(reason, "PLC list must contain nonempty text")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class PlcAuditEntry:
    operation_bytes: bytes
    claimed_cid: str
    directory_created_at: datetime
    directory_nullified: bool

    def __post_init__(self) -> None:
        if not isinstance(self.operation_bytes, bytes) or not self.operation_bytes:
            _fail("spaces_plc_evidence_invalid", "operation bytes are required")
        if len(self.operation_bytes) > PLC_OPERATION_MAX_BYTES:
            _fail("spaces_plc_operation_oversized", "PLC operation exceeds 7500 bytes")
        object.__setattr__(
            self, "directory_created_at", _utc(self.directory_created_at)
        )
        if not isinstance(self.directory_nullified, bool):
            _fail("spaces_plc_evidence_invalid", "nullified marker must be boolean")


@dataclass(frozen=True, slots=True)
class PlcHistoryEvidence:
    expected_did: str
    entries: tuple[PlcAuditEntry, ...]
    acquisition_ref: str
    current_document_bytes: bytes | None = None

    def __post_init__(self) -> None:
        if not _PLC_DID.fullmatch(self.expected_did):
            _fail("spaces_plc_evidence_invalid", "expected PLC DID is malformed")
        if not self.entries:
            _fail("spaces_plc_evidence_incomplete", "PLC audit is empty")
        if not self.acquisition_ref:
            _fail("spaces_plc_evidence_invalid", "acquisition reference is required")


@dataclass(frozen=True, slots=True)
class PlcAuthorizedOperation:
    cid: str
    prev: str | None
    signer: str
    signer_curve: str
    supplied_ordinal: int
    directory_created_at: datetime


@dataclass(frozen=True, slots=True)
class PlcResolutionReceipt:
    receipt_id: str
    expected_did: str
    acquisition_ref: str
    supplied_operation_cids: tuple[str, ...]
    active_operation_cids: tuple[str, ...]
    nullified_operation_cids: tuple[str, ...]
    authorized_operations: tuple[PlcAuthorizedOperation, ...]
    final_document_sha256: str | None
    deactivated: bool
    used_recovery: bool
    used_legacy_genesis: bool
    used_p256_rotation: bool
    evaluated_at: datetime
    verified_claims: frozenset[str]
    method: DidResolutionMethod = field(default=DidResolutionMethod.PLC, init=False)
    method_version: str = field(default=SA9C_PLC_VERSION, init=False)
    plc_spec_version: str = field(default=SA9C_PLC_SPEC_VERSION, init=False)
    reference_commit: str = field(default=SA9C_PLC_REFERENCE_COMMIT, init=False)
    doctrine: str = field(default=SA9C_RESOLUTION_DOCTRINE, init=False)
    authority_doctrine: str = field(default=SA9C_AUTHORITY_DOCTRINE, init=False)
    directory_timestamps_controller_authenticated: bool = False
    complete_history: bool = False
    directory_honest: bool = False
    globally_current: bool = False
    governance_authority: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluated_at", _utc(self.evaluated_at))
        if (
            _plc_receipt_id(
                expected_did=self.expected_did,
                acquisition_ref=self.acquisition_ref,
                supplied_operation_cids=self.supplied_operation_cids,
                active_operation_cids=self.active_operation_cids,
                nullified_operation_cids=self.nullified_operation_cids,
                authorized_operations=self.authorized_operations,
                final_document_sha256=self.final_document_sha256,
                used_recovery=self.used_recovery,
                used_legacy_genesis=self.used_legacy_genesis,
                used_p256_rotation=self.used_p256_rotation,
                evaluated_at=self.evaluated_at,
                verified_claims=self.verified_claims,
            )
            != self.receipt_id
        ):
            _fail("spaces_plc_receipt_invalid", "PLC receipt is not bound")
        if self.deactivated != (self.final_document_sha256 is None):
            _fail("spaces_plc_receipt_invalid", "deactivation/document state conflicts")
        expected_claims = {
            "plc_identifier_matches_genesis",
            "operation_cids_verified",
            "prev_relationships_verified",
            "rotation_signatures_verified",
            "active_state_derived",
            "directory_nullification_flags_checked",
            (
                "active_state_deactivated_by_tombstone"
                if self.deactivated
                else "exact_document_digest"
            ),
        }
        conditional = (
            (self.used_recovery, "recovery_rules_applied_with_directory_time_context"),
            (self.used_legacy_genesis, "legacy_create_genesis_normalized"),
            (self.used_p256_rotation, "p256_rotation_signature_verified"),
        )
        expected_claims.update(claim for applies, claim in conditional if applies)
        if self.verified_claims != frozenset(expected_claims):
            _fail("spaces_plc_receipt_invalid", "PLC claim set is invalid")
        if any(
            (
                self.directory_timestamps_controller_authenticated,
                self.complete_history,
                self.directory_honest,
                self.globally_current,
                self.governance_authority,
            )
        ):
            _fail("spaces_plc_receipt_invalid", "PLC receipt overclaims")


@dataclass(frozen=True, slots=True)
class PlcQualification:
    receipt: PlcResolutionReceipt
    resolved_document: ResolvedDidDocument | None

    def __post_init__(self) -> None:
        if self.receipt.deactivated != (self.resolved_document is None):
            _fail("spaces_plc_receipt_invalid", "PLC result is inconsistent")
        if self.resolved_document is not None and (
            self.resolved_document.method is not DidResolutionMethod.PLC
            or self.resolved_document.method_receipt_id != self.receipt.receipt_id
            or self.resolved_document.document_sha256
            != self.receipt.final_document_sha256
        ):
            _fail("spaces_plc_receipt_invalid", "resolved PLC document is not bound")


@dataclass(slots=True)
class _State:
    verification_methods: dict[str, str]
    rotation_keys: tuple[str, ...]
    also_known_as: tuple[str, ...]
    services: dict[str, dict[str, str]]


@dataclass(slots=True)
class _Node:
    entry: PlcAuditEntry
    supplied_ordinal: int
    operation: Mapping[str, object]
    cid: str
    prev: str | None
    state: _State | None = None
    signer: str = ""
    signer_curve: str = ""


def _operation(entry: PlcAuditEntry) -> Mapping[str, object]:
    try:
        value = decode_dag_cbor(entry.operation_bytes)
    except ValidationError as exc:
        raise ValidationError(
            "spaces_plc_operation_invalid", "operation DAG-CBOR is invalid"
        ) from exc
    if encode_dag_cbor(value) != entry.operation_bytes:
        _fail("spaces_plc_operation_invalid", "operation DAG-CBOR is not canonical")
    operation = _mapping(value, reason="spaces_plc_operation_invalid")
    if cid_for_dag_cbor(entry.operation_bytes) != entry.claimed_cid:
        _fail("spaces_plc_operation_cid_mismatch", "operation CID does not match bytes")
    return operation


def _shape(operation: Mapping[str, object], *, genesis: bool) -> tuple[str, str | None]:
    kind = operation.get("type")
    if kind == "plc_operation":
        required = {
            "type",
            "rotationKeys",
            "verificationMethods",
            "alsoKnownAs",
            "services",
            "prev",
            "sig",
        }
    elif kind == "create" and genesis:
        required = {
            "type",
            "signingKey",
            "recoveryKey",
            "handle",
            "service",
            "prev",
            "sig",
        }
    elif kind == "plc_tombstone" and not genesis:
        required = {"type", "prev", "sig"}
    else:
        _fail("spaces_plc_operation_invalid", "operation type is unsupported here")
    if set(operation) != required:
        _fail(
            "spaces_plc_operation_invalid", "operation fields do not match PLC schema"
        )
    prev = operation.get("prev")
    if prev is not None and not isinstance(prev, str):
        _fail("spaces_plc_operation_invalid", "prev must be a CID string or null")
    if genesis != (prev is None):
        _fail("spaces_plc_operation_invalid", "genesis/prev relationship is invalid")
    _signature(operation.get("sig"))
    return str(kind), prev


def _state(operation: Mapping[str, object]) -> _State | None:
    if operation["type"] == "plc_tombstone":
        return None
    if operation["type"] == "create":
        if not all(
            isinstance(operation[name], str) and operation[name]
            for name in ("signingKey", "recoveryKey", "handle", "service")
        ):
            _fail("spaces_plc_operation_invalid", "legacy create fields are invalid")
        verification = {"atproto": str(operation["signingKey"])}
        rotations = (str(operation["recoveryKey"]), str(operation["signingKey"]))
        handle = str(operation["handle"])
        handle = handle.replace("http://", "").replace("https://", "")
        aliases = (handle if handle.startswith("at://") else f"at://{handle}",)
        service = str(operation["service"])
        if not service.startswith(("http://", "https://")):
            service = "https://" + service
        services = {
            "atproto_pds": {
                "type": "AtprotoPersonalDataServer",
                "endpoint": service,
            }
        }
    else:
        verification = _string_map(
            operation["verificationMethods"], reason="spaces_plc_operation_invalid"
        )
        rotations = _string_list(
            operation["rotationKeys"], reason="spaces_plc_operation_invalid"
        )
        aliases = _string_list(
            operation["alsoKnownAs"], reason="spaces_plc_operation_invalid"
        )
        raw_services = _mapping(
            operation["services"], reason="spaces_plc_operation_invalid"
        )
        services = {}
        for service_id, raw in raw_services.items():
            if not isinstance(service_id, str) or not service_id:
                _fail("spaces_plc_operation_invalid", "service id is invalid")
            item = _mapping(raw, reason="spaces_plc_operation_invalid")
            if set(item) != {"type", "endpoint"} or not all(
                isinstance(item[key], str) and item[key] for key in ("type", "endpoint")
            ):
                _fail("spaces_plc_operation_invalid", "service entry is invalid")
            services[service_id] = {
                "type": str(item["type"]),
                "endpoint": str(item["endpoint"]),
            }
    if not 1 <= len(rotations) <= 5 or len(set(rotations)) != len(rotations):
        _fail("spaces_plc_operation_invalid", "rotation keys must be 1..5 unique keys")
    for key in rotations:
        _rotation_key(key)
    if len(verification) > 10 or len(services) > 10:
        _fail("spaces_plc_operation_invalid", "PLC state exceeds method limits")
    for value in verification.values():
        _verification_key(value)
    return _State(verification, rotations, aliases, services)


def _unsigned_bytes(operation: Mapping[str, object]) -> bytes:
    return encode_dag_cbor(
        {key: value for key, value in operation.items() if key != "sig"}
    )


def _authorized_signer(
    operation: Mapping[str, object], allowed: tuple[str, ...]
) -> tuple[str, str]:
    signature = _signature(operation["sig"])
    message = _unsigned_bytes(operation)
    for did_key in allowed:
        _, curve, public_key = _rotation_key(did_key)
        valid = (
            verify_es256k(public_key, message, signature)
            if curve == "k256"
            else verify_es256(public_key, message, signature)
        )
        if valid:
            return did_key, curve
    _fail(
        "spaces_plc_unauthorized_signer",
        "operation signature is not from an authorized rotation key",
    )


def _did_from_genesis(operation_bytes: bytes) -> str:
    encoded = (
        base64.b32encode(hashlib.sha256(operation_bytes).digest())
        .decode("ascii")
        .lower()
        .rstrip("=")
    )
    return "did:plc:" + encoded[:24]


def _render_document(did: str, state: _State) -> bytes:
    context = ["https://www.w3.org/ns/did/v1", "https://w3id.org/security/multikey/v1"]
    methods: list[dict[str, str]] = []
    for name, did_key in state.verification_methods.items():
        try:
            _, curve, _ = _rotation_key(did_key)
        except ValidationError:
            curve = "unknown"
        curve_context = {
            "k256": "https://w3id.org/security/suites/secp256k1-2019/v1",
            "p256": "https://w3id.org/security/suites/ecdsa-2019/v1",
        }.get(curve)
        if curve_context and curve_context not in context:
            context.append(curve_context)
        methods.append(
            {
                "id": f"{did}#{name}",
                "type": "Multikey",
                "controller": did,
                "publicKeyMultibase": did_key.removeprefix("did:key:"),
            }
        )
    services = [
        {"id": f"#{name}", "type": item["type"], "serviceEndpoint": item["endpoint"]}
        for name, item in state.services.items()
    ]
    document = {
        "@context": context,
        "id": did,
        "alsoKnownAs": list(state.also_known_as),
        "verificationMethod": methods,
        "service": services,
    }
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def _strict_json(value: bytes) -> object:
    class Duplicate(ValueError):
        pass

    def hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise Duplicate(key)
            result[key] = item
        return result

    try:
        return json.loads(value.decode("utf-8"), object_pairs_hook=hook)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValidationError(
            "spaces_plc_current_document_invalid", "directory summary is invalid JSON"
        ) from exc


def _plc_receipt_id(
    *,
    expected_did: str,
    acquisition_ref: str,
    supplied_operation_cids: tuple[str, ...],
    active_operation_cids: tuple[str, ...],
    nullified_operation_cids: tuple[str, ...],
    authorized_operations: tuple[PlcAuthorizedOperation, ...],
    final_document_sha256: str | None,
    used_recovery: bool,
    used_legacy_genesis: bool,
    used_p256_rotation: bool,
    evaluated_at: datetime,
    verified_claims: frozenset[str],
    **_ignored: object,
) -> str:
    fields = (
        "spaces-plc-resolution-receipt-v1",
        SA9C_PLC_METHOD,
        SA9C_PLC_VERSION,
        expected_did,
        acquisition_ref,
        *supplied_operation_cids,
        "active",
        *active_operation_cids,
        "nullified",
        *nullified_operation_cids,
        final_document_sha256 or "deactivated",
        str(used_recovery),
        str(used_legacy_genesis),
        str(used_p256_rotation),
        evaluated_at.isoformat(),
        *(sorted(verified_claims)),
        *(
            f"{item.cid}:{item.prev}:{item.signer}:{item.signer_curve}:{item.supplied_ordinal}:{item.directory_created_at.isoformat()}"
            for item in authorized_operations
        ),
    )
    return "sha256:" + hashlib.sha256("\x00".join(fields).encode()).hexdigest()


def qualify_plc_history(
    evidence: PlcHistoryEvidence, *, evaluated_at: datetime
) -> PlcQualification:
    """Derive one active state from supplied audit evidence under PLC v0.3.0."""

    nodes = [
        _Node(entry, ordinal, _operation(entry), entry.claimed_cid, None)
        for ordinal, entry in enumerate(evidence.entries)
    ]
    if len({node.cid for node in nodes}) != len(nodes):
        _fail("spaces_plc_evidence_invalid", "duplicate operation CID is ambiguous")
    times = [node.entry.directory_created_at for node in nodes]
    if len(set(times)) != len(times):
        _fail(
            "spaces_plc_timing_ambiguous",
            "directory operation times are not ordered uniquely",
        )
    ordered = sorted(nodes, key=lambda node: node.entry.directory_created_at)
    active: list[_Node] = []
    computed_nullified: set[str] = set()
    used_recovery = False
    used_legacy = False
    used_p256 = False
    for position, node in enumerate(ordered):
        kind, prev = _shape(node.operation, genesis=(position == 0))
        node.prev = prev
        state = _state(node.operation)
        if position == 0:
            if _did_from_genesis(node.entry.operation_bytes) != evidence.expected_did:
                _fail(
                    "spaces_plc_genesis_did_mismatch",
                    "PLC DID does not match signed genesis",
                )
            assert state is not None
            signer, curve = _authorized_signer(node.operation, state.rotation_keys)
            node.signer, node.signer_curve, node.state = signer, curve, state
            active.append(node)
            used_legacy = kind == "create"
            used_p256 = curve == "p256"
            continue
        parent_index = next(
            (index for index, item in enumerate(active) if item.cid == prev), -1
        )
        if parent_index < 0:
            _fail(
                "spaces_plc_prev_unqualified",
                "prev is absent from the active qualified history",
            )
        parent = active[parent_index]
        if parent.state is None:
            _fail(
                "spaces_plc_tombstone_bypass", "an operation cannot extend a tombstone"
            )
        suffix = active[parent_index + 1 :]
        if not suffix:
            signer, curve = _authorized_signer(
                node.operation, parent.state.rotation_keys
            )
        else:
            disputed = suffix[0]
            disputed_index = parent.state.rotation_keys.index(disputed.signer)
            stronger = parent.state.rotation_keys[:disputed_index]
            if not stronger:
                _fail(
                    "spaces_plc_recovery_priority",
                    "no higher-priority recovery key exists",
                )
            signer, curve = _authorized_signer(node.operation, stronger)
            if (
                node.entry.directory_created_at - disputed.entry.directory_created_at
                > PLC_RECOVERY_WINDOW
            ):
                _fail(
                    "spaces_plc_recovery_window",
                    "recovery exceeds directory-time window",
                )
            computed_nullified.update(item.cid for item in suffix)
            active = active[: parent_index + 1]
            used_recovery = True
        node.signer, node.signer_curve, node.state = signer, curve, state
        used_p256 = used_p256 or curve == "p256"
        active.append(node)
    supplied_nullified = {node.cid for node in nodes if node.entry.directory_nullified}
    if supplied_nullified != computed_nullified:
        _fail(
            "spaces_plc_nullification_mismatch",
            "directory nullification flags disagree with qualified recovery",
        )
    final = active[-1]
    document_bytes = (
        None
        if final.state is None
        else _render_document(evidence.expected_did, final.state)
    )
    if evidence.current_document_bytes is not None:
        if document_bytes is None or _strict_json(
            evidence.current_document_bytes
        ) != _strict_json(document_bytes):
            _fail(
                "spaces_plc_current_document_disagreement",
                "directory current document disagrees with qualified history",
            )
    claims = {
        "plc_identifier_matches_genesis",
        "operation_cids_verified",
        "prev_relationships_verified",
        "rotation_signatures_verified",
        "active_state_derived",
        "directory_nullification_flags_checked",
    }
    if used_recovery:
        claims.add("recovery_rules_applied_with_directory_time_context")
    if used_legacy:
        claims.add("legacy_create_genesis_normalized")
    if used_p256:
        claims.add("p256_rotation_signature_verified")
    if document_bytes is None:
        claims.add("active_state_deactivated_by_tombstone")
    else:
        claims.add("exact_document_digest")
    authorized = tuple(
        PlcAuthorizedOperation(
            node.cid,
            node.prev,
            node.signer,
            node.signer_curve,
            node.supplied_ordinal,
            node.entry.directory_created_at,
        )
        for node in ordered
    )
    receipt_fields = {
        "expected_did": evidence.expected_did,
        "acquisition_ref": evidence.acquisition_ref,
        "supplied_operation_cids": tuple(node.cid for node in nodes),
        "active_operation_cids": tuple(node.cid for node in active),
        "nullified_operation_cids": tuple(
            node.cid for node in ordered if node.cid in computed_nullified
        ),
        "authorized_operations": authorized,
        "final_document_sha256": hashlib.sha256(document_bytes).hexdigest()
        if document_bytes is not None
        else None,
        "deactivated": document_bytes is None,
        "used_recovery": used_recovery,
        "used_legacy_genesis": used_legacy,
        "used_p256_rotation": used_p256,
        "evaluated_at": _utc(evaluated_at),
        "verified_claims": frozenset(claims),
    }
    receipt = PlcResolutionReceipt(
        receipt_id=_plc_receipt_id(**receipt_fields), **receipt_fields
    )
    resolved = None
    if document_bytes is not None:
        resolved = ResolvedDidDocument(
            expected_did=evidence.expected_did,
            document_bytes=document_bytes,
            document_sha256=receipt.final_document_sha256 or "",
            method=DidResolutionMethod.PLC,
            method_receipt_id=receipt.receipt_id,
            provenance=DidResolutionProvenance.PLC_OPERATION_HISTORY,
            verified_claims=receipt.verified_claims,
            observed_at=receipt.evaluated_at,
        )
    return PlcQualification(receipt, resolved)


__all__ = [
    "PLC_OPERATION_MAX_BYTES",
    "PLC_RECOVERY_WINDOW",
    "PlcAuditEntry",
    "PlcAuthorizedOperation",
    "PlcHistoryEvidence",
    "PlcQualification",
    "PlcResolutionReceipt",
    "qualify_plc_history",
]
