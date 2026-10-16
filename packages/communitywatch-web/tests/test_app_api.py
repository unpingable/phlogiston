"""Wire-contract tests for the JSON read API of the canonical AppView."""

from __future__ import annotations

import base64
import json
import sqlite3
from datetime import timedelta
from pathlib import Path

from community_model import (
    MEMBER_ACTION_COLLECTION,
    REASON_CODES,
    AuditOutcome,
    member_action_rkey,
)
from communitywatch import ObserverStore, ProjectionQuery
from communitywatch_web.app import WebApp
from tests.web_support import (
    ADMIN_DID,
    APP_TIME,
    BASE_TIME,
    COMMUNITY_DID,
    SLUG,
    Sequencer,
    body_json,
    body_text,
    delivery,
    seed_visible_entry,
)

POSTS_KEYS = {
    "community",
    "entries",
    "cursor",
    "projectionVersion",
    "generatedAt",
}
COMMUNITY_KEYS = {"did", "slug", "displayName", "description"}
ENTRY_KEYS = {
    "subject",
    "submission",
    "admission",
    "authorDid",
    "admittedAt",
    "post",
    "sourceUrl",
}
AUDIT_KEYS = {
    "community",
    "communityDid",
    "events",
    "cursor",
    "projection",
    "generatedAt",
}
EVENT_KEYS = {
    "auditRowKey",
    "semanticEventKey",
    "eventVariantKey",
    "payloadHash",
    "payloadHashScope",
    "record",
    "operation",
    "kind",
    "subject",
    "actor",
    "reason",
    "createdAt",
    "firstReceivedAt",
    "verificationOutcomes",
    "receiptCount",
    "outcome",
    "reasonCodes",
}
HEALTH_KEYS = {
    "status",
    "schemaVersion",
    "projectionVersion",
    "activeGeneration",
    "projectionStatus",
    "highWaterMatches",
    "lastIngestAt",
    "lastResolveAt",
    "sources",
    "generatedAt",
    "reasonCodes",
}

POSTS_PATH = f"/api/v0/communities/{COMMUNITY_DID}/posts"
AUDIT_PATH = f"/api/v0/communities/{COMMUNITY_DID}/audit"


def _tamper_high_water(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE projection_builds SET source_high_waters_json = '{}'"
        )


def _decode_cursor(cursor: str) -> dict[str, object]:
    return json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))


def test_posts_wire_shape_matches_the_plan(app: WebApp) -> None:
    response = app.handle("GET", POSTS_PATH)
    assert response.status == 200
    document = body_json(response)
    assert set(document) == POSTS_KEYS
    assert set(document["community"]) == COMMUNITY_KEYS
    assert document["community"]["did"] == COMMUNITY_DID
    assert document["community"]["slug"] == SLUG
    assert document["projectionVersion"] == "v0"
    assert document["generatedAt"] == "2026-08-14T12:00:00Z"
    assert document["cursor"] is None

    entries = document["entries"]
    assert len(entries) == 1
    entry = entries[0]
    assert set(entry) == ENTRY_KEYS
    assert entry["authorDid"] == "did:web:alice.invalid"
    assert entry["post"]["text"] == '<script>alert("xss")</script> loud fans'
    assert entry["sourceUrl"] == (
        "https://bsky.app/profile/did:web:alice.invalid/post/3jzfcijpj2z2a"
    )
    assert entry["subject"]["uri"].startswith("at://did:web:alice.invalid/")


def test_removed_entries_never_appear_in_posts(app: WebApp) -> None:
    document = body_json(app.handle("GET", POSTS_PATH))
    authors = [entry["authorDid"] for entry in document["entries"]]
    assert "did:web:carol.invalid" not in authors


def test_posts_pagination_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "observer.sqlite3"
    store = ObserverStore(
        path, community_did=COMMUNITY_DID, administrator_did=ADMIN_DID
    )
    sequencer = Sequencer()
    for index in range(3):
        seed_visible_entry(
            store,
            sequencer,
            author_did=f"did:web:author{index}.invalid",
            post_rkey=f"3jzfcijpj2z2{chr(ord('a') + index)}",
            submission_rkey=f"3jzfcijpj2z2{chr(ord('k') + index)}",
            text=f"post {index}",
            admitted_at=f"2026-08-13T12:0{index}:00Z",
            observed_at=BASE_TIME + timedelta(minutes=index),
        )
    read_store = ObserverStore(path, community_did=COMMUNITY_DID, read_only=True)
    app = WebApp(
        ProjectionQuery(read_store, slug=SLUG),
        community_did=COMMUNITY_DID,
        slug=SLUG,
        stale_threshold_seconds=0,
        now=lambda: APP_TIME,
    )

    first = body_json(app.handle("GET", f"{POSTS_PATH}?limit=2"))
    assert len(first["entries"]) == 2
    assert first["cursor"] is not None
    cursor_payload = _decode_cursor(first["cursor"])
    assert set(cursor_payload) == {"admittedAt", "admissionUri"}
    assert all(isinstance(value, str) for value in cursor_payload.values())

    second = body_json(
        app.handle("GET", f"{POSTS_PATH}?limit=2&cursor={first['cursor']}")
    )
    assert second["cursor"] is None
    assert len(second["entries"]) == 1
    seen = [
        entry["subject"]["uri"] for entry in (*first["entries"], *second["entries"])
    ]
    assert len(set(seen)) == 3


def test_limit_bounds_and_malformed_values(app: WebApp) -> None:
    for raw in ("0", "101", "abc", "", "-1"):
        response = app.handle("GET", f"{POSTS_PATH}?limit={raw}")
        assert response.status == 400, raw
        assert body_json(response)["error"] == "bad_request"
    response = app.handle("GET", f"{POSTS_PATH}?limit=1&limit=2")
    assert response.status == 400
    assert body_json(app.handle("GET", f"{POSTS_PATH}?limit=1"))["entries"]


def test_malformed_cursors_are_400(app: WebApp) -> None:
    for path in (POSTS_PATH, AUDIT_PATH):
        response = app.handle("GET", f"{path}?cursor=bogus")
        assert response.status == 400, path
        assert body_json(response)["error"] == "bad_request"
        response = app.handle("GET", f"{path}?cursor=a&cursor=b")
        assert response.status == 400, path


def test_unknown_and_malformed_communities_are_404(app: WebApp) -> None:
    for did in ("did:web:other.invalid", "not-a-did"):
        response = app.handle("GET", f"/api/v0/communities/{did}/posts")
        assert response.status == 404, did
        assert body_json(response)["error"] == "unknown_community"


def test_unsupported_methods_are_405(app: WebApp) -> None:
    for method in ("POST", "PUT", "PATCH", "DELETE", "TRACE"):
        for path in (POSTS_PATH, AUDIT_PATH, "/health"):
            response = app.handle(method, path)
            assert response.status == 405, (method, path)
            assert body_json(response)["error"] == "method_not_allowed"
            assert ("Allow", "GET, HEAD, OPTIONS") in response.extra_headers
        # Browser routes carry the same status, header, and reason code in an
        # HTML body instead of JSON.
        response = app.handle(method, f"/c/{SLUG}")
        assert response.status == 405, (method, "html")
        assert "method_not_allowed" in body_text(response)
        assert ("Allow", "GET, HEAD, OPTIONS") in response.extra_headers


def test_unknown_routes_are_404(app: WebApp) -> None:
    for path in ("/api", "/api/v0/communities"):
        response = app.handle("GET", path)
        assert response.status == 404, path
        assert body_json(response)["error"] == "not_found"
    for path in ("/", "/c", "/c/x/y/z", "/x"):
        response = app.handle("GET", path)
        assert response.status == 404, path
        assert "not_found" in body_text(response)


def test_path_traversal_and_header_injection_are_rejected(app: WebApp) -> None:
    hostile = (
        "/c/..",
        "/c/%2e%2e",
        "/c/homelab/..%2f..%2fetc",
        "/c/homelab%2f..",
        "/c/homelab%5c..",
        "/c/homelab%0d%0aInjected: yes",
        f"/api/v0/communities/{COMMUNITY_DID}%0d%0aX-Evil: 1/posts",
        "/api/v0/communities/did%3Aweb%3Ax%2f..%2fsecrets/posts",
    )
    for path in hostile:
        response = app.handle("GET", path)
        assert response.status in (400, 404), path
        if response.content_type.startswith("application/json"):
            document = body_json(response)
            assert set(document) == {"error", "message"}
            assert "\r" not in document["message"] and "\n" not in document["message"]
            assert ".." not in document["message"]
        else:
            # The HTML error page interpolates no part of the request, so the
            # hostile input cannot be reflected at all.
            text = body_text(response)
            for marker in ("Injected", "secrets", "%2e", "%0d", "..", "\\"):
                assert marker not in text, (path, marker)


def test_audit_wire_shape_and_projection_metadata(app: WebApp) -> None:
    document = body_json(app.handle("GET", AUDIT_PATH))
    assert set(document) == AUDIT_KEYS
    assert document["communityDid"] == COMMUNITY_DID
    assert document["projection"] == {
        "generation": "g1",
        "version": "v0",
        "fresh": True,
    }
    assert document["cursor"] is None
    for event in document["events"]:
        assert set(event) == EVENT_KEYS, event


def test_audit_quarantine_and_conflict_rows(app: WebApp) -> None:
    events = body_json(app.handle("GET", AUDIT_PATH))["events"]
    quarantine = [event for event in events if event["kind"] == "quarantine"]
    assert len(quarantine) == 1
    row = quarantine[0]
    assert row["auditRowKey"].startswith("quarantine:")
    key_hex = row["auditRowKey"].removeprefix("quarantine:")
    assert len(key_hex) == 64 and key_hex == key_hex.lower()
    int(key_hex, 16)
    assert row["semanticEventKey"] is None
    assert row["eventVariantKey"] is None
    assert row["record"] is None
    assert row["operation"] is None
    assert row["outcome"] == "invalid"
    assert row["reasonCodes"] == ["commit_revision_invalid"]

    conflicts = [event for event in events if event["outcome"] == "conflict"]
    assert len(conflicts) == 2
    semantic_keys = {event["semanticEventKey"] for event in conflicts}
    variant_keys = {event["eventVariantKey"] for event in conflicts}
    assert len(semantic_keys) == 1
    assert len(variant_keys) == 2
    for event in conflicts:
        assert event["reasonCodes"] == ["semantic_event_conflict"]
        assert event["operation"] == "create"


def test_audit_identity_never_uses_sqlite_rowids(app: WebApp) -> None:
    events = body_json(app.handle("GET", AUDIT_PATH))["events"]
    assert events
    for event in events:
        assert event["auditRowKey"].startswith(
            ("event:sha256:", "observation:sha256:", "quarantine:")
        )
    cursor = None
    while True:
        suffix = "" if cursor is None else f"?limit=2&cursor={cursor}"
        document = body_json(app.handle("GET", f"{AUDIT_PATH}{suffix}"))
        if document["cursor"] is None:
            break
        cursor = document["cursor"]
        payload = _decode_cursor(cursor)
        assert set(payload) == {"receivedAt", "rowKey"}
        assert all(isinstance(value, str) for value in payload.values())


def test_audit_pagination_covers_every_row_once(app: WebApp) -> None:
    seen: list[str] = []
    cursor = None
    while True:
        suffix = "" if cursor is None else f"?limit=3&cursor={cursor}"
        document = body_json(app.handle("GET", f"{AUDIT_PATH}{suffix}"))
        seen.extend(event["auditRowKey"] for event in document["events"])
        cursor = document["cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 11


def test_audit_vocabulary_is_the_closed_plan_set(app: WebApp) -> None:
    events = body_json(app.handle("GET", AUDIT_PATH))["events"]
    outcomes = {event["outcome"] for event in events}
    assert outcomes <= {member.value for member in AuditOutcome}
    codes = {code for event in events for code in event["reasonCodes"]}
    assert codes <= REASON_CODES
    # The fixture exercises the audit-relevant corner vocabulary.
    assert {"commit_revision_invalid", "semantic_event_conflict"} <= codes


def test_health_ok_shape(app: WebApp) -> None:
    response = app.handle("GET", "/health")
    assert response.status == 200
    document = body_json(response)
    assert set(document) == HEALTH_KEYS
    assert document["status"] == "ok"
    assert document["schemaVersion"] == 3
    assert document["projectionVersion"] == "v0"
    assert document["activeGeneration"] == "g1"
    assert document["projectionStatus"] == "complete"
    assert document["highWaterMatches"] is True
    assert document["lastIngestAt"] == "2026-08-13T12:05:00Z"
    assert document["lastResolveAt"] == "2026-08-13T12:02:02Z"
    assert document["sources"] == [
        {
            "name": "fixture-source",
            "committedCursor": "9",
            "projectedCursor": "9",
            "matches": True,
        }
    ]
    assert document["generatedAt"] == "2026-08-14T12:00:00Z"
    assert document["reasonCodes"] == []


def test_health_stale_on_high_water_mismatch(app: WebApp, seeded_db: Path) -> None:
    _tamper_high_water(seeded_db)
    response = app.handle("GET", "/health")
    assert response.status == 503
    document = body_json(response)
    assert document["status"] == "stale"
    assert document["highWaterMatches"] is False
    assert document["reasonCodes"] == ["ingest_stale"]
    assert document["sources"][0]["matches"] is False


def test_health_unavailable_when_projection_incomplete(
    app: WebApp, seeded_db: Path
) -> None:
    with sqlite3.connect(seeded_db) as connection:
        connection.execute("UPDATE projection_builds SET status = 'building'")
    response = app.handle("GET", "/health")
    assert response.status == 503
    document = body_json(response)
    assert document["status"] == "unavailable"
    assert document["projectionStatus"] == "building"
    assert "projection_incomplete" in document["reasonCodes"]


def test_health_unavailable_on_schema_incompatibility(
    app: WebApp, seeded_db: Path
) -> None:
    with sqlite3.connect(seeded_db) as connection:
        connection.execute("UPDATE projection_builds SET reducer_version = 'v-ancient'")
    response = app.handle("GET", "/health")
    assert response.status == 503
    document = body_json(response)
    assert document["status"] == "unavailable"
    assert "schema_incompatible" in document["reasonCodes"]


def test_health_unavailable_without_any_projection(
    app: WebApp, seeded_db: Path
) -> None:
    with sqlite3.connect(seeded_db) as connection:
        connection.execute("DELETE FROM projection_builds")
    response = app.handle("GET", "/health")
    assert response.status == 503
    document = body_json(response)
    assert document["status"] == "unavailable"
    assert document["projectionStatus"] == "missing"
    assert "projection_incomplete" in document["reasonCodes"]


def test_health_stale_when_heartbeats_exceed_the_threshold(
    app: WebApp,
) -> None:
    app.stale_threshold_seconds = 180
    response = app.handle("GET", "/health")
    assert response.status == 503
    document = body_json(response)
    assert document["status"] == "stale"
    assert document["reasonCodes"] == ["ingest_stale", "resolve_stale"]


def test_current_view_503_but_audit_serves_last_complete_generation(
    app: WebApp, seeded_db: Path
) -> None:
    _tamper_high_water(seeded_db)
    response = app.handle("GET", POSTS_PATH)
    assert response.status == 503
    assert body_json(response)["error"] == "projection_unavailable"
    page = app.handle("GET", f"/c/{SLUG}")
    assert page.status == 503
    text = body_text(page)
    assert "ingest_stale" in text
    assert "still catching up" in text

    document = body_json(app.handle("GET", AUDIT_PATH))
    assert document["projection"]["fresh"] is False
    assert document["events"]
    page = app.handle("GET", f"/c/{SLUG}/audit")
    assert page.status == 200
    assert "may lag the latest observations" in page.body.decode("utf-8")


def test_audit_503_when_no_compatible_complete_generation(
    app: WebApp, seeded_db: Path
) -> None:
    with sqlite3.connect(seeded_db) as connection:
        connection.execute("UPDATE projection_builds SET status = 'building'")
    response = app.handle("GET", AUDIT_PATH)
    assert response.status == 503
    assert body_json(response)["error"] == "projection_unavailable"
    page = app.handle("GET", f"/c/{SLUG}/audit")
    assert page.status == 503
    assert "projection_incomplete" in body_text(page)


def test_errors_never_leak_paths_or_exception_text(
    app: WebApp, seeded_db: Path
) -> None:
    seeded_db.unlink()
    for path in (POSTS_PATH, AUDIT_PATH):
        response = app.handle("GET", path)
        assert response.status == 503, path
        document = body_json(response)
        assert set(document) == {"error", "message"}
        text = json.dumps(document)
        assert str(seeded_db) not in text
        assert "Traceback" not in text
        assert "sqlite3" not in text
    page = app.handle("GET", f"/c/{SLUG}")
    assert page.status == 503
    html = body_text(page)
    assert str(seeded_db) not in html
    assert "Traceback" not in html
    assert "sqlite3" not in html
    health = app.handle("GET", "/health")
    assert health.status == 503
    document = body_json(health)
    assert document["status"] == "unavailable"
    assert document["reasonCodes"] == ["projection_missing"]
    assert str(seeded_db) not in json.dumps(document)


def test_discussion_read_surfaces_carry_snapshot_boundary(app: WebApp) -> None:
    base = f"/api/v0/communities/{COMMUNITY_DID}"
    listing = body_json(app.handle("GET", f"{base}/discussions"))
    assert set(listing) == {"communityDid", "discussions", "cursor", "snapshot"}
    assert listing["snapshot"]["generation"] == "g1"
    assert isinstance(listing["snapshot"]["observerSequence"], int)
    assert len(listing["discussions"]) == 1
    root = listing["discussions"][0]
    assert root["closed"] is False
    assert root["post"]["text"] == '<script>alert("xss")</script> loud fans'

    admission_rkey_value = root["discussion"]["uri"].rsplit("/", 1)[-1]
    detail = body_json(app.handle("GET", f"{base}/discussions/{admission_rkey_value}"))
    assert detail["discussion"] == root
    assert detail["replies"] == []
    assert detail["activity"][0]["type"] == "root_admitted"
    assert detail["snapshot"] == listing["snapshot"]

    participant = body_json(
        app.handle("GET", f"{base}/participants/did:web:alice.invalid")
    )
    assert len(participant["discussions"]) == 1
    assert participant["activity"][0]["type"] == "root_admitted"
    assert participant["activity"][0]["discussion"] == root["discussion"]
    assert participant["snapshot"] == listing["snapshot"]


def test_moderation_queue_is_read_only_and_versioned(app: WebApp) -> None:
    path = f"/api/v0/communities/{COMMUNITY_DID}/moderation-queue"
    response = app.handle("GET", path)
    assert response.status == 200
    document = body_json(response)
    assert set(document) == {
        "communityDid",
        "submissions",
        "snapshot",
        "nextCursor",
        "coverage",
    }
    assert document["coverage"]["kind"] == "candidates"
    assert document["snapshot"]["generation"] == "g1"

    candidates = body_json(
        app.handle("GET", f"/api/v0/communities/{COMMUNITY_DID}/reply-candidates")
    )
    assert set(candidates) == {"communityDid", "candidates", "snapshot"}
    assert candidates["candidates"] == []
    assert candidates["snapshot"] == document["snapshot"]
    assert app.handle("POST", path).status == 405


def test_membership_projection_comes_only_from_authority_records(
    tmp_path: Path,
) -> None:
    path = tmp_path / "members.sqlite3"
    store = ObserverStore(
        path, community_did=COMMUNITY_DID, administrator_did=ADMIN_DID
    )
    sequence = Sequencer()
    for action, minute in (("add", 1), ("remove", 2)):
        record = {
            "$type": MEMBER_ACTION_COLLECTION,
            "action": action,
            "subject": "did:web:member.invalid",
            "actor": ADMIN_DID,
            "reason": "left" if action == "remove" else "approved",
            "createdAt": f"2026-08-13T12:0{minute}:00Z",
        }
        store.ingest(
            delivery(
                sequence,
                repo=COMMUNITY_DID,
                collection=MEMBER_ACTION_COLLECTION,
                rkey=member_action_rkey("did:web:member.invalid", action),
                record=record,
                at=BASE_TIME + timedelta(minutes=minute),
            )
        )
    read = ObserverStore(path, community_did=COMMUNITY_DID, read_only=True)
    app = WebApp(
        ProjectionQuery(read, slug=SLUG),
        community_did=COMMUNITY_DID,
        slug=SLUG,
        stale_threshold_seconds=0,
        now=lambda: APP_TIME,
    )
    response = app.handle("GET", f"/api/v0/communities/{COMMUNITY_DID}/members")
    document = body_json(response)
    assert response.status == 200
    assert document["members"] == [
        {
            "did": "did:web:member.invalid",
            "status": "removed",
            "action": "remove",
            "actor": ADMIN_DID,
            "reason": "left",
            "createdAt": "2026-08-13T12:02:00Z",
            "record": {
                "uri": f"at://{COMMUNITY_DID}/{MEMBER_ACTION_COLLECTION}/{member_action_rkey('did:web:member.invalid', 'remove')}",
                "cid": document["members"][0]["record"]["cid"],
            },
        }
    ]
    assert (
        app.handle("POST", f"/api/v0/communities/{COMMUNITY_DID}/members").status == 405
    )


def test_moderation_queue_rejects_oversized_cursor(app: WebApp) -> None:
    path = f"/api/v0/communities/{COMMUNITY_DID}/moderation-queue?cursor=" + "A" * 2049
    assert app.handle("GET", path).status == 400
