"""Fixture-backed cryptographic qualification for permissioned repo state.

The verifier consumes Spaces-specific commit, index, and record bytes.  It
does not consume public repo proofs, resolve DIDs, authenticate a service, or
interpret any established fact as governance authority.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType

from community_model import (
    ValidationError,
    cid_for_dag_cbor,
    decode_dag_cbor,
    encode_dag_cbor,
)
from community_model.identifiers import (
    validate_cid,
    validate_did,
    validate_nsid,
    validate_rkey,
    validate_tid,
)

from .compat import (
    ALPHA_LABEL,
    COMMIT_CONTEXT_TAG,
    COMMIT_FORMAT,
    LTHASH_STATE_BYTES,
    PERMISSIONED_REPO_PROOF_KIND,
    PUBLIC_REPO_PROOF_KIND,
    REQUIRED_REPO_VERIFICATION_CLAIMS,
    SA1_VERIFICATION_METHOD,
    SA1_VERIFIER_VERSION,
    SUPPORTED_SIGNATURE_ALGORITHMS,
)
from .crypto import commit_mac, lthash_add, lthash_digest, verify_es256k
from .model import (
    RepoRecord,
    RepoVerification,
    SpaceIdentity,
    SpaceRecordIdentity,
    VerificationMode,
)


def _fail(reason: str, message: str) -> None:
    raise ValidationError(reason, message)


def _nonempty(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail("spaces_qualification_invalid", f"{field} must be nonempty text")
    return value


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        _fail("spaces_qualification_invalid", "verified_at must be timezone-aware")
    return value.astimezone(UTC)


def _freeze_text_map(value: Mapping[str, str], *, field: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        _fail("spaces_qualification_invalid", f"{field} must be a mapping")
    result: dict[str, str] = {}
    for key, item in value.items():
        result[_nonempty(key, field=f"{field} key")] = _nonempty(
            item, field=f"{field} value"
        )
    return MappingProxyType(result)


class VerifiedSpaceClaim(StrEnum):
    COMMIT_STRUCTURE = "commit_structure"
    COMMIT_CONTEXT = "commit_context_space_author_rev_ikm"
    AUTHOR_SIGNATURE = "author_signature_against_supplied_key"
    COMMIT_MAC = "commit_mac_context_hash_binding"
    LTHASH_REPOSITORY_STATE = "lthash_repository_state"
    RECORD_CID = "record_cid"
    RECORD_DAG_CBOR = "record_canonical_dag_cbor"
    RECORD_PATH = "record_index_path"
    AUTHOR_BINDING = "record_author_matches_signed_context"
    SPACE_BINDING = "record_space_matches_signed_context"
    STATE_TRANSITION = "state_transition_from_supplied_prior"


_BASE_RECEIPT_CLAIMS = frozenset(
    {
        VerifiedSpaceClaim.COMMIT_STRUCTURE,
        VerifiedSpaceClaim.COMMIT_CONTEXT,
        VerifiedSpaceClaim.AUTHOR_SIGNATURE,
        VerifiedSpaceClaim.COMMIT_MAC,
        VerifiedSpaceClaim.LTHASH_REPOSITORY_STATE,
        VerifiedSpaceClaim.RECORD_CID,
        VerifiedSpaceClaim.RECORD_DAG_CBOR,
        VerifiedSpaceClaim.RECORD_PATH,
        VerifiedSpaceClaim.AUTHOR_BINDING,
        VerifiedSpaceClaim.SPACE_BINDING,
    }
)


@dataclass(frozen=True, slots=True)
class SignedSpaceCommit:
    version: int
    state_hash: bytes
    mac: bytes
    ikm: bytes
    signature: bytes
    rev: str

    @classmethod
    def parse(cls, commit_bytes: bytes) -> SignedSpaceCommit:
        if not isinstance(commit_bytes, bytes):
            _fail("spaces_commit_invalid", "commit block must be bytes")
        try:
            raw = decode_dag_cbor(commit_bytes)
        except ValidationError as exc:
            raise ValidationError(
                "spaces_commit_invalid", "commit is not canonical DAG-CBOR"
            ) from exc
        if not isinstance(raw, Mapping) or set(raw) != {
            "ver",
            "hash",
            "mac",
            "ikm",
            "sig",
            "rev",
        }:
            _fail("spaces_commit_invalid", "commit fields do not match alpha v1")
        version = raw["ver"]
        if isinstance(version, bool) or not isinstance(version, int):
            _fail("spaces_commit_invalid", "commit version must be an integer")
        if version != COMMIT_FORMAT:
            _fail(
                "spaces_alpha_compatibility_failure",
                f"unsupported Spaces commit version {version}",
            )
        state_hash = raw["hash"]
        mac = raw["mac"]
        ikm = raw["ikm"]
        signature = raw["sig"]
        if not isinstance(state_hash, bytes) or len(state_hash) != 32:
            _fail("spaces_commit_invalid", "commit hash must be 32 bytes")
        if not isinstance(mac, bytes) or len(mac) != 32:
            _fail("spaces_commit_invalid", "commit MAC must be 32 bytes")
        if not isinstance(ikm, bytes) or len(ikm) != 32:
            _fail("spaces_commit_invalid", "commit ikm must be 32 bytes")
        if not isinstance(signature, bytes) or len(signature) != 64:
            _fail(
                "spaces_commit_invalid",
                "SA1 ES256K signatures must be compact 64-byte values",
            )
        rev = raw["rev"]
        validate_tid(rev)
        return cls(version, state_hash, mac, ikm, signature, rev)


@dataclass(frozen=True, slots=True)
class SpaceRecordBlock:
    collection: str
    rkey: str
    cid: str
    record_bytes: bytes

    def __post_init__(self) -> None:
        validate_nsid(self.collection)
        validate_rkey(self.rkey)
        validate_cid(self.cid, require_dag_cbor=True)
        if not isinstance(self.record_bytes, bytes):
            _fail("spaces_record_content_invalid", "record block must be bytes")


@dataclass(frozen=True, slots=True)
class RepoOperation:
    rev: str
    collection: str
    rkey: str
    cid: str | None
    prev: str | None

    def __post_init__(self) -> None:
        validate_tid(self.rev)
        validate_nsid(self.collection)
        validate_rkey(self.rkey)
        if self.cid is not None:
            validate_cid(self.cid, require_dag_cbor=True)
        if self.prev is not None:
            validate_cid(self.prev, require_dag_cbor=True)
        if self.cid is None and self.prev is None:
            _fail("spaces_transition_invalid", "operation changes no record")


def _validated_index(value: Mapping[str, str], *, field: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        _fail("spaces_index_invalid", f"{field} must be a path-to-CID mapping")
    result: dict[str, str] = {}
    for path, cid in value.items():
        if not isinstance(path, str) or path.count("/") != 1:
            _fail("spaces_index_invalid", f"invalid record path in {field}")
        collection, rkey = path.split("/", 1)
        validate_nsid(collection)
        validate_rkey(rkey)
        validate_cid(cid, require_dag_cbor=True)
        result[path] = cid
    return MappingProxyType(result)


@dataclass(frozen=True, slots=True)
class RepoTransition:
    prior_rev: str
    prior_state: bytes
    prior_index: Mapping[str, str]
    operations: tuple[RepoOperation, ...]

    def __post_init__(self) -> None:
        validate_tid(self.prior_rev)
        if not isinstance(self.prior_state, bytes) or len(self.prior_state) != (
            LTHASH_STATE_BYTES
        ):
            _fail(
                "spaces_transition_invalid",
                "prior LtHash state must be exactly 2048 bytes",
            )
        object.__setattr__(
            self,
            "prior_index",
            _validated_index(self.prior_index, field="prior_index"),
        )
        if not isinstance(self.operations, list | tuple) or not self.operations:
            _fail("spaces_transition_invalid", "transition needs operations")
        if any(not isinstance(item, RepoOperation) for item in self.operations):
            _fail("spaces_transition_invalid", "transition operation shape is invalid")
        object.__setattr__(self, "operations", tuple(self.operations))


@dataclass(frozen=True, slots=True)
class SpaceRepoEvidence:
    source_vector_identifier: str
    proof_kind: str
    protocol_assumption: str
    commit_bytes: bytes
    index_bytes: bytes
    record_blocks: tuple[SpaceRecordBlock, ...]
    transition: RepoTransition | None = None

    def __post_init__(self) -> None:
        _nonempty(self.source_vector_identifier, field="source_vector_identifier")
        _nonempty(self.proof_kind, field="proof_kind")
        _nonempty(self.protocol_assumption, field="protocol_assumption")
        if not isinstance(self.commit_bytes, bytes) or not isinstance(
            self.index_bytes, bytes
        ):
            _fail("spaces_qualification_invalid", "commit and index must be bytes")
        if not isinstance(self.record_blocks, list | tuple) or any(
            not isinstance(item, SpaceRecordBlock) for item in self.record_blocks
        ):
            _fail("spaces_qualification_invalid", "record blocks are invalid")
        object.__setattr__(self, "record_blocks", tuple(self.record_blocks))
        if self.transition is not None and not isinstance(
            self.transition, RepoTransition
        ):
            _fail("spaces_transition_invalid", "transition shape is invalid")


@dataclass(frozen=True, slots=True)
class QualificationSourceContext:
    repo_host: str
    author_key_ref: str
    author_key_binding_method: str
    evidence_ref: str
    writer_discovery_ref: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.repo_host, str)
            or not self.repo_host.startswith("https://")
            or any(character.isspace() for character in self.repo_host)
        ):
            _fail("spaces_qualification_invalid", "repo_host must be an HTTPS URL")
        object.__setattr__(self, "repo_host", self.repo_host.rstrip("/"))
        for field in (
            "author_key_ref",
            "author_key_binding_method",
            "evidence_ref",
        ):
            _nonempty(getattr(self, field), field=field)
        if self.writer_discovery_ref is not None:
            _nonempty(self.writer_discovery_ref, field="writer_discovery_ref")

    def unverified_context(self) -> Mapping[str, str]:
        result = {
            "repoHost": self.repo_host,
            "authorKeyRef": self.author_key_ref,
            "authorKeyBindingMethod": self.author_key_binding_method,
            "evidenceRef": self.evidence_ref,
        }
        if self.writer_discovery_ref is not None:
            result["writerDiscoveryRef"] = self.writer_discovery_ref
        return MappingProxyType(result)


def _receipt_identifier(
    *,
    space: SpaceIdentity,
    record: SpaceRecordIdentity,
    record_cid: str,
    repo_rev: str,
    repo_commit_hash: str,
    claims: frozenset[VerifiedSpaceClaim],
    cryptographic_inputs: Mapping[str, str],
    unverified_context: Mapping[str, str],
    source_vector_identifier: str,
    verified_at: datetime,
) -> str:
    fields = [
        "spaces-observation-receipt-v1",
        space.uri,
        record.uri,
        record_cid,
        repo_rev,
        repo_commit_hash,
        source_vector_identifier,
        verified_at.astimezone(UTC).isoformat(),
        ALPHA_LABEL,
        str(COMMIT_FORMAT),
        SA1_VERIFICATION_METHOD,
        SA1_VERIFIER_VERSION,
        *sorted(claim.value for claim in claims),
        *(f"{key}={value}" for key, value in sorted(cryptographic_inputs.items())),
        *(
            f"context:{key}={value}"
            for key, value in sorted(unverified_context.items())
        ),
    ]
    return "sha256:" + hashlib.sha256("\x00".join(fields).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SpaceObservationReceipt:
    receipt_id: str
    space_identity: SpaceIdentity
    record_identity: SpaceRecordIdentity
    record_cid: str
    repo_rev: str
    repo_commit_hash: str
    verified_claims: frozenset[VerifiedSpaceClaim]
    cryptographic_inputs: Mapping[str, str]
    unverified_context: Mapping[str, str]
    source_vector_identifier: str
    verified_at: datetime
    protocol_assumption: str = ALPHA_LABEL
    commit_format: int = COMMIT_FORMAT
    verification_method: str = SA1_VERIFICATION_METHOD
    verifier_version: str = SA1_VERIFIER_VERSION
    governance_authority: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.space_identity, SpaceIdentity) or not isinstance(
            self.record_identity, SpaceRecordIdentity
        ):
            _fail("spaces_qualification_invalid", "receipt identities are invalid")
        if self.record_identity.space != self.space_identity:
            _fail("spaces_binding_invalid", "receipt record targets another Space")
        validate_cid(self.record_cid, require_dag_cbor=True)
        validate_tid(self.repo_rev)
        if (
            not isinstance(self.repo_commit_hash, str)
            or len(self.repo_commit_hash) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.repo_commit_hash
            )
        ):
            _fail("spaces_qualification_invalid", "receipt commit hash is invalid")
        if not isinstance(self.verified_claims, frozenset) or any(
            not isinstance(claim, VerifiedSpaceClaim) for claim in self.verified_claims
        ):
            _fail("spaces_qualification_invalid", "receipt claims are invalid")
        if not _BASE_RECEIPT_CLAIMS <= self.verified_claims:
            _fail("spaces_qualification_invalid", "receipt claims are incomplete")
        object.__setattr__(
            self,
            "cryptographic_inputs",
            _freeze_text_map(self.cryptographic_inputs, field="cryptographic_inputs"),
        )
        object.__setattr__(
            self,
            "unverified_context",
            _freeze_text_map(self.unverified_context, field="unverified_context"),
        )
        _nonempty(self.source_vector_identifier, field="source_vector_identifier")
        object.__setattr__(self, "verified_at", _utc(self.verified_at))
        if (
            self.protocol_assumption != ALPHA_LABEL
            or self.commit_format != COMMIT_FORMAT
        ):
            _fail(
                "spaces_alpha_compatibility_failure",
                "receipt uses unsupported alpha semantics",
            )
        if self.verification_method != SA1_VERIFICATION_METHOD:
            _fail("spaces_qualification_invalid", "unexpected verification method")
        if self.verifier_version != SA1_VERIFIER_VERSION:
            _fail("spaces_qualification_invalid", "unexpected verifier version")
        if self.governance_authority is not False:
            _fail(
                "spaces_qualification_invalid",
                "Spaces qualification cannot confer governance authority",
            )
        expected = _receipt_identifier(
            space=self.space_identity,
            record=self.record_identity,
            record_cid=self.record_cid,
            repo_rev=self.repo_rev,
            repo_commit_hash=self.repo_commit_hash,
            claims=self.verified_claims,
            cryptographic_inputs=self.cryptographic_inputs,
            unverified_context=self.unverified_context,
            source_vector_identifier=self.source_vector_identifier,
            verified_at=self.verified_at,
        )
        if self.receipt_id != expected:
            _fail("spaces_qualification_invalid", "receipt identifier is not bound")

    def to_provenance(self) -> Mapping[str, object]:
        return {
            "receiptId": self.receipt_id,
            "protocolAssumption": self.protocol_assumption,
            "commitFormat": self.commit_format,
            "verificationMethod": self.verification_method,
            "verifierVersion": self.verifier_version,
            "sourceVectorIdentifier": self.source_vector_identifier,
            "verifiedAt": self.verified_at.isoformat(),
            "verifiedClaims": sorted(claim.value for claim in self.verified_claims),
            "cryptographicInputs": dict(self.cryptographic_inputs),
            "unverifiedContext": dict(self.unverified_context),
            "governanceAuthority": False,
        }


@dataclass(frozen=True, slots=True)
class QualifiedRepoState:
    space: SpaceIdentity
    author_did: str
    commit: SignedSpaceCommit
    lthash_state: bytes
    records: tuple[RepoRecord, ...]
    receipts: tuple[SpaceObservationReceipt, ...]

    def repo_verification(
        self,
        *,
        source: QualificationSourceContext,
        verified_at: datetime,
    ) -> RepoVerification:
        checked_at = _utc(verified_at)
        expected_context = source.unverified_context()
        if any(
            receipt.verified_at != checked_at
            or receipt.unverified_context != expected_context
            for receipt in self.receipts
        ):
            _fail(
                "spaces_qualification_invalid",
                "repo verification metadata differs from its receipts",
            )
        return RepoVerification(
            mode=VerificationMode.VERIFIED,
            space=self.space,
            author_did=self.author_did,
            repo_host=source.repo_host,
            rev=self.commit.rev,
            commit_hash=self.commit.state_hash.hex(),
            verified_at=checked_at,
            method=SA1_VERIFICATION_METHOD,
            verifier_version=SA1_VERIFIER_VERSION,
            author_key_ref=source.author_key_ref,
            evidence_ref=source.evidence_ref,
            claims=REQUIRED_REPO_VERIFICATION_CLAIMS,
            qualification_receipt_ids=tuple(
                receipt.receipt_id for receipt in self.receipts
            ),
        )


def encode_commit_context(
    space: SpaceIdentity, author_did: str, rev: str, ikm: bytes
) -> bytes:
    validate_did(author_did)
    validate_tid(rev)
    if not isinstance(ikm, bytes) or len(ikm) != 32:
        _fail("spaces_commit_invalid", "commit ikm must be 32 bytes")
    fields = (space.uri.encode(), author_did.encode(), rev.encode(), ikm)
    result = bytearray(COMMIT_CONTEXT_TAG.encode())
    for field in fields:
        if len(field) > 0xFFFF:
            _fail("spaces_commit_invalid", "commit context field is too long")
        result.extend(len(field).to_bytes(2, "big"))
        result.extend(field)
    return bytes(result)


def parse_repo_index(index_bytes: bytes) -> Mapping[str, str]:
    """Parse the pinned alpha index shape shared by SA1 and SA2 handoff."""

    try:
        raw = decode_dag_cbor(index_bytes)
    except ValidationError as exc:
        raise ValidationError(
            "spaces_index_invalid", "index is not canonical DAG-CBOR"
        ) from exc
    if not isinstance(raw, Mapping):
        _fail("spaces_index_invalid", "index must be a DAG-CBOR map")
    links: dict[str, str] = {}
    for path, link in raw.items():
        if not isinstance(link, Mapping) or set(link) != {"$link"}:
            _fail("spaces_index_invalid", "index values must be CID links")
        cid = link["$link"]
        if not isinstance(cid, str):
            _fail("spaces_index_invalid", "index CID link is invalid")
        links[path] = cid
    return _validated_index(links, field="index")


def _state_from_index(index: Mapping[str, str]) -> bytes:
    state = bytes(LTHASH_STATE_BYTES)
    for path, cid in index.items():
        state = lthash_add(state, f"{path}/{cid}")
    return state


def _verify_transition(
    transition: RepoTransition,
    *,
    current_index: Mapping[str, str],
    current_state: bytes,
    commit_rev: str,
) -> None:
    prior_recomputed = _state_from_index(transition.prior_index)
    if not hmac.compare_digest(prior_recomputed, transition.prior_state):
        _fail(
            "spaces_transition_invalid",
            "supplied prior state does not match its index",
        )
    if transition.prior_rev >= commit_rev:
        _fail("spaces_transition_invalid", "prior revision is not before commit")
    staged_index = dict(transition.prior_index)
    staged_state = transition.prior_state
    for operation in transition.operations:
        if operation.rev != commit_rev:
            _fail(
                "spaces_transition_invalid",
                "SA1 transition operations must share the final commit revision",
            )
        path = f"{operation.collection}/{operation.rkey}"
        if staged_index.get(path) != operation.prev:
            _fail(
                "spaces_transition_invalid",
                "operation prev does not match supplied prior/current index",
            )
        if operation.prev is not None:
            staged_state = lthash_add(
                staged_state, f"{path}/{operation.prev}", subtract=True
            )
            del staged_index[path]
        if operation.cid is not None:
            staged_state = lthash_add(staged_state, f"{path}/{operation.cid}")
            staged_index[path] = operation.cid
    if staged_index != dict(current_index) or not hmac.compare_digest(
        staged_state, current_state
    ):
        _fail(
            "spaces_transition_invalid",
            "operations do not produce the verified repository state",
        )


def qualify_repo_state(
    evidence: SpaceRepoEvidence,
    *,
    expected_space: SpaceIdentity,
    expected_author_did: str,
    author_public_key: bytes,
    signature_algorithm: str,
    source: QualificationSourceContext,
    verified_at: datetime,
) -> QualifiedRepoState:
    """Qualify exact record existence in one pinned permissioned repo state."""

    if not isinstance(evidence, SpaceRepoEvidence):
        _fail("spaces_qualification_invalid", "Spaces repo evidence is required")
    if evidence.proof_kind == PUBLIC_REPO_PROOF_KIND:
        _fail(
            "spaces_public_proof_refused",
            "public CAR/MST proof cannot become a Spaces observation",
        )
    if evidence.proof_kind != PERMISSIONED_REPO_PROOF_KIND:
        _fail("spaces_qualification_invalid", "unsupported proof kind")
    if evidence.protocol_assumption != ALPHA_LABEL:
        _fail(
            "spaces_alpha_compatibility_failure",
            "evidence declares unsupported alpha semantics",
        )
    if not isinstance(expected_space, SpaceIdentity):
        _fail("spaces_binding_invalid", "expected Space identity is required")
    validate_did(expected_author_did)
    if signature_algorithm not in SUPPORTED_SIGNATURE_ALGORITHMS:
        _fail(
            "spaces_alpha_compatibility_failure",
            f"unsupported Spaces signature algorithm {signature_algorithm}",
        )
    if not isinstance(author_public_key, bytes):
        _fail("spaces_signature_invalid", "author public key must be bytes")
    if not isinstance(source, QualificationSourceContext):
        _fail("spaces_qualification_invalid", "source context is required")
    checked_at = _utc(verified_at)

    commit = SignedSpaceCommit.parse(evidence.commit_bytes)
    context = encode_commit_context(
        expected_space, expected_author_did, commit.rev, commit.ikm
    )
    expected_mac = commit_mac(commit.ikm, context, commit.state_hash)
    if not hmac.compare_digest(expected_mac, commit.mac):
        _fail("spaces_mac_invalid", "commit MAC does not bind context and hash")
    if not verify_es256k(author_public_key, context, commit.signature):
        _fail(
            "spaces_signature_invalid",
            "commit context signature does not match supplied author key",
        )

    index = parse_repo_index(evidence.index_bytes)
    state = _state_from_index(index)
    if not hmac.compare_digest(lthash_digest(state), commit.state_hash):
        _fail("spaces_lthash_invalid", "index LtHash does not match commit hash")

    index_items = tuple(index.items())
    if len(index_items) != len(evidence.record_blocks):
        _fail("spaces_record_content_invalid", "index and record count differ")
    records: list[RepoRecord] = []
    for (path, index_cid), block in zip(
        index_items, evidence.record_blocks, strict=True
    ):
        block_path = f"{block.collection}/{block.rkey}"
        if block_path != path or block.cid != index_cid:
            _fail(
                "spaces_record_content_invalid",
                "record order/path/CID does not match the canonical index",
            )
        if cid_for_dag_cbor(block.record_bytes) != block.cid:
            _fail("spaces_record_cid_invalid", "record bytes do not match CID")
        try:
            decoded = decode_dag_cbor(block.record_bytes)
        except ValidationError as exc:
            raise ValidationError(
                "spaces_record_content_invalid",
                "record is not canonical DAG-CBOR",
            ) from exc
        if not isinstance(decoded, Mapping) or encode_dag_cbor(decoded) != (
            block.record_bytes
        ):
            _fail(
                "spaces_record_content_invalid",
                "record is not a canonical DAG-CBOR map",
            )
        identity = SpaceRecordIdentity(
            space=expected_space,
            author_did=expected_author_did,
            collection=block.collection,
            rkey=block.rkey,
        )
        records.append(
            RepoRecord(
                identity=identity,
                cid=block.cid,
                record=decoded,
                record_bytes=block.record_bytes,
            )
        )

    claims = _BASE_RECEIPT_CLAIMS
    if evidence.transition is not None:
        _verify_transition(
            evidence.transition,
            current_index=index,
            current_state=state,
            commit_rev=commit.rev,
        )
        claims = claims | {VerifiedSpaceClaim.STATE_TRANSITION}

    common_inputs = {
        "authorPublicKeySha256": hashlib.sha256(author_public_key).hexdigest(),
        "commitBlockCid": cid_for_dag_cbor(evidence.commit_bytes),
        "commitContextSha256": hashlib.sha256(context).hexdigest(),
        "indexBlockCid": cid_for_dag_cbor(evidence.index_bytes),
        "lthashStateSha256": lthash_digest(state).hex(),
        "signatureAlgorithm": signature_algorithm,
    }
    unverified = source.unverified_context()
    receipts: list[SpaceObservationReceipt] = []
    for record in records:
        inputs = {**common_inputs, "recordBlockCid": record.cid}
        receipt_id = _receipt_identifier(
            space=expected_space,
            record=record.identity,
            record_cid=record.cid,
            repo_rev=commit.rev,
            repo_commit_hash=commit.state_hash.hex(),
            claims=claims,
            cryptographic_inputs=inputs,
            unverified_context=unverified,
            source_vector_identifier=evidence.source_vector_identifier,
            verified_at=checked_at,
        )
        receipts.append(
            SpaceObservationReceipt(
                receipt_id=receipt_id,
                space_identity=expected_space,
                record_identity=record.identity,
                record_cid=record.cid,
                repo_rev=commit.rev,
                repo_commit_hash=commit.state_hash.hex(),
                verified_claims=frozenset(claims),
                cryptographic_inputs=inputs,
                unverified_context=unverified,
                source_vector_identifier=evidence.source_vector_identifier,
                verified_at=checked_at,
            )
        )
    return QualifiedRepoState(
        space=expected_space,
        author_did=expected_author_did,
        commit=commit,
        lthash_state=state,
        records=tuple(records),
        receipts=tuple(receipts),
    )


__all__ = [
    "QualificationSourceContext",
    "QualifiedRepoState",
    "RepoOperation",
    "RepoTransition",
    "SignedSpaceCommit",
    "SpaceObservationReceipt",
    "SpaceRecordBlock",
    "SpaceRepoEvidence",
    "VerifiedSpaceClaim",
    "encode_commit_context",
    "parse_repo_index",
    "qualify_repo_state",
]
