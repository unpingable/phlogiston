"""In-process HTTP binding tests: headers, HEAD, 405, keep-alive."""

from __future__ import annotations

import http.client
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from communitywatch import ObserverStore, ProjectionQuery
from communitywatch_web.app import SECURITY_HEADERS, WebApp
from communitywatch_web.server import make_server
from tests.web_support import APP_TIME, COMMUNITY_DID, SLUG


@pytest.fixture()
def server(seeded_db: Path) -> Iterator:
    store = ObserverStore(seeded_db, community_did=COMMUNITY_DID, read_only=True)
    app = WebApp(
        ProjectionQuery(store, slug=SLUG),
        community_did=COMMUNITY_DID,
        slug=SLUG,
        stale_threshold_seconds=0,
        now=lambda: APP_TIME,
    )
    httpd = make_server(app, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


def _request(
    server,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
):
    host, port = server.server_address[:2]
    connection = http.client.HTTPConnection(host, port, timeout=10)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    payload = response.read()
    headers = dict(response.getheaders())
    connection.close()
    return response.status, headers, payload


def test_security_headers_on_every_response(server) -> None:
    for method, path, expected in (
        ("GET", f"/c/{SLUG}", 200),
        ("GET", "/health", 200),
        ("GET", "/nope", 404),
        ("POST", "/health", 405),
        ("DELETE", f"/c/{SLUG}", 405),
    ):
        status, headers, _ = _request(server, method, path)
        assert status == expected, (method, path)
        for name, value in SECURITY_HEADERS:
            assert headers.get(name) == value, (method, path, name)


def test_get_and_head_over_http(server) -> None:
    status, headers, payload = _request(server, "GET", f"/c/{SLUG}")
    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    assert b"loud fans" in payload

    status, headers, head_payload = _request(server, "HEAD", f"/c/{SLUG}")
    assert status == 200
    assert head_payload == b""
    assert int(headers["Content-Length"]) == len(payload)


def test_post_with_a_body_is_405_and_does_not_desync(server) -> None:
    status, headers, payload = _request(
        server, "POST", f"/api/v0/communities/{COMMUNITY_DID}/posts", body=b"{}"
    )
    assert status == 405
    assert headers.get("Allow") == "GET, HEAD, OPTIONS"
    assert b"method_not_allowed" in payload
    # The server stays healthy for subsequent requests.
    status, _, _ = _request(server, "GET", "/health")
    assert status == 200


def test_percent_encoded_traversal_never_reaches_the_disk(server) -> None:
    status, _, payload = _request(server, "GET", "/c/%2e%2e%2f%2e%2e%2fetc%2fpasswd")
    assert status in (400, 404)
    assert b"root:" not in payload


def test_arbitrary_methods_are_405_never_501(server) -> None:
    for method in ("PROPFIND", "CONNECT", "MKCOL"):
        status, headers, payload = _request(server, method, "/health")
        assert status == 405, method
        assert headers.get("Allow") == "GET, HEAD, OPTIONS"
        assert b"method_not_allowed" in payload
        for name, value in SECURITY_HEADERS:
            assert headers.get(name) == value, (method, name)


# --- Public-read CORS -------------------------------------------------------
#
# These routes are public, unauthenticated, read-only representations, so they
# are readable cross-origin.  The tests below pin that the allowance is exactly
# that and nothing more: no credentials, and no method beyond the read methods.

CROSS_ORIGIN = {"Origin": "https://client.example"}


def test_get_without_an_origin_is_unchanged_and_still_carries_cors(server) -> None:
    status, headers, payload = _request(server, "GET", "/health")
    assert status == 200
    assert b"projectionStatus" in payload
    # The header does not depend on the request: nothing is reflected, so an
    # ordinary same-origin or non-browser read sees exactly what a browser does.
    assert headers.get("Access-Control-Allow-Origin") == "*"
    assert "Access-Control-Allow-Credentials" not in headers


def test_get_with_an_arbitrary_origin_is_allowed(server) -> None:
    for path in (f"/c/{SLUG}", "/health", f"/api/v0/communities/{COMMUNITY_DID}/posts"):
        status, headers, _ = _request(server, "GET", path, headers=CROSS_ORIGIN)
        assert status == 200, path
        assert headers.get("Access-Control-Allow-Origin") == "*", path
        assert "Access-Control-Allow-Credentials" not in headers, path


def test_head_with_an_arbitrary_origin_is_allowed(server) -> None:
    status, headers, payload = _request(
        server, "HEAD", f"/c/{SLUG}", headers=CROSS_ORIGIN
    )
    assert status == 200
    assert payload == b""
    assert headers.get("Access-Control-Allow-Origin") == "*"
    assert "Access-Control-Allow-Credentials" not in headers


def test_preflight_is_answered_for_the_public_read_routes(server) -> None:
    preflight = {**CROSS_ORIGIN, "Access-Control-Request-Method": "GET"}
    for path in (f"/c/{SLUG}", "/health", f"/api/v0/communities/{COMMUNITY_DID}/posts"):
        status, headers, payload = _request(server, "OPTIONS", path, headers=preflight)
        assert status == 204, path
        assert payload == b"", path
        assert headers.get("Access-Control-Allow-Origin") == "*", path
        # Only the read methods are advertised, so a preflight for a mutating
        # method is refused here rather than at the request it precedes.
        assert headers.get("Access-Control-Allow-Methods") == "GET, HEAD, OPTIONS", path
        assert "Access-Control-Allow-Credentials" not in headers, path


def test_preflight_still_refuses_a_malformed_target(server) -> None:
    status, _, _ = _request(server, "OPTIONS", "/c/%2e%2e%2fetc", headers=CROSS_ORIGIN)
    assert status in (400, 404)


def test_mutating_methods_stay_rejected_and_cors_does_not_admit_them(server) -> None:
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        status, headers, payload = _request(
            server, method, "/health", headers=CROSS_ORIGIN
        )
        assert status == 405, method
        assert b"method_not_allowed" in payload, method
        assert headers.get("Allow") == "GET, HEAD, OPTIONS", method
        assert "Access-Control-Allow-Credentials" not in headers, method


def test_no_response_ever_carries_allow_credentials(server) -> None:
    for method, path in (
        ("GET", f"/c/{SLUG}"),
        ("GET", "/nope"),
        ("HEAD", "/health"),
        ("OPTIONS", "/health"),
        ("POST", "/health"),
    ):
        _, headers, _ = _request(server, method, path, headers=CROSS_ORIGIN)
        assert "Access-Control-Allow-Credentials" not in headers, (method, path)
