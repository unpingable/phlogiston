"""Item permalink surface: standing, provenance, and fail-closed behaviour.

The permalink is the object a member pastes back into their group chat, so it
must keep explaining an item after removal rather than 404ing, and must refuse
rather than reassure when the projection cannot be served.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from community_model import RecordRef
from communitywatch_web.app import WebApp
from tests.web_support import (
    SLUG,
    body_text,
)


def _rkey(ref: object) -> str:
    assert isinstance(ref, RecordRef)
    return ref.uri.rsplit("/", 1)[-1]


def test_community_page_links_each_item_to_its_permalink(app: WebApp) -> None:
    html = body_text(app.handle("GET", f"/c/{SLUG}"))
    assert f'href="/c/{SLUG}/i/admit-' in html
    assert "why is this here?" in html
    assert "Open on Bluesky" in html
    # The authority statement names the community, not an unbacked roster.
    assert "Who decides what is here" in html
    assert "signs each decision into its" in html


def test_item_page_explains_an_added_item(app: WebApp, refs: dict) -> None:
    html = body_text(app.handle("GET", f"/c/{SLUG}"))
    rkey = html.split(f'href="/c/{SLUG}/i/', 1)[1].split('"', 1)[0]
    response = app.handle("GET", f"/c/{SLUG}/i/{rkey}")
    assert response.status == 200
    page = response.body.decode("utf-8")

    assert "Added" in page
    assert "This is currently part of this community." in page
    # Ordinary-language provenance, no ATProto vocabulary above the fold.
    assert "Posted and suggested by" in page
    assert "only accepts posts suggested by their own author" in page
    assert "Added by" in page
    assert "did:web:admin.invalid" in page
    assert "fetched the signed repository record itself" in page
    # Hostile post text stays escaped on the item surface too.
    assert "<script>" not in page
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt; loud fans" in page
    # The exact technical refs stay available behind disclosure.
    assert "<summary>Technical details</summary>" in page
    assert "projected state <code>visible</code>" in page


def test_item_page_still_explains_a_removed_item(app: WebApp, refs: dict) -> None:
    """A pasted permalink must survive removal and say what happened."""

    rkey = _rkey(refs["removed_admission"])
    response = app.handle("GET", f"/c/{SLUG}/i/{rkey}")
    assert response.status == 200
    page = response.body.decode("utf-8")

    assert "Removed" in page
    assert "The original post still exists on Bluesky." in page
    assert "Removed by" in page
    assert "Reason given" in page
    # The moderator's hostile reason text is escaped, not executed.
    assert "<script>" not in page
    assert "off-topic &lt;script&gt;alert(&quot;reason&quot;)&lt;/script&gt;" in page
    assert "projected state <code>removed</code>" in page
    # And it is still absent from the community listing.
    assert "off-topic noise" not in body_text(app.handle("GET", f"/c/{SLUG}"))


def test_unknown_item_is_404_html(app: WebApp) -> None:
    response = app.handle("GET", f"/c/{SLUG}/i/admit-nope")
    assert response.status == 404
    assert "not_found" in body_text(response)


def test_item_page_wrong_slug_is_404(app: WebApp, refs: dict) -> None:
    rkey = _rkey(refs["removed_admission"])
    response = app.handle("GET", f"/c/other/i/{rkey}")
    assert response.status == 404
    assert "unknown_community" in body_text(response)


def test_item_page_fails_closed_when_projection_stale(
    app: WebApp, seeded_db: Path, refs: dict
) -> None:
    """A permalink refuses rather than showing possibly-superseded standing."""

    rkey = _rkey(refs["removed_admission"])
    with sqlite3.connect(seeded_db) as connection:
        connection.execute(
            "UPDATE projection_builds SET source_high_waters_json = '{}'"
        )
    response = app.handle("GET", f"/c/{SLUG}/i/{rkey}")
    assert response.status == 503
    text = body_text(response)
    assert "ingest_stale" in text
    assert "still catching up" in text


def test_empty_page_distinguishes_never_used_from_all_removed(
    tmp_path: Path,
) -> None:
    """M8 finding 1: the two kinds of empty must not read identically."""

    from communitywatch import ObserverStore, ProjectionQuery
    from tests.web_support import (
        ADMIN_DID,
        APP_TIME,
        BASE_TIME,
        COMMUNITY_DID,
        Sequencer,
        seed_removal,
        seed_visible_entry,
    )

    def build(path: Path) -> WebApp:
        store = ObserverStore(path, community_did=COMMUNITY_DID, read_only=True)
        return WebApp(
            ProjectionQuery(store, slug=SLUG),
            community_did=COMMUNITY_DID,
            slug=SLUG,
            stale_threshold_seconds=0,
            now=lambda: APP_TIME,
        )

    fresh = tmp_path / "fresh.sqlite3"
    ObserverStore(fresh, community_did=COMMUNITY_DID, administrator_did=ADMIN_DID)
    text = body_text(build(fresh).handle("GET", f"/c/{SLUG}"))
    assert "Nothing has been added to this community yet." in text

    emptied = tmp_path / "emptied.sqlite3"
    store = ObserverStore(
        emptied, community_did=COMMUNITY_DID, administrator_did=ADMIN_DID
    )
    sequencer = Sequencer()
    refs = seed_visible_entry(
        store,
        sequencer,
        author_did="did:web:zoe.invalid",
        post_rkey="3jzfcijpj2z2q",
        submission_rkey="3jzfcijpj2z2r",
        text="only item",
        admitted_at="2026-08-13T12:01:00Z",
        observed_at=BASE_TIME,
    )
    seed_removal(
        store,
        sequencer,
        subject=refs["subject"],
        admission=refs["admission"],
        reason="cleared out",
        at=BASE_TIME,
    )
    text = body_text(build(emptied).handle("GET", f"/c/{SLUG}"))
    assert "Nothing is being shown here right now" in text
    assert "some were removed" in text
    assert "Nothing has been added to this community yet." not in text
