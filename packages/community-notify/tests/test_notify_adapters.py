from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from community_notify import cli
from community_notify.adapters import (
    HttpProjectionSource,
    HttpsWebhookSender,
    WebhookError,
)

COMMUNITY = "did:plc:exampleparticipantabcdef"
CID = "bafyreidfayvfuwqa7qlnopdjiqrxzs6blmoeu4rujcjtnci5beludirz2a"


class FakeServer:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, bytes]] = []
        self.status = 200
        self.truncate = False
        self.documents: dict[str, object] = {}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                outer.requests.append((self.command, self.path, body))
                payload = json.dumps(outer.documents.get(self.path, {})).encode()
                self.send_response(outer.status)
                if 300 <= outer.status < 400:
                    self.send_header("Location", "http://127.0.0.1:1/elsewhere")
                self.send_header("Content-Type", "application/json")
                if outer.truncate:
                    # A chunked answer cut off mid-chunk: the client's read
                    # of the answer fails after the POST was accepted.
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    self.wfile.write(b"40\r\n" + payload[:2])
                    self.wfile.flush()
                    self.close_connection = True
                    return
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = _answer
            do_POST = _answer

            def log_message(self, *args: object) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def server() -> Iterator[FakeServer]:
    fake = FakeServer()
    try:
        yield fake
    finally:
        fake.close()


def plain_http_sender(url: str) -> HttpsWebhookSender:
    """The sender refuses http; tests reach the loopback fake by patching."""
    sender = HttpsWebhookSender("https://room.example.test/hook", timeout=2)
    sender._url = url
    return sender


def test_sender_refuses_non_https() -> None:
    with pytest.raises(ValueError, match="https"):
        HttpsWebhookSender("http://room.example.test/hook")
    assert "room.example" not in repr(HttpsWebhookSender("https://room.example.test/x"))


def test_sender_posts_one_json_object(server: FakeServer) -> None:
    plain_http_sender(server.origin + "/hook/secret-token").send({"content": "hello"})
    assert server.requests == [("POST", "/hook/secret-token", b'{"content":"hello"}')]


@pytest.mark.parametrize("status", [302, 429, 500])
def test_sender_errors_never_follow_redirects_or_leak_the_url(
    server: FakeServer, status: int
) -> None:
    server.status = status
    with pytest.raises(WebhookError) as caught:
        plain_http_sender(server.origin + "/hook/secret-token").send({"text": "x"})
    assert "secret-token" not in str(caught.value)
    assert len(server.requests) == 1


def test_sender_truncated_answer_is_a_webhook_error(server: FakeServer) -> None:
    server.truncate = True
    with pytest.raises(WebhookError, match="unreadable") as caught:
        plain_http_sender(server.origin + "/hook/secret-token").send({"text": "x"})
    assert "secret-token" not in str(caught.value)
    assert len(server.requests) == 1


def test_sender_unreachable_is_a_webhook_error() -> None:
    with pytest.raises(WebhookError, match="unreachable"):
        plain_http_sender("http://127.0.0.1:1/hook/secret-token").send({"text": "x"})


def test_projection_source_reads_json_and_reports_outage(server: FakeServer) -> None:
    server.documents["/a"] = {"communityDid": COMMUNITY}
    assert HttpProjectionSource(server.origin).get("/a") == {"communityDid": COMMUNITY}
    server.status = 503
    with pytest.raises(OSError, match="acquisition failed"):
        HttpProjectionSource(server.origin).get("/a")


def test_cli_once_against_a_fake_projection(
    server: FakeServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = f"/api/v0/communities/{COMMUNITY}"
    server.documents[f"{base}/moderation-queue"] = {
        "communityDid": COMMUNITY,
        "submissions": [
            {
                "submission": {
                    "uri": "at://did:plc:alice/app.phlogiston.community.submit/p1",
                    "cid": CID,
                },
                "subject": {
                    "uri": "at://did:plc:alice/app.bsky.feed.post/p1",
                    "cid": CID,
                },
            }
        ],
        "snapshot": {},
    }
    server.documents[f"{base}/discussions"] = {
        "communityDid": COMMUNITY,
        "discussions": [],
        "snapshot": {},
    }
    config = tmp_path / "notify.toml"
    config.write_text(f"""
projection_origin = "{server.origin}"
community_did = "{COMMUNITY}"
community_name = "Test Community"
public_base_url = "https://community.example.test"
webhook_url = "https://room.invalid/hook"
webhook_payload_key = "content"
poll_interval_seconds = 30
cursor_path = "{tmp_path / "cursor.json"}"
""")
    assert cli.main(["--config", str(config), "--once"]) == 0
    assert json.loads(capsys.readouterr().out)["baselined"] == 1
    assert [method for method, _, _ in server.requests] == ["GET", "GET"]


def test_cli_refuses_an_http_webhook(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "notify.toml"
    config.write_text(f"""
projection_origin = "http://127.0.0.1:8080"
community_did = "{COMMUNITY}"
community_name = "Test Community"
public_base_url = "https://community.example.test"
webhook_url = "http://room.invalid/hook/secret-token"
webhook_payload_key = "content"
poll_interval_seconds = 30
cursor_path = "{tmp_path / "cursor.json"}"
""")
    assert cli.main(["--config", str(config), "--once"]) == 1
    error = capsys.readouterr().err
    assert "webhook_url must be a credential-free https URL" in error
    assert "secret-token" not in error
    assert not (tmp_path / "cursor.json").exists()
