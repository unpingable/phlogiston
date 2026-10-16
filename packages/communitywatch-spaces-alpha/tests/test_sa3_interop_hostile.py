from __future__ import annotations

from dataclasses import replace

import pytest

from community_model import ValidationError
from communitywatch_spaces_alpha import (
    compare_reference_car,
    extract_space_repo_evidence,
    parse_space_car,
    qualify_repo_state,
)
from spaces_support import (
    sa1_algorithm,
    sa1_author,
    sa1_public_key,
    sa1_source,
    sa1_space,
    sa2_hostile_car,
    sa3_car,
    sa3_expectation,
    timestamp,
)


def _assert_refusal(reason: str, operation) -> None:
    with pytest.raises(ValidationError) as caught:
        operation()
    assert caught.value.reason_code == reason


def test_r1_reference_car_block_byte_mutation_is_refused_by_parity_and_sa2(
    sa3_vectors: dict[str, object],
) -> None:
    raw = bytearray(sa3_car(sa3_vectors))
    raw[-1] ^= 1
    mutated = bytes(raw)

    _assert_refusal(
        "spaces_reference_parity_failure",
        lambda: compare_reference_car(mutated, sa3_expectation(sa3_vectors)),
    )
    _assert_refusal(
        "spaces_car_block_cid_mismatch",
        lambda: extract_space_repo_evidence(
            mutated, source_vector_identifier="sa3:r1-mutated"
        ),
    )


def test_r2_valid_local_parse_with_reference_byte_disagreement_fails_parity(
    sa3_vectors: dict[str, object],
) -> None:
    expectation = sa3_expectation(sa3_vectors)
    altered_record = replace(
        expectation.blocks[2], block_bytes=expectation.blocks[0].block_bytes
    )
    disagreeing = replace(
        expectation,
        blocks=(*expectation.blocks[:2], altered_record),
    )

    parsed = parse_space_car(
        sa3_car(sa3_vectors), source_vector_identifier="sa3:r2-valid-car"
    )
    assert len(parsed.blocks) == 3
    _assert_refusal(
        "spaces_reference_parity_failure",
        lambda: compare_reference_car(sa3_car(sa3_vectors), disagreeing),
    )


def test_r3_equivalent_noncanonical_header_length_encoding_is_refused(
    sa3_vectors: dict[str, object],
) -> None:
    raw = sa3_car(sa3_vectors)
    assert raw[0] < 0x80
    noncanonical = bytes([raw[0] | 0x80, 0]) + raw[1:]

    _assert_refusal(
        "spaces_car_framing_invalid",
        lambda: parse_space_car(
            noncanonical, source_vector_identifier="sa3:r3-noncanonical"
        ),
    )


def test_r4_public_reference_artifact_has_no_spaces_fallback(
    sa2_vectors: dict[str, object], sa3_vectors: dict[str, object]
) -> None:
    public_car = sa2_hostile_car(sa2_vectors, "carH8PublicCarB64")

    _assert_refusal(
        "spaces_reference_parity_failure",
        lambda: compare_reference_car(public_car, sa3_expectation(sa3_vectors)),
    )
    _assert_refusal(
        "spaces_car_root_count_invalid",
        lambda: extract_space_repo_evidence(
            public_car, source_vector_identifier="sa3:r4-public"
        ),
    )


@pytest.mark.parametrize(
    ("field_name", "drifted"),
    [
        ("generator_commit", "f2c33aa4a72c95762c2708cf02acbfab7ddd2b5a"),
        ("generator_package_version", "0.0.2"),
        ("local_adapter_version", "sa2-car-v2"),
        ("local_interop_version", "sa3-v2"),
        ("raw_car_sha256", "0" * 64),
        ("source_vector_identifier", "caller:rewritten-label"),
    ],
)
def test_r5_reference_or_local_version_drift_fails_compatibility(
    sa3_vectors: dict[str, object], field_name: str, drifted: str
) -> None:
    expectation = replace(sa3_expectation(sa3_vectors), **{field_name: drifted})

    _assert_refusal(
        "spaces_reference_compatibility_failure",
        lambda: compare_reference_car(sa3_car(sa3_vectors), expectation),
    )


def test_receipt_metadata_cannot_relabel_a_different_sa1_result(
    sa1_vectors: dict[str, object], sa3_vectors: dict[str, object]
) -> None:
    expectation = replace(
        sa3_expectation(sa3_vectors),
        qualification_receipt_ids=("sha256:" + "0" * 64,),
    )
    _assert_refusal(
        "spaces_reference_compatibility_failure",
        lambda: compare_reference_car(sa3_car(sa3_vectors), expectation),
    )

    result = compare_reference_car(sa3_car(sa3_vectors), sa3_expectation(sa3_vectors))
    qualified = qualify_repo_state(
        result.extraction.evidence,
        expected_space=sa1_space(sa1_vectors),
        expected_author_did=sa1_author(sa1_vectors),
        author_public_key=sa1_public_key(sa1_vectors),
        signature_algorithm=sa1_algorithm(sa1_vectors),
        source=sa1_source(sa1_vectors),
        verified_at=timestamp("2026-08-20T14:00:03Z"),
    )
    _assert_refusal(
        "spaces_reference_qualification_parity_failure",
        lambda: result.assert_qualification_parity(qualified),
    )
