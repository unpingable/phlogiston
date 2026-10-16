"""Pure-Python secp256k1 ECDSA verification for ATProto commit proofs.

This module verifies only.  It contains no key generation or signing path,
consistent with the observer's detect-only charter: ``communitywatch`` checks
signatures other parties made and can never produce one.

ATProto signs the SHA-256 of the canonical DAG-CBOR unsigned commit with a
compact 64-byte ``r || s`` signature and requires low-S normalized form.
"""

from __future__ import annotations

_FIELD = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
_GENERATOR = (_GX, _GY)

_Point = tuple[int, int] | None


def _add(left: _Point, right: _Point) -> _Point:
    if left is None:
        return right
    if right is None:
        return left
    x1, y1 = left
    x2, y2 = right
    if x1 == x2 and (y1 != y2 or y1 == 0):
        return None
    if left == right:
        slope = (3 * x1 * x1) * pow(2 * y1, -1, _FIELD) % _FIELD
    else:
        slope = (y2 - y1) * pow(x2 - x1, -1, _FIELD) % _FIELD
    x3 = (slope * slope - x1 - x2) % _FIELD
    y3 = (slope * (x1 - x3) - y1) % _FIELD
    return (x3, y3)


def _multiply(scalar: int, point: _Point) -> _Point:
    result: _Point = None
    addend = point
    while scalar:
        if scalar & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)
        scalar >>= 1
    return result


def decode_public_key(public_key: bytes) -> tuple[int, int]:
    """Decode a 33-byte compressed secp256k1 public key to a curve point."""

    if (
        not isinstance(public_key, bytes)
        or len(public_key) != 33
        or public_key[0] not in (2, 3)
    ):
        raise ValueError("expected a 33-byte compressed secp256k1 public key")
    x = int.from_bytes(public_key[1:], "big")
    if x >= _FIELD:
        raise ValueError("public key x-coordinate is outside the field")
    y_squared = (pow(x, 3, _FIELD) + 7) % _FIELD
    y = pow(y_squared, (_FIELD + 1) // 4, _FIELD)
    if (y * y) % _FIELD != y_squared:
        raise ValueError("public key is not on the secp256k1 curve")
    if (y & 1) != (public_key[0] & 1):
        y = _FIELD - y
    return (x, y)


def verify_signature(
    public_key: bytes, message_digest32: bytes, signature: bytes
) -> bool:
    """Verify one compact low-S ECDSA signature over a 32-byte digest.

    Returns ``False`` for every malformed or non-matching input instead of
    raising, so hostile proof material fails closed without exceptions.
    """

    try:
        point = decode_public_key(public_key)
    except ValueError:
        return False
    if (
        not isinstance(message_digest32, bytes)
        or len(message_digest32) != 32
        or not isinstance(signature, bytes)
        or len(signature) != 64
    ):
        return False
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    if not (1 <= r < _ORDER and 1 <= s <= _ORDER // 2):
        # ATProto requires low-S normalized signatures; a high-S signature is
        # not authentic commit evidence even though the math would accept it.
        return False
    z = int.from_bytes(message_digest32, "big")
    inverse = pow(s, -1, _ORDER)
    candidate = _add(
        _multiply(z * inverse % _ORDER, _GENERATOR),
        _multiply(r * inverse % _ORDER, point),
    )
    return candidate is not None and candidate[0] % _ORDER == r


__all__ = ["decode_public_key", "verify_signature"]
