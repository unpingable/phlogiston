"""Versioned deterministic encodings and identity hashes for V0."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from collections.abc import Mapping
from enum import Enum

from .constants import PayloadHashScope, RepositoryOperation
from .errors import ValidationError
from .identifiers import (
    parse_at_uri,
    validate_cid,
    validate_did,
    validate_nsid,
    validate_rkey,
    validate_tid,
)
from .values import RecordRef

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _without_nul(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValidationError(
            "schema_invalid", f"{name} must be a nonempty NUL-free string"
        )
    return value


def sha256_digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def member_action_rkey(subject_did: str, action: str) -> str:
    """Bind the one-way V0 membership transition to subject and verb."""

    validate_did(subject_did)
    if action not in {"add", "remove"}:
        raise ValidationError("unsupported_action", "membership action is unsupported")
    return hashlib.sha256(
        b"member-action-v1\x00" + subject_did.encode() + b"\x00" + action.encode()
    ).hexdigest()


def validate_sha256(value: object) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValidationError(
            "payload_evidence_invalid", "expected sha256:<lowercase hex>"
        )
    return value


def _json_value(value: object, *, path: tuple[str | int, ...] = ()) -> object:
    if isinstance(value, Enum):
        return _json_value(value.value, path=path)
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValidationError(
                "payload_evidence_invalid",
                "non-finite numbers are not valid observer JSON",
                path=path,
            )
        return value
    if isinstance(value, list | tuple):
        return [
            _json_value(item, path=path + (index,)) for index, item in enumerate(value)
        ]
    if isinstance(value, set | frozenset):
        raise ValidationError(
            "payload_evidence_invalid",
            "sets are not valid observer JSON arrays",
            path=path,
        )
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValidationError(
                    "payload_evidence_invalid",
                    "observer JSON object keys must be strings",
                    path=path,
                )
            normalized[key] = _json_value(item, path=path + (key,))
        return normalized
    if isinstance(value, bytes):
        raise ValidationError(
            "payload_evidence_invalid", "bytes are not valid observer JSON", path=path
        )
    raise ValidationError(
        "payload_evidence_invalid",
        f"{type(value).__name__} is not valid observer JSON",
        path=path,
    )


def canonical_json_bytes(value: object) -> bytes:
    """Encode the explicitly scoped V0 JSON form.

    This is deterministic Python JSON evidence, not DAG-CBOR and not an
    authority signature or record CID.
    """

    try:
        rendered = json.dumps(
            _json_value(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return rendered.encode("utf-8")
    except ValidationError:
        raise
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ValidationError(
            "payload_evidence_invalid", "value is outside canonical V0 JSON"
        ) from exc


def payload_hash(scope: PayloadHashScope | str, value: object) -> str:
    try:
        normalized_scope = PayloadHashScope(scope)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "payload_evidence_invalid", "unsupported payload hash scope"
        ) from exc
    if normalized_scope is PayloadHashScope.DAG_CBOR:
        if not isinstance(value, bytes | bytearray | memoryview):
            raise ValidationError(
                "payload_evidence_invalid", "dag_cbor evidence must be bytes"
            )
        encoded = bytes(value)
    elif isinstance(value, Mapping) or isinstance(value, list | tuple):
        encoded = canonical_json_bytes(value)
    else:
        raise ValidationError(
            "payload_evidence_invalid", "JSON evidence must be a mapping or sequence"
        )
    return sha256_digest(encoded)


def semantic_event_key(
    *,
    repo_did: str,
    commit_identity: str,
    collection: str,
    rkey: str,
    operation: RepositoryOperation | str,
) -> str:
    validate_did(repo_did)
    if not commit_identity.startswith("rev:"):
        raise ValidationError(
            "commit_revision_invalid", "commit identity must use the rev: scope"
        )
    _without_nul("commit_identity", commit_identity)
    validate_tid(commit_identity.removeprefix("rev:"))
    validate_nsid(collection)
    validate_rkey(rkey)
    try:
        normalized_operation = RepositoryOperation(operation)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "schema_invalid", "unsupported repository operation"
        ) from exc
    fields = (
        "v0",
        repo_did,
        commit_identity,
        collection,
        rkey,
        normalized_operation.value,
    )
    return sha256_digest("\x00".join(fields).encode("utf-8"))


def event_variant_key(
    *,
    semantic_event_key: str,
    record_cid: str | None,
    payload_hash_scope: PayloadHashScope | str,
    payload_hash: str,
) -> str:
    validate_sha256(semantic_event_key)
    if record_cid is not None:
        validate_cid(record_cid, require_dag_cbor=True)
    try:
        scope = PayloadHashScope(payload_hash_scope)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "payload_evidence_invalid", "unsupported payload hash scope"
        ) from exc
    validate_sha256(payload_hash)
    fields = (
        "v0",
        semantic_event_key,
        record_cid or "-",
        scope.value,
        payload_hash,
    )
    return sha256_digest("\x00".join(fields).encode("utf-8"))


def _authority_rkey(prefix: str, reference: RecordRef) -> str:
    material = f"v0\n{reference.uri}\n{reference.cid}".encode()
    return f"{prefix}-{hashlib.sha256(material).hexdigest()}"


def admission_rkey(submission: RecordRef) -> str:
    return _authority_rkey("admit", submission)


def removal_rkey(admission: RecordRef) -> str:
    return _authority_rkey("remove", admission)


def reply_policy_rkey(root_admission: RecordRef) -> str:
    """Bind exactly one immutable reply policy to a root admission."""

    return _authority_rkey("reply-policy", root_admission)


def reply_admission_rkey(submission: RecordRef) -> str:
    """Return the idempotent key for an exact author opt-in record."""

    return _authority_rkey("reply-admit", submission)


def reply_moderation_key(
    *, community_did: str, root_admission: RecordRef, reply_uri: str
) -> str:
    """Identify a logical community reply independently of its mutable CID."""

    validate_did(community_did)
    logical_reply = parse_at_uri(reply_uri, path=("reply_uri",))
    if logical_reply.collection != "app.bsky.feed.post":
        raise ValidationError(
            "subject_collection_invalid",
            "logical reply URI must identify a Bluesky post",
        )
    fields = (
        "pcv0-reply",
        community_did,
        root_admission.uri,
        root_admission.cid,
        reply_uri,
    )
    return sha256_digest("\x00".join(fields).encode("utf-8"))


def reply_action_rkey(
    *, action: str, moderation_key: str, previous_action: RecordRef | None = None
) -> str:
    """Return a deterministic append-only action key for one moderation chain."""

    if action not in {"remove", "restore"}:
        raise ValidationError(
            "unsupported_action", "reply action must remove or restore"
        )
    validate_sha256(moderation_key)
    previous = (
        "-"
        if previous_action is None
        else f"{previous_action.uri}\n{previous_action.cid}"
    )
    material = f"pcv0\n{action}\n{moderation_key}\n{previous}".encode()
    return f"reply-{action}-{hashlib.sha256(material).hexdigest()}"


def quarantine_audit_key(*, source: str, cursor: str, raw_envelope_hash: str) -> str:
    fields = (
        "v0",
        _without_nul("source", source),
        _without_nul("cursor", cursor),
        validate_sha256(raw_envelope_hash),
    )
    digest = hashlib.sha256("\x00".join(fields).encode()).hexdigest()
    return f"quarantine:{digest}"


def cid_for_dag_cbor(value: bytes) -> str:
    """Return the canonical CIDv1/dag-cbor/sha2-256 identifier for exact bytes."""

    if not isinstance(value, bytes):
        raise TypeError("DAG-CBOR evidence must be bytes")
    digest = hashlib.sha256(value).digest()
    cid_bytes = bytes((0x01, 0x71, 0x12, len(digest))) + digest
    return "b" + base64.b32encode(cid_bytes).decode("ascii").lower().rstrip("=")
