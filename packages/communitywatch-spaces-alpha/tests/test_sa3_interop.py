from __future__ import annotations

import hashlib
from pathlib import Path

from communitywatch_spaces_alpha import (
    CAR_DAG_CBOR_CODEC,
    CAR_SHA256_MULTIHASH,
    SA2_CAR_ADAPTER_VERSION,
    SA3_INTEROP_METHOD,
    SA3_INTEROP_VERSION,
    SA3_REFERENCE_COMMIT,
    SA3_REFERENCE_IMPLEMENTATION,
    SA3_REFERENCE_PACKAGE_VERSION,
    SA3_REFERENCE_VECTOR_FORMAT,
    ReferenceParityClaim,
    compare_reference_car,
    qualify_repo_state,
)
from spaces_support import (
    sa1_algorithm,
    sa1_author,
    sa1_evidence,
    sa1_public_key,
    sa1_source,
    sa1_space,
    sa2_car,
    sa3_car,
    sa3_expectation,
    timestamp,
)

REFERENCE_DRIVER = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "spaces-alpha"
    / "reference"
    / "sa3-generate.mjs"
)


def _qualify(evidence, sa1_vectors: dict[str, object]):
    return qualify_repo_state(
        evidence,
        expected_space=sa1_space(sa1_vectors),
        expected_author_did=sa1_author(sa1_vectors),
        author_public_key=sa1_public_key(sa1_vectors),
        signature_algorithm=sa1_algorithm(sa1_vectors),
        source=sa1_source(sa1_vectors),
        verified_at=timestamp("2026-08-20T14:00:02Z"),
    )


def _flatten_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {str(key).lower() for key in value} | set().union(
            *(_flatten_keys(item) for item in value.values()), set()
        )
    if isinstance(value, list | tuple):
        return set().union(*(_flatten_keys(item) for item in value), set())
    return set()


def test_reference_fixture_pins_generator_driver_and_local_boundary(
    sa3_vectors: dict[str, object],
) -> None:
    generator = sa3_vectors["generator"]
    local = sa3_vectors["localExpectation"]
    assert isinstance(generator, dict) and isinstance(local, dict)
    assert sa3_vectors["format"] == SA3_REFERENCE_VECTOR_FORMAT
    assert generator["implementation"] == SA3_REFERENCE_IMPLEMENTATION
    assert generator["packageVersion"] == SA3_REFERENCE_PACKAGE_VERSION
    assert generator["commit"] == SA3_REFERENCE_COMMIT
    assert generator["pnpmVersion"] == "11.11.0"
    assert local["adapterVersion"] == SA2_CAR_ADAPTER_VERSION
    assert local["interoperabilityVersion"] == SA3_INTEROP_VERSION
    assert (
        hashlib.sha256(REFERENCE_DRIVER.read_bytes()).hexdigest()
        == (generator["driverSha256"])
    )
    assert not (
        _flatten_keys(sa3_vectors)
        & {
            "private_key",
            "oauth_token",
            "space_credential",
            "delegation_token",
            "dpop_private_key",
            "authorization_header",
            "cookie",
        }
    )


def test_i1_i2_reference_roots_blocks_bytes_and_codecs_match_local_parser(
    sa3_vectors: dict[str, object],
) -> None:
    expectation = sa3_expectation(sa3_vectors)
    result = compare_reference_car(sa3_car(sa3_vectors), expectation)

    assert result.extraction.car.roots == expectation.roots
    assert len(result.extraction.car.blocks) == len(expectation.blocks) == 3
    assert tuple(block.cid for block in result.extraction.car.blocks) == tuple(
        block.cid for block in expectation.blocks
    )
    assert tuple(block.block_bytes for block in result.extraction.car.blocks) == tuple(
        block.block_bytes for block in expectation.blocks
    )
    assert all(block.codec == CAR_DAG_CBOR_CODEC for block in expectation.blocks)
    assert all(
        block.multihash_code == CAR_SHA256_MULTIHASH for block in expectation.blocks
    )
    assert result.parity_claims == frozenset(ReferenceParityClaim)
    provenance = result.to_provenance()
    assert provenance["method"] == SA3_INTEROP_METHOD
    assert provenance["semanticObservationClaims"] == ()
    assert provenance["governanceAuthority"] is False


def test_i3_reference_car_extracts_exact_existing_sa1_evidence(
    sa1_vectors: dict[str, object], sa3_vectors: dict[str, object]
) -> None:
    result = compare_reference_car(sa3_car(sa3_vectors), sa3_expectation(sa3_vectors))
    expected = sa1_evidence(sa1_vectors, "initial")

    assert result.extraction.evidence == expected
    assert result.extraction.evidence.commit_bytes == expected.commit_bytes
    assert result.extraction.evidence.index_bytes == expected.index_bytes
    assert result.extraction.evidence.record_blocks == expected.record_blocks


def test_i4_reference_derived_qualification_matches_direct_sa1_result(
    sa1_vectors: dict[str, object], sa3_vectors: dict[str, object]
) -> None:
    result = compare_reference_car(sa3_car(sa3_vectors), sa3_expectation(sa3_vectors))
    reference_derived = _qualify(result.extraction.evidence, sa1_vectors)
    direct = _qualify(sa1_evidence(sa1_vectors, "initial"), sa1_vectors)

    assert reference_derived == direct
    assert tuple(receipt.verified_claims for receipt in reference_derived.receipts) == (
        tuple(receipt.verified_claims for receipt in direct.receipts)
    )
    result.assert_qualification_parity(reference_derived)


def test_i5_two_reference_runs_are_byte_identical_and_match_sa2_car1(
    sa2_vectors: dict[str, object], sa3_vectors: dict[str, object]
) -> None:
    artifact = sa3_vectors["artifact"]
    regeneration = sa3_vectors["regeneration"]
    assert isinstance(artifact, dict) and isinstance(regeneration, dict)
    assert regeneration == {
        "runs": 2,
        "stability": "byte-identical",
        "firstSha256": artifact["rawSha256"],
        "secondSha256": artifact["rawSha256"],
    }
    assert len(sa3_car(sa3_vectors)) == artifact["byteLength"] == 580
    assert sa3_car(sa3_vectors) == sa2_car(sa2_vectors)
