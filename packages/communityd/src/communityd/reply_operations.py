"""PCV0 reply authority operations, validated against direct repository state."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from community_model import (
    ADMISSION_COLLECTION,
    REPLY_ACTION_COLLECTION,
    REPLY_ADMISSION_COLLECTION,
    REPLY_POLICY_COLLECTION,
    SUBMISSION_COLLECTION,
    AdmissionRecord,
    RecordRef,
    ReplyActionRecord,
    ReplyAdmissionRecord,
    ReplyModerationState,
    ReplyPolicyRecord,
    SubmissionRecord,
    ValidationContext,
    ValidationError,
    reply_action_rkey,
    reply_admission_rkey,
    reply_moderation_key,
    reply_policy_rkey,
    validate_record,
    validate_reply_admission_references,
    validate_reply_policy_references,
    validate_reply_submission_references,
)
from community_model.identifiers import format_rfc3339

from .config import DaemonConfig
from .operations import (
    DaemonPorts,
    OperationOutcome,
    _create_at_deterministic_rkey,
    _resolve_exact,
)


class ReplyAuthorityLedgerReader(Protocol):
    """Direct community-repository reply state; never an observer projection."""

    def eligible_reply_uris(
        self, community_did: str, discussion: RecordRef
    ) -> frozenset[str]: ...

    def moderation_state(
        self, community_did: str, moderation_key: str
    ) -> ReplyModerationState | None: ...


def create_reply_policy(
    ports: DaemonPorts,
    config: DaemonConfig,
    discussion: RecordRef,
    *,
    now: datetime,
    operation_id: str,
) -> OperationOutcome:
    """Bind one immutable author-opt-in policy to an exact root admission."""

    raw = _resolve_exact(ports.reader, discussion, role="root admission")
    _parse(raw, discussion, config, ADMISSION_COLLECTION, AdmissionRecord)
    record = ReplyPolicyRecord(
        discussion=discussion,
        mode="authorOptIn",
        actor=config.administrator_did,
        created_at=now,
        created_at_raw=format_rfc3339(now),
    ).to_record()
    return _create_at_deterministic_rkey(
        ports,
        config,
        collection=REPLY_POLICY_COLLECTION,
        rkey=reply_policy_rkey(discussion),
        record=record,
        operation_id=operation_id,
    )


def admit_reply(
    ports: DaemonPorts,
    reply_ledger: ReplyAuthorityLedgerReader,
    config: DaemonConfig,
    submission: RecordRef,
    discussion: RecordRef,
    policy_ref: RecordRef,
    *,
    now: datetime,
    operation_id: str,
) -> OperationOutcome:
    """Automatically admit an author opt-in under the root's immutable policy."""

    ports.credentials.require(config.credential_ref)
    submission_raw = _resolve_exact(ports.reader, submission, role="reply submission")
    parsed_submission = _parse(
        submission_raw, submission, config, SUBMISSION_COLLECTION, SubmissionRecord
    )
    assert isinstance(parsed_submission, SubmissionRecord)
    if parsed_submission.discussion != discussion:
        raise ValidationError(
            "strong_ref_mismatch", "submission names another discussion"
        )

    root_raw = _resolve_exact(ports.reader, discussion, role="root admission")
    root = _parse(root_raw, discussion, config, ADMISSION_COLLECTION, AdmissionRecord)
    assert isinstance(root, AdmissionRecord)
    policy_raw = _resolve_exact(ports.reader, policy_ref, role="reply policy")
    policy = _parse(
        policy_raw, policy_ref, config, REPLY_POLICY_COLLECTION, ReplyPolicyRecord
    )
    assert isinstance(policy, ReplyPolicyRecord)
    validate_reply_policy_references(policy, discussion)

    subject_raw = _resolve_exact(
        ports.reader, parsed_submission.subject, role="reply subject"
    )
    reply_root, reply_parent = _reply_refs(subject_raw)
    validate_reply_submission_references(
        parsed_submission,
        root,
        root_admission_ref=discussion,
        reply_root=reply_root,
        reply_parent=reply_parent,
        eligible_parent_uris=reply_ledger.eligible_reply_uris(
            config.community_did, discussion
        ),
    )
    _require_open_root(ports, config, root)

    record_model = ReplyAdmissionRecord(
        submission=submission,
        subject=parsed_submission.subject,
        discussion=discussion,
        policy=policy_ref,
        actor=config.administrator_did,
        created_at=now,
        created_at_raw=format_rfc3339(now),
    )
    validate_reply_admission_references(
        record_model,
        parsed_submission,
        policy,
        submission_ref=submission,
        policy_ref=policy_ref,
    )
    # The synchronous authority server serializes effects.  This final direct
    # ledger read is intentionally adjacent to the create boundary so closure
    # observed first always wins.
    _require_open_root(ports, config, root)
    return _create_at_deterministic_rkey(
        ports,
        config,
        collection=REPLY_ADMISSION_COLLECTION,
        rkey=reply_admission_rkey(submission),
        record=record_model.to_record(),
        operation_id=operation_id,
    )


def moderate_reply(
    ports: DaemonPorts,
    reply_ledger: ReplyAuthorityLedgerReader,
    config: DaemonConfig,
    admission_ref: RecordRef,
    action: str,
    reason: str | None,
    *,
    controlling_action: RecordRef | None,
    now: datetime,
    operation_id: str,
) -> OperationOutcome:
    """Remove/restore a logical reply with a chain sticky across source CIDs."""

    ports.credentials.require(config.credential_ref)
    admission_raw = _resolve_exact(ports.reader, admission_ref, role="reply admission")
    admission = _parse(
        admission_raw,
        admission_ref,
        config,
        REPLY_ADMISSION_COLLECTION,
        ReplyAdmissionRecord,
    )
    assert isinstance(admission, ReplyAdmissionRecord)
    moderation_key = reply_moderation_key(
        community_did=config.community_did,
        root_admission=admission.discussion,
        reply_uri=admission.subject.uri,
    )
    state = reply_ledger.moderation_state(config.community_did, moderation_key)
    if action == "remove":
        if state is not None and state.removed:
            raise ValidationError("action_chain_invalid", "reply is already removed")
        previous = None if state is None else state.last_action
    elif action == "restore":
        if state is None or not state.removed:
            raise ValidationError("action_chain_invalid", "reply is not removed")
        if controlling_action != state.last_action:
            raise ValidationError(
                "action_chain_invalid", "restore does not name the controlling removal"
            )
        previous = state.last_action
    else:
        raise ValidationError("unsupported_action", "reply action is unsupported")

    record = ReplyActionRecord(
        action=action,
        admission=admission_ref,
        subject=admission.subject,
        moderation_key=moderation_key,
        previous_action=previous,
        actor=config.administrator_did,
        reason=reason,
        created_at=now,
        created_at_raw=format_rfc3339(now),
    ).to_record()
    return _create_at_deterministic_rkey(
        ports,
        config,
        collection=REPLY_ACTION_COLLECTION,
        rkey=reply_action_rkey(
            action=action,
            moderation_key=moderation_key,
            previous_action=previous,
        ),
        record=record,
        operation_id=operation_id,
    )


def _parse(
    raw: Mapping[str, object],
    ref: RecordRef,
    config: DaemonConfig,
    collection: str,
    expected: type[object],
) -> object:
    context = ValidationContext(
        community_did=config.community_did,
        repo_did=ref.repo_did,
        collection=collection,
        rkey=ref.rkey,
        operation="create",
        record_cid=ref.cid,
        administrator_did=config.administrator_did,
    )
    parsed = validate_record(raw, context=context).record
    if not isinstance(parsed, expected):
        raise ValidationError("schema_invalid", "authority record has wrong type")
    return parsed


def _reply_refs(record: Mapping[str, object]) -> tuple[RecordRef, RecordRef]:
    reply = record.get("reply")
    if not isinstance(reply, Mapping):
        raise ValidationError("reply_ancestry_invalid", "subject is not a reply")
    return (
        RecordRef.from_mapping(reply.get("root"), path=("reply", "root")),
        RecordRef.from_mapping(reply.get("parent"), path=("reply", "parent")),
    )


def _require_open_root(
    ports: DaemonPorts, config: DaemonConfig, root: AdmissionRecord
) -> None:
    lifecycle = ports.ledger.find_subject_lifecycle(config.community_did, root.subject)
    if lifecycle.valid_removals:
        raise ValidationError("discussion_closed", "root discussion is closed")


__all__ = [
    "ReplyAuthorityLedgerReader",
    "admit_reply",
    "create_reply_policy",
    "moderate_reply",
]
