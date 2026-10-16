"""Immutable Spaces-alpha observation and governance-boundary values."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from community_model import (
    ValidationError,
    cid_for_dag_cbor,
    decode_dag_cbor,
    deep_freeze,
)
from community_model.identifiers import (
    validate_cid,
    validate_did,
    validate_nsid,
    validate_rkey,
    validate_tid,
)

from .compat import (
    ALPHA_LABEL,
    COMMIT_FORMAT,
    NOTIFICATION_ENDPOINT,
    REQUIRED_REPO_VERIFICATION_CLAIMS,
    SPACE_URI_MARKER,
    WRITER_SET_ENDPOINT,
)

if TYPE_CHECKING:
    from .qualification import SpaceObservationReceipt

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValidationError(
            "schema_invalid", f"{field} must be a nonempty NUL-free string"
        )
    return value


def _utc(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValidationError("datetime_invalid", f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _set_hash(value: object, *, field: str = "commit_hash") -> str:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        raise ValidationError(
            "schema_invalid", f"{field} must be a lowercase sha256 hex digest"
        )
    return value


def _host(value: object, *, field: str) -> str:
    text = _text(value, field=field)
    if not text.startswith("https://") or any(char.isspace() for char in text):
        raise ValidationError(
            "schema_invalid", f"{field} must be an https origin or endpoint"
        )
    return text.rstrip("/")


@dataclass(frozen=True, slots=True)
class SpaceIdentity:
    authority_did: str
    space_type: str
    skey: str

    def __post_init__(self) -> None:
        validate_did(self.authority_did)
        validate_nsid(self.space_type)
        validate_rkey(self.skey)

    @property
    def uri(self) -> str:
        return (
            f"at://{self.authority_did}/{SPACE_URI_MARKER}/"
            f"{self.space_type}/{self.skey}"
        )

    @classmethod
    def parse(cls, value: object) -> SpaceIdentity:
        if not isinstance(value, str) or not value.startswith("at://"):
            raise ValidationError("at_uri_invalid", "expected a Space at:// URI")
        if any(char in value for char in ("?", "#", "\x00")):
            raise ValidationError("at_uri_invalid", "invalid Space URI suffix")
        parts = value[5:].split("/")
        if len(parts) != 4 or parts[1] != SPACE_URI_MARKER:
            raise ValidationError(
                "at_uri_invalid",
                "expected at://<authority>/space/<spaceType>/<skey>",
            )
        return cls(authority_did=parts[0], space_type=parts[2], skey=parts[3])


@dataclass(frozen=True, slots=True)
class SpaceRecordIdentity:
    space: SpaceIdentity
    author_did: str
    collection: str
    rkey: str

    def __post_init__(self) -> None:
        if not isinstance(self.space, SpaceIdentity):
            raise ValidationError("schema_invalid", "space identity is required")
        validate_did(self.author_did)
        validate_nsid(self.collection)
        validate_rkey(self.rkey)

    @property
    def uri(self) -> str:
        return f"{self.space.uri}/{self.author_did}/{self.collection}/{self.rkey}"

    @classmethod
    def parse(cls, value: object) -> SpaceRecordIdentity:
        if not isinstance(value, str) or not value.startswith("at://"):
            raise ValidationError("at_uri_invalid", "expected a Space record URI")
        if any(char in value for char in ("?", "#", "\x00")):
            raise ValidationError("at_uri_invalid", "invalid Space record URI suffix")
        parts = value[5:].split("/")
        if len(parts) != 7 or parts[1] != SPACE_URI_MARKER:
            raise ValidationError(
                "at_uri_invalid",
                "Space record URI does not have the alpha path shape",
            )
        return cls(
            space=SpaceIdentity(parts[0], parts[2], parts[3]),
            author_did=parts[4],
            collection=parts[5],
            rkey=parts[6],
        )


@dataclass(frozen=True, slots=True)
class AccessContext:
    """Non-secret acquisition-time facts about a Space read capability.

    There is deliberately no field for the token, delegation, DPoP private
    key, or any serialized authentication header.
    """

    space: SpaceIdentity
    issuer_did: str
    user_did: str
    client_id: str
    issued_at: datetime
    expires_at: datetime
    verified_at: datetime
    access_method: str = "space-credential+dpop"

    def __post_init__(self) -> None:
        if not isinstance(self.space, SpaceIdentity):
            raise ValidationError("schema_invalid", "space identity is required")
        validate_did(self.issuer_did)
        validate_did(self.user_did)
        if self.issuer_did != self.space.authority_did:
            raise ValidationError(
                "schema_invalid", "access issuer must be the Space authority"
            )
        _text(self.client_id, field="client_id")
        _text(self.access_method, field="access_method")
        issued = _utc(self.issued_at, field="issued_at")
        expires = _utc(self.expires_at, field="expires_at")
        verified = _utc(self.verified_at, field="verified_at")
        if not issued <= verified < expires:
            raise ValidationError(
                "schema_invalid",
                "access must be valid at the recorded acquisition check",
            )
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)
        object.__setattr__(self, "verified_at", verified)


@dataclass(frozen=True, slots=True)
class WriterSetClaim:
    """Discovery testimony from ``listRepos``; never per-repo proof."""

    space: SpaceIdentity
    space_host: str
    repo_did: str
    rev: str
    commit_hash: str
    discovered_at: datetime
    source_method: str = WRITER_SET_ENDPOINT

    def __post_init__(self) -> None:
        if not isinstance(self.space, SpaceIdentity):
            raise ValidationError("schema_invalid", "space identity is required")
        object.__setattr__(
            self, "space_host", _host(self.space_host, field="space_host")
        )
        validate_did(self.repo_did)
        validate_tid(self.rev)
        _set_hash(self.commit_hash)
        object.__setattr__(
            self,
            "discovered_at",
            _utc(self.discovered_at, field="discovered_at"),
        )
        _text(self.source_method, field="source_method")


@dataclass(frozen=True, slots=True)
class RepoBinding:
    space: SpaceIdentity
    repo_did: str
    repo_host: str
    resolved_at: datetime
    resolution_method: str
    evidence_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.space, SpaceIdentity):
            raise ValidationError("schema_invalid", "space identity is required")
        validate_did(self.repo_did)
        object.__setattr__(self, "repo_host", _host(self.repo_host, field="repo_host"))
        object.__setattr__(
            self, "resolved_at", _utc(self.resolved_at, field="resolved_at")
        )
        _text(self.resolution_method, field="resolution_method")
        _text(self.evidence_ref, field="evidence_ref")


class VerificationMode(StrEnum):
    VERIFIED = "verified"
    FIXTURE = "fixture"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RepoVerification:
    """Claims made by a Spaces-specific verifier adapter.

    ``fixture`` mode is accepted only when a caller explicitly enables it and
    is never equivalent to a live cryptographic verification.
    """

    mode: VerificationMode | str
    space: SpaceIdentity
    author_did: str
    repo_host: str
    rev: str
    commit_hash: str
    verified_at: datetime
    method: str
    verifier_version: str
    author_key_ref: str
    evidence_ref: str
    claims: frozenset[str]
    qualification_receipt_ids: tuple[str, ...] = ()
    protocol_assumption: str = ALPHA_LABEL
    commit_format: int = COMMIT_FORMAT

    def __post_init__(self) -> None:
        try:
            mode = VerificationMode(self.mode)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "schema_invalid", "unsupported verification mode"
            ) from exc
        object.__setattr__(self, "mode", mode)
        if not isinstance(self.space, SpaceIdentity):
            raise ValidationError("schema_invalid", "space identity is required")
        validate_did(self.author_did)
        object.__setattr__(self, "repo_host", _host(self.repo_host, field="repo_host"))
        validate_tid(self.rev)
        _set_hash(self.commit_hash)
        object.__setattr__(
            self, "verified_at", _utc(self.verified_at, field="verified_at")
        )
        for field in (
            "method",
            "verifier_version",
            "author_key_ref",
            "evidence_ref",
            "protocol_assumption",
        ):
            _text(getattr(self, field), field=field)
        if self.commit_format != COMMIT_FORMAT:
            raise ValidationError("schema_invalid", "unsupported alpha commit format")
        if not isinstance(self.claims, frozenset) or any(
            not isinstance(claim, str) for claim in self.claims
        ):
            raise ValidationError("schema_invalid", "claims must be a frozenset")
        if not isinstance(self.qualification_receipt_ids, list | tuple) or any(
            not isinstance(receipt_id, str) or not receipt_id
            for receipt_id in self.qualification_receipt_ids
        ):
            raise ValidationError(
                "schema_invalid",
                "qualification receipt identifiers must be nonempty strings",
            )
        receipt_ids = tuple(self.qualification_receipt_ids)
        if len(receipt_ids) != len(set(receipt_ids)):
            raise ValidationError(
                "schema_invalid", "qualification receipt identifiers must be unique"
            )
        object.__setattr__(self, "qualification_receipt_ids", receipt_ids)

    @property
    def complete(self) -> bool:
        return REQUIRED_REPO_VERIFICATION_CLAIMS <= self.claims


@dataclass(frozen=True, slots=True)
class RepoRecord:
    identity: SpaceRecordIdentity
    cid: str
    record: Mapping[str, object]
    record_bytes: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.identity, SpaceRecordIdentity):
            raise ValidationError("schema_invalid", "record identity is required")
        validate_cid(self.cid, require_dag_cbor=True)
        if not isinstance(self.record, Mapping):
            raise ValidationError("schema_invalid", "record must be a mapping")
        if not isinstance(self.record_bytes, bytes):
            raise ValidationError("schema_invalid", "record_bytes must be bytes")
        if cid_for_dag_cbor(self.record_bytes) != self.cid:
            raise ValidationError("cid_invalid", "record bytes do not match the CID")
        decoded = decode_dag_cbor(self.record_bytes)
        frozen = deep_freeze(self.record)
        if deep_freeze(decoded) != frozen:
            raise ValidationError(
                "payload_evidence_invalid", "record bytes do not encode the record"
            )
        object.__setattr__(self, "record", frozen)


@dataclass(frozen=True, slots=True)
class RepoSnapshot:
    space: SpaceIdentity
    author_did: str
    repo_host: str
    rev: str
    commit_hash: str
    acquired_at: datetime
    access: AccessContext
    verification: RepoVerification
    records: tuple[RepoRecord, ...]
    qualification_receipts: tuple[SpaceObservationReceipt, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.space, SpaceIdentity):
            raise ValidationError("schema_invalid", "space identity is required")
        validate_did(self.author_did)
        object.__setattr__(self, "repo_host", _host(self.repo_host, field="repo_host"))
        validate_tid(self.rev)
        _set_hash(self.commit_hash)
        object.__setattr__(
            self, "acquired_at", _utc(self.acquired_at, field="acquired_at")
        )
        if not isinstance(self.access, AccessContext) or not isinstance(
            self.verification, RepoVerification
        ):
            raise ValidationError(
                "schema_invalid", "access and repo verification provenance are required"
            )
        if not self.access.issued_at <= self.acquired_at < self.access.expires_at:
            raise ValidationError(
                "schema_invalid",
                "repo acquisition must occur while the recorded access was valid",
            )
        if self.verification.verified_at > self.acquired_at:
            raise ValidationError(
                "schema_invalid", "repo verification cannot postdate acquisition"
            )
        if not isinstance(self.records, list | tuple) or any(
            not isinstance(record, RepoRecord) for record in self.records
        ):
            raise ValidationError("schema_invalid", "records must be RepoRecord values")
        records = tuple(self.records)
        uris = [record.identity.uri for record in records]
        if len(uris) != len(set(uris)):
            raise ValidationError("schema_invalid", "repo snapshot has duplicate paths")
        object.__setattr__(self, "records", records)
        from .qualification import SpaceObservationReceipt

        if not isinstance(self.qualification_receipts, list | tuple) or any(
            not isinstance(receipt, SpaceObservationReceipt)
            for receipt in self.qualification_receipts
        ):
            raise ValidationError(
                "schema_invalid", "qualification receipts have an invalid shape"
            )
        receipts = tuple(self.qualification_receipts)
        receipt_ids = tuple(receipt.receipt_id for receipt in receipts)
        if receipt_ids != self.verification.qualification_receipt_ids:
            raise ValidationError(
                "schema_invalid",
                "repo verification does not name its qualification receipts",
            )
        object.__setattr__(self, "qualification_receipts", receipts)


@dataclass(frozen=True, slots=True)
class SpaceNotification:
    """Best-effort advancement hint; it contains no admissible record data."""

    space: SpaceIdentity
    space_host: str
    repo_did: str
    rev: str
    commit_hash: str
    received_at: datetime
    source_method: str = NOTIFICATION_ENDPOINT

    def __post_init__(self) -> None:
        if not isinstance(self.space, SpaceIdentity):
            raise ValidationError("schema_invalid", "space identity is required")
        object.__setattr__(
            self, "space_host", _host(self.space_host, field="space_host")
        )
        validate_did(self.repo_did)
        validate_tid(self.rev)
        _set_hash(self.commit_hash)
        object.__setattr__(
            self, "received_at", _utc(self.received_at, field="received_at")
        )
        _text(self.source_method, field="source_method")


@dataclass(frozen=True, slots=True)
class SpaceObservation:
    record: RepoRecord
    writer_discovery: WriterSetClaim
    repo_binding: RepoBinding
    repo_snapshot: RepoSnapshot
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.record, RepoRecord):
            raise ValidationError("schema_invalid", "record is required")
        if not isinstance(self.writer_discovery, WriterSetClaim):
            raise ValidationError("schema_invalid", "writer discovery is required")
        if not isinstance(self.repo_binding, RepoBinding):
            raise ValidationError("schema_invalid", "repo binding is required")
        if not isinstance(self.repo_snapshot, RepoSnapshot):
            raise ValidationError("schema_invalid", "repo snapshot is required")
        object.__setattr__(
            self, "observed_at", _utc(self.observed_at, field="observed_at")
        )

    def provenance(self) -> Mapping[str, object]:
        """Render the bounded claim without token material or authority claims."""

        verification = self.repo_snapshot.verification
        return {
            "claimScope": "space-record-observation",
            "space": {
                "authorityDid": self.record.identity.space.authority_did,
                "spaceType": self.record.identity.space.space_type,
                "skey": self.record.identity.space.skey,
            },
            "record": {
                "uri": self.record.identity.uri,
                "authorDid": self.record.identity.author_did,
                "collection": self.record.identity.collection,
                "rkey": self.record.identity.rkey,
                "cid": self.record.cid,
            },
            "acquisition": {
                "spaceHost": self.writer_discovery.space_host,
                "repoHost": self.repo_snapshot.repo_host,
                "writerSetMethod": self.writer_discovery.source_method,
                "writerSetRev": self.writer_discovery.rev,
                "writerSetHash": self.writer_discovery.commit_hash,
                "repoRev": self.repo_snapshot.rev,
                "repoHash": self.repo_snapshot.commit_hash,
                "acquiredAt": self.repo_snapshot.acquired_at.isoformat(),
                "accessMethod": self.repo_snapshot.access.access_method,
                "accessIssuer": self.repo_snapshot.access.issuer_did,
                "accessUser": self.repo_snapshot.access.user_did,
                "clientId": self.repo_snapshot.access.client_id,
                "accessExpiresAt": self.repo_snapshot.access.expires_at.isoformat(),
            },
            "verification": {
                "mode": verification.mode.value,
                "method": verification.method,
                "verifierVersion": verification.verifier_version,
                "authorKeyRef": verification.author_key_ref,
                "evidenceRef": verification.evidence_ref,
                "claims": sorted(verification.claims),
                "protocolAssumption": verification.protocol_assumption,
                "commitFormat": verification.commit_format,
                "qualificationReceiptIds": list(verification.qualification_receipt_ids),
            },
            "cryptographicQualification": [
                receipt.to_provenance()
                for receipt in self.repo_snapshot.qualification_receipts
                if receipt.record_identity == self.record.identity
                and receipt.record_cid == self.record.cid
            ],
            "governanceAuthority": False,
        }


@dataclass(frozen=True, slots=True)
class EvidenceAdmission:
    """An admitted observer fact, not a community authority record."""

    observation: SpaceObservation
    admitted_at: datetime
    policy: str = "spaces-alpha-direct-repo-v1"

    def __post_init__(self) -> None:
        if not isinstance(self.observation, SpaceObservation):
            raise ValidationError("schema_invalid", "observation is required")
        object.__setattr__(
            self, "admitted_at", _utc(self.admitted_at, field="admitted_at")
        )
        _text(self.policy, field="policy")


@dataclass(frozen=True, slots=True)
class FrozenEffectAuthorization:
    """Effective collection set captured at a governed boundary.

    This value is necessary but never sufficient for an effect.  Standing and
    a per-occurrence authorization remain separate required inputs.
    """

    authorization_id: str
    space: SpaceIdentity
    effective_collections: frozenset[str]
    authorized_at: datetime
    scope: str
    declaration_evidence_ref: str
    resolved_from_dynamic_default: bool

    def __post_init__(self) -> None:
        _text(self.authorization_id, field="authorization_id")
        if not isinstance(self.space, SpaceIdentity):
            raise ValidationError("schema_invalid", "space identity is required")
        if not isinstance(self.effective_collections, frozenset) or not (
            self.effective_collections
        ):
            raise ValidationError(
                "schema_invalid", "effective collections must be a nonempty frozenset"
            )
        for collection in self.effective_collections:
            validate_nsid(collection)
        object.__setattr__(
            self, "authorized_at", _utc(self.authorized_at, field="authorized_at")
        )
        _text(self.scope, field="scope")
        _text(self.declaration_evidence_ref, field="declaration_evidence_ref")
        if not isinstance(self.resolved_from_dynamic_default, bool):
            raise ValidationError(
                "schema_invalid", "resolved_from_dynamic_default must be boolean"
            )

    def permits(self, collection: str) -> bool:
        validate_nsid(collection)
        return collection in self.effective_collections


@dataclass(frozen=True, slots=True)
class EffectPreconditionAssessment:
    """Refusal-oriented assessment which never confers effect authority."""

    preconditions_met: bool
    authority_conferred: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.authority_conferred:
            raise ValidationError(
                "schema_invalid",
                "the Spaces observation boundary cannot confer effect authority",
            )


def assess_effect_preconditions(
    admission: EvidenceAdmission,
    *,
    evidence_is_current: bool,
    standing_ref: str | None,
    occurrence_authorization_ref: str | None,
    collection_authorization: FrozenEffectAuthorization | None,
    effect_collection: str,
) -> EffectPreconditionAssessment:
    """Explain missing inputs without replacing the existing authorizer."""

    if not isinstance(admission, EvidenceAdmission):
        raise ValidationError("schema_invalid", "evidence admission is required")
    validate_nsid(effect_collection)
    reasons: list[str] = []
    if not evidence_is_current:
        reasons.append("evidence_not_current")
    if standing_ref is None:
        reasons.append("community_standing_required")
    else:
        _text(standing_ref, field="standing_ref")
    if occurrence_authorization_ref is None:
        reasons.append("occurrence_authorization_required")
    else:
        _text(
            occurrence_authorization_ref,
            field="occurrence_authorization_ref",
        )
    if collection_authorization is None:
        reasons.append("frozen_collection_authorization_required")
    else:
        if (
            collection_authorization.space
            != admission.observation.record.identity.space
        ):
            reasons.append("authorization_space_mismatch")
        if not collection_authorization.permits(effect_collection):
            reasons.append("collection_not_authorized_at_boundary")
    return EffectPreconditionAssessment(
        preconditions_met=not reasons,
        authority_conferred=False,
        reasons=tuple(reasons),
    )


__all__ = [
    "AccessContext",
    "EffectPreconditionAssessment",
    "EvidenceAdmission",
    "FrozenEffectAuthorization",
    "RepoBinding",
    "RepoRecord",
    "RepoSnapshot",
    "RepoVerification",
    "SpaceIdentity",
    "SpaceNotification",
    "SpaceObservation",
    "SpaceRecordIdentity",
    "VerificationMode",
    "WriterSetClaim",
    "assess_effect_preconditions",
]
