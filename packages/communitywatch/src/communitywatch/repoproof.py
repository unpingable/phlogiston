"""Independent ATProto repository proof verification (OQ-2, answer A).

Everything in this module treats fetched bytes as hostile until every check
passes: each CAR block hash must match its CID, the commit signature must
verify against the current DID document key, and the Merkle Search Tree path
from the signed commit root must prove membership (or non-membership) of the
exact ``collection/rkey`` key.  Repository revision and order come only from
the signed commit, never from a relay envelope.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from community_model import ValidationError, decode_dag_cbor, encode_dag_cbor
from community_model.identifiers import validate_did, validate_nsid, validate_tid

from .secp256k1 import verify_signature

_SECP256K1_PUB_MULTICODEC = b"\xe7\x01"
_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


class ProofError(ValueError):
    """Retained proof material is malformed or fails a cryptographic check."""


@dataclass(frozen=True, slots=True)
class CarArchive:
    """One parsed CARv1 with every block hash already verified."""

    roots: tuple[str, ...]
    blocks: Mapping[str, bytes]


@dataclass(frozen=True, slots=True)
class VerifiedCommit:
    """A signed commit whose signature verified against the DID document key."""

    did: str
    rev: str
    commit_cid: str
    data_root: str


@dataclass(frozen=True, slots=True)
class RecordProof:
    """The verified state of one repository key at one signed commit."""

    commit: VerifiedCommit
    present: bool
    record_cid: str | None
    record_bytes: bytes | None


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    for position in range(offset, len(data)):
        octet = data[position]
        value |= (octet & 0x7F) << shift
        if not octet & 0x80:
            if position > offset and octet == 0:
                raise ProofError("non-canonical varint in CAR framing")
            return value, position + 1
        shift += 7
        if shift > 63:
            break
    raise ProofError("truncated varint in CAR framing")


def cid_from_bytes(raw: bytes) -> str:
    """Render raw CIDv1 bytes as their canonical base32-lower string."""

    if len(raw) != 36 or raw[:4] != b"\x01\x71\x12\x20":
        raise ProofError("CAR block CID is not CIDv1/dag-cbor/sha2-256")
    return "b" + base64.b32encode(raw).decode("ascii").lower().rstrip("=")


def parse_car(data: bytes) -> CarArchive:
    """Parse one CARv1 and verify every block hash against its CID."""

    if not isinstance(data, bytes) or not data:
        raise ProofError("CAR evidence must be nonempty bytes")
    try:
        header_length, cursor = _read_varint(data, 0)
        header = decode_dag_cbor(data[cursor : cursor + header_length])
    except (ValidationError, ProofError) as exc:
        raise ProofError(f"CAR header is not valid DAG-CBOR: {exc}") from exc
    cursor += header_length
    if (
        not isinstance(header, dict)
        or header.get("version") != 1
        or not isinstance(header.get("roots"), tuple)
        or not all(
            isinstance(root, dict) and set(root) == {"$link"}
            for root in header["roots"]
        )
        or set(header) - {"version", "roots"}
    ):
        raise ProofError("CAR header must be exactly {version: 1, roots: [CID...]}")
    roots = tuple(str(root["$link"]) for root in header["roots"])
    blocks: dict[str, bytes] = {}
    while cursor < len(data):
        block_length, cursor = _read_varint(data, cursor)
        end = cursor + block_length
        if end > len(data):
            raise ProofError("truncated CAR block")
        cid_raw = data[cursor : cursor + 36]
        cid = cid_from_bytes(cid_raw)
        payload = data[cursor + 36 : end]
        if hashlib.sha256(payload).digest() != cid_raw[4:]:
            raise ProofError("CAR block hash does not match its CID")
        if cid in blocks:
            raise ProofError("CAR contains a duplicate block")
        blocks[cid] = payload
        cursor = end
    return CarArchive(roots=roots, blocks=blocks)


def key_depth(key: bytes) -> int:
    """Return the ATProto MST depth: leading zero 2-bit groups of sha256."""

    digest = hashlib.sha256(key).digest()
    depth = 0
    for octet in digest:
        for shift in (6, 4, 2, 0):
            if (octet >> shift) & 0x03:
                return depth
            depth += 1
    return depth


def _link(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"$link"}:
        raise ProofError(f"MST {field} is not a CID link")
    return str(value["$link"])


def _decode_node(
    block: bytes,
) -> tuple[str | None, list[tuple[bytes, str, str | None]]]:
    """Decode one MST node to (left link, [(full key, value, tree link)])."""

    try:
        node = decode_dag_cbor(block)
    except ValidationError as exc:
        raise ProofError(f"MST node is not valid DAG-CBOR: {exc}") from exc
    if (
        not isinstance(node, dict)
        or set(node) - {"l", "e"}
        or not isinstance(node.get("e"), tuple)
    ):
        raise ProofError("MST node must be a map with an entry list")
    left = _link(node.get("l"), field="left link")
    entries: list[tuple[bytes, str, str | None]] = []
    previous = b""
    for raw_entry in node["e"]:
        if not isinstance(raw_entry, dict) or set(raw_entry) - {"p", "k", "v", "t"}:
            raise ProofError("MST entry must use p/k/v/t fields")
        prefix = raw_entry.get("p")
        suffix = raw_entry.get("k")
        if (
            not isinstance(prefix, int)
            or isinstance(prefix, bool)
            or prefix < 0
            or not isinstance(suffix, bytes)
        ):
            raise ProofError("MST entry prefix/suffix are malformed")
        if prefix > len(previous):
            raise ProofError("MST entry prefix exceeds the previous key")
        key = previous[:prefix] + suffix
        value = _link(raw_entry.get("v"), field="entry value")
        if value is None:
            raise ProofError("MST entry value link is required")
        entries.append((key, value, _link(raw_entry.get("t"), field="entry tree")))
        previous = key
    keys = [key for key, _, _ in entries]
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        raise ProofError("MST entries are not strictly ordered")
    if entries:
        depth = key_depth(entries[0][0])
        if any(key_depth(key) != depth for key, _, _ in entries[1:]):
            raise ProofError("MST node mixes entry depths")
    return left, entries


def mst_lookup(blocks: Mapping[str, bytes], root_cid: str, key: bytes) -> str | None:
    """Return the proven value CID for *key*, or ``None`` when proven absent.

    Raises :class:`ProofError` when the retained blocks cannot prove either
    (structurally invalid tree, or a needed proof node is missing).
    """

    target_depth = key_depth(key)
    current = root_cid
    parent_depth: int | None = None
    visited: set[str] = set()
    while True:
        if current in visited:
            raise ProofError("MST proof contains a node cycle")
        visited.add(current)
        block = blocks.get(current)
        if block is None:
            raise ProofError("proof is missing a needed MST node")
        left, entries = _decode_node(block)
        if not entries:
            if left is None:
                # An empty leaf is legal only as the root of an empty tree.
                if parent_depth is not None:
                    raise ProofError("empty leaf nodes are pruned from the tree")
                return None
            if parent_depth is None:
                # An empty root pointing at a subtree must be pruned.
                raise ProofError("the tree top must not be an empty node")
            # Spec-legal empty intermediate node: it must point to a
            # sub-tree containing entries, so the lookup descends; an empty
            # leaf at the bottom is rejected by the branch above.
            current = left
            continue
        depth = key_depth(entries[0][0])
        if parent_depth is not None and depth >= parent_depth:
            raise ProofError("MST depths do not strictly decrease down the tree")
        for entry_key, value, _ in entries:
            if entry_key == key:
                if depth != target_depth:
                    raise ProofError("MST entry sits at the wrong depth")
                return value
        if depth <= target_depth:
            # The node covering the key at its own depth lacks it: absent.
            return None
        if key < entries[0][0]:
            child = left
        elif key > entries[-1][0]:
            child = entries[-1][2]
        else:
            child = None
            for index in range(len(entries) - 1):
                if entries[index][0] < key < entries[index + 1][0]:
                    child = entries[index][2]
                    break
        if child is None:
            return None
        parent_depth = depth
        current = child


def verify_commit(
    archive: CarArchive, *, repo_did: str, public_key: bytes
) -> VerifiedCommit:
    """Verify the CAR root commit signature and return its signed coordinates."""

    if len(archive.roots) != 1:
        raise ProofError("repository proof CAR must have exactly one root")
    commit_cid = archive.roots[0]
    block = archive.blocks.get(commit_cid)
    if block is None:
        raise ProofError("commit root block is missing from the CAR")
    try:
        commit = decode_dag_cbor(block)
    except ValidationError as exc:
        raise ProofError(f"commit block is not valid DAG-CBOR: {exc}") from exc
    if (
        not isinstance(commit, dict)
        or not {"did", "version", "data", "rev", "sig"} <= set(commit)
        or set(commit) - {"did", "version", "data", "rev", "sig", "prev"}
    ):
        raise ProofError("commit block fields do not match the repository schema")
    if commit["did"] != repo_did:
        raise ProofError("commit DID does not match the repository DID")
    if commit["version"] not in (2, 3) or isinstance(commit["version"], bool):
        raise ProofError("unsupported repository commit version")
    try:
        rev = validate_tid(commit["rev"])
    except ValidationError as exc:
        raise ProofError("commit revision is not a valid TID") from exc
    data_root = _link(commit["data"], field="commit data root")
    if data_root is None:
        raise ProofError("commit data root link is required")
    if data_root not in archive.blocks:
        raise ProofError("commit data root block is missing from the CAR")
    signature = commit["sig"]
    if not isinstance(signature, bytes) or len(signature) != 64:
        raise ProofError("commit signature must be 64 compact bytes")
    unsigned = {key: value for key, value in commit.items() if key != "sig"}
    digest = hashlib.sha256(encode_dag_cbor(unsigned)).digest()
    if not verify_signature(public_key, digest, signature):
        raise ProofError("commit signature does not verify against the DID key")
    return VerifiedCommit(
        did=repo_did, rev=rev, commit_cid=commit_cid, data_root=data_root
    )


def verify_record_proof(
    car_bytes: bytes,
    *,
    repo_did: str,
    collection: str,
    rkey: str,
    public_key: bytes,
) -> RecordProof:
    """Verify one getRecord/getRepo CAR for an exact repository key.

    The returned revision always comes from the verified signed commit.  A
    proof whose commit revision is newer than the triggering stream event
    establishes only the current repository state; callers must apply the
    OQ-2 later-revision rule and must not present it as authentication of
    that historical event.
    """

    archive = parse_car(car_bytes)
    commit = verify_commit(archive, repo_did=repo_did, public_key=public_key)
    key = f"{validate_nsid(collection)}/{rkey}".encode("utf-8")
    record_cid = mst_lookup(archive.blocks, commit.data_root, key)
    if record_cid is None:
        return RecordProof(
            commit=commit, present=False, record_cid=None, record_bytes=None
        )
    record_bytes = archive.blocks.get(record_cid)
    if record_bytes is None:
        raise ProofError("proven record block is missing from the CAR")
    return RecordProof(
        commit=commit,
        present=True,
        record_cid=record_cid,
        record_bytes=record_bytes,
    )


def _base58btc_decode(text: str) -> bytes:
    value = 0
    for character in text:
        index = _B58_ALPHABET.find(character)
        if index < 0:
            raise ProofError("invalid base58btc character in multibase key")
        value = value * 58 + index
    leading = len(text) - len(text.lstrip("1"))
    if value == 0:
        return b"\x00" * leading
    body = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return b"\x00" * leading + body


def extract_verification_key(did_document: object) -> bytes:
    """Extract the repo secp256k1 key from a DID document (``#atproto`` first)."""

    if not isinstance(did_document, Mapping):
        raise ProofError("DID document must be an object")
    methods = did_document.get("verificationMethod")
    if not isinstance(methods, list | tuple):
        raise ProofError("DID document has no verification methods")
    candidates: list[Mapping[str, object]] = []
    for method in methods:
        if isinstance(method, Mapping):
            candidates.append(method)
    candidates.sort(
        key=lambda item: 0 if str(item.get("id", "")).endswith("#atproto") else 1
    )
    for method in candidates:
        multibase = method.get("publicKeyMultibase")
        if not isinstance(multibase, str) or not multibase.startswith("z"):
            continue
        raw = _base58btc_decode(multibase[1:])
        if raw.startswith(_SECP256K1_PUB_MULTICODEC) and len(raw) == 35:
            return raw[2:]
    raise ProofError("DID document has no secp256k1 verification key")


def extract_pds_endpoint(did_document: object) -> str:
    """Extract the AtprotoPersonalDataServer service endpoint URL."""

    if not isinstance(did_document, Mapping):
        raise ProofError("DID document must be an object")
    services = did_document.get("service")
    if not isinstance(services, list | tuple):
        raise ProofError("DID document has no service entries")
    for service in services:
        if not isinstance(service, Mapping):
            continue
        if (
            service.get("id") == "#atproto_pds"
            or service.get("type") == "AtprotoPersonalDataServer"
        ):
            endpoint = service.get("serviceEndpoint")
            if isinstance(endpoint, str) and endpoint.startswith(
                ("https://", "http://")
            ):
                return endpoint.rstrip("/")
    raise ProofError("DID document has no PDS service endpoint")


def validate_repo_did(value: str) -> str:
    try:
        return validate_did(value)
    except ValidationError as exc:
        raise ProofError("repository DID is invalid") from exc


__all__ = [
    "CarArchive",
    "ProofError",
    "RecordProof",
    "VerifiedCommit",
    "extract_pds_endpoint",
    "extract_verification_key",
    "key_depth",
    "mst_lookup",
    "parse_car",
    "validate_repo_did",
    "verify_commit",
    "verify_record_proof",
]
