from __future__ import annotations

import pytest

from community_model import ValidationError, encode_dag_cbor
from communitywatch_spaces_alpha import (
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
    sa2_car,
    sa2_hostile_car,
    timestamp,
)


def _read_uvarint(raw: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        octet = raw[offset]
        offset += 1
        value |= (octet & 0x7F) << shift
        if not octet & 0x80:
            return value, offset
        shift += 7


def _sections(raw: bytes) -> tuple[tuple[int, int, int], ...]:
    header_length, cursor = _read_uvarint(raw, 0)
    cursor += header_length
    result: list[tuple[int, int, int]] = []
    while cursor < len(raw):
        framed_start = cursor
        section_length, content_start = _read_uvarint(raw, cursor)
        cursor = content_start + section_length
        result.append((framed_start, content_start, cursor))
    return tuple(result)


def _assert_refusal(reason: str, operation) -> None:
    with pytest.raises(ValidationError) as caught:
        operation()
    assert caught.value.reason_code == reason


def _parse(sa2_vectors: dict[str, object], name: str):
    return parse_space_car(
        sa2_hostile_car(sa2_vectors, name),
        source_vector_identifier=f"sa2:{name}",
    )


def _extract(sa2_vectors: dict[str, object], name: str):
    return extract_space_repo_evidence(
        sa2_hostile_car(sa2_vectors, name),
        source_vector_identifier=f"sa2:{name}",
    )


def test_car_h1_swapped_root_order_is_refused_before_qualification(
    sa2_vectors: dict[str, object],
) -> None:
    _assert_refusal(
        "spaces_car_root_order_invalid",
        lambda: _parse(sa2_vectors, "carH1WrongRootOrderB64"),
    )


@pytest.mark.parametrize(
    "name",
    ["carH2MissingRootB64", "carH3ExtraRootB64"],
)
def test_car_h2_h3_nonexact_root_count_is_refused(
    sa2_vectors: dict[str, object], name: str
) -> None:
    _assert_refusal("spaces_car_root_count_invalid", lambda: _parse(sa2_vectors, name))


def test_car_h4_truncated_block_is_refused(
    sa2_vectors: dict[str, object],
) -> None:
    _assert_refusal(
        "spaces_car_framing_invalid",
        lambda: _parse(sa2_vectors, "carH4TruncatedBlockB64"),
    )


def test_car_h5_block_cid_mismatch_is_refused(
    sa2_vectors: dict[str, object],
) -> None:
    _assert_refusal(
        "spaces_car_block_cid_mismatch",
        lambda: _parse(sa2_vectors, "carH5BlockCidMismatchB64"),
    )


def test_car_h6_duplicate_conflicting_cid_is_refused(
    sa2_vectors: dict[str, object],
) -> None:
    _assert_refusal(
        "spaces_car_duplicate_conflict",
        lambda: _parse(sa2_vectors, "carH6DuplicateConflictingCidB64"),
    )


def test_identical_duplicate_cid_is_also_refused_as_ambiguous(
    sa2_vectors: dict[str, object],
) -> None:
    raw = sa2_car(sa2_vectors)
    record_start, _, record_end = _sections(raw)[2]

    _assert_refusal(
        "spaces_car_duplicate_block",
        lambda: parse_space_car(
            raw + raw[record_start:record_end],
            source_vector_identifier="sa2:duplicate-identical",
        ),
    )


def test_missing_index_reference_is_preserved_for_handoff_refusal(
    sa2_vectors: dict[str, object],
) -> None:
    raw = sa2_car(sa2_vectors)
    record_start, _, _ = _sections(raw)[2]
    without_record = raw[:record_start]

    parsed = parse_space_car(
        without_record, source_vector_identifier="sa2:missing-record"
    )
    assert len(parsed.blocks) == 2
    _assert_refusal(
        "spaces_car_handoff_invalid",
        lambda: extract_space_repo_evidence(
            without_record, source_vector_identifier="sa2:missing-record"
        ),
    )


def test_unsupported_block_codec_fails_at_compatibility_boundary(
    sa2_vectors: dict[str, object],
) -> None:
    raw = bytearray(sa2_car(sa2_vectors))
    _, record_content_start, _ = _sections(raw)[2]
    # The fixture uses one-byte CID version and codec varints. Change only the
    # record block codec from dag-cbor (0x71) to raw (0x55).
    raw[record_content_start + 1] = 0x55

    _assert_refusal(
        "spaces_car_compatibility_failure",
        lambda: parse_space_car(
            bytes(raw), source_vector_identifier="sa2:unsupported-codec"
        ),
    )


def test_car_h7_valid_container_reaches_sa1_then_invalid_lthash_is_refused(
    sa1_vectors: dict[str, object], sa2_vectors: dict[str, object]
) -> None:
    name = "carH7ValidContainerInvalidSa1B64"
    parsed = _parse(sa2_vectors, name)
    extraction = _extract(sa2_vectors, name)

    assert parsed == extraction.car
    _assert_refusal(
        "spaces_lthash_invalid",
        lambda: qualify_repo_state(
            extraction.evidence,
            expected_space=sa1_space(sa1_vectors),
            expected_author_did=sa1_author(sa1_vectors),
            author_public_key=sa1_public_key(sa1_vectors),
            signature_algorithm=sa1_algorithm(sa1_vectors),
            source=sa1_source(sa1_vectors),
            verified_at=timestamp("2026-08-20T14:00:02Z"),
        ),
    )


def test_car_h8_public_one_root_car_is_not_spaces_evidence(
    sa2_vectors: dict[str, object],
) -> None:
    _assert_refusal(
        "spaces_car_root_count_invalid",
        lambda: _extract(sa2_vectors, "carH8PublicCarB64"),
    )


def test_unsupported_car_version_is_explicit_compatibility_failure() -> None:
    header = encode_dag_cbor({"roots": (), "version": 2})
    raw = bytes([len(header)]) + header

    _assert_refusal(
        "spaces_car_compatibility_failure",
        lambda: parse_space_car(raw, source_vector_identifier="sa2:future-car"),
    )


@pytest.mark.parametrize(
    "raw",
    [b"", b"\x01\xff", b"\x80"],
)
def test_malformed_car_framing_fails_closed(raw: bytes) -> None:
    _assert_refusal(
        "spaces_car_framing_invalid",
        lambda: parse_space_car(raw, source_vector_identifier="sa2:malformed"),
    )


def test_unsupported_protocol_label_cannot_relabel_valid_car(
    sa2_vectors: dict[str, object],
) -> None:
    raw = sa2_hostile_car(sa2_vectors, "carH1WrongRootOrderB64")

    _assert_refusal(
        "spaces_car_compatibility_failure",
        lambda: parse_space_car(
            raw,
            source_vector_identifier="sa2:relabeled",
            protocol_assumption="atproto-spaces-alpha-future",
        ),
    )
