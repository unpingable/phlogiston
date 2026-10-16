"""Deeply immutable value contracts shared across the three distributions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Generic, TypeVar

from .constants import (
    CurrentRecordStatus,
    DeliveryTrustMode,
    PayloadHashScope,
    RepositoryOperation,
    ResolutionStatus,
    ResolverTrustMode,
    VerificationOutcome,
)
from .errors import ValidationError
from .identifiers import (
    format_rfc3339,
    normalize_commit_identity,
    parse_at_uri,
    validate_cid,
    validate_did,
    validate_nsid,
    validate_rkey,
    validate_tid,
)
from .immutable import deep_freeze

T = TypeVar("T")


def _utc(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValidationError(
            "datetime_invalid", f"{field} must be a timezone-aware datetime"
        )
    return value.astimezone(UTC)


def _enum(enum_type: type[T], value: object, *, field: str) -> T:
    try:
        return enum_type(value)  # type: ignore[call-arg,return-value]
    except (TypeError, ValueError) as exc:
        raise ValidationError("schema_invalid", f"unsupported {field}") from exc


def _optional_hash(value: str | None) -> str | None:
    if value is None:
        return None
    from .canonical import validate_sha256

    return validate_sha256(value)


def _optional_text(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValidationError(
            "schema_invalid", f"{field} must be a nonempty NUL-free string"
        )
    return value


def _required_text(value: object, *, field: str) -> str:
    validated = _optional_text(value, field=field)
    if validated is None:
        raise ValidationError("schema_invalid", f"{field} is required")
    return validated


def _same_frozen_data(left: object, right: object) -> bool:
    """Compare decoded evidence without Python's bool/int equality collapse."""

    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return left.keys() == right.keys() and all(
            _same_frozen_data(left[key], right[key]) for key in left
        )
    if isinstance(left, tuple) and isinstance(right, tuple):
        return len(left) == len(right) and all(
            _same_frozen_data(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return type(left) is type(right) and left == right


@dataclass(frozen=True, slots=True)
class RecordRef:
    uri: str
    cid: str

    def __post_init__(self) -> None:
        parse_at_uri(self.uri, path=("uri",))
        validate_cid(self.cid, require_dag_cbor=True, path=("cid",))

    @property
    def repo_did(self) -> str:
        return parse_at_uri(self.uri).authority

    @property
    def collection(self) -> str:
        return parse_at_uri(self.uri).collection

    @property
    def rkey(self) -> str:
        return parse_at_uri(self.uri).rkey

    def as_dict(self) -> dict[str, str]:
        return {"uri": self.uri, "cid": self.cid}

    @classmethod
    def from_mapping(
        cls, value: object, *, path: tuple[str | int, ...] = ()
    ) -> RecordRef:
        if not isinstance(value, Mapping):
            raise ValidationError(
                "schema_invalid", "strong reference must be an object", path=path
            )
        unknown = set(value) - {"uri", "cid"}
        missing = {"uri", "cid"} - set(value)
        if missing or unknown:
            raise ValidationError(
                "schema_invalid",
                "strong reference requires exactly uri and cid",
                path=path,
            )
        try:
            return cls(uri=value["uri"], cid=value["cid"])  # type: ignore[arg-type]
        except ValidationError as exc:
            raise ValidationError(
                exc.reason_code, exc.issue.message, path=path + exc.path
            ) from exc


@dataclass(frozen=True, slots=True)
class ImmutableCreateOutcome:
    """Result of one create-only authority write at a deterministic rkey.

    ``created`` is True only when this operation committed the record —
    including an ambiguity-resolving readback after the pre-create check
    found the rkey absent (a compatible occupant then is our own dropped
    commit); it is False when a compatible record already held the rkey
    before this operation ran.
    """

    reference: RecordRef
    created: bool

    def __post_init__(self) -> None:
        if not isinstance(self.reference, RecordRef):
            raise ValidationError(
                "schema_invalid", "reference must be an exact record reference"
            )
        if not isinstance(self.created, bool):
            raise ValidationError("schema_invalid", "created must be a boolean")


@dataclass(frozen=True, slots=True)
class IncomingDelivery:
    source: str
    cursor: str
    source_event_time: datetime | None
    received_at: datetime
    raw_envelope: bytes | Mapping[str, object]
    trust_mode: DeliveryTrustMode | str
    verification_outcome: VerificationOutcome | str
    verification_method: str
    verifier_version: str
    evidence_ref: str | None = None
    evidence_hash: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "source",
            "cursor",
            "verification_method",
            "verifier_version",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or "\x00" in value:
                raise ValidationError(
                    "schema_invalid", f"{field_name} must be a nonempty NUL-free string"
                )
        if self.source_event_time is not None:
            object.__setattr__(
                self,
                "source_event_time",
                _utc(self.source_event_time, field="source_event_time"),
            )
        object.__setattr__(
            self, "received_at", _utc(self.received_at, field="received_at")
        )
        if isinstance(self.raw_envelope, bytes | bytearray | memoryview):
            frozen_envelope: object = bytes(self.raw_envelope)
        elif isinstance(self.raw_envelope, Mapping):
            frozen_envelope = deep_freeze(self.raw_envelope)
        else:
            raise ValidationError(
                "schema_invalid", "raw_envelope must be bytes or a mapping"
            )
        object.__setattr__(self, "raw_envelope", frozen_envelope)
        object.__setattr__(
            self,
            "trust_mode",
            _enum(DeliveryTrustMode, self.trust_mode, field="delivery trust mode"),
        )
        object.__setattr__(
            self,
            "verification_outcome",
            _enum(
                VerificationOutcome,
                self.verification_outcome,
                field="verification outcome",
            ),
        )
        object.__setattr__(
            self,
            "evidence_ref",
            _optional_text(self.evidence_ref, field="evidence_ref"),
        )
        object.__setattr__(self, "evidence_hash", _optional_hash(self.evidence_hash))


@dataclass(frozen=True, slots=True)
class RepoEvent:
    semantic_event_key: str
    event_variant_key: str
    commit_identity: str
    repo_order: str
    repo_did: str
    operation: RepositoryOperation | str
    collection: str
    rkey: str
    record_uri: str
    record_cid: str | None
    commit_rev: str
    commit_cid: str | None
    record: Mapping[str, object] | None
    record_bytes: bytes | None
    payload_hash: str
    payload_hash_scope: PayloadHashScope | str

    def __post_init__(self) -> None:
        from .canonical import (
            cid_for_dag_cbor,
            event_variant_key,
            payload_hash,
            semantic_event_key,
            validate_sha256,
        )

        validate_sha256(self.semantic_event_key)
        validate_sha256(self.event_variant_key)
        validate_did(self.repo_did)
        validate_tid(self.commit_rev)
        if self.commit_identity != normalize_commit_identity(self.commit_rev):
            raise ValidationError(
                "commit_revision_invalid", "commit identity and revision disagree"
            )
        if self.repo_order != self.commit_rev:
            raise ValidationError(
                "commit_revision_invalid",
                "repo_order must be the validated raw revision",
            )
        validate_nsid(self.collection)
        validate_rkey(self.rkey)
        parsed_uri = parse_at_uri(self.record_uri)
        if (
            parsed_uri.authority != self.repo_did
            or parsed_uri.collection != self.collection
            or parsed_uri.rkey != self.rkey
        ):
            raise ValidationError(
                "repo_mismatch", "record URI does not match its repository envelope"
            )
        operation = _enum(RepositoryOperation, self.operation, field="operation")
        object.__setattr__(self, "operation", operation)
        scope = _enum(
            PayloadHashScope, self.payload_hash_scope, field="payload hash scope"
        )
        object.__setattr__(self, "payload_hash_scope", scope)
        if self.record is not None and not isinstance(self.record, Mapping):
            raise ValidationError("schema_invalid", "record must be a mapping")
        if self.record_bytes is not None and not isinstance(
            self.record_bytes, bytes | bytearray | memoryview
        ):
            raise ValidationError(
                "schema_invalid", "record_bytes must be bytes-like evidence"
            )
        if operation is RepositoryOperation.DELETE:
            if (
                self.record_cid is not None
                or self.record is not None
                or self.record_bytes is not None
            ):
                raise ValidationError(
                    "schema_invalid", "delete events may not manufacture record content"
                )
            if scope is not PayloadHashScope.DELETE_ENVELOPE_V0:
                raise ValidationError(
                    "payload_evidence_invalid",
                    "delete events require delete_envelope_v0 evidence",
                )
        else:
            if self.record_cid is None or self.record is None:
                raise ValidationError(
                    "schema_invalid",
                    "create/update events require exact record content",
                )
            validate_cid(self.record_cid, require_dag_cbor=True)
            if scope is PayloadHashScope.DELETE_ENVELOPE_V0:
                raise ValidationError(
                    "payload_evidence_invalid",
                    "record events cannot use delete-envelope evidence",
                )
        if self.commit_cid is not None:
            validate_cid(self.commit_cid, require_dag_cbor=True)
        if self.record is not None:
            object.__setattr__(self, "record", deep_freeze(self.record))
        if self.record_bytes is not None:
            object.__setattr__(self, "record_bytes", bytes(self.record_bytes))
        validate_sha256(self.payload_hash)

        expected_semantic_key = semantic_event_key(
            repo_did=self.repo_did,
            commit_identity=self.commit_identity,
            collection=self.collection,
            rkey=self.rkey,
            operation=operation,
        )
        if self.semantic_event_key != expected_semantic_key:
            raise ValidationError(
                "payload_evidence_invalid",
                "semantic event key does not match its fields",
            )

        if scope is PayloadHashScope.DAG_CBOR:
            if self.record_bytes is None or self.record_cid is None:
                raise ValidationError(
                    "payload_evidence_invalid",
                    "dag_cbor scope requires exact record bytes and CID",
                )
            expected_payload_hash = payload_hash(scope, self.record_bytes)
            if cid_for_dag_cbor(self.record_bytes) != self.record_cid:
                raise ValidationError(
                    "payload_evidence_invalid",
                    "DAG-CBOR bytes do not match record CID",
                )
            from .dag_cbor import decode_dag_cbor

            decoded_record = decode_dag_cbor(self.record_bytes)
            if not isinstance(decoded_record, Mapping) or not _same_frozen_data(
                deep_freeze(decoded_record), self.record
            ):
                raise ValidationError(
                    "payload_evidence_invalid",
                    "DAG-CBOR bytes do not encode the supplied record",
                )
        elif scope is PayloadHashScope.OBSERVER_JSON_V0:
            assert self.record is not None
            expected_payload_hash = payload_hash(scope, self.record)
        else:
            expected_payload_hash = payload_hash(
                scope,
                {
                    "collection": self.collection,
                    "commitIdentity": self.commit_identity,
                    "operation": operation.value,
                    "repoDid": self.repo_did,
                    "rkey": self.rkey,
                },
            )
        if self.payload_hash != expected_payload_hash:
            raise ValidationError(
                "payload_evidence_invalid",
                "payload hash does not match its scoped evidence",
            )

        expected_variant_key = event_variant_key(
            semantic_event_key=self.semantic_event_key,
            record_cid=self.record_cid,
            payload_hash_scope=scope,
            payload_hash=self.payload_hash,
        )
        if self.event_variant_key != expected_variant_key:
            raise ValidationError(
                "payload_evidence_invalid",
                "event variant key does not match its fields",
            )


@dataclass(frozen=True, slots=True)
class EventReceipt:
    event_variant_key: str
    source: str
    cursor: str
    source_event_time: datetime | None
    received_at: datetime
    observer_sequence: int
    trust_mode: DeliveryTrustMode | str
    verification_outcome: VerificationOutcome | str
    verification_method: str
    verifier_version: str
    evidence_ref: str | None = None
    evidence_hash: str | None = None

    def __post_init__(self) -> None:
        from .canonical import validate_sha256

        validate_sha256(self.event_variant_key)
        for field_name in (
            "source",
            "cursor",
            "verification_method",
            "verifier_version",
        ):
            _required_text(getattr(self, field_name), field=field_name)
        if (
            isinstance(self.observer_sequence, bool)
            or not isinstance(self.observer_sequence, int)
            or self.observer_sequence < 1
        ):
            raise ValidationError(
                "schema_invalid",
                "observer_sequence must be a positive local coordinate",
            )
        if self.source_event_time is not None:
            object.__setattr__(
                self,
                "source_event_time",
                _utc(self.source_event_time, field="source_event_time"),
            )
        object.__setattr__(
            self, "received_at", _utc(self.received_at, field="received_at")
        )
        object.__setattr__(
            self,
            "trust_mode",
            _enum(DeliveryTrustMode, self.trust_mode, field="delivery trust mode"),
        )
        object.__setattr__(
            self,
            "verification_outcome",
            _enum(
                VerificationOutcome,
                self.verification_outcome,
                field="verification outcome",
            ),
        )
        object.__setattr__(
            self,
            "evidence_ref",
            _optional_text(self.evidence_ref, field="evidence_ref"),
        )
        object.__setattr__(self, "evidence_hash", _optional_hash(self.evidence_hash))


@dataclass(frozen=True, slots=True)
class ResolveResult:
    status: ResolutionStatus | str
    requested: RecordRef
    current_cid: str | None
    record: Mapping[str, object] | None
    checked_at: datetime
    trust_mode: ResolverTrustMode | str
    verification_outcome: VerificationOutcome | str
    resolution_method: str
    resolver_version: str
    evidence_ref: str | None = None
    evidence_hash: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.requested, RecordRef):
            raise ValidationError(
                "schema_invalid", "requested must be an exact record reference"
            )
        if self.record is not None and not isinstance(self.record, Mapping):
            raise ValidationError("schema_invalid", "record must be a mapping")
        status = _enum(ResolutionStatus, self.status, field="resolution status")
        object.__setattr__(self, "status", status)
        _required_text(self.resolution_method, field="resolution_method")
        _required_text(self.resolver_version, field="resolver_version")
        object.__setattr__(
            self, "checked_at", _utc(self.checked_at, field="checked_at")
        )
        object.__setattr__(
            self,
            "trust_mode",
            _enum(ResolverTrustMode, self.trust_mode, field="resolver trust mode"),
        )
        object.__setattr__(
            self,
            "verification_outcome",
            _enum(
                VerificationOutcome,
                self.verification_outcome,
                field="verification outcome",
            ),
        )
        if status is ResolutionStatus.EXACT:
            if self.current_cid != self.requested.cid or self.record is None:
                raise ValidationError(
                    "strong_ref_mismatch", "exact result must contain the requested CID"
                )
        elif status is ResolutionStatus.MISMATCH:
            if self.current_cid is None or self.current_cid == self.requested.cid:
                raise ValidationError(
                    "strong_ref_mismatch",
                    "mismatch result requires a different current CID",
                )
        elif self.current_cid is not None or self.record is not None:
            raise ValidationError(
                "schema_invalid", "missing/error results may not claim current content"
            )
        if self.current_cid is not None:
            validate_cid(self.current_cid, require_dag_cbor=True)
        if self.record is not None:
            object.__setattr__(self, "record", deep_freeze(self.record))
        object.__setattr__(
            self,
            "evidence_ref",
            _optional_text(self.evidence_ref, field="evidence_ref"),
        )
        object.__setattr__(self, "evidence_hash", _optional_hash(self.evidence_hash))


@dataclass(frozen=True, slots=True)
class CurrentRecordResult:
    status: CurrentRecordStatus | str
    uri: str
    current_cid: str | None
    record: Mapping[str, object] | None
    checked_at: datetime
    trust_mode: ResolverTrustMode | str
    verification_outcome: VerificationOutcome | str
    resolution_method: str
    resolver_version: str
    evidence_ref: str | None = None
    evidence_hash: str | None = None

    def __post_init__(self) -> None:
        if self.record is not None and not isinstance(self.record, Mapping):
            raise ValidationError("schema_invalid", "record must be a mapping")
        status = _enum(CurrentRecordStatus, self.status, field="current record status")
        object.__setattr__(self, "status", status)
        parse_at_uri(self.uri)
        object.__setattr__(
            self, "checked_at", _utc(self.checked_at, field="checked_at")
        )
        object.__setattr__(
            self,
            "trust_mode",
            _enum(ResolverTrustMode, self.trust_mode, field="resolver trust mode"),
        )
        object.__setattr__(
            self,
            "verification_outcome",
            _enum(
                VerificationOutcome,
                self.verification_outcome,
                field="verification outcome",
            ),
        )
        _required_text(self.resolution_method, field="resolution_method")
        _required_text(self.resolver_version, field="resolver_version")
        if status is CurrentRecordStatus.PRESENT:
            if self.current_cid is None or self.record is None:
                raise ValidationError(
                    "schema_invalid", "present result requires CID and record"
                )
        elif self.current_cid is not None or self.record is not None:
            raise ValidationError(
                "schema_invalid", "missing/error results may not claim current content"
            )
        if self.current_cid is not None:
            validate_cid(self.current_cid, require_dag_cbor=True)
        if self.record is not None:
            object.__setattr__(self, "record", deep_freeze(self.record))
        object.__setattr__(
            self,
            "evidence_ref",
            _optional_text(self.evidence_ref, field="evidence_ref"),
        )
        object.__setattr__(self, "evidence_hash", _optional_hash(self.evidence_hash))


@dataclass(frozen=True, slots=True)
class AuthoritySubjectState:
    subject: RecordRef
    valid_admissions: tuple[RecordRef, ...]
    valid_removals: tuple[RecordRef, ...]
    community_repo_high_water: str

    def __post_init__(self) -> None:
        if not isinstance(self.subject, RecordRef):
            raise ValidationError(
                "schema_invalid", "subject must be an exact record reference"
            )
        for field_name in ("valid_admissions", "valid_removals"):
            references = getattr(self, field_name)
            if not isinstance(references, list | tuple) or any(
                not isinstance(reference, RecordRef) for reference in references
            ):
                raise ValidationError(
                    "schema_invalid",
                    f"{field_name} must contain exact record references",
                )
        object.__setattr__(self, "valid_admissions", tuple(self.valid_admissions))
        object.__setattr__(self, "valid_removals", tuple(self.valid_removals))
        validate_tid(self.community_repo_high_water)


@dataclass(frozen=True, slots=True)
class AuthorizedAdmin:
    did: str
    effective_uid: int

    def __post_init__(self) -> None:
        validate_did(self.did)
        if (
            isinstance(self.effective_uid, bool)
            or not isinstance(self.effective_uid, int)
            or self.effective_uid < 0
        ):
            raise ValidationError("schema_invalid", "effective UID must be nonnegative")


@dataclass(frozen=True, slots=True)
class EventBatch(Generic[T]):
    items: tuple[T, ...]
    next_cursor: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.items, list | tuple):
            raise ValidationError("schema_invalid", "items must be a finite sequence")
        object.__setattr__(
            self,
            "items",
            tuple(_freeze_page_item(item) for item in self.items),
        )
        object.__setattr__(
            self,
            "next_cursor",
            _optional_text(self.next_cursor, field="next_cursor"),
        )


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    items: tuple[T, ...]
    cursor: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.items, list | tuple):
            raise ValidationError("schema_invalid", "items must be a finite sequence")
        object.__setattr__(
            self,
            "items",
            tuple(_freeze_page_item(item) for item in self.items),
        )
        object.__setattr__(
            self,
            "cursor",
            _optional_text(self.cursor, field="cursor"),
        )


def datetime_to_wire(value: datetime) -> str:
    """Public helper used by record models without accepting naive values."""

    return format_rfc3339(value)


def _freeze_page_item(item: T) -> T:
    if isinstance(item, Mapping | list | tuple | set):
        return deep_freeze(item)  # type: ignore[return-value]
    return item
