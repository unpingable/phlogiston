"""Strict, network-free validation for V0 identifiers and signed time."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Match

from .errors import ValidationError

_DID_IDCHAR = r"(?:[A-Za-z0-9._-]|%[0-9A-Fa-f]{2})"
_DID_RE = re.compile(rf"^did:[a-z]+:(?:{_DID_IDCHAR}|:)*{_DID_IDCHAR}$")
_NSID_RE = re.compile(
    r"^[A-Za-z](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
    r"\.[A-Za-z][A-Za-z0-9]{0,62}$"
)
_RKEY_RE = re.compile(r"^[A-Za-z0-9._~:-]{1,512}$")
_TID_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"
_TID_RE = re.compile(r"^[234567abcdefghijklmnopqrstuvwxyz]{13}$")
_RFC3339_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T"
    r"(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?P<fraction>\.\d+)?"
    r"(?P<offset>Z|[+-]\d{2}:\d{2})$"
)


def validate_did(value: object, *, path: tuple[str | int, ...] = ()) -> str:
    if not isinstance(value, str) or len(value) > 2048 or not _DID_RE.fullmatch(value):
        raise ValidationError(
            "did_invalid", "expected a syntactically valid DID", path=path
        )
    return value


def validate_nsid(value: object, *, path: tuple[str | int, ...] = ()) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 317
        or not _NSID_RE.fullmatch(value)
        or len(value.rsplit(".", 1)[0]) > 253
    ):
        raise ValidationError(
            "schema_invalid", "expected a syntactically valid NSID", path=path
        )
    return value


def validate_rkey(value: object, *, path: tuple[str | int, ...] = ()) -> str:
    if (
        not isinstance(value, str)
        or not _RKEY_RE.fullmatch(value)
        or value in {".", ".."}
    ):
        raise ValidationError(
            "at_uri_invalid", "expected a valid ATProto record key", path=path
        )
    return value


@dataclass(frozen=True, slots=True)
class AtUri:
    raw: str
    authority: str
    collection: str
    rkey: str


def parse_at_uri(
    value: object,
    *,
    require_did_authority: bool = True,
    path: tuple[str | int, ...] = (),
) -> AtUri:
    if not isinstance(value, str) or not value.startswith("at://"):
        raise ValidationError("at_uri_invalid", "expected an at:// URI", path=path)
    if any(character in value for character in ("?", "#", "\x00")):
        raise ValidationError(
            "at_uri_invalid",
            "AT URI may not contain query, fragment, or NUL",
            path=path,
        )
    parts = value[5:].split("/")
    if len(parts) != 3 or any(not part for part in parts):
        raise ValidationError(
            "at_uri_invalid",
            "expected at://<did>/<collection>/<rkey>",
            path=path,
        )
    authority, collection, rkey = parts
    if require_did_authority:
        try:
            validate_did(authority, path=path + ("authority",))
        except ValidationError as exc:
            raise ValidationError(
                "at_uri_invalid", "AT URI authority must be a DID", path=path
            ) from exc
    validate_nsid(collection, path=path + ("collection",))
    validate_rkey(rkey, path=path + ("rkey",))
    return AtUri(value, authority, collection, rkey)


def _read_uvarint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    for position in range(offset, len(data)):
        octet = data[position]
        value |= (octet & 0x7F) << shift
        if not octet & 0x80:
            encoded_length = position - offset + 1
            if encoded_length > 1 and octet == 0:
                raise ValueError("non-canonical varint")
            return value, position + 1
        shift += 7
        if shift > 63:
            break
    raise ValueError("invalid varint")


def decode_cid(value: object, *, path: tuple[str | int, ...] = ()) -> bytes:
    if (
        not isinstance(value, str)
        or not value.startswith("b")
        or value != value.lower()
    ):
        raise ValidationError(
            "cid_invalid", "expected a canonical base32-lower CIDv1", path=path
        )
    encoded = value[1:]
    if not encoded or not re.fullmatch(r"[a-z2-7]+", encoded):
        raise ValidationError("cid_invalid", "invalid CID multibase payload", path=path)
    try:
        padding = "=" * ((8 - len(encoded) % 8) % 8)
        raw = base64.b32decode(encoded.upper() + padding, casefold=False)
        version, cursor = _read_uvarint(raw, 0)
        codec, cursor = _read_uvarint(raw, cursor)
        hash_code, cursor = _read_uvarint(raw, cursor)
        digest_length, cursor = _read_uvarint(raw, cursor)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValidationError("cid_invalid", "malformed CID", path=path) from exc
    if (
        version != 1
        or codec not in {0x55, 0x71}
        or hash_code != 0x12
        or digest_length != 32
        or len(raw) - cursor != digest_length
    ):
        raise ValidationError(
            "cid_invalid", "CID uses unsupported ATProto components", path=path
        )
    canonical = "b" + base64.b32encode(raw).decode("ascii").lower().rstrip("=")
    if canonical != value:
        raise ValidationError("cid_invalid", "CID is not canonical", path=path)
    return raw


def validate_cid(
    value: object,
    *,
    require_dag_cbor: bool = False,
    path: tuple[str | int, ...] = (),
) -> str:
    raw = decode_cid(value, path=path)
    _, cursor = _read_uvarint(raw, 0)
    codec, _ = _read_uvarint(raw, cursor)
    if require_dag_cbor and codec != 0x71:
        raise ValidationError(
            "cid_invalid", "repository record CID must use dag-cbor", path=path
        )
    assert isinstance(value, str)
    return value


def parse_rfc3339(value: object, *, path: tuple[str | int, ...] = ()) -> datetime:
    match = _match_rfc3339(value, path=path)
    assert isinstance(value, str)
    fraction = match.group("fraction")
    if fraction is not None:
        native_fraction = fraction[1:7].ljust(6, "0")
        native_value = (
            f"{match.group('date')}T{match.group('time')}.{native_fraction}"
            f"{match.group('offset')}"
        )
    else:
        native_value = value
    normalized = (
        native_value[:-1] + "+00:00" if native_value.endswith("Z") else native_value
    )
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValidationError(
            "datetime_invalid", "invalid calendar time", path=path
        ) from exc
    if parsed.utcoffset() is None:
        raise ValidationError(
            "datetime_invalid", "datetime offset is required", path=path
        )
    return parsed.astimezone(UTC)


def _match_rfc3339(value: object, *, path: tuple[str | int, ...] = ()) -> Match[str]:
    if not isinstance(value, str) or not (match := _RFC3339_RE.fullmatch(value)):
        raise ValidationError(
            "datetime_invalid",
            "expected RFC 3339 with an explicit offset",
            path=path,
        )
    if match.group("offset") == "-00:00":
        raise ValidationError(
            "datetime_invalid",
            "negative-zero timezone offset is not allowed",
            path=path,
        )
    return match


def rfc3339_is_after(value: str, boundary: datetime) -> bool:
    """Compare signed timestamp text without losing fractional precision."""

    match = _match_rfc3339(value)
    if not isinstance(boundary, datetime) or boundary.utcoffset() is None:
        raise ValidationError(
            "datetime_invalid", "comparison boundary must have an offset"
        )
    offset = match.group("offset")
    base_text = f"{match.group('date')}T{match.group('time')}{offset}"
    normalized = base_text[:-1] + "+00:00" if base_text.endswith("Z") else base_text
    try:
        base = datetime.fromisoformat(normalized).astimezone(UTC)
    except ValueError as exc:
        raise ValidationError("datetime_invalid", "invalid calendar time") from exc
    boundary_utc = boundary.astimezone(UTC)
    boundary_base = boundary_utc.replace(microsecond=0)
    if base != boundary_base:
        return base > boundary_base
    digits = (match.group("fraction") or ".0")[1:]
    leading_microseconds = int(digits[:6].ljust(6, "0"))
    if leading_microseconds != boundary_utc.microsecond:
        return leading_microseconds > boundary_utc.microsecond
    return any(digit != "0" for digit in digits[6:])


def normalize_rfc3339(value: object, *, path: tuple[str | int, ...] = ()) -> str:
    """Normalize an RFC 3339 instant to UTC without truncating its fraction."""

    match = _match_rfc3339(value, path=path)
    offset = match.group("offset")
    base_text = f"{match.group('date')}T{match.group('time')}{offset}"
    normalized = base_text[:-1] + "+00:00" if base_text.endswith("Z") else base_text
    try:
        utc_base = datetime.fromisoformat(normalized).astimezone(UTC)
    except ValueError as exc:
        raise ValidationError(
            "datetime_invalid", "invalid calendar time", path=path
        ) from exc
    whole_seconds = utc_base.isoformat(timespec="seconds").removesuffix("+00:00")
    return f"{whole_seconds}{match.group('fraction') or ''}Z"


def format_rfc3339(value: datetime) -> str:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValidationError("datetime_invalid", "naive datetime is not allowed")
    normalized = value.astimezone(UTC)
    timespec = "microseconds" if normalized.microsecond else "seconds"
    return normalized.isoformat(timespec=timespec).replace("+00:00", "Z")


def validate_tid(value: object, *, path: tuple[str | int, ...] = ()) -> str:
    if not isinstance(value, str) or not _TID_RE.fullmatch(value):
        raise ValidationError(
            "commit_revision_invalid", "expected a 13-character ATProto TID", path=path
        )
    if _TID_ALPHABET.index(value[0]) >= 16:
        raise ValidationError(
            "commit_revision_invalid",
            "TID exceeds its 64-bit canonical range",
            path=path,
        )
    return value


def tid_sort_key(value: str) -> int:
    validate_tid(value)
    result = 0
    for character in value:
        result = result * 32 + _TID_ALPHABET.index(character)
    return result


def normalize_commit_identity(revision: object) -> str:
    return f"rev:{validate_tid(revision)}"
