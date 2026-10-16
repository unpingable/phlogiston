from __future__ import annotations

from communitywatch import render_community_page

IDENTITY = {
    "did": "did:web:community.invalid",
    "slug": "homelab",
    "displayName": "Homelab",
    "description": "Tiny computers.",
}


def _entry(text: str, source_url: str) -> dict[str, object]:
    return {
        "subject": {
            "uri": "at://did:web:alice.invalid/app.bsky.feed.post/x",
            "cid": "b",
        },
        "authorDid": "did:web:alice.invalid",
        "admittedAt": "2026-08-13T12:01:00Z",
        "post": {"text": text, "createdAt": "2026-08-13T12:00:00Z"},
        "sourceUrl": source_url,
    }


def test_page_escapes_post_profile_and_link_text() -> None:
    hostile_identity = {
        **IDENTITY,
        "displayName": '<img src=x onerror="alert(1)">',
        "description": "</p><script>alert(2)</script>",
    }
    entry = _entry(
        '<script>alert("xss")</script>',
        'https://bsky.app/profile/x/post/y" onclick="evil()',
    )
    page = render_community_page(hostile_identity, [entry])

    assert "<script>" not in page
    assert "onclick=" not in page.replace("onclick=&quot;", "")
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;" in page
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in page
    assert "https://bsky.app/profile/x/post/y&quot; onclick=&quot;evil()" in page


def test_page_renders_plain_content_and_degraded_banner() -> None:
    page = render_community_page(
        IDENTITY, [_entry("hello world", "https://bsky.app/profile/a/post/b")]
    )
    assert "<h1>Homelab</h1>" in page
    assert "hello world" in page
    assert "did:web:alice.invalid" in page
    assert "2026-08-13T12:01:00Z" in page

    degraded = render_community_page(IDENTITY, [], degraded_banner="stale <data>")
    assert "stale &lt;data&gt;" in degraded


def test_page_without_description_omits_the_paragraph() -> None:
    identity = {**IDENTITY, "description": None}
    page = render_community_page(identity, [])
    assert '<p class="community-description">' not in page


def test_every_projection_state_has_human_words() -> None:
    """The vocabulary is a total relabelling of the V0 projected states."""

    from community_model.constants import ProjectionState
    from communitywatch.render import describe_state

    for state in ProjectionState:
        words = describe_state(state.value)
        assert words.label, state
        assert words.meaning.endswith("."), state
    # Item-level and place-level failure never share wording.
    assert describe_state("subject_unavailable").label == "Can't check right now"
    assert describe_state("removed").label == "Removed"
    assert describe_state("stale_cid").label == "Changed at source"
    assert describe_state("subject_deleted").label == "Deleted by author"
    # An unknown token degrades conservatively instead of leaking itself.
    assert describe_state("wat").label == "Not shown"
    assert "wat" not in describe_state("wat").meaning


def test_error_page_explains_place_level_failure_without_reflecting_input() -> None:
    from communitywatch.render import render_error_page

    page = render_error_page(503, "ingest_stale", slug="homelab")
    assert "still catching up" in page
    assert "ingest_stale" in page
    assert '<a href="/c/homelab">' in page
    # Distinct from any item-level state wording.
    assert "Can't check right now" not in page


def test_stylesheet_hash_matches_the_inlined_stylesheet() -> None:
    """The CSP hash must cover exactly the bytes the page inlines."""

    import base64
    import hashlib

    from communitywatch.render import STYLE_SHA256, STYLESHEET, render_error_page

    expected = "sha256-" + base64.b64encode(
        hashlib.sha256(STYLESHEET.encode("utf-8")).digest()
    ).decode("ascii")
    assert STYLE_SHA256 == expected
    assert f"<style>{STYLESHEET}</style>" in render_error_page(404, "not_found")


def test_audit_kinds_all_have_a_human_gloss() -> None:
    """Every kind the reducer emits gets plain words, not a repeated token."""

    from communitywatch.render import _AUDIT_KIND_WORDS

    for kind in (
        "submission",
        "admission",
        "removal",
        "profile",
        "subject_observation",
        "quarantine",
        "ignored",
    ):
        gloss = _AUDIT_KIND_WORDS.get(kind)
        assert gloss and gloss != kind, kind
