"""SA10a state-level qualification for an empty permissioned repository."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType

from community_model import ValidationError, cid_for_dag_cbor

from .compat import ALPHA_LABEL, SA10A_EMPTY_STATE_METHOD, SA10A_EMPTY_STATE_VERSION
from .model import SpaceIdentity
from .qualification import (
    QualificationSourceContext,
    QualifiedRepoState,
    SpaceRepoEvidence,
    qualify_repo_state,
)

_NON = frozenset(
    {
        "record_existence",
        "complete_history",
        "currentness",
        "authority",
        "standing",
        "authorization",
        "governance_authority",
    }
)


def _fail(message: str) -> None:
    raise ValidationError("spaces_empty_state_invalid", message)


class EmptyStateClaim(StrEnum):
    SA1_COMMIT = "sa1_commit_qualified"
    EMPTY_INDEX = "canonical_empty_index"
    ZERO_LTHASH = "zero_record_lthash_state"
    NO_RECORDS = "no_record_blocks_or_receipts"


@dataclass(frozen=True, slots=True)
class EmptyRepoStateReceipt:
    receipt_id: str
    space: SpaceIdentity
    author_did: str
    repo_rev: str
    repo_commit_hash: str
    commit_block_cid: str
    index_block_cid: str
    lthash_state_sha256: str
    source_vector_identifier: str
    source_context: MappingProxyType[str, str]
    verified_at: datetime
    verified_claims: frozenset[EmptyStateClaim] = field(
        default=frozenset(EmptyStateClaim)
    )
    explicit_non_claims: frozenset[str] = field(default=_NON)
    method: str = field(default=SA10A_EMPTY_STATE_METHOD, init=False)
    version: str = field(default=SA10A_EMPTY_STATE_VERSION, init=False)

    def __post_init__(self) -> None:
        if (
            self.verified_claims != frozenset(EmptyStateClaim)
            or self.explicit_non_claims != _NON
            or self.receipt_id != _rid(self)
        ):
            _fail("empty-state receipt is not bound")

    def to_provenance(self) -> dict[str, object]:
        return {
            "receiptId": self.receipt_id,
            "space": self.space.uri,
            "authorDid": self.author_did,
            "repoRev": self.repo_rev,
            "repoCommitHash": self.repo_commit_hash,
            "commitBlockCid": self.commit_block_cid,
            "indexBlockCid": self.index_block_cid,
            "lthashStateSha256": self.lthash_state_sha256,
            "sourceVectorIdentifier": self.source_vector_identifier,
            "sourceContext": dict(self.source_context),
            "verifiedAt": self.verified_at.isoformat(),
            "verifiedClaims": sorted(x.value for x in self.verified_claims),
            "explicitNonClaims": sorted(self.explicit_non_claims),
        }


def _rid(r: EmptyRepoStateReceipt) -> str:
    values = (
        ALPHA_LABEL,
        SA10A_EMPTY_STATE_METHOD,
        SA10A_EMPTY_STATE_VERSION,
        r.space.uri,
        r.author_did,
        r.repo_rev,
        r.repo_commit_hash,
        r.commit_block_cid,
        r.index_block_cid,
        r.lthash_state_sha256,
        r.source_vector_identifier,
        r.verified_at.isoformat(),
        *(f"{k}={v}" for k, v in sorted(r.source_context.items())),
        *(x.value for x in sorted(r.verified_claims, key=lambda x: x.value)),
    )
    return "sha256:" + hashlib.sha256("\x00".join(values).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class QualifiedEmptyRepoState(QualifiedRepoState):
    empty_receipt: EmptyRepoStateReceipt

    def __post_init__(self) -> None:
        if (
            self.records
            or self.receipts
            or self.lthash_state != bytes(len(self.lthash_state))
        ):
            _fail("qualified empty state is not empty")
        if (
            self.empty_receipt.space != self.space
            or self.empty_receipt.author_did != self.author_did
            or self.empty_receipt.repo_rev != self.commit.rev
            or self.empty_receipt.repo_commit_hash != self.commit.state_hash.hex()
        ):
            _fail("empty receipt differs from state")


def qualify_empty_repo_state(
    evidence: SpaceRepoEvidence,
    *,
    expected_space: SpaceIdentity,
    expected_author_did: str,
    author_public_key: bytes,
    signature_algorithm: str,
    source: QualificationSourceContext,
    verified_at: datetime,
) -> QualifiedEmptyRepoState:
    state = qualify_repo_state(
        evidence,
        expected_space=expected_space,
        expected_author_did=expected_author_did,
        author_public_key=author_public_key,
        signature_algorithm=signature_algorithm,
        source=source,
        verified_at=verified_at,
    )
    if state.records or state.receipts or evidence.record_blocks:
        _fail("empty qualifier accepts no records")
    context = MappingProxyType(dict(source.unverified_context()))
    checked = verified_at.astimezone(UTC)
    fields = dict(
        receipt_id="",
        space=state.space,
        author_did=state.author_did,
        repo_rev=state.commit.rev,
        repo_commit_hash=state.commit.state_hash.hex(),
        commit_block_cid=cid_for_dag_cbor(evidence.commit_bytes),
        index_block_cid=cid_for_dag_cbor(evidence.index_bytes),
        lthash_state_sha256=hashlib.sha256(state.lthash_state).hexdigest(),
        source_vector_identifier=evidence.source_vector_identifier,
        source_context=context,
        verified_at=checked,
    )
    provisional = EmptyRepoStateReceipt.__new__(EmptyRepoStateReceipt)
    for k, v in fields.items():
        object.__setattr__(provisional, k, v)
    object.__setattr__(provisional, "verified_claims", frozenset(EmptyStateClaim))
    object.__setattr__(provisional, "explicit_non_claims", _NON)
    object.__setattr__(provisional, "method", SA10A_EMPTY_STATE_METHOD)
    object.__setattr__(provisional, "version", SA10A_EMPTY_STATE_VERSION)
    fields["receipt_id"] = _rid(provisional)
    receipt = EmptyRepoStateReceipt(**fields)
    return QualifiedEmptyRepoState(
        state.space,
        state.author_did,
        state.commit,
        state.lthash_state,
        state.records,
        state.receipts,
        receipt,
    )


__all__ = [
    "EmptyRepoStateReceipt",
    "EmptyStateClaim",
    "QualifiedEmptyRepoState",
    "qualify_empty_repo_state",
]
