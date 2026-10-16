"""Shared helpers for governance tooling: digests and canonical hashing."""

from __future__ import annotations

import hashlib

import jcs


def sha256_hex(data: bytes) -> str:
    """Return the bare lowercase hex SHA-256 of *data*."""
    return hashlib.sha256(data).hexdigest()


def sha256_digest(data: bytes) -> str:
    """Return the ``sha256:``-prefixed digest used by governance artifacts."""
    return "sha256:" + sha256_hex(data)


def canonical_sha256(value: object) -> str:
    """Digest the RFC 8785 canonical form of a parsed JSON value."""
    return sha256_digest(jcs.canonical_bytes(value))


def find_key_paths(value: object, key_name: str, where: str = "$") -> list[str]:
    """Return paths of every occurrence of *key_name* in a JSON value."""
    found = []
    if isinstance(value, dict):
        for key, sub in value.items():
            here = f"{where}.{key}"
            if key == key_name:
                found.append(here)
            found.extend(find_key_paths(sub, key_name, here))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(find_key_paths(item, key_name, f"{where}[{index}]"))
    return found


def collect_strings(value: object) -> list[str]:
    """Return every string contained anywhere in a parsed JSON value."""
    out = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for key, sub in value.items():
            out.append(key)
            out.extend(collect_strings(sub))
    elif isinstance(value, list):
        for item in value:
            out.extend(collect_strings(item))
    return out
