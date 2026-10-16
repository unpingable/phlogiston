"""Minimal RFC 8785 (JSON Canonicalization Scheme) serializer.

Governance artifacts are digested over their canonical JSON form. This
serializer covers the JSON subset the governance schemas allow: null,
booleans, integers, strings, arrays, and objects. Floats are rejected
outright so no artifact can smuggle in a value whose canonical number
serialization is implementation-defined.

Key ordering follows RFC 8785: object keys are sorted by their UTF-16
code-unit sequence. For the printable-ASCII identifiers used by the
governance schemas this equals plain codepoint order, but the UTF-16
encoding is used here so non-ASCII keys still canonicalize correctly.
"""

from __future__ import annotations

import json

_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


class JcsError(ValueError):
    """A value cannot be canonically serialized."""


def _encode_string(value: str) -> str:
    out = ['"']
    for ch in value:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _sort_key(key: str) -> bytes:
    return key.encode("utf-16-be", "surrogatepass")


def _serialize(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        raise JcsError("floats are not permitted in canonical governance JSON")
    if isinstance(value, str):
        return _encode_string(value)
    if isinstance(value, list):
        return "[" + ",".join(_serialize(item) for item in value) + "]"
    if isinstance(value, dict):
        parts = []
        for key in sorted(value, key=_sort_key):
            if not isinstance(key, str):
                raise JcsError("object keys must be strings")
            parts.append(_encode_string(key) + ":" + _serialize(value[key]))
        return "{" + ",".join(parts) + "}"
    raise JcsError(f"unsupported value type: {type(value).__name__}")


def canonicalize(value: object) -> str:
    """Return the RFC 8785 canonical form of a parsed JSON value."""
    return _serialize(value)


def canonical_bytes(value: object) -> bytes:
    """Return the canonical form as UTF-8 bytes, ready for digesting."""
    return canonicalize(value).encode("utf-8")


def round_trips(text: str) -> bool:
    """True when *text* is already the canonical form of its own value."""
    return canonicalize(json.loads(text)) == text
