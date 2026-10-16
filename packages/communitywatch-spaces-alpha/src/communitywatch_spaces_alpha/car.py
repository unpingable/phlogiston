"""Raw CAR transport boundary for the pinned Spaces alpha.

SA2 validates only container framing and content addressing, then constructs
the exact :class:`SpaceRepoEvidence` already consumed by SA1. It does not
produce observation receipts or establish identity, currentness, admission,
or authority.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from community_model import ValidationError, decode_dag_cbor
from community_model.identifiers import validate_cid

from .compat import (
    ALPHA_LABEL,
    CAR_DAG_CBOR_CODEC,
    CAR_ROOT_COUNT,
    CAR_SHA256_DIGEST_BYTES,
    CAR_SHA256_MULTIHASH,
    CAR_VERSION,
    PERMISSIONED_REPO_PROOF_KIND,
    SA2_CAR_ADAPTER_VERSION,
    SA2_CAR_METHOD,
)
from .qualification import (
    RepoTransition,
    SpaceRecordBlock,
    SpaceRepoEvidence,
    parse_repo_index,
)


def _fail(reason: str, message: str) -> None:
    raise ValidationError(reason, message)


def _nonempty(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail("spaces_car_invalid", f"{field} must be nonempty text")
    return value


def _encode_uvarint(value: int) -> bytes:
    if value < 0:
        raise ValueError("uvarint cannot encode a negative value")
    result = bytearray()
    while value >= 0x80:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def _read_uvarint(data: bytes, offset: int, *, field: str) -> tuple[int, int]:
    start = offset
    value = 0
    shift = 0
    while offset < len(data) and shift <= 63:
        octet = data[offset]
        offset += 1
        value |= (octet & 0x7F) << shift
        if not octet & 0x80:
            if value > 0xFFFF_FFFF_FFFF_FFFF:
                _fail("spaces_car_framing_invalid", f"{field} is too large")
            if data[start:offset] != _encode_uvarint(value):
                _fail("spaces_car_framing_invalid", f"{field} is not canonical")
            return value, offset
        shift += 7
    _fail("spaces_car_framing_invalid", f"{field} is truncated or too large")


def _cid_text(raw: bytes) -> str:
    return "b" + base64.b32encode(raw).decode("ascii").lower().rstrip("=")


@dataclass(frozen=True, slots=True)
class _RawCid:
    text: str
    length: int
    digest: bytes


def _read_cid(data: bytes, offset: int, *, field: str) -> _RawCid:
    start = offset
    version, offset = _read_uvarint(data, offset, field=f"{field} CID version")
    codec, offset = _read_uvarint(data, offset, field=f"{field} CID codec")
    hash_code, offset = _read_uvarint(data, offset, field=f"{field} multihash code")
    digest_length, offset = _read_uvarint(
        data, offset, field=f"{field} multihash length"
    )
    if (
        version != 1
        or codec != CAR_DAG_CBOR_CODEC
        or hash_code != CAR_SHA256_MULTIHASH
        or digest_length != CAR_SHA256_DIGEST_BYTES
    ):
        _fail(
            "spaces_car_compatibility_failure",
            f"{field} CID uses unsupported alpha components",
        )
    end = offset + digest_length
    if end > len(data):
        _fail("spaces_car_framing_invalid", f"{field} CID is truncated")
    raw = data[start:end]
    text = _cid_text(raw)
    validate_cid(text, require_dag_cbor=True)
    return _RawCid(text=text, length=len(raw), digest=data[offset:end])


class CarContainerClaim(StrEnum):
    CANONICAL_HEADER = "canonical_car_header"
    TWO_ORDERED_ROOTS = "two_ordered_root_identifiers"
    COMPLETE_BLOCK_FRAMING = "complete_length_delimited_blocks"
    DAG_CBOR_SHA256_CIDS = "dag_cbor_sha256_block_cids"
    BLOCK_CONTENT_ADDRESSES = "block_bytes_match_declared_cids"
    UNIQUE_BLOCK_IDENTIFIERS = "unique_block_identifiers"
    ORIGINAL_BLOCK_ORDER = "original_block_order_preserved"


_CONTAINER_CLAIMS = frozenset(CarContainerClaim)


@dataclass(frozen=True, slots=True)
class CarBlock:
    ordinal: int
    cid: str
    block_bytes: bytes

    def __post_init__(self) -> None:
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int):
            _fail("spaces_car_invalid", "block ordinal must be an integer")
        if self.ordinal < 0:
            _fail("spaces_car_invalid", "block ordinal cannot be negative")
        validate_cid(self.cid, require_dag_cbor=True)
        if not isinstance(self.block_bytes, bytes):
            _fail("spaces_car_invalid", "block content must be bytes")


@dataclass(frozen=True, slots=True)
class ParsedSpaceCar:
    version: int
    roots: tuple[str, str]
    blocks: tuple[CarBlock, ...]
    raw_sha256: str
    source_vector_identifier: str
    protocol_assumption: str
    container_claims: frozenset[CarContainerClaim] = field(
        default=_CONTAINER_CLAIMS, init=False
    )
    adapter_method: str = field(default=SA2_CAR_METHOD, init=False)
    adapter_version: str = field(default=SA2_CAR_ADAPTER_VERSION, init=False)

    def __post_init__(self) -> None:
        if self.version != CAR_VERSION or len(self.roots) != CAR_ROOT_COUNT:
            _fail("spaces_car_invalid", "parsed CAR violates pinned root shape")
        for root in self.roots:
            validate_cid(root, require_dag_cbor=True)
        if not isinstance(self.blocks, tuple) or any(
            not isinstance(block, CarBlock) for block in self.blocks
        ):
            _fail("spaces_car_invalid", "parsed CAR blocks are invalid")
        if tuple(block.ordinal for block in self.blocks) != tuple(
            range(len(self.blocks))
        ):
            _fail("spaces_car_invalid", "parsed CAR block order is not contiguous")
        if len(self.raw_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.raw_sha256
        ):
            _fail("spaces_car_invalid", "raw CAR digest is invalid")
        _nonempty(self.source_vector_identifier, field="source_vector_identifier")
        if self.protocol_assumption != ALPHA_LABEL:
            _fail(
                "spaces_car_compatibility_failure",
                "CAR declares unsupported Spaces alpha semantics",
            )
        if self.container_claims != _CONTAINER_CLAIMS:
            _fail("spaces_car_invalid", "container claims are incomplete")
        if (
            self.adapter_method != SA2_CAR_METHOD
            or self.adapter_version != SA2_CAR_ADAPTER_VERSION
        ):
            _fail("spaces_car_invalid", "unexpected CAR adapter identity")

    @property
    def block_index(self) -> Mapping[str, bytes]:
        return MappingProxyType({block.cid: block.block_bytes for block in self.blocks})

    def to_provenance(self) -> Mapping[str, object]:
        """Describe bounded container facts separately from supplied context."""

        return MappingProxyType(
            {
                "claimScope": "spaces_car_container_only",
                "adapterMethod": self.adapter_method,
                "adapterVersion": self.adapter_version,
                "carVersion": self.version,
                "rawCarSha256": self.raw_sha256,
                "orderedRootIdentifiers": self.roots,
                "orderedBlocks": tuple(
                    MappingProxyType(
                        {
                            "ordinal": block.ordinal,
                            "cid": block.cid,
                            "byteLength": len(block.block_bytes),
                        }
                    )
                    for block in self.blocks
                ),
                "verifiedContainerFacts": tuple(
                    sorted(claim.value for claim in self.container_claims)
                ),
                "unverifiedContext": MappingProxyType(
                    {
                        "protocolAssumption": self.protocol_assumption,
                        "sourceVectorIdentifier": self.source_vector_identifier,
                    }
                ),
                "semanticObservationClaims": (),
                "governanceAuthority": False,
            }
        )


@dataclass(frozen=True, slots=True)
class SpaceCarExtraction:
    """SA2 container result paired with the exact SA1 evidence handoff."""

    car: ParsedSpaceCar
    evidence: SpaceRepoEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.car, ParsedSpaceCar) or not isinstance(
            self.evidence, SpaceRepoEvidence
        ):
            _fail("spaces_car_invalid", "CAR extraction shape is invalid")


def parse_space_car(
    raw_car: bytes,
    *,
    source_vector_identifier: str,
    protocol_assumption: str = ALPHA_LABEL,
) -> ParsedSpaceCar:
    """Validate the pinned CAR container without qualifying repo semantics."""

    if not isinstance(raw_car, bytes) or not raw_car:
        _fail("spaces_car_framing_invalid", "raw CAR must be nonempty bytes")
    _nonempty(source_vector_identifier, field="source_vector_identifier")
    if protocol_assumption != ALPHA_LABEL:
        _fail(
            "spaces_car_compatibility_failure",
            "CAR declares unsupported Spaces alpha semantics",
        )

    header_length, cursor = _read_uvarint(raw_car, 0, field="header length")
    header_end = cursor + header_length
    if header_length == 0 or header_end > len(raw_car):
        _fail("spaces_car_framing_invalid", "CAR header is empty or truncated")
    header_bytes = raw_car[cursor:header_end]
    try:
        header = decode_dag_cbor(header_bytes)
    except ValidationError as exc:
        raise ValidationError(
            "spaces_car_framing_invalid", "CAR header is not canonical DAG-CBOR"
        ) from exc
    if not isinstance(header, Mapping) or set(header) != {"roots", "version"}:
        _fail("spaces_car_framing_invalid", "CAR header fields are invalid")
    version = header["version"]
    if isinstance(version, bool) or not isinstance(version, int):
        _fail("spaces_car_framing_invalid", "CAR version must be an integer")
    if version != CAR_VERSION:
        _fail(
            "spaces_car_compatibility_failure",
            f"unsupported CAR version {version}",
        )
    roots_value = header["roots"]
    if not isinstance(roots_value, tuple):
        _fail("spaces_car_framing_invalid", "CAR roots must be an array")
    if len(roots_value) != CAR_ROOT_COUNT:
        _fail(
            "spaces_car_root_count_invalid",
            f"Spaces alpha CAR requires exactly {CAR_ROOT_COUNT} roots",
        )
    roots: list[str] = []
    for root in roots_value:
        if not isinstance(root, Mapping) or set(root) != {"$link"}:
            _fail("spaces_car_framing_invalid", "CAR root must be a CID link")
        cid = root["$link"]
        validate_cid(cid, require_dag_cbor=True)
        assert isinstance(cid, str)
        roots.append(cid)

    blocks: list[CarBlock] = []
    indexed: dict[str, bytes] = {}
    cursor = header_end
    while cursor < len(raw_car):
        section_length, section_start = _read_uvarint(
            raw_car, cursor, field=f"block {len(blocks)} length"
        )
        section_end = section_start + section_length
        if section_length == 0 or section_end > len(raw_car):
            _fail(
                "spaces_car_framing_invalid",
                f"block {len(blocks)} is empty or truncated",
            )
        raw_cid = _read_cid(raw_car, section_start, field=f"block {len(blocks)}")
        cid_end = section_start + raw_cid.length
        if cid_end >= section_end:
            _fail("spaces_car_framing_invalid", "CAR block content is empty")
        block_bytes = raw_car[cid_end:section_end]
        prior = indexed.get(raw_cid.text)
        if prior is not None:
            reason = (
                "spaces_car_duplicate_block"
                if prior == block_bytes
                else "spaces_car_duplicate_conflict"
            )
            _fail(reason, "CAR contains a duplicate block identifier")
        if not hmac.compare_digest(
            hashlib.sha256(block_bytes).digest(), raw_cid.digest
        ):
            _fail(
                "spaces_car_block_cid_mismatch",
                "CAR block bytes do not match the declared CID",
            )
        indexed[raw_cid.text] = block_bytes
        blocks.append(CarBlock(len(blocks), raw_cid.text, block_bytes))
        cursor = section_end

    if len(blocks) < CAR_ROOT_COUNT:
        _fail("spaces_car_root_order_invalid", "CAR root blocks are missing")
    if blocks[0].cid != roots[0] or blocks[1].cid != roots[1]:
        _fail(
            "spaces_car_root_order_invalid",
            "Spaces alpha roots must identify the first commit and index blocks",
        )
    return ParsedSpaceCar(
        version=version,
        roots=(roots[0], roots[1]),
        blocks=tuple(blocks),
        raw_sha256=hashlib.sha256(raw_car).hexdigest(),
        source_vector_identifier=source_vector_identifier,
        protocol_assumption=protocol_assumption,
    )


def extract_space_repo_evidence(
    raw_car: bytes,
    *,
    source_vector_identifier: str,
    protocol_assumption: str = ALPHA_LABEL,
    transition: RepoTransition | None = None,
) -> SpaceCarExtraction:
    """Convert one parsed alpha CAR into the existing SA1 evidence type."""

    car = parse_space_car(
        raw_car,
        source_vector_identifier=source_vector_identifier,
        protocol_assumption=protocol_assumption,
    )
    index = parse_repo_index(car.blocks[1].block_bytes)
    record_blocks = car.blocks[2:]
    if len(index) != len(record_blocks):
        _fail(
            "spaces_car_handoff_invalid",
            "CAR record block count does not match the alpha index",
        )
    records: list[SpaceRecordBlock] = []
    for (path, expected_cid), block in zip(index.items(), record_blocks, strict=True):
        if block.cid != expected_cid:
            _fail(
                "spaces_car_handoff_invalid",
                "CAR record blocks do not follow canonical index order",
            )
        collection, rkey = path.split("/", 1)
        records.append(
            SpaceRecordBlock(
                collection=collection,
                rkey=rkey,
                cid=block.cid,
                record_bytes=block.block_bytes,
            )
        )
    evidence = SpaceRepoEvidence(
        source_vector_identifier=source_vector_identifier,
        proof_kind=PERMISSIONED_REPO_PROOF_KIND,
        protocol_assumption=protocol_assumption,
        commit_bytes=car.blocks[0].block_bytes,
        index_bytes=car.blocks[1].block_bytes,
        record_blocks=tuple(records),
        transition=transition,
    )
    return SpaceCarExtraction(car=car, evidence=evidence)


__all__ = [
    "CarBlock",
    "CarContainerClaim",
    "ParsedSpaceCar",
    "SpaceCarExtraction",
    "extract_space_repo_evidence",
    "parse_space_car",
]
