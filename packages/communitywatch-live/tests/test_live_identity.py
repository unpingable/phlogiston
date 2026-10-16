from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from community_model import ValidationError
from communitywatch_live import PlcDirectoryIdentityQualifier

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "tests/fixtures/spaces-alpha/reference/sa9e-hosted-alpha.json"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        body, status, headers = self.server.dispatch(self.path)  # type: ignore[attr-defined]
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


class _Server:
    def __init__(
        self, dispatch: Callable[[str], tuple[bytes, int, dict[str, str]]]
    ) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.dispatch = dispatch  # type: ignore[attr-defined]
        self.server = server
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def origin(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def manifest() -> dict[str, object]:
    value = json.loads(MANIFEST.read_bytes())
    assert isinstance(value, dict)
    return value


def _audit(manifest: dict[str, object]) -> bytes:
    return json.dumps(
        manifest["plcAudit"], sort_keys=True, separators=(",", ":")
    ).encode()


def test_plc_audit_acquisition_qualifies_repo_and_space_host(
    tmp_path: Path, manifest: dict[str, object]
) -> None:
    identity = manifest["identity"]
    assert isinstance(identity, dict)
    did = str(identity["did"])
    expected_path = f"/{did}/log/audit"
    server = _Server(
        lambda path: (
            (_audit(manifest), 200, {"Content-Type": "application/json"})
            if path == expected_path
            else (b"no", 404, {})
        )
    )
    try:
        qualifier = PlcDirectoryIdentityQualifier(
            tmp_path,
            directory_origin=server.origin,
            allow_loopback_fixture=True,
        )
        when = datetime(2026, 8, 24, 12, tzinfo=UTC)
        repo = qualifier.qualify(did, evaluated_at=when)
        authority = qualifier.qualify_space_authority(did, evaluated_at=when)
    finally:
        server.close()

    assert repo.did == did
    assert repo.repo_host == identity["repoHost"]
    assert repo.signature_algorithm == "ES256K"
    assert authority.did == did
    assert authority.authority_host == identity["repoHost"]
    assert len(tuple(tmp_path.glob("*.audit.json"))) == 1
    assert len(tuple(tmp_path.glob("*.receipt.json"))) == 1
    receipt = json.loads(next(tmp_path.glob("*.receipt.json")).read_bytes())
    assert receipt["verifiedClaims"] == ["exact_http_response_bytes"]
    assert receipt["explicitNonClaims"] == [
        "directory_honesty",
        "globally_current",
        "governance_authority",
    ]


def test_plc_audit_refuses_redirect_duplicate_json_and_did_mismatch(
    tmp_path: Path, manifest: dict[str, object]
) -> None:
    identity = manifest["identity"]
    assert isinstance(identity, dict)
    did = str(identity["did"])
    when = datetime(2026, 8, 24, 12, tzinfo=UTC)

    redirect = _Server(lambda _: (b"", 302, {"Location": "https://elsewhere.invalid/"}))
    try:
        with pytest.raises(ValidationError, match="redirect refused"):
            PlcDirectoryIdentityQualifier(
                tmp_path / "redirect",
                directory_origin=redirect.origin,
                allow_loopback_fixture=True,
            ).qualify(did, evaluated_at=when)
    finally:
        redirect.close()

    duplicate = _Server(lambda _: (b'[{"did":"a","did":"b"}]', 200, {}))
    try:
        with pytest.raises(ValidationError, match="JSON is invalid"):
            PlcDirectoryIdentityQualifier(
                tmp_path / "duplicate",
                directory_origin=duplicate.origin,
                allow_loopback_fixture=True,
            ).qualify(did, evaluated_at=when)
    finally:
        duplicate.close()

    changed = json.loads(_audit(manifest))
    changed[0]["did"] = "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa"
    mismatch = _Server(
        lambda _: (
            json.dumps(changed).encode(),
            200,
            {"Content-Type": "application/json"},
        )
    )
    try:
        with pytest.raises(ValidationError, match="entry differs"):
            PlcDirectoryIdentityQualifier(
                tmp_path / "mismatch",
                directory_origin=mismatch.origin,
                allow_loopback_fixture=True,
            ).qualify(did, evaluated_at=when)
    finally:
        mismatch.close()


def test_plc_audit_refuses_non_boolean_nullification(
    tmp_path: Path, manifest: dict[str, object]
) -> None:
    identity = manifest["identity"]
    assert isinstance(identity, dict)
    changed = json.loads(_audit(manifest))
    changed[0]["nullified"] = "false"
    server = _Server(lambda _: (json.dumps(changed).encode(), 200, {}))
    try:
        with pytest.raises(ValidationError, match="entry differs"):
            PlcDirectoryIdentityQualifier(
                tmp_path,
                directory_origin=server.origin,
                allow_loopback_fixture=True,
            ).qualify(
                str(identity["did"]),
                evaluated_at=datetime(2026, 8, 24, 12, tzinfo=UTC),
            )
    finally:
        server.close()
