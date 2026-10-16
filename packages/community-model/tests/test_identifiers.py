from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import pytest

from community_model.errors import ValidationError
from community_model.identifiers import (
    format_rfc3339,
    normalize_commit_identity,
    normalize_rfc3339,
    parse_at_uri,
    parse_rfc3339,
    rfc3339_is_after,
    tid_sort_key,
    validate_cid,
    validate_did,
    validate_nsid,
    validate_tid,
)

CID = "bafyreidfayvfuwqa7qlnopdjiqrxzs6blmoeu4rujcjtnci5beludirz2a"


@pytest.mark.parametrize(
    "did",
    [
        "did:web:community.invalid",
        "did:plc:ewvi7nxzyoun6zhxrhs64oiz",
        "did:method::::val",
    ],
)
def test_did_validation_is_network_free_and_syntactic(did: str) -> None:
    assert validate_did(did) == did


@pytest.mark.parametrize(
    "did",
    [
        "alice.example",
        "DID:web:example.com",
        "did:m3thod:value",
        "did::value",
        "did:web:",
        "did:web:a%b",
        "did:web:a%zzb",
        "did:web:a%2",
        "did:web:" + "a" * 2041,
    ],
)
def test_invalid_dids_have_a_stable_reason(did: str) -> None:
    with pytest.raises(ValidationError, match="did_invalid") as captured:
        validate_did(did)
    assert captured.value.reason_code == "did_invalid"


def test_at_uri_requires_did_authority_and_exact_record_path() -> None:
    uri = "at://did:web:alice.invalid/app.bsky.feed.post/3jzfcijpj2z2a"
    parsed = parse_at_uri(uri)
    assert (parsed.authority, parsed.collection, parsed.rkey) == (
        "did:web:alice.invalid",
        "app.bsky.feed.post",
        "3jzfcijpj2z2a",
    )

    for invalid in (
        "at://alice.example/app.bsky.feed.post/3jzfcijpj2z2a",
        f"{uri}?view=latest",
        "at://did:web:alice.invalid/app.bsky.feed.post",
    ):
        with pytest.raises(ValidationError, match="at_uri_invalid"):
            parse_at_uri(invalid)


def test_cid_validation_checks_structure_and_canonical_encoding() -> None:
    assert validate_cid(CID) == CID
    for invalid in (CID.upper(), CID[:-1], "bafy-not-base32", "QmNotAcceptedAsV1"):
        with pytest.raises(ValidationError, match="cid_invalid"):
            validate_cid(invalid)


def _cid(codec: int, hash_code: int, digest: bytes) -> str:
    raw = bytes((1, codec, hash_code, len(digest))) + digest
    return "b" + base64.b32encode(raw).decode().lower().rstrip("=")


def test_cid_validation_enforces_atproto_codec_and_hash_constraints() -> None:
    raw_blob = _cid(0x55, 0x12, b"x" * 32)
    assert validate_cid(raw_blob) == raw_blob
    with pytest.raises(ValidationError, match="cid_invalid"):
        validate_cid(raw_blob, require_dag_cbor=True)

    for invalid in (
        _cid(0x72, 0x12, b"x" * 32),
        _cid(0x71, 0x13, b"x" * 64),
    ):
        with pytest.raises(ValidationError, match="cid_invalid"):
            validate_cid(invalid)


def test_rfc3339_requires_offset_and_normalizes_utc() -> None:
    parsed = parse_rfc3339("2026-07-10T10:00:00-04:00")
    assert parsed == datetime(2026, 7, 10, 14, tzinfo=UTC)
    assert format_rfc3339(parsed) == "2026-07-10T14:00:00Z"
    assert format_rfc3339(parsed + timedelta(microseconds=123)) == (
        "2026-07-10T14:00:00.000123Z"
    )
    assert parse_rfc3339("2026-07-10T14:00:00.12345678912345Z") == datetime(
        2026, 7, 10, 14, 0, 0, 123456, tzinfo=UTC
    )
    assert (
        normalize_rfc3339("2026-07-10T10:00:00.12345678912345-04:00")
        == "2026-07-10T14:00:00.12345678912345Z"
    )
    boundary = datetime(2026, 7, 10, 14, 5, tzinfo=UTC)
    assert not rfc3339_is_after("2026-07-10T14:05:00.0000000Z", boundary)
    assert rfc3339_is_after("2026-07-10T14:05:00.0000001Z", boundary)

    for invalid in (
        "2026-07-10T14:00:00",
        "2026-07-10 14:00:00Z",
        "2026-07-10T14:00:00-00:00",
        "later",
    ):
        with pytest.raises(ValidationError, match="datetime_invalid"):
            parse_rfc3339(invalid)


def test_rfc3339_helpers_reject_wrong_runtime_types_as_validation_errors() -> None:
    boundary = datetime(2026, 7, 10, 14, tzinfo=UTC)
    calls = (
        lambda: parse_rfc3339(1),  # type: ignore[arg-type]
        lambda: rfc3339_is_after(1, boundary),  # type: ignore[arg-type]
        lambda: rfc3339_is_after(
            "2026-07-10T14:00:00Z",
            "2026-07-10T14:00:00Z",  # type: ignore[arg-type]
        ),
        lambda: format_rfc3339("2026-07-10T14:00:00Z"),  # type: ignore[arg-type]
    )
    for call in calls:
        with pytest.raises(ValidationError) as captured:
            call()
        assert captured.value.reason_code == "datetime_invalid"


def test_repository_revision_has_one_normalized_identity_and_numeric_order() -> None:
    earlier = "3jzfcijpj2z2b"
    later = "3jzfcijpj2z2c"
    assert validate_tid(earlier) == earlier
    assert normalize_commit_identity(earlier) == f"rev:{earlier}"
    assert tid_sort_key(earlier) < tid_sort_key(later)

    with pytest.raises(ValidationError, match="commit_revision_invalid"):
        validate_tid("not-a-tid")


@pytest.mark.parametrize(
    "nsid", ["com.example.fooBar", "net.users.bob.ping", "cn.8.lex.stuff"]
)
def test_nsid_uses_atproto_authority_and_name_grammar(nsid: str) -> None:
    assert validate_nsid(nsid) == nsid


@pytest.mark.parametrize(
    "nsid", ["com.example", "com.example.3", "com.example.foo-", "3com.example.foo"]
)
def test_invalid_nsid_is_rejected(nsid: str) -> None:
    with pytest.raises(ValidationError, match="schema_invalid"):
        validate_nsid(nsid)
