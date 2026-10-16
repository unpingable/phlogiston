"""Loopback fake PDS for offline communityd tests and acceptance wiring.

Implements the four XRPC procedures the real adapters use —
``com.atproto.server.createSession``, ``com.atproto.repo.getRecord``,
``com.atproto.repo.listRecords``, and ``com.atproto.repo.createRecord`` —
with realistic response shapes over ``http.server`` on 127.0.0.1.  It never
touches a real network or real credentials; the fixture app password and
bearer token are test canaries.  Response-drop injection lets ambiguous-write
tests prove the writer's readback resolution: exactly one ``createRecord``
reaches the server and the deterministic rkey settles the outcome.
"""

from __future__ import annotations

import json
import threading
import urllib.parse
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Literal

from community_model import RecordRef, canonical_json_bytes, cid_for_dag_cbor

DropMode = Literal["before_commit", "after_commit"]


class FakePds:
    """A single-thread-safe in-memory PDS speaking XRPC on loopback."""

    def __init__(
        self,
        *,
        session_did: str,
        identifier: str = "community.test",
        app_password: str = "test-app-password-canary",
        page_limit: int = 2,
    ) -> None:
        self.session_did = session_did
        self.identifier = identifier
        self.app_password = app_password
        self.token = "loopback-test-access-token"
        self.page_limit = page_limit
        self.records: dict[tuple[str, str, str], tuple[str, Mapping[str, object]]] = {}
        self.requests: list[str] = []
        self.created: list[tuple[str, str, str]] = []
        self.create_record_attempts = 0
        self.session_attempts = 0
        self.drop_mode: DropMode | None = None
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.fake_pds = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> FakePds:
        self._thread.start()
        return self

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def __enter__(self) -> FakePds:
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def seed(
        self, repo: str, collection: str, rkey: str, record: Mapping[str, object]
    ) -> RecordRef:
        """Place a record as pre-existing repository content."""

        cid = cid_for_dag_cbor(canonical_json_bytes(record))
        self.records[(repo, collection, rkey)] = (cid, dict(record))
        return RecordRef(uri=f"at://{repo}/{collection}/{rkey}", cid=cid)

    def drop(self, repo: str, collection: str, rkey: str) -> None:
        self.records.pop((repo, collection, rkey), None)

    def get(self, repo: str, collection: str, rkey: str) -> RecordRef | None:
        stored = self.records.get((repo, collection, rkey))
        if stored is None:
            return None
        return RecordRef(uri=f"at://{repo}/{collection}/{rkey}", cid=stored[0])


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def fake(self) -> FakePds:
        return self.server.fake_pds  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: object) -> None:
        # Log only the request line shape; POST bodies (credentials) are
        # never rendered into the request log.
        self.fake.requests.append(f"{self.command} {self.path}")

    def do_GET(self) -> None:
        split = urllib.parse.urlsplit(self.path)
        params = {
            key: values[0] for key, values in urllib.parse.parse_qs(split.query).items()
        }
        if split.path == "/xrpc/com.atproto.repo.getRecord":
            self._get_record(params)
        elif split.path == "/xrpc/com.atproto.repo.listRecords":
            self._list_records(params)
        else:
            self._send(
                404, {"error": "MethodNotImplemented", "message": "unknown XRPC"}
            )

    def do_POST(self) -> None:
        split = urllib.parse.urlsplit(self.path)
        body = self._read_body()
        if body is None:
            return
        if split.path == "/xrpc/com.atproto.server.createSession":
            self._create_session(body)
        elif split.path == "/xrpc/com.atproto.repo.createRecord":
            self._create_record(body)
        else:
            self._send(
                404, {"error": "MethodNotImplemented", "message": "unknown XRPC"}
            )

    def _read_body(self) -> Mapping[str, object] | None:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        raw = self.rfile.read(min(length, 1 << 20))
        try:
            decoded = json.loads(raw) if raw else {}
        except ValueError:
            self._send(400, {"error": "InvalidRequest", "message": "body is not JSON"})
            return None
        if not isinstance(decoded, dict):
            self._send(
                400, {"error": "InvalidRequest", "message": "body is not an object"}
            )
            return None
        return decoded

    def _send(self, status: int, payload: Mapping[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _drop_connection(self) -> None:
        """Close without any response, simulating a lost commit reply."""

        self.close_connection = True

    def _get_record(self, params: Mapping[str, str]) -> None:
        key = (
            params.get("repo", ""),
            params.get("collection", ""),
            params.get("rkey", ""),
        )
        stored = self.fake.records.get(key)
        if stored is None:
            self._send(400, {"error": "RecordNotFound", "message": "no such record"})
            return
        cid, value = stored
        self._send(
            200,
            {"uri": f"at://{key[0]}/{key[1]}/{key[2]}", "cid": cid, "value": value},
        )

    def _list_records(self, params: Mapping[str, str]) -> None:
        repo = params.get("repo", "")
        collection = params.get("collection", "")
        try:
            limit = int(params.get("limit", "100"))
            offset = int(params.get("cursor", "0"))
        except ValueError:
            self._send(400, {"error": "InvalidRequest", "message": "bad limit/cursor"})
            return
        limit = max(1, min(limit, self.fake.page_limit))
        keys = sorted(
            key for key in self.fake.records if key[0] == repo and key[1] == collection
        )
        page = keys[offset : offset + limit]
        entries = [
            {
                "uri": f"at://{key[0]}/{key[1]}/{key[2]}",
                "cid": self.fake.records[key][0],
                "value": self.fake.records[key][1],
            }
            for key in page
        ]
        payload: dict[str, object] = {"records": entries}
        if offset + limit < len(keys):
            payload["cursor"] = str(offset + limit)
        self._send(200, payload)

    def _create_session(self, body: Mapping[str, object]) -> None:
        self.fake.session_attempts += 1
        if (
            body.get("identifier") != self.fake.identifier
            or body.get("password") != self.fake.app_password
        ):
            self._send(
                401,
                {"error": "AuthenticationRequired", "message": "invalid credentials"},
            )
            return
        self._send(
            200,
            {
                "accessJwt": self.fake.token,
                "refreshJwt": f"{self.fake.token}-refresh",
                "handle": self.fake.identifier,
                "did": self.fake.session_did,
            },
        )

    def _create_record(self, body: Mapping[str, object]) -> None:
        if self.headers.get("Authorization") != f"Bearer {self.fake.token}":
            self._send(401, {"error": "AuthenticationRequired", "message": "bad token"})
            return
        self.fake.create_record_attempts += 1
        if self.fake.drop_mode == "before_commit":
            self._drop_connection()
            return
        repo = body.get("repo")
        collection = body.get("collection")
        rkey = body.get("rkey")
        record = body.get("record")
        if (
            not isinstance(repo, str)
            or not isinstance(collection, str)
            or not isinstance(rkey, str)
            or not isinstance(record, dict)
        ):
            self._send(400, {"error": "InvalidRequest", "message": "malformed write"})
            return
        key = (repo, collection, rkey)
        if key in self.fake.records:
            self._send(
                400, {"error": "InvalidRequest", "message": "record already exists"}
            )
            return
        cid = cid_for_dag_cbor(canonical_json_bytes(record))
        self.fake.records[key] = (cid, record)
        self.fake.created.append(key)
        if self.fake.drop_mode == "after_commit":
            self._drop_connection()
            return
        self._send(200, {"uri": f"at://{repo}/{collection}/{rkey}", "cid": cid})


__all__ = ["DropMode", "FakePds"]
