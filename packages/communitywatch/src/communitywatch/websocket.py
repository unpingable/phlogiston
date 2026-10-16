"""Minimal stdlib WebSocket client for the Jetstream v2 subscription.

The frame/handshake pattern is adapted from the repository's governed
read-only exercise harness (``governance/tools/v0_exercise.py``); this is a
fresh product implementation, not an import of governance tooling.  Clients
mask every frame (RFC 6455 section 5.3); messages are bounded and pings are
answered with pongs.
"""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
from collections.abc import Iterator
from urllib.parse import urlsplit

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

MAX_MESSAGE_BYTES = 1 << 20


class WebSocketError(OSError):
    """The WebSocket handshake or framing failed."""


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    chunks: list[bytes] = []
    remaining = count
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise WebSocketError("connection closed mid-frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def send_frame(
    sock: socket.socket,
    opcode: int,
    payload: bytes = b"",
    *,
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
        payload = bytes(b ^ key[index % 4] for index, b in enumerate(payload))
    sock.sendall(bytes(header) + payload)


def recv_frame(sock: socket.socket) -> tuple[bool, int, bytes]:
    """Receive one frame; returns (fin, opcode, unmasked payload)."""

    first, second = _recv_exact(sock, 2)
    fin = bool(first & 0x80)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        (length,) = struct.unpack("!H", _recv_exact(sock, 2))
    elif length == 127:
        (length,) = struct.unpack("!Q", _recv_exact(sock, 8))
    if length > MAX_MESSAGE_BYTES:
        raise WebSocketError("websocket frame exceeds the V0 message bound")
    key = _recv_exact(sock, 4) if masked else b""
    payload = _recv_exact(sock, length) if length else b""
    if masked:
        payload = bytes(b ^ key[index % 4] for index, b in enumerate(payload))
    return fin, opcode, payload


def iter_messages(sock: socket.socket) -> Iterator[bytes]:
    """Yield reassembled text/binary message payloads until close."""

    fragments: list[bytes] = []
    total = 0
    while True:
        fin, opcode, payload = recv_frame(sock)
        if opcode == OP_CLOSE:
            try:
                send_frame(sock, OP_CLOSE, payload)
            except OSError:
                pass
            return
        if opcode == OP_PING:
            send_frame(sock, OP_PONG, payload)
            continue
        if opcode == OP_PONG:
            continue
        if opcode in (OP_TEXT, OP_BINARY):
            fragments = [payload]
            total = len(payload)
        elif opcode == OP_CONTINUATION and fragments:
            fragments.append(payload)
            total += len(payload)
        else:
            continue
        if total > MAX_MESSAGE_BYTES:
            raise WebSocketError("websocket message exceeds the V0 message bound")
        if fin:
            yield b"".join(fragments)
            fragments = []
            total = 0


def _read_http_head(sock: socket.socket, limit: int = 65536) -> tuple[bytes, bytes]:
    """Read through the header terminator; returns (head, leftover bytes)."""

    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise WebSocketError("connection closed during websocket upgrade")
        data += chunk
        if len(data) > limit:
            raise WebSocketError("websocket upgrade response too large")
    head, _, rest = data.partition(b"\r\n\r\n")
    return head + b"\r\n\r\n", rest


class _BufferedSocket:
    """Socket wrapper preserving bytes read past the upgrade headers."""

    def __init__(self, sock: socket.socket, buffered: bytes = b"") -> None:
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


def ws_connect(url: str, *, timeout: float) -> socket.socket:
    """Open one client WebSocket to a ws:// or wss:// URL."""

    parts = urlsplit(url)
    if parts.scheme not in {"ws", "wss"} or not parts.hostname:
        raise WebSocketError("event source URL must use ws:// or wss://")
    tls = parts.scheme == "wss"
    port = parts.port or (443 if tls else 80)
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    sock = socket.create_connection((parts.hostname, port), timeout=timeout)
    try:
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
            raise WebSocketError(f"websocket upgrade refused: {status_line!r}")
        expected = base64.b64encode(
            hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()
        )
        if expected.lower() not in response.lower():
            raise WebSocketError("websocket accept key mismatch")
        return _BufferedSocket(sock, rest)  # type: ignore[return-value]
    except BaseException:
        sock.close()
        raise


__all__ = [
    "MAX_MESSAGE_BYTES",
    "WebSocketError",
    "iter_messages",
    "recv_frame",
    "send_frame",
    "ws_connect",
]
