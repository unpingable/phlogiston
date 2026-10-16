"""HTML surface tests: canonical page, audit page, escaping, fallback."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from communitywatch import ObserverStore, ProjectionQuery
from communitywatch_web.app import WebApp
from tests.web_support import (
    APP_TIME,
    COMMUNITY_DID,
    SLUG,
    body_text,
)


def test_community_page_renders_visible_entries_escaped(app: WebApp) -> None:
    response = app.handle("GET", f"/c/{SLUG}")
    assert response.status == 200
    assert response.content_type.startswith("text/html")
    html = response.body.decode("utf-8")

    assert "<script>" not in html
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt; loud fans" in html
    # Profile decoration is escaped too (displayName and description).
    assert "Homelab &lt;Friends&gt;" in html
    assert "&lt;/p&gt;&lt;script&gt;alert(2)&lt;/script&gt;" in html
    assert "did:web:alice.invalid" in html
    assert f"<code>{COMMUNITY_DID}</code>" in html
    # The removed entry never renders.
    assert "did:web:carol.invalid" not in html
    assert "off-topic noise" not in html
    assert 'class="degraded"' not in html


def test_community_page_unknown_slug_is_404(app: WebApp) -> None:
    for slug in ("other", "..", "homelab2"):
        response = app.handle("GET", f"/c/{slug}")
        assert response.status == 404, slug
        assert "unknown_community" in body_text(response)


def test_community_page_503_when_projection_stale(app: WebApp, seeded_db: Path) -> None:
    with sqlite3.connect(seeded_db) as connection:
        connection.execute(
            "UPDATE projection_builds SET source_high_waters_json = '{}'"
        )
    response = app.handle("GET", f"/c/{SLUG}")
    assert response.status == 503
    text = body_text(response)
    assert "ingest_stale" in text
    assert "still catching up" in text


def test_audit_page_lists_events_and_escapes_reasons(app: WebApp) -> None:
    response = app.handle("GET", f"/c/{SLUG}/audit")
    assert response.status == 200
    html = response.body.decode("utf-8")

    assert "Homelab &lt;Friends&gt; audit log" in html
    assert "<script>" not in html
    assert "off-topic &lt;script&gt;alert(&quot;reason&quot;)&lt;/script&gt;" in html
    for kind in ("submission", "admission", "removal", "quarantine"):
        assert f'<span class="kind">{kind}</span>' in html
    assert '<span class="outcome">conflict</span>' in html
    assert "semantic_event_conflict" in html
    assert 'class="degraded"' not in html


def test_audit_page_shows_a_stale_banner_when_degraded(
    app: WebApp, seeded_db: Path
) -> None:
    with sqlite3.connect(seeded_db) as connection:
        connection.execute(
            "UPDATE projection_builds SET source_high_waters_json = '{}'"
        )
    response = app.handle("GET", f"/c/{SLUG}/audit")
    assert response.status == 200
    html = response.body.decode("utf-8")
    assert '<p class="degraded">' in html
    assert "may lag the latest observations" in html


def test_profile_fallback_renders_slug_identity(tmp_path: Path) -> None:
    path = tmp_path / "observer.sqlite3"
    ObserverStore(
        path, community_did=COMMUNITY_DID, administrator_did="did:web:admin.invalid"
    )
    store = ObserverStore(path, community_did=COMMUNITY_DID, read_only=True)
    app = WebApp(
        ProjectionQuery(store, slug=SLUG),
        community_did=COMMUNITY_DID,
        slug=SLUG,
        stale_threshold_seconds=0,
        now=lambda: APP_TIME,
    )
    response = app.handle("GET", f"/c/{SLUG}")
    assert response.status == 200
    html = response.body.decode("utf-8")
    assert f"<h1>{SLUG}</h1>" in html
    assert 'class="community-description"' not in html
    assert f"<code>{COMMUNITY_DID}</code>" in html


def test_head_matches_get_headers_and_body(app: WebApp) -> None:
    get = app.handle("GET", f"/c/{SLUG}")
    head = app.handle("HEAD", f"/c/{SLUG}")
    assert (head.status, head.content_type, head.body) == (
        get.status,
        get.content_type,
        get.body,
    )
