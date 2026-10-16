from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


@dataclass(frozen=True, slots=True)
class HttpFixtureResponse:
    status: int = 200
    body: bytes = b""
    headers: Mapping[str, str] = field(default_factory=dict)
    declared_length: int | None = None
    delay_seconds: float = 0.0
    close_after_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class HttpFixtureRequest:
    method: str
    target: str
    headers: Mapping[str, str]


Dispatch = Callable[[HttpFixtureRequest], HttpFixtureResponse]


class _FixtureServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, dispatch: Dispatch) -> None:
        self.dispatch = dispatch
        self.requests: list[HttpFixtureRequest] = []
        super().__init__(("127.0.0.1", 0), _FixtureHandler)


class _FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        server = self.server
        assert isinstance(server, _FixtureServer)
        request = HttpFixtureRequest(
            method="GET",
            target=self.path,
            headers={name.lower(): value for name, value in self.headers.items()},
        )
        server.requests.append(request)
        response = server.dispatch(request)
        if response.delay_seconds:
            time.sleep(response.delay_seconds)
        self.send_response(response.status)
        supplied_headers = {name.lower() for name in response.headers}
        for name, value in response.headers.items():
            self.send_header(name, value)
        if "content-length" not in supplied_headers:
            length = (
                response.declared_length
                if response.declared_length is not None
                else len(response.body)
            )
            self.send_header("Content-Length", str(length))
        self.end_headers()
        body = response.body
        if response.close_after_bytes is not None:
            body = body[: response.close_after_bytes]
        try:
            self.wfile.write(body)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        if response.close_after_bytes is not None:
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()

    def log_message(self, format: str, *args: object) -> None:
        return


@dataclass(slots=True)
class RunningHttpFixture:
    server: _FixtureServer
    thread: threading.Thread

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def requests(self) -> tuple[HttpFixtureRequest, ...]:
        return tuple(self.server.requests)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def http_fixture_factory() -> Iterator[Callable[[Dispatch], RunningHttpFixture]]:
    fixtures: list[RunningHttpFixture] = []

    def create(dispatch: Dispatch) -> RunningHttpFixture:
        server = _FixtureServer(dispatch)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        fixture = RunningHttpFixture(server, thread)
        fixtures.append(fixture)
        return fixture

    yield create
    for fixture in reversed(fixtures):
        fixture.close()
