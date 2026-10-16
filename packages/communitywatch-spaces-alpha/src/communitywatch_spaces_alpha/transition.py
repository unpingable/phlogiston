"""Bounded qualification of one supplied Spaces repository state transition.

SA4 composes two SA1-qualified states with the exact operation batch that SA1
already validates. It proves that bounded relationship only: no commit parent,
complete history, actor legitimacy, authorization, or governance authority is
created here.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType

from community_model import ValidationError
from community_model.identifiers import validate_cid, validate_did, validate_tid

from .compat import (
    ALPHA_LABEL,
    LTHASH_STATE_BYTES,
    SA4_TRANSITION_METHOD,
    SA4_TRANSITION_VERSION,
)
from .crypto import lthash_add, lthash_digest
from .model import SpaceIdentity
from .qualification import (
    QualificationSourceContext,
    QualifiedRepoState,
    RepoOperation,
    SpaceRepoEvidence,
    VerifiedSpaceClaim,
    qualify_repo_state,
)


def _fail(reason: str, message: str) -> None:
    raise ValidationError(reason, message)


def _sha256_text(value: object, *, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _fail("spaces_transition_receipt_invalid", f"{field_name} is not SHA-256")


def _receipt_digest(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        _fail("spaces_transition_receipt_invalid", f"{field_name} is invalid")
    _sha256_text(value[7:], field_name=field_name)


def _checked_at(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        _fail("spaces_transition_invalid", "verified_at must be timezone-aware")
    return value.astimezone(UTC)


class TransitionOperationKind(StrEnum):
    ADD = "add"
    UPDATE = "update"
    REMOVE = "remove"


class VerifiedTransitionClaim(StrEnum):
    SOURCE_QUALIFIED_STATE = "source_sa1_qualified_state"
    TARGET_QUALIFIED_STATE = "target_sa1_qualified_state"
    ORDERED_OPERATION_BATCH = "supplied_operation_order_preserved"
    INDEX_TRANSITION = "record_index_transition"
    LTHASH_TRANSITION = "lthash_state_transition"
    RECORD_EFFECTS = "record_level_effects"


_TRANSITION_CLAIMS = frozenset(VerifiedTransitionClaim)


@dataclass(frozen=True, slots=True)
class TransitionStateIdentity:
    space: SpaceIdentity
    author_did: str
    repo_rev: str
    repo_commit_hash: str
    commit_block_cid: str
    index_block_cid: str
    record_index_sha256: str
    record_count: int
    qualification_receipt_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.space, SpaceIdentity):
            _fail("spaces_transition_receipt_invalid", "state Space is invalid")
        validate_did(self.author_did)
        validate_tid(self.repo_rev)
        _sha256_text(self.repo_commit_hash, field_name="repository commit hash")
        validate_cid(self.commit_block_cid, require_dag_cbor=True)
        validate_cid(self.index_block_cid, require_dag_cbor=True)
        _sha256_text(self.record_index_sha256, field_name="record index digest")
        if (
            isinstance(self.record_count, bool)
            or not isinstance(self.record_count, int)
            or self.record_count < 0
        ):
            _fail(
                "spaces_transition_receipt_invalid",
                "SA4 state record count is invalid",
            )
        if not isinstance(self.qualification_receipt_ids, tuple) or len(
            self.qualification_receipt_ids
        ) != (self.record_count if self.record_count else 1):
            _fail(
                "spaces_transition_receipt_invalid",
                "state qualification receipt count is invalid",
            )
        for receipt_id in self.qualification_receipt_ids:
            _receipt_digest(receipt_id, field_name="qualification receipt")

    def to_provenance(self) -> MappingProxyType[str, object]:
        return MappingProxyType(
            {
                "space": self.space.uri,
                "authorDid": self.author_did,
                "repoRev": self.repo_rev,
                "repoCommitHash": self.repo_commit_hash,
                "commitBlockCid": self.commit_block_cid,
                "indexBlockCid": self.index_block_cid,
                "recordIndexSha256": self.record_index_sha256,
                "recordCount": self.record_count,
                "qualificationReceiptIds": self.qualification_receipt_ids,
            }
        )


@dataclass(frozen=True, slots=True)
class TransitionRecordEffect:
    ordinal: int
    kind: TransitionOperationKind
    rev: str
    collection: str
    rkey: str
    prior_cid: str | None
    resulting_cid: str | None

    def __post_init__(self) -> None:
        if (
            isinstance(self.ordinal, bool)
            or not isinstance(self.ordinal, int)
            or self.ordinal < 0
        ):
            _fail("spaces_transition_receipt_invalid", "effect ordinal is invalid")
        if not isinstance(self.kind, TransitionOperationKind):
            _fail("spaces_transition_receipt_invalid", "effect kind is invalid")
        operation = RepoOperation(
            rev=self.rev,
            collection=self.collection,
            rkey=self.rkey,
            cid=self.resulting_cid,
            prev=self.prior_cid,
        )
        expected_kind = _operation_kind(operation)
        if self.kind is not expected_kind:
            _fail("spaces_transition_receipt_invalid", "effect kind is inconsistent")

    @property
    def path(self) -> str:
        return f"{self.collection}/{self.rkey}"

    def to_provenance(self) -> MappingProxyType[str, object]:
        return MappingProxyType(
            {
                "ordinal": self.ordinal,
                "kind": self.kind.value,
                "rev": self.rev,
                "path": self.path,
                "priorCid": self.prior_cid,
                "resultingCid": self.resulting_cid,
            }
        )


def _operation_kind(operation: RepoOperation) -> TransitionOperationKind:
    if operation.prev is None:
        return TransitionOperationKind.ADD
    if operation.cid is None:
        return TransitionOperationKind.REMOVE
    return TransitionOperationKind.UPDATE


def _state_identifier(state: QualifiedRepoState) -> TransitionStateIdentity:
    if not isinstance(state, QualifiedRepoState):
        _fail("spaces_transition_invalid", "SA1 qualified state is required")
    if not isinstance(state.lthash_state, bytes) or len(state.lthash_state) != (
        LTHASH_STATE_BYTES
    ):
        _fail("spaces_transition_invalid", "qualified state accumulator is invalid")
    if state.records and len(state.records) != len(state.receipts):
        _fail(
            "spaces_transition_invalid",
            "SA4 requires one SA1 receipt for every nonempty state record",
        )
    from .empty_state import QualifiedEmptyRepoState

    if not state.records and not isinstance(state, QualifiedEmptyRepoState):
        _fail(
            "spaces_transition_invalid",
            "empty source state requires an SA10a state-level receipt",
        )
    if state.records and isinstance(state, QualifiedEmptyRepoState):
        _fail("spaces_transition_invalid", "empty-state receipt cannot label records")
    recomputed_state = bytes(LTHASH_STATE_BYTES)
    index_fields: list[str] = []
    seen_paths: set[str] = set()
    commit_block_cid: str | None = None
    index_block_cid: str | None = None
    for record, receipt in zip(state.records, state.receipts, strict=True):
        path = f"{record.identity.collection}/{record.identity.rkey}"
        if path in seen_paths:
            _fail("spaces_transition_invalid", "qualified state repeats a record path")
        seen_paths.add(path)
        if (
            record.identity.space != state.space
            or record.identity.author_did != state.author_did
            or receipt.space_identity != state.space
            or receipt.record_identity != record.identity
            or receipt.record_cid != record.cid
            or receipt.repo_rev != state.commit.rev
            or receipt.repo_commit_hash != state.commit.state_hash.hex()
        ):
            _fail(
                "spaces_transition_invalid",
                "qualified state records and receipts are inconsistent",
            )
        candidate_commit = receipt.cryptographic_inputs.get("commitBlockCid")
        candidate_index = receipt.cryptographic_inputs.get("indexBlockCid")
        if not isinstance(candidate_commit, str) or not isinstance(
            candidate_index, str
        ):
            _fail(
                "spaces_transition_invalid",
                "qualified state lacks SA1 block identities",
            )
        if commit_block_cid is None:
            commit_block_cid = candidate_commit
            index_block_cid = candidate_index
        elif commit_block_cid != candidate_commit or index_block_cid != candidate_index:
            _fail(
                "spaces_transition_invalid",
                "qualified state receipts disagree on block identities",
            )
        recomputed_state = lthash_add(recomputed_state, f"{path}/{record.cid}")
        index_fields.append(f"{path}\x00{record.cid}")
    if not hmac.compare_digest(
        recomputed_state, state.lthash_state
    ) or not hmac.compare_digest(
        lthash_digest(state.lthash_state), state.commit.state_hash
    ):
        _fail("spaces_transition_invalid", "qualified state accumulator is invalid")
    qualification_receipt_ids: tuple[str, ...]
    if isinstance(state, QualifiedEmptyRepoState):
        commit_block_cid = state.empty_receipt.commit_block_cid
        index_block_cid = state.empty_receipt.index_block_cid
        qualification_receipt_ids = (state.empty_receipt.receipt_id,)
    else:
        qualification_receipt_ids = tuple(
            receipt.receipt_id for receipt in state.receipts
        )
    assert commit_block_cid is not None and index_block_cid is not None
    record_index_sha256 = hashlib.sha256(
        "\x00".join(index_fields).encode("utf-8")
    ).hexdigest()
    return TransitionStateIdentity(
        space=state.space,
        author_did=state.author_did,
        repo_rev=state.commit.rev,
        repo_commit_hash=state.commit.state_hash.hex(),
        commit_block_cid=commit_block_cid,
        index_block_cid=index_block_cid,
        record_index_sha256=record_index_sha256,
        record_count=len(state.records),
        qualification_receipt_ids=qualification_receipt_ids,
    )


def _receipt_identifier(
    *,
    source: TransitionStateIdentity,
    target: TransitionStateIdentity,
    effects: tuple[TransitionRecordEffect, ...],
    verified_at: datetime,
) -> str:
    fields = [
        "spaces-transition-receipt-v1",
        ALPHA_LABEL,
        SA4_TRANSITION_METHOD,
        SA4_TRANSITION_VERSION,
        source.space.uri,
        source.author_did,
        source.repo_rev,
        source.repo_commit_hash,
        source.commit_block_cid,
        source.index_block_cid,
        source.record_index_sha256,
        target.repo_rev,
        target.repo_commit_hash,
        target.commit_block_cid,
        target.index_block_cid,
        target.record_index_sha256,
        verified_at.astimezone(UTC).isoformat(),
        *(f"source-receipt:{item}" for item in source.qualification_receipt_ids),
        *(f"target-receipt:{item}" for item in target.qualification_receipt_ids),
        *sorted(claim.value for claim in _TRANSITION_CLAIMS),
        *(
            "\x00".join(
                (
                    str(effect.ordinal),
                    effect.kind.value,
                    effect.rev,
                    effect.path,
                    effect.prior_cid or "-",
                    effect.resulting_cid or "-",
                )
            )
            for effect in effects
        ),
    ]
    return "sha256:" + hashlib.sha256("\x00".join(fields).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SpaceTransitionReceipt:
    receipt_id: str
    source_state: TransitionStateIdentity
    target_state: TransitionStateIdentity
    effects: tuple[TransitionRecordEffect, ...]
    verified_at: datetime
    verified_claims: frozenset[VerifiedTransitionClaim] = field(
        default=_TRANSITION_CLAIMS, init=False
    )
    protocol_assumption: str = field(default=ALPHA_LABEL, init=False)
    qualification_method: str = field(default=SA4_TRANSITION_METHOD, init=False)
    qualifier_version: str = field(default=SA4_TRANSITION_VERSION, init=False)
    operation_ordering: str = field(default="supplied_order_preserved", init=False)
    complete_history: bool = False
    signed_ancestry: bool = False
    operation_log_authenticated: bool = False
    actor_legitimacy: bool = False
    authorization: bool = False
    governance_authority: bool = False

    def __post_init__(self) -> None:
        _receipt_digest(self.receipt_id, field_name="transition receipt")
        if not isinstance(self.source_state, TransitionStateIdentity) or not isinstance(
            self.target_state, TransitionStateIdentity
        ):
            _fail("spaces_transition_receipt_invalid", "state identities are invalid")
        if (
            self.source_state.space != self.target_state.space
            or self.source_state.author_did != self.target_state.author_did
            or self.source_state.repo_rev >= self.target_state.repo_rev
        ):
            _fail(
                "spaces_transition_receipt_invalid",
                "transition state identities are incompatible",
            )
        if not isinstance(self.effects, tuple) or not self.effects:
            _fail(
                "spaces_transition_receipt_invalid", "transition effects are required"
            )
        if any(
            not isinstance(effect, TransitionRecordEffect) for effect in self.effects
        ):
            _fail(
                "spaces_transition_receipt_invalid",
                "transition effects have an invalid shape",
            )
        if tuple(effect.ordinal for effect in self.effects) != tuple(
            range(len(self.effects))
        ):
            _fail(
                "spaces_transition_receipt_invalid",
                "transition effect order is not contiguous",
            )
        if any(effect.rev != self.target_state.repo_rev for effect in self.effects):
            _fail(
                "spaces_transition_receipt_invalid",
                "transition effects do not share the target revision",
            )
        object.__setattr__(self, "verified_at", _checked_at(self.verified_at))
        if (
            self.verified_claims != _TRANSITION_CLAIMS
            or self.protocol_assumption != ALPHA_LABEL
            or self.qualification_method != SA4_TRANSITION_METHOD
            or self.qualifier_version != SA4_TRANSITION_VERSION
            or self.operation_ordering != "supplied_order_preserved"
        ):
            _fail(
                "spaces_transition_receipt_invalid",
                "transition receipt compatibility fields are invalid",
            )
        if any(
            (
                self.complete_history,
                self.signed_ancestry,
                self.operation_log_authenticated,
                self.actor_legitimacy,
                self.authorization,
                self.governance_authority,
            )
        ):
            _fail(
                "spaces_transition_receipt_invalid",
                "transition receipt cannot confer history, legitimacy, or authority",
            )
        expected = _receipt_identifier(
            source=self.source_state,
            target=self.target_state,
            effects=self.effects,
            verified_at=self.verified_at,
        )
        if self.receipt_id != expected:
            _fail(
                "spaces_transition_receipt_invalid",
                "transition receipt identifier is not bound",
            )

    def to_provenance(self) -> MappingProxyType[str, object]:
        return MappingProxyType(
            {
                "receiptId": self.receipt_id,
                "claimScope": "single_supplied_transition_batch",
                "protocolAssumption": self.protocol_assumption,
                "qualificationMethod": self.qualification_method,
                "qualifierVersion": self.qualifier_version,
                "verifiedAt": self.verified_at.isoformat(),
                "verifiedClaims": tuple(
                    sorted(claim.value for claim in self.verified_claims)
                ),
                "sourceState": self.source_state.to_provenance(),
                "targetState": self.target_state.to_provenance(),
                "recordEffects": tuple(
                    effect.to_provenance() for effect in self.effects
                ),
                "operationOrdering": self.operation_ordering,
                "completeHistory": False,
                "signedAncestry": False,
                "operationLogAuthenticated": False,
                "actorLegitimacy": False,
                "authorization": False,
                "governanceAuthority": False,
            }
        )


@dataclass(frozen=True, slots=True)
class QualifiedSpaceTransition:
    source: QualifiedRepoState
    target: QualifiedRepoState
    receipt: SpaceTransitionReceipt

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, SpaceTransitionReceipt):
            _fail("spaces_transition_receipt_invalid", "transition receipt is required")
        if self.receipt.source_state != _state_identifier(
            self.source
        ) or self.receipt.target_state != _state_identifier(self.target):
            _fail(
                "spaces_transition_receipt_invalid",
                "transition result does not match its receipt",
            )


def identify_qualified_repo_state(state: QualifiedRepoState) -> TransitionStateIdentity:
    """Return SA4's bounded identity for an already SA1-qualified state."""

    return _state_identifier(state)


def qualify_repo_transition(
    source_state: QualifiedRepoState,
    target_evidence: SpaceRepoEvidence,
    *,
    expected_space: SpaceIdentity,
    expected_author_did: str,
    author_public_key: bytes,
    signature_algorithm: str,
    source: QualificationSourceContext,
    verified_at: datetime,
) -> QualifiedSpaceTransition:
    """Qualify one exact supplied operation batch between two SA1 states."""

    source_identity = _state_identifier(source_state)
    if not isinstance(target_evidence, SpaceRepoEvidence):
        _fail("spaces_transition_invalid", "target Spaces evidence is required")
    transition = target_evidence.transition
    if transition is None:
        _fail(
            "spaces_transition_evidence_required",
            "snapshot evidence has no supplied transition batch",
        )
    source_index = {
        f"{record.identity.collection}/{record.identity.rkey}": record.cid
        for record in source_state.records
    }
    if (
        transition.prior_rev != source_state.commit.rev
        or not hmac.compare_digest(transition.prior_state, source_state.lthash_state)
        or dict(transition.prior_index) != source_index
    ):
        _fail(
            "spaces_transition_source_mismatch",
            "supplied transition does not begin at the qualified source state",
        )
    target = qualify_repo_state(
        target_evidence,
        expected_space=expected_space,
        expected_author_did=expected_author_did,
        author_public_key=author_public_key,
        signature_algorithm=signature_algorithm,
        source=source,
        verified_at=verified_at,
    )
    target_identity = _state_identifier(target)
    if (
        source_identity.space != target_identity.space
        or source_identity.author_did != target_identity.author_did
        or any(
            VerifiedSpaceClaim.STATE_TRANSITION not in receipt.verified_claims
            for receipt in target.receipts
        )
    ):
        _fail(
            "spaces_transition_invalid",
            "target is not a compatible SA1-qualified transition state",
        )
    effects = tuple(
        TransitionRecordEffect(
            ordinal=ordinal,
            kind=_operation_kind(operation),
            rev=operation.rev,
            collection=operation.collection,
            rkey=operation.rkey,
            prior_cid=operation.prev,
            resulting_cid=operation.cid,
        )
        for ordinal, operation in enumerate(transition.operations)
    )
    checked_at = _checked_at(verified_at)
    receipt_id = _receipt_identifier(
        source=source_identity,
        target=target_identity,
        effects=effects,
        verified_at=checked_at,
    )
    receipt = SpaceTransitionReceipt(
        receipt_id=receipt_id,
        source_state=source_identity,
        target_state=target_identity,
        effects=effects,
        verified_at=checked_at,
    )
    return QualifiedSpaceTransition(source=source_state, target=target, receipt=receipt)


__all__ = [
    "QualifiedSpaceTransition",
    "SpaceTransitionReceipt",
    "TransitionOperationKind",
    "TransitionRecordEffect",
    "TransitionStateIdentity",
    "VerifiedTransitionClaim",
    "identify_qualified_repo_state",
    "qualify_repo_transition",
]
