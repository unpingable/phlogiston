"""Small dependency-free deep-immutability primitives."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence, Set
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, TypeVar

V = TypeVar("V")


class FrozenDict(Mapping[str, Any]):
    """An order-insensitive immutable mapping with recursively frozen values."""

    __slots__ = ("_data", "_hash")

    def __init__(self, source: Mapping[str, object] | None = None) -> None:
        data: dict[str, object] = {}
        for key, value in (source or {}).items():
            if not isinstance(key, str):
                raise TypeError("immutable mapping keys must be strings")
            data[key] = deep_freeze(value)
        object.__setattr__(self, "_data", MappingProxyType(data))
        object.__setattr__(self, "_hash", hash(tuple(sorted(data.items()))))

    def __setattr__(self, name: str, value: object) -> None:
        raise TypeError("FrozenDict is immutable")

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"FrozenDict({self._data!r})"

    def __hash__(self) -> int:
        return self._hash


def deep_freeze(value: object) -> object:
    """Copy nested containers into immutable equivalents.

    The accepted domain is deliberately small: JSON-like values plus bytes,
    aware datetimes, and enums used by the model contracts.
    """

    if isinstance(value, FrozenDict):
        return value
    if isinstance(value, Mapping):
        return FrozenDict(value)
    if isinstance(value, (str, int, float, bool, bytes, type(None), datetime, Enum)):
        return value
    if isinstance(value, bytearray | memoryview):
        return bytes(value)
    if isinstance(value, Set) and not isinstance(value, str | bytes):
        return frozenset(deep_freeze(item) for item in value)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return tuple(deep_freeze(item) for item in value)
    raise TypeError(f"unsupported mutable value type: {type(value).__name__}")


def deep_thaw(value: object) -> object:
    """Return ordinary JSON-like containers from frozen model values."""

    if isinstance(value, Mapping):
        return {key: deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [deep_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return [deep_thaw(item) for item in sorted(value, key=repr)]
    if isinstance(value, Enum):
        return value.value
    return value
