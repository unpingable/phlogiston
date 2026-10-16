"""Tests for the gstrict engine, strict loader, and JCS canonicalizer."""

from __future__ import annotations

import gstrict
import jcs
import pytest


class TestStrictLoader:
    def test_duplicate_keys_rejected(self):
        with pytest.raises(gstrict.StrictJsonError):
            gstrict.strict_loads('{"a": 1, "a": 2}')

    def test_non_json_constants_rejected(self):
        for text in ('{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}'):
            with pytest.raises(gstrict.StrictJsonError):
                gstrict.strict_loads(text)

    def test_floats_rejected(self):
        with pytest.raises(gstrict.StrictJsonError):
            gstrict.strict_loads('{"a": 1.5}')

    def test_malformed_json_rejected(self):
        with pytest.raises(gstrict.StrictJsonError):
            gstrict.strict_loads("{not json")


class TestJcs:
    def test_canonical_ordering_and_whitespace(self):
        value = {"b": [1, True, None], "a": {"z": "x"}}
        assert jcs.canonicalize(value) == '{"a":{"z":"x"},"b":[1,true,null]}'

    def test_string_escaping(self):
        value = 'a"b\nc\x01'
        assert jcs.canonicalize(value) == '"a\\"b\\nc\\u0001"'

    def test_float_rejected(self):
        with pytest.raises(jcs.JcsError):
            jcs.canonicalize(1.5)

    def test_non_ascii_key_ordering_uses_utf16(self):
        # U+00E9 (é) sorts after ASCII keys under UTF-16 code-unit order.
        assert jcs.canonicalize({"é": 1, "z": 2}) == '{"z":2,"é":1}'


class TestSchemaEngine:
    SCHEMA = {
        "schema": "gstrict-v1",
        "id": "test",
        "version": "1",
        "root": {
            "type": "object",
            "fields": {
                "name": {"type": "string", "min_length": 1},
                "count": {"type": "integer", "minimum": 0},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "unique_items": True,
                },
                "kind": {"type": "string", "enum": ["a", "b"]},
                "note": {"type": "string"},
            },
            "required": ["name", "count"],
        },
    }

    def setup_method(self):
        self.root = gstrict.load_schema(self.SCHEMA)

    def test_valid(self):
        assert not gstrict.validate({"name": "x", "count": 0}, self.root)

    def test_missing_required(self):
        problems = gstrict.validate({"count": 0}, self.root)
        assert any("missing required field 'name'" in p for p in problems)

    def test_unknown_field(self):
        problems = gstrict.validate({"name": "x", "count": 0, "extra": 1}, self.root)
        assert any("unknown field 'extra'" in p for p in problems)

    def test_placeholder_rejected(self):
        for bad in ("TBD", "todo", "<fill me>", "FIXME"):
            problems = gstrict.validate({"name": bad, "count": 0}, self.root)
            assert any("placeholder" in p for p in problems), bad

    def test_boolean_is_not_integer(self):
        problems = gstrict.validate({"name": "x", "count": True}, self.root)
        assert any("expected integer" in p for p in problems)

    def test_enum(self):
        problems = gstrict.validate({"name": "x", "count": 0, "kind": "c"}, self.root)
        assert any("not one of" in p for p in problems)

    def test_unique_items(self):
        problems = gstrict.validate(
            {"name": "x", "count": 0, "tags": ["a", "a"]}, self.root
        )
        assert any("duplicate array item" in p for p in problems)

    def test_one_of_exactly_one(self):
        node = {
            "one_of": [
                {"type": "string", "enum": ["x"]},
                {"type": "string", "min_length": 1},
            ]
        }
        assert gstrict.validate("x", node)  # matches both branches
        assert not gstrict.validate("y", node)
        assert gstrict.validate(5, node)  # matches neither


class TestFormats:
    @pytest.mark.parametrize(
        ("fmt", "good", "bad"),
        [
            (
                "digest",
                "sha256:" + "a" * 64,
                ["sha256:" + "A" * 64, "sha256:abc", "a" * 64],
            ),
            ("commit", "a" * 40, ["a" * 39, "g" * 40]),
            (
                "timestamp",
                "2026-08-14T01:58:09Z",
                [
                    "2026-08-14T01:58:09+00:00",
                    "2026-08-14 01:58:09Z",
                    "2026-13-14T01:58:09Z",
                ],
            ),
            ("id", "OQP-OQ-7-2026-07-27-03", ["has space", "tab\there"]),
            ("uri", "file:///evidence/x", ["relative/path", "no scheme"]),
            (
                "path",
                "docs/OPEN-QUESTIONS.md",
                ["/abs/path", "../up", "a//b", "a/./b", "a\\b"],
            ),
        ],
    )
    def test_format(self, fmt, good, bad):
        node = {"type": "string", "format": fmt}
        assert not gstrict.validate(good, node)
        for value in bad:
            assert gstrict.validate(value, node), (fmt, value)
