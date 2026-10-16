"""V0-M5 acceptance: the canonical web AppView over a seeded observer DB.

Covers the submit -> admit -> render -> remove proof through the HTTP
surface, the read-only subprocess boundary with an allow-listed environment,
and concurrent WAL ingest versus web reads.  Everything is offline: fake
adapters, temporary directories, ephemeral ports.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from community_model import (
    POST_COLLECTION,
    SUBMISSION_COLLECTION,
    IncomingDelivery,
    ResolveResult,
    canonical_json_bytes,
    cid_for_dag_cbor,
)
from communityd.config import DaemonConfig
from communityd.fakes import (
    FakeAdminAuthorizer,
    FakeAuthorityLedgerReader,
    FakeAuthorityWriter,
    FakeCredentialProvider,
    FakeRecordReader,
    FakeRepoState,
)
from communityd.operations import DaemonPorts, admit, remove
from communitywatch import ObserverStore, ProjectionQuery
from communitywatch.fakes import FakeSubjectResolver
from communitywatch_web.app import SECURITY_HEADERS, WebApp

COMMUNITY_DID = "did:web:community.invalid"
ADMIN_DID = "did:web:admin.invalid"
ALICE_DID = "did:web:alice.invalid"
SLUG = "homelab"
ALLOWED_UID = 4242
CREDENTIAL_REF = "fake://communityd-admin"
SOURCE = "fake-relay"
POSTS_PATH = f"/api/v0/communities/{COMMUNITY_DID}/posts"
AUDIT_PATH = f"/api/v0/communities/{COMMUNITY_DID}/audit"

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_SRCS = (
    ROOT / "packages" / "community-model" / "src",
    ROOT / "packages" / "communitywatch" / "src",
    ROOT / "packages" / "communitywatch-web" / "src",
)


def _cid(record: dict[str, object]) -> str:
    return cid_for_dag_cbor(canonical_json_bytes(record))


def _delivery(
    envelope: dict[str, object], *, cursor: str, received_at: datetime
) -> IncomingDelivery:
    return IncomingDelivery(
        source=SOURCE,
        cursor=cursor,
        source_event_time=received_at,
        received_at=received_at,
        raw_envelope=envelope,
        trust_mode="test_fixture",
        verification_outcome="verified",
        verification_method="fixture",
        verifier_version="1",
    )


def _daemon(state: FakeRepoState) -> tuple[DaemonPorts, DaemonConfig]:
    ports = DaemonPorts(
        reader=FakeRecordReader(state),
        ledger=FakeAuthorityLedgerReader(state),
        authorizer=FakeAdminAuthorizer(
            administrator_did=ADMIN_DID,
            allowed_uid=ALLOWED_UID,
            effective_uid=ALLOWED_UID,
        ),
        writer=FakeAuthorityWriter(state),
        credentials=FakeCredentialProvider({CREDENTIAL_REF: "fake-handle"}),
    )
    config = DaemonConfig(
        community_did=COMMUNITY_DID,
        administrator_did=ADMIN_DID,
        community_pds_url="https://pds.invalid",
        allowed_uid=ALLOWED_UID,
        reader_adapter="fake",
        ledger_adapter="fake",
        writer_adapter="fake",
        credential_provider="fake",
        credential_ref=CREDENTIAL_REF,
    )
    return ports, config


def _web_app(path: Path, *, now: datetime) -> WebApp:
    store = ObserverStore(path, community_did=COMMUNITY_DID, read_only=True)
    return WebApp(
        ProjectionQuery(store, slug=SLUG),
        community_did=COMMUNITY_DID,
        slug=SLUG,
        stale_threshold_seconds=0,
        now=lambda: now,
    )


def _json(response) -> dict[str, object]:
    return json.loads(response.body.decode("utf-8"))


def _seed_lifecycle(path: Path, t0: datetime) -> dict[str, object]:
    """submit -> admit -> observe -> CID mismatch -> remove; return material."""

    store = ObserverStore(
        path, community_did=COMMUNITY_DID, administrator_did=ADMIN_DID
    )
    state = FakeRepoState()
    ports, config = _daemon(state)

    post_a = {
        "$type": POST_COLLECTION,
        "text": 'Tiny computers <script>alert("xss")</script> loud fans.',
        "createdAt": (t0 - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
    }
    post_ref = state.seed(ALICE_DID, POST_COLLECTION, "3jzfcijpj2z2a", post_a)
    submission_record = {
        "$type": SUBMISSION_COLLECTION,
        "community": COMMUNITY_DID,
        "subject": post_ref.as_dict(),
        "createdAt": (t0 - timedelta(seconds=90)).isoformat().replace("+00:00", "Z"),
    }
    submission_ref = state.seed(
        ALICE_DID, SUBMISSION_COLLECTION, "3jzfcijpj2z2b", submission_record
    )

    stages: dict[str, object] = {"store": store, "state": state}
    store.ingest(
        _delivery(
            {
                "repo": ALICE_DID,
                "rev": "3jzfcijpj2z2c",
                "operation": "create",
                "collection": SUBMISSION_COLLECTION,
                "rkey": "3jzfcijpj2z2b",
                "cid": submission_ref.cid,
                "record": submission_record,
            },
            cursor="1",
            received_at=t0 - timedelta(seconds=89),
        )
    )

    admission = admit(ports, config, submission_ref, now=t0 - timedelta(seconds=60))
    admission_result = store.ingest(
        _delivery(state.emitted[-1], cursor="2", received_at=t0 - timedelta(seconds=59))
    )
    resolver = FakeSubjectResolver(
        {
            post_ref: [
                ResolveResult(
                    status="exact",
                    requested=post_ref,
                    current_cid=post_ref.cid,
                    record=post_a,
                    checked_at=t0 - timedelta(seconds=58),
                    trust_mode="test_fixture",
                    verification_outcome="verified",
                    resolution_method="fixture",
                    resolver_version="1",
                )
            ]
        }
    )
    store.record_subject_observation(
        resolver.resolve_exact(post_ref),
        triggering_event_variant_key=admission_result.key,
    )
    stages["post_ref"] = post_ref
    stages["post_a"] = post_a

    post_b = dict(post_a, text="Tiny computers, louder fans.")
    cid_b = _cid(post_b)
    state.move(ALICE_DID, POST_COLLECTION, "3jzfcijpj2z2a", cid_b)
    store.record_subject_observation(
        ResolveResult(
            status="mismatch",
            requested=post_ref,
            current_cid=cid_b,
            record=None,
            checked_at=t0 - timedelta(seconds=30),
            trust_mode="test_fixture",
            verification_outcome="verified",
            resolution_method="fixture",
            resolver_version="1",
        )
    )

    removal = remove(
        ports,
        config,
        admission.record,
        'off-topic <script>alert("reason")</script>',
        now=t0 - timedelta(seconds=10),
    )
    store.ingest(
        _delivery(state.emitted[-1], cursor="3", received_at=t0 - timedelta(seconds=9))
    )
    stages["admission"] = admission.record
    stages["removal"] = removal.record
    stages["ports"] = ports
    return stages


def test_web_appview_serves_the_seeded_lifecycle(tmp_path: Path) -> None:
    path = tmp_path / "observer.sqlite3"
    t0 = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)
    material = _seed_lifecycle(path, t0)
    app = _web_app(path, now=t0)

    # The current page/posts API is healthy and empty after the removal.
    posts = _json(app.handle("GET", POSTS_PATH))
    assert posts["entries"] == []
    assert posts["projectionVersion"] == "v0"
    page = app.handle("GET", f"/c/{SLUG}")
    assert page.status == 200
    html = page.body.decode("utf-8")
    assert "<script>" not in html
    assert "did:web:alice.invalid" not in html

    # Health reports a complete, high-water-matched projection.
    health_response = app.handle("GET", "/health")
    assert health_response.status == 200
    health = _json(health_response)
    assert health["status"] == "ok"
    assert health["highWaterMatches"] is True
    assert health["projectionStatus"] == "complete"
    assert health["sources"][0]["committedCursor"] == "3"
    assert health["sources"][0]["projectedCursor"] == "3"
    assert health["reasonCodes"] == []

    # Audit retains the whole lifecycle, with escaped human rendering.
    audit = _json(app.handle("GET", AUDIT_PATH))
    assert audit["communityDid"] == COMMUNITY_DID
    assert audit["projection"]["fresh"] is True
    kinds = sorted(event["kind"] for event in audit["events"])
    assert kinds == [
        "admission",
        "removal",
        "subject_observation",
        "subject_observation",
        "submission",
    ]
    removal_row = next(event for event in audit["events"] if event["kind"] == "removal")
    assert removal_row["record"] == material["removal"].as_dict()
    assert removal_row["reason"] == 'off-topic <script>alert("reason")</script>'
    assert removal_row["outcome"] == "valid"
    audit_page = app.handle("GET", f"/c/{SLUG}/audit")
    assert audit_page.status == 200
    audit_html = audit_page.body.decode("utf-8")
    assert "<script>" not in audit_html
    assert (
        "off-topic &lt;script&gt;alert(&quot;reason&quot;)&lt;/script&gt;" in audit_html
    )

    # The author record was never mutated by either side.
    state = material["state"]
    assert state.records[(ALICE_DID, POST_COLLECTION, "3jzfcijpj2z2a")].cid != (
        material["post_ref"].cid
    )
    ports = material["ports"]
    assert [call[0] for call in ports.writer.calls] == [
        "create_immutable",
        "create_immutable",
    ]


def test_web_visibility_tracks_the_lifecycle(tmp_path: Path) -> None:
    """Replay the lifecycle stage by stage, checking visibility transitions."""

    path = tmp_path / "observer.sqlite3"
    t0 = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)
    store = ObserverStore(
        path, community_did=COMMUNITY_DID, administrator_did=ADMIN_DID
    )
    state = FakeRepoState()
    ports, config = _daemon(state)
    post_a = {
        "$type": POST_COLLECTION,
        "text": "stage watcher",
        "createdAt": "2026-08-14T11:58:00Z",
    }
    post_ref = state.seed(ALICE_DID, POST_COLLECTION, "3jzfcijpj2z2a", post_a)
    submission_record = {
        "$type": SUBMISSION_COLLECTION,
        "community": COMMUNITY_DID,
        "subject": post_ref.as_dict(),
        "createdAt": "2026-08-14T11:58:30Z",
    }
    submission_ref = state.seed(
        ALICE_DID, SUBMISSION_COLLECTION, "3jzfcijpj2z2b", submission_record
    )

    def visible_texts() -> list[str]:
        app = _web_app(path, now=t0)
        document = _json(app.handle("GET", POSTS_PATH))
        return [entry["post"]["text"] for entry in document["entries"]]

    # Submission alone: audit-visible, absent from the page.
    store.ingest(
        _delivery(
            {
                "repo": ALICE_DID,
                "rev": "3jzfcijpj2z2c",
                "operation": "create",
                "collection": SUBMISSION_COLLECTION,
                "rkey": "3jzfcijpj2z2b",
                "cid": submission_ref.cid,
                "record": submission_record,
            },
            cursor="1",
            received_at=t0 - timedelta(seconds=89),
        )
    )
    assert visible_texts() == []

    # Admission plus an exact observation renders exactly one entry.
    admission = admit(ports, config, submission_ref, now=t0 - timedelta(seconds=60))
    result = store.ingest(
        _delivery(state.emitted[-1], cursor="2", received_at=t0 - timedelta(seconds=59))
    )
    store.record_subject_observation(
        ResolveResult(
            status="exact",
            requested=post_ref,
            current_cid=post_ref.cid,
            record=post_a,
            checked_at=t0 - timedelta(seconds=58),
            trust_mode="test_fixture",
            verification_outcome="verified",
            resolution_method="fixture",
            resolver_version="1",
        ),
        triggering_event_variant_key=result.key,
    )
    assert visible_texts() == ["stage watcher"]

    # Removal keeps it hidden.
    remove(ports, config, admission.record, "cleanup", now=t0 - timedelta(seconds=10))
    store.ingest(
        _delivery(state.emitted[-1], cursor="3", received_at=t0 - timedelta(seconds=9))
    )
    assert visible_texts() == []


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _http(method: str, port: int, path: str) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connection.request(method, path)
    response = connection.getresponse()
    payload = response.read()
    headers = dict(response.getheaders())
    connection.close()
    return response.status, headers, payload


def test_web_subprocess_serves_get_flows(tmp_path: Path) -> None:
    path = tmp_path / "observer.sqlite3"
    t0 = datetime.now(UTC) - timedelta(minutes=5)
    _seed_lifecycle(path, t0)
    port = _free_port()
    config_path = tmp_path / "communitywatch.toml"
    config_path.write_text(
        "\n".join(
            (
                f'community_did = "{COMMUNITY_DID}"',
                f'community_slug = "{SLUG}"',
                f'sqlite_path = "{path}"',
                'event_source_url = "https://relay.invalid"',
                'resolver_url = "https://pds.invalid"',
                f"port = {port}",
                "stale_threshold_seconds = 86400",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin"),
        "HOME": str(tmp_path),
        "PYTHONPATH": os.pathsep.join(str(src) for src in PACKAGE_SRCS),
        # Daemon-side variables deliberately present in the launch
        # environment; the web process must drop and never consult them.
        "COMMUNITYD_CREDENTIAL_REF": CREDENTIAL_REF,
        "COMMUNITYD_CONFIG": "/etc/communityd/communityd.toml",
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "communitywatch_web",
            "--config",
            str(config_path),
        ],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                status, _, _ = _http("GET", port, "/health")
                break
            except OSError:
                if process.poll() is not None:
                    raise AssertionError(
                        f"web subprocess exited {process.returncode}: "
                        f"{process.stderr.read()}"
                    ) from None
                if time.monotonic() > deadline:
                    raise AssertionError("web subprocess never came up") from None
                time.sleep(0.1)

        assert status == 200
        status, headers, payload = _http("GET", port, f"/c/{SLUG}")
        assert status == 200
        assert headers["Content-Type"].startswith("text/html")
        for name, value in SECURITY_HEADERS:
            assert headers.get(name) == value

        status, _, payload = _http("GET", port, POSTS_PATH)
        assert status == 200
        assert json.loads(payload)["entries"] == []

        status, _, payload = _http("GET", port, AUDIT_PATH)
        assert status == 200
        assert json.loads(payload)["projection"]["fresh"] is True

        status, headers, payload = _http("POST", port, POSTS_PATH)
        assert status == 405
        assert headers.get("Allow") == "GET, HEAD, OPTIONS"

        status, _, _ = _http(
            "GET", port, "/api/v0/communities/did:web:other.invalid/posts"
        )
        assert status == 404

        status, _, payload = _http("GET", port, "/c/%2e%2e%2fetc%2fpasswd")
        assert status in (400, 404)
        assert b"root:" not in payload
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_web_entry_point_drops_daemon_environment(tmp_path: Path) -> None:
    """The entry point scrubs the environment before it touches anything."""

    code = (
        "import os\n"
        "from communitywatch_web.cli import main\n"
        "rc = main(['--config', '/nonexistent/communitywatch.toml'])\n"
        "assert 'COMMUNITYD_CREDENTIAL_REF' not in os.environ\n"
        "assert 'SENTINEL' not in os.environ\n"
        "assert rc == 2\n"
    )
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin"),
        "PYTHONPATH": os.pathsep.join(str(src) for src in PACKAGE_SRCS),
        "COMMUNITYD_CREDENTIAL_REF": CREDENTIAL_REF,
        "SENTINEL": "should-be-dropped",
    }
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_web_reads_never_see_partial_generations_under_concurrent_ingest(
    tmp_path: Path,
) -> None:
    path = tmp_path / "observer.sqlite3"
    t0 = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)
    _seed_lifecycle(path, t0)
    app = _web_app(path, now=t0)
    baseline_audit = _json(app.handle("GET", AUDIT_PATH))
    baseline_events = len(baseline_audit["events"])

    writer = ObserverStore(
        path, community_did=COMMUNITY_DID, administrator_did=ADMIN_DID
    )
    failures: list[str] = []
    done = threading.Event()

    def ingest_more() -> None:
        try:
            for index in range(8):
                author = f"did:web:extra{index}.invalid"
                post = {
                    "$type": POST_COLLECTION,
                    "text": f"extra {index}",
                    "createdAt": "2026-08-14T11:59:00Z",
                }
                subject = {
                    "uri": f"at://{author}/{POST_COLLECTION}/3jzfcijpj2z2a",
                    "cid": _cid(post),
                }
                submission = {
                    "$type": SUBMISSION_COLLECTION,
                    "community": COMMUNITY_DID,
                    "subject": subject,
                    "createdAt": "2026-08-14T11:59:00Z",
                }
                writer.ingest(
                    _delivery(
                        {
                            "repo": author,
                            "rev": "3jzfcijpj2z2c",
                            "operation": "create",
                            "collection": SUBMISSION_COLLECTION,
                            "rkey": "3jzfcijpj2z2b",
                            "cid": _cid(submission),
                            "record": submission,
                        },
                        cursor=str(100 + index),
                        received_at=t0 + timedelta(seconds=index),
                    )
                )
        except Exception as exc:  # noqa: BLE001 - reported to the main thread
            failures.append(f"writer: {exc!r}")
        finally:
            done.set()

    def read_loop(label: str) -> None:
        try:
            while not done.is_set():
                for route in (POSTS_PATH, AUDIT_PATH, "/health", f"/c/{SLUG}"):
                    response = app.handle("GET", route)
                    if response.status != 200:
                        failures.append(f"{label} {route}: {response.status}")
                        return
                    if route != f"/c/{SLUG}":
                        json.loads(response.body.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - reported to the main thread
            failures.append(f"{label}: {exc!r}")

    writer_thread = threading.Thread(target=ingest_more)
    readers = [
        threading.Thread(target=read_loop, args=(f"reader-{index}",))
        for index in range(3)
    ]
    writer_thread.start()
    for reader in readers:
        reader.start()
    writer_thread.join(timeout=120)
    for reader in readers:
        reader.join(timeout=120)

    assert done.is_set(), "writer starved beyond the bounded busy timeout"
    assert not failures, "\n".join(failures)

    # Final committed state is consistent and includes every new submission.
    final_audit = _json(app.handle("GET", AUDIT_PATH))
    assert len(final_audit["events"]) == baseline_events + 8
    assert final_audit["projection"]["fresh"] is True
    health = _json(app.handle("GET", "/health"))
    assert health["status"] == "ok"
    assert health["sources"][0]["committedCursor"] == "107"
    assert health["sources"][0]["projectedCursor"] == "107"
