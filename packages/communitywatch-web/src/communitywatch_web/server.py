"""Stdlib HTTP binding for the canonical V0 AppView (GET/HEAD/OPTIONS only).

The server adds the security and public-read CORS headers to every response,
answers every other method with 405, and never reflects request data into
headers.  OPTIONS is answered as a browser preflight for the public read
routes; it reads no request header and grants no method beyond GET and HEAD.
"""

from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Protocol

from community_model import canonical_json_bytes

from .app import CORS_HEADERS, JSON_CONTENT_TYPE, SECURITY_HEADERS, WebApp

_LOGGER = logging.getLogger("communitywatch_web")


class HttpApplication(Protocol):
    """Small replaceable request-handler boundary for read-only web apps."""

    def handle(self, method: str, target: str): ...


def make_server(
    app: WebApp | HttpApplication, *, host: str, port: int
) -> ThreadingHTTPServer:
    """Bind a threading HTTP server for the app on the given address."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "communitywatch-web/0.1.0"
        protocol_version = "HTTP/1.1"

        def __getattr__(self, name: str):
            # Any method without an explicit do_* implementation is still an
            # unsupported method: answer 405 through the app, never 501.
            if name.startswith("do_"):
                method = name[3:]

                def _unsupported() -> None:
                    self._respond(method)

                return _unsupported
            raise AttributeError(name)

        def _respond(self, method: str) -> None:
            response = app.handle(method, self.path)
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            security_headers = getattr(app, "security_headers", SECURITY_HEADERS)
            for name, value in (
                *security_headers,
                *CORS_HEADERS,
                *response.extra_headers,
            ):
                self.send_header(name, value)
            self.end_headers()
            if method != "HEAD" and response.body:
                self.wfile.write(response.body)
            if method not in ("GET", "HEAD", "OPTIONS"):
                # A rejected method may carry an unread request body; close
                # rather than risk keep-alive desynchronization.
                self.close_connection = True

        def send_error(
            self,
            code: int,
            message: str | None = None,
            explain: str | None = None,
        ) -> None:
            # Low-level HTTP failures (bad request lines, overlong targets)
            # keep the JSON error contract and the security headers.
            body = canonical_json_bytes(
                {"error": "bad_request", "message": "malformed request"}
            )
            self.send_response(code)
            self.send_header("Content-Type", JSON_CONTENT_TYPE)
            self.send_header("Content-Length", str(len(body)))
            for name, value in (*SECURITY_HEADERS, *CORS_HEADERS):
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            self.close_connection = True

        def do_GET(self) -> None:
            self._respond("GET")

        def do_HEAD(self) -> None:
            self._respond("HEAD")

        def do_POST(self) -> None:
            self._respond("POST")

        def do_PUT(self) -> None:
            self._respond("PUT")

        def do_PATCH(self) -> None:
            self._respond("PATCH")

        def do_DELETE(self) -> None:
            self._respond("DELETE")

        def do_OPTIONS(self) -> None:
            self._respond("OPTIONS")

        def do_TRACE(self) -> None:
            self._respond("TRACE")

        def log_message(self, format: str, *args: object) -> None:
            _LOGGER.info("%s - %s", self.address_string(), format % args)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server
