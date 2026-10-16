"""SA6 bounded reconciliation over already qualified Spaces evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType

from community_model import ValidationError

from .compat import (
    ALPHA_LABEL,
    SA6_RECONCILER_VERSION,
    SA6_RECONCILIATION_METHOD,
)
from .qualification import QualifiedRepoState
from .transition import (
    QualifiedSpaceTransition,
    SpaceTransitionReceipt,
    TransitionStateIdentity,
    identify_qualified_repo_state,
)


def _fail(message: str) -> None:
    raise ValidationError("spaces_reconciliation_invalid", message)


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        _fail("reconciliation time must be timezone-aware")
    return value.astimezone(UTC)


def _state_key(state: TransitionStateIdentity) -> tuple[object, ...]:
    """Cryptographic repository identity, excluding observation receipt timing."""

    return (
        state.space,
        state.author_did,
        state.repo_rev,
        state.repo_commit_hash,
        state.commit_block_cid,
        state.index_block_cid,
        state.record_index_sha256,
        state.record_count,
    )


def _same_repo(left: TransitionStateIdentity, right: TransitionStateIdentity) -> bool:
    return left.space == right.space and left.author_did == right.author_did


class ReconciliationDisposition(StrEnum):
    EQUAL_STATE = "equal_state"
    QUALIFIED_TRANSITION = "qualified_transition"
    SNAPSHOT_ONLY = "snapshot_only"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    known_state: TransitionStateIdentity
    observed_state: TransitionStateIdentity
    disposition: ReconciliationDisposition
    reason: str
    reconciled_at: datetime
    transition_receipt: SpaceTransitionReceipt | None = None
    considered_transition_receipt_id: str | None = None
    protocol_assumption: str = field(default=ALPHA_LABEL, init=False)
    method: str = field(default=SA6_RECONCILIATION_METHOD, init=False)
    reconciler_version: str = field(default=SA6_RECONCILER_VERSION, init=False)
    complete_history: bool = False
    currentness: bool = False
    authority: bool = False
    authorization: bool = False
    governance_authority: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.known_state, TransitionStateIdentity) or not isinstance(
            self.observed_state, TransitionStateIdentity
        ):
            _fail("reconciliation state identities are invalid")
        if not isinstance(self.disposition, ReconciliationDisposition):
            _fail("reconciliation disposition is invalid")
        if not isinstance(self.reason, str) or not self.reason:
            _fail("reconciliation reason is required")
        object.__setattr__(self, "reconciled_at", _utc(self.reconciled_at))
        if self.disposition is ReconciliationDisposition.EQUAL_STATE:
            if _state_key(self.known_state) != _state_key(self.observed_state):
                _fail("equal_state requires identical qualified repository state")
            if self.transition_receipt is not None:
                _fail("equal_state cannot carry transition evidence")
        elif self.disposition is ReconciliationDisposition.QUALIFIED_TRANSITION:
            receipt = self.transition_receipt
            if not isinstance(receipt, SpaceTransitionReceipt) or (
                _state_key(receipt.source_state) != _state_key(self.known_state)
                or _state_key(receipt.target_state) != _state_key(self.observed_state)
            ):
                _fail("qualified_transition requires the exact SA4 relationship")
            if self.considered_transition_receipt_id != receipt.receipt_id:
                _fail("qualified_transition receipt context is inconsistent")
        elif self.transition_receipt is not None:
            _fail("only qualified_transition may carry an SA4 receipt")
        if self.considered_transition_receipt_id is not None and (
            not self.considered_transition_receipt_id.startswith("sha256:")
            or len(self.considered_transition_receipt_id) != 71
            or any(
                character not in "0123456789abcdef"
                for character in self.considered_transition_receipt_id[7:]
            )
        ):
            _fail("considered transition receipt identifier is invalid")
        if self.disposition is ReconciliationDisposition.SNAPSHOT_ONLY and (
            not _same_repo(self.known_state, self.observed_state)
            or self.known_state.repo_rev >= self.observed_state.repo_rev
        ):
            _fail("snapshot_only requires a later state of the same Space repository")
        if any(
            (
                self.complete_history,
                self.currentness,
                self.authority,
                self.authorization,
                self.governance_authority,
            )
        ):
            _fail("reconciliation cannot confer history, freshness, or authority")

    def to_provenance(self) -> MappingProxyType[str, object]:
        return MappingProxyType(
            {
                "disposition": self.disposition.value,
                "reason": self.reason,
                "protocolAssumption": self.protocol_assumption,
                "method": self.method,
                "reconcilerVersion": self.reconciler_version,
                "reconciledAt": self.reconciled_at.isoformat(),
                "knownState": self.known_state.to_provenance(),
                "observedState": self.observed_state.to_provenance(),
                "transitionReceiptId": (
                    self.transition_receipt.receipt_id
                    if self.transition_receipt is not None
                    else None
                ),
                "consideredTransitionReceiptId": self.considered_transition_receipt_id,
                "completeHistory": False,
                "currentness": False,
                "authority": False,
                "authorization": False,
                "governanceAuthority": False,
            }
        )


def reconcile_qualified_states(
    known_state: QualifiedRepoState,
    observed_state: QualifiedRepoState,
    *,
    transition: QualifiedSpaceTransition | None = None,
    reconciled_at: datetime,
) -> ReconciliationResult:
    """Classify only the bounded relationship established by supplied evidence."""

    if not isinstance(known_state, QualifiedRepoState) or not isinstance(
        observed_state, QualifiedRepoState
    ):
        _fail("SA1-qualified known and observed states are required")
    if transition is not None and not isinstance(transition, QualifiedSpaceTransition):
        _fail("optional transition must be SA4-qualified")
    known = identify_qualified_repo_state(known_state)
    observed = identify_qualified_repo_state(observed_state)
    checked_at = _utc(reconciled_at)

    if transition is not None:
        receipt = transition.receipt
        if _state_key(receipt.source_state) == _state_key(known) and _state_key(
            receipt.target_state
        ) == _state_key(observed):
            return ReconciliationResult(
                known_state=known,
                observed_state=observed,
                disposition=ReconciliationDisposition.QUALIFIED_TRANSITION,
                reason="supplied_sa4_transition_exactly_links_states",
                reconciled_at=checked_at,
                transition_receipt=receipt,
                considered_transition_receipt_id=receipt.receipt_id,
            )
        return ReconciliationResult(
            known_state=known,
            observed_state=observed,
            disposition=ReconciliationDisposition.INSUFFICIENT_EVIDENCE,
            reason="supplied_transition_does_not_link_known_and_observed_states",
            reconciled_at=checked_at,
            considered_transition_receipt_id=receipt.receipt_id,
        )

    if _state_key(known) == _state_key(observed):
        return ReconciliationResult(
            known_state=known,
            observed_state=observed,
            disposition=ReconciliationDisposition.EQUAL_STATE,
            reason="qualified_repository_state_is_equal",
            reconciled_at=checked_at,
        )
    if not _same_repo(known, observed):
        reason = "space_or_author_identity_differs"
    elif known.repo_rev == observed.repo_rev:
        reason = "same_revision_has_conflicting_qualified_state"
    elif observed.repo_rev < known.repo_rev:
        reason = "observed_state_is_stale_or_replayed"
    else:
        return ReconciliationResult(
            known_state=known,
            observed_state=observed,
            disposition=ReconciliationDisposition.SNAPSHOT_ONLY,
            reason="later_qualified_snapshot_has_no_linking_transition_evidence",
            reconciled_at=checked_at,
        )
    return ReconciliationResult(
        known_state=known,
        observed_state=observed,
        disposition=ReconciliationDisposition.INSUFFICIENT_EVIDENCE,
        reason=reason,
        reconciled_at=checked_at,
    )


__all__ = [
    "ReconciliationDisposition",
    "ReconciliationResult",
    "reconcile_qualified_states",
]
