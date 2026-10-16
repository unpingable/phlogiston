"""Offline repository/stream fixtures for the M6 observer-ingestion tests.

Everything here runs without a network: fixture repositories are built
programmatically (pure-Python secp256k1 *signing* lives only in this test
helper — the product package verifies and can never sign), fake PDS/PLC
answers come from a loopback HTTP server, and the fake Jetstream endpoint is
a loopback WebSocket server.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import socket
import threading
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from community_model import cid_for_dag_cbor, encode_dag_cbor
from community_model.identifiers import decode_cid
from communitywatch.repoproof import key_depth
from communitywatch.websocket import OP_CLOSE, OP_TEXT, send_frame

_FIELD = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)
_TID_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"
_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# --- test-side secp256k1 signing (never in product code) ---------------------


def _add(left, right):
    if left is None:
        return right
    if right is None:
        return left
    x1, y1 = left
    x2, y2 = right
    if x1 == x2 and (y1 != y2 or y1 == 0):
        return None
    if left == right:
        slope = (3 * x1 * x1) * pow(2 * y1, -1, _FIELD) % _FIELD
    else:
        slope = (y2 - y1) * pow(x2 - x1, -1, _FIELD) % _FIELD
    x3 = (slope * slope - x1 - x2) % _FIELD
    return x3, (slope * (x1 - x3) - y1) % _FIELD


def _multiply(scalar: int, point):
    result = None
    addend = point
    while scalar:
        if scalar & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)
        scalar >>= 1
    return result


def public_key_bytes(private: int) -> bytes:
    """Compressed public key for a fixture private scalar."""

    x, y = _multiply(private, _G)
    return (b"\x03" if y & 1 else b"\x02") + x.to_bytes(32, "big")


def _rfc6979_nonce(private: int, digest: bytes) -> int:
    bx = private.to_bytes(32, "big")
    v = b"\x01" * 32
    k = b"\x00" * 32
    k = hmac.new(k, v + b"\x00" + bx + digest, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + bx + digest, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        candidate = int.from_bytes(v, "big")
        if 1 <= candidate < _ORDER:
            return candidate
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


def sign_digest(private: int, digest: bytes) -> bytes:
    """Deterministic low-S compact ECDSA signature for fixture commits."""

    while True:
        nonce = _rfc6979_nonce(private, digest)
        point = _multiply(nonce, _G)
        r = point[0] % _ORDER
        s = (
            pow(nonce, -1, _ORDER) * (int.from_bytes(digest, "big") + r * private)
        ) % _ORDER
        if r and s:
            break
        digest = hashlib.sha256(digest).digest()
    if s > _ORDER // 2:
        s = _ORDER - s
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def multibase_key(private: int) -> str:
    """The publicKeyMultibase form of a fixture key (base58btc multicodec)."""

    raw = b"\xe7\x01" + public_key_bytes(private)
    value = int.from_bytes(raw, "big")
    digits = ""
    while value:
        digits = _B58_ALPHABET[value % 58] + digits
        value //= 58
    leading = len(raw) - len(raw.lstrip(b"\x00"))
    return "z" + "1" * leading + digits


def mint_tid(sequence: int) -> str:
    digits = ""
    value = sequence
    while True:
        digits = _TID_ALPHABET[value % 32] + digits
        value //= 32
        if not value:
            break
    return digits.rjust(13, "2")


# --- repository fixtures ------------------------------------------------------


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        octet = value & 0x7F
        value >>= 7
        if value:
            out.append(octet | 0x80)
        else:
            out.append(octet)
            return bytes(out)


def build_car(root_cid: str, blocks: Mapping[str, bytes]) -> bytes:
    header = encode_dag_cbor({"version": 1, "roots": [{"$link": root_cid}]})
    out = bytearray(_varint(len(header)) + header)
    for cid, data in blocks.items():
        raw = decode_cid(cid)
        out += _varint(len(raw) + len(data)) + raw + data
    return bytes(out)


def _build_mst(items: list[tuple[bytes, str]], blocks: dict[str, bytes]) -> str:
    """Build one correct MST over sorted (key, value CID) items."""

    if not items:
        raise ValueError("empty subtree")
    depth = max(key_depth(key) for key, _ in items)
    tops: list[tuple[bytes, str]] = []
    segments: list[list[tuple[bytes, str]]] = [[]]
    for key, cid in items:
        if key_depth(key) == depth:
            tops.append((key, cid))
            segments.append([])
        else:
            segments[-1].append((key, cid))
    entries = []
    previous = b""
    for index, (key, cid) in enumerate(tops):
        child = None
        if segments[index + 1]:
            child = _build_mst(segments[index + 1], blocks)
        prefix = 0
        while (
            prefix < len(previous)
            and prefix < len(key)
            and previous[prefix] == key[prefix]
        ):
            prefix += 1
        entries.append(
            {
                "p": prefix,
                "k": key[prefix:],
                "v": {"$link": cid},
                "t": None if child is None else {"$link": child},
            }
        )
        previous = key
    left = _build_mst(segments[0], blocks) if segments[0] else None
    node = {"l": None if left is None else {"$link": left}, "e": entries}
    data = encode_dag_cbor(node)
    cid = cid_for_dag_cbor(data)
    blocks[cid] = data
    return cid


def _mst_path(blocks: Mapping[str, bytes], root: str, key: bytes) -> set[str]:
    """Collect the proof-path node CIDs a getRecord CAR must carry."""

    from community_model import decode_dag_cbor

    path: set[str] = set()
    current: str | None = root
    while current is not None:
        path.add(current)
        node = decode_dag_cbor(blocks[current])
        assert isinstance(node, dict)
        left_link = node.get("l")
        left = left_link["$link"] if isinstance(left_link, dict) else None
        entries: list[tuple[bytes, str | None]] = []
        previous = b""
        for entry in node["e"]:
            full = previous[: entry["p"]] + entry["k"]
            tree_link = entry.get("t")
            entries.append(
                (full, tree_link["$link"] if isinstance(tree_link, dict) else None)
            )
            previous = full
        if not entries:
            return path
        if any(full == key for full, _ in entries):
            return path
        target: str | None
        if key < entries[0][0]:
            target = left
        elif key > entries[-1][0]:
            target = entries[-1][1]
        else:
            target = None
            for index in range(len(entries) - 1):
                if entries[index][0] < key < entries[index + 1][0]:
                    target = entries[index][1]
                    break
        current = target
    return path


class FixtureRepo:
    """One small signed repository with correct MST/CAR material."""

    def __init__(self, did: str, private: int) -> None:
        self.did = did
        self.private = private
        self.records: dict[tuple[str, str], dict[str, object]] = {}
        self.rev = 0

    @property
    def public_key(self) -> bytes:
        return public_key_bytes(self.private)

    def put(self, collection: str, rkey: str, record: dict[str, object]) -> str:
        self.records[(collection, rkey)] = record
        self.rev += 1
        return self.current_rev

    def delete(self, collection: str, rkey: str) -> str:
        del self.records[(collection, rkey)]
        self.rev += 1
        return self.current_rev

    @property
    def current_rev(self) -> str:
        return mint_tid(self.rev)

    def record_cid(self, collection: str, rkey: str) -> str:
        return cid_for_dag_cbor(encode_dag_cbor(self.records[(collection, rkey)]))

    def _commit(
        self, sign_with: int | None = None
    ) -> tuple[str, dict[str, bytes], str]:
        blocks: dict[str, bytes] = {}
        entries = []
        for (collection, rkey), record in self.records.items():
            data = encode_dag_cbor(record)
            cid = cid_for_dag_cbor(data)
            blocks[cid] = data
            entries.append((f"{collection}/{rkey}".encode(), cid))
        entries.sort()
        if entries:
            root = _build_mst(entries, blocks)
        else:
            root = cid_for_dag_cbor(encode_dag_cbor({"l": None, "e": []}))
            blocks[root] = encode_dag_cbor({"l": None, "e": []})
        unsigned = {
            "data": {"$link": root},
            "did": self.did,
            "prev": None,
            "rev": self.current_rev,
            "version": 3,
        }
        digest = hashlib.sha256(encode_dag_cbor(unsigned)).digest()
        commit = {**unsigned, "sig": sign_digest(sign_with or self.private, digest)}
        commit_block = encode_dag_cbor(commit)
        commit_cid = cid_for_dag_cbor(commit_block)
        blocks[commit_cid] = commit_block
        return commit_cid, blocks, root

    def repo_car(self, sign_with: int | None = None) -> bytes:
        commit_cid, blocks, _ = self._commit(sign_with)
        return build_car(commit_cid, blocks)

    def record_car(
        self, collection: str, rkey: str, sign_with: int | None = None
    ) -> bytes:
        """A getRecord-shaped CAR: commit, proof-path nodes, record block."""

        commit_cid, blocks, root = self._commit(sign_with)
        key = f"{collection}/{rkey}".encode()
        record_cid = cid_for_dag_cbor(encode_dag_cbor(self.records[(collection, rkey)]))
        keep = _mst_path(blocks, root, key)
        selected = {
            cid: data
            for cid, data in blocks.items()
            if cid in keep or cid in {commit_cid, record_cid}
        }
        return build_car(commit_cid, selected)

    def did_document(self, pds_url: str) -> dict[str, object]:
        return {
            "@context": [
                "https://www.w3.org/ns/did/v1",
                "https://w3id.org/security/multikey/v1",
            ],
            "id": self.did,
            "verificationMethod": [
                {
                    "id": f"{self.did}#atproto",
                    "type": "Multikey",
                    "controller": self.did,
                    "publicKeyMultibase": multibase_key(self.private),
                }
            ],
            "service": [
                {
                    "id": "#atproto_pds",
                    "type": "AtprotoPersonalDataServer",
                    "serviceEndpoint": pds_url,
                }
            ],
        }


# --- loopback fake servers ----------------------------------------------------


class FakeAtprotoServer:
    """One loopback HTTP server acting as both PLC directory and every PDS."""

    def __init__(
        self,
        repos: Mapping[str, FixtureRepo],
        sign_with: Mapping[str, int] | None = None,
    ) -> None:
        self.repos = dict(repos)
        self.sign_with = dict(sign_with or {})
        handler = self._make_handler()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def _make_handler(self):
        repos = self.repos
        sign_with = self.sign_with
        url_of = lambda: f"http://127.0.0.1:{self._server.server_port}"  # noqa: E731

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:
                pass

            def do_GET(self) -> None:  # noqa: N802
                parts = urlsplit(self.path)
                if parts.path == "/xrpc/com.atproto.sync.getRecord":
                    query = parse_qs(parts.query)
                    if "did" not in query:
                        # The real PDS rejects the legacy "repo" key.
                        self._reply(400, b'{"error":"InvalidRequest"}')
                        return
                    repo = repos.get(query["did"][0])
                    if repo is None:
                        self._reply(400, b'{"error":"RepoNotFound"}')
                        return
                    collection = query["collection"][0]
                    rkey = query["rkey"][0]
                    if (collection, rkey) not in repo.records:
                        self._reply(400, b'{"error":"RecordNotFound"}')
                        return
                    self._reply(
                        200,
                        repo.record_car(
                            collection, rkey, sign_with=sign_with.get(repo.did)
                        ),
                    )
                    return
                if parts.path == "/xrpc/com.atproto.sync.getRepo":
                    query = parse_qs(parts.query)
                    if "did" not in query:
                        self._reply(400, b'{"error":"InvalidRequest"}')
                        return
                    repo = repos.get(query["did"][0])
                    if repo is None:
                        self._reply(400, b'{"error":"RepoNotFound"}')
                        return
                    self._reply(200, repo.repo_car(sign_with=sign_with.get(repo.did)))
                    return
                did = parts.path.lstrip("/")
                repo = repos.get(did)
                if repo is not None:
                    self._reply(
                        200,
                        json.dumps(repo.did_document(url_of())).encode(),
                    )
                    return
                self._reply(404, b'{"error":"NotFound"}')

            def _reply(self, status: int, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler


class FakeJetstreamServer:
    """One loopback WebSocket server replaying pinned Jetstream v2 events."""

    def __init__(self, events: list[dict[str, object] | bytes]) -> None:
        self.events = list(events)
        self.request_paths: list[str] = []
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(8)
        self._listener.settimeout(10)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self._listener.getsockname()[1]}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._listener.close()
        self._thread.join(timeout=5)

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _ = self._listener.accept()
            except OSError:
                return
            try:
                self._handle(connection)
            except OSError:
                pass
            finally:
                try:
                    connection.close()
                except OSError:
                    pass

    def _handle(self, connection: socket.socket) -> None:
        connection.settimeout(10)
        request = b""
        while b"\r\n\r\n" not in request:
            chunk = connection.recv(4096)
            if not chunk:
                return
            request += chunk
        head = request.split(b"\r\n\r\n", 1)[0].decode("latin-1")
        lines = head.split("\r\n")
        self.request_paths.append(lines[0].split(" ", 2)[1])
        key = ""
        for line in lines[1:]:
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
        accept = base64.b64encode(
            hashlib.sha1((key + _WS_GUID).encode()).digest()
        ).decode()
        connection.sendall(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n"
                "\r\n"
            ).encode()
        )
        floor = 0
        query = parse_qs(urlsplit(self.request_paths[-1]).query)
        if "cursor" in query:
            floor = int(query["cursor"][0])
        for event in self.events:
            if isinstance(event, dict):
                payload = event.get("payload")
                seq = (
                    payload.get("seq")
                    if isinstance(payload, dict)
                    else event.get("seq")
                )
                if isinstance(seq, int) and seq < floor:
                    continue
                payload_bytes = json.dumps(event).encode()
            else:
                payload_bytes = event
            send_frame(connection, OP_TEXT, payload_bytes, mask=False)
        # Keep the connection briefly open, then close: the client's read
        # loop ends cleanly on the close frame.
        try:
            connection.settimeout(0.5)
            connection.recv(4096)
        except OSError:
            pass
        try:
            send_frame(connection, OP_CLOSE, mask=False)
        except OSError:
            pass
