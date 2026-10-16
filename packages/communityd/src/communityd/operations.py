"""Daemon admit/remove operations over the create-only authority ports.

Authorization runs before any credential, reader, ledger, or writer call.  The
actor DID is always the single configured administrator returned by the
authorizer; callers can never supply it.  Rkeys are deterministic and
create-only: admissions derive from the exact submission, removals from the
exact admission.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from community_model import (
    ADMISSION_COLLECTION,
    MEMBER_ACTION_COLLECTION,
    MOD_ACTION_COLLECTION,
    SUBMISSION_COLLECTION,
    AdmissionRecord,
    AuthorizationError,
    AuthorizedAdmin,
    CurrentRecordStatus,
    MemberActionRecord,
    ModActionRecord,
    PortUnavailableError,
    RecordRef,
    ResolutionStatus,
    SubmissionRecord,
    UnsupportedReadmissionError,
    ValidationContext,
    ValidationError,
    WriteFailedError,
    admission_rkey,
    canonical_json_bytes,
    member_action_rkey,
    removal_rkey,
    validate_record,
)
from community_model.identifiers import format_rfc3339, validate_did

from .config import DaemonConfig
from .journal import JournalConflictError, SQLiteOperationJournal
from .ports import (
    AdminAuthorizer,
    AuthorityLedgerReader,
    AuthorityWriter,
    CredentialProvider,
    RecordReader,
)


@dataclass(frozen=True, slots=True)
class OperationOutcome:
    """The CLI-visible result of one admit/remove invocation."""

    operation: Literal["created", "existing"]
    record: RecordRef


@dataclass(frozen=True, slots=True)
class DaemonPorts:
    """The complete port set one operation invocation may touch."""

    reader: RecordReader
    ledger: AuthorityLedgerReader
    authorizer: AdminAuthorizer
    writer: AuthorityWriter
    credentials: CredentialProvider
    operation_journal: SQLiteOperationJournal | None = None
    authority_reader: RecordReader | None = None


class LocalAdminAuthorizer:
    """Authorize by effective UID and return the configured administrator DID."""

    def __init__(
        self,
        *,
        administrator_did: str,
        allowed_uid: int,
        uid_reader: Callable[[], int] = os.geteuid,
    ) -> None:
        self.administrator_did = validate_did(administrator_did)
        self.allowed_uid = allowed_uid
        self.uid_reader = uid_reader

    def require(
        self, action: Literal["admit", "remove", "membership"]
    ) -> AuthorizedAdmin:
        effective_uid = self.uid_reader()
        if effective_uid != self.allowed_uid:
            raise AuthorizationError(
                f"effective UID is not authorized to {action} for this community"
            )
        return AuthorizedAdmin(did=self.administrator_did, effective_uid=effective_uid)


def _authorize(
    ports: DaemonPorts,
    config: DaemonConfig,
    action: Literal["admit", "remove", "membership"],
) -> AuthorizedAdmin:
    admin = ports.authorizer.require(action)
    if admin.did != config.administrator_did:
        raise AuthorizationError("authorizer returned an unconfigured administrator")
    ports.credentials.require(config.credential_ref)
    return admin


def _resolve_exact(
    reader: RecordReader, ref: RecordRef, *, role: str
) -> Mapping[str, object]:
    result = reader.get_exact(ref)
    if result.status is ResolutionStatus.ERROR:
        raise PortUnavailableError(f"{role} resolution failed")
    if result.status is ResolutionStatus.MISSING:
        raise ValidationError("reference_missing", f"{role} is not in its repository")
    if result.status is ResolutionStatus.MISMATCH:
        raise ValidationError(
            "strong_ref_mismatch", f"{role} no longer exists at the exact CID"
        )
    assert result.record is not None
    return result.record


def _parsed_record(
    result_record: Mapping[str, object], context: ValidationContext
) -> SubmissionRecord | AdmissionRecord:
    validated = validate_record(result_record, context=context)
    record = validated.record
    assert isinstance(record, SubmissionRecord | AdmissionRecord)
    return record


def _create_at_deterministic_rkey(
    ports: DaemonPorts,
    config: DaemonConfig,
    *,
    collection: str,
    rkey: str,
    record: Mapping[str, object],
    operation_id: str | None = None,
    before_dispatch: Callable[[], None] | None = None,
    retain_attempt_marker: bool = False,
) -> OperationOutcome:
    uri = f"at://{config.community_did}/{collection}/{rkey}"
    journal = ports.operation_journal
    durable_id = operation_id or f"{collection}:{rkey}"
    intended = record
    if journal is not None:
        prior = journal.get(durable_id)
        if prior is not None:
            if (
                prior.repo_did != config.community_did
                or prior.collection != collection
                or prior.rkey != rkey
                or _authority_defining(prior.intended_record)
                != _authority_defining(record)
            ):
                raise JournalConflictError(
                    "operation id was reused for different authority input"
                )
            intended = prior.intended_record
        entry = journal.prepare(
            operation_id=durable_id,
            action=collection,
            repo_did=config.community_did,
            collection=collection,
            rkey=rkey,
            intended_record=intended,
        )
        if entry.state == "committed":
            assert entry.result_uri is not None and entry.result_cid is not None
            return OperationOutcome(
                operation="existing",
                record=RecordRef(uri=entry.result_uri, cid=entry.result_cid),
            )
        if entry.state in {"conflict", "refused"}:
            raise JournalConflictError("authority operation is terminal")
        if entry.state == "attempted_unknown":
            reconciled = _reconcile_journaled_write(ports, journal, entry)
            if reconciled is not None:
                return reconciled
            # A direct authority-repository read established exact absence.
            # This is the sole safe transition that permits one new attempt.
            if not retain_attempt_marker:
                journal.transition(durable_id, "prepared")
    if before_dispatch is not None:
        before_dispatch()
    if journal is not None:
        journal.transition(durable_id, "attempted_unknown")
    try:
        # The writer performs the single existence check at the rkey and
        # reports whether it committed; no separate reader pre-read.
        outcome = ports.writer.create_immutable(
            config.community_did, collection, rkey, intended
        )
    except PortUnavailableError as exc:
        if journal is not None:
            entry = journal.get(durable_id)
            assert entry is not None
            try:
                reconciled = _reconcile_journaled_write(ports, journal, entry)
                if reconciled is not None:
                    return reconciled
            except PortUnavailableError:
                pass
        raise WriteFailedError("authority write failed or remained ambiguous") from exc
    if outcome.reference.uri != uri:
        raise WriteFailedError("authority writer returned an unexpected record URI")
    operation: Literal["created", "existing"] = (
        "created" if outcome.created else "existing"
    )
    if journal is not None:
        journal.transition(
            durable_id,
            "committed",
            result_uri=outcome.reference.uri,
            result_cid=outcome.reference.cid,
        )
    return OperationOutcome(operation=operation, record=outcome.reference)


def _authority_defining(record: Mapping[str, object]) -> bytes:
    return canonical_json_bytes(
        {key: value for key, value in record.items() if key != "createdAt"}
    )


def _reconcile_journaled_write(
    ports: DaemonPorts,
    journal: SQLiteOperationJournal,
    entry: object,
) -> OperationOutcome | None:
    from .journal import JournalEntry

    assert isinstance(entry, JournalEntry)
    result = (ports.authority_reader or ports.reader).get_current(entry.record_uri)
    if result.status is CurrentRecordStatus.ERROR:
        raise PortUnavailableError("authority readback is unavailable")
    if result.status is CurrentRecordStatus.MISSING:
        return None
    assert result.record is not None and result.current_cid is not None
    if _authority_defining(result.record) != _authority_defining(entry.intended_record):
        journal.transition(entry.operation_id, "conflict")
        raise JournalConflictError("authority rkey contains incompatible content")
    journal.transition(
        entry.operation_id,
        "committed",
        result_uri=entry.record_uri,
        result_cid=result.current_cid,
    )
    return OperationOutcome(
        operation="created",
        record=RecordRef(uri=entry.record_uri, cid=result.current_cid),
    )


def admit(
    ports: DaemonPorts,
    config: DaemonConfig,
    submission: RecordRef,
    *,
    now: datetime,
    operation_id: str | None = None,
    before_dispatch: Callable[[], None] | None = None,
    retain_attempt_marker: bool = False,
) -> OperationOutcome:
    """Create an immutable admission for one exact, current self-submission."""

    admin = _authorize(ports, config, "admit")
    submission_record_raw = _resolve_exact(ports.reader, submission, role="submission")
    context = ValidationContext(
        community_did=config.community_did,
        repo_did=submission.repo_did,
        collection=SUBMISSION_COLLECTION,
        rkey=submission.rkey,
        operation="create",
        record_cid=submission.cid,
        administrator_did=config.administrator_did,
    )
    parsed = _parsed_record(submission_record_raw, context)
    assert isinstance(parsed, SubmissionRecord)
    subject = parsed.subject
    _resolve_exact(ports.reader, subject, role="subject")

    lifecycle = ports.ledger.find_subject_lifecycle(config.community_did, subject)
    if lifecycle.valid_removals:
        raise UnsupportedReadmissionError(
            "a valid removal already terminalizes this exact subject"
        )

    record = AdmissionRecord(
        submission=submission,
        subject=subject,
        actor=admin.did,
        created_at=now,
        created_at_raw=format_rfc3339(now),
    ).to_record()
    return _create_at_deterministic_rkey(
        ports,
        config,
        collection=ADMISSION_COLLECTION,
        rkey=admission_rkey(submission),
        record=record,
        operation_id=operation_id,
        before_dispatch=before_dispatch,
        retain_attempt_marker=retain_attempt_marker,
    )


def remove(
    ports: DaemonPorts,
    config: DaemonConfig,
    admission: RecordRef,
    reason: str | None,
    *,
    now: datetime,
    operation_id: str | None = None,
) -> OperationOutcome:
    """Create an immutable removal for one exact admission, stale post or not."""

    admin = _authorize(ports, config, "remove")
    admission_record_raw = _resolve_exact(ports.reader, admission, role="admission")
    context = ValidationContext(
        community_did=config.community_did,
        repo_did=admission.repo_did,
        collection=ADMISSION_COLLECTION,
        rkey=admission.rkey,
        operation="create",
        record_cid=admission.cid,
        administrator_did=config.administrator_did,
    )
    parsed = _parsed_record(admission_record_raw, context)
    assert isinstance(parsed, AdmissionRecord)

    record = ModActionRecord(
        action="remove",
        admission=admission,
        subject=parsed.subject,
        actor=admin.did,
        reason=reason,
        created_at=now,
        created_at_raw=format_rfc3339(now),
    ).to_record()
    return _create_at_deterministic_rkey(
        ports,
        config,
        collection=MOD_ACTION_COLLECTION,
        rkey=removal_rkey(admission),
        record=record,
        operation_id=operation_id,
    )


def change_membership(
    ports: DaemonPorts,
    config: DaemonConfig,
    subject_did: str,
    action: Literal["add", "remove"],
    reason: str | None,
    *,
    now: datetime,
    operation_id: str | None = None,
) -> OperationOutcome:
    """Create one authority-owned membership transition.

    V0 deliberately permits only one add and one terminal remove per DID. A
    future re-enrollment policy needs an explicit chain design rather than an
    ambiguous overwrite.
    """

    admin = _authorize(ports, config, "membership")
    validate_did(subject_did)
    if action not in {"add", "remove"}:
        raise ValidationError("unsupported_action", "membership action is unsupported")
    authority_reader = ports.authority_reader or ports.reader
    required_action = "remove" if action == "add" else "add"
    required_uri = (
        f"at://{config.community_did}/{MEMBER_ACTION_COLLECTION}/"
        f"{member_action_rkey(subject_did, required_action)}"
    )
    standing = authority_reader.get_current(required_uri)
    if standing.status is CurrentRecordStatus.ERROR:
        raise PortUnavailableError("membership lifecycle readback is unavailable")
    if action == "add" and standing.status is CurrentRecordStatus.PRESENT:
        raise ValidationError(
            "unsupported_readmission", "removed membership is terminal in V0"
        )
    if action == "remove" and standing.status is CurrentRecordStatus.MISSING:
        raise ValidationError(
            "reference_missing", "membership removal requires a prior add"
        )
    record = MemberActionRecord(
        action=action,
        subject=subject_did,
        actor=admin.did,
        reason=reason,
        created_at=now,
        created_at_raw=format_rfc3339(now),
    ).to_record()
    return _create_at_deterministic_rkey(
        ports,
        config,
        collection=MEMBER_ACTION_COLLECTION,
        rkey=member_action_rkey(subject_did, action),
        record=record,
        operation_id=operation_id,
    )


__all__ = [
    "DaemonPorts",
    "LocalAdminAuthorizer",
    "OperationOutcome",
    "admit",
    "change_membership",
    "remove",
]
