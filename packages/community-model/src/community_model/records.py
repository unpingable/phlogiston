"""Strict provisional V0 community record models and contextual checks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypeAlias

from .canonical import (
    admission_rkey,
    member_action_rkey,
    removal_rkey,
    reply_action_rkey,
    reply_admission_rkey,
    reply_moderation_key,
    reply_policy_rkey,
    validate_sha256,
)
from .constants import (
    ADMISSION_COLLECTION,
    COMMUNITY_COLLECTIONS,
    MEMBER_ACTION_COLLECTION,
    MOD_ACTION_COLLECTION,
    POST_COLLECTION,
    PROFILE_COLLECTION,
    REASON_CODES,
    REPLY_ACTION_COLLECTION,
    REPLY_ADMISSION_COLLECTION,
    REPLY_POLICY_COLLECTION,
    SUBMISSION_COLLECTION,
    RepositoryOperation,
)
from .errors import ValidationError
from .identifiers import (
    normalize_rfc3339,
    parse_rfc3339,
    rfc3339_is_after,
    validate_cid,
    validate_did,
    validate_nsid,
    validate_rkey,
    validate_tid,
)
from .values import RecordRef


def _validated_shape(record: object) -> Mapping[str, object]:
    from .lexicons import validate_lexicon_record

    if not isinstance(record, Mapping):
        raise ValidationError("schema_invalid", "record must be an object")
    validate_lexicon_record(record)
    return record


def _validate_model_time(instance: object) -> None:
    raw_time = getattr(instance, "created_at_raw", None)
    parsed = parse_rfc3339(raw_time, path=("createdAt",))
    supplied = getattr(instance, "created_at", None)
    if not isinstance(supplied, datetime) or supplied.utcoffset() is None:
        raise ValidationError(
            "datetime_invalid", "created_at must be timezone-aware", path=("createdAt",)
        )
    normalized = supplied.astimezone(UTC)
    if normalized != parsed:
        raise ValidationError(
            "datetime_invalid",
            "created_at and its signed raw value disagree",
            path=("createdAt",),
        )
    object.__setattr__(instance, "created_at", normalized)


def _require_ref(value: object, *, field: str) -> RecordRef:
    if not isinstance(value, RecordRef):
        raise ValidationError(
            "schema_invalid", f"{field} must be a RecordRef", path=(field,)
        )
    return value


@dataclass(frozen=True, slots=True)
class ProfileRecord:
    display_name: str
    description: str | None
    created_at: datetime
    created_at_raw: str

    record_type = PROFILE_COLLECTION

    def __post_init__(self) -> None:
        _validate_model_time(self)
        _validated_shape(self.to_record())

    @classmethod
    def from_record(cls, value: object) -> ProfileRecord:
        record = _validated_shape(value)
        raw_time = record["createdAt"]
        assert isinstance(record["displayName"], str)
        assert isinstance(raw_time, str)
        description = record.get("description")
        assert description is None or isinstance(description, str)
        return cls(
            display_name=record["displayName"],
            description=description,
            created_at=parse_rfc3339(raw_time, path=("createdAt",)),
            created_at_raw=raw_time,
        )

    def to_record(self) -> dict[str, object]:
        result: dict[str, object] = {
            "$type": self.record_type,
            "displayName": self.display_name,
            "createdAt": self.created_at_raw,
        }
        if self.description is not None:
            result["description"] = self.description
        return result


@dataclass(frozen=True, slots=True)
class SubmissionRecord:
    community: str
    subject: RecordRef
    created_at: datetime
    created_at_raw: str
    discussion: RecordRef | None = None

    record_type = SUBMISSION_COLLECTION

    def __post_init__(self) -> None:
        validate_did(self.community, path=("community",))
        _require_ref(self.subject, field="subject")
        if self.discussion is not None:
            _require_ref(self.discussion, field="discussion")
        _validate_model_time(self)
        _validated_shape(self.to_record())

    @classmethod
    def from_record(cls, value: object) -> SubmissionRecord:
        record = _validated_shape(value)
        raw_time = record["createdAt"]
        assert isinstance(record["community"], str)
        assert isinstance(raw_time, str)
        return cls(
            community=validate_did(record["community"], path=("community",)),
            subject=RecordRef.from_mapping(record["subject"], path=("subject",)),
            created_at=parse_rfc3339(raw_time, path=("createdAt",)),
            created_at_raw=raw_time,
            discussion=(
                RecordRef.from_mapping(record["discussion"], path=("discussion",))
                if "discussion" in record
                else None
            ),
        )

    def to_record(self) -> dict[str, object]:
        result: dict[str, object] = {
            "$type": self.record_type,
            "community": self.community,
            "subject": self.subject.as_dict(),
            "createdAt": self.created_at_raw,
        }
        if self.discussion is not None:
            result["discussion"] = self.discussion.as_dict()
        return result

    @classmethod
    def from_legacy_record(cls, value: object) -> SubmissionRecord:
        """Parse the root-only shape without misclassifying reply opt-ins."""

        if isinstance(value, Mapping) and "discussion" in value:
            raise ValidationError(
                "schema_incompatible",
                "legacy submission readers must not treat a reply opt-in as a root",
                path=("discussion",),
            )
        return cls.from_record(value)


@dataclass(frozen=True, slots=True)
class AdmissionRecord:
    submission: RecordRef
    subject: RecordRef
    actor: str
    created_at: datetime
    created_at_raw: str

    record_type = ADMISSION_COLLECTION

    def __post_init__(self) -> None:
        _require_ref(self.submission, field="submission")
        _require_ref(self.subject, field="subject")
        validate_did(self.actor, path=("actor",))
        _validate_model_time(self)
        _validated_shape(self.to_record())

    @classmethod
    def from_record(cls, value: object) -> AdmissionRecord:
        record = _validated_shape(value)
        raw_time = record["createdAt"]
        assert isinstance(record["actor"], str)
        assert isinstance(raw_time, str)
        return cls(
            submission=RecordRef.from_mapping(
                record["submission"], path=("submission",)
            ),
            subject=RecordRef.from_mapping(record["subject"], path=("subject",)),
            actor=validate_did(record["actor"], path=("actor",)),
            created_at=parse_rfc3339(raw_time, path=("createdAt",)),
            created_at_raw=raw_time,
        )

    def to_record(self) -> dict[str, object]:
        return {
            "$type": self.record_type,
            "submission": self.submission.as_dict(),
            "subject": self.subject.as_dict(),
            "actor": self.actor,
            "createdAt": self.created_at_raw,
        }


@dataclass(frozen=True, slots=True)
class ModActionRecord:
    action: str
    admission: RecordRef
    subject: RecordRef
    actor: str
    reason: str | None
    created_at: datetime
    created_at_raw: str

    record_type = MOD_ACTION_COLLECTION

    def __post_init__(self) -> None:
        if self.action != "remove":
            raise ValidationError(
                "unsupported_action",
                "V0 understands only the remove action",
                path=("action",),
            )
        _require_ref(self.admission, field="admission")
        _require_ref(self.subject, field="subject")
        validate_did(self.actor, path=("actor",))
        _validate_model_time(self)
        _validated_shape(self.to_record())

    @classmethod
    def from_record(cls, value: object) -> ModActionRecord:
        record = _validated_shape(value)
        action = record["action"]
        if action != "remove":
            raise ValidationError(
                "unsupported_action",
                "V0 understands only the remove action",
                path=("action",),
            )
        raw_time = record["createdAt"]
        assert isinstance(action, str)
        assert isinstance(record["actor"], str)
        assert isinstance(raw_time, str)
        reason = record.get("reason")
        assert reason is None or isinstance(reason, str)
        return cls(
            action=action,
            admission=RecordRef.from_mapping(record["admission"], path=("admission",)),
            subject=RecordRef.from_mapping(record["subject"], path=("subject",)),
            actor=validate_did(record["actor"], path=("actor",)),
            reason=reason,
            created_at=parse_rfc3339(raw_time, path=("createdAt",)),
            created_at_raw=raw_time,
        )

    def to_record(self) -> dict[str, object]:
        result: dict[str, object] = {
            "$type": self.record_type,
            "action": self.action,
            "admission": self.admission.as_dict(),
            "subject": self.subject.as_dict(),
            "actor": self.actor,
            "createdAt": self.created_at_raw,
        }
        if self.reason is not None:
            result["reason"] = self.reason
        return result


@dataclass(frozen=True, slots=True)
class MemberActionRecord:
    """An authority-owned, append-only membership transition."""

    action: str
    subject: str
    actor: str
    reason: str | None
    created_at: datetime
    created_at_raw: str

    record_type = MEMBER_ACTION_COLLECTION

    def __post_init__(self) -> None:
        if self.action not in {"add", "remove"}:
            raise ValidationError(
                "unsupported_action",
                "membership action must be add or remove",
                path=("action",),
            )
        validate_did(self.subject, path=("subject",))
        validate_did(self.actor, path=("actor",))
        _validate_model_time(self)
        _validated_shape(self.to_record())

    @classmethod
    def from_record(cls, value: object) -> MemberActionRecord:
        record = _validated_shape(value)
        action, subject, actor, raw_time = (
            record["action"],
            record["subject"],
            record["actor"],
            record["createdAt"],
        )
        if action not in {"add", "remove"}:
            raise ValidationError(
                "unsupported_action",
                "membership action must be add or remove",
                path=("action",),
            )
        assert isinstance(action, str) and isinstance(subject, str)
        assert isinstance(actor, str) and isinstance(raw_time, str)
        reason = record.get("reason")
        assert reason is None or isinstance(reason, str)
        return cls(
            action=action,
            subject=subject,
            actor=actor,
            reason=reason,
            created_at=parse_rfc3339(raw_time, path=("createdAt",)),
            created_at_raw=raw_time,
        )

    def to_record(self) -> dict[str, object]:
        result: dict[str, object] = {
            "$type": self.record_type,
            "action": self.action,
            "subject": self.subject,
            "actor": self.actor,
            "createdAt": self.created_at_raw,
        }
        if self.reason is not None:
            result["reason"] = self.reason
        return result


@dataclass(frozen=True, slots=True)
class ReplyPolicyRecord:
    discussion: RecordRef
    mode: str
    actor: str
    created_at: datetime
    created_at_raw: str

    record_type = REPLY_POLICY_COLLECTION

    def __post_init__(self) -> None:
        _require_ref(self.discussion, field="discussion")
        if self.mode != "authorOptIn":
            raise ValidationError(
                "reply_policy_mismatch",
                "PCV0 requires authorOptIn mode",
                path=("mode",),
            )
        validate_did(self.actor, path=("actor",))
        _validate_model_time(self)
        _validated_shape(self.to_record())

    @classmethod
    def from_record(cls, value: object) -> ReplyPolicyRecord:
        record = _validated_shape(value)
        raw_time = record["createdAt"]
        assert isinstance(record["mode"], str)
        assert isinstance(record["actor"], str)
        assert isinstance(raw_time, str)
        return cls(
            discussion=RecordRef.from_mapping(
                record["discussion"], path=("discussion",)
            ),
            mode=record["mode"],
            actor=validate_did(record["actor"], path=("actor",)),
            created_at=parse_rfc3339(raw_time, path=("createdAt",)),
            created_at_raw=raw_time,
        )

    def to_record(self) -> dict[str, object]:
        return {
            "$type": self.record_type,
            "discussion": self.discussion.as_dict(),
            "mode": self.mode,
            "actor": self.actor,
            "createdAt": self.created_at_raw,
        }


@dataclass(frozen=True, slots=True)
class ReplyAdmissionRecord:
    submission: RecordRef
    subject: RecordRef
    discussion: RecordRef
    policy: RecordRef
    actor: str
    created_at: datetime
    created_at_raw: str

    record_type = REPLY_ADMISSION_COLLECTION

    def __post_init__(self) -> None:
        for field in ("submission", "subject", "discussion", "policy"):
            _require_ref(getattr(self, field), field=field)
        validate_did(self.actor, path=("actor",))
        _validate_model_time(self)
        _validated_shape(self.to_record())

    @classmethod
    def from_record(cls, value: object) -> ReplyAdmissionRecord:
        record = _validated_shape(value)
        raw_time = record["createdAt"]
        assert isinstance(record["actor"], str)
        assert isinstance(raw_time, str)
        return cls(
            submission=RecordRef.from_mapping(
                record["submission"], path=("submission",)
            ),
            subject=RecordRef.from_mapping(record["subject"], path=("subject",)),
            discussion=RecordRef.from_mapping(
                record["discussion"], path=("discussion",)
            ),
            policy=RecordRef.from_mapping(record["policy"], path=("policy",)),
            actor=validate_did(record["actor"], path=("actor",)),
            created_at=parse_rfc3339(raw_time, path=("createdAt",)),
            created_at_raw=raw_time,
        )

    def to_record(self) -> dict[str, object]:
        return {
            "$type": self.record_type,
            "submission": self.submission.as_dict(),
            "subject": self.subject.as_dict(),
            "discussion": self.discussion.as_dict(),
            "policy": self.policy.as_dict(),
            "actor": self.actor,
            "createdAt": self.created_at_raw,
        }


@dataclass(frozen=True, slots=True)
class ReplyActionRecord:
    action: str
    admission: RecordRef
    subject: RecordRef
    moderation_key: str
    previous_action: RecordRef | None
    actor: str
    reason: str | None
    created_at: datetime
    created_at_raw: str

    record_type = REPLY_ACTION_COLLECTION

    def __post_init__(self) -> None:
        if self.action not in {"remove", "restore"}:
            raise ValidationError(
                "unsupported_action",
                "reply action must remove or restore",
                path=("action",),
            )
        _require_ref(self.admission, field="admission")
        _require_ref(self.subject, field="subject")
        validate_sha256(self.moderation_key)
        if self.previous_action is not None:
            _require_ref(self.previous_action, field="previousAction")
        if self.action == "restore" and self.previous_action is None:
            raise ValidationError(
                "action_chain_invalid",
                "restore must reference the controlling removal",
                path=("previousAction",),
            )
        validate_did(self.actor, path=("actor",))
        _validate_model_time(self)
        _validated_shape(self.to_record())

    @classmethod
    def from_record(cls, value: object) -> ReplyActionRecord:
        record = _validated_shape(value)
        raw_time = record["createdAt"]
        assert isinstance(record["action"], str)
        assert isinstance(record["moderationKey"], str)
        assert isinstance(record["actor"], str)
        assert isinstance(raw_time, str)
        reason = record.get("reason")
        assert reason is None or isinstance(reason, str)
        return cls(
            action=record["action"],
            admission=RecordRef.from_mapping(record["admission"], path=("admission",)),
            subject=RecordRef.from_mapping(record["subject"], path=("subject",)),
            moderation_key=record["moderationKey"],
            previous_action=(
                RecordRef.from_mapping(
                    record["previousAction"], path=("previousAction",)
                )
                if "previousAction" in record
                else None
            ),
            actor=validate_did(record["actor"], path=("actor",)),
            reason=reason,
            created_at=parse_rfc3339(raw_time, path=("createdAt",)),
            created_at_raw=raw_time,
        )

    def to_record(self) -> dict[str, object]:
        result: dict[str, object] = {
            "$type": self.record_type,
            "action": self.action,
            "admission": self.admission.as_dict(),
            "subject": self.subject.as_dict(),
            "moderationKey": self.moderation_key,
            "actor": self.actor,
            "createdAt": self.created_at_raw,
        }
        if self.previous_action is not None:
            result["previousAction"] = self.previous_action.as_dict()
        if self.reason is not None:
            result["reason"] = self.reason
        return result


CommunityRecord: TypeAlias = (
    ProfileRecord
    | SubmissionRecord
    | AdmissionRecord
    | ModActionRecord
    | MemberActionRecord
    | ReplyPolicyRecord
    | ReplyAdmissionRecord
    | ReplyActionRecord
)


@dataclass(frozen=True, slots=True)
class ValidationContext:
    community_did: str
    repo_did: str
    collection: str
    rkey: str
    operation: RepositoryOperation | str
    record_cid: str
    administrator_did: str | None = None
    first_accepted_at: datetime | None = None

    def __post_init__(self) -> None:
        validate_did(self.community_did, path=("community_did",))
        validate_did(self.repo_did, path=("repo_did",))
        validate_nsid(self.collection, path=("collection",))
        if self.collection not in COMMUNITY_COLLECTIONS:
            raise ValidationError(
                "unsupported_record_type",
                "envelope collection is not a V0 community collection",
                path=("collection",),
            )
        validate_rkey(self.rkey, path=("rkey",))
        try:
            operation = RepositoryOperation(self.operation)
        except (TypeError, ValueError) as exc:
            raise ValidationError("schema_invalid", "unsupported operation") from exc
        object.__setattr__(self, "operation", operation)
        validate_cid(self.record_cid, require_dag_cbor=True, path=("record_cid",))
        if self.administrator_did is not None:
            validate_did(self.administrator_did, path=("administrator_did",))
        if self.first_accepted_at is not None:
            if (
                not isinstance(self.first_accepted_at, datetime)
                or self.first_accepted_at.utcoffset() is None
            ):
                raise ValidationError(
                    "datetime_invalid", "first accepted time must have an offset"
                )
            object.__setattr__(
                self, "first_accepted_at", self.first_accepted_at.astimezone(UTC)
            )


@dataclass(frozen=True, slots=True)
class RecordValidation:
    record: CommunityRecord
    findings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(
            self.record,
            ProfileRecord
            | SubmissionRecord
            | AdmissionRecord
            | ModActionRecord
            | MemberActionRecord
            | ReplyPolicyRecord
            | ReplyAdmissionRecord
            | ReplyActionRecord,
        ):
            raise ValidationError(
                "schema_invalid", "record validation requires a community record"
            )
        if (
            not isinstance(self.findings, list | tuple)
            or any(
                not isinstance(finding, str) or finding not in REASON_CODES
                for finding in self.findings
            )
            or len(set(self.findings)) != len(self.findings)
        ):
            raise ValidationError(
                "schema_invalid", "findings must be unique known reason codes"
            )
        object.__setattr__(self, "findings", tuple(self.findings))


def _check_timestamp(
    record: CommunityRecord, context: ValidationContext
) -> tuple[str, ...]:
    if context.first_accepted_at is None:
        return ()
    if not rfc3339_is_after(
        record.created_at_raw, context.first_accepted_at + timedelta(minutes=5)
    ):
        return ()
    if isinstance(record, ModActionRecord | MemberActionRecord):
        return ("created_at_future",)
    raise ValidationError(
        "created_at_future",
        "signed createdAt exceeds the five-minute accepted skew",
        path=("createdAt",),
    )


def validate_record(value: object, *, context: ValidationContext) -> RecordValidation:
    if not isinstance(value, Mapping):
        raise ValidationError("schema_invalid", "record must be an object")
    record_type = value.get("$type")
    if record_type in COMMUNITY_COLLECTIONS and record_type != context.collection:
        raise ValidationError(
            "schema_invalid",
            "record $type does not match its envelope collection",
            path=("$type",),
        )
    if record_type == PROFILE_COLLECTION:
        record: CommunityRecord = ProfileRecord.from_record(value)
        if context.repo_did != context.community_did:
            raise ValidationError(
                "authority_repo_mismatch", "profile must live in the community repo"
            )
        if context.rkey != "self":
            raise ValidationError("schema_invalid", "profile rkey must be self")
        if context.operation not in {
            RepositoryOperation.CREATE,
            RepositoryOperation.UPDATE,
        }:
            raise ValidationError(
                "schema_invalid", "profile deletion has no record payload"
            )
    elif record_type == SUBMISSION_COLLECTION:
        record = SubmissionRecord.from_record(value)
        if record.community != context.community_did:
            raise ValidationError(
                "community_mismatch", "submission targets a different community"
            )
        if record.subject.repo_did != context.repo_did:
            raise ValidationError(
                "repo_mismatch", "self-submission must be owned by its envelope repo"
            )
        if record.subject.collection != POST_COLLECTION:
            raise ValidationError(
                "subject_collection_invalid",
                "submission subject must be a Bluesky post",
            )
        if (
            record.discussion is not None
            and record.discussion.collection != ADMISSION_COLLECTION
        ):
            raise ValidationError(
                "strong_ref_mismatch",
                "discussion must reference a root admission",
            )
        validate_tid(context.rkey, path=("rkey",))
        if context.operation not in {
            RepositoryOperation.CREATE,
            RepositoryOperation.UPDATE,
        }:
            raise ValidationError(
                "schema_invalid", "submission delete has no record payload"
            )
    elif record_type == ADMISSION_COLLECTION:
        record = AdmissionRecord.from_record(value)
        _validate_authority_context(record.actor, context)
        if record.submission.collection != SUBMISSION_COLLECTION:
            raise ValidationError(
                "strong_ref_mismatch", "admission must reference a submission record"
            )
        if record.subject.collection != POST_COLLECTION:
            raise ValidationError(
                "subject_collection_invalid", "admission subject must be a Bluesky post"
            )
        if context.rkey != admission_rkey(record.submission):
            raise ValidationError(
                "strong_ref_mismatch",
                "admission rkey does not match its exact submission",
            )
    elif record_type == MOD_ACTION_COLLECTION:
        record = ModActionRecord.from_record(value)
        _validate_authority_context(record.actor, context)
        if record.admission.collection != ADMISSION_COLLECTION:
            raise ValidationError(
                "strong_ref_mismatch", "removal must reference an admission record"
            )
        if record.subject.collection != POST_COLLECTION:
            raise ValidationError(
                "subject_collection_invalid", "removal subject must be a Bluesky post"
            )
        if context.rkey != removal_rkey(record.admission):
            raise ValidationError(
                "strong_ref_mismatch", "removal rkey does not match its exact admission"
            )
    elif record_type == MEMBER_ACTION_COLLECTION:
        record = MemberActionRecord.from_record(value)
        _validate_authority_context(record.actor, context)
        if context.rkey != member_action_rkey(record.subject, record.action):
            raise ValidationError(
                "strong_ref_mismatch",
                "membership rkey does not match subject and action",
            )
    elif record_type == REPLY_POLICY_COLLECTION:
        record = ReplyPolicyRecord.from_record(value)
        _validate_authority_context(record.actor, context)
        if record.discussion.collection != ADMISSION_COLLECTION:
            raise ValidationError(
                "strong_ref_mismatch", "reply policy must reference a root admission"
            )
        if context.rkey != reply_policy_rkey(record.discussion):
            raise ValidationError(
                "strong_ref_mismatch", "reply policy rkey does not match its discussion"
            )
    elif record_type == REPLY_ADMISSION_COLLECTION:
        record = ReplyAdmissionRecord.from_record(value)
        _validate_authority_context(record.actor, context)
        if record.submission.collection != SUBMISSION_COLLECTION:
            raise ValidationError(
                "strong_ref_mismatch", "reply admission must reference a submission"
            )
        if record.subject.collection != POST_COLLECTION:
            raise ValidationError(
                "subject_collection_invalid",
                "reply admission subject must be a Bluesky post",
            )
        if record.discussion.collection != ADMISSION_COLLECTION:
            raise ValidationError(
                "strong_ref_mismatch", "reply admission must reference a root admission"
            )
        if record.policy.collection != REPLY_POLICY_COLLECTION:
            raise ValidationError(
                "strong_ref_mismatch", "reply admission must reference a reply policy"
            )
        if context.rkey != reply_admission_rkey(record.submission):
            raise ValidationError(
                "strong_ref_mismatch",
                "reply admission rkey does not match its submission",
            )
    elif record_type == REPLY_ACTION_COLLECTION:
        record = ReplyActionRecord.from_record(value)
        _validate_authority_context(record.actor, context)
        if record.admission.collection != REPLY_ADMISSION_COLLECTION:
            raise ValidationError(
                "strong_ref_mismatch", "reply action must reference a reply admission"
            )
        if record.subject.collection != POST_COLLECTION:
            raise ValidationError(
                "subject_collection_invalid",
                "reply action subject must be a Bluesky post",
            )
        if (
            record.previous_action is not None
            and record.previous_action.collection != REPLY_ACTION_COLLECTION
        ):
            raise ValidationError(
                "action_chain_invalid", "previous action must reference a reply action"
            )
        if context.rkey != reply_action_rkey(
            action=record.action,
            moderation_key=record.moderation_key,
            previous_action=record.previous_action,
        ):
            raise ValidationError(
                "strong_ref_mismatch",
                "reply action rkey does not match its action chain",
            )
    else:
        raise ValidationError(
            "unsupported_record_type",
            "record is not a supported community type",
        )
    return RecordValidation(record=record, findings=_check_timestamp(record, context))


def _validate_authority_context(actor: str, context: ValidationContext) -> None:
    if context.repo_did != context.community_did:
        raise ValidationError(
            "authority_repo_mismatch",
            "authority record must live in the community repo",
        )
    if context.administrator_did is None or actor != context.administrator_did:
        raise ValidationError(
            "actor_unauthorized",
            "authority record actor is not the configured administrator",
        )
    if context.operation is not RepositoryOperation.CREATE:
        raise ValidationError(
            "authority_record_mutated", "authority records are create-only"
        )


def validate_admission_references(
    admission: AdmissionRecord, submission: SubmissionRecord
) -> None:
    if submission.discussion is not None:
        raise ValidationError(
            "schema_incompatible",
            "reply opt-ins require replyAdmission and cannot be admitted as roots",
        )
    if admission.subject != submission.subject:
        raise ValidationError(
            "strong_ref_mismatch",
            "admission and submission subjects must match exactly",
        )


def validate_removal_references(
    removal: ModActionRecord, admission: AdmissionRecord
) -> None:
    if removal.subject != admission.subject:
        raise ValidationError(
            "strong_ref_mismatch", "removal and admission subjects must match exactly"
        )


def validate_reply_submission_references(
    submission: SubmissionRecord,
    root_admission: AdmissionRecord,
    *,
    root_admission_ref: RecordRef,
    reply_root: RecordRef,
    reply_parent: RecordRef,
    eligible_parent_uris: frozenset[str] = frozenset(),
) -> None:
    """Validate opt-in thread connection without turning fetch results into policy."""

    if submission.discussion is None:
        raise ValidationError(
            "reply_ancestry_invalid", "reply opt-in requires discussion"
        )
    if submission.discussion != root_admission_ref:
        raise ValidationError(
            "reply_ancestry_invalid", "reply opt-in names another discussion"
        )
    if reply_root != root_admission.subject:
        raise ValidationError(
            "reply_ancestry_invalid", "reply root must exactly match admitted root"
        )
    if (
        reply_parent != root_admission.subject
        and reply_parent.uri not in eligible_parent_uris
    ):
        raise ValidationError(
            "reply_ancestry_invalid", "reply parent is not eligible in this discussion"
        )


def validate_reply_policy_references(
    policy: ReplyPolicyRecord, root_admission_ref: RecordRef
) -> None:
    if policy.discussion != root_admission_ref:
        raise ValidationError(
            "reply_policy_mismatch", "policy is bound to another root admission"
        )


def validate_reply_admission_references(
    admission: ReplyAdmissionRecord,
    submission: SubmissionRecord,
    policy: ReplyPolicyRecord,
    *,
    submission_ref: RecordRef,
    policy_ref: RecordRef,
) -> None:
    if submission.discussion is None:
        raise ValidationError(
            "strong_ref_mismatch", "root submissions cannot receive reply admission"
        )
    if admission.submission != submission_ref:
        raise ValidationError(
            "strong_ref_mismatch", "reply admission references another submission"
        )
    if admission.subject != submission.subject:
        raise ValidationError(
            "strong_ref_mismatch", "reply admission and submission subjects differ"
        )
    if (
        admission.discussion != submission.discussion
        or policy.discussion != submission.discussion
    ):
        raise ValidationError(
            "reply_policy_mismatch",
            "reply admission, submission, and policy discussions differ",
        )
    if admission.policy != policy_ref:
        raise ValidationError(
            "reply_policy_mismatch", "reply admission references another policy"
        )


def validate_reply_action_references(
    action: ReplyActionRecord,
    admission: ReplyAdmissionRecord,
    *,
    admission_ref: RecordRef,
    community_did: str,
) -> None:
    if action.admission != admission_ref or action.subject != admission.subject:
        raise ValidationError(
            "strong_ref_mismatch", "reply action does not match its exact admission"
        )
    expected = reply_moderation_key(
        community_did=community_did,
        root_admission=admission.discussion,
        reply_uri=admission.subject.uri,
    )
    if action.moderation_key != expected:
        raise ValidationError(
            "moderation_key_mismatch",
            "reply action has the wrong logical moderation key",
        )


@dataclass(frozen=True, slots=True)
class ReplyModerationState:
    moderation_key: str
    removed: bool
    last_action: RecordRef

    def __post_init__(self) -> None:
        validate_sha256(self.moderation_key)
        if not isinstance(self.removed, bool):
            raise ValidationError("schema_invalid", "removed must be boolean")
        _require_ref(self.last_action, field="lastAction")


def apply_reply_action(
    state: ReplyModerationState | None,
    action: ReplyActionRecord,
    *,
    action_ref: RecordRef,
    admission: ReplyAdmissionRecord,
    admission_ref: RecordRef,
    community_did: str,
) -> ReplyModerationState:
    """Apply one exact action; logical URI identity makes removal sticky across edits."""

    validate_reply_action_references(
        action, admission, admission_ref=admission_ref, community_did=community_did
    )
    if state is None:
        if action.action != "remove" or action.previous_action is not None:
            raise ValidationError(
                "action_chain_invalid", "the first action must be an unchained removal"
            )
    else:
        if state.moderation_key != action.moderation_key:
            raise ValidationError(
                "moderation_key_mismatch", "action switches moderation chains"
            )
        if action.previous_action != state.last_action:
            raise ValidationError(
                "action_chain_invalid", "action does not reference the chain head"
            )
        if action.action == "remove" and state.removed:
            raise ValidationError("action_chain_invalid", "reply is already removed")
        if action.action == "restore" and not state.removed:
            raise ValidationError("action_chain_invalid", "reply is not removed")
    return ReplyModerationState(
        moderation_key=action.moderation_key,
        removed=action.action == "remove",
        last_action=action_ref,
    )


def normalized_created_at(record: CommunityRecord) -> str:
    """Return normalized UTC time without replacing signed raw evidence."""

    return normalize_rfc3339(record.created_at_raw, path=("createdAt",))
