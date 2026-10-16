"""SA8 deterministic recovery path selection over SA2 through SA7.

Recovery can restore observability. It cannot manufacture missing provenance.
This module only orchestrates existing qualification boundaries. It contains no
fetch, retry, scheduling, persistence, authentication, or authority behavior.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType

from community_model import ValidationError

from .artifact_source import ObservedCarArtifact
from .car import extract_space_repo_evidence
from .compat import (
    ALPHA_LABEL,
    SA8_RECOVERY_DOCTRINE,
    SA8_RECOVERY_METHOD,
    SA8_RECOVERY_VERSION,
)
from .operations import OperationAcquisitionResult, OperationAcquisitionStatus
from .qualification import (
    QualificationSourceContext,
    QualifiedRepoState,
    qualify_repo_state,
)
from .reconciliation import ReconciliationDisposition, reconcile_qualified_states
from .transition import (
    TransitionStateIdentity,
    identify_qualified_repo_state,
    qualify_repo_transition,
)


def _fail(reason: str, message: str) -> None:
    raise ValidationError(reason, message)


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        _fail("spaces_recovery_invalid", "recovery time must be timezone-aware")
    return value.astimezone(UTC)


def _nonempty(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail("spaces_recovery_trace_invalid", f"{field_name} must be nonempty")
    return value


def _sha256(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _fail("spaces_recovery_trace_invalid", f"{field_name} is not SHA-256")
    return value


def _receipt_id(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        _fail("spaces_recovery_trace_invalid", f"{field_name} is invalid")
    _sha256(value[7:], field_name=field_name)
    return value


def _acquisition_identifier(acquisition: OperationAcquisitionResult) -> str:
    """Fingerprint the exact supplied SA5 result without authenticating it."""

    context = acquisition.context
    fields = [
        "spaces-sa5-acquisition-context-v1",
        context.space.uri,
        context.repo_did,
        context.repo_host,
        context.source_ref,
        context.acquired_at.astimezone(UTC).isoformat(),
        acquisition.status.value,
        acquisition.ordered_operation_sha256 or "-",
        "closed" if acquisition.pagination_chain_closed else "open",
    ]
    for page in acquisition.pages:
        fields.extend(
            (
                f"page:{page.ordinal}",
                page.request_since,
                page.request_cursor or "-",
                page.response_cursor or "-",
                page.terminal_commit_sha256 or "-",
                page.received_at.astimezone(UTC).isoformat(),
            )
        )
        for ordinal, (operation, value_present) in enumerate(
            zip(page.operations, page.value_presence, strict=True)
        ):
            fields.extend(
                (
                    f"operation:{ordinal}",
                    operation.rev,
                    operation.collection,
                    operation.rkey,
                    operation.cid or "-",
                    operation.prev or "-",
                    "value-present" if value_present else "value-absent",
                )
            )
    return "sha256:" + hashlib.sha256("\x00".join(fields).encode()).hexdigest()


class OperationUnavailableReason(StrEnum):
    COMPACTED_OR_UNAVAILABLE = "oplog_compacted_or_unavailable"


class TransitionEvidenceState(StrEnum):
    AVAILABLE_CANDIDATE = "complete_candidate_available"
    PARTIAL = "partial_operation_retrieval"
    EMPTY = "empty_terminal_operation_retrieval"
    UNAVAILABLE = "operation_retrieval_compacted_or_unavailable"
    CANDIDATE_REFUSED = "transition_candidate_refused"


class Sa4AttemptDisposition(StrEnum):
    QUALIFIED = "sa4_qualified"
    REFUSED = "sa4_refused"
    SKIPPED_NO_TRANSITION = "sa4_skipped_no_transition_evidence"
    NOT_REACHED = "sa4_not_reached"


class FullRepoArtifactRole(StrEnum):
    TRANSITION_TARGET = "sa4_transition_target_evidence"
    SNAPSHOT_RECOVERY = "independent_snapshot_recovery"
    SNAPSHOT_AFTER_REFUSAL = "independent_snapshot_after_sa4_refusal"


class RecoveryOutcome(StrEnum):
    QUALIFIED_TRANSITION = "qualified_transition"
    EQUAL_STATE = "equal_state"
    SNAPSHOT_ONLY = "snapshot_only"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    HARD_REFUSAL = "hard_refusal"


_OUTCOME_BY_RECONCILIATION = {
    ReconciliationDisposition.QUALIFIED_TRANSITION: (
        RecoveryOutcome.QUALIFIED_TRANSITION
    ),
    ReconciliationDisposition.EQUAL_STATE: RecoveryOutcome.EQUAL_STATE,
    ReconciliationDisposition.SNAPSHOT_ONLY: RecoveryOutcome.SNAPSHOT_ONLY,
    ReconciliationDisposition.INSUFFICIENT_EVIDENCE: (
        RecoveryOutcome.INSUFFICIENT_EVIDENCE
    ),
}


def _missing_provenance(
    state: TransitionEvidenceState,
) -> tuple[str, ...]:
    if state is TransitionEvidenceState.AVAILABLE_CANDIDATE:
        return ()
    if state is TransitionEvidenceState.PARTIAL:
        return ("unretrieved_operation_pages", "complete_transition_batch")
    if state is TransitionEvidenceState.EMPTY:
        return ("record_level_transition_operations",)
    if state is TransitionEvidenceState.UNAVAILABLE:
        return ("operation_response", "complete_transition_batch")
    return ("qualified_transition_relationship",)


def _trace_identifier(
    *,
    known_state: TransitionStateIdentity,
    observed_state: TransitionStateIdentity | None,
    acquisition_status: OperationAcquisitionStatus | None,
    acquisition_result_id: str | None,
    acquisition_source_ref: str | None,
    ordered_operation_sha256: str | None,
    unavailable_reason: OperationUnavailableReason | None,
    transition_evidence: TransitionEvidenceState,
    sa4_attempt: Sa4AttemptDisposition,
    sa4_failure_reason_code: str | None,
    full_repo_role: FullRepoArtifactRole,
    full_repo_request_id: str,
    full_repo_artifact_ref: str,
    full_repo_source_endpoint: str,
    full_repo_observed_at: datetime,
    supplied_car_sha256: str,
    sa2_car_sha256: str | None,
    transition_receipt_id: str | None,
    reconciliation_disposition: ReconciliationDisposition | None,
    reconciliation_reason: str | None,
    outcome: RecoveryOutcome,
    failure_reason_code: str | None,
    decided_at: datetime,
) -> str:
    fields = [
        "spaces-recovery-trace-v1",
        ALPHA_LABEL,
        SA8_RECOVERY_METHOD,
        SA8_RECOVERY_VERSION,
        SA8_RECOVERY_DOCTRINE,
        known_state.space.uri,
        known_state.author_did,
        known_state.repo_rev,
        known_state.repo_commit_hash,
        *(f"known-receipt:{item}" for item in known_state.qualification_receipt_ids),
        acquisition_status.value if acquisition_status is not None else "-",
        acquisition_result_id or "-",
        acquisition_source_ref or "-",
        ordered_operation_sha256 or "-",
        unavailable_reason.value if unavailable_reason is not None else "-",
        transition_evidence.value,
        sa4_attempt.value,
        sa4_failure_reason_code or "-",
        full_repo_role.value,
        full_repo_request_id,
        full_repo_artifact_ref,
        full_repo_source_endpoint,
        full_repo_observed_at.astimezone(UTC).isoformat(),
        supplied_car_sha256,
        sa2_car_sha256 or "-",
        transition_receipt_id or "-",
        reconciliation_disposition.value
        if reconciliation_disposition is not None
        else "-",
        reconciliation_reason or "-",
        outcome.value,
        failure_reason_code or "-",
        decided_at.astimezone(UTC).isoformat(),
    ]
    if observed_state is not None:
        fields.extend(
            (
                observed_state.space.uri,
                observed_state.author_did,
                observed_state.repo_rev,
                observed_state.repo_commit_hash,
                *(
                    f"observed-receipt:{item}"
                    for item in observed_state.qualification_receipt_ids
                ),
            )
        )
    return "sha256:" + hashlib.sha256("\x00".join(fields).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class RecoveryDecisionTrace:
    trace_id: str
    known_state: TransitionStateIdentity
    observed_state: TransitionStateIdentity | None
    acquisition_status: OperationAcquisitionStatus | None
    acquisition_result_id: str | None
    acquisition_source_ref: str | None
    ordered_operation_sha256: str | None
    unavailable_reason: OperationUnavailableReason | None
    transition_evidence: TransitionEvidenceState
    sa4_attempt: Sa4AttemptDisposition
    sa4_failure_reason_code: str | None
    full_repo_role: FullRepoArtifactRole
    full_repo_request_id: str
    full_repo_artifact_ref: str
    full_repo_source_endpoint: str
    full_repo_observed_at: datetime
    supplied_car_sha256: str
    sa2_car_sha256: str | None
    transition_receipt_id: str | None
    reconciliation_disposition: ReconciliationDisposition | None
    reconciliation_reason: str | None
    outcome: RecoveryOutcome
    failure_reason_code: str | None
    decided_at: datetime
    protocol_assumption: str = field(default=ALPHA_LABEL, init=False)
    recovery_method: str = field(default=SA8_RECOVERY_METHOD, init=False)
    recovery_version: str = field(default=SA8_RECOVERY_VERSION, init=False)
    doctrine: str = field(default=SA8_RECOVERY_DOCTRINE, init=False)
    canonical_truth: bool = False
    complete_history: bool = False
    authenticated_ancestry: bool = False
    currentness: bool = False
    standing: bool = False
    authorization: bool = False
    governance_authority: bool = False

    def __post_init__(self) -> None:
        _receipt_id(self.trace_id, field_name="recovery trace")
        if not isinstance(self.known_state, TransitionStateIdentity):
            _fail("spaces_recovery_trace_invalid", "known state identity is invalid")
        if self.observed_state is not None and not isinstance(
            self.observed_state, TransitionStateIdentity
        ):
            _fail("spaces_recovery_trace_invalid", "observed state identity is invalid")
        if self.acquisition_status is None:
            if (
                self.unavailable_reason
                is not OperationUnavailableReason.COMPACTED_OR_UNAVAILABLE
            ):
                _fail(
                    "spaces_recovery_trace_invalid",
                    "missing acquisition needs an explicit unavailable reason",
                )
        elif not isinstance(self.acquisition_status, OperationAcquisitionStatus):
            _fail("spaces_recovery_trace_invalid", "acquisition status is invalid")
        elif self.unavailable_reason is not None:
            _fail(
                "spaces_recovery_trace_invalid",
                "present acquisition cannot also be unavailable",
            )
        if (self.acquisition_status is None) != (self.acquisition_source_ref is None):
            _fail(
                "spaces_recovery_trace_invalid",
                "acquisition source presence does not match acquisition status",
            )
        if (self.acquisition_status is None) != (self.acquisition_result_id is None):
            _fail(
                "spaces_recovery_trace_invalid",
                "acquisition identifier presence does not match acquisition status",
            )
        if self.acquisition_result_id is not None:
            _receipt_id(
                self.acquisition_result_id,
                field_name="SA5 acquisition identifier",
            )
        if self.acquisition_source_ref is not None:
            _nonempty(self.acquisition_source_ref, field_name="acquisition source")
        if self.ordered_operation_sha256 is not None:
            _sha256(
                self.ordered_operation_sha256,
                field_name="ordered operation digest",
            )
        if not isinstance(self.transition_evidence, TransitionEvidenceState):
            _fail(
                "spaces_recovery_trace_invalid", "transition evidence state is invalid"
            )
        if not isinstance(self.sa4_attempt, Sa4AttemptDisposition):
            _fail("spaces_recovery_trace_invalid", "SA4 disposition is invalid")
        if not isinstance(self.full_repo_role, FullRepoArtifactRole):
            _fail("spaces_recovery_trace_invalid", "full-repo role is invalid")
        if not isinstance(self.outcome, RecoveryOutcome):
            _fail("spaces_recovery_trace_invalid", "recovery outcome is invalid")
        expected_evidence = {
            None: {TransitionEvidenceState.UNAVAILABLE},
            OperationAcquisitionStatus.TRANSITION_CANDIDATE: {
                TransitionEvidenceState.AVAILABLE_CANDIDATE,
                TransitionEvidenceState.CANDIDATE_REFUSED,
            },
            OperationAcquisitionStatus.PARTIAL_RETRIEVAL: {
                TransitionEvidenceState.PARTIAL
            },
            OperationAcquisitionStatus.EMPTY_TERMINAL_PAGE: {
                TransitionEvidenceState.EMPTY
            },
        }
        if self.transition_evidence not in expected_evidence[self.acquisition_status]:
            _fail(
                "spaces_recovery_trace_invalid",
                "transition evidence does not match the SA5 acquisition",
            )
        if (
            self.transition_evidence
            in {
                TransitionEvidenceState.AVAILABLE_CANDIDATE,
                TransitionEvidenceState.PARTIAL,
                TransitionEvidenceState.CANDIDATE_REFUSED,
            }
        ) != (self.ordered_operation_sha256 is not None):
            _fail(
                "spaces_recovery_trace_invalid",
                "operation digest presence does not match transition evidence",
            )
        for field_name, value in (
            ("full-repo request", self.full_repo_request_id),
            ("full-repo artifact", self.full_repo_artifact_ref),
            ("full-repo source", self.full_repo_source_endpoint),
        ):
            _nonempty(value, field_name=field_name)
        object.__setattr__(
            self, "full_repo_observed_at", _utc(self.full_repo_observed_at)
        )
        object.__setattr__(self, "decided_at", _utc(self.decided_at))
        _sha256(self.supplied_car_sha256, field_name="supplied CAR digest")
        if self.sa2_car_sha256 is not None:
            _sha256(self.sa2_car_sha256, field_name="SA2 CAR digest")
            if self.sa2_car_sha256 != self.supplied_car_sha256:
                _fail(
                    "spaces_recovery_trace_invalid",
                    "SA2 and supplied CAR digests disagree",
                )
        if self.outcome is not RecoveryOutcome.HARD_REFUSAL and (
            self.sa2_car_sha256 is None
        ):
            _fail(
                "spaces_recovery_trace_invalid",
                "classified recovery requires an SA2-qualified CAR",
            )
        if self.transition_receipt_id is not None:
            _receipt_id(self.transition_receipt_id, field_name="SA4 transition receipt")
        if self.outcome is RecoveryOutcome.HARD_REFUSAL:
            if (
                self.observed_state is not None
                or self.reconciliation_disposition is not None
                or self.reconciliation_reason is not None
                or self.failure_reason_code is None
                or self.transition_receipt_id is not None
            ):
                _fail(
                    "spaces_recovery_trace_invalid",
                    "hard refusal cannot carry qualified recovery evidence",
                )
        else:
            if (
                self.observed_state is None
                or not isinstance(
                    self.reconciliation_disposition, ReconciliationDisposition
                )
                or self.reconciliation_disposition is None
                or self.reconciliation_reason is None
                or self.failure_reason_code is not None
                or _OUTCOME_BY_RECONCILIATION[self.reconciliation_disposition]
                is not self.outcome
            ):
                _fail(
                    "spaces_recovery_trace_invalid",
                    "recovery outcome does not match SA6 classification",
                )
        if self.sa4_attempt is Sa4AttemptDisposition.QUALIFIED:
            if (
                self.transition_receipt_id is None
                or self.transition_evidence
                is not TransitionEvidenceState.AVAILABLE_CANDIDATE
                or self.full_repo_role is not FullRepoArtifactRole.TRANSITION_TARGET
                or self.outcome is not RecoveryOutcome.QUALIFIED_TRANSITION
            ):
                _fail(
                    "spaces_recovery_trace_invalid",
                    "qualified SA4 path has inconsistent evidence",
                )
        elif self.transition_receipt_id is not None:
            _fail(
                "spaces_recovery_trace_invalid",
                "only a qualified SA4 path may carry a transition receipt",
            )
        if self.sa4_attempt is Sa4AttemptDisposition.REFUSED:
            if (
                self.sa4_failure_reason_code is None
                or self.transition_evidence
                is not TransitionEvidenceState.CANDIDATE_REFUSED
                or self.full_repo_role
                is not FullRepoArtifactRole.SNAPSHOT_AFTER_REFUSAL
            ):
                _fail(
                    "spaces_recovery_trace_invalid",
                    "refused SA4 path has inconsistent fallback evidence",
                )
        elif self.sa4_failure_reason_code is not None:
            _fail(
                "spaces_recovery_trace_invalid",
                "SA4 failure reason exists without an SA4 refusal",
            )
        if self.sa4_attempt is Sa4AttemptDisposition.SKIPPED_NO_TRANSITION and (
            self.full_repo_role is not FullRepoArtifactRole.SNAPSHOT_RECOVERY
            or self.transition_evidence
            not in {
                TransitionEvidenceState.PARTIAL,
                TransitionEvidenceState.EMPTY,
                TransitionEvidenceState.UNAVAILABLE,
            }
        ):
            _fail(
                "spaces_recovery_trace_invalid",
                "skipped SA4 path lacks a snapshot-recovery reason",
            )
        if self.sa4_attempt is Sa4AttemptDisposition.NOT_REACHED and (
            self.transition_evidence is not TransitionEvidenceState.AVAILABLE_CANDIDATE
            or self.full_repo_role is not FullRepoArtifactRole.TRANSITION_TARGET
            or self.outcome is not RecoveryOutcome.HARD_REFUSAL
        ):
            _fail(
                "spaces_recovery_trace_invalid",
                "unreached SA4 path must record a pre-qualification refusal",
            )
        if any(
            (
                self.canonical_truth,
                self.complete_history,
                self.authenticated_ancestry,
                self.currentness,
                self.standing,
                self.authorization,
                self.governance_authority,
            )
        ):
            _fail(
                "spaces_recovery_trace_invalid",
                "recovery cannot confer history, truth, freshness, or authority",
            )
        expected = _trace_identifier(
            known_state=self.known_state,
            observed_state=self.observed_state,
            acquisition_status=self.acquisition_status,
            acquisition_result_id=self.acquisition_result_id,
            acquisition_source_ref=self.acquisition_source_ref,
            ordered_operation_sha256=self.ordered_operation_sha256,
            unavailable_reason=self.unavailable_reason,
            transition_evidence=self.transition_evidence,
            sa4_attempt=self.sa4_attempt,
            sa4_failure_reason_code=self.sa4_failure_reason_code,
            full_repo_role=self.full_repo_role,
            full_repo_request_id=self.full_repo_request_id,
            full_repo_artifact_ref=self.full_repo_artifact_ref,
            full_repo_source_endpoint=self.full_repo_source_endpoint,
            full_repo_observed_at=self.full_repo_observed_at,
            supplied_car_sha256=self.supplied_car_sha256,
            sa2_car_sha256=self.sa2_car_sha256,
            transition_receipt_id=self.transition_receipt_id,
            reconciliation_disposition=self.reconciliation_disposition,
            reconciliation_reason=self.reconciliation_reason,
            outcome=self.outcome,
            failure_reason_code=self.failure_reason_code,
            decided_at=self.decided_at,
        )
        if self.trace_id != expected:
            _fail("spaces_recovery_trace_invalid", "recovery trace is not bound")

    def to_provenance(self) -> MappingProxyType[str, object]:
        return MappingProxyType(
            {
                "traceId": self.trace_id,
                "doctrine": self.doctrine,
                "protocolAssumption": self.protocol_assumption,
                "recoveryMethod": self.recovery_method,
                "recoveryVersion": self.recovery_version,
                "decidedAt": self.decided_at.isoformat(),
                "outcome": self.outcome.value,
                "knownState": self.known_state.to_provenance(),
                "operationAcquisition": MappingProxyType(
                    {
                        "status": (
                            self.acquisition_status.value
                            if self.acquisition_status is not None
                            else None
                        ),
                        "resultId": self.acquisition_result_id,
                        "sourceRef": self.acquisition_source_ref,
                        "orderedOperationSha256": self.ordered_operation_sha256,
                        "unavailableReason": (
                            self.unavailable_reason.value
                            if self.unavailable_reason is not None
                            else None
                        ),
                        "transitionEvidence": self.transition_evidence.value,
                        "missingProvenance": _missing_provenance(
                            self.transition_evidence
                        ),
                    }
                ),
                "pathDecision": MappingProxyType(
                    {
                        "sa4Attempt": self.sa4_attempt.value,
                        "sa4FailureReasonCode": self.sa4_failure_reason_code,
                        "fullRepoRole": self.full_repo_role.value,
                    }
                ),
                "fullRepoArtifact": MappingProxyType(
                    {
                        "requestId": self.full_repo_request_id,
                        "artifactRef": self.full_repo_artifact_ref,
                        "sourceEndpoint": self.full_repo_source_endpoint,
                        "observedAt": self.full_repo_observed_at.isoformat(),
                        "suppliedCarSha256": self.supplied_car_sha256,
                        "sa2QualifiedCarSha256": self.sa2_car_sha256,
                        "trustClassification": "unverified_sa7_source_context",
                    }
                ),
                "qualifiedEvidence": MappingProxyType(
                    {
                        "knownSa1ReceiptIds": (
                            self.known_state.qualification_receipt_ids
                        ),
                        "observedState": (
                            self.observed_state.to_provenance()
                            if self.observed_state is not None
                            else None
                        ),
                        "observedSa1ReceiptIds": (
                            self.observed_state.qualification_receipt_ids
                            if self.observed_state is not None
                            else ()
                        ),
                        "sa4TransitionReceiptId": self.transition_receipt_id,
                    }
                ),
                "reconciliation": MappingProxyType(
                    {
                        "disposition": (
                            self.reconciliation_disposition.value
                            if self.reconciliation_disposition is not None
                            else None
                        ),
                        "reason": self.reconciliation_reason,
                        "failureReasonCode": self.failure_reason_code,
                    }
                ),
                "canonicalTruth": False,
                "completeHistory": False,
                "authenticatedAncestry": False,
                "currentness": False,
                "standing": False,
                "authorization": False,
                "governanceAuthority": False,
            }
        )


def _operation_path(
    acquisition: OperationAcquisitionResult | None,
    unavailable_reason: OperationUnavailableReason | None,
) -> tuple[
    TransitionEvidenceState,
    Sa4AttemptDisposition,
    FullRepoArtifactRole,
]:
    if acquisition is None:
        if (
            unavailable_reason
            is not OperationUnavailableReason.COMPACTED_OR_UNAVAILABLE
        ):
            _fail(
                "spaces_recovery_invalid",
                "missing SA5 acquisition needs compacted/unavailable reason",
            )
        return (
            TransitionEvidenceState.UNAVAILABLE,
            Sa4AttemptDisposition.SKIPPED_NO_TRANSITION,
            FullRepoArtifactRole.SNAPSHOT_RECOVERY,
        )
    if unavailable_reason is not None:
        _fail(
            "spaces_recovery_invalid",
            "SA5 acquisition and unavailable reason are mutually exclusive",
        )
    if acquisition.status is OperationAcquisitionStatus.TRANSITION_CANDIDATE:
        return (
            TransitionEvidenceState.AVAILABLE_CANDIDATE,
            Sa4AttemptDisposition.NOT_REACHED,
            FullRepoArtifactRole.TRANSITION_TARGET,
        )
    if acquisition.status is OperationAcquisitionStatus.PARTIAL_RETRIEVAL:
        return (
            TransitionEvidenceState.PARTIAL,
            Sa4AttemptDisposition.SKIPPED_NO_TRANSITION,
            FullRepoArtifactRole.SNAPSHOT_RECOVERY,
        )
    return (
        TransitionEvidenceState.EMPTY,
        Sa4AttemptDisposition.SKIPPED_NO_TRANSITION,
        FullRepoArtifactRole.SNAPSHOT_RECOVERY,
    )


def _make_trace(
    *,
    known_state: TransitionStateIdentity,
    acquisition: OperationAcquisitionResult | None,
    unavailable_reason: OperationUnavailableReason | None,
    transition_evidence: TransitionEvidenceState,
    sa4_attempt: Sa4AttemptDisposition,
    sa4_failure_reason_code: str | None,
    full_repo_role: FullRepoArtifactRole,
    artifact: ObservedCarArtifact,
    supplied_car_sha256: str,
    sa2_car_sha256: str | None,
    observed_state: TransitionStateIdentity | None,
    transition_receipt_id: str | None,
    reconciliation_disposition: ReconciliationDisposition | None,
    reconciliation_reason: str | None,
    outcome: RecoveryOutcome,
    failure_reason_code: str | None,
    decided_at: datetime,
) -> RecoveryDecisionTrace:
    checked_at = _utc(decided_at)
    fields = {
        "known_state": known_state,
        "observed_state": observed_state,
        "acquisition_status": (acquisition.status if acquisition is not None else None),
        "acquisition_result_id": (
            _acquisition_identifier(acquisition) if acquisition is not None else None
        ),
        "acquisition_source_ref": (
            acquisition.context.source_ref if acquisition is not None else None
        ),
        "ordered_operation_sha256": (
            acquisition.ordered_operation_sha256 if acquisition is not None else None
        ),
        "unavailable_reason": unavailable_reason,
        "transition_evidence": transition_evidence,
        "sa4_attempt": sa4_attempt,
        "sa4_failure_reason_code": sa4_failure_reason_code,
        "full_repo_role": full_repo_role,
        "full_repo_request_id": artifact.request.identity.request_id,
        "full_repo_artifact_ref": artifact.source.artifact_ref,
        "full_repo_source_endpoint": artifact.source.source_endpoint,
        "full_repo_observed_at": artifact.source.observed_at,
        "supplied_car_sha256": supplied_car_sha256,
        "sa2_car_sha256": sa2_car_sha256,
        "transition_receipt_id": transition_receipt_id,
        "reconciliation_disposition": reconciliation_disposition,
        "reconciliation_reason": reconciliation_reason,
        "outcome": outcome,
        "failure_reason_code": failure_reason_code,
        "decided_at": checked_at,
    }
    trace_id = _trace_identifier(**fields)
    return RecoveryDecisionTrace(trace_id=trace_id, **fields)


def qualify_recovery_decision(
    known_state: QualifiedRepoState,
    *,
    operation_acquisition: OperationAcquisitionResult | None,
    operation_unavailable_reason: OperationUnavailableReason | None,
    full_repo_artifact: ObservedCarArtifact,
    author_public_key: bytes,
    signature_algorithm: str,
    qualification_source: QualificationSourceContext,
    qualified_at: datetime,
    decided_at: datetime,
) -> RecoveryDecisionTrace:
    """Select and execute one existing bounded qualification path."""

    if not isinstance(known_state, QualifiedRepoState):
        _fail("spaces_recovery_invalid", "known SA1-qualified state is required")
    if not isinstance(full_repo_artifact, ObservedCarArtifact):
        _fail("spaces_recovery_invalid", "SA7 full-repo artifact is required")
    if not isinstance(qualification_source, QualificationSourceContext):
        _fail("spaces_recovery_invalid", "SA1 source context is required")
    known_identity = identify_qualified_repo_state(known_state)
    transition_evidence, sa4_attempt, full_repo_role = _operation_path(
        operation_acquisition, operation_unavailable_reason
    )
    raw_car = full_repo_artifact.sa2_input()
    supplied_car_sha256 = hashlib.sha256(raw_car).hexdigest()

    request_identity = full_repo_artifact.request.identity
    source_context = full_repo_artifact.source
    known_repo_hosts = {
        receipt.unverified_context.get("repoHost") for receipt in known_state.receipts
    }
    source_mismatch = (
        request_identity.space != known_state.space
        or request_identity.repo_did != known_state.author_did
        or qualification_source.repo_host != source_context.source_endpoint
        or qualification_source.evidence_ref != source_context.artifact_ref
        or known_repo_hosts != {source_context.source_endpoint}
        or (
            operation_acquisition is not None
            and (
                operation_acquisition.context.space != known_state.space
                or operation_acquisition.context.repo_did != known_state.author_did
                or operation_acquisition.context.repo_host
                != source_context.source_endpoint
            )
        )
    )
    if source_mismatch:
        return _make_trace(
            known_state=known_identity,
            acquisition=operation_acquisition,
            unavailable_reason=operation_unavailable_reason,
            transition_evidence=transition_evidence,
            sa4_attempt=sa4_attempt,
            sa4_failure_reason_code=None,
            full_repo_role=full_repo_role,
            artifact=full_repo_artifact,
            supplied_car_sha256=supplied_car_sha256,
            sa2_car_sha256=None,
            observed_state=None,
            transition_receipt_id=None,
            reconciliation_disposition=None,
            reconciliation_reason=None,
            outcome=RecoveryOutcome.HARD_REFUSAL,
            failure_reason_code="spaces_recovery_source_mismatch",
            decided_at=decided_at,
        )

    try:
        extraction = extract_space_repo_evidence(
            raw_car,
            source_vector_identifier=source_context.artifact_ref,
        )
    except ValidationError as error:
        return _make_trace(
            known_state=known_identity,
            acquisition=operation_acquisition,
            unavailable_reason=operation_unavailable_reason,
            transition_evidence=transition_evidence,
            sa4_attempt=sa4_attempt,
            sa4_failure_reason_code=None,
            full_repo_role=full_repo_role,
            artifact=full_repo_artifact,
            supplied_car_sha256=supplied_car_sha256,
            sa2_car_sha256=None,
            observed_state=None,
            transition_receipt_id=None,
            reconciliation_disposition=None,
            reconciliation_reason=None,
            outcome=RecoveryOutcome.HARD_REFUSAL,
            failure_reason_code=error.reason_code,
            decided_at=decided_at,
        )

    if (
        operation_acquisition is not None
        and operation_acquisition.status
        is OperationAcquisitionStatus.TRANSITION_CANDIDATE
    ):
        assert operation_acquisition.transition is not None
        transition_evidence_input = replace(
            extraction.evidence,
            transition=operation_acquisition.transition,
        )
        try:
            qualified_transition = qualify_repo_transition(
                known_state,
                transition_evidence_input,
                expected_space=known_state.space,
                expected_author_did=known_state.author_did,
                author_public_key=author_public_key,
                signature_algorithm=signature_algorithm,
                source=qualification_source,
                verified_at=qualified_at,
            )
        except ValidationError as error:
            transition_evidence = TransitionEvidenceState.CANDIDATE_REFUSED
            sa4_attempt = Sa4AttemptDisposition.REFUSED
            sa4_failure_reason_code = error.reason_code
            full_repo_role = FullRepoArtifactRole.SNAPSHOT_AFTER_REFUSAL
        else:
            reconciliation = reconcile_qualified_states(
                known_state,
                qualified_transition.target,
                transition=qualified_transition,
                reconciled_at=decided_at,
            )
            observed_identity = identify_qualified_repo_state(
                qualified_transition.target
            )
            return _make_trace(
                known_state=known_identity,
                acquisition=operation_acquisition,
                unavailable_reason=None,
                transition_evidence=TransitionEvidenceState.AVAILABLE_CANDIDATE,
                sa4_attempt=Sa4AttemptDisposition.QUALIFIED,
                sa4_failure_reason_code=None,
                full_repo_role=FullRepoArtifactRole.TRANSITION_TARGET,
                artifact=full_repo_artifact,
                supplied_car_sha256=supplied_car_sha256,
                sa2_car_sha256=extraction.car.raw_sha256,
                observed_state=observed_identity,
                transition_receipt_id=qualified_transition.receipt.receipt_id,
                reconciliation_disposition=reconciliation.disposition,
                reconciliation_reason=reconciliation.reason,
                outcome=_OUTCOME_BY_RECONCILIATION[reconciliation.disposition],
                failure_reason_code=None,
                decided_at=decided_at,
            )
    else:
        sa4_failure_reason_code = None

    try:
        snapshot = qualify_repo_state(
            extraction.evidence,
            expected_space=known_state.space,
            expected_author_did=known_state.author_did,
            author_public_key=author_public_key,
            signature_algorithm=signature_algorithm,
            source=qualification_source,
            verified_at=qualified_at,
        )
        reconciliation = reconcile_qualified_states(
            known_state,
            snapshot,
            reconciled_at=decided_at,
        )
    except ValidationError as error:
        return _make_trace(
            known_state=known_identity,
            acquisition=operation_acquisition,
            unavailable_reason=operation_unavailable_reason,
            transition_evidence=transition_evidence,
            sa4_attempt=sa4_attempt,
            sa4_failure_reason_code=sa4_failure_reason_code,
            full_repo_role=full_repo_role,
            artifact=full_repo_artifact,
            supplied_car_sha256=supplied_car_sha256,
            sa2_car_sha256=extraction.car.raw_sha256,
            observed_state=None,
            transition_receipt_id=None,
            reconciliation_disposition=None,
            reconciliation_reason=None,
            outcome=RecoveryOutcome.HARD_REFUSAL,
            failure_reason_code=error.reason_code,
            decided_at=decided_at,
        )
    observed_identity = identify_qualified_repo_state(snapshot)
    return _make_trace(
        known_state=known_identity,
        acquisition=operation_acquisition,
        unavailable_reason=operation_unavailable_reason,
        transition_evidence=transition_evidence,
        sa4_attempt=sa4_attempt,
        sa4_failure_reason_code=sa4_failure_reason_code,
        full_repo_role=full_repo_role,
        artifact=full_repo_artifact,
        supplied_car_sha256=supplied_car_sha256,
        sa2_car_sha256=extraction.car.raw_sha256,
        observed_state=observed_identity,
        transition_receipt_id=None,
        reconciliation_disposition=reconciliation.disposition,
        reconciliation_reason=reconciliation.reason,
        outcome=_OUTCOME_BY_RECONCILIATION[reconciliation.disposition],
        failure_reason_code=None,
        decided_at=decided_at,
    )


__all__ = [
    "FullRepoArtifactRole",
    "OperationUnavailableReason",
    "RecoveryDecisionTrace",
    "RecoveryOutcome",
    "Sa4AttemptDisposition",
    "TransitionEvidenceState",
    "qualify_recovery_decision",
]
