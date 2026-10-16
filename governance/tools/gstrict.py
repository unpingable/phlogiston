"""Strict JSON loading and a minimal strict schema engine ("gstrict-v1").

The governance tooling may not depend on third-party JSON Schema packages,
so this module implements the small strict dialect used by the schema
documents under ``governance/schemas/``:

- ``{"type": "object", "fields": {...}, "required": [...]}`` — every key in
  the value must be declared in ``fields`` (unknown keys are rejected) and
  every name in ``required`` must be present.
- ``{"type": "array", "items": node, "min_items": n, "max_items": n,
  "unique_items": bool}``.
- ``{"type": "string", "enum": [...], "pattern": regex, "min_length": n,
  "max_length": n, "format": name}``.
- ``{"type": "integer", "minimum": n, "maximum": n}``.
- ``{"type": "boolean"}`` and ``{"type": "null"}``.
- ``{"one_of": [node, ...]}`` — exactly one branch must match.

String formats: ``digest`` (``sha256:`` + 64 lowercase hex), ``commit``
(40 lowercase hex), ``timestamp`` (RFC 3339 UTC), ``id`` (nonempty printable
ASCII without whitespace), ``uri`` (absolute URI), ``path``
(repository-relative path without traversal).

Every string value is additionally screened for placeholder tokens
(``TBD``, ``TODO``, angle-bracket placeholders, and similar), and the strict
loader rejects duplicate object keys, non-JSON constants, and floats.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
ID_RE = re.compile(r"^[!-~]+$")
URI_RE = re.compile(r"^[a-z][a-z0-9+.-]*:[^\s]+$")
PATH_RE = re.compile(r"^[ -~]+$")

PLACEHOLDER_TOKENS = frozenset(
    {
        "tbd",
        "todo",
        "fixme",
        "xxx",
        "changeme",
        "change-me",
        "placeholder",
        "lorem ipsum",
    }
)

_FORMAT_CHECKS = {
    "digest": lambda v: bool(DIGEST_RE.match(v)),
    "commit": lambda v: bool(COMMIT_RE.match(v)),
    "timestamp": lambda v: _is_utc_timestamp(v),
    "id": lambda v: bool(ID_RE.match(v)),
    "uri": lambda v: bool(URI_RE.match(v)),
    "path": lambda v: _is_repo_path(v),
}


def _is_utc_timestamp(value: str) -> bool:
    if not TIMESTAMP_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _is_repo_path(value: str) -> bool:
    if not PATH_RE.match(value) or value.startswith("/"):
        return False
    if "\\" in value or "//" in value:
        return False
    return all(segment not in ("", ".", "..") for segment in value.split("/"))


def is_placeholder(value: str) -> bool:
    stripped = value.strip()
    if stripped.lower() in PLACEHOLDER_TOKENS:
        return True
    return len(stripped) >= 3 and stripped.startswith("<") and stripped.endswith(">")


class StrictJsonError(ValueError):
    """The JSON text violates strictness rules (duplicate keys, constants)."""


class SchemaError(ValueError):
    """A value does not conform to the gstrict schema."""


def _reject_constant(name: str) -> None:
    raise StrictJsonError(f"non-JSON constant {name!r} is not permitted")


def _pairs_no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    seen: set[str] = set()
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise StrictJsonError(f"duplicate object key {key!r}")
        seen.add(key)
        out[key] = value
    return out


def strict_loads(text: str) -> object:
    """Parse JSON, rejecting duplicate keys and non-JSON constants."""
    try:
        return json.loads(
            text,
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
            parse_float=_reject_float,
        )
    except json.JSONDecodeError as exc:
        raise StrictJsonError(f"invalid JSON: {exc}") from exc


def _reject_float(value: str) -> None:
    raise StrictJsonError(f"float literal {value!r} is not permitted")


def load_schema(document: object) -> object:
    """Validate a parsed gstrict schema document and return its root node."""
    if not isinstance(document, dict):
        raise SchemaError("schema document must be an object")
    if document.get("schema") != "gstrict-v1":
        raise SchemaError('schema document must declare "gstrict-v1"')
    if not isinstance(document.get("id"), str) or not document["id"]:
        raise SchemaError("schema document requires a nonempty id")
    if "root" not in document:
        raise SchemaError("schema document requires a root node")
    _check_node(document["root"], "$.root")
    return document["root"]


def _check_node(node: object, where: str) -> None:
    if not isinstance(node, dict):
        raise SchemaError(f"{where}: schema node must be an object")
    if "one_of" in node:
        branches = node["one_of"]
        if set(node) != {"one_of"}:
            raise SchemaError(f"{where}: one_of nodes take no other keys")
        if not isinstance(branches, list) or not branches:
            raise SchemaError(f"{where}: one_of requires a nonempty array")
        for index, branch in enumerate(branches):
            _check_node(branch, f"{where}.one_of[{index}]")
        return
    kind = node.get("type")
    if kind == "object":
        fields = node.get("fields")
        if not isinstance(fields, dict):
            raise SchemaError(f"{where}: object node requires fields")
        for name, sub in fields.items():
            if not isinstance(name, str):
                raise SchemaError(f"{where}: field names must be strings")
            _check_node(sub, f"{where}.fields.{name}")
        required = node.get("required", [])
        if not isinstance(required, list) or any(
            name not in fields for name in required
        ):
            raise SchemaError(f"{where}: required must name declared fields")
        if len(set(required)) != len(required):
            raise SchemaError(f"{where}: duplicate names in required")
        unknown = set(node) - {"type", "fields", "required"}
    elif kind == "array":
        if "items" not in node:
            raise SchemaError(f"{where}: array node requires items")
        _check_node(node["items"], f"{where}.items")
        unknown = set(node) - {
            "type",
            "items",
            "min_items",
            "max_items",
            "unique_items",
        }
    elif kind == "string":
        fmt = node.get("format")
        if fmt is not None and fmt not in _FORMAT_CHECKS:
            raise SchemaError(f"{where}: unknown string format {fmt!r}")
        unknown = set(node) - {
            "type",
            "enum",
            "pattern",
            "min_length",
            "max_length",
            "format",
        }
    elif kind == "integer":
        unknown = set(node) - {"type", "minimum", "maximum"}
    elif kind in ("boolean", "null"):
        unknown = set(node) - {"type"}
    else:
        raise SchemaError(f"{where}: unknown node type {kind!r}")
    if unknown:
        raise SchemaError(f"{where}: unknown schema keys {sorted(unknown)}")


def validate(value: object, node: object, where: str = "$") -> list[str]:
    """Validate *value* against a schema node; return a list of problems."""
    if "one_of" in node:
        matches = [
            branch for branch in node["one_of"] if not validate(value, branch, where)
        ]
        if len(matches) != 1:
            return [f"{where}: expected exactly one matching branch"]
        return []
    kind = node["type"]
    if kind == "object":
        return _validate_object(value, node, where)
    if kind == "array":
        return _validate_array(value, node, where)
    if kind == "string":
        return _validate_string(value, node, where)
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return [f"{where}: expected integer"]
        problems = []
        if "minimum" in node and value < node["minimum"]:
            problems.append(f"{where}: below minimum {node['minimum']}")
        if "maximum" in node and value > node["maximum"]:
            problems.append(f"{where}: above maximum {node['maximum']}")
        return problems
    if kind == "boolean":
        if not isinstance(value, bool):
            return [f"{where}: expected boolean"]
        return []
    if kind == "null":
        if value is not None:
            return [f"{where}: expected null"]
        return []
    raise SchemaError(f"{where}: unknown node type {kind!r}")


def _validate_object(value: object, node: dict, where: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{where}: expected object"]
    problems = []
    fields = node["fields"]
    for name in node.get("required", []):
        if name not in value:
            problems.append(f"{where}: missing required field {name!r}")
    for name, sub in value.items():
        if name not in fields:
            problems.append(f"{where}: unknown field {name!r}")
        else:
            problems.extend(validate(sub, fields[name], f"{where}.{name}"))
    return problems


def _validate_array(value: object, node: dict, where: str) -> list[str]:
    if not isinstance(value, list):
        return [f"{where}: expected array"]
    problems = []
    if "min_items" in node and len(value) < node["min_items"]:
        problems.append(f"{where}: fewer than {node['min_items']} items")
    if "max_items" in node and len(value) > node["max_items"]:
        problems.append(f"{where}: more than {node['max_items']} items")
    if node.get("unique_items"):
        seen: set[str] = set()
        for item in value:
            marker = json.dumps(item, sort_keys=True, default=str)
            if marker in seen:
                problems.append(f"{where}: duplicate array item")
                break
            seen.add(marker)
    for index, item in enumerate(value):
        problems.extend(validate(item, node["items"], f"{where}[{index}]"))
    return problems


def _validate_string(value: object, node: dict, where: str) -> list[str]:
    if not isinstance(value, str):
        return [f"{where}: expected string"]
    if is_placeholder(value):
        return [f"{where}: placeholder value is not permitted"]
    problems = []
    if "enum" in node and value not in node["enum"]:
        problems.append(f"{where}: not one of {node['enum']}")
    if "min_length" in node and len(value) < node["min_length"]:
        problems.append(f"{where}: shorter than {node['min_length']}")
    if "max_length" in node and len(value) > node["max_length"]:
        problems.append(f"{where}: longer than {node['max_length']}")
    if "pattern" in node and not re.search(node["pattern"], value):
        problems.append(f"{where}: does not match pattern {node['pattern']}")
    if "format" in node and not _FORMAT_CHECKS[node["format"]](value):
        problems.append(f"{where}: invalid {node['format']} format")
    return problems
