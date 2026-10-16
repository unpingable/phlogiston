"""Round-trip and canonical-order tests for the DAG-CBOR encoder."""

from __future__ import annotations

import pytest

from community_model import (
    ValidationError,
    cid_for_dag_cbor,
    decode_dag_cbor,
    encode_dag_cbor,
)


def _roundtrip(value: object) -> None:
    encoded = encode_dag_cbor(value)
    assert encode_dag_cbor(decode_dag_cbor(encoded)) == encoded


def test_scalars_roundtrip() -> None:
    for value in (
        None,
        True,
        False,
        0,
        1,
        23,
        24,
        255,
        256,
        65535,
        65536,
        2**32,
        2**63 - 1,
        -1,
        -24,
        -25,
        -(2**63),
    ):
        _roundtrip(value)
    assert encode_dag_cbor(None) == b"\xf6"
    assert encode_dag_cbor(True) == b"\xf5"
    assert encode_dag_cbor(False) == b"\xf4"
    assert encode_dag_cbor(23) == b"\x17"
    assert encode_dag_cbor(24) == b"\x18\x18"
    assert encode_dag_cbor(-1) == b"\x20"


def test_text_bytes_and_arrays_roundtrip() -> None:
    _roundtrip("")
    _roundtrip("héllo")
    _roundtrip(b"")
    _roundtrip(b"\x00\xff" * 100)
    _roundtrip(())
    _roundtrip((1, "two", b"three", None))
    _roundtrip([1, [2, [3]]])
    assert encode_dag_cbor("a") == b"aa"


def test_maps_use_canonical_key_order() -> None:
    # Canonical DAG-CBOR orders map keys by encoded length, then bytes.
    assert encode_dag_cbor({"bb": 1, "a": 2, "ccc": 3}) == (
        b"\xa3aa\x02bbb\x01cccc\x03"
    )
    assert encode_dag_cbor({"b": 1, "a": 2}) == b"\xa2aa\x02ab\x01"
    _roundtrip({"nested": {"x": [1, {"y": None}]}, "list": [{"k": "v"}]})


def test_links_roundtrip_through_tag_42() -> None:
    record = {"$type": "x.y.z", "ref": None}
    cid = cid_for_dag_cbor(encode_dag_cbor(record))
    value = {"cid": {"$link": cid}}
    encoded = encode_dag_cbor(value)
    decoded = decode_dag_cbor(encoded)
    assert decoded == value
    _roundtrip(value)


def test_encoder_rejects_unsupported_values() -> None:
    with pytest.raises(ValidationError):
        encode_dag_cbor(1.5)
    with pytest.raises(ValidationError):
        encode_dag_cbor({1: "x"})
    with pytest.raises(ValidationError):
        encode_dag_cbor(2**64)
    with pytest.raises(ValidationError):
        encode_dag_cbor({"$link": "not-a-cid"})
    with pytest.raises(ValidationError):
        encode_dag_cbor(object())
