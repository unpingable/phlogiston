"""Verification-only primitives for the pinned Spaces alpha.

This module has no key generation or signing operation.  Its constrained
BLAKE3 implementation handles one alpha set-hash element (which is shorter
than one 1024-byte BLAKE3 chunk after identifier validation) and emits the
2048-byte XOF output required by LtHash.
"""

from __future__ import annotations

import hashlib
import hmac

from .compat import LTHASH_STATE_BYTES

_BLAKE3_IV = (
    0x6A09E667,
    0xBB67AE85,
    0x3C6EF372,
    0xA54FF53A,
    0x510E527F,
    0x9B05688C,
    0x1F83D9AB,
    0x5BE0CD19,
)
_MESSAGE_PERMUTATION = (2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8)
_CHUNK_START = 1
_CHUNK_END = 2
_ROOT = 8
_MASK32 = 0xFFFF_FFFF

_SECP_FIELD = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_SECP_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_SECP_GENERATOR = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)
_P256_FIELD = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_P256_A = _P256_FIELD - 3
_P256_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_P256_GENERATOR = (
    0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
    0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5,
)
_Point = tuple[int, int] | None


def _rotate_right(value: int, count: int) -> int:
    return ((value >> count) | (value << (32 - count))) & _MASK32


def _mix(state: list[int], a: int, b: int, c: int, d: int, x: int, y: int) -> None:
    state[a] = (state[a] + state[b] + x) & _MASK32
    state[d] = _rotate_right(state[d] ^ state[a], 16)
    state[c] = (state[c] + state[d]) & _MASK32
    state[b] = _rotate_right(state[b] ^ state[c], 12)
    state[a] = (state[a] + state[b] + y) & _MASK32
    state[d] = _rotate_right(state[d] ^ state[a], 8)
    state[c] = (state[c] + state[d]) & _MASK32
    state[b] = _rotate_right(state[b] ^ state[c], 7)


def _compress(
    chaining_value: tuple[int, ...],
    block_words: tuple[int, ...],
    counter: int,
    block_length: int,
    flags: int,
) -> tuple[int, ...]:
    state = [
        *chaining_value,
        *_BLAKE3_IV[:4],
        counter & _MASK32,
        counter >> 32,
        block_length,
        flags,
    ]
    message = list(block_words)
    for _ in range(7):
        _mix(state, 0, 4, 8, 12, message[0], message[1])
        _mix(state, 1, 5, 9, 13, message[2], message[3])
        _mix(state, 2, 6, 10, 14, message[4], message[5])
        _mix(state, 3, 7, 11, 15, message[6], message[7])
        _mix(state, 0, 5, 10, 15, message[8], message[9])
        _mix(state, 1, 6, 11, 12, message[10], message[11])
        _mix(state, 2, 7, 8, 13, message[12], message[13])
        _mix(state, 3, 4, 9, 14, message[14], message[15])
        message = [message[index] for index in _MESSAGE_PERMUTATION]
    return tuple(
        [state[index] ^ state[index + 8] for index in range(8)]
        + [state[index + 8] ^ chaining_value[index] for index in range(8)]
    )


def _block_words(block: bytes) -> tuple[int, ...]:
    padded = block.ljust(64, b"\x00")
    return tuple(
        int.from_bytes(padded[offset : offset + 4], "little")
        for offset in range(0, 64, 4)
    )


def blake3_xof_one_chunk(data: bytes, length: int) -> bytes:
    """Return unkeyed BLAKE3 XOF bytes for one validated alpha element."""

    if not isinstance(data, bytes) or len(data) > 1024:
        raise ValueError("alpha LtHash element must fit one BLAKE3 chunk")
    if not isinstance(length, int) or length < 0:
        raise ValueError("XOF length must be nonnegative")
    blocks = [data[offset : offset + 64] for offset in range(0, len(data), 64)]
    if not blocks:
        blocks = [b""]
    chaining_value = _BLAKE3_IV
    for position, block in enumerate(blocks[:-1]):
        flags = _CHUNK_START if position == 0 else 0
        chaining_value = _compress(
            chaining_value, _block_words(block), 0, len(block), flags
        )[:8]
    final = blocks[-1]
    final_flags = _CHUNK_END
    if len(blocks) == 1:
        final_flags |= _CHUNK_START
    words = _block_words(final)
    output = bytearray()
    output_counter = 0
    while len(output) < length:
        compressed = _compress(
            chaining_value,
            words,
            output_counter,
            len(final),
            final_flags | _ROOT,
        )
        output.extend(b"".join(word.to_bytes(4, "little") for word in compressed))
        output_counter += 1
    return bytes(output[:length])


def lthash_add(state: bytes, element: str, *, subtract: bool = False) -> bytes:
    """Apply one alpha LtHash element to an immutable 2048-byte state."""

    if not isinstance(state, bytes) or len(state) != LTHASH_STATE_BYTES:
        raise ValueError("LtHash state must be exactly 2048 bytes")
    if not isinstance(element, str):
        raise ValueError("LtHash element must be text")
    expanded = blake3_xof_one_chunk(element.encode("utf-8"), LTHASH_STATE_BYTES)
    result = bytearray(LTHASH_STATE_BYTES)
    for offset in range(0, LTHASH_STATE_BYTES, 2):
        current = int.from_bytes(state[offset : offset + 2], "little")
        lane = int.from_bytes(expanded[offset : offset + 2], "little")
        value = current - lane if subtract else current + lane
        result[offset : offset + 2] = (value & 0xFFFF).to_bytes(2, "little")
    return bytes(result)


def lthash_digest(state: bytes) -> bytes:
    if not isinstance(state, bytes) or len(state) != LTHASH_STATE_BYTES:
        raise ValueError("LtHash state must be exactly 2048 bytes")
    return hashlib.sha256(state).digest()


def commit_mac(ikm: bytes, context: bytes, state_hash: bytes) -> bytes:
    """Compute the alpha's no-extract HKDF-expand/HMAC binding."""

    if len(ikm) != 32 or len(state_hash) != 32:
        raise ValueError("commit ikm and hash must each be 32 bytes")
    expanded_key = hmac.new(ikm, context + b"\x01", hashlib.sha256).digest()
    return hmac.new(expanded_key, state_hash, hashlib.sha256).digest()


def _point_add(left: _Point, right: _Point) -> _Point:
    if left is None:
        return right
    if right is None:
        return left
    x1, y1 = left
    x2, y2 = right
    if x1 == x2 and (y1 != y2 or y1 == 0):
        return None
    if left == right:
        slope = (3 * x1 * x1) * pow(2 * y1, -1, _SECP_FIELD) % _SECP_FIELD
    else:
        slope = (y2 - y1) * pow(x2 - x1, -1, _SECP_FIELD) % _SECP_FIELD
    x3 = (slope * slope - x1 - x2) % _SECP_FIELD
    return x3, (slope * (x1 - x3) - y1) % _SECP_FIELD


def _point_multiply(scalar: int, point: _Point) -> _Point:
    result: _Point = None
    addend = point
    while scalar:
        if scalar & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        scalar >>= 1
    return result


def _decode_secp256k1_key(public_key: bytes) -> tuple[int, int]:
    if len(public_key) != 33 or public_key[0] not in (2, 3):
        raise ValueError("expected compressed secp256k1 public key")
    x = int.from_bytes(public_key[1:], "big")
    if x >= _SECP_FIELD:
        raise ValueError("public key x-coordinate is outside the field")
    square = (pow(x, 3, _SECP_FIELD) + 7) % _SECP_FIELD
    y = pow(square, (_SECP_FIELD + 1) // 4, _SECP_FIELD)
    if y * y % _SECP_FIELD != square:
        raise ValueError("public key is not on secp256k1")
    if y & 1 != public_key[0] & 1:
        y = _SECP_FIELD - y
    return x, y


def verify_es256k(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Verify an ATProto compact low-S ES256K signature over message bytes."""

    try:
        point = _decode_secp256k1_key(public_key)
    except (TypeError, ValueError):
        return False
    if len(signature) != 64:
        return False
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    if not (1 <= r < _SECP_ORDER and 1 <= s <= _SECP_ORDER // 2):
        return False
    digest = hashlib.sha256(message).digest()
    z = int.from_bytes(digest, "big")
    inverse = pow(s, -1, _SECP_ORDER)
    candidate = _point_add(
        _point_multiply(z * inverse % _SECP_ORDER, _SECP_GENERATOR),
        _point_multiply(r * inverse % _SECP_ORDER, point),
    )
    return candidate is not None and candidate[0] % _SECP_ORDER == r


def _p256_point_add(left: _Point, right: _Point) -> _Point:
    if left is None:
        return right
    if right is None:
        return left
    x1, y1 = left
    x2, y2 = right
    if x1 == x2 and (y1 != y2 or y1 == 0):
        return None
    if left == right:
        slope = (3 * x1 * x1 + _P256_A) * pow(2 * y1, -1, _P256_FIELD)
    else:
        slope = (y2 - y1) * pow(x2 - x1, -1, _P256_FIELD)
    slope %= _P256_FIELD
    x3 = (slope * slope - x1 - x2) % _P256_FIELD
    return x3, (slope * (x1 - x3) - y1) % _P256_FIELD


def _p256_point_multiply(scalar: int, point: _Point) -> _Point:
    result: _Point = None
    addend = point
    while scalar:
        if scalar & 1:
            result = _p256_point_add(result, addend)
        addend = _p256_point_add(addend, addend)
        scalar >>= 1
    return result


def _decode_p256_key(public_key: bytes) -> tuple[int, int]:
    if len(public_key) != 33 or public_key[0] not in (2, 3):
        raise ValueError("expected compressed P-256 public key")
    x = int.from_bytes(public_key[1:], "big")
    if x >= _P256_FIELD:
        raise ValueError("public key x-coordinate is outside the field")
    square = (pow(x, 3, _P256_FIELD) + _P256_A * x + _P256_B) % _P256_FIELD
    # P-256's prime is 3 mod 4.
    y = pow(square, (_P256_FIELD + 1) // 4, _P256_FIELD)
    if y * y % _P256_FIELD != square:
        raise ValueError("public key is not on P-256")
    if y & 1 != public_key[0] & 1:
        y = _P256_FIELD - y
    return x, y


def verify_es256(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Verify an ATProto compact low-S ES256 signature over message bytes."""

    try:
        point = _decode_p256_key(public_key)
    except (TypeError, ValueError):
        return False
    if len(signature) != 64:
        return False
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    if not (1 <= r < _P256_ORDER and 1 <= s <= _P256_ORDER // 2):
        return False
    z = int.from_bytes(hashlib.sha256(message).digest(), "big")
    inverse = pow(s, -1, _P256_ORDER)
    candidate = _p256_point_add(
        _p256_point_multiply(z * inverse % _P256_ORDER, _P256_GENERATOR),
        _p256_point_multiply(r * inverse % _P256_ORDER, point),
    )
    return candidate is not None and candidate[0] % _P256_ORDER == r


__all__ = [
    "blake3_xof_one_chunk",
    "commit_mac",
    "lthash_add",
    "lthash_digest",
    "verify_es256",
    "verify_es256k",
]
