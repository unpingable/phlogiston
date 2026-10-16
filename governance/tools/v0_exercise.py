#!/usr/bin/env python3
"""Protected V0 controlled-live-exercise harness (controller-owned).

Usage::

    v0_exercise.py OPERATION_ID --packet READ_ONLY_PATH

``V0-X6-READ-SMOKE`` (bounded public reads, zero writes) and
``V0-X7-WRITE-SMOKE`` (bounded non-production writes in the single pinned
subject repository) are implemented. ``V0-X8-HUMAN-TRIAL`` is refused
cleanly as UNAUTHORIZED, as is any unrecognized operation.

X7 enforcement, beyond the shared skeleton:

- the credential is read from the JSON file named by the
  ``V0_X7_CREDENTIAL_REF`` environment variable before any socket use;
  the secret never enters logs, receipts, or retained artifacts (the
  staging tree is grep-checked for it before retention);
- writes 1-2 are direct ``createRecord`` calls at deterministic rkeys
  derived from the packet's ``idempotency_input``; writes 3-4 (the
  permanent admission/removal NSIDs pinned by the OQ-1 decision) go
  through the repository's ``communityd`` CLI as a subprocess;
- all subprocess XRPC is confined to an in-process loopback accounting
  proxy (``AccountingProxy``) that shares the single ExerciseContext
  request/byte budget: every communityd session, retry, readback, and
  write is checked against the ceiling before any upstream socket opens,
  so ``counters.requests`` is the authoritative exercise-wide total;
- an ambiguous write is never blind-retried: it is resolved by a
  deterministic-rkey readback (``com.atproto.repo.getRecord``) or the
  run stops with a failure receipt;
- the observer demonstration runs in capture-then-verify mode: the
  harness captures relay events and getRecord proofs under the packet
  ceilings, and the transition check runs offline over the captured
  artifacts (``communitywatch`` does its own unaccountable live I/O, so
  it is not invoked in the accounted path).

The harness is digest-pinned by the controller-entry packet
(``launch_payload.live_exercise.harness``): before any socket use it
recomputes the SHA-256 and byte length of its own module file and refuses
to run on mismatch. The pin covers this enforcement module;
``scripts/v0-exercise`` is a trivial exec shim.

Enforcement shape (contract "Controlled live exercises"):

- every origin contacted must exactly match a ``target_allow_list`` entry;
- every DID/repo and record collection seen on the wire must be pinned by
  ``subject_allow_list`` / ``allowed_record_kinds``;
- requests, bytes, events, proof fetches, and wall clock are bounded by
  ``ceilings``; transport failures are retried per ``retry`` and exhaustion
  stops the run with a failure receipt;
- under X6 the harness issues GET/subscribe only; ``counters.writes`` is
  enforced at zero (a write would be a harness bug, not a packet
  violation); under X7 writes are hard-capped at ``ceilings.max_writes``;
- proof fetches are capture-only: CAR bytes are stored verbatim and no
  cryptographic verification happens here (offline M6 code verifies the
  captured artifacts).

Artifacts are staged, then retained under the packet's
``evidence_policy.destination_uri`` (``file://`` only) in a run directory
named by ``receipt_id`` using ``evidence_store.write_tree`` readback
verification; readback failure downgrades the outcome to
ENVIRONMENT_BLOCKED. Retention itself (including the pinned
``retention.retain_artifacts`` behavior) is controller business; the
receipt states the pinned retention in its notes.

Cross-checking the receipt against the packet at admission time (targets a
subset of the allow-list, counters within ceilings, packet/harness digest
equality, receipt-schema pin) is controller business done at run time; it
is not repeated by the static receipt validator.

Exit codes: 0 PASS; 1 CHECK_FAILED/ENVIRONMENT_BLOCKED;
2 UNAUTHORIZED/CONTRACT_INVALID.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import http.server
import json
import os
import re
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import common  # noqa: E402
import evidence_store  # noqa: E402
import gstrict  # noqa: E402
import validators  # noqa: E402

KNOWN_OPERATIONS = (
    "V0-X6-READ-SMOKE",
    "V0-X7-WRITE-SMOKE",
    "V0-X8-HUMAN-TRIAL",
)
IMPLEMENTED_OPERATIONS = ("V0-X6-READ-SMOKE", "V0-X7-WRITE-SMOKE")

PROXY_VARS = (
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "all_proxy",
)

SUBSCRIBE_PATH = "/xrpc/network.bsky.jetstream.subscribeEvents"
GET_RECORD_PATH = "/xrpc/com.atproto.sync.getRecord"
CREATE_SESSION_PATH = "/xrpc/com.atproto.server.createSession"
CREATE_RECORD_PATH = "/xrpc/com.atproto.repo.createRecord"
REPO_GET_RECORD_PATH = "/xrpc/com.atproto.repo.getRecord"
LIST_RECORDS_PATH = "/xrpc/com.atproto.repo.listRecords"
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

PLC_DIRECTORY_ORIGIN = "https://plc.directory"

CREDENTIAL_ENV = "V0_X7_CREDENTIAL_REF"

# Permanent V0 NSIDs pinned by the OQ-1 decision (answer A, domain
# community.phlogiston.app); the X7 packet's allowed_record_kinds must pin
# every one of them plus the post collection.
POST_COLLECTION = "app.bsky.feed.post"
SUBMIT_COLLECTION = "app.phlogiston.community.submit"
ADMISSION_COLLECTION = "app.phlogiston.community.admission"
MOD_ACTION_COLLECTION = "app.phlogiston.community.modAction"
X7_RECORD_KINDS = (
    POST_COLLECTION,
    SUBMIT_COLLECTION,
    ADMISSION_COLLECTION,
    MOD_ACTION_COLLECTION,
)

OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

MEDIA_TYPES = {
    "events_ndjson": "application/x-ndjson",
    "request_log": "application/x-ndjson",
    "did_doc": "application/did+json",
    "proof_car": "application/vnd.ipld.car",
    "daemon_config": "application/toml",
    "projection_snapshot": "application/json",
    "cli_transcript": "application/json",
}


class PlanStop(Exception):
    """The read plan must stop now; carries the receipt outcome fields."""

    def __init__(self, stop_rule: str, notes: str, outcome: str = "CHECK_FAILED"):
        super().__init__(f"{stop_rule}: {notes}")
        self.stop_rule = stop_rule
        self.notes = notes
        self.outcome = outcome


class ByteBudgetExceeded(Exception):
    """A response body would exceed the packet's max_bytes ceiling."""


class EnvironmentBlocked(Exception):
    """Evidence write/readback failed; the store, not the plan, is at fault."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


# --- environment ------------------------------------------------------------


def scrub_environment(env: dict | None = None) -> dict:
    """Remove proxy variables so no request can be silently rerouted."""
    env = os.environ if env is None else env
    for name in PROXY_VARS:
        env.pop(name, None)
    return env


def minimal_child_env() -> dict:
    """The allow-listed environment for any child process (PATH/HOME/LANG)."""
    return {k: os.environ[k] for k in ("PATH", "HOME", "LANG") if k in os.environ}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)


# --- HTTP transport ---------------------------------------------------------


def http_get(
    origin: str, path: str, timeout: float, byte_budget: int, bearer: str | None = None
) -> tuple[int, bytes]:
    """GET ``path`` from an exact allow-listed ``origin``.

    Reads at most ``byte_budget`` body bytes; raises ByteBudgetExceeded when
    the body is larger. Transport errors surface as OSError/http.client
    exceptions for the retry layer.
    """
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    parts = urlsplit(origin)
    if parts.scheme == "https":
        conn = http.client.HTTPSConnection(parts.hostname, parts.port, timeout=timeout)
    else:
        conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=timeout)
    try:
        conn.request("GET", path, headers=headers)
        response = conn.getresponse()
        body = response.read(byte_budget + 1)
    finally:
        conn.close()
    if len(body) > byte_budget:
        raise ByteBudgetExceeded(f"response from {origin}{path} exceeds byte budget")
    return response.status, body


def http_post(
    origin: str,
    path: str,
    payload: bytes,
    timeout: float,
    byte_budget: int,
    bearer: str | None = None,
) -> tuple[int, bytes]:
    """POST a JSON body to an exact allow-listed ``origin``.

    Same budget and error surfacing as http_get. The request body is never
    logged or retained by the harness.
    """
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    parts = urlsplit(origin)
    if parts.scheme == "https":
        conn = http.client.HTTPSConnection(parts.hostname, parts.port, timeout=timeout)
    else:
        conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=timeout)
    try:
        conn.request("POST", path, body=payload, headers=headers)
        response = conn.getresponse()
        body = response.read(byte_budget + 1)
    finally:
        conn.close()
    if len(body) > byte_budget:
        raise ByteBudgetExceeded(f"response from {origin}{path} exceeds byte budget")
    return response.status, body


# --- WebSocket transport (minimal stdlib client) ----------------------------


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    chunks = []
    remaining = count
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise OSError("connection closed mid-frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def ws_send_frame(
    sock: socket.socket,
    opcode: int,
    payload: bytes = b"",
    mask: bool = True,
    fin: bool = True,
) -> None:
    """Send one WebSocket frame; clients must mask (RFC 6455 section 5.3)."""
    header = bytearray([(0x80 if fin else 0) | opcode])
    length = len(payload)
    mask_bit = 0x80 if mask else 0
    if length < 126:
        header.append(mask_bit | length)
    elif length < 65536:
        header.append(mask_bit | 126)
        header += struct.pack("!H", length)
    else:
        header.append(mask_bit | 127)
        header += struct.pack("!Q", length)
    if mask:
        key = os.urandom(4)
        header += key
        payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    sock.sendall(bytes(header) + payload)


class WallClockExceeded(Exception):
    """The packet's wall-clock deadline passed while reading the stream."""


def _recv_exact_deadline(
    sock: socket.socket, count: int, deadline: float | None
) -> bytes:
    """_recv_exact that can resume after inactivity timeouts.

    Partial chunks are kept across a timeout, so retrying is safe even
    mid-frame; between pings the deadline is re-checked every few seconds
    and WallClockExceeded is raised once it passes.
    """
    if deadline is None:
        return _recv_exact(sock, count)
    chunks = []
    remaining = count
    while remaining > 0:
        left = deadline - time.monotonic()
        if left <= 0:
            raise WallClockExceeded
        sock.settimeout(min(left, 5.0))
        try:
            chunk = sock.recv(remaining)
        except socket.timeout:
            continue
        if not chunk:
            raise OSError("connection closed mid-frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def ws_recv_frame(
    sock: socket.socket, deadline: float | None = None
) -> tuple[bool, int, bytes]:
    """Receive one WebSocket frame; returns (fin, opcode, unmasked payload)."""
    first, second = _recv_exact_deadline(sock, 2, deadline)
    fin = bool(first & 0x80)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        (length,) = struct.unpack("!H", _recv_exact_deadline(sock, 2, deadline))
    elif length == 127:
        (length,) = struct.unpack("!Q", _recv_exact_deadline(sock, 8, deadline))
    key = _recv_exact_deadline(sock, 4, deadline) if masked else b""
    payload = _recv_exact_deadline(sock, length, deadline) if length else b""
    if masked:
        payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    return fin, opcode, payload


def iter_ws_messages(sock: socket.socket, deadline: float | None = None):
    """Yield reassembled text/binary message payloads from *sock*.

    Ping frames are answered with pong; pong frames are ignored; a close
    frame is echoed and ends the iteration. When *deadline* is given it is
    enforced across control frames (pings no longer reset the wall clock).
    """
    fragments: list[bytes] = []
    while True:
        fin, opcode, payload = ws_recv_frame(sock, deadline)
        if opcode == OP_CLOSE:
            try:
                ws_send_frame(sock, OP_CLOSE, payload)
            except OSError:
                pass
            return
        if opcode == OP_PING:
            ws_send_frame(sock, OP_PONG, payload)
            continue
        if opcode == OP_PONG:
            continue
        if opcode in (OP_TEXT, OP_BINARY):
            fragments = [payload]
        elif opcode == OP_CONTINUATION and fragments:
            fragments.append(payload)
        else:
            continue
        if fin:
            yield b"".join(fragments)
            fragments = []


def _read_http_head(sock: socket.socket, limit: int = 65536) -> tuple[bytes, bytes]:
    """Read through the header terminator; returns (head, leftover bytes)."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise OSError("connection closed during websocket upgrade")
        data += chunk
        if len(data) > limit:
            raise OSError("websocket upgrade response too large")
    head, _, rest = data.partition(b"\r\n\r\n")
    return head + b"\r\n\r\n", rest


class _BufferedSocket:
    """Socket wrapper preserving bytes read past the upgrade headers."""

    def __init__(self, sock: socket.socket, buffered: bytes = b""):
        self._sock = sock
        self._buffer = bytearray(buffered)

    def recv(self, count: int) -> bytes:
        if self._buffer:
            data = bytes(self._buffer[:count])
            del self._buffer[:count]
            return data
        return self._sock.recv(count)

    def sendall(self, data: bytes) -> None:
        self._sock.sendall(data)

    def settimeout(self, value: float) -> None:
        self._sock.settimeout(value)

    def close(self) -> None:
        self._sock.close()


def ws_connect(origin: str, path: str, timeout: float) -> socket.socket:
    """Open a WebSocket to an exact allow-listed origin; returns the socket."""
    parts = urlsplit(origin)
    tls = parts.scheme == "wss"
    port = parts.port or (443 if tls else 80)
    sock = socket.create_connection((parts.hostname, port), timeout=timeout)
    if tls:
        context = ssl.create_default_context()
        sock = context.wrap_socket(sock, server_hostname=parts.hostname)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    host = parts.hostname if parts.port is None else f"{parts.hostname}:{port}"
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(request.encode("ascii"))
    response, rest = _read_http_head(sock)
    status_line = response.split(b"\r\n", 1)[0]
    if b" 101" not in status_line:
        sock.close()
        raise OSError(f"websocket upgrade refused: {status_line!r}")
    expected = base64.b64encode(hashlib.sha1((key + WS_GUID).encode("ascii")).digest())
    if expected.lower() not in response.lower():
        sock.close()
        raise OSError("websocket accept key mismatch")
    return _BufferedSocket(sock, rest)


# --- bounded read plan --------------------------------------------------------


def _zero_counters() -> dict:
    return {
        "requests": 0,
        "events": 0,
        "proof_fetches": 0,
        "bytes": 0,
        "writes": 0,
        "retries": 0,
    }


class ExerciseContext:
    """Holds the packet pins, counters, contacted targets, and wall clock."""

    def __init__(self, live: dict, started_monotonic: float):
        self.live = live
        self.ceilings = live["ceilings"]
        self.retry = live["retry"]
        self.counters = _zero_counters()
        self.targets_contacted: set[str] = set()
        self.deadline = started_monotonic + self.ceilings["max_wall_clock_seconds"]
        # One entry per counted request, harness- and proxy-originated
        # alike; paths only — bodies, headers, and bearer tokens are never
        # recorded, so the log is safe to retain as evidence.
        self.request_log: list[dict] = []

    def _open_request(
        self, source: str, kind: str, method: str, origin: str, path: str
    ) -> dict:
        """Append one counted-request log entry; the caller fills status."""
        entry = {
            "seq": len(self.request_log) + 1,
            "source": source,
            "kind": kind,
            "method": method,
            "origin": origin,
            "path": path,
        }
        self.request_log.append(entry)
        return entry

    def remaining_wall(self) -> float:
        return self.deadline - time.monotonic()

    def add_bytes(self, count: int) -> None:
        self.counters["bytes"] += count
        if self.counters["bytes"] > self.ceilings["max_bytes"]:
            raise PlanStop(
                "byte_ceiling_exceeded",
                f"max_bytes {self.ceilings['max_bytes']} exceeded",
            )

    def with_retries(self, fn):
        """Run *fn* with the packet's bounded retry policy."""
        attempts = 1 + self.retry["max_retries"]
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                return fn()
            except (OSError, http.client.HTTPException) as exc:
                last = exc
                if attempt + 1 < attempts:
                    self.counters["retries"] += 1
                    time.sleep(self.retry["retry_backoff_seconds"])
        raise PlanStop(
            "retry_exhausted",
            f"transport failure after {attempts} attempt(s): {last}",
        )

    def _count_request(self) -> None:
        if self.counters["requests"] >= self.ceilings["max_requests"]:
            raise PlanStop(
                "request_ceiling_exceeded",
                f"max_requests {self.ceilings['max_requests']} exceeded",
            )
        self.counters["requests"] += 1

    def begin_write(self) -> None:
        """Gate one write attempt on the packet's max_writes ceiling."""
        if self.counters["writes"] >= self.ceilings["max_writes"]:
            raise PlanStop(
                "write_ceiling_exceeded",
                f"max_writes {self.ceilings['max_writes']} exceeded",
            )

    def record_write(self) -> None:
        """Count one confirmed write (direct or resolved by readback)."""
        self.counters["writes"] += 1

    def counted_get(
        self, origin: str, path: str, bearer: str | None = None, *, kind: str = "read"
    ) -> tuple[int, bytes]:
        def attempt() -> tuple[int, bytes]:
            self._count_request()
            entry = self._open_request("harness", kind, "GET", origin, path)
            budget = self.ceilings["max_bytes"] - self.counters["bytes"]
            try:
                status, body = http_get(
                    origin, path, self.retry["request_timeout_seconds"], budget, bearer
                )
            except ByteBudgetExceeded as exc:
                entry["error"] = "byte_budget_exceeded"
                raise PlanStop("byte_ceiling_exceeded", str(exc)) from exc
            except (OSError, http.client.HTTPException):
                entry["error"] = "transport"
                raise
            entry["status"] = status
            entry["bytes"] = len(body)
            return status, body

        status, body = self.with_retries(attempt)
        self.targets_contacted.add(origin)
        self.add_bytes(len(body))
        return status, body

    def counted_post(
        self,
        origin: str,
        path: str,
        payload: dict,
        bearer: str | None = None,
        retry: bool = True,
        *,
        kind: str = "write",
    ) -> tuple[int, bytes]:
        """Counted JSON POST; transport errors raise unless ``retry`` is off.

        With ``retry=False`` (used for writes, which must never be
        blind-retried) a transport failure raises OSError/http.client
        exceptions to the caller, which resolves the ambiguity by readback.
        """
        body = json.dumps(payload).encode("utf-8")

        def attempt() -> tuple[int, bytes]:
            self._count_request()
            entry = self._open_request("harness", kind, "POST", origin, path)
            budget = self.ceilings["max_bytes"] - self.counters["bytes"]
            try:
                status, response = http_post(
                    origin,
                    path,
                    body,
                    self.retry["request_timeout_seconds"],
                    budget,
                    bearer,
                )
            except ByteBudgetExceeded as exc:
                entry["error"] = "byte_budget_exceeded"
                raise PlanStop("byte_ceiling_exceeded", str(exc)) from exc
            except (OSError, http.client.HTTPException):
                entry["error"] = "transport"
                raise
            entry["status"] = status
            entry["bytes"] = len(response)
            return status, response

        if retry:
            status, response = self.with_retries(attempt)
        else:
            status, response = attempt()
        self.targets_contacted.add(origin)
        self.add_bytes(len(response))
        return status, response

    def counted_ws_connect(self, origin: str, path: str) -> socket.socket:
        def attempt() -> socket.socket:
            self._count_request()
            entry = self._open_request("harness", "subscribe", "GET", origin, path)
            try:
                sock = ws_connect(origin, path, self.retry["request_timeout_seconds"])
            except OSError:
                entry["error"] = "transport"
                raise
            entry["status"] = 101
            return sock

        sock = self.with_retries(attempt)
        self.targets_contacted.add(origin)
        return sock


def origin_of(url: str) -> str | None:
    """Reduce an absolute URL to its exact ``scheme://host[:port]`` origin."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if not parts.scheme or not parts.hostname:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    netloc = parts.hostname if port is None else f"{parts.hostname}:{port}"
    return f"{parts.scheme}://{netloc}"


def _parse_did_doc(did: str, body: bytes) -> dict:
    try:
        doc = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PlanStop("did_doc_invalid", f"{did}: DID document is not JSON: {exc}")
    if not isinstance(doc, dict) or doc.get("id") != did:
        raise PlanStop("did_doc_invalid", f"{did}: document id mismatch")
    return doc


def resolve_subject_did(ctx: ExerciseContext, did: str) -> tuple[dict, bytes]:
    """Resolve one allow-listed DID to its (document, raw bytes)."""
    allow = ctx.live["target_allow_list"]
    if did.startswith("did:web:"):
        origin = f"https://{did[len('did:web:') :]}"
        if origin not in allow:
            raise PlanStop(
                "subject_origin_not_allowed",
                f"origin {origin} derived from {did} is not in target_allow_list",
            )
        status, body = ctx.counted_get(
            origin, "/.well-known/did.json", kind="did_resolve"
        )
        if status != 200:
            raise PlanStop("did_resolution_failed", f"{did}: HTTP {status}")
        return _parse_did_doc(did, body), body
    if did.startswith("did:plc:") and PLC_DIRECTORY_ORIGIN in allow:
        # A PLC DID resolves through the directory by specification. When
        # the packet pins the real directory, query exactly it: probing the
        # other allow-listed origins first is a deterministic wasted request
        # against the request ceiling.
        status, body = ctx.counted_get(
            PLC_DIRECTORY_ORIGIN, "/" + did, kind="did_resolve"
        )
        if status != 200:
            raise PlanStop("did_resolution_failed", f"{did}: HTTP {status}")
        return _parse_did_doc(did, body), body
    # Offline/test packets pin a loopback resolver instead of the real
    # directory; try each allow-listed HTTP origin until one serves the DID.
    http_origins = sorted(o for o in allow if urlsplit(o).scheme in ("http", "https"))
    for origin in http_origins:
        status, body = ctx.counted_get(origin, "/" + did, kind="did_resolve")
        if status != 200:
            continue
        try:
            return _parse_did_doc(did, body), body
        except PlanStop:
            continue  # this origin does not serve the DID; try the next
    raise PlanStop(
        "did_resolution_failed",
        f"{did}: no allow-listed resolver returned a DID document",
    )


def extract_pds_origin(ctx: ExerciseContext, did: str, doc: dict) -> str:
    """Extract the #atproto_pds endpoint origin; it must be allow-listed."""
    for service in doc.get("service", []):
        if not isinstance(service, dict):
            continue
        service_id = service.get("id", "")
        if service_id not in (f"{did}#atproto_pds", "#atproto_pds"):
            continue
        origin = origin_of(str(service.get("serviceEndpoint", "")))
        if origin is None:
            raise PlanStop("pds_origin_invalid", f"{did}: malformed serviceEndpoint")
        if origin not in ctx.live["target_allow_list"]:
            raise PlanStop(
                "pds_origin_not_allowed",
                f"PDS origin {origin} for {did} is not in target_allow_list",
            )
        return origin
    raise PlanStop("pds_missing", f"{did}: no #atproto_pds service entry")


def relay_origin(live: dict) -> str:
    """The pinned relay is the (lexically first) ws/wss allow-list entry."""
    candidates = sorted(
        o for o in live["target_allow_list"] if urlsplit(o).scheme in ("ws", "wss")
    )
    if not candidates:
        raise PlanStop(
            "no_relay_origin", "target_allow_list pins no ws/wss relay origin"
        )
    return candidates[0]


def subscribe_path(live: dict) -> str:
    """Jetstream v2 subscribe: collections/dids/kinds filters."""
    params = [("collections", k) for k in live["allowed_record_kinds"]]
    params += [("dids", d) for d in live["subject_allow_list"]]
    params.append(("kinds", "commit"))
    return f"{SUBSCRIBE_PATH}?{urlencode(params)}"


def _v2_commit_payload(message: bytes) -> dict | None:
    """Parse one Jetstream v2 message; return the commit payload or None.

    v2 envelope: {"$type": "message", "payload": {"$type":
    "network.bsky.jetstream.subscribeEvents#commit", "did", "seq", "time",
    "operation", "collection", "rkey", "rev", "cid"?, "record"?}}.
    Non-commit payloads (identity/account/sync) yield None.
    """
    event = json.loads(message.decode("utf-8"))
    if not isinstance(event, dict):
        raise PlanStop("event_invalid", "stream event is not an object")
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise PlanStop("event_invalid", "stream event without payload object")
    if payload.get("$type") != "network.bsky.jetstream.subscribeEvents#commit":
        return None
    return payload


def _check_event(ctx: ExerciseContext, message: bytes) -> None:
    """Refuse events naming an unpinned repo or record collection."""
    try:
        payload = _v2_commit_payload(message)
    except (ValueError, UnicodeDecodeError) as exc:
        raise PlanStop("event_invalid", f"stream event is not JSON: {exc}")
    if payload is None:
        return  # identity/account/sync payloads carry no repo records
    collection = payload.get("collection")
    if collection not in ctx.live["allowed_record_kinds"]:
        raise PlanStop(
            "unexpected_collection",
            f"stream delivered unpinned collection {collection!r}",
        )
    repo = payload.get("did")
    if repo not in ctx.live["subject_allow_list"]:
        raise PlanStop("unexpected_repo", f"stream delivered unpinned repo {repo!r}")


def collect_events(ctx: ExerciseContext, staging: Path) -> tuple[list[str], str]:
    """Subscribe to the pinned relay and collect bounded commit events."""
    live = ctx.live
    sock = ctx.counted_ws_connect(relay_origin(live), subscribe_path(live))
    events: list[str] = []
    stop_rule = None
    try:
        # The frame reader enforces the wall clock across ping/pong traffic;
        # a periodic relay ping must not hold the run open past the deadline.
        messages = iter_ws_messages(sock, ctx.deadline)
        while len(events) < ctx.ceilings["max_events"]:
            try:
                message = next(messages)
            except StopIteration:
                stop_rule = "completed"
                break
            except WallClockExceeded:
                stop_rule = "max_wall_clock_seconds"
                break
            ctx.add_bytes(len(message))
            _check_event(ctx, message)
            ctx.counters["events"] += 1
            events.append(message.decode("utf-8"))
    except OSError as exc:
        raise PlanStop("stream_failed", f"relay stream failed mid-run: {exc}")
    finally:
        try:
            ws_send_frame(sock, OP_CLOSE)
        except OSError:
            pass
        sock.close()
    if stop_rule is None:
        stop_rule = "max_events"
    text = "".join(line if line.endswith("\n") else line + "\n" for line in events)
    (staging / "events.ndjson").write_text(text, encoding="utf-8")
    return events, stop_rule


def fetch_proofs(
    ctx: ExerciseContext, events: list[str], pds_by_did: dict, staging: Path
) -> None:
    """Capture getRecord CAR bytes verbatim for commit events with a CID.

    Capture only: no cryptographic verification happens in the harness; the
    offline M6 verification code checks these artifacts.
    """
    fetched = 0
    for line in events:
        if fetched >= ctx.ceilings["max_proof_fetches"]:
            break
        if ctx.remaining_wall() <= 0:
            raise PlanStop(
                "wall_clock_exceeded",
                "wall clock exhausted before proof fetches completed",
            )
        payload = _v2_commit_payload(line.encode("utf-8"))
        if payload is None:
            continue
        if payload.get("operation") not in ("create", "update"):
            continue
        if not payload.get("cid"):
            continue
        did = payload["did"]
        pds = pds_by_did[did]
        query = urlencode(
            {
                "did": did,
                "collection": payload["collection"],
                "rkey": payload["rkey"],
            }
        )
        status, body = ctx.counted_get(
            pds, f"{GET_RECORD_PATH}?{query}", kind="proof_fetch"
        )
        if status != 200:
            raise PlanStop(
                "proof_fetch_failed",
                f"getRecord {did} {payload['collection']}/{payload['rkey']} "
                f"returned HTTP {status}",
            )
        dest = (
            staging
            / "proofs"
            / _safe_segment(did)
            / _safe_segment(payload["collection"])
            / (_safe_segment(payload["rkey"]) + ".car")
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        fetched += 1
    ctx.counters["proof_fetches"] = fetched


def run_read_plan(live: dict, ctx: ExerciseContext, staging: Path) -> str:
    """Execute the X6 read plan; returns the stop rule for a clean run."""
    pds_by_did = {}
    did_dir = staging / "did_docs"
    did_dir.mkdir(parents=True, exist_ok=True)
    for did in live["subject_allow_list"]:
        doc, body = resolve_subject_did(ctx, did)
        (did_dir / (_safe_segment(did) + ".json")).write_bytes(body)
        pds_by_did[did] = extract_pds_origin(ctx, did, doc)
    events, stop_rule = collect_events(ctx, staging)
    fetch_proofs(ctx, events, pds_by_did, staging)
    if ctx.counters["writes"] != 0:
        raise PlanStop("unexpected_write", "harness bug: write counter is nonzero")
    return stop_rule


# --- bounded write plan (V0-X7-WRITE-SMOKE) ---------------------------------


def load_write_credential() -> tuple[dict | None, str, str]:
    """Load the X7 credential named by V0_X7_CREDENTIAL_REF.

    Returns (credential, stop_rule, notes); on failure credential is None.
    The secret value never appears in the returned notes. This runs before
    any socket use; the file lives outside the repository by contract.
    """
    ref = os.environ.get(CREDENTIAL_ENV)
    if not ref:
        return None, "credential_unavailable", f"{CREDENTIAL_ENV} is not set"
    try:
        raw = Path(ref).read_bytes()
    except OSError:
        return None, "credential_unavailable", "credential file is unreadable"
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None, "credential_malformed", "credential file is not JSON"
    if (
        not isinstance(obj, dict)
        or not isinstance(obj.get("identifier"), str)
        or not isinstance(obj.get("app_password"), str)
        or not obj["identifier"]
        or not obj["app_password"]
    ):
        return (
            None,
            "credential_malformed",
            'credential file must be {"identifier", "app_password"}',
        )
    return obj, "", ""


def _community_model():
    """Import the inert shared model for pure rkey derivation only.

    Lazily imported so X6 runs never touch it; the repository source tree
    is the fallback when the interpreter lacks it on sys.path.
    """
    try:
        import community_model

        return community_model
    except ImportError:
        candidate = TOOLS_DIR.parent.parent / "packages" / "community-model" / "src"
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
        import community_model

        return community_model


_TID_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"


def _x7_rkey(token: str, label: str) -> str:
    """Deterministic exercise rkey: a valid TID derived from the token.

    communityd validates that submission rkeys are ATProto TIDs, so the
    exercise records must use TID-shaped keys; deriving them from the
    idempotency input keeps reruns idempotent at the same rkeys.
    """
    digest = hashlib.sha256(f"v0-x7\n{label}\n{token}".encode()).digest()
    value = int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF
    return "".join(_TID_ALPHABET[(value >> shift) & 31] for shift in range(60, -1, -5))


def _readback_record(
    ctx: ExerciseContext,
    pds: str,
    repo: str,
    collection: str,
    rkey: str,
    bearer: str,
) -> dict | None:
    """Fetch one record as JSON for ambiguity resolution; None if absent."""
    query = urlencode({"repo": repo, "collection": collection, "rkey": rkey})
    status, body = ctx.counted_get(
        pds, f"{REPO_GET_RECORD_PATH}?{query}", bearer, kind="ambiguity_readback"
    )
    if status != 200:
        return None
    try:
        obj = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def counted_create_record(
    ctx: ExerciseContext,
    pds: str,
    repo: str,
    collection: str,
    rkey: str,
    record: dict,
    bearer: str,
) -> dict:
    """One bounded createRecord at a deterministic rkey; never retried blind.

    A transport failure after the request was sent is ambiguous: the run
    resolves it by a deterministic-rkey readback and treats a compatible
    found record as written, or stops with a failure receipt.
    """
    ctx.begin_write()
    payload = {
        "repo": repo,
        "collection": collection,
        "rkey": rkey,
        "record": record,
    }
    try:
        status, body = ctx.counted_post(
            pds, CREATE_RECORD_PATH, payload, bearer=bearer, retry=False
        )
    except (OSError, http.client.HTTPException) as exc:
        found = _readback_record(ctx, pds, repo, collection, rkey, bearer)
        if found is not None and found.get("value") == record:
            ctx.record_write()
            return {"uri": found["uri"], "cid": found["cid"], "resolved": "readback"}
        raise PlanStop(
            "ambiguous_write",
            f"createRecord {collection}/{rkey} transport failure stayed "
            f"ambiguous after readback: {exc}",
        ) from exc
    if status != 200:
        raise PlanStop(
            "write_rejected",
            f"createRecord {collection}/{rkey} returned HTTP {status}",
        )
    try:
        result = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PlanStop(
            "write_response_invalid", f"createRecord response is not JSON: {exc}"
        ) from exc
    expected_uri = f"at://{repo}/{collection}/{rkey}"
    if not isinstance(result, dict) or result.get("uri") != expected_uri:
        raise PlanStop(
            "write_response_invalid",
            f"createRecord returned uri {result.get('uri')!r}, "
            f"expected {expected_uri!r}",
        )
    ctx.record_write()
    return {"uri": result["uri"], "cid": result["cid"], "resolved": "direct"}


def _redact(data: bytes, secrets: list[str]) -> bytes:
    redacted = data
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret.encode(), b"<redacted>")
    return redacted


def _write_daemon_config(staging: Path, pds_origin: str, subject_did: str) -> Path:
    """Stage the communityd config; carries the env var NAME, never a secret."""
    path = staging / "communityd.toml"
    if not path.exists():
        path.write_text(
            "\n".join(
                [
                    f'community_did = "{subject_did}"',
                    f'administrator_did = "{subject_did}"',
                    f'community_pds_url = "{pds_origin}"',
                    f"allowed_uid = {os.geteuid()}",
                    'reader_adapter = "pds_fixed"',
                    'ledger_adapter = "pds"',
                    'writer_adapter = "pds"',
                    'credential_provider = "env_file"',
                    f'credential_ref = "env:{CREDENTIAL_ENV}"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return path


def _invoke_communityd(
    argv: list[str], env: dict, timeout: float
) -> subprocess.CompletedProcess:
    """The subprocess boundary for the communityd CLI (patched in tests)."""
    return subprocess.run(argv, env=env, capture_output=True, timeout=timeout)


def _proxy_kind(path: str) -> str:
    """Operation class for one proxied communityd XRPC request."""
    procedure = urlsplit(path).path
    return {
        CREATE_SESSION_PATH: "session",
        CREATE_RECORD_PATH: "write",
        REPO_GET_RECORD_PATH: "read",
        LIST_RECORDS_PATH: "ledger_list",
        GET_RECORD_PATH: "proof_fetch",
    }.get(procedure, "xrpc")


class AccountingProxy:
    """Loopback HTTP front forcing communityd XRPC through the exercise budget.

    communityd only ever dials its configured ``community_pds_url``; the
    staged config points that at this proxy, and the child environment is
    scrubbed of proxy variables, so no subprocess request can bypass the
    budget. Every proxied request consumes the SAME ExerciseContext
    request/byte budget as harness-originated traffic, checked and
    decremented under a lock BEFORE any upstream socket is opened. When
    the budget is exhausted the proxy answers an error without any network
    I/O (fail closed) and the stored stop rule surfaces in the receipt.
    The proxy forwards to exactly one pinned, allow-listed upstream origin
    and only ``/xrpc/`` paths. ``counters.requests`` is therefore the one
    authoritative exercise-wide total: harness calls, communityd session
    authentication, retries, ambiguity readbacks, and proof fetches alike.
    """

    def __init__(self, ctx: ExerciseContext, upstream_origin: str):
        if upstream_origin not in ctx.live["target_allow_list"]:
            raise PlanStop(
                "cli_pds_not_allowed",
                f"proxy upstream {upstream_origin} is not in target_allow_list",
            )
        self.ctx = ctx
        self.upstream = upstream_origin
        self.lock = threading.Lock()
        self.stop: PlanStop | None = None
        self.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), self._make_handler()
        )
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.origin = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _make_handler(self):
        proxy = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # noqa: A002 - stdlib name
                pass  # no request logging: headers may carry a bearer token

            def do_GET(self):
                self._forward(None)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length > 0 else b""
                self._forward(body)

            def _refuse(self, status: int, error: str, stop: PlanStop | None = None):
                if stop is not None and proxy.stop is None:
                    proxy.stop = stop
                self._answer(status, json.dumps({"error": error}).encode("utf-8"))

            def _forward(self, body: bytes | None):
                if not self.path.startswith("/xrpc/"):
                    self._answer(404, b'{"error":"not_an_xrpc_path"}')
                    return
                with proxy.lock:
                    try:
                        proxy.ctx._count_request()
                    except PlanStop as exc:
                        self._refuse(502, "exercise_request_budget_exhausted", exc)
                        return
                    entry = proxy.ctx._open_request(
                        "communityd-proxy",
                        _proxy_kind(self.path),
                        self.command,
                        proxy.upstream,
                        self.path,
                    )
                bearer_header = self.headers.get("Authorization")
                bearer = None
                if bearer_header and bearer_header.startswith("Bearer "):
                    bearer = bearer_header[len("Bearer ") :]
                budget = proxy.ctx.ceilings["max_bytes"] - proxy.ctx.counters["bytes"]
                timeout = proxy.ctx.retry["request_timeout_seconds"]
                try:
                    if body is None:
                        status, response = http_get(
                            proxy.upstream, self.path, timeout, budget, bearer
                        )
                    else:
                        status, response = http_post(
                            proxy.upstream, self.path, body, timeout, budget, bearer
                        )
                except ByteBudgetExceeded:
                    entry["error"] = "byte_budget_exceeded"
                    with proxy.lock:
                        stop = PlanStop(
                            "byte_ceiling_exceeded",
                            "proxied response exceeded the max_bytes ceiling",
                        )
                        proxy.stop = proxy.stop or stop
                    self._answer(502, b'{"error":"exercise_byte_budget_exhausted"}')
                    return
                except (OSError, http.client.HTTPException):
                    # Counted already; the transport failure surfaces to the
                    # subprocess, whose own retry policy re-enters the proxy
                    # (and the budget) for every attempt.
                    entry["error"] = "transport"
                    self._answer(502, b'{"error":"upstream_transport_failure"}')
                    return
                entry["status"] = status
                entry["bytes"] = len(response)
                with proxy.lock:
                    try:
                        proxy.ctx.add_bytes(len(response))
                    except PlanStop as exc:
                        self._refuse(502, "exercise_byte_budget_exhausted", exc)
                        return
                    proxy.ctx.targets_contacted.add(proxy.upstream)
                self._answer(status, response)

            def _answer(self, status: int, body: bytes):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler


def run_communityd_cli(
    ctx: ExerciseContext,
    staging: Path,
    proxy: AccountingProxy,
    pds_origin: str,
    subject_did: str,
    command: str,
    arguments: list[str],
    expected: tuple[str, str],
    expected_subject_uri: str,
    bearer: str,
    secrets: list[str],
) -> dict:
    """One authority write via the repository's real communityd CLI.

    ``expected`` is the (collection, deterministic rkey) the CLI must land;
    exit 8 is resolved by readback of that rkey, never by rerunning the
    CLI. The subprocess gets a scrubbed minimal environment plus the
    credential reference; its stdout/stderr are retained redacted. The
    staged config points the CLI's PDS URL at ``proxy``, so every XRPC
    request the subprocess makes — session authentication, retries,
    readbacks, the write itself — consumes this exercise's shared budget
    before any upstream socket opens.
    """
    ctx.begin_write()
    if pds_origin not in ctx.live["target_allow_list"]:
        raise PlanStop(
            "cli_pds_not_allowed",
            f"communityd PDS origin {pds_origin} is not in target_allow_list",
        )
    collection, rkey = expected
    config_path = _write_daemon_config(staging, proxy.origin, subject_did)
    env = minimal_child_env()
    env[CREDENTIAL_ENV] = os.environ.get(CREDENTIAL_ENV, "")
    packages = TOOLS_DIR.parent.parent / "packages"
    env["PYTHONPATH"] = os.pathsep.join(
        str(packages / name / "src") for name in ("communityd", "community-model")
    )
    argv = [
        sys.executable,
        "-m",
        "communityd",
        "--config",
        str(config_path),
        command,
        *arguments,
    ]
    try:
        result = _invoke_communityd(argv, env, max(1.0, ctx.remaining_wall()))
    except subprocess.TimeoutExpired as exc:
        raise PlanStop(
            "max_wall_clock_seconds", "communityd CLI outlived the wall clock"
        ) from exc
    cli_dir = staging / "cli"
    cli_dir.mkdir(exist_ok=True)
    (cli_dir / f"{command}.stdout.json").write_bytes(_redact(result.stdout, secrets))
    (cli_dir / f"{command}.stderr.txt").write_bytes(_redact(result.stderr, secrets))
    if result.returncode != 0 and proxy.stop is not None:
        # A proxied request hit the exhausted budget; that stop rule, not
        # the CLI's downstream failure, is the honest receipt outcome.
        raise proxy.stop
    if result.returncode == 0:
        try:
            outcome = json.loads(result.stdout.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise PlanStop(
                "cli_output_invalid", f"communityd {command} stdout is not JSON"
            ) from exc
        expected_uri = f"at://{subject_did}/{collection}/{rkey}"
        if not isinstance(outcome, dict) or outcome.get("uri") != expected_uri:
            raise PlanStop(
                "cli_unexpected_record",
                f"communityd {command} returned uri "
                f"{isinstance(outcome, dict) and outcome.get('uri')!r}, "
                f"expected {expected_uri!r}",
            )
        ctx.record_write()
        return {"uri": outcome["uri"], "cid": outcome["cid"]}
    if result.returncode == 8:
        # Ambiguous authority write: resolve the deterministic rkey by
        # readback; a compatible found record counts as existing.
        found = _readback_record(ctx, pds_origin, subject_did, collection, rkey, bearer)
        value = found.get("value") if found else None
        subject = value.get("subject") if isinstance(value, dict) else None
        if (
            isinstance(value, dict)
            and value.get("$type") == collection
            and isinstance(subject, dict)
            and subject.get("uri") == expected_subject_uri
        ):
            ctx.record_write()
            return {"uri": found["uri"], "cid": found["cid"]}
        raise PlanStop(
            "ambiguous_write",
            f"communityd {command} stayed ambiguous after {collection}/{rkey} readback",
        )
    if result.returncode == 5:
        raise PlanStop(
            "authority_write_conflict",
            f"communityd {command} reported an immutable conflict or "
            "unsupported readmission",
        )
    raise PlanStop("cli_failed", f"communityd {command} exited {result.returncode}")


def _drain_events(
    ctx: ExerciseContext,
    messages,
    captured: list[str],
    seen: set[tuple[str, str]],
    expected: set[tuple[str, str]],
) -> None:
    """Collect relay events until every expected (collection, rkey) is seen."""
    while not expected <= seen:
        if ctx.counters["events"] >= ctx.ceilings["max_events"]:
            raise PlanStop(
                "max_events",
                "event ceiling reached before the expected commit events were observed",
            )
        try:
            message = next(messages)
        except StopIteration:
            raise PlanStop(
                "expected_events_missing",
                f"relay closed before events for {sorted(expected - seen)}",
            ) from None
        except WallClockExceeded:
            raise PlanStop(
                "max_wall_clock_seconds",
                "wall clock exhausted before the expected commit events were observed",
            ) from None
        except OSError as exc:
            raise PlanStop("stream_failed", f"relay stream failed mid-run: {exc}")
        ctx.add_bytes(len(message))
        _check_event(ctx, message)
        ctx.counters["events"] += 1
        captured.append(message.decode("utf-8"))
        payload = _v2_commit_payload(message)
        if payload is not None:
            seen.add((payload.get("collection"), payload.get("rkey")))


def run_observer_pass(staging: Path, expected: list[tuple[str, str]]) -> dict:
    """Verify the projection transitions from the captured artifacts.

    Capture-then-verify mode: communitywatch does its own live I/O (its
    own subscription and resolver traffic) which the harness cannot
    bounds-account, so the transition check replays the events the harness
    captured under the packet ceilings. The summary is retained as
    projections.json. Tests may patch this seam.
    """
    lines = (staging / "events.ndjson").read_text(encoding="utf-8").splitlines()
    positions: dict[tuple[str, str], int] = {}
    for index, line in enumerate(lines):
        payload = _v2_commit_payload(line.encode("utf-8"))
        if payload is None:
            continue
        key = (payload.get("collection"), payload.get("rkey"))
        positions.setdefault(key, index)
    missing = [key for key in expected if key not in positions]
    if missing:
        raise PlanStop(
            "observer_verification_failed",
            f"no captured commit event for {missing}",
        )
    states = ["submitted", "visible", "removed"]
    anchors = expected[1:]  # submit, admission, removal
    sequence = [positions[key] for key in anchors]
    if sequence != sorted(sequence):
        raise PlanStop(
            "observer_verification_failed",
            "captured commit events are out of transition order",
        )
    summary = {
        "mode": "capture_then_verify",
        "transitions": [
            {"state": state, "after": f"{collection}/{rkey}"}
            for state, (collection, rkey) in zip(states, anchors)
        ],
    }
    (staging / "projections.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def _assert_secret_absent(staging: Path, secrets: list[str]) -> None:
    """Grep the retained staging tree for credential material.

    On a hit the tree is purged rather than retained: a leaked secret is a
    harness bug, and retention must never preserve one.
    """
    needles = [s.encode() for s in secrets if s]
    for path in sorted(staging.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if any(needle in data for needle in needles):
            for child in staging.iterdir():
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
            raise PlanStop(
                "secret_leak_detected",
                f"{path.name} held credential material; staging was purged",
            )


def run_write_plan(live: dict, ctx: ExerciseContext, staging: Path, credential) -> str:
    """Execute the X7 write plan; returns the stop rule for a clean run."""
    subjects = live["subject_allow_list"]
    if len(subjects) != 1:
        raise PlanStop(
            "x7_requires_single_subject",
            "X7 writes exactly one pinned subject repository",
        )
    subject = subjects[0]
    missing_kinds = sorted(set(X7_RECORD_KINDS) - set(live["allowed_record_kinds"]))
    if missing_kinds:
        raise PlanStop(
            "record_kind_not_pinned",
            f"allowed_record_kinds does not pin {missing_kinds}",
        )
    did_dir = staging / "did_docs"
    did_dir.mkdir(parents=True, exist_ok=True)
    doc, body = resolve_subject_did(ctx, subject)
    (did_dir / (_safe_segment(subject) + ".json")).write_bytes(body)
    pds = extract_pds_origin(ctx, subject, doc)

    status, session_body = ctx.counted_post(
        pds,
        CREATE_SESSION_PATH,
        {
            "identifier": credential["identifier"],
            # The wire field is "password" per the createSession lexicon;
            # the credential file's "app_password" key names our custody
            # rule, not the XRPC parameter.
            "password": credential["app_password"],
        },
        kind="session",
    )
    if status != 200:
        raise PlanStop("session_failed", f"createSession returned HTTP {status}")
    try:
        session = json.loads(session_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PlanStop(
            "session_invalid", f"createSession response is not JSON: {exc}"
        ) from exc
    bearer = session.get("accessJwt")
    if not isinstance(bearer, str) or not bearer:
        raise PlanStop("session_invalid", "createSession returned no accessJwt")
    secrets = [credential["app_password"], bearer]

    token = live["idempotency_input"]
    model = _community_model()
    # The subscription opens before the first write: Jetstream exposes no
    # current-seq read to pin a replay cursor, and a pre-write subscription
    # is strictly stronger (no gap between baseline and write 1).
    sock = ctx.counted_ws_connect(relay_origin(live), subscribe_path(live))
    # All communityd subprocess XRPC flows through this loopback proxy into
    # the same counted budget as harness-originated traffic.
    proxy = AccountingProxy(ctx, pds)
    messages = iter_ws_messages(sock, ctx.deadline)
    captured: list[str] = []
    seen: set[tuple[str, str]] = set()
    expected_order = []
    try:
        post_rkey = _x7_rkey(token, "post")
        post = counted_create_record(
            ctx,
            pds,
            subject,
            POST_COLLECTION,
            post_rkey,
            {
                "$type": POST_COLLECTION,
                "text": f"V0-X7-WRITE-SMOKE {token}",
                "createdAt": _utc_now(),
            },
            bearer,
        )
        submit_rkey = _x7_rkey(token, "submit")
        submit = counted_create_record(
            ctx,
            pds,
            subject,
            SUBMIT_COLLECTION,
            submit_rkey,
            {
                "$type": SUBMIT_COLLECTION,
                "community": subject,
                "subject": {"uri": post["uri"], "cid": post["cid"]},
                "createdAt": _utc_now(),
            },
            bearer,
        )
        admission_rkey = model.admission_rkey(
            model.RecordRef(uri=submit["uri"], cid=submit["cid"])
        )
        admission = run_communityd_cli(
            ctx,
            staging,
            proxy,
            pds,
            subject,
            "admit",
            ["--submission-uri", submit["uri"], "--submission-cid", submit["cid"]],
            (ADMISSION_COLLECTION, admission_rkey),
            post["uri"],
            bearer,
            secrets,
        )
        expected_order = [
            (POST_COLLECTION, post_rkey),
            (SUBMIT_COLLECTION, submit_rkey),
            (ADMISSION_COLLECTION, admission_rkey),
        ]
        _drain_events(ctx, messages, captured, seen, set(expected_order))
        removal_rkey = model.removal_rkey(
            model.RecordRef(uri=admission["uri"], cid=admission["cid"])
        )
        run_communityd_cli(
            ctx,
            staging,
            proxy,
            pds,
            subject,
            "remove",
            ["--admission-uri", admission["uri"], "--admission-cid", admission["cid"]],
            (MOD_ACTION_COLLECTION, removal_rkey),
            post["uri"],
            bearer,
            secrets,
        )
        expected_order.append((MOD_ACTION_COLLECTION, removal_rkey))
        _drain_events(ctx, messages, captured, seen, set(expected_order))
    finally:
        proxy.close()
        try:
            ws_send_frame(sock, OP_CLOSE)
        except OSError:
            pass
        sock.close()
    text = "".join(line if line.endswith("\n") else line + "\n" for line in captured)
    (staging / "events.ndjson").write_text(text, encoding="utf-8")
    fetch_proofs(ctx, captured, {subject: pds}, staging)
    run_observer_pass(staging, expected_order)
    _assert_secret_absent(staging, secrets)
    return "completed"


# --- evidence retention and receipt ------------------------------------------


def _artifact_role(path: str) -> str:
    if path == "events.ndjson":
        return "events_ndjson"
    if path == "request_log.ndjson":
        return "request_log"
    if path.startswith("did_docs/"):
        return "did_doc"
    if path.startswith("proofs/"):
        return "proof_car"
    if path == "communityd.toml":
        return "daemon_config"
    if path == "projections.json":
        return "projection_snapshot"
    if path.startswith("cli/"):
        return "cli_transcript"
    return "artifact"


def _artifact_media_type(path: str, role: str) -> str:
    if path.endswith(".txt"):
        return "text/plain"
    return MEDIA_TYPES.get(role, "application/octet-stream")


def retain_run(staging: Path, destination_uri: str, receipt_id: str):
    """Copy the staging tree to the destination and verify the readback."""
    parts = urlsplit(destination_uri)
    if parts.scheme != "file" or parts.netloc not in ("", "localhost"):
        raise EnvironmentBlocked(
            [f"unsupported evidence destination {destination_uri!r}"]
        )
    run_dir = Path(parts.path) / receipt_id
    report = evidence_store.write_tree(staging, run_dir)
    if not report["ok"]:
        raise EnvironmentBlocked(report["problems"])
    return run_dir, report["manifest"]


def self_pin() -> tuple[int, str]:
    """Byte length and SHA-256 digest of this enforcement module's file."""
    data = Path(__file__).read_bytes()
    return len(data), common.sha256_digest(data)


def _receipt_id(operation_id: str, started_at: str, token: str) -> str:
    compact = re.sub(r"[-:TZ]", "", started_at)
    return f"EXR-{operation_id}-{_safe_segment(token)}-{compact}"


def _base_receipt(
    operation_id: str, packet_digest: str, harness_digest: str, started_at: str
) -> dict:
    return {
        "schema": "exercise-receipt-v1",
        "receipt_id": _receipt_id(operation_id, started_at, "preflight"),
        "operation_id": operation_id,
        "controller_entry_packet_sha256": packet_digest,
        "harness_sha256": harness_digest,
        "started_at": started_at,
        "ended_at": started_at,
        "targets_contacted": [],
        "counters": _zero_counters(),
        "stop_rule": "not_started",
        "artifacts": [],
        "outcome": "CONTRACT_INVALID",
    }


def _fail(
    outcome: str,
    stop_rule: str,
    notes: str,
    operation_id: str,
    packet_digest: str,
    harness_digest: str,
    started_at: str,
) -> int:
    receipt = _base_receipt(operation_id, packet_digest, harness_digest, started_at)
    receipt["outcome"] = outcome
    receipt["stop_rule"] = stop_rule
    receipt["notes"] = notes
    receipt["ended_at"] = _utc_now()
    return _emit(receipt, 2)


def _emit(receipt: dict, exit_code: int) -> int:
    problems = validators.validate_artifact("exercise-receipt", receipt)
    if problems:
        # Best-effort evidence only: a self-check failure is a harness bug
        # (or an unrecognized operation id); the receipt is still printed.
        for problem in problems:
            print(f"receipt self-check: {problem}", file=sys.stderr)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return exit_code


def _load_packet(path: Path):
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, common.sha256_digest(b""), [f"packet unreadable: {exc}"]
    digest = common.sha256_digest(raw)
    try:
        packet = gstrict.strict_loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, gstrict.StrictJsonError) as exc:
        return None, digest, [str(exc)]
    problems = validators.validate_artifact("controller-entry-packet", packet)
    if problems:
        return None, digest, problems
    return packet, digest, []


def _run_exercise(
    operation_id: str, packet: dict, packet_digest: str, started_at: str
) -> int:
    live = packet["launch_payload"]["live_exercise"]
    harness_bytes, harness_digest = self_pin()
    pin = live["harness"]
    if pin["sha256"] != harness_digest or pin["bytes"] != harness_bytes:
        return _fail(
            "UNAUTHORIZED",
            "harness_pin_mismatch",
            "harness digest/bytes do not match the packet pin; refusing to run",
            operation_id,
            packet_digest,
            harness_digest,
            started_at,
        )

    started_monotonic = time.monotonic()
    receipt_id = _receipt_id(operation_id, started_at, live["idempotency_input"])
    credential = None
    if operation_id == "V0-X7-WRITE-SMOKE":
        # The credential is resolved before any socket use; a missing or
        # malformed reference is UNAUTHORIZED, never a runtime failure.
        credential, stop_rule, notes = load_write_credential()
        if credential is None:
            return _fail(
                "UNAUTHORIZED",
                stop_rule,
                notes,
                operation_id,
                packet_digest,
                harness_digest,
                started_at,
            )
    ctx = ExerciseContext(live, started_monotonic)
    staging = Path(tempfile.mkdtemp(prefix="v0-exercise-"))
    outcome = "PASS"
    stop_rule = "completed"
    notes = ""
    try:
        if operation_id == "V0-X7-WRITE-SMOKE":
            stop_rule = run_write_plan(live, ctx, staging, credential)
        else:
            stop_rule = run_read_plan(live, ctx, staging)
    except PlanStop as exc:
        outcome = exc.outcome
        stop_rule = exc.stop_rule
        notes = exc.notes
    except Exception as exc:  # noqa: BLE001 - a crash must still receipt
        outcome = "CHECK_FAILED"
        stop_rule = "harness_internal_error"
        # Type name only: an unexpected exception's message is not
        # guaranteed free of credential material.
        notes = f"unhandled {type(exc).__name__} in the exercise plan"

    # The per-request accounting log is retained on every outcome; it must
    # explain every counted request. A mismatch means traffic escaped the
    # budget accounting — a harness defect, never a PASS.
    (staging / "request_log.ndjson").write_text(
        "".join(json.dumps(entry, sort_keys=True) + "\n" for entry in ctx.request_log),
        encoding="utf-8",
    )
    if len(ctx.request_log) != ctx.counters["requests"]:
        outcome = "CHECK_FAILED"
        notes = (f"{notes}; " if notes else "") + (
            f"request_log_inconsistent: {len(ctx.request_log)} logged vs "
            f"{ctx.counters['requests']} counted"
        )

    manifest, manifest_problems = evidence_store.build_manifest(staging)
    destination = packet["launch_payload"]["evidence_policy"]["destination_uri"]
    run_uri = f"{destination.rstrip('/')}/{receipt_id}"
    artifacts = [
        {
            "role": _artifact_role(entry["path"]),
            "uri": f"{run_uri}/{entry['path']}",
            "media_type": _artifact_media_type(
                entry["path"], _artifact_role(entry["path"])
            ),
            "bytes": entry["bytes"],
            "sha256": entry["sha256"],
        }
        for entry in manifest["files"]
    ]
    receipt = _base_receipt(operation_id, packet_digest, harness_digest, started_at)
    receipt.update(
        {
            "receipt_id": receipt_id,
            "targets_contacted": sorted(ctx.targets_contacted),
            "counters": ctx.counters,
            "stop_rule": stop_rule,
            "artifacts": artifacts,
            "outcome": outcome,
        }
    )
    retention = live["retention"]
    receipt["notes"] = (f"{notes}; " if notes else "") + (
        f"artifacts retained at {run_uri} until {retention['retention_until']} "
        f"(retain_artifacts={str(retention['retain_artifacts']).lower()})"
    )
    if operation_id == "V0-X7-WRITE-SMOKE":
        receipt["notes"] += (
            "; observer pass mode: capture_then_verify (communitywatch does"
            " its own unaccountable live I/O, so transitions were verified"
            " offline from harness-captured events and proofs); the relay"
            " subscription was opened before write 1 in place of a replay"
            " cursor (Jetstream exposes no current-seq read); communityd"
            " CLI subprocess XRPC was confined to an in-process loopback"
            " accounting proxy sharing this receipt's request/byte budget,"
            " so counters.requests is the authoritative exercise-wide"
            " total (harness calls, session authentication, retries,"
            " ambiguity readbacks, and proof fetches alike)"
        )
    if manifest_problems:
        receipt["outcome"] = "ENVIRONMENT_BLOCKED"
        receipt["stop_rule"] = "evidence_manifest_failed"
        receipt["notes"] += "; " + "; ".join(manifest_problems)
        receipt["ended_at"] = _utc_now()
    else:
        receipt["ended_at"] = _utc_now()
        (staging / "receipt.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        try:
            retain_run(staging, destination, receipt_id)
        except EnvironmentBlocked as exc:
            receipt["outcome"] = "ENVIRONMENT_BLOCKED"
            receipt["stop_rule"] = "evidence_readback_failed"
            receipt["notes"] += "; " + "; ".join(exc.problems)
        else:
            # The verified destination copy is authoritative; do not leak
            # staging tempdirs onto the controller's filesystem.
            shutil.rmtree(staging, ignore_errors=True)
    exit_code = 0 if receipt["outcome"] == "PASS" else 1
    return _emit(receipt, exit_code)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="v0-exercise",
        description="Protected V0 controlled-live-exercise harness.",
    )
    parser.add_argument("operation_id")
    parser.add_argument("--packet", type=Path, required=True)
    args = parser.parse_args(argv)

    scrub_environment()
    started_at = _utc_now()
    _, harness_digest = self_pin()

    packet, packet_digest, problems = _load_packet(args.packet)
    if problems:
        return _fail(
            "CONTRACT_INVALID",
            "packet_invalid",
            "; ".join(problems),
            args.operation_id,
            packet_digest,
            harness_digest,
            started_at,
        )
    if args.operation_id not in KNOWN_OPERATIONS:
        return _fail(
            "UNAUTHORIZED",
            "unrecognized_operation",
            f"operation {args.operation_id!r} is not a contract operation id",
            args.operation_id,
            packet_digest,
            harness_digest,
            started_at,
        )
    live = packet["launch_payload"].get("live_exercise")
    if live is None:
        return _fail(
            "UNAUTHORIZED",
            "no_live_exercise",
            "packet carries no live_exercise authorization",
            args.operation_id,
            packet_digest,
            harness_digest,
            started_at,
        )
    if live["operation_id"] != args.operation_id:
        return _fail(
            "UNAUTHORIZED",
            "operation_mismatch",
            f"packet pins {live['operation_id']}, not {args.operation_id}",
            args.operation_id,
            packet_digest,
            harness_digest,
            started_at,
        )
    if args.operation_id not in IMPLEMENTED_OPERATIONS:
        return _fail(
            "UNAUTHORIZED",
            "operation_not_implemented",
            f"{args.operation_id} is not implemented by this harness",
            args.operation_id,
            packet_digest,
            harness_digest,
            started_at,
        )
    return _run_exercise(args.operation_id, packet, packet_digest, started_at)


if __name__ == "__main__":
    raise SystemExit(main())
