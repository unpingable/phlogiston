"""Escaped HTML rendering for the canonical community AppView.

Every interpolated value is HTML-escaped, attributes included; hostile record
text cannot inject markup.  The stylesheet is a module constant with no
interpolation, and its SHA-256 is exported as :data:`STYLE_SHA256` so the web
layer can admit exactly this one inline style block by hash rather than by
``'unsafe-inline'``.

Presentation explains standing.  It never computes or alters it: every state
shown here is read from the committed projection, and the vocabulary below is
a pure relabelling of the states defined in ``docs/V0-STATE-MACHINE.md``.
"""

from __future__ import annotations

import base64
import hashlib
import html
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

STYLESHEET = """
:root {
  color-scheme: light dark;
  --bg: #fbfbfa; --fg: #1b1b1a; --muted: #5c5c58; --line: #e0e0dc;
  --card: #ffffff; --accent: #2b5d4c; --warn-bg: #fdf6e3; --warn-fg: #6b4e00;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #16171a; --fg: #e9e9e6; --muted: #a0a09a; --line: #2c2e33;
    --card: #1d1f23; --accent: #7fbfa6; --warn-bg: #2e2716; --warn-fg: #e8cf94;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 1rem 1rem 4rem; background: var(--bg); color: var(--fg);
  font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  -webkit-text-size-adjust: 100%;
}
.wrap { max-width: 38rem; margin: 0 auto; }
a { color: var(--accent); }
h1 { font-size: 1.5rem; line-height: 1.25; margin: 0 0 .35rem; }
h2 { font-size: 1.05rem; margin: 2rem 0 .6rem; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .8em;
  overflow-wrap: anywhere; }
.community-description { margin: .35rem 0 .9rem; color: var(--fg); }
.authority { margin: .9rem 0 0; padding: .7rem .8rem; border: 1px solid var(--line);
  border-radius: .5rem; background: var(--card); font-size: .875rem;
  color: var(--muted); }
.authority strong { color: var(--fg); font-weight: 600; }
.community-did { margin: .4rem 0 0; font-size: .8rem; color: var(--muted); }
.degraded { margin: 1rem 0; padding: .7rem .8rem; border-radius: .5rem;
  background: var(--warn-bg); color: var(--warn-fg); font-size: .9rem; }
nav.crumbs { margin: 0 0 1rem; font-size: .875rem; }
main { margin-top: 1.25rem; }
article { padding: .9rem 1rem; margin: 0 0 .75rem; background: var(--card);
  border: 1px solid var(--line); border-radius: .6rem; }
.post-text { margin: 0 0 .6rem; white-space: pre-wrap; overflow-wrap: anywhere; }
.post-meta { margin: 0; font-size: .8rem; color: var(--muted);
  display: flex; flex-wrap: wrap; gap: .5rem; align-items: baseline; }
.post-meta a { text-decoration: none; }
.state { display: inline-block; padding: .1rem .45rem; border-radius: .3rem;
  border: 1px solid var(--line); font-size: .75rem; color: var(--muted); }
.state-visible { color: var(--accent); border-color: var(--accent); }
.empty { padding: 1.5rem 1rem; border: 1px dashed var(--line); border-radius: .6rem;
  color: var(--muted); text-align: center; }
.why { margin: 1.25rem 0 0; }
.why dt { font-size: .75rem; color: var(--muted); margin-top: .7rem; }
.why dd { margin: .1rem 0 0; overflow-wrap: anywhere; }
details { margin-top: 1.25rem; border-top: 1px solid var(--line); padding-top: .8rem; }
summary { cursor: pointer; font-size: .875rem; color: var(--muted); }
.tech { font-size: .8rem; color: var(--muted); }
.tech p { margin: .45rem 0; overflow-wrap: anywhere; }
.audit-head { margin: 0 0 .4rem; display: flex; flex-wrap: wrap; gap: .4rem;
  align-items: baseline; font-size: .8rem; }
.kind { font-weight: 600; color: var(--fg); font-size: .9rem; }
.outcome, .audit-record, .audit-subject, .audit-actor, .audit-reason,
.audit-codes { color: var(--muted); font-size: .8rem; }
.audit-record, .audit-subject, .audit-actor, .audit-reason, .audit-codes {
  margin: .2rem 0 0; }
.gloss { color: var(--fg); }
footer { margin-top: 2.5rem; font-size: .8rem; color: var(--muted);
  border-top: 1px solid var(--line); padding-top: .8rem; }
"""

STYLE_SHA256 = "sha256-" + base64.b64encode(
    hashlib.sha256(STYLESHEET.encode("utf-8")).digest()
).decode("ascii")


@dataclass(frozen=True, slots=True)
class StateWords:
    """Ordinary-language rendering of one projected state."""

    label: str
    meaning: str


# A pure relabelling of docs/V0-STATE-MACHINE.md projected states.  Adding a
# state here changes no semantics; a state absent from this map falls back to
# the conservative "not shown" wording rather than leaking the raw token.
_STATE_WORDS: Mapping[str, StateWords] = {
    "visible": StateWords(
        "Added",
        "This is currently part of this community.",
    ),
    "removed": StateWords(
        "Removed",
        "A moderator removed this from the community. "
        "The original post still exists on Bluesky.",
    ),
    "stale_cid": StateWords(
        "Changed at source",
        "The author edited this post after it was added, so the exact version "
        "this community accepted is no longer the current one.",
    ),
    "subject_deleted": StateWords(
        "Deleted by author",
        "The author deleted the original post, so there is nothing left to show.",
    ),
    "subject_unavailable": StateWords(
        "Can't check right now",
        "This community could not reach the original post to confirm it. "
        "This is temporary and resolves on its own.",
    ),
    "submitted": StateWords(
        "Suggested",
        "Someone suggested this, and no moderator has added it yet.",
    ),
    "pending": StateWords(
        "Waiting on related records",
        "Part of the record this refers to has not arrived yet, "
        "so its status cannot be settled.",
    ),
    "invalid": StateWords(
        "Not shown",
        "The records for this did not pass validation, so it is not part of "
        "this community.",
    ),
    "unauthorized": StateWords(
        "Not shown",
        "This was not accepted from this community's own authority, "
        "so it is not part of the community.",
    ),
    "conflict": StateWords(
        "Not shown",
        "The records for this disagree with each other, so this community "
        "will not show it.",
    ),
}

_UNKNOWN_STATE = StateWords(
    "Not shown",
    "This community cannot currently show this item.",
)

# Place-level failure reasons, as distinct from an item's own state.
_REASON_WORDS: Mapping[str, str] = {
    "projection_missing": "This community has not finished building its view yet.",
    "projection_incomplete": "This community has not finished building its view yet.",
    "schema_incompatible": (
        "This community's stored view was built by a different version "
        "and cannot be shown safely."
    ),
    "ingest_stale": (
        "This community is still catching up on recent changes. "
        "Showing the list now could hide a removal, so it is withheld."
    ),
    "unknown_community": "There is no community at this address.",
    "not_found": "There is nothing at this address.",
    "bad_request": "That address was not understood.",
    "method_not_allowed": "That kind of request is not supported here.",
    "internal_error": "Something went wrong while building this page.",
    "projection_unavailable": (
        "This community's view is not available right now. "
        "Nothing is shown rather than showing something misleading."
    ),
}


def describe_state(state: object) -> StateWords:
    """Return ordinary-language words for one projected state."""

    return _STATE_WORDS.get(str(state), _UNKNOWN_STATE)


def describe_reason(code: object) -> str:
    """Return ordinary-language text for one place-level reason code."""

    return _REASON_WORDS.get(str(code), _REASON_WORDS["projection_unavailable"])


def _text(value: object) -> str:
    return html.escape(str(value), quote=True)


def _rkey_of(uri: object) -> str:
    """Last path segment of an AT URI, used as the stable item permalink key."""

    text = str(uri)
    return text.rsplit("/", 1)[-1] if "/" in text else text


def _document(title: str, body: Sequence[str]) -> str:
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{title}</title>",
        f"<style>{STYLESHEET}</style>",
        "</head>",
        "<body>",
        '<div class="wrap">',
        *body,
        "</div>",
        "</body>",
        "</html>",
    ]
    return "\n".join(parts) + "\n"


def _identity_header(
    identity: Mapping[str, object], *, degraded_banner: str | None
) -> list[str]:
    display_name = _text(identity.get("displayName", ""))
    description = identity.get("description")
    parts = [f"<h1>{display_name}</h1>"]
    if description is not None:
        parts.append(f'<p class="community-description">{_text(description)}</p>')
    parts.append(
        f'<p class="community-did">Community <code>{_text(identity.get("did", ""))}'
        "</code></p>"
    )
    if degraded_banner is not None:
        parts.append(f'<p class="degraded">{_text(degraded_banner)}</p>')
    return parts


def _authority_note(identity: Mapping[str, object], *, has_profile: bool) -> str:
    """State what can be said honestly about who curates, and nothing more."""

    name = _text(identity.get("displayName", ""))
    did = _text(identity.get("did", ""))
    described = (
        "Its name and description above come from a record this community signed."
        if has_profile
        else "This community has not published a name or description record yet."
    )
    return (
        '<p class="authority">'
        f"<strong>Who decides what is here:</strong> everything is added or "
        f"removed by <strong>{name}</strong>, which signs each decision into its "
        f"own repository as <code>{did}</code>. {described}"
        "</p>"
    )


def render_community_page(
    identity: Mapping[str, object],
    entries: Sequence[Mapping[str, object]],
    *,
    degraded_banner: str | None = None,
    has_profile: bool = True,
    hidden_count: int = 0,
) -> str:
    """Render the escaped canonical page for visible entries only."""

    display_name = _text(identity.get("displayName", ""))
    slug = _text(identity.get("slug", ""))
    body = _identity_header(identity, degraded_banner=degraded_banner)
    body.append(_authority_note(identity, has_profile=has_profile))
    body.append("<main>")
    if not entries:
        # M8 finding 1: an empty page must say which kind of empty it is.
        message = (
            "Nothing is being shown here right now. Items have been added "
            "before — some were removed, or their originals changed. "
            "The activity log below has the details."
            if hidden_count
            else "Nothing has been added to this community yet."
        )
        body.append(f'<p class="empty">{_text(message)}</p>')
    for entry in entries:
        post = entry.get("post")
        post_mapping = post if isinstance(post, Mapping) else {}
        admission = entry.get("admission")
        admission_uri = admission.get("uri") if isinstance(admission, Mapping) else ""
        permalink = f"/c/{slug}/i/{_text(_rkey_of(admission_uri))}"
        body.append("<article>")
        body.append(f'<p class="post-text">{_text(post_mapping.get("text", ""))}</p>')
        body.append(
            '<p class="post-meta">'
            f'<span class="author">{_text(entry.get("authorDid", ""))}</span> '
            f"<time>{_text(entry.get('admittedAt', ''))}</time> "
            f'<a href="{permalink}">why is this here?</a> '
            f'<a href="{_text(entry.get("sourceUrl", ""))}">Open on Bluesky</a>'
            "</p>"
        )
        body.append("</article>")
    body.append("</main>")
    body.append(
        f'<footer><a href="/c/{slug}/audit">Full activity log</a> — every decision '
        f"this community has made, including ones not shown above.</footer>"
    )
    return _document(display_name, body)


def render_item_page(
    identity: Mapping[str, object],
    entry: Mapping[str, object],
    status: object,
    events: Sequence[Mapping[str, object]],
) -> str:
    """Render one item's standing and its ordinary-language provenance."""

    display_name = _text(identity.get("displayName", ""))
    slug = _text(identity.get("slug", ""))
    words = describe_state(status)
    post = entry.get("post")
    post_mapping = post if isinstance(post, Mapping) else {}
    state_class = " state-visible" if str(status) == "visible" else ""
    body = [
        f'<nav class="crumbs"><a href="/c/{slug}">&larr; {display_name}</a></nav>',
        "<article>",
    ]
    if "text" in post_mapping:
        body.append(f'<p class="post-text">{_text(post_mapping.get("text", ""))}</p>')
    else:
        body.append(
            '<p class="post-text"><em>The text of this post is not available '
            "to this community.</em></p>"
        )
    body.append(
        '<p class="post-meta">'
        f'<span class="state{state_class}">{_text(words.label)}</span> '
        f'<span class="author">{_text(entry.get("authorDid", ""))}</span> '
        f'<a href="{_text(entry.get("sourceUrl", ""))}">Open on Bluesky</a>'
        "</p>"
    )
    body.append("</article>")
    body.append(f'<p class="gloss">{_text(words.meaning)}</p>')

    body.append("<h2>Why is this here?</h2>")
    body.append('<dl class="why">')
    added_by = next(
        (
            row.get("actor")
            for row in events
            if row.get("kind") == "admission" and row.get("actor") is not None
        ),
        None,
    )
    removed_by = next(
        (
            row.get("actor")
            for row in events
            if row.get("kind") == "removal" and row.get("actor") is not None
        ),
        None,
    )
    removal_reason = next(
        (
            row.get("reason")
            for row in events
            if row.get("kind") == "removal" and row.get("reason") is not None
        ),
        None,
    )
    # V0 accepts self-submission only (community-model records.py enforces that
    # a submission's repository is the subject's author), so the suggester and
    # the author are the same party by construction.  Rendering them as two
    # identical rows reads as noise; one row states the fact and why.
    body.append("<dt>Posted and suggested by</dt>")
    body.append(
        f"<dd>{_text(entry.get('authorDid', ''))}<br>"
        "<small>This community only accepts posts suggested by their own "
        "author.</small></dd>"
    )
    if added_by is not None:
        body.append("<dt>Added by</dt>")
        body.append(f"<dd>{_text(added_by)}</dd>")
    body.append("<dt>Added at</dt>")
    body.append(f"<dd>{_text(entry.get('admittedAt', ''))}</dd>")
    if removed_by is not None:
        body.append("<dt>Removed by</dt>")
        body.append(f"<dd>{_text(removed_by)}</dd>")
    if removal_reason is not None:
        body.append("<dt>Reason given</dt>")
        body.append(f"<dd>{_text(removal_reason)}</dd>")
    outcomes = sorted(
        {
            str(outcome)
            for row in events
            for outcome in _as_sequence(row.get("verificationOutcomes"))
        }
    )
    if outcomes:
        body.append("<dt>Checked how</dt>")
        body.append(f"<dd>{_text(_verification_words(outcomes))}</dd>")
    body.append("</dl>")

    body.append("<details>")
    body.append("<summary>Technical details</summary>")
    body.append('<div class="tech">')
    for label, key in (
        ("subject", "subject"),
        ("submission", "submission"),
        ("admission", "admission"),
    ):
        ref = entry.get(key)
        if isinstance(ref, Mapping):
            body.append(
                f"<p>{_text(label)} <code>{_text(ref.get('uri', ''))}</code> "
                f"<code>{_text(ref.get('cid', ''))}</code></p>"
            )
    body.append(f"<p>projected state <code>{_text(status)}</code></p>")
    for row in events:
        codes = ", ".join(_text(code) for code in _as_sequence(row.get("reasonCodes")))
        body.append(
            f"<p>{_text(row.get('kind', ''))} "
            f"<code>{_text(row.get('outcome', ''))}</code> "
            f"<time>{_text(row.get('firstReceivedAt', ''))}</time>"
            + (f" {codes}" if codes else "")
            + "</p>"
        )
    body.append("</div>")
    body.append("</details>")
    return _document(f"{display_name} — {_text(words.label)}", body)


def _as_sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return tuple(value)
    return ()


def _verification_words(outcomes: Sequence[str]) -> str:
    if "verified" in outcomes:
        return (
            "This community fetched the signed repository record itself and "
            "checked the signature, rather than trusting a relay's report."
        )
    if "failed" in outcomes:
        return "A repository proof for this did not check out."
    return "This has only been seen reported by a relay, not independently confirmed."


def _ref_text(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    return f"{_text(value.get('uri', ''))} {_text(value.get('cid', ''))}".strip()


_AUDIT_KIND_WORDS: Mapping[str, str] = {
    "submission": "suggested",
    "admission": "added",
    "removal": "removed",
    "profile": "community details changed",
    "subject_observation": "checked the original post",
    "quarantine": "could not be read",
    "ignored": "not one of this community's record types",
}


def render_audit_page(
    identity: Mapping[str, object],
    rows: Sequence[Mapping[str, object]],
    *,
    degraded_banner: str | None = None,
) -> str:
    """Render the escaped human-readable admission/removal audit log."""

    display_name = _text(identity.get("displayName", ""))
    slug = _text(identity.get("slug", ""))
    body = [
        f'<nav class="crumbs"><a href="/c/{slug}">&larr; {display_name}</a></nav>',
        f"<h1>{display_name} audit log</h1>",
        '<p class="community-description">Every decision and observation this '
        "community recorded, including items that are not shown on the main "
        "page.</p>",
        f'<p class="community-did">Community <code>{_text(identity.get("did", ""))}'
        "</code></p>",
    ]
    if degraded_banner is not None:
        body.append(f'<p class="degraded">{_text(degraded_banner)}</p>')
    body.append("<main>")
    if not rows:
        body.append('<p class="empty">Nothing has been recorded yet.</p>')
    for row in rows:
        kind = str(row.get("kind", ""))
        body.append("<article>")
        body.append(
            '<p class="audit-head">'
            f'<span class="kind">{_text(kind)}</span> '
            f'<span class="gloss">{_text(_AUDIT_KIND_WORDS.get(kind, kind))}</span> '
            f'<span class="outcome">{_text(row.get("outcome", ""))}</span> '
            f"<time>{_text(row.get('firstReceivedAt', ''))}</time>"
            "</p>"
        )
        record = _ref_text(row.get("record"))
        if record:
            body.append(f'<p class="audit-record">record <code>{record}</code></p>')
        subject = _ref_text(row.get("subject"))
        if subject:
            body.append(f'<p class="audit-subject">subject <code>{subject}</code></p>')
        actor = row.get("actor")
        if actor is not None:
            body.append(f'<p class="audit-actor">actor {_text(actor)}</p>')
        reason = row.get("reason")
        if reason is not None:
            body.append(f'<p class="audit-reason">reason {_text(reason)}</p>')
        codes = row.get("reasonCodes")
        if isinstance(codes, Sequence) and not isinstance(codes, str) and codes:
            rendered = ", ".join(_text(code) for code in codes)
            body.append(f'<p class="audit-codes">findings {rendered}</p>')
        body.append("</article>")
    body.append("</main>")
    return _document(f"{display_name} audit", body)


def render_error_page(status: int, code: str, *, slug: str | None = None) -> str:
    """Render a human explanation for a refused request, preserving status."""

    headline = {
        404: "Not found",
        400: "That link looks wrong",
        405: "Not supported",
        500: "Something went wrong",
    }.get(status, "This community can't be shown right now")
    body = [
        f"<h1>{_text(headline)}</h1>",
        f'<p class="gloss">{_text(describe_reason(code))}</p>',
        f'<p class="community-did">reason <code>{_text(code)}</code></p>',
    ]
    if slug:
        body.append(f'<p><a href="/c/{_text(slug)}">Back to the community</a></p>')
    return _document(headline, body)


__all__ = [
    "STYLESHEET",
    "STYLE_SHA256",
    "StateWords",
    "describe_reason",
    "describe_state",
    "render_audit_page",
    "render_community_page",
    "render_error_page",
    "render_item_page",
]
