"""Pinned-reference interoperability checks layered above unchanged SA2/SA1.

The reference implementation is a serialization oracle only.  Matching its
artifact establishes deterministic compatibility, never identity, access,
observation authority, or governance authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from community_model import ValidationError
from community_model.identifiers import validate_cid

from .car import SpaceCarExtraction, extract_space_repo_evidence
from .compat import (
    CAR_DAG_CBOR_CODEC,
    CAR_ROOT_COUNT,
    CAR_SHA256_MULTIHASH,
    SA2_CAR_ADAPTER_VERSION,
    SA3_INTEROP_METHOD,
    SA3_INTEROP_VERSION,
    SA3_QUALIFICATION_RECEIPT_IDS,
    SA3_REFERENCE_ARTIFACT_SHA256,
    SA3_REFERENCE_COMMIT,
    SA3_REFERENCE_IMPLEMENTATION,
    SA3_REFERENCE_PACKAGE_VERSION,
    SA3_REFERENCE_VECTOR_FORMAT,
    SA3_SOURCE_VECTOR_IDENTIFIER,
)
from .qualification import QualifiedRepoState


def _fail(reason: str, message: str) -> None:
    raise ValidationError(reason, message)


def _nonempty(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail("spaces_reference_metadata_invalid", f"{field_name} is invalid")
    return value


def _sha256(value: object, *, field_name: str) -> str:
    text = _nonempty(value, field_name=field_name)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        _fail("spaces_reference_metadata_invalid", f"{field_name} is not SHA-256")
    return text


class ReferenceParityClaim(StrEnum):
    ARTIFACT_DIGEST = "reference_artifact_sha256"
    ORDERED_ROOTS = "reference_ordered_roots"
    BLOCK_COUNT = "reference_block_count"
    ORDERED_BLOCK_CIDS = "reference_ordered_block_cids"
    BLOCK_BYTES = "reference_block_bytes"
    CODEC_INTERPRETATION = "reference_codec_interpretation"
    SA1_EVIDENCE_HANDOFF = "reference_to_sa1_evidence_handoff"


_PARITY_CLAIMS = frozenset(ReferenceParityClaim)


@dataclass(frozen=True, slots=True)
class ReferenceBlockExpectation:
    ordinal: int
    cid: str
    codec: int
    multihash_code: int
    block_bytes: bytes

    def __post_init__(self) -> None:
        if (
            isinstance(self.ordinal, bool)
            or not isinstance(self.ordinal, int)
            or self.ordinal < 0
        ):
            _fail("spaces_reference_metadata_invalid", "block ordinal is invalid")
        validate_cid(self.cid, require_dag_cbor=True)
        if isinstance(self.codec, bool) or not isinstance(self.codec, int):
            _fail("spaces_reference_metadata_invalid", "block codec is invalid")
        if isinstance(self.multihash_code, bool) or not isinstance(
            self.multihash_code, int
        ):
            _fail(
                "spaces_reference_metadata_invalid",
                "block multihash code is invalid",
            )
        if not isinstance(self.block_bytes, bytes):
            _fail("spaces_reference_metadata_invalid", "block bytes are invalid")


@dataclass(frozen=True, slots=True)
class ReferenceCarExpectation:
    format: str
    generator_implementation: str
    generator_package_version: str
    generator_commit: str
    local_adapter_version: str
    local_interop_version: str
    raw_car_sha256: str
    roots: tuple[str, str]
    blocks: tuple[ReferenceBlockExpectation, ...]
    source_vector_identifier: str
    qualification_receipt_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "format",
            "generator_implementation",
            "generator_package_version",
            "generator_commit",
            "local_adapter_version",
            "local_interop_version",
            "source_vector_identifier",
        ):
            _nonempty(getattr(self, field_name), field_name=field_name)
        _sha256(self.raw_car_sha256, field_name="raw_car_sha256")
        if not isinstance(self.roots, tuple) or len(self.roots) != CAR_ROOT_COUNT:
            _fail("spaces_reference_metadata_invalid", "root expectation is invalid")
        for root in self.roots:
            validate_cid(root, require_dag_cbor=True)
        if not isinstance(self.blocks, tuple) or any(
            not isinstance(block, ReferenceBlockExpectation) for block in self.blocks
        ):
            _fail("spaces_reference_metadata_invalid", "block expectations are invalid")
        if tuple(block.ordinal for block in self.blocks) != tuple(
            range(len(self.blocks))
        ):
            _fail(
                "spaces_reference_metadata_invalid",
                "block expectation order is not contiguous",
            )
        if not isinstance(self.qualification_receipt_ids, tuple) or not (
            self.qualification_receipt_ids
        ):
            _fail(
                "spaces_reference_metadata_invalid",
                "qualification receipt expectations are required",
            )
        for receipt_id in self.qualification_receipt_ids:
            if not isinstance(receipt_id, str) or not receipt_id.startswith("sha256:"):
                _fail(
                    "spaces_reference_metadata_invalid",
                    "qualification receipt expectation is invalid",
                )
            _sha256(receipt_id[7:], field_name="qualification receipt digest")


@dataclass(frozen=True, slots=True)
class ReferenceInteropResult:
    extraction: SpaceCarExtraction
    expectation: ReferenceCarExpectation
    parity_claims: frozenset[ReferenceParityClaim] = field(
        default=_PARITY_CLAIMS, init=False
    )
    method: str = field(default=SA3_INTEROP_METHOD, init=False)
    version: str = field(default=SA3_INTEROP_VERSION, init=False)
    governance_authority: bool = field(default=False, init=False)

    def assert_qualification_parity(self, qualified: QualifiedRepoState) -> None:
        """Compare an unchanged SA1 result with the pinned receipt identities."""

        if not isinstance(qualified, QualifiedRepoState):
            _fail(
                "spaces_reference_qualification_parity_failure",
                "SA1 qualified state is required",
            )
        actual = tuple(receipt.receipt_id for receipt in qualified.receipts)
        if actual != SA3_QUALIFICATION_RECEIPT_IDS:
            _fail(
                "spaces_reference_qualification_parity_failure",
                "SA1 qualification receipts differ from the golden expectation",
            )

    def to_provenance(self) -> MappingProxyType[str, object]:
        return MappingProxyType(
            {
                "claimScope": "spaces_reference_interoperability_only",
                "method": self.method,
                "version": self.version,
                "generatorCommit": self.expectation.generator_commit,
                "referenceParityClaims": tuple(
                    sorted(claim.value for claim in self.parity_claims)
                ),
                "semanticObservationClaims": (),
                "governanceAuthority": False,
            }
        )


def compare_reference_car(
    raw_car: bytes, expectation: ReferenceCarExpectation
) -> ReferenceInteropResult:
    """Compare a pinned reference artifact, then hand it to unchanged SA2."""

    if not isinstance(expectation, ReferenceCarExpectation):
        _fail(
            "spaces_reference_metadata_invalid",
            "reference CAR expectation is required",
        )
    compatibility = {
        "format": (expectation.format, SA3_REFERENCE_VECTOR_FORMAT),
        "generator implementation": (
            expectation.generator_implementation,
            SA3_REFERENCE_IMPLEMENTATION,
        ),
        "generator package version": (
            expectation.generator_package_version,
            SA3_REFERENCE_PACKAGE_VERSION,
        ),
        "generator commit": (
            expectation.generator_commit,
            SA3_REFERENCE_COMMIT,
        ),
        "local adapter version": (
            expectation.local_adapter_version,
            SA2_CAR_ADAPTER_VERSION,
        ),
        "local interoperability version": (
            expectation.local_interop_version,
            SA3_INTEROP_VERSION,
        ),
        "reference artifact digest": (
            expectation.raw_car_sha256,
            SA3_REFERENCE_ARTIFACT_SHA256,
        ),
        "qualification receipt identities": (
            expectation.qualification_receipt_ids,
            SA3_QUALIFICATION_RECEIPT_IDS,
        ),
        "source vector identifier": (
            expectation.source_vector_identifier,
            SA3_SOURCE_VECTOR_IDENTIFIER,
        ),
    }
    for field_name, (actual, expected) in compatibility.items():
        if actual != expected:
            _fail(
                "spaces_reference_compatibility_failure",
                f"{field_name} differs from the pinned SA3 boundary",
            )
    if any(
        block.codec != CAR_DAG_CBOR_CODEC
        or block.multihash_code != CAR_SHA256_MULTIHASH
        for block in expectation.blocks
    ):
        _fail(
            "spaces_reference_compatibility_failure",
            "reference block metadata uses unsupported CID components",
        )
    if not isinstance(raw_car, bytes):
        _fail("spaces_reference_parity_failure", "reference CAR must be bytes")
    if hashlib.sha256(raw_car).hexdigest() != expectation.raw_car_sha256:
        _fail(
            "spaces_reference_parity_failure",
            "reference CAR digest differs from its golden metadata",
        )

    extraction = extract_space_repo_evidence(
        raw_car,
        source_vector_identifier=expectation.source_vector_identifier,
    )
    if extraction.car.roots != expectation.roots:
        _fail(
            "spaces_reference_parity_failure",
            "local ordered roots differ from the reference interpretation",
        )
    if len(extraction.car.blocks) != len(expectation.blocks):
        _fail(
            "spaces_reference_parity_failure",
            "local block count differs from the reference interpretation",
        )
    for local, expected in zip(extraction.car.blocks, expectation.blocks, strict=True):
        if local.ordinal != expected.ordinal or local.cid != expected.cid:
            _fail(
                "spaces_reference_parity_failure",
                "local block order/CID differs from the reference interpretation",
            )
        if local.block_bytes != expected.block_bytes:
            _fail(
                "spaces_reference_parity_failure",
                "local block bytes differ from the reference interpretation",
            )
    return ReferenceInteropResult(extraction=extraction, expectation=expectation)


__all__ = [
    "ReferenceBlockExpectation",
    "ReferenceCarExpectation",
    "ReferenceInteropResult",
    "ReferenceParityClaim",
    "compare_reference_car",
]
