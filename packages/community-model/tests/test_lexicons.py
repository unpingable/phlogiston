from __future__ import annotations

from collections.abc import Mapping

import pytest

from community_model.errors import ValidationError
from community_model.immutable import deep_thaw
from community_model.lexicons import (
    available_lexicons,
    load_lexicon,
    validate_lexicon_record,
    validate_lexicon_schema,
)
from community_model.text import grapheme_count

POST_REF = {
    "uri": "at://did:web:alice.invalid/app.bsky.feed.post/3jzfcijpj2z2a",
    "cid": "bafyreidfayvfuwqa7qlnopdjiqrxzs6blmoeu4rujcjtnci5beludirz2a",
}
SUBMISSION_REF = {
    "uri": ("at://did:web:alice.invalid/app.phlogiston.community.submit/3jzfcijpj2z2b"),
    "cid": "bafyreigoxt64qghytzkr6ik7qvtzc7lyytiq5xbbrokbxjows2wp7vmo6q",
}
ADMISSION_REF = {
    "uri": (
        "at://did:web:community.invalid/app.phlogiston.community.admission/"
        "admit-a2d124bb56d1024475998d71b53d0fb36fc3caf4433efbcc7cc095dd226ff752"
    ),
    "cid": "bafyreiaizynclnqiolq7byfpjjtgqzn4sfrsgn7z2hhf6bo4utdwkin7ke",
}

PROFILE = {
    "$type": "app.phlogiston.community.profile",
    "displayName": "Homelab",
    "description": "Tiny computers, loud fans, unnecessary VLANs.",
    "createdAt": "2026-07-10T14:00:00Z",
}
SUBMISSION = {
    "$type": "app.phlogiston.community.submit",
    "community": "did:web:community.invalid",
    "subject": POST_REF,
    "createdAt": "2026-07-10T14:01:00Z",
}
ADMISSION = {
    "$type": "app.phlogiston.community.admission",
    "submission": SUBMISSION_REF,
    "subject": POST_REF,
    "actor": "did:web:admin.invalid",
    "createdAt": "2026-07-10T14:02:00Z",
}
REMOVAL = {
    "$type": "app.phlogiston.community.modAction",
    "action": "remove",
    "admission": ADMISSION_REF,
    "subject": POST_REF,
    "actor": "did:web:admin.invalid",
    "reason": "Off-topic for this community.",
    "createdAt": "2026-07-10T14:03:00Z",
}


def test_packaged_lexicon_inventory_is_stable_and_loadable() -> None:
    assert available_lexicons() == (
        "app.phlogiston.community.admission",
        "app.phlogiston.community.modAction",
        "app.phlogiston.community.memberAction",
        "app.phlogiston.community.profile",
        "app.phlogiston.community.replyAction",
        "app.phlogiston.community.replyAdmission",
        "app.phlogiston.community.replyPolicy",
        "app.phlogiston.community.submit",
    )
    for nsid in available_lexicons():
        document = load_lexicon(nsid)
        assert document["id"] == nsid
        assert validate_lexicon_schema(document) == document


def test_loaded_lexicons_are_deeply_immutable() -> None:
    document = load_lexicon("app.phlogiston.community.submit")
    defs = document["defs"]
    assert isinstance(defs, Mapping)
    with pytest.raises(TypeError):
        defs["later"] = {}  # type: ignore[index]


@pytest.mark.parametrize("record", [PROFILE, SUBMISSION, ADMISSION, REMOVAL])
def test_documented_record_examples_validate(record: dict[str, object]) -> None:
    validated = validate_lexicon_record(record)
    assert deep_thaw(validated) == record


def test_validated_record_copies_and_freezes_constructor_input() -> None:
    subject = dict(POST_REF)
    source = dict(SUBMISSION, subject=subject)
    validated = validate_lexicon_record(source)

    subject["uri"] = "at://did:web:mallory.invalid/app.bsky.feed.post/changed"
    source["community"] = "did:web:mallory.invalid"

    assert validated["community"] == "did:web:community.invalid"
    frozen_subject = validated["subject"]
    assert isinstance(frozen_subject, Mapping)
    assert frozen_subject["uri"] == POST_REF["uri"]
    with pytest.raises(TypeError):
        frozen_subject["uri"] = "changed"  # type: ignore[index]


@pytest.mark.parametrize(
    ("record", "path"),
    [
        ({"displayName": "Homelab", "createdAt": "2026-07-10T14:00:00Z"}, ("$type",)),
        (dict(PROFILE, surprise=True), ("surprise",)),
        (dict(PROFILE, displayName=""), ("displayName",)),
        (dict(SUBMISSION, community="not-a-did"), ("community",)),
        (dict(SUBMISSION, createdAt="2026-07-10 14:01:00"), ("createdAt",)),
    ],
)
def test_record_validation_is_strict(
    record: dict[str, object], path: tuple[str | int, ...]
) -> None:
    with pytest.raises(ValidationError) as captured:
        validate_lexicon_record(record)
    assert captured.value.path == path


def test_malformed_unicode_is_a_structured_schema_failure() -> None:
    with pytest.raises(ValidationError) as captured:
        validate_lexicon_record(dict(PROFILE, displayName="\ud800"))
    assert captured.value.reason_code == "schema_invalid"
    assert captured.value.path == ("displayName",)


def test_unknown_record_type_has_stable_reason() -> None:
    with pytest.raises(ValidationError) as captured:
        validate_lexicon_record({"$type": "example.other.record"})
    assert captured.value.reason_code == "unsupported_record_type"
    assert captured.value.path == ("$type",)


@pytest.mark.parametrize(
    "subject",
    [
        {"uri": POST_REF["uri"]},
        {"cid": POST_REF["cid"]},
        {**POST_REF, "extra": "not allowed"},
        {**POST_REF, "uri": "https://example.invalid/post"},
        {**POST_REF, "cid": "not-a-cid"},
    ],
)
def test_strong_ref_requires_exact_uri_cid_shape(subject: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        validate_lexicon_record(dict(SUBMISSION, subject=subject))


def test_string_limits_apply_to_graphemes_and_utf8_bytes() -> None:
    with pytest.raises(ValidationError):
        validate_lexicon_record(dict(PROFILE, displayName="x" * 65))

    # One base character plus combining marks remains one grapheme but crosses
    # the independent 640-byte Lexicon ceiling.
    with pytest.raises(ValidationError):
        validate_lexicon_record(dict(PROFILE, displayName="a" + "\u0301" * 320))


def test_grapheme_count_handles_unicode_clusters_without_zwj_limit_bypass() -> None:
    assert grapheme_count("가") == 1
    assert grapheme_count("का") == 1
    assert grapheme_count("👩\u200d👩\u200d👧\u200d👦") == 1
    assert grapheme_count("🇺🇸🇨🇦") == 2
    assert grapheme_count("a\u200db") == 2
    assert grapheme_count("👩\u200d\u0301👩") == 2
    assert grapheme_count("्a" * 65) == 66

    bypass = "a\u200db" * 33
    assert len(bypass.encode("utf-8")) < 640
    assert grapheme_count(bypass) == 66
    with pytest.raises(ValidationError):
        validate_lexicon_record(dict(PROFILE, displayName=bypass))

    for exact_bypass in ("\U000e0000\u0735" * 33, "a\u106c" * 33):
        assert len(exact_bypass.encode("utf-8")) < 640
        assert grapheme_count(exact_bypass) == 66
        with pytest.raises(ValidationError):
            validate_lexicon_record(dict(PROFILE, displayName=exact_bypass))


def test_known_values_remain_open_at_generic_lexicon_layer() -> None:
    record = dict(REMOVAL, action="future-action")
    assert validate_lexicon_record(record)["action"] == "future-action"


def test_schema_validator_rejects_invalid_local_schema() -> None:
    schema = deep_thaw(load_lexicon("app.phlogiston.community.profile"))
    assert isinstance(schema, dict)
    main = schema["defs"]["main"]  # type: ignore[index]
    required = main["record"]["required"]  # type: ignore[index]
    required.append("displayName")

    with pytest.raises(ValidationError) as captured:
        validate_lexicon_schema(schema)
    assert captured.value.reason_code == "schema_invalid"
    assert captured.value.path == ("defs", "main", "record", "required", 2)


def test_unavailable_lexicon_fails_closed() -> None:
    with pytest.raises(ValidationError) as captured:
        load_lexicon("app.phlogiston.community.unknown")
    assert captured.value.reason_code == "unsupported_record_type"


def test_superseded_neutral_record_cannot_enter_current_model() -> None:
    with pytest.raises(ValidationError) as captured:
        validate_lexicon_record(
            dict(PROFILE, **{"$type": "zone.neutral.community.profile"})
        )
    assert captured.value.reason_code == "unsupported_record_type"
