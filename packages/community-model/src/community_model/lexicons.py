"""Packaged provisional Lexicons and their deliberately small validator.

This module implements only the Lexicon subset used by the four V0 records.
It validates record shape; repository ownership, authority, and agreement
between strong references remain contextual validation concerns.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from functools import lru_cache
from importlib import resources
from typing import TypeAlias, cast

from .errors import ValidationError
from .identifiers import (
    parse_at_uri,
    parse_rfc3339,
    validate_cid,
    validate_did,
    validate_nsid,
)
from .immutable import deep_freeze
from .text import grapheme_count

JsonPath: TypeAlias = tuple[str | int, ...]

_LEXICON_NSIDS = (
    "app.phlogiston.community.admission",
    "app.phlogiston.community.modAction",
    "app.phlogiston.community.memberAction",
    "app.phlogiston.community.profile",
    "app.phlogiston.community.replyAction",
    "app.phlogiston.community.replyAdmission",
    "app.phlogiston.community.replyPolicy",
    "app.phlogiston.community.submit",
)
_ROOT_FIELDS = frozenset({"lexicon", "id", "defs", "revision", "description"})
_DEFINITION_FIELDS = frozenset({"type", "key", "description", "record"})
_OBJECT_SCHEMA_FIELDS = frozenset({"type", "required", "properties"})
_STRING_SCHEMA_FIELDS = frozenset(
    {
        "type",
        "format",
        "description",
        "minLength",
        "maxLength",
        "minGraphemes",
        "maxGraphemes",
        "knownValues",
    }
)
_REF_SCHEMA_FIELDS = frozenset({"type", "ref", "description"})
_SUPPORTED_RECORD_KEYS = frozenset({"literal:self", "tid", "any"})
_SUPPORTED_STRING_FORMATS = frozenset({"did", "datetime"})
_STRONG_REF = "com.atproto.repo.strongRef"


def available_lexicons() -> tuple[str, ...]:
    """Return the stable, sorted set of packaged provisional record NSIDs."""

    return _LEXICON_NSIDS


@lru_cache(maxsize=len(_LEXICON_NSIDS))
def load_lexicon(nsid: str) -> Mapping[str, object]:
    """Load and validate one packaged Lexicon as a deeply immutable mapping."""

    if nsid not in _LEXICON_NSIDS:
        raise ValidationError(
            "unsupported_record_type",
            f"unsupported provisional Lexicon: {nsid!r}",
            path=("id",),
        )

    resource = resources.files("community_model").joinpath("schemas", f"{nsid}.json")
    try:
        document = json.loads(
            resource.read_text(encoding="utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
        )
    except _DuplicateKeyError as exc:
        raise ValidationError(
            "schema_invalid",
            f"duplicate key in packaged Lexicon: {exc.key!r}",
            path=(),
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "schema_invalid",
            f"could not load packaged Lexicon {nsid!r}",
            path=(),
        ) from exc

    validated = validate_lexicon_schema(document)
    if validated["id"] != nsid:
        raise ValidationError(
            "schema_invalid",
            "packaged Lexicon id does not match its resource name",
            path=("id",),
        )
    return validated


def validate_lexicon_schema(document: object) -> Mapping[str, object]:
    """Validate the local, record-only Lexicon subset and freeze the result."""

    root = _require_mapping(document, ())
    _reject_unknown_fields(root, _ROOT_FIELDS, ())

    if root.get("lexicon") != 1 or isinstance(root.get("lexicon"), bool):
        _fail("Lexicon version must be integer 1", ("lexicon",))

    nsid = _require_string(root, "id", ())
    try:
        validate_nsid(nsid, path=("id",))
    except ValidationError as exc:
        raise ValidationError(
            "schema_invalid", "Lexicon id is not a valid NSID", path=("id",)
        ) from exc

    if "revision" in root:
        _require_nonnegative_integer(root["revision"], ("revision",))
    if "description" in root:
        _require_value_string(root["description"], ("description",))

    defs = _require_mapping_field(root, "defs", ())
    if not defs:
        _fail("Lexicon defs must not be empty", ("defs",))
    if "main" not in defs:
        _fail("record Lexicon must define defs.main", ("defs", "main"))

    for def_name, definition_value in defs.items():
        if not isinstance(def_name, str) or not def_name:
            _fail("Lexicon definition names must be non-empty strings", ("defs",))
        _validate_record_definition(definition_value, ("defs", def_name))

    return cast(Mapping[str, object], deep_freeze(root))


def validate_lexicon_record(record: object) -> Mapping[str, object]:
    """Validate a record against its packaged provisional Lexicon.

    ``knownValues`` is intentionally advisory at this generic Lexicon layer, as
    required by Lexicon's open-world semantics. V0 policy may separately reject
    an action it does not implement.
    """

    value = _require_mapping(record, ())
    record_type = value.get("$type")
    if not isinstance(record_type, str) or not record_type:
        _fail("record must contain a non-empty string $type", ("$type",))
    if record_type not in _LEXICON_NSIDS:
        raise ValidationError(
            "unsupported_record_type",
            f"unsupported provisional record type: {record_type!r}",
            path=("$type",),
        )

    lexicon = load_lexicon(record_type)
    defs = cast(Mapping[str, object], lexicon["defs"])
    main = cast(Mapping[str, object], defs["main"])
    schema = cast(Mapping[str, object], main["record"])
    properties = cast(Mapping[str, object], schema["properties"])
    allowed_fields = frozenset(properties) | {"$type"}
    _reject_unknown_fields(value, allowed_fields, ())

    required = cast(Sequence[str], schema.get("required", ()))
    for field in required:
        if field not in value:
            _fail("required record field is missing", (field,))

    for field, field_value in value.items():
        if field == "$type":
            continue
        property_schema = cast(Mapping[str, object], properties[field])
        _validate_property_value(field_value, property_schema, (field,))

    return cast(Mapping[str, object], deep_freeze(value))


def _validate_record_definition(value: object, path: JsonPath) -> None:
    definition = _require_mapping(value, path)
    _reject_unknown_fields(definition, _DEFINITION_FIELDS, path)
    if definition.get("type") != "record":
        _fail("only record definitions are supported", path + ("type",))

    key = _require_string(definition, "key", path)
    if key not in _SUPPORTED_RECORD_KEYS:
        _fail("unsupported record-key declaration", path + ("key",))
    if "description" in definition:
        _require_value_string(definition["description"], path + ("description",))

    record = _require_mapping_field(definition, "record", path)
    _reject_unknown_fields(record, _OBJECT_SCHEMA_FIELDS, path + ("record",))
    if record.get("type") != "object":
        _fail("record schema type must be object", path + ("record", "type"))

    properties = _require_mapping_field(record, "properties", path + ("record",))
    for name, property_value in properties.items():
        if not isinstance(name, str) or not name or name.startswith("$"):
            _fail(
                "record property names must be non-empty strings without a $ prefix",
                path + ("record", "properties"),
            )
        _validate_property_schema(
            property_value,
            path + ("record", "properties", name),
        )

    required_value = record.get("required", ())
    required = _require_sequence(required_value, path + ("record", "required"))
    seen: set[str] = set()
    for index, name in enumerate(required):
        item_path = path + ("record", "required", index)
        if not isinstance(name, str) or not name:
            _fail("required fields must be non-empty strings", item_path)
        if name in seen:
            _fail("required fields must not contain duplicates", item_path)
        if name not in properties:
            _fail("required field has no property schema", item_path)
        seen.add(name)


def _validate_property_schema(value: object, path: JsonPath) -> None:
    schema = _require_mapping(value, path)
    property_type = schema.get("type")
    if property_type == "string":
        _reject_unknown_fields(schema, _STRING_SCHEMA_FIELDS, path)
        if "description" in schema:
            _require_value_string(schema["description"], path + ("description",))
        if "format" in schema:
            string_format = _require_value_string(schema["format"], path + ("format",))
            if string_format not in _SUPPORTED_STRING_FORMATS:
                _fail("unsupported string format", path + ("format",))

        constraints: dict[str, int] = {}
        for name in ("minLength", "maxLength", "minGraphemes", "maxGraphemes"):
            if name in schema:
                constraints[name] = _require_nonnegative_integer(
                    schema[name], path + (name,)
                )
        if constraints.get("minLength", 0) > constraints.get("maxLength", 2**63):
            _fail("minLength must not exceed maxLength", path)
        if constraints.get("minGraphemes", 0) > constraints.get("maxGraphemes", 2**63):
            _fail("minGraphemes must not exceed maxGraphemes", path)

        if "knownValues" in schema:
            known_values = _require_sequence(
                schema["knownValues"], path + ("knownValues",)
            )
            seen: set[str] = set()
            for index, known_value in enumerate(known_values):
                item_path = path + ("knownValues", index)
                if not isinstance(known_value, str):
                    _fail("knownValues entries must be strings", item_path)
                if known_value in seen:
                    _fail("knownValues entries must be unique", item_path)
                seen.add(known_value)
        return

    if property_type == "ref":
        _reject_unknown_fields(schema, _REF_SCHEMA_FIELDS, path)
        ref = _require_string(schema, "ref", path)
        if ref != _STRONG_REF:
            _fail("only com.atproto.repo.strongRef is supported", path + ("ref",))
        if "description" in schema:
            _require_value_string(schema["description"], path + ("description",))
        return

    _fail("property schema has unsupported type", path + ("type",))


def _validate_property_value(
    value: object,
    schema: Mapping[str, object],
    path: JsonPath,
) -> None:
    property_type = schema["type"]
    if property_type == "ref":
        _validate_strong_ref(value, path)
        return

    if property_type != "string" or not isinstance(value, str):
        _fail("record field has the wrong type", path)

    try:
        byte_length = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        _fail("record string is not valid Unicode scalar text", path)
    if "minLength" in schema and byte_length < cast(int, schema["minLength"]):
        _fail("record string is shorter than minLength", path)
    if "maxLength" in schema and byte_length > cast(int, schema["maxLength"]):
        _fail("record string exceeds maxLength", path)

    if "minGraphemes" in schema or "maxGraphemes" in schema:
        graphemes = grapheme_count(value)
        if "minGraphemes" in schema and graphemes < cast(int, schema["minGraphemes"]):
            _fail("record string is shorter than minGraphemes", path)
        if "maxGraphemes" in schema and graphemes > cast(int, schema["maxGraphemes"]):
            _fail("record string exceeds maxGraphemes", path)

    string_format = schema.get("format")
    if string_format == "did":
        validate_did(value, path=path)
    elif string_format == "datetime":
        parse_rfc3339(value, path=path)


def _validate_strong_ref(value: object, path: JsonPath) -> None:
    strong_ref = _require_mapping(value, path)
    _reject_unknown_fields(strong_ref, frozenset({"uri", "cid"}), path)
    uri = _require_string(strong_ref, "uri", path)
    cid = _require_string(strong_ref, "cid", path)
    parse_at_uri(uri, path=path + ("uri",))
    validate_cid(cid, require_dag_cbor=True, path=path + ("cid",))


def _reject_unknown_fields(
    value: Mapping[object, object],
    allowed: frozenset[str] | set[str],
    path: JsonPath,
) -> None:
    for key in value:
        if not isinstance(key, str):
            _fail("object keys must be strings", path)
        if key not in allowed:
            _fail("unknown field", path + (key,))


def _require_mapping(value: object, path: JsonPath) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        _fail("expected an object", path)
    return cast(Mapping[str, object], value)


def _require_mapping_field(
    value: Mapping[str, object],
    name: str,
    path: JsonPath,
) -> Mapping[str, object]:
    if name not in value:
        _fail("required field is missing", path + (name,))
    return _require_mapping(value[name], path + (name,))


def _require_string(value: Mapping[str, object], name: str, path: JsonPath) -> str:
    if name not in value:
        _fail("required field is missing", path + (name,))
    return _require_value_string(value[name], path + (name,))


def _require_value_string(value: object, path: JsonPath) -> str:
    if not isinstance(value, str) or not value:
        _fail("expected a non-empty string", path)
    return value


def _require_sequence(value: object, path: JsonPath) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail("expected an array", path)
    return cast(Sequence[object], value)


def _require_nonnegative_integer(value: object, path: JsonPath) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail("expected a non-negative integer", path)
    return value


def _fail(message: str, path: JsonPath) -> None:
    raise ValidationError("schema_invalid", message, path=path)


class _DuplicateKeyError(ValueError):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _object_without_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(key)
        result[key] = value
    return result


__all__ = [
    "available_lexicons",
    "load_lexicon",
    "validate_lexicon_record",
    "validate_lexicon_schema",
]
