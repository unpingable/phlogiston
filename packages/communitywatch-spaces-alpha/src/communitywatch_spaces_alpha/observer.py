"""Fixture-first direct-sync observer for the Spaces alpha boundary."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC
from typing import Protocol, runtime_checkable

from community_model import ValidationError

from .model import (
    AccessContext,
    EvidenceAdmission,
    RepoBinding,
    RepoSnapshot,
    SpaceIdentity,
    SpaceNotification,
    SpaceObservation,
    VerificationMode,
    WriterSetClaim,
)


@runtime_checkable
class DirectSpaceSource(Protocol):
    """Read-only alpha port; authentication and crypto remain adapter details."""

    def list_writer_claims(
        self, space: SpaceIdentity, access: AccessContext
    ) -> Sequence[WriterSetClaim]: ...

    def bind_repo(
        self, space: SpaceIdentity, repo_did: str, access: AccessContext
    ) -> RepoBinding: ...

    def fetch_repo(
        self, space: SpaceIdentity, repo_did: str, access: AccessContext
    ) -> RepoSnapshot: ...


@dataclass(frozen=True, slots=True)
class RepoHead:
    rev: str
    commit_hash: str


@dataclass(frozen=True, slots=True)
class SyncResult:
    trigger: str
    observations: tuple[SpaceObservation, ...] = ()
    admissions: tuple[EvidenceAdmission, ...] = ()
    refusals: tuple[str, ...] = ()


@dataclass(slots=True)
class SpaceObserver:
    """Synchronize one exact Space without importing public-repo semantics."""

    space: SpaceIdentity
    space_host: str
    source: DirectSpaceSource
    admitted_collections: frozenset[str]
    access: AccessContext | None
    accepted_verification_modes: frozenset[VerificationMode | str] = field(
        default_factory=lambda: frozenset({VerificationMode.VERIFIED})
    )
    _writer_claims: dict[str, WriterSetClaim] = field(default_factory=dict, init=False)
    _heads: dict[str, RepoHead] = field(default_factory=dict, init=False)
    _observations: list[SpaceObservation] = field(default_factory=list, init=False)
    _admissions: list[EvidenceAdmission] = field(default_factory=list, init=False)
    _notifications: list[SpaceNotification] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.space, SpaceIdentity):
            raise ValidationError("schema_invalid", "space identity is required")
        if not self.space_host.startswith("https://"):
            raise ValidationError("schema_invalid", "space_host must be https")
        self.space_host = self.space_host.rstrip("/")
        if not isinstance(self.admitted_collections, frozenset) or not (
            self.admitted_collections
        ):
            raise ValidationError(
                "schema_invalid", "admitted_collections must be a nonempty frozenset"
            )
        normalized_modes: set[VerificationMode] = set()
        for mode in self.accepted_verification_modes:
            try:
                normalized_modes.add(VerificationMode(mode))
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    "schema_invalid", "unsupported accepted verification mode"
                ) from exc
        self.accepted_verification_modes = frozenset(normalized_modes)
        if self.access is not None and self.access.space != self.space:
            raise ValidationError("schema_invalid", "access targets another Space")

    @property
    def observations(self) -> tuple[SpaceObservation, ...]:
        return tuple(self._observations)

    @property
    def admissions(self) -> tuple[EvidenceAdmission, ...]:
        return tuple(self._admissions)

    @property
    def pending_notifications(self) -> tuple[SpaceNotification, ...]:
        return tuple(self._notifications)

    def replace_access(self, access: AccessContext | None) -> None:
        """Change present read access without rewriting observation history."""

        if access is not None and access.space != self.space:
            raise ValidationError("schema_invalid", "access targets another Space")
        self.access = access

    def record_notification(self, notification: SpaceNotification) -> SyncResult:
        """Retain an advancement hint; never turn it into evidence."""

        if notification.space != self.space:
            return SyncResult(trigger="notification", refusals=("wrong_space",))
        if notification.space_host != self.space_host:
            return SyncResult(
                trigger="notification", refusals=("space_host_substitution",)
            )
        self._notifications.append(notification)
        return SyncResult(trigger="notification")

    def synchronize_notifications(self) -> tuple[SyncResult, ...]:
        """Fetch source state for queued hints; hint rev/hash are not evidence."""

        queued = tuple(self._notifications)
        self._notifications.clear()
        results: list[SyncResult] = []
        missing_discovery = False
        for notification in queued:
            claim = self._writer_claims.get(notification.repo_did)
            if claim is None:
                missing_discovery = True
                continue
            results.append(self._sync_claim(claim, trigger="notification-refetch"))
        if missing_discovery:
            results.extend(self.reconcile())
        return tuple(results)

    def reconcile(self) -> tuple[SyncResult, ...]:
        """Authoritative recovery loop: discover writers, then fetch repo hosts."""

        if self.access is None:
            return (SyncResult(trigger="reconcile", refusals=("access_unavailable",)),)
        try:
            claims = tuple(self.source.list_writer_claims(self.space, self.access))
        except (OSError, ValidationError):
            return (SyncResult(trigger="reconcile", refusals=("discovery_failed",)),)
        results: list[SyncResult] = []
        seen: set[str] = set()
        for claim in claims:
            if claim.space != self.space:
                results.append(
                    SyncResult(trigger="reconcile", refusals=("wrong_space",))
                )
                continue
            if claim.space_host != self.space_host:
                results.append(
                    SyncResult(
                        trigger="reconcile",
                        refusals=("space_host_substitution",),
                    )
                )
                continue
            seen.add(claim.repo_did)
            self._writer_claims[claim.repo_did] = claim
            head = self._heads.get(claim.repo_did)
            if (
                head is None
                or claim.rev > head.rev
                or (claim.rev == head.rev and claim.commit_hash != head.commit_hash)
            ):
                results.append(self._sync_claim(claim, trigger="reconcile"))
        # Absence from a later discovery page does not delete historical
        # evidence or prove membership revocation.  It only drops the current
        # discovery route for subsequent notification handling.
        for repo_did in set(self._writer_claims) - seen:
            del self._writer_claims[repo_did]
        return tuple(results)

    def sync_discovered_repo(self, repo_did: str) -> SyncResult:
        claim = self._writer_claims.get(repo_did)
        if claim is None:
            return SyncResult(
                trigger="direct-sync", refusals=("writer_not_discovered",)
            )
        return self._sync_claim(claim, trigger="direct-sync")

    def current_admissions(self) -> tuple[EvidenceAdmission, ...]:
        return tuple(
            admission
            for admission in self._admissions
            if self.is_current(admission.observation)
        )

    def is_current(self, observation: SpaceObservation) -> bool:
        snapshot = observation.repo_snapshot
        head = self._heads.get(snapshot.author_did)
        return head == RepoHead(snapshot.rev, snapshot.commit_hash)

    def _sync_claim(self, claim: WriterSetClaim, *, trigger: str) -> SyncResult:
        if self.access is None:
            return SyncResult(trigger=trigger, refusals=("access_unavailable",))
        try:
            binding = self.source.bind_repo(self.space, claim.repo_did, self.access)
            snapshot = self.source.fetch_repo(self.space, claim.repo_did, self.access)
        except (OSError, ValidationError):
            return SyncResult(trigger=trigger, refusals=("repo_fetch_failed",))

        refusals = self._refusals(claim, binding, snapshot)
        if refusals:
            return SyncResult(trigger=trigger, refusals=refusals)

        head = self._heads.get(snapshot.author_did)
        historical = head is not None and snapshot.rev < head.rev
        if head is not None and snapshot.rev == head.rev:
            if snapshot.commit_hash != head.commit_hash:
                return SyncResult(
                    trigger=trigger, refusals=("established_head_conflict",)
                )
            return SyncResult(trigger=trigger, refusals=("already_current",))

        observed_at = snapshot.acquired_at.astimezone(UTC)
        observations = tuple(
            SpaceObservation(
                record=record,
                writer_discovery=claim,
                repo_binding=binding,
                repo_snapshot=snapshot,
                observed_at=observed_at,
            )
            for record in snapshot.records
        )
        self._observations.extend(observations)

        if historical:
            return SyncResult(
                trigger=trigger,
                observations=observations,
                refusals=("stale_repo_revision",),
            )

        self._heads[snapshot.author_did] = RepoHead(snapshot.rev, snapshot.commit_hash)
        admissions = tuple(
            EvidenceAdmission(observation=item, admitted_at=observed_at)
            for item in observations
            if item.record.identity.collection in self.admitted_collections
        )
        self._admissions.extend(admissions)
        excluded = len(observations) - len(admissions)
        return SyncResult(
            trigger=trigger,
            observations=observations,
            admissions=admissions,
            refusals=("collection_not_selected",) if excluded else (),
        )

    def _refusals(
        self,
        claim: WriterSetClaim,
        binding: RepoBinding,
        snapshot: RepoSnapshot,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        verification = snapshot.verification
        if claim.space != self.space or binding.space != self.space:
            reasons.append("wrong_space")
        if binding.repo_did != claim.repo_did:
            reasons.append("repo_binding_identity_mismatch")
        if snapshot.space != self.space:
            reasons.append("wrong_space")
        if snapshot.author_did != claim.repo_did:
            reasons.append("repo_author_mismatch")
        if snapshot.repo_host != binding.repo_host:
            reasons.append("repo_host_substitution")
        if snapshot.access != self.access:
            reasons.append("access_context_substitution")
        if verification.space != snapshot.space:
            reasons.append("verification_space_mismatch")
        if verification.author_did != snapshot.author_did:
            reasons.append("verification_author_mismatch")
        if verification.repo_host != snapshot.repo_host:
            reasons.append("verification_source_mismatch")
        if verification.rev != snapshot.rev:
            reasons.append("verification_revision_mismatch")
        if verification.commit_hash != snapshot.commit_hash:
            reasons.append("verification_hash_mismatch")
        if verification.mode not in self.accepted_verification_modes:
            reasons.append("verification_mode_refused")
        if not verification.complete:
            reasons.append("verification_incomplete")
        if verification.mode is VerificationMode.VERIFIED:
            receipts = snapshot.qualification_receipts
            if not receipts:
                reasons.append("cryptographic_qualification_missing")
            elif len(receipts) != len(snapshot.records):
                reasons.append("cryptographic_qualification_mismatch")
            else:
                expected_records = {
                    (record.identity.uri, record.cid) for record in snapshot.records
                }
                received_records = {
                    (receipt.record_identity.uri, receipt.record_cid)
                    for receipt in receipts
                }
                if expected_records != received_records:
                    reasons.append("cryptographic_qualification_mismatch")
                for receipt in receipts:
                    if (
                        receipt.space_identity != snapshot.space
                        or receipt.record_identity.author_did != snapshot.author_did
                        or receipt.repo_rev != snapshot.rev
                        or receipt.repo_commit_hash != snapshot.commit_hash
                        or receipt.protocol_assumption
                        != verification.protocol_assumption
                        or receipt.commit_format != verification.commit_format
                        or receipt.verification_method != verification.method
                        or receipt.verifier_version != verification.verifier_version
                    ):
                        reasons.append("cryptographic_qualification_mismatch")
                    if receipt.unverified_context.get("repoHost") != (
                        snapshot.repo_host
                    ):
                        reasons.append("qualification_source_mismatch")
                    if receipt.unverified_context.get("authorKeyRef") != (
                        verification.author_key_ref
                    ) or receipt.unverified_context.get("evidenceRef") != (
                        verification.evidence_ref
                    ):
                        reasons.append("qualification_source_mismatch")
                    if receipt.verified_at != verification.verified_at:
                        reasons.append("cryptographic_qualification_mismatch")
        if claim.rev == snapshot.rev and claim.commit_hash != snapshot.commit_hash:
            reasons.append("writer_set_state_conflict")
        if claim.rev > snapshot.rev:
            reasons.append("repo_behind_writer_discovery")
        for record in snapshot.records:
            if record.identity.space != self.space:
                reasons.append("record_wrong_space")
            if record.identity.author_did != snapshot.author_did:
                reasons.append("record_author_mismatch")
        return tuple(dict.fromkeys(reasons))


__all__ = [
    "DirectSpaceSource",
    "RepoHead",
    "SpaceObserver",
    "SyncResult",
]
