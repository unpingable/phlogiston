"""Strict codec for the JSON-shaped DAG-CBOR evidence used by V0 records."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence

from .errors import ValidationError
from .identifiers import decode_cid, validate_cid


class _Decoder:
    _MAX_NESTING = 128

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.cursor = 0

    def _take(self, length: int) -> bytes:
        end = self.cursor + length
        if length < 0 or end > len(self.data):
            raise ValidationError("payload_evidence_invalid", "truncated DAG-CBOR")
        value = self.data[self.cursor : end]
        self.cursor = end
        return value

    def _argument(self, additional: int) -> int:
        if additional < 24:
            return additional
        widths = {24: 1, 25: 2, 26: 4, 27: 8}
        width = widths.get(additional)
        if width is None:
            raise ValidationError(
                "payload_evidence_invalid",
                "indefinite/reserved DAG-CBOR lengths are not allowed",
            )
        raw = self._take(width)
        value = int.from_bytes(raw, "big")
        minimum = {1: 24, 2: 256, 4: 65536, 8: 4294967296}[width]
        if value < minimum:
            raise ValidationError(
                "payload_evidence_invalid", "non-canonical DAG-CBOR integer/length"
            )
        return value

    def decode(self, depth: int = 0) -> object:
        if depth > self._MAX_NESTING:
            raise ValidationError(
                "payload_evidence_invalid", "DAG-CBOR nesting exceeds the V0 limit"
            )
        initial = self._take(1)[0]
        major = initial >> 5
        additional = initial & 0x1F
        if major in {0, 1}:
            value = self._argument(additional)
            if value > 0x7FFF_FFFF_FFFF_FFFF:
                raise ValidationError(
                    "payload_evidence_invalid",
                    "DAG-CBOR integer is outside signed 64-bit range",
                )
            return value if major == 0 else -1 - value
        if major in {2, 3}:
            raw = self._take(self._argument(additional))
            if major == 2:
                return raw
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValidationError(
                    "payload_evidence_invalid", "DAG-CBOR text is not UTF-8"
                ) from exc
        if major == 4:
            return tuple(
                self.decode(depth + 1) for _ in range(self._argument(additional))
            )
        if major == 5:
            result: dict[str, object] = {}
            previous_key_order: tuple[int, bytes] | None = None
            for _ in range(self._argument(additional)):
                key_start = self.cursor
                key = self.decode(depth + 1)
                encoded_key = self.data[key_start : self.cursor]
                key_order = (len(encoded_key), encoded_key)
                if not isinstance(key, str) or key in result:
                    raise ValidationError(
                        "payload_evidence_invalid",
                        "DAG-CBOR map keys must be unique strings",
                    )
                if previous_key_order is not None and key_order <= previous_key_order:
                    raise ValidationError(
                        "payload_evidence_invalid",
                        "DAG-CBOR map keys are not in canonical order",
                    )
                previous_key_order = key_order
                result[key] = self.decode(depth + 1)
            return result
        if major == 6:
            tag = self._argument(additional)
            linked = self.decode(depth + 1)
            if (
                tag != 42
                or not isinstance(linked, bytes)
                or not linked.startswith(b"\x00")
            ):
                raise ValidationError(
                    "payload_evidence_invalid", "unsupported DAG-CBOR tag"
                )
            raw_cid = linked[1:]
            cid = "b" + base64.b32encode(raw_cid).decode("ascii").lower().rstrip("=")
            validate_cid(cid)
            return {"$link": cid}
        if major == 7 and additional in {20, 21, 22}:
            return {20: False, 21: True, 22: None}[additional]
        raise ValidationError("payload_evidence_invalid", "unsupported DAG-CBOR scalar")


def decode_dag_cbor(data: bytes) -> object:
    """Decode one complete canonical DAG-CBOR value or fail structurally."""

    if not isinstance(data, bytes):
        raise TypeError("DAG-CBOR evidence must be bytes")
    decoder = _Decoder(data)
    value = decoder.decode()
    if decoder.cursor != len(data):
        raise ValidationError(
            "payload_evidence_invalid", "trailing bytes after DAG-CBOR value"
        )
    return value


def _encode_head(major: int, value: int) -> bytes:
    if value < 0:
        raise ValidationError("payload_evidence_invalid", "negative head argument")
    if value < 24:
        return bytes([(major << 5) | value])
    if value < 256:
        return bytes([(major << 5) | 24, value])
    if value < 65536:
        return bytes([(major << 5) | 25]) + value.to_bytes(2, "big")
    if value < 4294967296:
        return bytes([(major << 5) | 26]) + value.to_bytes(4, "big")
    if value <= 0xFFFF_FFFF_FFFF_FFFF:
        return bytes([(major << 5) | 27]) + value.to_bytes(8, "big")
    raise ValidationError(
        "payload_evidence_invalid", "DAG-CBOR integer is outside 64-bit range"
    )


def encode_dag_cbor(value: object) -> bytes:
    """Encode one value as canonical DAG-CBOR or fail structurally.

    The encoder is the exact inverse of :func:`decode_dag_cbor`: it accepts
    only the value shapes the decoder produces (including ``{"$link": cid}``
    mappings), emits canonical integer/length forms, and orders map keys by
    encoded length then bytes, so ``encode_dag_cbor(decode_dag_cbor(x)) == x``
    for every decodable input.
    """

    if value is None:
        return b"\xf6"
    if isinstance(value, bool):
        return b"\xf5" if value else b"\xf4"
    if isinstance(value, int):
        if not -(2**63) <= value <= 2**63 - 1:
            raise ValidationError(
                "payload_evidence_invalid",
                "DAG-CBOR integer is outside signed 64-bit range",
            )
        if value >= 0:
            return _encode_head(0, value)
        return _encode_head(1, -1 - value)
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        return _encode_head(3, len(encoded)) + encoded
    if isinstance(value, bytes | bytearray | memoryview):
        raw = bytes(value)
        return _encode_head(2, len(raw)) + raw
    if isinstance(value, Mapping):
        if set(value) == {"$link"}:
            link = value["$link"]
            if not isinstance(link, str):
                raise ValidationError(
                    "payload_evidence_invalid", "$link value must be a CID string"
                )
            cid_raw = decode_cid(validate_cid(link))
            linked = b"\x00" + cid_raw
            return _encode_head(6, 42) + _encode_head(2, len(linked)) + linked
        encoded_items: list[tuple[bytes, bytes, bytes]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValidationError(
                    "payload_evidence_invalid", "DAG-CBOR map keys must be strings"
                )
            encoded_key = key.encode("utf-8")
            encoded_items.append(
                (
                    encoded_key,
                    _encode_head(3, len(encoded_key)) + encoded_key,
                    encode_dag_cbor(item),
                )
            )
        encoded_items.sort(key=lambda item: (len(item[0]), item[0]))
        body = b"".join(head + item for _, head, item in encoded_items)
        return _encode_head(5, len(encoded_items)) + body
    if isinstance(value, Sequence) and not isinstance(value, str):
        items = b"".join(encode_dag_cbor(item) for item in value)
        return _encode_head(4, len(value)) + items
    raise ValidationError(
        "payload_evidence_invalid",
        f"{type(value).__name__} is not encodable as DAG-CBOR",
    )


__all__ = ["decode_dag_cbor", "encode_dag_cbor"]
