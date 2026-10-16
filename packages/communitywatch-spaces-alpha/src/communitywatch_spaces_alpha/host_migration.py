"""SA10c bounded service-host rebinding without retroactive attribution."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

from community_model import ValidationError

from .compat import SA10C_HOST_MIGRATION_METHOD, SA10C_HOST_MIGRATION_VERSION
from .did_binding import DidBindingReceipt, DidInterpretationProfile
from .did_resolution import ResolvedDidDocument, require_resolved_document_binding

_NON = frozenset(
    {
        "global_currentness",
        "canonical_truth",
        "remote_control",
        "historical_reattribution",
        "artifact_validity",
        "authorization",
        "governance_authority",
    }
)


def _fail(reason: str, message: str) -> None:
    raise ValidationError(reason, message)


def _sha(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class HostBindingEpoch:
    did: str
    profile: DidInterpretationProfile
    origin: str
    document_sha256: str
    resolution_receipt_id: str
    binding_receipt_id: str
    qualified_at: datetime

    @classmethod
    def from_receipts(
        cls, resolved: ResolvedDidDocument, binding: DidBindingReceipt
    ) -> "HostBindingEpoch":
        require_resolved_document_binding(resolved, resolved.document_bytes)
        if (
            binding.expected_did != resolved.expected_did
            or binding.document_sha256 != resolved.document_sha256
            or binding.document_provenance_ref != resolved.method_receipt_id
            or binding.selected_origin is None
        ):
            _fail("spaces_host_epoch_mismatch", "resolution and service binding differ")
        if binding.profile not in {
            DidInterpretationProfile.ACCOUNT_REPO_HOST,
            DidInterpretationProfile.SPACE_AUTHORITY_HOST,
        }:
            _fail("spaces_host_epoch_invalid", "host service profile required")
        return cls(
            binding.expected_did,
            binding.profile,
            binding.selected_origin,
            binding.document_sha256,
            resolved.method_receipt_id,
            binding.receipt_id,
            binding.qualified_at,
        )


@dataclass(frozen=True, slots=True)
class HostMigrationReceipt:
    receipt_id: str
    prior: HostBindingEpoch
    successor: HostBindingEpoch
    historical_artifact_refs: tuple[str, ...]
    evaluated_at: datetime
    explicit_non_claims: frozenset[str] = field(default=_NON)
    method: str = field(default=SA10C_HOST_MIGRATION_METHOD, init=False)
    version: str = field(default=SA10C_HOST_MIGRATION_VERSION, init=False)
    historical_reattribution: bool = False

    def __post_init__(self) -> None:
        if (
            self.prior.did != self.successor.did
            or self.prior.profile != self.successor.profile
        ):
            _fail(
                "spaces_host_migration_identity_mismatch",
                "epochs bind different identity/profile",
            )
        if (
            self.prior.origin == self.successor.origin
            or self.prior.document_sha256 == self.successor.document_sha256
            or self.prior.resolution_receipt_id == self.successor.resolution_receipt_id
        ):
            _fail(
                "spaces_host_migration_fresh_evidence_required",
                "migration requires a distinct resolution and endpoint",
            )
        if self.successor.qualified_at <= self.prior.qualified_at:
            _fail("spaces_host_migration_stale", "successor evidence is not later")
        if len(set(self.historical_artifact_refs)) != len(
            self.historical_artifact_refs
        ) or any(not x for x in self.historical_artifact_refs):
            _fail(
                "spaces_host_migration_history_invalid",
                "historical references are invalid",
            )
        if (
            self.explicit_non_claims != _NON
            or self.historical_reattribution
            or self.receipt_id != _rid(self)
        ):
            _fail(
                "spaces_host_migration_receipt_invalid",
                "migration receipt is not bound",
            )

    def to_provenance(self) -> dict[str, object]:
        return {
            "receiptId": self.receipt_id,
            "did": self.prior.did,
            "profile": self.prior.profile.value,
            "priorOrigin": self.prior.origin,
            "successorOrigin": self.successor.origin,
            "priorResolutionReceiptId": self.prior.resolution_receipt_id,
            "successorResolutionReceiptId": self.successor.resolution_receipt_id,
            "historicalArtifactRefs": self.historical_artifact_refs,
            "historicalArtifactsRemainAt": self.prior.origin,
            "futureAcquisitionOrigin": self.successor.origin,
            "evaluatedAt": self.evaluated_at.isoformat(),
            "explicitNonClaims": sorted(self.explicit_non_claims),
            "historicalReattribution": False,
        }


def _rid(r: HostMigrationReceipt) -> str:
    vals = (
        SA10C_HOST_MIGRATION_METHOD,
        SA10C_HOST_MIGRATION_VERSION,
        r.prior.did,
        r.prior.profile.value,
        r.prior.origin,
        r.successor.origin,
        r.prior.document_sha256,
        r.successor.document_sha256,
        r.prior.resolution_receipt_id,
        r.successor.resolution_receipt_id,
        r.prior.binding_receipt_id,
        r.successor.binding_receipt_id,
        r.evaluated_at.isoformat(),
        *r.historical_artifact_refs,
    )
    return "sha256:" + _sha("\x00".join(vals))


def qualify_host_migration(
    prior: HostBindingEpoch,
    successor: HostBindingEpoch,
    *,
    historical_artifact_refs: tuple[str, ...],
    evaluated_at: datetime,
) -> HostMigrationReceipt:
    fields = dict(
        receipt_id="",
        prior=prior,
        successor=successor,
        historical_artifact_refs=historical_artifact_refs,
        evaluated_at=evaluated_at.astimezone(UTC),
    )
    provisional = HostMigrationReceipt.__new__(HostMigrationReceipt)
    for k, v in fields.items():
        object.__setattr__(provisional, k, v)
    object.__setattr__(provisional, "explicit_non_claims", _NON)
    object.__setattr__(provisional, "method", SA10C_HOST_MIGRATION_METHOD)
    object.__setattr__(provisional, "version", SA10C_HOST_MIGRATION_VERSION)
    object.__setattr__(provisional, "historical_reattribution", False)
    fields["receipt_id"] = _rid(provisional)
    return HostMigrationReceipt(**fields)


__all__ = ["HostBindingEpoch", "HostMigrationReceipt", "qualify_host_migration"]
