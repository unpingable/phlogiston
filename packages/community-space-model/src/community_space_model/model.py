"""Immutable SCV0-M1 records with exact occurrence bindings.

This module has no transport, credential, signature, storage, or authority
writer behavior. It consumes receipt identifiers produced elsewhere and does
not reinterpret those receipts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from community_model import ValidationError, canonical_json_bytes, sha256_digest
from community_model.canonical import validate_sha256
from community_model.identifiers import (
    normalize_rfc3339,
    parse_rfc3339,
    validate_cid,
    validate_did,
    validate_nsid,
    validate_rkey,
)

COMPATIBILITY_PROFILE: Final = "scv0-m1+spaces-alpha-2026-08-20"
_SPACE_URI_MARKER: Final = "space"


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValidationError(
            "schema_invalid", f"{field} must be a nonempty NUL-free string"
        )
    return value


def _receipt(value: object, *, field: str) -> str:
    try:
        return validate_sha256(value)
    except ValidationError as exc:
        raise ValidationError(
            "receipt_reference_invalid", f"{field} must be a sha256 receipt ID"
        ) from exc


def _timestamp(value: object, *, field: str) -> str:
    try:
        return normalize_rfc3339(value)
    except ValidationError as exc:
        raise ValidationError(
            "datetime_invalid", f"{field} must be an RFC 3339 instant"
        ) from exc


def _identity(kind: str, fields: object) -> str:
    return sha256_digest(
        canonical_json_bytes(
            {"kind": kind, "profile": COMPATIBILITY_PROFILE, "fields": fields}
        )
    )


@dataclass(frozen=True, slots=True)
class SpaceIdentity:
    """The alpha Space tuple; not a community or membership claim."""

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
            f"at://{self.authority_did}/{_SPACE_URI_MARKER}/"
            f"{self.space_type}/{self.skey}"
        )

    @property
    def identity_id(self) -> str:
        return _identity("space", self.uri)


@dataclass(frozen=True, slots=True)
class ExactSpaceRecordReference:
    """An exact Space record path and CID, with author separate from authority."""

    space: SpaceIdentity
    author_did: str
    collection: str
    rkey: str
    cid: str

    def __post_init__(self) -> None:
        if not isinstance(self.space, SpaceIdentity):
            raise ValidationError("space_binding_invalid", "space identity is required")
        validate_did(self.author_did)
        validate_nsid(self.collection)
        validate_rkey(self.rkey)
        validate_cid(self.cid, require_dag_cbor=True)

    @property
    def uri(self) -> str:
        return f"{self.space.uri}/{self.author_did}/{self.collection}/{self.rkey}"

    @property
    def exact_id(self) -> str:
        return _identity("exact-space-record", [self.uri, self.cid])


@dataclass(frozen=True, slots=True)
class CommunityIdentity:
    """One community actor operating in one Space; no standing semantics."""

    space: SpaceIdentity
    community_actor_did: str

    def __post_init__(self) -> None:
        if not isinstance(self.space, SpaceIdentity):
            raise ValidationError("space_binding_invalid", "space identity is required")
        validate_did(self.community_actor_did)

    @property
    def identity_id(self) -> str:
        return _identity(
            "community", [self.space.identity_id, self.community_actor_did]
        )


@dataclass(frozen=True, slots=True)
class PostReference:
    """A qualified exact author-owned source reference, never an admission."""

    record: ExactSpaceRecordReference
    source_qualification_receipt_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.record, ExactSpaceRecordReference):
            raise ValidationError(
                "source_observation_required",
                "post reference requires an exact qualified Space record",
            )
        _receipt(
            self.source_qualification_receipt_id,
            field="source_qualification_receipt_id",
        )

    @property
    def reference_id(self) -> str:
        return _identity(
            "post-reference",
            [self.record.exact_id, self.source_qualification_receipt_id],
        )


@dataclass(frozen=True, slots=True)
class Submission:
    """A candidate occurrence, not acceptance, standing, or authorization."""

    record: ExactSpaceRecordReference
    post: PostReference
    submitting_actor_did: str
    community: CommunityIdentity
    submitted_at: str
    submission_evidence_receipt_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.record, ExactSpaceRecordReference):
            raise ValidationError(
                "submission_reference_invalid", "submission record is required"
            )
        if not isinstance(self.post, PostReference):
            raise ValidationError(
                "submission_reference_invalid", "qualified post reference is required"
            )
        if not isinstance(self.community, CommunityIdentity):
            raise ValidationError(
                "community_binding_invalid", "community identity is required"
            )
        validate_did(self.submitting_actor_did)
        if self.record.author_did != self.submitting_actor_did:
            raise ValidationError(
                "author_binding_mismatch",
                "submission record must be authored by the submitting actor",
            )
        if self.post.record.author_did != self.submitting_actor_did:
            raise ValidationError(
                "author_binding_mismatch", "only the post author may self-submit"
            )
        if self.record.space != self.post.record.space:
            raise ValidationError(
                "space_binding_mismatch",
                "post and submission must belong to the same Space",
            )
        if self.record.space != self.community.space:
            raise ValidationError(
                "community_binding_mismatch",
                "submission target must use the community Space",
            )
        object.__setattr__(
            self, "submitted_at", _timestamp(self.submitted_at, field="submitted_at")
        )
        _receipt(
            self.submission_evidence_receipt_id,
            field="submission_evidence_receipt_id",
        )

    @property
    def submission_id(self) -> str:
        return _identity(
            "submission",
            [
                self.record.exact_id,
                self.post.reference_id,
                self.submitting_actor_did,
                self.community.identity_id,
                self.submitted_at,
                self.submission_evidence_receipt_id,
            ],
        )


class AuthorizedAction(StrEnum):
    ADMIT = "admit"
    REMOVE = "remove"


@dataclass(frozen=True, slots=True)
class ModeratorAuthorization:
    """One time-bounded action over one exact occurrence; never standing."""

    community: CommunityIdentity
    decision_id: str
    moderator_did: str
    action: AuthorizedAction | str
    target_occurrence_id: str
    authorization_basis_receipt_id: str
    authorized_at: str
    expires_at: str
    provenance_receipt_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.community, CommunityIdentity):
            raise ValidationError(
                "community_binding_invalid", "community identity is required"
            )
        _text(self.decision_id, field="decision_id")
        validate_did(self.moderator_did)
        try:
            action = AuthorizedAction(self.action)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "authorization_action_invalid", "unsupported authorized action"
            ) from exc
        object.__setattr__(self, "action", action)
        _receipt(self.target_occurrence_id, field="target_occurrence_id")
        _receipt(
            self.authorization_basis_receipt_id,
            field="authorization_basis_receipt_id",
        )
        _receipt(self.provenance_receipt_id, field="provenance_receipt_id")
        authorized_at = _timestamp(self.authorized_at, field="authorized_at")
        expires_at = _timestamp(self.expires_at, field="expires_at")
        if parse_rfc3339(expires_at) <= parse_rfc3339(authorized_at):
            raise ValidationError(
                "authorization_interval_invalid",
                "authorization must expire after it becomes valid",
            )
        object.__setattr__(self, "authorized_at", authorized_at)
        object.__setattr__(self, "expires_at", expires_at)

    @property
    def authorization_id(self) -> str:
        return _identity(
            "moderator-authorization",
            [
                self.community.identity_id,
                self.decision_id,
                self.moderator_did,
                self.action,
                self.target_occurrence_id,
                self.authorization_basis_receipt_id,
                self.authorized_at,
                self.expires_at,
                self.provenance_receipt_id,
            ],
        )

    def require_for(
        self,
        *,
        community: CommunityIdentity,
        action: AuthorizedAction,
        occurrence_id: str,
        occurred_at: str,
    ) -> None:
        if self.community != community:
            raise ValidationError(
                "authorization_community_mismatch",
                "authorization belongs to another community",
            )
        if self.action is not action:
            raise ValidationError(
                "authorization_action_mismatch",
                "authorization does not cover this action",
            )
        if self.target_occurrence_id != occurrence_id:
            raise ValidationError(
                "authorization_occurrence_mismatch",
                "authorization does not cover this exact occurrence",
            )
        event_time = parse_rfc3339(_timestamp(occurred_at, field="occurred_at"))
        if not (
            parse_rfc3339(self.authorized_at)
            <= event_time
            < parse_rfc3339(self.expires_at)
        ):
            raise ValidationError(
                "authorization_stale",
                "authorization is not valid at the occurrence time",
            )


@dataclass(frozen=True, slots=True)
class CommunityAdmission:
    """A community decision over an exact post; never a source mutation."""

    record: ExactSpaceRecordReference
    community: CommunityIdentity
    post: PostReference
    submission: Submission
    authorization: ModeratorAuthorization
    source_observation_receipt_id: str
    admitted_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.record, ExactSpaceRecordReference):
            raise ValidationError(
                "admission_record_invalid", "admission record is required"
            )
        if not isinstance(self.community, CommunityIdentity):
            raise ValidationError(
                "community_binding_invalid", "community identity is required"
            )
        if not isinstance(self.post, PostReference):
            raise ValidationError(
                "source_observation_required", "qualified post reference is required"
            )
        if not isinstance(self.submission, Submission):
            raise ValidationError(
                "submission_reference_invalid", "submission is required"
            )
        if not isinstance(self.authorization, ModeratorAuthorization):
            raise ValidationError(
                "authorization_required", "moderator authorization is required"
            )
        if self.record.space != self.community.space:
            raise ValidationError(
                "community_binding_mismatch",
                "admission record must use the community Space",
            )
        if self.record.author_did != self.community.community_actor_did:
            raise ValidationError(
                "community_actor_mismatch",
                "admission record must be authored by the community actor",
            )
        if self.submission.community != self.community:
            raise ValidationError(
                "community_binding_mismatch",
                "submission and admission community must match",
            )
        if self.submission.post != self.post:
            raise ValidationError(
                "post_reference_mismatch",
                "admission must bind the submission's exact post reference",
            )
        _receipt(
            self.source_observation_receipt_id,
            field="source_observation_receipt_id",
        )
        if (
            self.source_observation_receipt_id
            != self.post.source_qualification_receipt_id
        ):
            raise ValidationError(
                "source_observation_mismatch",
                "admission observation must match the qualified post reference",
            )
        admitted_at = _timestamp(self.admitted_at, field="admitted_at")
        if parse_rfc3339(admitted_at) < parse_rfc3339(self.submission.submitted_at):
            raise ValidationError(
                "admission_chronology_invalid",
                "admission cannot predate the exact submission",
            )
        self.authorization.require_for(
            community=self.community,
            action=AuthorizedAction.ADMIT,
            occurrence_id=self.submission.submission_id,
            occurred_at=admitted_at,
        )
        object.__setattr__(self, "admitted_at", admitted_at)

    @property
    def occurrence_id(self) -> str:
        return _identity(
            "admission-occurrence",
            [
                self.community.identity_id,
                self.submission.submission_id,
                self.authorization.authorization_id,
            ],
        )

    @property
    def admission_id(self) -> str:
        return _identity(
            "community-admission",
            [
                self.record.exact_id,
                self.occurrence_id,
                self.post.reference_id,
                self.source_observation_receipt_id,
                self.admitted_at,
            ],
        )


class SourceRelationship(StrEnum):
    EXACT = "exact"
    CHANGED = "changed_at_source"
    DELETED = "deleted_by_author"
    UNAVAILABLE = "unavailable"


class RenderState(StrEnum):
    INCLUDED = "included"
    HIDDEN_CHANGED = "hidden_changed"
    HIDDEN_DELETED = "hidden_deleted"
    HIDDEN_UNAVAILABLE = "hidden_unavailable"


_RENDER_RELATIONSHIPS: Final = {
    RenderState.INCLUDED: SourceRelationship.EXACT,
    RenderState.HIDDEN_CHANGED: SourceRelationship.CHANGED,
    RenderState.HIDDEN_DELETED: SourceRelationship.DELETED,
    RenderState.HIDDEN_UNAVAILABLE: SourceRelationship.UNAVAILABLE,
}


@dataclass(frozen=True, slots=True)
class ProjectionReference:
    """A display decision referring to an admission, never a source copy."""

    admission: CommunityAdmission
    render_state: RenderState | str
    current_source_relationship: SourceRelationship | str
    source_qualification_receipt_id: str
    last_qualification_check: str

    def __post_init__(self) -> None:
        if not isinstance(self.admission, CommunityAdmission):
            raise ValidationError(
                "admission_required", "projection requires a valid admission"
            )
        try:
            render_state = RenderState(self.render_state)
            relationship = SourceRelationship(self.current_source_relationship)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "projection_state_invalid", "unsupported projection state"
            ) from exc
        if _RENDER_RELATIONSHIPS[render_state] is not relationship:
            raise ValidationError(
                "projection_state_invalid",
                "render state must match the current source relationship",
            )
        _receipt(
            self.source_qualification_receipt_id,
            field="source_qualification_receipt_id",
        )
        checked = _timestamp(
            self.last_qualification_check, field="last_qualification_check"
        )
        if parse_rfc3339(checked) < parse_rfc3339(self.admission.admitted_at):
            raise ValidationError(
                "projection_chronology_invalid",
                "source qualification check cannot predate admission",
            )
        object.__setattr__(self, "render_state", render_state)
        object.__setattr__(self, "current_source_relationship", relationship)
        object.__setattr__(self, "last_qualification_check", checked)

    @property
    def projection_id(self) -> str:
        return _identity(
            "projection-reference",
            [
                self.admission.admission_id,
                self.render_state,
                self.current_source_relationship,
                self.source_qualification_receipt_id,
                self.last_qualification_check,
            ],
        )


@dataclass(frozen=True, slots=True)
class RemovalRecord:
    """An append-only removal of one admission from a view, not source deletion."""

    record: ExactSpaceRecordReference
    admission: CommunityAdmission
    authorization: ModeratorAuthorization
    reason_category: str
    removed_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.record, ExactSpaceRecordReference):
            raise ValidationError(
                "removal_record_invalid", "removal record is required"
            )
        if not isinstance(self.admission, CommunityAdmission):
            raise ValidationError(
                "prior_admission_required", "removal requires a prior admission"
            )
        if not isinstance(self.authorization, ModeratorAuthorization):
            raise ValidationError(
                "authorization_required", "removal authorization is required"
            )
        community = self.admission.community
        if self.record.space != community.space:
            raise ValidationError(
                "community_binding_mismatch",
                "removal record must use the community Space",
            )
        if self.record.author_did != community.community_actor_did:
            raise ValidationError(
                "community_actor_mismatch",
                "removal record must be authored by the community actor",
            )
        _text(self.reason_category, field="reason_category")
        removed_at = _timestamp(self.removed_at, field="removed_at")
        if parse_rfc3339(removed_at) < parse_rfc3339(self.admission.admitted_at):
            raise ValidationError(
                "removal_chronology_invalid",
                "removal cannot predate the exact admission",
            )
        self.authorization.require_for(
            community=community,
            action=AuthorizedAction.REMOVE,
            occurrence_id=self.admission.admission_id,
            occurred_at=removed_at,
        )
        object.__setattr__(self, "removed_at", removed_at)

    @property
    def removal_id(self) -> str:
        return _identity(
            "removal-record",
            [
                self.record.exact_id,
                self.admission.admission_id,
                self.authorization.authorization_id,
                self.reason_category,
                self.removed_at,
            ],
        )


@dataclass(frozen=True, slots=True)
class AuthorWithdrawal:
    """An author's exact prospective withdrawal, never source/community mutation."""

    record: ExactSpaceRecordReference
    admission: CommunityAdmission
    submission: Submission
    withdrawal_evidence_receipt_id: str
    withdrawn_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.record, ExactSpaceRecordReference):
            raise ValidationError(
                "withdrawal_record_invalid", "withdrawal record is required"
            )
        if not isinstance(self.admission, CommunityAdmission):
            raise ValidationError(
                "prior_admission_required", "withdrawal requires a prior admission"
            )
        if not isinstance(self.submission, Submission):
            raise ValidationError(
                "submission_reference_invalid", "withdrawal requires a submission"
            )
        if self.submission != self.admission.submission:
            raise ValidationError(
                "withdrawal_occurrence_mismatch",
                "withdrawal must target the admitted exact submission",
            )
        author_did = self.submission.post.record.author_did
        if self.record.author_did != author_did:
            raise ValidationError(
                "author_binding_mismatch",
                "withdrawal record must be authored by the source author",
            )
        if self.record.space != self.admission.community.space:
            raise ValidationError(
                "space_binding_mismatch",
                "withdrawal record must use the admitted Space",
            )
        _receipt(
            self.withdrawal_evidence_receipt_id,
            field="withdrawal_evidence_receipt_id",
        )
        withdrawn_at = _timestamp(self.withdrawn_at, field="withdrawn_at")
        if parse_rfc3339(withdrawn_at) < parse_rfc3339(self.admission.admitted_at):
            raise ValidationError(
                "withdrawal_chronology_invalid",
                "withdrawal cannot predate the exact admission",
            )
        object.__setattr__(self, "withdrawn_at", withdrawn_at)

    @property
    def withdrawal_id(self) -> str:
        return _identity(
            "author-withdrawal",
            [
                self.record.exact_id,
                self.admission.admission_id,
                self.submission.submission_id,
                self.withdrawal_evidence_receipt_id,
                self.withdrawn_at,
            ],
        )


class AdmissionDisposition(StrEnum):
    NEW = "new"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"


def classify_admission_candidate(
    existing: tuple[CommunityAdmission, ...], candidate: CommunityAdmission
) -> AdmissionDisposition:
    """Classify without sorting, deduplicating, or choosing a winner."""

    if not isinstance(existing, tuple) or any(
        not isinstance(item, CommunityAdmission) for item in existing
    ):
        raise ValidationError(
            "admission_set_invalid", "existing admissions must be an ordered tuple"
        )
    if not isinstance(candidate, CommunityAdmission):
        raise ValidationError(
            "admission_record_invalid", "candidate admission is required"
        )
    for item in existing:
        if item.admission_id == candidate.admission_id:
            return AdmissionDisposition.DUPLICATE
        if item.occurrence_id == candidate.occurrence_id:
            return AdmissionDisposition.CONFLICT
    return AdmissionDisposition.NEW


def refuse_claim_upgrade(labels: object) -> None:
    """Reject caller labels that try to mint claims absent from M1 records."""

    if not isinstance(labels, dict) or any(not isinstance(key, str) for key in labels):
        raise ValidationError("claim_labels_invalid", "claim labels must be a mapping")
    if labels:
        raise ValidationError(
            "claim_upgrade_refused",
            "caller labels cannot add claims to an SCV0-M1 record",
        )
