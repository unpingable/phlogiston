"""Tests for the protected V0 exercise harness (loopback fake servers only).

No test in this module touches the network beyond 127.0.0.1 listeners
created by the test itself. The harness self-pin digest is always computed
from the real ``governance/tools/v0_exercise.py`` at test time; it is never
hardcoded.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import common
import evidence_store
import pytest
import v0_exercise
import v0_gate
import validators

from community_model import RecordRef, admission_rkey, cid_for_dag_cbor, removal_rkey

DID = "did:plc:abcdefghijklmnopqrstuvwx"
KIND = "app.bsky.feed.post"

POST = v0_exercise.POST_COLLECTION
SUBMIT = v0_exercise.SUBMIT_COLLECTION
ADMISSION = v0_exercise.ADMISSION_COLLECTION
MOD_ACTION = v0_exercise.MOD_ACTION_COLLECTION
X7_KINDS = sorted([POST, SUBMIT, ADMISSION, MOD_ACTION])
X7_TOKEN = "x7-test-token"
X7_PASSWORD = "x7-test-app-password"
X7_JWT = "x7-test-access-jwt"


# --- packet builders ----------------------------------------------------------


def _harness_pin() -> tuple[int, str]:
    data = Path(v0_exercise.__file__).read_bytes()
    return len(data), common.sha256_digest(data)


def build_packet(fixtures_dir, tmp_path, **overrides) -> dict:
    packet = json.loads(
        (
            fixtures_dir / "valid" / "controller-entry-packet__cep-live-x6.json"
        ).read_text(encoding="utf-8")
    )
    payload = packet["launch_payload"]
    live = payload["live_exercise"]
    live["target_allow_list"] = sorted(overrides.get("targets", []))
    live["subject_allow_list"] = sorted(overrides.get("subjects", [DID]))
    live["allowed_record_kinds"] = sorted(overrides.get("kinds", [KIND]))
    live["ceilings"].update(
        overrides.get(
            "ceilings",
            {
                "max_requests": 50,
                "max_events": 10,
                "max_proof_fetches": 5,
                "max_bytes": 1 << 20,
                "max_wall_clock_seconds": 15,
                "max_writes": 0,
            },
        )
    )
    live["retry"].update(
        overrides.get(
            "retry",
            {
                "request_timeout_seconds": 2,
                "max_retries": 1,
                "retry_backoff_seconds": 0,
            },
        )
    )
    if "operation" in overrides:
        live["operation_id"] = overrides["operation"]
    if "idempotency" in overrides:
        live["idempotency_input"] = overrides["idempotency"]
    payload["network_mode"] = overrides.get("network", "public_read")
    payload["credential_mode"] = overrides.get("credential", "none")
    payload["evidence_policy"]["destination_uri"] = f"file://{tmp_path}/evidence"
    size, digest = overrides.get("harness_pin", _harness_pin())
    live["harness"]["bytes"] = size
    live["harness"]["sha256"] = digest
    payload["live_exercise"] = live
    packet["authentication"]["payload_sha256"] = common.canonical_sha256(payload)
    return packet


def write_packet(packet: dict, tmp_path) -> Path:
    path = tmp_path / "packet.json"
    path.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
    return path


def run_harness(packet_path: Path, capsys, operation="V0-X6-READ-SMOKE"):
    code = v0_exercise.main([operation, "--packet", str(packet_path)])
    out = capsys.readouterr()
    return code, json.loads(out.out), out.err


# --- loopback fake servers ----------------------------------------------------


def _make_handler(routes: dict):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            entry = routes.get(urlsplit(self.path).path)
            if entry is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status, body = entry
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return Handler


@pytest.fixture()
def http_server_factory():
    servers = []

    def spawn(routes: dict) -> str:
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), _make_handler(routes)
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield spawn
    for server in servers:
        server.shutdown()
        server.server_close()


class FakeWsServer:
    """A minimal WebSocket server speaking unmasked server frames."""

    def __init__(
        self,
        messages: list[str],
        close: bool = True,
        ping_interval: float | None = None,
    ):
        self.messages = messages
        self.close = close
        self.ping_interval = ping_interval
        self.path_seen: str | None = None
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.origin = f"ws://127.0.0.1:{self.listener.getsockname()[1]}"
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        try:
            conn, _ = self.listener.accept()
            conn.settimeout(15)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                data += chunk
            request = data.decode("ascii")
            self.path_seen = request.split("\r\n", 1)[0].split(" ")[1]
            key = next(
                line.split(":", 1)[1].strip()
                for line in request.split("\r\n")
                if line.lower().startswith("sec-websocket-key")
            )
            accept = base64.b64encode(
                hashlib.sha1((key + v0_exercise.WS_GUID).encode("ascii")).digest()
            ).decode("ascii")
            conn.sendall(
                (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n"
                    "\r\n"
                ).encode("ascii")
            )
            for message in self.messages:
                v0_exercise.ws_send_frame(
                    conn, v0_exercise.OP_TEXT, message.encode("utf-8"), mask=False
                )
            if self.ping_interval is not None:
                # Hold the stream open with control-frame traffic only, the
                # way a real relay keepalive does.
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    v0_exercise.ws_send_frame(
                        conn, v0_exercise.OP_PING, b"ka", mask=False
                    )
                    time.sleep(self.ping_interval)
            if self.close:
                v0_exercise.ws_send_frame(conn, v0_exercise.OP_CLOSE, mask=False)
            while conn.recv(4096):
                pass
        except OSError:
            pass
        finally:
            self.listener.close()


def _did_doc(did: str, pds_origin: str) -> bytes:
    return json.dumps(
        {
            "id": did,
            "service": [
                {
                    "id": "#atproto_pds",
                    "type": "AtprotoPersonalDataServer",
                    "serviceEndpoint": pds_origin,
                }
            ],
        }
    ).encode("utf-8")


def _commit_event(did: str, rkey: str, cid: str, collection: str = KIND) -> str:
    return json.dumps(
        {
            "$type": "message",
            "payload": {
                "$type": "network.bsky.jetstream.subscribeEvents#commit",
                "did": did,
                "seq": 1,
                "time": "2026-08-14T00:00:00.000000Z",
                "operation": "create",
                "collection": collection,
                "rkey": rkey,
                "rev": "3mexample",
                "cid": cid,
            },
        }
    )


def _closed_port_origin() -> str:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}"


# --- harness end-to-end tests --------------------------------------------------


def _happy_setup(http_server_factory, events, close=True):
    pds = http_server_factory({"/xrpc/com.atproto.sync.getRecord": (200, b"CARBYTES")})
    did_origin = http_server_factory({f"/{DID}": (200, _did_doc(DID, pds))})
    ws = FakeWsServer(events, close=close)
    return pds, did_origin, ws


def test_happy_path_pass_receipt(fixtures_dir, tmp_path, http_server_factory, capsys):
    events = [_commit_event(DID, f"rkey{i}", f"cid{i}") for i in range(2)]
    pds, did_origin, ws = _happy_setup(http_server_factory, events)
    packet = build_packet(fixtures_dir, tmp_path, targets=[pds, did_origin, ws.origin])
    code, receipt, _ = run_harness(write_packet(packet, tmp_path), capsys)

    assert code == 0
    assert receipt["outcome"] == "PASS"
    assert receipt["stop_rule"] == "completed"
    assert not validators.validate_artifact("exercise-receipt", receipt)
    counters = receipt["counters"]
    assert counters["events"] == 2
    assert counters["proof_fetches"] == 2
    assert counters["writes"] == 0
    assert receipt["targets_contacted"] == sorted([pds, did_origin, ws.origin])
    assert receipt["harness_sha256"] == _harness_pin()[1]

    run_dir = tmp_path / "evidence" / receipt["receipt_id"]
    assert (run_dir / "receipt.json").is_file()
    retained = json.loads((run_dir / "receipt.json").read_text(encoding="utf-8"))
    assert retained == receipt
    assert (run_dir / "events.ndjson").read_text(encoding="utf-8").count("\n") == 2
    proofs = sorted((run_dir / "proofs").rglob("*.car"))
    assert len(proofs) == 2
    assert all(p.read_bytes() == b"CARBYTES" for p in proofs)
    roles = {a["role"] for a in receipt["artifacts"]}
    assert {"events_ndjson", "did_doc", "proof_car"} <= roles

    assert f"collections={KIND}" in ws.path_seen
    assert "dids=did%3Aplc%3A" in ws.path_seen
    assert "kinds=commit" in ws.path_seen


def test_did_web_origin_not_allow_listed(fixtures_dir, tmp_path, capsys):
    dead = _closed_port_origin()
    packet = build_packet(
        fixtures_dir,
        tmp_path,
        targets=[dead],
        subjects=["did:web:example.test"],
    )
    code, receipt, _ = run_harness(write_packet(packet, tmp_path), capsys)
    assert code == 1
    assert receipt["outcome"] == "CHECK_FAILED"
    assert receipt["stop_rule"] == "subject_origin_not_allowed"
    # refused before any socket use: nothing was contacted
    assert receipt["targets_contacted"] == []


def test_pds_origin_not_allow_listed(
    fixtures_dir, tmp_path, http_server_factory, capsys
):
    pds, did_origin, ws = _happy_setup(http_server_factory, [])
    packet = build_packet(
        fixtures_dir,
        tmp_path,
        targets=[did_origin, ws.origin],  # the PDS origin is deliberately absent
    )
    code, receipt, _ = run_harness(write_packet(packet, tmp_path), capsys)
    assert code == 1
    assert receipt["outcome"] == "CHECK_FAILED"
    assert receipt["stop_rule"] == "pds_origin_not_allowed"


def test_max_events_is_a_clean_bounded_stop(
    fixtures_dir, tmp_path, http_server_factory, capsys
):
    events = [_commit_event(DID, f"rkey{i}", f"cid{i}") for i in range(5)]
    pds, did_origin, ws = _happy_setup(http_server_factory, events, close=False)
    packet = build_packet(
        fixtures_dir,
        tmp_path,
        targets=[pds, did_origin, ws.origin],
        ceilings={"max_events": 2},
    )
    # ceilings.update keeps the other defaults; set only max_events
    live = packet["launch_payload"]["live_exercise"]
    assert live["ceilings"]["max_events"] == 2
    code, receipt, _ = run_harness(write_packet(packet, tmp_path), capsys)
    assert code == 0
    assert receipt["outcome"] == "PASS"
    assert receipt["stop_rule"] == "max_events"
    assert receipt["counters"]["events"] == 2


def test_periodic_pings_do_not_defeat_wall_clock(
    fixtures_dir, tmp_path, http_server_factory, capsys
):
    """A relay keepalive (ping traffic, no messages) must not hold the run
    open past the packet's wall-clock ceiling."""
    pds, did_origin, _ = _happy_setup(http_server_factory, [])
    ws = FakeWsServer([], close=False, ping_interval=0.2)
    packet = build_packet(
        fixtures_dir,
        tmp_path,
        targets=[pds, did_origin, ws.origin],
        ceilings={"max_wall_clock_seconds": 3},
    )
    started = time.monotonic()
    code, receipt, _ = run_harness(write_packet(packet, tmp_path), capsys)
    elapsed = time.monotonic() - started
    assert code == 0
    assert receipt["outcome"] == "PASS"
    assert receipt["stop_rule"] == "max_wall_clock_seconds"
    assert receipt["counters"]["events"] == 0
    # The 3s ceiling must actually bind; pre-fix this run hung indefinitely.
    assert elapsed < 30


def test_retry_exhaustion_receipts_failure(fixtures_dir, tmp_path, capsys):
    dead = _closed_port_origin()
    ws_dead = f"ws://{dead[len('http://') :]}"
    packet = build_packet(fixtures_dir, tmp_path, targets=[dead, ws_dead])
    code, receipt, _ = run_harness(write_packet(packet, tmp_path), capsys)
    assert code == 1
    assert receipt["outcome"] == "CHECK_FAILED"
    assert receipt["stop_rule"] == "retry_exhausted"
    assert receipt["counters"]["retries"] == 1
    assert not validators.validate_artifact("exercise-receipt", receipt)


def test_harness_pin_mismatch_is_unauthorized(fixtures_dir, tmp_path, capsys):
    packet = build_packet(
        fixtures_dir,
        tmp_path,
        targets=["http://127.0.0.1:1"],
        harness_pin=(1, "sha256:" + "0" * 64),
    )
    code, receipt, _ = run_harness(write_packet(packet, tmp_path), capsys)
    assert code == 2
    assert receipt["outcome"] == "UNAUTHORIZED"
    assert receipt["stop_rule"] == "harness_pin_mismatch"


def test_x7_without_credential_env_is_unauthorized(
    fixtures_dir, tmp_path, http_server_factory, capsys, monkeypatch
):
    """X7 refuses before any socket use when the credential ref is unset."""
    monkeypatch.delenv("V0_X7_CREDENTIAL_REF", raising=False)
    pds = FakePds()
    did_origin = http_server_factory({f"/{DID}": (200, _did_doc(DID, pds.origin))})
    ws = FakeWsServer([])
    packet = build_x7_packet(
        fixtures_dir, tmp_path, targets=[pds.origin, did_origin, ws.origin]
    )
    path = write_packet(packet, tmp_path)
    code, receipt, _ = run_harness(path, capsys, operation="V0-X7-WRITE-SMOKE")
    assert code == 2
    assert receipt["outcome"] == "UNAUTHORIZED"
    assert receipt["stop_rule"] == "credential_unavailable"
    assert receipt["targets_contacted"] == []
    # refused before any socket use: the fake servers saw nothing
    assert pds.log == []
    assert ws.path_seen is None


def test_operation_mismatch_is_unauthorized(fixtures_dir, tmp_path, capsys):
    packet = build_packet(
        fixtures_dir,
        tmp_path,
        targets=["http://127.0.0.1:1"],
        operation="V0-X7-WRITE-SMOKE",
        network="nonproduction_write",
        credential="nonproduction_external_ref",
    )
    code, receipt, _ = run_harness(write_packet(packet, tmp_path), capsys)
    assert code == 2
    assert receipt["outcome"] == "UNAUTHORIZED"
    assert receipt["stop_rule"] == "operation_mismatch"


def test_invalid_packet_is_contract_invalid(fixtures_dir, tmp_path, capsys):
    packet = build_packet(fixtures_dir, tmp_path, targets=["http://127.0.0.1:1"])
    packet["launch_payload"]["network_mode"] = "denied"  # live on denied
    packet["authentication"]["payload_sha256"] = common.canonical_sha256(
        packet["launch_payload"]
    )
    code, receipt, _ = run_harness(write_packet(packet, tmp_path), capsys)
    assert code == 2
    assert receipt["outcome"] == "CONTRACT_INVALID"
    assert "live_exercise is forbidden" in receipt["notes"]


def test_readback_tamper_is_environment_blocked(
    fixtures_dir, tmp_path, http_server_factory, capsys, monkeypatch
):
    events = [_commit_event(DID, "rkey0", "cid0")]
    pds, did_origin, ws = _happy_setup(http_server_factory, events)
    packet = build_packet(fixtures_dir, tmp_path, targets=[pds, did_origin, ws.origin])

    real_write_tree = evidence_store.write_tree

    def tampering_write_tree(src, dst):
        report = real_write_tree(src, dst)
        target = dst / "events.ndjson"
        target.write_bytes(target.read_bytes() + b"x")
        result = evidence_store.verify_tree(report["manifest"], dst)
        result["manifest"] = report["manifest"]
        return result

    monkeypatch.setattr(v0_exercise.evidence_store, "write_tree", tampering_write_tree)
    code, receipt, _ = run_harness(write_packet(packet, tmp_path), capsys)
    assert code == 1
    assert receipt["outcome"] == "ENVIRONMENT_BLOCKED"
    assert receipt["stop_rule"] == "evidence_readback_failed"


def test_stream_delivering_unpinned_collection_is_refused(
    fixtures_dir, tmp_path, http_server_factory, capsys
):
    events = [_commit_event(DID, "rkey0", "cid0", collection="evil.example.post")]
    pds, did_origin, ws = _happy_setup(http_server_factory, events)
    packet = build_packet(fixtures_dir, tmp_path, targets=[pds, did_origin, ws.origin])
    code, receipt, _ = run_harness(write_packet(packet, tmp_path), capsys)
    assert code == 1
    assert receipt["outcome"] == "CHECK_FAILED"
    assert receipt["stop_rule"] == "unexpected_collection"


# --- websocket frame layer (socketpair round-trips) ----------------------------


def test_frame_roundtrip_masked():
    left, right = socket.socketpair()
    try:
        v0_exercise.ws_send_frame(left, v0_exercise.OP_TEXT, b"hello", mask=True)
        fin, opcode, payload = v0_exercise.ws_recv_frame(right)
        assert (fin, opcode, payload) == (True, v0_exercise.OP_TEXT, b"hello")
    finally:
        left.close()
        right.close()


def test_frame_roundtrip_extended_lengths():
    left, right = socket.socketpair()
    try:
        for size in (125, 126, 200, 70000):
            payload = bytes(size)
            v0_exercise.ws_send_frame(left, v0_exercise.OP_BINARY, payload)
            fin, opcode, received = v0_exercise.ws_recv_frame(right)
            assert fin and opcode == v0_exercise.OP_BINARY
            assert received == payload
    finally:
        left.close()
        right.close()


def test_fragmented_message_is_reassembled():
    left, right = socket.socketpair()
    try:
        v0_exercise.ws_send_frame(
            left, v0_exercise.OP_TEXT, b"Hello, ", mask=True, fin=False
        )
        v0_exercise.ws_send_frame(
            left, v0_exercise.OP_CONTINUATION, b"world", mask=True, fin=True
        )
        messages = v0_exercise.iter_ws_messages(right)
        assert next(messages) == b"Hello, world"
    finally:
        left.close()
        right.close()


def test_ping_is_answered_with_pong():
    left, right = socket.socketpair()
    received = []

    def reader():
        for message in v0_exercise.iter_ws_messages(right):
            received.append(message)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    try:
        v0_exercise.ws_send_frame(left, v0_exercise.OP_PING, b"ping-body", mask=False)
        fin, opcode, payload = v0_exercise.ws_recv_frame(left)
        assert fin
        assert opcode == v0_exercise.OP_PONG
        assert payload == b"ping-body"
        v0_exercise.ws_send_frame(left, v0_exercise.OP_CLOSE, mask=False)
        thread.join(timeout=5)
        assert received == []
    finally:
        left.close()
        right.close()


# --- packet / receipt semantic validation --------------------------------------


def _validate_live_packet(fixtures_dir, mutate) -> list[str]:
    packet = json.loads(
        (
            fixtures_dir / "valid" / "controller-entry-packet__cep-live-x6.json"
        ).read_text(encoding="utf-8")
    )
    payload = packet["launch_payload"]
    mutate(payload)
    packet["authentication"]["payload_sha256"] = common.canonical_sha256(payload)
    return validators.validate_artifact("controller-entry-packet", packet)


class TestLiveExerciseSemantics:
    def test_live_exercise_required_when_not_denied(self, fixtures_dir):
        problems = _validate_live_packet(fixtures_dir, lambda p: p.pop("live_exercise"))
        assert any("live_exercise is required" in p for p in problems)

    def test_x6_rejects_nonproduction_modes(self, fixtures_dir):
        def mutate(payload):
            payload["network_mode"] = "nonproduction_write"
            payload["credential_mode"] = "nonproduction_external_ref"

        problems = _validate_live_packet(fixtures_dir, mutate)
        assert any("requires network/credential modes" in p for p in problems)

    def test_x7_with_nonproduction_modes_is_valid(self, fixtures_dir):
        def mutate(payload):
            payload["network_mode"] = "nonproduction_write"
            payload["credential_mode"] = "nonproduction_external_ref"
            live = payload["live_exercise"]
            live["operation_id"] = "V0-X7-WRITE-SMOKE"
            live["ceilings"]["max_writes"] = 2

        assert _validate_live_packet(fixtures_dir, mutate) == []

    def test_http_origin_off_loopback_rejected(self, fixtures_dir):
        def mutate(payload):
            payload["live_exercise"]["target_allow_list"] = ["http://example.com"]

        problems = _validate_live_packet(fixtures_dir, mutate)
        assert any("loopback" in p for p in problems)

    def test_origin_with_path_rejected(self, fixtures_dir):
        def mutate(payload):
            payload["live_exercise"]["target_allow_list"] = ["https://example.com/xrpc"]

        problems = _validate_live_packet(fixtures_dir, mutate)
        assert any("path, query, and fragment" in p for p in problems)

    def test_origin_with_userinfo_rejected(self, fixtures_dir):
        def mutate(payload):
            payload["live_exercise"]["target_allow_list"] = ["https://user@example.com"]

        problems = _validate_live_packet(fixtures_dir, mutate)
        assert any("userinfo" in p for p in problems)

    def test_unsorted_subjects_rejected(self, fixtures_dir):
        def mutate(payload):
            live = payload["live_exercise"]
            live["subject_allow_list"] = list(reversed(live["subject_allow_list"]))

        problems = _validate_live_packet(fixtures_dir, mutate)
        assert any("subject_allow_list must be lexically sorted" in p for p in problems)

    def test_unsorted_record_kinds_rejected(self, fixtures_dir):
        def mutate(payload):
            live = payload["live_exercise"]
            live["allowed_record_kinds"] = list(reversed(live["allowed_record_kinds"]))

        problems = _validate_live_packet(fixtures_dir, mutate)
        assert any(
            "allowed_record_kinds must be lexically sorted" in p for p in problems
        )


class TestExerciseReceiptSemantics:
    def _receipt(self, fixtures_dir, **overrides):
        receipt = json.loads(
            (fixtures_dir / "valid" / "exercise-receipt__x6-read.json").read_text(
                encoding="utf-8"
            )
        )
        for key, value in overrides.items():
            receipt[key] = value
        return receipt

    def test_ended_before_started_rejected(self, fixtures_dir):
        receipt = self._receipt(fixtures_dir, ended_at="2026-08-14T10:00:00Z")
        problems = validators.validate_artifact("exercise-receipt", receipt)
        assert any("ended_at must be at or after started_at" in p for p in problems)

    def test_unsorted_targets_rejected(self, fixtures_dir):
        receipt = self._receipt(
            fixtures_dir,
            targets_contacted=["ws://127.0.0.1:8803", "http://127.0.0.1:8801"],
        )
        problems = validators.validate_artifact("exercise-receipt", receipt)
        assert any("targets_contacted must be lexically sorted" in p for p in problems)

    def test_failed_outcome_may_report_writes(self, fixtures_dir):
        receipt = self._receipt(fixtures_dir, outcome="CHECK_FAILED")
        receipt["counters"]["writes"] = 1
        assert validators.validate_artifact("exercise-receipt", receipt) == []

    def test_x6_pass_with_writes_rejected(self, fixtures_dir):
        receipt = self._receipt(fixtures_dir)
        receipt["counters"]["writes"] = 2
        problems = validators.validate_artifact("exercise-receipt", receipt)
        assert any("PASS outcome with counters.writes > 0" in p for p in problems)

    def test_x7_pass_with_writes_allowed(self, fixtures_dir):
        receipt = self._receipt(fixtures_dir, operation_id="V0-X7-WRITE-SMOKE")
        receipt["counters"]["writes"] = 4
        assert validators.validate_artifact("exercise-receipt", receipt) == []


# --- gate integration ------------------------------------------------------------


class TestGateExerciseReceipts:
    def test_not_applicable_for_other_tasks(self, monkeypatch):
        monkeypatch.delenv("V0_GATE_EXERCISE_RECEIPT", raising=False)
        check = v0_gate._check_exercise_receipts("V0-M5")
        assert check["ok"]
        assert check["status"] == "not_applicable"

    def test_m6_requires_receipt_env(self, monkeypatch):
        monkeypatch.delenv("V0_GATE_EXERCISE_RECEIPT", raising=False)
        check = v0_gate._check_exercise_receipts("V0-M6")
        assert not check["ok"]
        assert any("V0_GATE_EXERCISE_RECEIPT" in d for d in check["detail"])

    def test_m6_accepts_pass_receipt(self, fixtures_dir, monkeypatch):
        path = fixtures_dir / "valid" / "exercise-receipt__x6-read.json"
        monkeypatch.setenv("V0_GATE_EXERCISE_RECEIPT", str(path))
        assert v0_gate._check_exercise_receipts("V0-M6")["ok"]

    def test_m6_rejects_failed_receipt(self, fixtures_dir, tmp_path, monkeypatch):
        receipt = json.loads(
            (fixtures_dir / "valid" / "exercise-receipt__x6-read.json").read_text(
                encoding="utf-8"
            )
        )
        receipt["outcome"] = "CHECK_FAILED"
        path = tmp_path / "receipt.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        monkeypatch.setenv("V0_GATE_EXERCISE_RECEIPT", str(path))
        check = v0_gate._check_exercise_receipts("V0-M6")
        assert not check["ok"]
        assert any("outcome must be PASS" in d for d in check["detail"])

    def test_m6_rejects_wrong_operation(self, fixtures_dir, tmp_path, monkeypatch):
        receipt = json.loads(
            (fixtures_dir / "valid" / "exercise-receipt__x6-read.json").read_text(
                encoding="utf-8"
            )
        )
        receipt["operation_id"] = "V0-X7-WRITE-SMOKE"
        path = tmp_path / "receipt.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        monkeypatch.setenv("V0_GATE_EXERCISE_RECEIPT", str(path))
        check = v0_gate._check_exercise_receipts("V0-M6")
        assert not check["ok"]
        assert any(
            "operation_id must be V0-X6-READ-SMOKE" in d for d in check["detail"]
        )

    def test_m7_requires_receipt_env(self, monkeypatch):
        monkeypatch.delenv("V0_GATE_EXERCISE_RECEIPT", raising=False)
        check = v0_gate._check_exercise_receipts("V0-M7")
        assert not check["ok"]
        assert any("V0_GATE_EXERCISE_RECEIPT" in d for d in check["detail"])
        assert any("V0-X7-WRITE-SMOKE" in d for d in check["detail"])

    def test_m7_accepts_pass_receipt(self, fixtures_dir, monkeypatch):
        path = fixtures_dir / "valid" / "exercise-receipt__x7-write.json"
        monkeypatch.setenv("V0_GATE_EXERCISE_RECEIPT", str(path))
        assert v0_gate._check_exercise_receipts("V0-M7")["ok"]

    def test_m7_rejects_x6_receipt(self, fixtures_dir, monkeypatch):
        path = fixtures_dir / "valid" / "exercise-receipt__x6-read.json"
        monkeypatch.setenv("V0_GATE_EXERCISE_RECEIPT", str(path))
        check = v0_gate._check_exercise_receipts("V0-M7")
        assert not check["ok"]
        assert any(
            "operation_id must be V0-X7-WRITE-SMOKE" in d for d in check["detail"]
        )

    def test_m7_rejects_failed_receipt(self, fixtures_dir, tmp_path, monkeypatch):
        receipt = json.loads(
            (fixtures_dir / "valid" / "exercise-receipt__x7-write.json").read_text(
                encoding="utf-8"
            )
        )
        receipt["outcome"] = "CHECK_FAILED"
        path = tmp_path / "receipt.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        monkeypatch.setenv("V0_GATE_EXERCISE_RECEIPT", str(path))
        check = v0_gate._check_exercise_receipts("V0-M7")
        assert not check["ok"]
        assert any("outcome must be PASS" in d for d in check["detail"])


# --- V0-X7-WRITE-SMOKE --------------------------------------------------------


def build_x7_packet(fixtures_dir, tmp_path, targets, **overrides) -> dict:
    """An X7-pinned packet: nonproduction modes, 4 writes, the four NSIDs."""
    overrides.setdefault("operation", "V0-X7-WRITE-SMOKE")
    overrides.setdefault("network", "nonproduction_write")
    overrides.setdefault("credential", "nonproduction_external_ref")
    overrides.setdefault("kinds", X7_KINDS)
    overrides.setdefault("idempotency", X7_TOKEN)
    overrides.setdefault(
        "ceilings",
        {
            "max_requests": 24,
            "max_events": 10,
            "max_proof_fetches": 5,
            "max_bytes": 4 << 20,
            "max_wall_clock_seconds": 60,
            "max_writes": 4,
        },
    )
    overrides.setdefault(
        "retry",
        {"request_timeout_seconds": 2, "max_retries": 2, "retry_backoff_seconds": 0},
    )
    return build_packet(fixtures_dir, tmp_path, targets=targets, **overrides)


def _write_credential(tmp_path, content: str | None = None) -> Path:
    path = tmp_path / "credential.json"
    path.write_text(
        content
        if content is not None
        else json.dumps({"identifier": "x7.test", "app_password": X7_PASSWORD}),
        encoding="utf-8",
    )
    return path


def _mint_cid(repo: str, collection: str, rkey: str) -> str:
    """Deterministic fake-PDS CID, known to the test before the run starts."""
    return cid_for_dag_cbor(f"{repo}/{collection}/{rkey}".encode())


def _x7_refs() -> dict:
    """The exact uri/cid/rkey chain the X7 happy-path run must produce."""
    post_rkey = v0_exercise._x7_rkey(X7_TOKEN, "post")
    submit_rkey = v0_exercise._x7_rkey(X7_TOKEN, "submit")
    post_uri = f"at://{DID}/{POST}/{post_rkey}"
    post_cid = _mint_cid(DID, POST, post_rkey)
    submit_uri = f"at://{DID}/{SUBMIT}/{submit_rkey}"
    submit_cid = _mint_cid(DID, SUBMIT, submit_rkey)
    admit_rkey = admission_rkey(RecordRef(uri=submit_uri, cid=submit_cid))
    admit_uri = f"at://{DID}/{ADMISSION}/{admit_rkey}"
    admit_cid = _mint_cid(DID, ADMISSION, admit_rkey)
    remove_rkey = removal_rkey(RecordRef(uri=admit_uri, cid=admit_cid))
    return {
        "post": (POST, post_rkey, post_uri, post_cid),
        "submit": (SUBMIT, submit_rkey, submit_uri, submit_cid),
        "admission": (ADMISSION, admit_rkey, admit_uri, admit_cid),
        "removal": (MOD_ACTION, remove_rkey),
    }


class FakePds:
    """Loopback fake PDS: createSession/createRecord/repo+sync getRecord.

    ``drop_after_commit`` collections commit the record but drop the
    response (an ambiguous write); ``drop_without_commit`` collections
    drop the response without committing. CIDs are minted deterministically
    from the record key so tests can pin the whole reference chain upfront.
    """

    def __init__(self):
        self.records: dict[tuple[str, str, str], dict] = {}
        self.log: list[tuple[str, str]] = []
        self.create_attempts: list[tuple[str, str, str]] = []
        self.drop_after_commit: set[str] = set()
        self.drop_without_commit: set[str] = set()
        self.drop_reads_after_commit: dict[str, int] = {}
        self.fail_first_create_session = False
        self._session_attempts = 0
        self.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), self._make_handler()
        )
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.origin = f"http://127.0.0.1:{self.server.server_address[1]}"

    def put(self, repo: str, collection: str, rkey: str, value: dict) -> str:
        cid = _mint_cid(repo, collection, rkey)
        self.records[(repo, collection, rkey)] = {
            "uri": f"at://{repo}/{collection}/{rkey}",
            "cid": cid,
            "value": value,
        }
        return cid

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def _make_handler(self):
        pds = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _send(self, status: int, body: bytes):
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status: int, obj: dict):
                self._send(status, json.dumps(obj).encode("utf-8"))

            def _drop(self):
                # Commit state is whatever it is; the client never sees a
                # response, so the write outcome is ambiguous on the wire.
                self.close_connection = True

            def do_POST(self):
                path = urlsplit(self.path).path
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                pds.log.append(("POST", path))
                if path == v0_exercise.CREATE_SESSION_PATH:
                    pds._session_attempts += 1
                    if pds.fail_first_create_session and pds._session_attempts == 1:
                        self._drop()
                        return
                    # Pin the wire shape: the lexicon field is "password",
                    # not the credential file's "app_password" key.
                    session = json.loads(raw.decode("utf-8"))
                    if set(session) != {"identifier", "password"}:
                        self._json(400, {"error": "InvalidRequest"})
                        return
                    self._json(
                        200,
                        {"accessJwt": X7_JWT, "did": DID, "handle": "x7.test"},
                    )
                    return
                if path == v0_exercise.CREATE_RECORD_PATH:
                    payload = json.loads(raw.decode("utf-8"))
                    key = (payload["repo"], payload["collection"], payload["rkey"])
                    pds.create_attempts.append(key)
                    if payload["collection"] in pds.drop_without_commit:
                        self._drop()
                        return
                    cid = pds.put(*key, payload["record"])
                    if payload["collection"] in pds.drop_after_commit:
                        self._drop()
                        return
                    self._json(
                        200, {"uri": f"at://{key[0]}/{key[1]}/{key[2]}", "cid": cid}
                    )
                    return
                self._json(404, {"error": "not found"})

            def do_GET(self):
                split = urlsplit(self.path)
                pds.log.append(("GET", split.path))
                query = dict(parse_qsl(split.query))
                key = (
                    query.get("repo", ""),
                    query.get("collection", ""),
                    query.get("rkey", ""),
                )
                if split.path == v0_exercise.REPO_GET_RECORD_PATH:
                    record = pds.records.get(key)
                    if record is not None:
                        remaining = pds.drop_reads_after_commit.get(key[1], 0)
                        if remaining:
                            # Drop committed-record reads (communityd's
                            # ambiguity readback and its bounded retries).
                            pds.drop_reads_after_commit[key[1]] = remaining - 1
                            self._drop()
                            return
                    if record is None:
                        self._json(400, {"error": "RecordNotFound"})
                        return
                    self._json(200, record)
                    return
                if split.path == "/xrpc/com.atproto.repo.listRecords":
                    repo = query.get("repo", "")
                    collection = query.get("collection", "")
                    limit = int(query.get("limit", "100"))
                    start = int(query.get("cursor") or 0)
                    entries = sorted(
                        (
                            entry
                            for key, entry in pds.records.items()
                            if key[0] == repo and key[1] == collection
                        ),
                        key=lambda entry: entry["uri"],
                    )
                    page = entries[start : start + limit]
                    body = {"records": page}
                    if start + limit < len(entries):
                        body["cursor"] = str(start + limit)
                    self._json(200, body)
                    return
                if split.path == v0_exercise.GET_RECORD_PATH:
                    # com.atproto.sync.getRecord names the repo key "did";
                    # the real PDS 400s the legacy "repo" spelling.
                    if "did" not in query:
                        self._json(400, {"error": "InvalidRequest"})
                        return
                    sync_key = (
                        query.get("did", ""),
                        query.get("collection", ""),
                        query.get("rkey", ""),
                    )
                    if sync_key not in pds.records:
                        self._json(404, {"error": "RecordNotFound"})
                        return
                    self._send(200, b"CARBYTES")
                    return
                self._json(404, {"error": "not found"})

            def log_message(self, *args):
                pass

        return Handler


def make_fake_communityd(pds: FakePds, behavior: str = "ok"):
    """A scripted stand-in for the communityd subprocess boundary.

    Used for exit-code injection (conflict, exit-8 ambiguity) that a fake
    PDS cannot stage on its own; everything around the subprocess in the
    harness (config staging, transcripts, exit-code handling,
    deterministic-rkey cross-check, readback) runs for real, and the fake
    commits through the same FakePds minting so readbacks resolve. The
    budget-accounting tests below instead run the REAL communityd CLI
    against the loopback accounting proxy.
    """

    def fake(argv, env, timeout):
        command = argv[argv.index("communityd") + 3]
        flags = dict(
            zip(argv[argv.index(command) + 1 :: 2], argv[argv.index(command) + 2 :: 2])
        )
        if command == "admit":
            submission = RecordRef(
                uri=flags["--submission-uri"], cid=flags["--submission-cid"]
            )
            rkey = admission_rkey(submission)
            collection = ADMISSION
            submit_key = (DID, SUBMIT, submission.rkey)
            record = {
                "$type": ADMISSION,
                "submission": {"uri": submission.uri, "cid": submission.cid},
                "subject": pds.records[submit_key]["value"]["subject"],
                "actor": DID,
                "createdAt": "2026-08-14T00:00:00.000Z",
            }
        else:
            admission = RecordRef(
                uri=flags["--admission-uri"], cid=flags["--admission-cid"]
            )
            rkey = removal_rkey(admission)
            collection = MOD_ACTION
            admission_key = (DID, ADMISSION, admission.rkey)
            record = {
                "$type": MOD_ACTION,
                "action": "remove",
                "admission": {"uri": admission.uri, "cid": admission.cid},
                "subject": pds.records[admission_key]["value"]["subject"],
                "actor": DID,
                "createdAt": "2026-08-14T00:00:00.000Z",
            }
        if behavior == "conflict":
            return subprocess.CompletedProcess(
                argv, 5, b"", b'{"error": "immutable_conflict"}\n'
            )
        cid = pds.put(DID, collection, rkey, record)
        uri = f"at://{DID}/{collection}/{rkey}"
        if behavior == "ambiguous":
            # The write committed but the CLI reports it ambiguous (exit 8).
            return subprocess.CompletedProcess(
                argv, 8, b"", b'{"error": "write_failed"}\n'
            )
        stdout = json.dumps({"operation": "created", "uri": uri, "cid": cid})
        return subprocess.CompletedProcess(argv, 0, stdout.encode() + b"\n", b"")

    return fake


def _x7_setup(http_server_factory):
    pds = FakePds()
    did_origin = http_server_factory({f"/{DID}": (200, _did_doc(DID, pds.origin))})
    refs = _x7_refs()
    events = [
        _commit_event(DID, refs["post"][1], refs["post"][3], POST),
        _commit_event(DID, refs["submit"][1], refs["submit"][3], SUBMIT),
        _commit_event(DID, refs["admission"][1], refs["admission"][3], ADMISSION),
        _commit_event(DID, refs["removal"][1], "cidremoval", MOD_ACTION),
    ]
    ws = FakeWsServer(events)
    return pds, did_origin, ws


def _run_x7(fixtures_dir, tmp_path, capsys, monkeypatch, pds, did_origin, ws):
    monkeypatch.setenv("V0_X7_CREDENTIAL_REF", str(_write_credential(tmp_path)))
    monkeypatch.setattr(v0_exercise, "_invoke_communityd", make_fake_communityd(pds))
    packet = build_x7_packet(
        fixtures_dir, tmp_path, targets=[pds.origin, did_origin, ws.origin]
    )
    return run_harness(
        write_packet(packet, tmp_path), capsys, operation="V0-X7-WRITE-SMOKE"
    )


def _retained_bytes(run_dir: Path) -> bytes:
    chunks = []
    for path in sorted(run_dir.rglob("*")):
        if path.is_file():
            chunks.append(path.read_bytes())
    return b"\n".join(chunks)


def test_x7_happy_path_pass_receipt(
    fixtures_dir, tmp_path, http_server_factory, capsys, monkeypatch
):
    pds, did_origin, ws = _x7_setup(http_server_factory)
    code, receipt, _ = _run_x7(
        fixtures_dir, tmp_path, capsys, monkeypatch, pds, did_origin, ws
    )

    assert code == 0
    assert receipt["outcome"] == "PASS"
    assert receipt["stop_rule"] == "completed"
    assert not validators.validate_artifact("exercise-receipt", receipt)
    counters = receipt["counters"]
    assert counters["writes"] == 4
    assert counters["events"] == 4
    assert counters["proof_fetches"] == 4
    # DID GET (one extra resolver probe when the PDS port sorts first) +
    # createSession + WS subscribe + 2 createRecord + 4 proofs
    assert counters["requests"] in (9, 10)
    assert counters["requests"] <= 24  # the pinned ceiling
    assert receipt["targets_contacted"] == sorted([pds.origin, did_origin, ws.origin])
    assert "capture_then_verify" in receipt["notes"]

    run_dir = tmp_path / "evidence" / receipt["receipt_id"]
    config = (run_dir / "communityd.toml").read_text(encoding="utf-8")
    assert 'credential_ref = "env:V0_X7_CREDENTIAL_REF"' in config
    assert 'writer_adapter = "pds"' in config
    projections = json.loads((run_dir / "projections.json").read_text(encoding="utf-8"))
    assert projections["mode"] == "capture_then_verify"
    assert [t["state"] for t in projections["transitions"]] == [
        "submitted",
        "visible",
        "removed",
    ]
    admit_out = json.loads((run_dir / "cli" / "admit.stdout.json").read_text())
    refs = _x7_refs()
    assert admit_out["uri"] == refs["admission"][2]
    proofs = sorted((run_dir / "proofs").rglob("*.car"))
    assert len(proofs) == 4
    roles = {a["role"] for a in receipt["artifacts"]}
    assert {
        "events_ndjson",
        "did_doc",
        "proof_car",
        "daemon_config",
        "projection_snapshot",
        "cli_transcript",
    } <= roles

    # The credential and the bearer token never reached retained bytes.
    retained = _retained_bytes(run_dir)
    assert X7_PASSWORD.encode() not in retained
    assert X7_JWT.encode() not in retained


def test_x7_credential_file_malformed_is_unauthorized(
    fixtures_dir, tmp_path, http_server_factory, capsys, monkeypatch
):
    pds = FakePds()
    monkeypatch.setenv(
        "V0_X7_CREDENTIAL_REF", str(_write_credential(tmp_path, "not json"))
    )
    packet = build_x7_packet(fixtures_dir, tmp_path, targets=[pds.origin])
    code, receipt, _ = run_harness(
        write_packet(packet, tmp_path), capsys, operation="V0-X7-WRITE-SMOKE"
    )
    assert code == 2
    assert receipt["outcome"] == "UNAUTHORIZED"
    assert receipt["stop_rule"] == "credential_malformed"
    assert pds.log == []


def test_x7_ambiguous_write_resolved_by_readback(
    fixtures_dir, tmp_path, http_server_factory, capsys, monkeypatch
):
    """Server commits the post but drops the response: readback resolves."""
    pds, did_origin, ws = _x7_setup(http_server_factory)
    pds.drop_after_commit.add(POST)
    code, receipt, _ = _run_x7(
        fixtures_dir, tmp_path, capsys, monkeypatch, pds, did_origin, ws
    )
    assert code == 0
    assert receipt["outcome"] == "PASS"
    assert receipt["counters"]["writes"] == 4
    # exactly one createRecord for the post reached the server: no blind retry
    refs = _x7_refs()
    post_attempts = [
        k for k in pds.create_attempts if k == (DID, POST, refs["post"][1])
    ]
    assert len(post_attempts) == 1


def test_x7_unresolved_ambiguous_write_stops(
    fixtures_dir, tmp_path, http_server_factory, capsys, monkeypatch
):
    """Dropped response, nothing committed: stop with a failure receipt."""
    pds, did_origin, ws = _x7_setup(http_server_factory)
    pds.drop_without_commit.add(POST)
    code, receipt, _ = _run_x7(
        fixtures_dir, tmp_path, capsys, monkeypatch, pds, did_origin, ws
    )
    assert code == 1
    assert receipt["outcome"] == "CHECK_FAILED"
    assert receipt["stop_rule"] == "ambiguous_write"
    assert receipt["counters"]["writes"] == 0
    refs = _x7_refs()
    post_attempts = [
        k for k in pds.create_attempts if k == (DID, POST, refs["post"][1])
    ]
    assert len(post_attempts) == 1


def test_x7_cli_ambiguous_resolved_by_readback(
    fixtures_dir, tmp_path, http_server_factory, capsys, monkeypatch
):
    """communityd exit 8: the deterministic-rkey readback treats the
    committed admission/removal as existing; the CLI is never rerun."""
    pds, did_origin, ws = _x7_setup(http_server_factory)
    monkeypatch.setenv("V0_X7_CREDENTIAL_REF", str(_write_credential(tmp_path)))
    monkeypatch.setattr(
        v0_exercise, "_invoke_communityd", make_fake_communityd(pds, "ambiguous")
    )
    packet = build_x7_packet(
        fixtures_dir, tmp_path, targets=[pds.origin, did_origin, ws.origin]
    )
    code, receipt, _ = run_harness(
        write_packet(packet, tmp_path), capsys, operation="V0-X7-WRITE-SMOKE"
    )
    assert code == 0
    assert receipt["outcome"] == "PASS"
    assert receipt["counters"]["writes"] == 4
    # two readbacks (admission + removal) beyond the happy path's 9-10
    assert receipt["counters"]["requests"] in (11, 12)
    run_dir = tmp_path / "evidence" / receipt["receipt_id"]
    assert (
        json.loads((run_dir / "cli" / "admit.stderr.txt").read_text())["error"]
        == "write_failed"
    )


def test_x7_cli_conflict_stops(
    fixtures_dir, tmp_path, http_server_factory, capsys, monkeypatch
):
    pds, did_origin, ws = _x7_setup(http_server_factory)
    monkeypatch.setenv("V0_X7_CREDENTIAL_REF", str(_write_credential(tmp_path)))
    monkeypatch.setattr(
        v0_exercise, "_invoke_communityd", make_fake_communityd(pds, "conflict")
    )
    packet = build_x7_packet(
        fixtures_dir, tmp_path, targets=[pds.origin, did_origin, ws.origin]
    )
    code, receipt, _ = run_harness(
        write_packet(packet, tmp_path), capsys, operation="V0-X7-WRITE-SMOKE"
    )
    assert code == 1
    assert receipt["outcome"] == "CHECK_FAILED"
    assert receipt["stop_rule"] == "authority_write_conflict"
    # post + submit landed; the conflicting admission did not count
    assert receipt["counters"]["writes"] == 2


def test_x7_pds_origin_not_allow_listed(
    fixtures_dir, tmp_path, http_server_factory, capsys, monkeypatch
):
    """The pinned/config PDS origin must be in target_allow_list."""
    pds, did_origin, ws = _x7_setup(http_server_factory)
    monkeypatch.setenv("V0_X7_CREDENTIAL_REF", str(_write_credential(tmp_path)))
    monkeypatch.setattr(v0_exercise, "_invoke_communityd", make_fake_communityd(pds))
    packet = build_x7_packet(
        fixtures_dir,
        tmp_path,
        targets=[did_origin, ws.origin],  # PDS absent
    )
    code, receipt, _ = run_harness(
        write_packet(packet, tmp_path), capsys, operation="V0-X7-WRITE-SMOKE"
    )
    assert code == 1
    assert receipt["outcome"] == "CHECK_FAILED"
    assert receipt["stop_rule"] == "pds_origin_not_allowed"
    assert receipt["counters"]["writes"] == 0
    assert ("POST", v0_exercise.CREATE_SESSION_PATH) not in pds.log


def test_x7_retry_policy_is_respected(
    fixtures_dir, tmp_path, http_server_factory, capsys, monkeypatch
):
    """A dropped createSession (idempotent, not a write) is retried once."""
    pds, did_origin, ws = _x7_setup(http_server_factory)
    pds.fail_first_create_session = True
    code, receipt, _ = _run_x7(
        fixtures_dir, tmp_path, capsys, monkeypatch, pds, did_origin, ws
    )
    assert code == 0
    assert receipt["outcome"] == "PASS"
    assert receipt["counters"]["retries"] == 1
    assert pds._session_attempts == 2


def test_x7_write_ceiling_blocks_fifth_write():
    live = {
        "ceilings": {
            "max_requests": 24,
            "max_events": 10,
            "max_proof_fetches": 5,
            "max_bytes": 4 << 20,
            "max_wall_clock_seconds": 60,
            "max_writes": 4,
        },
        "retry": {
            "request_timeout_seconds": 2,
            "max_retries": 2,
            "retry_backoff_seconds": 0,
        },
    }
    ctx = v0_exercise.ExerciseContext(live, time.monotonic())
    for _ in range(4):
        ctx.begin_write()
        ctx.record_write()
    with pytest.raises(v0_exercise.PlanStop) as excinfo:
        ctx.begin_write()
    assert excinfo.value.stop_rule == "write_ceiling_exceeded"
    assert ctx.counters["writes"] == 4


# --- exercise-wide budget accounting (real communityd subprocess) -----------
#
# The X7 authorization's request ceiling covers the WHOLE exercise, including
# communityd subprocess XRPC. The harness confines the CLI to an in-process
# loopback AccountingProxy sharing the one ExerciseContext budget; these
# tests run the REAL communityd CLI (no subprocess patching) and prove the
# receipt's counters.requests is the exact cross-process total.


class CountingDidServer:
    """DID-document server that records exactly how many GETs it served."""

    def __init__(self, did: str, pds_origin: str):
        self.hits = 0
        body = _did_doc(did, pds_origin)
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                owner.hits += 1
                if urlsplit(self.path).path == f"/{did}":
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.origin = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def _x7_setup_counting():
    """X7 fixture set whose DID server counts hits, for the budget identity."""
    pds = FakePds()
    did = CountingDidServer(DID, pds.origin)
    refs = _x7_refs()
    events = [
        _commit_event(DID, refs["post"][1], refs["post"][3], POST),
        _commit_event(DID, refs["submit"][1], refs["submit"][3], SUBMIT),
        _commit_event(DID, refs["admission"][1], refs["admission"][3], ADMISSION),
        _commit_event(DID, refs["removal"][1], "cidremoval", MOD_ACTION),
    ]
    ws = FakeWsServer(events)
    return pds, did, ws


def _run_x7_real_cli(
    fixtures_dir, tmp_path, capsys, monkeypatch, pds, did, ws, **overrides
):
    """Run X7 with the REAL communityd CLI subprocess (nothing patched)."""
    monkeypatch.setenv("V0_X7_CREDENTIAL_REF", str(_write_credential(tmp_path)))
    packet = build_x7_packet(
        fixtures_dir,
        tmp_path,
        targets=[pds.origin, did.origin, ws.origin],
        **overrides,
    )
    return run_harness(
        write_packet(packet, tmp_path), capsys, operation="V0-X7-WRITE-SMOKE"
    )


def _assert_request_identity(receipt, pds, did):
    """Receipt requests == every cross-process request the fakes observed.

    pds.log holds direct harness calls AND proxied communityd calls; the
    DID server counts resolver traffic; the relay WebSocket upgrade is the
    one remaining counted request. If any request bypassed the budget —
    harness, subprocess, session, retry, or readback — this fails.
    """
    observed = len(pds.log) + did.hits + 1
    assert receipt["counters"]["requests"] == observed


def test_x7_real_cli_happy_path_counts_everything(
    fixtures_dir, tmp_path, capsys, monkeypatch
):
    """Cases 1/2/3/8/9: harness, subprocess, and session traffic all share
    the budget; the receipt total equals the observed cross-process count;
    secrets never reach retained bytes."""
    pds, did, ws = _x7_setup_counting()
    code, receipt, _ = _run_x7_real_cli(
        fixtures_dir, tmp_path, capsys, monkeypatch, pds, did, ws
    )
    assert code == 0, receipt["notes"]
    assert receipt["outcome"] == "PASS"
    assert receipt["counters"]["writes"] == 4
    _assert_request_identity(receipt, pds, did)
    # Session authentication consumed budget: harness + both CLI sessions.
    sessions = [e for e in pds.log if e == ("POST", v0_exercise.CREATE_SESSION_PATH)]
    assert len(sessions) == 3
    # The real CLI committed the authority records at the pinned rkeys.
    refs = _x7_refs()
    assert (DID, ADMISSION, refs["admission"][1]) in pds.records
    assert (DID, MOD_ACTION, refs["removal"][1]) in pds.records
    # The credential and bearer tokens never reached retained bytes.
    run_dir = tmp_path / "evidence" / receipt["receipt_id"]
    retained = _retained_bytes(run_dir)
    assert X7_PASSWORD.encode() not in retained
    assert X7_JWT.encode() not in retained


def test_x7_real_cli_budget_exhaustion_fails_closed(
    fixtures_dir, tmp_path, capsys, monkeypatch
):
    """Cases 2/6: mid-CLI exhaustion blocks the next upstream socket; the
    run stops with request_ceiling_exceeded and nothing escapes the budget."""
    pds, did, ws = _x7_setup_counting()
    ceilings = {
        "max_requests": 8,
        "max_events": 10,
        "max_proof_fetches": 5,
        "max_bytes": 4 << 20,
        "max_wall_clock_seconds": 60,
        "max_writes": 4,
    }
    code, receipt, _ = _run_x7_real_cli(
        fixtures_dir, tmp_path, capsys, monkeypatch, pds, did, ws, ceilings=ceilings
    )
    assert code == 1
    assert receipt["outcome"] == "CHECK_FAILED"
    assert receipt["stop_rule"] == "request_ceiling_exceeded"
    assert receipt["counters"]["requests"] == 8
    _assert_request_identity(receipt, pds, did)
    # The budget stopped the exercise before the admission could land.
    refs = _x7_refs()
    assert (DID, ADMISSION, refs["admission"][1]) not in pds.records
    assert receipt["counters"]["writes"] == 2


def test_x7_real_cli_ambiguity_readback_consumes_budget(
    fixtures_dir, tmp_path, capsys, monkeypatch
):
    """Case 5: the CLI's own ambiguous-write readback flows through the
    proxy and is counted (drop after committing the admission create)."""
    pds, did, ws = _x7_setup_counting()
    pds.drop_after_commit.add(ADMISSION)
    code, receipt, _ = _run_x7_real_cli(
        fixtures_dir, tmp_path, capsys, monkeypatch, pds, did, ws
    )
    assert code == 0, receipt["notes"]
    assert receipt["outcome"] == "PASS"
    assert receipt["counters"]["writes"] == 4
    _assert_request_identity(receipt, pds, did)


def test_x7_harness_ambiguity_readback_consumes_budget(
    fixtures_dir, tmp_path, capsys, monkeypatch
):
    """Case 5 (harness side): a dropped submit createRecord is resolved by
    a counted readback and the run still completes."""
    pds, did, ws = _x7_setup_counting()
    pds.drop_after_commit.add(SUBMIT)
    code, receipt, _ = _run_x7_real_cli(
        fixtures_dir, tmp_path, capsys, monkeypatch, pds, did, ws
    )
    assert code == 0, receipt["notes"]
    assert receipt["outcome"] == "PASS"
    assert receipt["counters"]["writes"] == 4
    _assert_request_identity(receipt, pds, did)


def test_x7_real_cli_failure_fallback_readback_counted(
    fixtures_dir, tmp_path, capsys, monkeypatch
):
    """Cases 6/7: the CLI exits 8 (its readback kept failing); the harness
    fallback readback is a counted request. The extra failure-path traffic
    then exhausts the pinned 24-request ceiling during proof fetches and
    the run fails closed — with the receipt total still exactly matching
    the observed cross-process count."""
    pds, did, ws = _x7_setup_counting()
    pds.drop_after_commit.add(ADMISSION)
    # Drop the CLI's post-ambiguity readback and its bounded retries, plus
    # enough further read attempts to keep this failure path above the
    # pinned 24-request ceiling after the pre-read collapse made the happy
    # path two requests cheaper.
    pds.drop_reads_after_commit[ADMISSION] = 5
    code, receipt, _ = _run_x7_real_cli(
        fixtures_dir, tmp_path, capsys, monkeypatch, pds, did, ws
    )
    assert code == 1
    assert receipt["outcome"] == "CHECK_FAILED"
    assert receipt["stop_rule"] == "request_ceiling_exceeded"
    assert receipt["counters"]["requests"] == 24
    # All four writes landed (the admission via the harness fallback
    # readback, never a blind retry); only the proof pass was cut short.
    assert receipt["counters"]["writes"] == 4
    refs = _x7_refs()
    assert (DID, ADMISSION, refs["admission"][1]) in pds.records
    _assert_request_identity(receipt, pds, did)


def test_x7_real_cli_retries_consume_budget(
    fixtures_dir, tmp_path, capsys, monkeypatch
):
    """Case 4: a dropped (idempotent) session call is retried, and the
    retry is a counted request in the shared total."""
    pds, did, ws = _x7_setup_counting()
    pds.fail_first_create_session = True
    code, receipt, _ = _run_x7_real_cli(
        fixtures_dir, tmp_path, capsys, monkeypatch, pds, did, ws
    )
    assert code == 0, receipt["notes"]
    assert receipt["outcome"] == "PASS"
    assert receipt["counters"]["retries"] == 1
    # 1 dropped attempt + 1 harness session + 2 real-CLI sessions.
    assert pds._session_attempts == 4
    _assert_request_identity(receipt, pds, did)


def test_harness_runs_standalone_without_test_imports(tmp_path):
    """The harness must import and run as a bare script.

    Regression guard: in-process tests share this module's imports (which
    include http.server), masking missing imports inside the harness
    itself — the AccountingProxy crashed live on exactly that. Run the
    harness file in a fresh interpreter against a missing packet and
    require the clean CONTRACT_INVALID refusal path.
    """
    result = subprocess.run(
        [
            sys.executable,
            str(Path(v0_exercise.__file__)),
            "V0-X7-WRITE-SMOKE",
            "--packet",
            str(tmp_path / "missing.json"),
        ],
        capture_output=True,
        timeout=30,
    )
    receipt = json.loads(result.stdout.decode("utf-8"))
    assert result.returncode == 2
    assert receipt["outcome"] == "CONTRACT_INVALID"
    assert receipt["stop_rule"] == "packet_invalid"


# --- DID resolution pinning ----------------------------------------------------


def _resolver_ctx(allow):
    live = {
        "target_allow_list": sorted(allow),
        "subject_allow_list": [DID],
        "allowed_record_kinds": [KIND],
        "ceilings": {
            "max_requests": 10,
            "max_events": 1,
            "max_proof_fetches": 1,
            "max_bytes": 1 << 20,
            "max_wall_clock_seconds": 30,
            "max_writes": 0,
        },
        "retry": {
            "request_timeout_seconds": 1,
            "max_retries": 0,
            "retry_backoff_seconds": 0,
        },
    }
    return v0_exercise.ExerciseContext(live, time.monotonic())


def test_plc_did_resolves_through_directory_only(monkeypatch):
    """With the real directory pinned, a PLC DID costs exactly one request.

    Regression guard: the resolver previously probed every allow-listed
    HTTP origin in sorted order, burning one counted request against the
    subject's PDS before reaching plc.directory.
    """
    calls = []

    def fake_get(origin, path, timeout, budget, bearer=None):
        calls.append((origin, path))
        return 200, json.dumps({"id": DID}).encode()

    monkeypatch.setattr(v0_exercise, "http_get", fake_get)
    ctx = _resolver_ctx(
        [
            "https://pds.aaa.example",  # sorts before plc.directory on purpose
            v0_exercise.PLC_DIRECTORY_ORIGIN,
            "wss://relay.example",
        ]
    )
    doc, _ = v0_exercise.resolve_subject_did(ctx, DID)
    assert doc["id"] == DID
    assert calls == [(v0_exercise.PLC_DIRECTORY_ORIGIN, f"/{DID}")]
    assert ctx.counters["requests"] == 1
    assert ctx.request_log[0]["kind"] == "did_resolve"


def test_plc_did_without_directory_falls_back_to_generic_iteration(monkeypatch):
    """Offline packets pin a loopback resolver, not the real directory."""
    calls = []

    def fake_get(origin, path, timeout, budget, bearer=None):
        calls.append(origin)
        if origin.endswith("aaa.example"):
            return 404, b""
        return 200, json.dumps({"id": DID}).encode()

    monkeypatch.setattr(v0_exercise, "http_get", fake_get)
    ctx = _resolver_ctx(["https://zzz.example", "https://aaa.example"])
    doc, _ = v0_exercise.resolve_subject_did(ctx, DID)
    assert doc["id"] == DID
    assert calls == ["https://aaa.example", "https://zzz.example"]


# --- retained request accounting log -------------------------------------------


def test_x7_request_log_explains_every_counted_request(
    fixtures_dir, tmp_path, capsys, monkeypatch
):
    pds, did, ws = _x7_setup_counting()
    code, receipt, _ = _run_x7_real_cli(
        fixtures_dir, tmp_path, capsys, monkeypatch, pds, did, ws
    )
    assert code == 0, receipt["notes"]

    run_dir = tmp_path / "evidence" / receipt["receipt_id"]
    raw = (run_dir / "request_log.ndjson").read_bytes()
    entries = [json.loads(line) for line in raw.decode().splitlines()]
    assert len(entries) == receipt["counters"]["requests"]
    assert [entry["seq"] for entry in entries] == list(range(1, len(entries) + 1))
    for entry in entries:
        assert {"seq", "source", "kind", "method", "origin", "path"} <= set(entry)
        assert "status" in entry  # the happy path has no error entries
    assert {entry["source"] for entry in entries} == {"harness", "communityd-proxy"}
    kinds = {entry["kind"] for entry in entries}
    assert {
        "did_resolve",
        "subscribe",
        "session",
        "write",
        "read",
        "ledger_list",
        "proof_fetch",
    } <= kinds
    # The artifact listing pins the retained log byte-for-byte.
    listed = [a for a in receipt["artifacts"] if a["role"] == "request_log"]
    assert len(listed) == 1
    assert listed[0]["sha256"] == common.sha256_digest(raw)
    assert listed[0]["bytes"] == len(raw)
    # Credential material never reaches the log.
    assert X7_PASSWORD.encode() not in raw
    assert X7_JWT.encode() not in raw


def test_x7_request_log_divergence_fails_closed(
    fixtures_dir, tmp_path, http_server_factory, capsys, monkeypatch
):
    """A log/counter divergence means traffic escaped accounting: never PASS."""
    pds, did_origin, ws = _x7_setup(http_server_factory)
    monkeypatch.setattr(
        v0_exercise.ExerciseContext,
        "_open_request",
        lambda self, *args, **kwargs: {},
    )
    code, receipt, _ = _run_x7(
        fixtures_dir, tmp_path, capsys, monkeypatch, pds, did_origin, ws
    )
    assert code == 1
    assert receipt["outcome"] == "CHECK_FAILED"
    assert "request_log_inconsistent" in receipt["notes"]
