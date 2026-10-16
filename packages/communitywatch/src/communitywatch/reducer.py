"""Pure V0 projection rules over persisted observer facts.

This module has no SQLite, transport, clock, or filesystem dependency.  The
storage layer translates immutable rows into these facts and materializes the
returned projection under a generation identifier.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from community_model import (
    ADMISSION_COLLECTION,
    COMMUNITY_COLLECTIONS,
    MEMBER_ACTION_COLLECTION,
    MOD_ACTION_COLLECTION,
    PROFILE_COLLECTION,
    REPLY_ACTION_COLLECTION,
    REPLY_ADMISSION_COLLECTION,
    REPLY_POLICY_COLLECTION,
    SUBMISSION_COLLECTION,
    AdmissionRecord,
    AuditOutcome,
    MemberActionRecord,
    ModActionRecord,
    ProfileRecord,
    ProjectionState,
    RecordRef,
    ReplyActionRecord,
    ReplyAdmissionRecord,
    ReplyModerationState,
    ReplyPolicyRecord,
    RepositoryOperation,
    ResolutionStatus,
    SubmissionRecord,
    ValidationContext,
    ValidationError,
    apply_reply_action,
    canonical_json_bytes,
    normalized_created_at,
    reply_moderation_key,
    sha256_digest,
    validate_admission_references,
    validate_record,
    validate_removal_references,
    validate_reply_admission_references,
    validate_reply_policy_references,
    validate_reply_submission_references,
)
from community_model.identifiers import tid_sort_key


@dataclass(frozen=True, slots=True)
class EventFact:
    semantic_event_key: str
    event_variant_key: str
    repo_did: str
    repo_order: str
    operation: str
    collection: str
    rkey: str
    record_uri: str
    record_cid: str | None
    record: Mapping[str, object] | None
    payload_hash: str
    payload_hash_scope: str
    first_observed_sequence: int
    first_received_at: datetime
    first_accepted_at: datetime | None
    receipt_count: int
    verification_outcomes: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return self.first_accepted_at is not None


@dataclass(frozen=True, slots=True)
class ObservationFact:
    observation_key: str
    subject_variant_key: str
    requested: RecordRef
    status: str
    current_cid: str | None
    record: Mapping[str, object] | None
    payload_hash: str
    payload_hash_scope: str
    triggering_event_variant_key: str | None
    checked_at: datetime
    observer_sequence: int
    trust_mode: str
    verification_outcome: str
    resolution_method: str
    resolver_version: str
    evidence_ref: str | None
    evidence_hash: str | None
    accepted: bool


@dataclass(frozen=True, slots=True)
class ReducerConfig:
    community_did: str
    administrator_did: str


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    records_current: tuple[Mapping[str, object], ...]
    community_profiles: tuple[Mapping[str, object], ...]
    ledger_records: tuple[Mapping[str, object], ...]
    subject_current: tuple[Mapping[str, object], ...]
    admission_lifecycles: tuple[Mapping[str, object], ...]
    community_entries: tuple[Mapping[str, object], ...]
    discussion_roots: tuple[Mapping[str, object], ...]
    discussion_replies: tuple[Mapping[str, object], ...]
    discussion_activity: tuple[Mapping[str, object], ...]
    projection_findings: tuple[Mapping[str, object], ...]
    audit_index: tuple[Mapping[str, object], ...]


def _event_sort_key(event: EventFact) -> tuple[int, str, str]:
    return (
        tid_sort_key(event.repo_order),
        event.record_uri,
        event.event_variant_key,
    )


def _record_identity(event: EventFact) -> tuple[str | None, bytes | None]:
    encoded = None if event.record is None else canonical_json_bytes(event.record)
    return event.record_cid, encoded


def _ref_key(ref: RecordRef) -> tuple[str, str]:
    return ref.uri, ref.cid


def _ref_dict(ref: RecordRef) -> dict[str, str]:
    return {"uri": ref.uri, "cid": ref.cid}


def _logical_lifecycle_key(submission: RecordRef) -> str:
    return sha256_digest(
        b"v0\x00lifecycle\x00"
        + submission.uri.encode("utf-8")
        + b"\x00"
        + submission.cid.encode("ascii")
    )


def _kind(collection: str) -> str:
    return {
        PROFILE_COLLECTION: "profile",
        SUBMISSION_COLLECTION: "submission",
        ADMISSION_COLLECTION: "admission",
        MOD_ACTION_COLLECTION: "removal",
        MEMBER_ACTION_COLLECTION: "member_action",
        REPLY_POLICY_COLLECTION: "reply_policy",
        REPLY_ADMISSION_COLLECTION: "reply_admission",
        REPLY_ACTION_COLLECTION: "reply_action",
    }.get(collection, "ignored")


def _authenticity_reasons(event: EventFact) -> tuple[str, ...]:
    if event.accepted:
        return ()
    if "failed" in event.verification_outcomes:
        return ("authenticity_failed",)
    return ("authenticity_unverified",)


def _outcome_for_error(reason: str) -> str:
    if reason in {"authority_repo_mismatch", "actor_unauthorized"}:
        return AuditOutcome.UNAUTHORIZED.value
    if reason == "reference_pending":
        return AuditOutcome.PENDING.value
    return AuditOutcome.INVALID.value


def _state_for_observation(observation: ObservationFact | None) -> str:
    if observation is None:
        return ProjectionState.PENDING.value
    if not observation.accepted:
        return ProjectionState.SUBJECT_UNAVAILABLE.value
    return {
        ResolutionStatus.EXACT.value: ProjectionState.VISIBLE.value,
        ResolutionStatus.MISMATCH.value: ProjectionState.STALE_CID.value,
        ResolutionStatus.MISSING.value: ProjectionState.SUBJECT_DELETED.value,
        ResolutionStatus.ERROR.value: ProjectionState.SUBJECT_UNAVAILABLE.value,
    }[observation.status]


def _state_rank(state: str) -> int:
    return {
        ProjectionState.REMOVED.value: 90,
        "author_withdrawn": 75,
        ProjectionState.CONFLICT.value: 80,
        ProjectionState.SUBJECT_DELETED.value: 70,
        ProjectionState.STALE_CID.value: 60,
        ProjectionState.SUBJECT_UNAVAILABLE.value: 50,
        ProjectionState.VISIBLE.value: 40,
        ProjectionState.PENDING.value: 30,
        ProjectionState.SUBMITTED.value: 20,
        ProjectionState.UNAUTHORIZED.value: 10,
        ProjectionState.INVALID.value: 0,
    }[state]


def reduce_projection(
    events: Sequence[EventFact],
    observations: Sequence[ObservationFact],
    *,
    config: ReducerConfig,
) -> ProjectionResult:
    """Reduce immutable observer facts into deterministic generation rows."""

    events_by_semantic: dict[str, list[EventFact]] = defaultdict(list)
    for event in events:
        events_by_semantic[event.semantic_event_key].append(event)

    conflict_variants: set[str] = set()
    for variants in events_by_semantic.values():
        accepted = [event for event in variants if event.accepted]
        identities = {_record_identity(event) for event in accepted}
        if len(identities) > 1:
            conflict_variants.update(event.event_variant_key for event in accepted)

    current_by_uri: dict[str, EventFact] = {}
    for event in events:
        if not event.accepted or event.event_variant_key in conflict_variants:
            continue
        current = current_by_uri.get(event.record_uri)
        if current is None or _event_sort_key(event) > _event_sort_key(current):
            current_by_uri[event.record_uri] = event

    records_current: list[Mapping[str, object]] = []
    for uri, event in sorted(current_by_uri.items()):
        records_current.append(
            {
                "record_uri": uri,
                "event_variant_key": event.event_variant_key,
                "repo_order": event.repo_order,
                "record_cid": event.record_cid,
                "deleted": event.operation == RepositoryOperation.DELETE.value,
            }
        )

    validation_by_variant: dict[str, tuple[str, tuple[str, ...], object | None]] = {}
    ledger_records: list[Mapping[str, object]] = []
    audit_index: list[Mapping[str, object]] = []
    findings: list[Mapping[str, object]] = []

    for event in sorted(events, key=lambda item: item.event_variant_key):
        reasons: tuple[str, ...] = ()
        parsed: object | None = None
        outcome = AuditOutcome.VALID.value

        if event.collection not in COMMUNITY_COLLECTIONS:
            outcome = AuditOutcome.IGNORED.value
        elif event.event_variant_key in conflict_variants:
            outcome = AuditOutcome.CONFLICT.value
            reasons = ("semantic_event_conflict",)
        elif not event.accepted:
            outcome = AuditOutcome.UNAUTHORIZED.value
            reasons = _authenticity_reasons(event)
        elif event.operation == RepositoryOperation.DELETE.value:
            if event.collection in {
                ADMISSION_COLLECTION,
                MOD_ACTION_COLLECTION,
                MEMBER_ACTION_COLLECTION,
                REPLY_POLICY_COLLECTION,
                REPLY_ADMISSION_COLLECTION,
                REPLY_ACTION_COLLECTION,
            }:
                outcome = AuditOutcome.CONFLICT.value
                reasons = ("authority_record_mutated",)
            else:
                outcome = AuditOutcome.VALID.value
        elif event.record is None or event.record_cid is None:
            outcome = AuditOutcome.INVALID.value
            reasons = ("schema_invalid",)
        else:
            try:
                validated = validate_record(
                    event.record,
                    context=ValidationContext(
                        community_did=config.community_did,
                        repo_did=event.repo_did,
                        collection=event.collection,
                        rkey=event.rkey,
                        operation=event.operation,
                        record_cid=event.record_cid,
                        administrator_did=config.administrator_did,
                        first_accepted_at=event.first_accepted_at,
                    ),
                )
                parsed = validated.record
                reasons = validated.findings
            except ValidationError as exc:
                outcome = _outcome_for_error(exc.reason_code)
                reasons = (exc.reason_code,)

        if event.event_variant_key in conflict_variants and event.accepted:
            if (
                parsed is None
                and event.record is not None
                and event.record_cid is not None
            ):
                try:
                    parsed = validate_record(
                        event.record,
                        context=ValidationContext(
                            community_did=config.community_did,
                            repo_did=event.repo_did,
                            collection=event.collection,
                            rkey=event.rkey,
                            operation=event.operation,
                            record_cid=event.record_cid,
                            administrator_did=config.administrator_did,
                            first_accepted_at=event.first_accepted_at,
                        ),
                    ).record
                except ValidationError:
                    pass
            outcome = AuditOutcome.CONFLICT.value
            reasons = ("semantic_event_conflict",)

        validation_by_variant[event.event_variant_key] = (outcome, reasons, parsed)
        subject = (
            parsed.subject
            if isinstance(
                parsed,
                SubmissionRecord
                | AdmissionRecord
                | ModActionRecord
                | ReplyAdmissionRecord
                | ReplyActionRecord,
            )
            else None
        )
        if isinstance(parsed, MemberActionRecord):
            subject = parsed.subject
        actor = (
            parsed.actor
            if isinstance(
                parsed,
                AdmissionRecord
                | ModActionRecord
                | MemberActionRecord
                | ReplyPolicyRecord
                | ReplyAdmissionRecord
                | ReplyActionRecord,
            )
            else None
        )
        reason = (
            parsed.reason
            if isinstance(
                parsed, ModActionRecord | MemberActionRecord | ReplyActionRecord
            )
            else None
        )
        signed_created_at = (
            normalized_created_at(parsed) if parsed is not None else None
        )
        audit_index.append(
            {
                "audit_row_key": (
                    f"event:{event.semantic_event_key}:{event.event_variant_key}"
                ),
                "kind": _kind(event.collection),
                "semantic_event_key": event.semantic_event_key,
                "event_variant_key": event.event_variant_key,
                "record_uri": event.record_uri,
                "record_cid": event.record_cid,
                "subject_uri": (
                    None
                    if subject is None
                    else subject
                    if isinstance(subject, str)
                    else subject.uri
                ),
                "subject_cid": (
                    None if subject is None or isinstance(subject, str) else subject.cid
                ),
                "actor": actor,
                "reason": reason,
                "signed_created_at": signed_created_at,
                "payload_hash": event.payload_hash,
                "payload_hash_scope": event.payload_hash_scope,
                "first_received_at": event.first_received_at.isoformat(),
                "observer_sequence": event.first_observed_sequence,
                "outcome": outcome,
                "reason_codes": reasons,
                "receipt_count": event.receipt_count,
                "verification_outcomes": event.verification_outcomes,
            }
        )
        if event.collection in COMMUNITY_COLLECTIONS:
            ledger_records.append(
                {
                    "event_variant_key": event.event_variant_key,
                    "record_uri": event.record_uri,
                    "record_cid": event.record_cid,
                    "kind": _kind(event.collection),
                    "repo_did": event.repo_did,
                    "repo_order": event.repo_order,
                    "operation": event.operation,
                    "outcome": outcome,
                    "reason_codes": reasons,
                    "normalized_record": (
                        parsed.to_record() if parsed is not None else None  # type: ignore[union-attr]
                    ),
                    "first_observed_sequence": event.first_observed_sequence,
                }
            )
        for reason in reasons:
            findings.append(
                {
                    "finding_key": (f"event:{event.event_variant_key}:{reason}"),
                    "event_variant_key": event.event_variant_key,
                    "subject_uri": None,
                    "subject_cid": None,
                    "reason_code": reason,
                }
            )

    record_versions: dict[tuple[str, str], tuple[EventFact, object]] = {}
    for event in events:
        outcome, _, parsed = validation_by_variant.get(
            event.event_variant_key, ("", (), None)
        )
        if (
            outcome == AuditOutcome.VALID.value
            and event.record_cid is not None
            and parsed is not None
        ):
            key = (event.record_uri, event.record_cid)
            existing = record_versions.get(key)
            if (
                existing is None
                or event.first_observed_sequence < existing[0].first_observed_sequence
            ):
                record_versions[key] = (event, parsed)

    submissions: dict[tuple[str, str], tuple[EventFact, SubmissionRecord]] = {
        key: (event, parsed)
        for key, (event, parsed) in record_versions.items()
        if isinstance(parsed, SubmissionRecord)
    }
    admissions: dict[tuple[str, str], tuple[EventFact, AdmissionRecord]] = {
        key: (event, parsed)
        for key, (event, parsed) in record_versions.items()
        if isinstance(parsed, AdmissionRecord)
    }
    removals: list[tuple[EventFact, ModActionRecord]] = [
        (event, parsed)
        for event, parsed in record_versions.values()
        if isinstance(parsed, ModActionRecord)
    ]
    reply_policies: dict[tuple[str, str], tuple[EventFact, ReplyPolicyRecord]] = {
        key: (event, parsed)
        for key, (event, parsed) in record_versions.items()
        if isinstance(parsed, ReplyPolicyRecord)
    }
    reply_admissions: dict[tuple[str, str], tuple[EventFact, ReplyAdmissionRecord]] = {
        key: (event, parsed)
        for key, (event, parsed) in record_versions.items()
        if isinstance(parsed, ReplyAdmissionRecord)
    }
    reply_actions: list[tuple[EventFact, ReplyActionRecord]] = [
        (event, parsed)
        for event, parsed in record_versions.values()
        if isinstance(parsed, ReplyActionRecord)
    ]

    accepted_observations = [item for item in observations if item.accepted]
    observations_by_ref: dict[tuple[str, str], list[ObservationFact]] = defaultdict(
        list
    )
    for observation in observations:
        observations_by_ref[_ref_key(observation.requested)].append(observation)

    subject_current: list[Mapping[str, object]] = []
    for ref_key, items in sorted(observations_by_ref.items()):
        current = max(
            items, key=lambda item: (item.observer_sequence, item.observation_key)
        )
        subject_current.append(
            {
                "subject_uri": ref_key[0],
                "subject_cid": ref_key[1],
                "observation_key": current.observation_key,
                "status": current.status,
                "current_cid": current.current_cid,
                "observer_sequence": current.observer_sequence,
                "accepted": current.accepted,
            }
        )

    for observation in sorted(observations, key=lambda item: item.observation_key):
        reasons: tuple[str, ...]
        outcome: str
        if not observation.accepted:
            outcome = AuditOutcome.INVALID.value
            reasons = (
                "authenticity_failed"
                if observation.verification_outcome == "failed"
                else "authenticity_unverified",
            )
        elif observation.status == ResolutionStatus.MISMATCH.value:
            outcome = AuditOutcome.VALID.value
            reasons = ("subject_cid_mismatch",)
        elif observation.status == ResolutionStatus.MISSING.value:
            outcome = AuditOutcome.VALID.value
            reasons = ("subject_deleted",)
        elif observation.status == ResolutionStatus.ERROR.value:
            outcome = AuditOutcome.PENDING.value
            reasons = ("resolver_error",)
        else:
            outcome = AuditOutcome.VALID.value
            reasons = ()
        audit_index.append(
            {
                "audit_row_key": f"observation:{observation.observation_key}",
                "kind": "subject_observation",
                "semantic_event_key": None,
                "event_variant_key": observation.triggering_event_variant_key,
                "record_uri": None,
                "record_cid": None,
                "subject_uri": observation.requested.uri,
                "subject_cid": observation.requested.cid,
                "actor": None,
                "reason": None,
                "signed_created_at": None,
                "payload_hash": observation.payload_hash,
                "payload_hash_scope": observation.payload_hash_scope,
                "first_received_at": observation.checked_at.isoformat(),
                "observer_sequence": observation.observer_sequence,
                "outcome": outcome,
                "reason_codes": reasons,
                "receipt_count": 1,
                "verification_outcomes": (observation.verification_outcome,),
            }
        )

    valid_removals: list[
        tuple[EventFact, ModActionRecord, EventFact, AdmissionRecord]
    ] = []
    for event, removal in removals:
        admission_pair = admissions.get(_ref_key(removal.admission))
        if admission_pair is None:
            findings.append(
                {
                    "finding_key": f"event:{event.event_variant_key}:reference_missing",
                    "event_variant_key": event.event_variant_key,
                    "subject_uri": removal.subject.uri,
                    "subject_cid": removal.subject.cid,
                    "reason_code": "reference_missing",
                }
            )
            continue
        admission_event, admission = admission_pair
        try:
            validate_removal_references(removal, admission)
        except ValidationError as exc:
            findings.append(
                {
                    "finding_key": f"event:{event.event_variant_key}:{exc.reason_code}",
                    "event_variant_key": event.event_variant_key,
                    "subject_uri": removal.subject.uri,
                    "subject_cid": removal.subject.cid,
                    "reason_code": exc.reason_code,
                }
            )
            continue
        valid_removals.append((event, removal, admission_event, admission))

    removal_by_subject: dict[tuple[str, str], tuple[EventFact, ModActionRecord]] = {}
    for event, removal, _, admission in valid_removals:
        key = _ref_key(admission.subject)
        candidate = (event, removal)
        current = removal_by_subject.get(key)
        if current is None or _event_sort_key(event) < _event_sort_key(current[0]):
            removal_by_subject[key] = candidate

    lifecycles: list[dict[str, object]] = []
    terminal_by_subject: dict[tuple[str, str], int] = {}
    admission_items = sorted(
        admissions.items(),
        key=lambda item: (
            item[1][0].first_observed_sequence,
            item[0],
        ),
    )
    for admission_key, (event, admission) in admission_items:
        submission_pair = submissions.get(_ref_key(admission.submission))
        state = ProjectionState.PENDING.value
        reason_codes: tuple[str, ...] = ("reference_pending",)
        start: ObservationFact | None = None
        terminal: ObservationFact | None = None
        eligible = False

        if submission_pair is not None:
            submission_event, submission = submission_pair
            if submission.discussion is not None:
                findings.append(
                    {
                        "finding_key": f"lifecycle:{event.event_variant_key}:strong_ref_mismatch",
                        "event_variant_key": event.event_variant_key,
                        "subject_uri": admission.subject.uri,
                        "subject_cid": admission.subject.cid,
                        "reason_code": "strong_ref_mismatch",
                    }
                )
                continue
            try:
                validate_admission_references(admission, submission)
            except ValidationError as exc:
                state = ProjectionState.INVALID.value
                reason_codes = (exc.reason_code,)
            else:
                subject_key = _ref_key(admission.subject)
                starts = [
                    item
                    for item in accepted_observations
                    if item.triggering_event_variant_key == event.event_variant_key
                    and _ref_key(item.requested) == subject_key
                ]
                if starts:
                    start = min(
                        starts,
                        key=lambda item: (
                            item.observer_sequence,
                            item.observation_key,
                        ),
                    )
                    prior_terminal = terminal_by_subject.get(subject_key, 0)
                    eligible = (
                        submission_event.first_observed_sequence > prior_terminal
                        and event.first_observed_sequence > prior_terminal
                    )
                    later = sorted(
                        (
                            item
                            for item in observations
                            if _ref_key(item.requested) == subject_key
                            and item.observer_sequence >= start.observer_sequence
                        ),
                        key=lambda item: (
                            item.observer_sequence,
                            item.observation_key,
                        ),
                    )
                    terminals = [
                        item
                        for item in later
                        if item.accepted
                        and item.status
                        in {
                            ResolutionStatus.MISMATCH.value,
                            ResolutionStatus.MISSING.value,
                        }
                    ]
                    if terminals:
                        # Terminality never reverts, and eligibility is
                        # measured against the latest terminal observation.
                        # A confirmed deletion supersedes an earlier mismatch
                        # flavor (stale_cid -> subject_deleted).
                        terminal = terminals[-1]
                        terminal_by_subject[subject_key] = max(
                            terminal_by_subject.get(subject_key, 0),
                            terminal.observer_sequence,
                        )
                        if any(
                            item.status == ResolutionStatus.MISSING.value
                            for item in terminals
                        ):
                            state = ProjectionState.SUBJECT_DELETED.value
                            reason_codes = ("subject_deleted",)
                        else:
                            state = ProjectionState.STALE_CID.value
                            reason_codes = ("subject_cid_mismatch",)
                    elif not eligible:
                        state = ProjectionState.STALE_CID.value
                        reason_codes = ("subject_cid_mismatch",)
                    else:
                        latest = max(
                            later,
                            key=lambda item: (
                                item.observer_sequence,
                                item.observation_key,
                            ),
                            default=start,
                        )
                        state = _state_for_observation(latest)
                        reason_codes = {
                            ProjectionState.VISIBLE.value: (),
                            ProjectionState.SUBJECT_UNAVAILABLE.value: (
                                "resolver_error",
                            ),
                        }.get(state, ())
                else:
                    reason_codes = ("reference_pending",)

        subject_key = _ref_key(admission.subject)
        # OQ-5 (operator-ruled 2026-08-14, answer A): a submission is signed
        # intent at admission time.  Updating or deleting it after a valid
        # admission never revokes the admission; the mutation stays
        # audit-visible through its own event row.  A mutation the observer
        # had already accepted before first observing the admission is
        # different: the admission never referenced a current submission, so
        # it is rejected rather than revived by replay.  Supersession is
        # decided by author-repo revision order; "before first validation" is
        # decided by first-observed observer sequence.
        if submission_pair is not None and state != ProjectionState.INVALID.value:
            referenced_order = tid_sort_key(submission_pair[0].repo_order)
            submission_superseded_before_admission = any(
                candidate.accepted
                and candidate.event_variant_key not in conflict_variants
                and candidate.record_uri == admission.submission.uri
                and tid_sort_key(candidate.repo_order) > referenced_order
                and candidate.first_observed_sequence < event.first_observed_sequence
                and (
                    candidate.operation == RepositoryOperation.DELETE.value
                    or candidate.record_cid != admission.submission.cid
                )
                for candidate in events
            )
            if submission_superseded_before_admission:
                state = ProjectionState.INVALID.value
                reason_codes = ("reference_missing",)

        # Authority records are create-only.  An accepted update/delete (or an
        # occupied deterministic rkey with differing content) fails the
        # admission closed; it can never grant or preserve visibility.
        admission_mutated = any(
            candidate.accepted
            and candidate.event_variant_key not in conflict_variants
            and candidate.record_uri == admission_key[0]
            and candidate.event_variant_key != event.event_variant_key
            and (
                candidate.operation != RepositoryOperation.CREATE.value
                or candidate.record_cid != admission_key[1]
            )
            for candidate in events
        )
        if admission_mutated:
            state = ProjectionState.CONFLICT.value
            reason_codes = ("authority_record_mutated",)

        removal = removal_by_subject.get(subject_key)
        if removal is not None:
            state = ProjectionState.REMOVED.value
            reason_codes = ()
            if _event_sort_key(event) > _event_sort_key(removal[0]):
                findings.append(
                    {
                        "finding_key": (
                            f"lifecycle:{event.event_variant_key}"
                            ":unsupported_readmission"
                        ),
                        "event_variant_key": event.event_variant_key,
                        "subject_uri": admission.subject.uri,
                        "subject_cid": admission.subject.cid,
                        "reason_code": "unsupported_readmission",
                    }
                )

        submission_withdrawn = any(
            candidate.accepted
            and candidate.record_uri == admission.submission.uri
            and _event_sort_key(candidate) > _event_sort_key(event)
            and (
                candidate.operation == RepositoryOperation.DELETE.value
                or candidate.record_cid != admission.submission.cid
            )
            for candidate in events
        )
        if (
            submission_withdrawn
            and removal is None
            and state == ProjectionState.VISIBLE.value
        ):
            state = "author_withdrawn"
            reason_codes = ()

        if event.event_variant_key in conflict_variants:
            state = ProjectionState.CONFLICT.value
            reason_codes = ("semantic_event_conflict",)

        lifecycle = {
            "admission_uri": admission_key[0],
            "admission_cid": admission_key[1],
            "admission_event_variant_key": event.event_variant_key,
            "submission_uri": admission.submission.uri,
            "submission_cid": admission.submission.cid,
            "subject_uri": admission.subject.uri,
            "subject_cid": admission.subject.cid,
            "logical_lifecycle_key": _logical_lifecycle_key(admission.submission),
            "admitted_at": normalized_created_at(admission),
            "admission_first_observed_sequence": event.first_observed_sequence,
            "start_observation_key": (None if start is None else start.observation_key),
            "start_sequence": None if start is None else start.observer_sequence,
            "terminal_observation_key": (
                None if terminal is None else terminal.observation_key
            ),
            "terminal_sequence": (
                None if terminal is None else terminal.observer_sequence
            ),
            "removal_uri": None if removal is None else removal[0].record_uri,
            "removal_cid": None if removal is None else removal[0].record_cid,
            "status": state,
            "reason_codes": reason_codes,
            "eligible": eligible,
        }
        lifecycles.append(lifecycle)
        for reason in reason_codes:
            findings.append(
                {
                    "finding_key": (f"lifecycle:{event.event_variant_key}:{reason}"),
                    "event_variant_key": event.event_variant_key,
                    "subject_uri": admission.subject.uri,
                    "subject_cid": admission.subject.cid,
                    "reason_code": reason,
                }
            )

    community_entries: list[Mapping[str, object]] = []
    lifecycles_by_subject: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(
        list
    )
    for lifecycle in lifecycles:
        lifecycles_by_subject[
            (str(lifecycle["subject_uri"]), str(lifecycle["subject_cid"]))
        ].append(lifecycle)
    for subject_key, items in sorted(lifecycles_by_subject.items()):
        # Eligible visible lifecycles render; terminal history of superseded
        # lifecycles for the same exact subject stays in audit without
        # masking them.  Removals mask every lifecycle of the exact subject,
        # so a visible candidate can never outrank a valid removal.
        visible = [
            item for item in items if item["status"] == ProjectionState.VISIBLE.value
        ]
        candidates = visible or items
        state = max((str(item["status"]) for item in candidates), key=_state_rank)
        canonical = min(
            candidates,
            key=lambda item: (
                str(item["admitted_at"]),
                str(item["admission_uri"]),
            ),
        )
        community_entries.append(
            {
                "community_did": config.community_did,
                "subject_uri": subject_key[0],
                "subject_cid": subject_key[1],
                "submission_uri": canonical["submission_uri"],
                "submission_cid": canonical["submission_cid"],
                "admission_uri": canonical["admission_uri"],
                "admission_cid": canonical["admission_cid"],
                "admitted_at": canonical["admitted_at"],
                "status": state,
            }
        )

    valid_reply_admissions: dict[
        tuple[str, str], tuple[EventFact, ReplyAdmissionRecord, ObservationFact | None]
    ] = {}
    eligible_reply_uris: dict[tuple[str, str], set[str]] = defaultdict(set)
    discussion_replies: list[Mapping[str, object]] = []
    reply_activity: list[Mapping[str, object]] = []
    reply_last_sequence: dict[tuple[str, str], int] = defaultdict(int)

    for admission_key, (event, reply_admission) in sorted(
        reply_admissions.items(), key=lambda item: _event_sort_key(item[1][0])
    ):
        submission_pair = submissions.get(_ref_key(reply_admission.submission))
        policy_pair = reply_policies.get(_ref_key(reply_admission.policy))
        root_pair = admissions.get(_ref_key(reply_admission.discussion))
        if submission_pair is None or policy_pair is None or root_pair is None:
            findings.append(
                {
                    "finding_key": f"reply:{event.event_variant_key}:reference_missing",
                    "event_variant_key": event.event_variant_key,
                    "subject_uri": reply_admission.subject.uri,
                    "subject_cid": reply_admission.subject.cid,
                    "reason_code": "reference_missing",
                }
            )
            continue
        submission_event, submission = submission_pair
        _, policy = policy_pair
        root_event, root_admission = root_pair
        root_key = _ref_key(reply_admission.discussion)
        closure = removal_by_subject.get(_ref_key(root_admission.subject))
        try:
            validate_reply_policy_references(policy, reply_admission.discussion)
            validate_reply_admission_references(
                reply_admission,
                submission,
                policy,
                submission_ref=reply_admission.submission,
                policy_ref=reply_admission.policy,
            )
            if closure is not None and _event_sort_key(closure[0]) < _event_sort_key(
                event
            ):
                raise ValidationError(
                    "discussion_closed", "discussion closed before reply admission"
                )
        except ValidationError as exc:
            findings.append(
                {
                    "finding_key": f"reply:{event.event_variant_key}:{exc.reason_code}",
                    "event_variant_key": event.event_variant_key,
                    "subject_uri": reply_admission.subject.uri,
                    "subject_cid": reply_admission.subject.cid,
                    "reason_code": exc.reason_code,
                }
            )
            continue

        subject_key = _ref_key(reply_admission.subject)
        starts = [
            item
            for item in accepted_observations
            if item.triggering_event_variant_key == event.event_variant_key
            and _ref_key(item.requested) == subject_key
        ]
        start = (
            min(starts, key=lambda item: (item.observer_sequence, item.observation_key))
            if starts
            else None
        )
        state = _state_for_observation(start)
        parent_uri: str | None = None
        parent_cid: str | None = None
        ancestry_valid = False
        if start is not None and start.record is not None:
            try:
                reply = start.record["reply"]
                if not isinstance(reply, Mapping):
                    raise ValidationError(
                        "reply_ancestry_invalid", "reply field unavailable"
                    )
                root_ref = RecordRef.from_mapping(reply["root"], path=("reply", "root"))
                parent_ref = RecordRef.from_mapping(
                    reply["parent"], path=("reply", "parent")
                )
                validate_reply_submission_references(
                    submission,
                    root_admission,
                    root_admission_ref=reply_admission.discussion,
                    reply_root=root_ref,
                    reply_parent=parent_ref,
                    eligible_parent_uris=frozenset(eligible_reply_uris[root_key]),
                )
                parent_uri, parent_cid = parent_ref.uri, parent_ref.cid
                ancestry_valid = True
            except (KeyError, TypeError, ValidationError) as exc:
                state = ProjectionState.INVALID.value
                code = (
                    exc.reason_code
                    if isinstance(exc, ValidationError)
                    else "reply_ancestry_invalid"
                )
                findings.append(
                    {
                        "finding_key": f"reply:{event.event_variant_key}:{code}",
                        "event_variant_key": event.event_variant_key,
                        "subject_uri": reply_admission.subject.uri,
                        "subject_cid": reply_admission.subject.cid,
                        "reason_code": code,
                    }
                )
        elif start is not None:
            state = ProjectionState.SUBJECT_UNAVAILABLE.value

        withdrawn = any(
            candidate.accepted
            and candidate.record_uri == submission_event.record_uri
            and _event_sort_key(candidate) > _event_sort_key(submission_event)
            and (
                candidate.operation == RepositoryOperation.DELETE.value
                or candidate.record_cid != submission_event.record_cid
            )
            for candidate in events
        )
        if withdrawn:
            state = "author_withdrawn"
        logical_key = reply_moderation_key(
            community_did=config.community_did,
            root_admission=reply_admission.discussion,
            reply_uri=reply_admission.subject.uri,
        )
        valid_reply_admissions[admission_key] = (event, reply_admission, start)
        if ancestry_valid and not withdrawn:
            eligible_reply_uris[root_key].add(reply_admission.subject.uri)
        discussion_replies.append(
            {
                "logical_moderation_key": logical_key,
                "root_admission_uri": root_key[0],
                "root_admission_cid": root_key[1],
                "reply_uri": reply_admission.subject.uri,
                "reply_cid": reply_admission.subject.cid,
                "author_did": reply_admission.subject.repo_did,
                "parent_uri": parent_uri,
                "parent_cid": parent_cid,
                "submission_uri": reply_admission.submission.uri,
                "submission_cid": reply_admission.submission.cid,
                "admission_uri": admission_key[0],
                "admission_cid": admission_key[1],
                "admitted_at": normalized_created_at(reply_admission),
                "status": state,
                "reason": None,
                "controlling_action_uri": None,
                "controlling_action_cid": None,
                "snapshot_observation_key": None
                if start is None
                else start.observation_key,
                "activity_sequence": event.first_observed_sequence,
            }
        )
        reply_activity.append(
            {
                "activity_key": f"reply:{event.event_variant_key}",
                "root_admission_uri": root_key[0],
                "root_admission_cid": root_key[1],
                "actor_did": reply_admission.subject.repo_did,
                "activity_type": "reply_admitted",
                "target_uri": reply_admission.subject.uri,
                "target_cid": reply_admission.subject.cid,
                "occurred_at": normalized_created_at(reply_admission),
                "observer_sequence": event.first_observed_sequence,
            }
        )
        reply_last_sequence[root_key] = max(
            reply_last_sequence[root_key], event.first_observed_sequence
        )

    moderation_states: dict[str, ReplyModerationState] = {}
    moderation_reasons: dict[str, str | None] = {}
    for action_event, action in sorted(
        reply_actions, key=lambda pair: _event_sort_key(pair[0])
    ):
        admission_pair = valid_reply_admissions.get(_ref_key(action.admission))
        if admission_pair is None:
            continue
        _, admission, _ = admission_pair
        action_ref = RecordRef(action_event.record_uri, str(action_event.record_cid))
        try:
            next_state = apply_reply_action(
                moderation_states.get(action.moderation_key),
                action,
                action_ref=action_ref,
                admission=admission,
                admission_ref=action.admission,
                community_did=config.community_did,
            )
        except ValidationError as exc:
            findings.append(
                {
                    "finding_key": f"reply-action:{action_event.event_variant_key}:{exc.reason_code}",
                    "event_variant_key": action_event.event_variant_key,
                    "subject_uri": action.subject.uri,
                    "subject_cid": action.subject.cid,
                    "reason_code": exc.reason_code,
                }
            )
            continue
        moderation_states[action.moderation_key] = next_state
        moderation_reasons[action.moderation_key] = (
            action.reason if next_state.removed else None
        )
        root_key = _ref_key(admission.discussion)
        reply_activity.append(
            {
                "activity_key": f"reply-action:{action_event.event_variant_key}",
                "root_admission_uri": root_key[0],
                "root_admission_cid": root_key[1],
                "actor_did": action.actor,
                "activity_type": "reply_removed"
                if next_state.removed
                else "reply_restored",
                "target_uri": action.subject.uri,
                "target_cid": action.subject.cid,
                "occurred_at": normalized_created_at(action),
                "observer_sequence": action_event.first_observed_sequence,
            }
        )
        reply_last_sequence[root_key] = max(
            reply_last_sequence[root_key], action_event.first_observed_sequence
        )

    for row in discussion_replies:
        moderation = moderation_states.get(str(row["logical_moderation_key"]))
        if moderation is not None and moderation.removed:
            row["status"] = ProjectionState.REMOVED.value
            row["reason"] = moderation_reasons.get(str(row["logical_moderation_key"]))
            row["controlling_action_uri"] = moderation.last_action.uri
            row["controlling_action_cid"] = moderation.last_action.cid

    latest_reply_by_logical: dict[str, Mapping[str, object]] = {}
    for row in discussion_replies:
        key = str(row["logical_moderation_key"])
        prior = latest_reply_by_logical.get(key)
        if prior is None or (
            int(row["activity_sequence"]),
            str(row["admission_uri"]),
        ) > (int(prior["activity_sequence"]), str(prior["admission_uri"])):
            latest_reply_by_logical[key] = row
    discussion_replies = list(latest_reply_by_logical.values())

    discussion_roots: list[Mapping[str, object]] = []
    discussion_activity: list[Mapping[str, object]] = list(reply_activity)
    lifecycle_by_admission = {
        (str(item["admission_uri"]), str(item["admission_cid"])): item
        for item in lifecycles
    }
    for entry in community_entries:
        admission_key = (str(entry["admission_uri"]), str(entry["admission_cid"]))
        lifecycle = lifecycle_by_admission[admission_key]
        admission_event, admission = admissions[admission_key]
        removal = removal_by_subject.get(_ref_key(admission.subject))
        last_sequence = max(
            admission_event.first_observed_sequence, reply_last_sequence[admission_key]
        )
        closed = entry["status"] != ProjectionState.VISIBLE.value
        discussion_activity.append(
            {
                "activity_key": f"root:{admission_event.event_variant_key}",
                "root_admission_uri": admission_key[0],
                "root_admission_cid": admission_key[1],
                "actor_did": admission.actor,
                "activity_type": "root_admitted",
                "target_uri": admission.subject.uri,
                "target_cid": admission.subject.cid,
                "occurred_at": normalized_created_at(admission),
                "observer_sequence": admission_event.first_observed_sequence,
            }
        )
        if removal is not None:
            removal_event, removal_record = removal
            last_sequence = max(last_sequence, removal_event.first_observed_sequence)
            discussion_activity.append(
                {
                    "activity_key": f"root-close:{removal_event.event_variant_key}",
                    "root_admission_uri": admission_key[0],
                    "root_admission_cid": admission_key[1],
                    "actor_did": removal_record.actor,
                    "activity_type": "root_closed",
                    "target_uri": admission.subject.uri,
                    "target_cid": admission.subject.cid,
                    "occurred_at": normalized_created_at(removal_record),
                    "observer_sequence": removal_event.first_observed_sequence,
                }
            )
        discussion_roots.append(
            {
                "root_admission_uri": admission_key[0],
                "root_admission_cid": admission_key[1],
                "root_subject_uri": admission.subject.uri,
                "root_subject_cid": admission.subject.cid,
                "author_did": admission.subject.repo_did,
                "admitted_at": entry["admitted_at"],
                "status": entry["status"],
                "closed": closed,
                "snapshot_observation_key": lifecycle["start_observation_key"],
                "last_activity_sequence": last_sequence,
            }
        )

    profiles: list[Mapping[str, object]] = []
    current_profile = current_by_uri.get(
        f"at://{config.community_did}/{PROFILE_COLLECTION}/self"
    )
    if current_profile is not None:
        outcome, _, parsed = validation_by_variant.get(
            current_profile.event_variant_key, ("", (), None)
        )
        if outcome == AuditOutcome.VALID.value and isinstance(parsed, ProfileRecord):
            profiles.append(
                {
                    "community_did": config.community_did,
                    "record_uri": current_profile.record_uri,
                    "record_cid": current_profile.record_cid,
                    "display_name": parsed.display_name,
                    "description": parsed.description,
                    "created_at": normalized_created_at(parsed),
                }
            )

    return ProjectionResult(
        records_current=tuple(records_current),
        community_profiles=tuple(profiles),
        ledger_records=tuple(ledger_records),
        subject_current=tuple(subject_current),
        admission_lifecycles=tuple(lifecycles),
        community_entries=tuple(community_entries),
        discussion_roots=tuple(discussion_roots),
        discussion_replies=tuple(discussion_replies),
        discussion_activity=tuple(discussion_activity),
        projection_findings=tuple(
            sorted(findings, key=lambda item: str(item["finding_key"]))
        ),
        audit_index=tuple(
            sorted(audit_index, key=lambda item: str(item["audit_row_key"]))
        ),
    )
