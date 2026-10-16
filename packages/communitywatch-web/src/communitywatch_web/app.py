"""Transport-independent request handling for the canonical V0 AppView.

The web process serves ``GET`` and ``HEAD`` only, over the committed SQLite
projection.  It performs no migration, no write, and no network resolution in
a request.  All record/profile/reason text is escaped by the communitywatch
render layer.

Error bodies are stable JSON on the machine surfaces (``/health`` and
``/api/...``) and an escaped HTML explanation on the browser routes, so a
person who opens a community link on a phone is told what happened instead of
being handed a JSON blob.  Both forms carry the same status and reason code,
interpolate no part of the request, and never contain filesystem paths, raw
exception text, configuration, or credentials.  A refusal is never softened
into a successful empty page: an incomplete, incompatible, or stale
projection still answers 503.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, unquote

from community_model import (
    CursorError,
    ValidationError,
    canonical_json_bytes,
)
from community_model.identifiers import validate_did
from community_model.immutable import deep_thaw
from communitywatch import (
    STYLE_SHA256,
    DiscussionQuery,
    ProjectionQuery,
    ProjectionUnavailableError,
    UnknownCommunityError,
    UnknownEntryError,
    render_audit_page,
    render_community_page,
    render_error_page,
    render_item_page,
)
from communitywatch.storage import PROJECTION_VERSION, SCHEMA_VERSION

HTML_CONTENT_TYPE = "text/html; charset=utf-8"
JSON_CONTENT_TYPE = "application/json; charset=utf-8"

# Applied to every response, including errors, by the HTTP binding.  The one
# inline stylesheet is admitted by SHA-256 hash, never by 'unsafe-inline', so
# the page can be laid out for a phone without loosening the policy: any other
# inline style or script remains blocked.
SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    (
        "Content-Security-Policy",
        "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
        f"style-src '{STYLE_SHA256}'",
    ),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
)

# Applied to every response by the HTTP binding, alongside SECURITY_HEADERS.
#
# Every route this process serves is a public, unauthenticated, read-only
# representation of the committed projection, so the allowed origin is `*`.
# The representations are already public; restricting browser origins would
# withhold nothing from a non-browser client and would create configuration
# without creating an authority boundary.
#
# This is not an authorization mechanism and confers no standing.  It is a
# statement that these particular bytes are already public.  `Allow-Credentials`
# is deliberately absent: there is no cookie or session to send, and with
# `Allow-Origin: *` a browser would refuse the pair anyway.
#
# Bounded to this surface on purpose.  A route on this server that mutates
# anything, or any future write/admin surface, does not inherit this policy and
# must decide its own; adding one here means revisiting this block first.
CORS_HEADERS: tuple[tuple[str, str], ...] = (("Access-Control-Allow-Origin", "*"),)

# Sent only on the preflight response.
PREFLIGHT_HEADERS: tuple[tuple[str, str], ...] = (
    ("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS"),
    ("Access-Control-Max-Age", "86400"),
)

READ_METHODS = ("GET", "HEAD")
ALLOWED_METHODS = "GET, HEAD, OPTIONS"

STALE_AUDIT_BANNER = (
    "This audit log shows the last complete projection and may lag the "
    "latest observations."
)


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    content_type: str
    body: bytes
    extra_headers: tuple[tuple[str, str], ...] = ()


class _HttpError(Exception):
    """An expected request failure with a stable wire code and safe text."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _wire_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_stored_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


@dataclass(slots=True)
class WebApp:
    """Routes requests onto the committed-projection query/render layer."""

    query: ProjectionQuery
    community_did: str
    slug: str
    page_size: int = 50
    stale_threshold_seconds: int = 180
    now: Callable[[], datetime] = _utc_now

    def handle(self, method: str, target: str) -> Response:
        """Answer one request; every failure maps to a safe error response.

        Browser-facing routes get an escaped HTML explanation carrying the
        same status and reason code that the JSON surfaces carry.  A refusal
        is never downgraded into a successful empty page: a stale, incomplete,
        or incompatible projection still answers 503.
        """

        html_route = self._is_html_route(target)
        try:
            return self._dispatch(method.upper(), target)
        except _HttpError as exc:
            return self._error(exc.status, exc.code, exc.message, html_route)
        except UnknownEntryError:
            return self._error(404, "not_found", "unknown entry", html_route)
        except UnknownCommunityError:
            return self._error(
                404, "unknown_community", "unknown community", html_route
            )
        except CursorError:
            return self._error(400, "bad_request", "malformed cursor", html_route)
        except ValidationError as exc:
            # Validation messages are stable static text, never user data.
            return self._error(400, "bad_request", exc.issue.message, html_route)
        except ProjectionUnavailableError as exc:
            return self._error(
                503,
                exc.reason_code,
                f"projection unavailable ({exc.reason_code})",
                html_route,
                json_code="projection_unavailable",
            )
        except (sqlite3.Error, OSError):
            return self._error(
                503,
                "projection_unavailable",
                "observer data unavailable",
                html_route,
            )
        except Exception:  # deliberate fail-closed catch-all
            return self._error(500, "internal_error", "internal error", html_route)

    @staticmethod
    def _is_html_route(target: str) -> bool:
        """Browser routes render HTML errors; machine routes stay JSON."""

        path = target.partition("?")[0]
        machine = path == "/health" or path == "/api" or path.startswith("/api/")
        return not machine

    def _dispatch(self, method: str, target: str) -> Response:
        if method == "OPTIONS":
            return self._preflight(target)
        if method not in READ_METHODS:
            raise _HttpError(
                405,
                "method_not_allowed",
                "only GET, HEAD, and OPTIONS are supported",
            )
        path, _, query_string = target.partition("?")
        segments = self._decode_path(path)
        params = parse_qs(query_string, keep_blank_values=True)
        if segments == ["health"]:
            return self._health()
        if len(segments) == 2 and segments[0] == "c":
            return self._community_page(segments[1])
        if len(segments) == 3 and segments[0] == "c" and segments[2] == "audit":
            return self._audit_page(segments[1])
        if len(segments) == 4 and segments[0] == "c" and segments[2] == "i":
            return self._item_page(segments[1], segments[3])
        if len(segments) == 5 and segments[:3] == ["api", "v0", "communities"]:
            if segments[4] == "posts":
                return self._posts_json(segments[3], params)
            if segments[4] == "audit":
                return self._audit_json(segments[3], params)
            if segments[4] == "discussions":
                return self._discussions_json(segments[3])
            if segments[4] == "reply-candidates":
                return self._reply_candidates_json(segments[3])
            if segments[4] == "moderation-queue":
                return self._moderation_queue_json(segments[3], params)
            if segments[4] == "members":
                return self._members_json(segments[3])
        if len(segments) == 6 and segments[:3] == ["api", "v0", "communities"]:
            if segments[4] == "discussions":
                return self._discussion_json(segments[3], segments[5])
            if segments[4] == "participants":
                return self._participant_json(segments[3], segments[5])
        raise _HttpError(404, "not_found", "unknown route")

    def _preflight(self, target: str) -> Response:
        """Answer a browser preflight for the public read routes.

        Advertises the read methods and nothing else, so a preflight for a
        mutating method fails here rather than at the refused request.  The
        path is still decoded, so a malformed target is refused exactly as it
        would be on GET.  No request header is read, and none is reflected:
        these routes need no custom request header, so a preflight that asks
        for one is correctly not granted.
        """

        self._decode_path(target.partition("?")[0])
        return Response(204, JSON_CONTENT_TYPE, b"", PREFLIGHT_HEADERS)

    def _decode_path(self, path: str) -> list[str]:
        if not path.startswith("/"):
            raise _HttpError(400, "bad_request", "malformed path")
        segments: list[str] = []
        for raw in path[1:].split("/"):
            segment = unquote(raw)
            # Percent-encoded slashes, backslashes, and control characters
            # (including CR/LF) may never reach routing or a response.
            if (
                any(ord(char) < 0x20 or ord(char) == 0x7F for char in segment)
                or "/" in segment
                or "\\" in segment
            ):
                raise _HttpError(400, "bad_request", "malformed path")
            segments.append(segment)
        return segments

    def _check_slug(self, slug: str) -> None:
        if slug != self.slug:
            raise _HttpError(404, "unknown_community", "unknown community")

    def _check_did(self, community_did: str) -> str:
        try:
            validate_did(community_did)
        except ValidationError:
            raise _HttpError(404, "unknown_community", "unknown community") from None
        if community_did != self.community_did:
            raise _HttpError(404, "unknown_community", "unknown community")
        return community_did

    def _limit(self, params: Mapping[str, list[str]]) -> int:
        raw = params.get("limit")
        if raw is None:
            return self.page_size
        if len(raw) != 1 or not raw[0].isdigit():
            raise _HttpError(400, "bad_request", "malformed limit")
        # Range bounds are enforced by the query layer (1..max_limit).
        return int(raw[0])

    def _cursor(self, params: Mapping[str, list[str]]) -> str | None:
        raw = params.get("cursor")
        if raw is None:
            return None
        if len(raw) != 1:
            raise _HttpError(400, "bad_request", "malformed cursor")
        return raw[0]

    def _json(self, status: int, document: Mapping[str, object]) -> Response:
        return Response(status, JSON_CONTENT_TYPE, canonical_json_bytes(document))

    def _error(
        self,
        status: int,
        code: str,
        message: str,
        html_route: bool = False,
        *,
        json_code: str | None = None,
    ) -> Response:
        extra = (("Allow", ALLOWED_METHODS),) if status == 405 else ()
        if html_route:
            page = render_error_page(status, code, slug=self.slug)
            return Response(status, HTML_CONTENT_TYPE, page.encode("utf-8"), extra)
        return Response(
            status,
            JSON_CONTENT_TYPE,
            canonical_json_bytes({"error": json_code or code, "message": message}),
            extra,
        )

    def _community_page(self, slug: str) -> Response:
        self._check_slug(slug)
        page = self.query.list_visible(self.community_did, self.page_size, None)
        identity = self.query.community_identity(self.community_did)
        has_profile = self.query.has_profile_record(self.community_did)
        hidden = 0 if page.items else self.query.hidden_entry_count(self.community_did)
        html = render_community_page(
            identity, page.items, has_profile=has_profile, hidden_count=hidden
        )
        return Response(200, HTML_CONTENT_TYPE, html.encode("utf-8"))

    def _item_page(self, slug: str, admission_rkey: str) -> Response:
        self._check_slug(slug)
        detail = self.query.entry_detail(self.community_did, admission_rkey)
        identity = self.query.community_identity(self.community_did)
        html = render_item_page(identity, detail.entry, detail.status, detail.events)
        return Response(200, HTML_CONTENT_TYPE, html.encode("utf-8"))

    def _audit_page(self, slug: str) -> Response:
        self._check_slug(slug)
        page = self.query.list_audit(self.community_did, self.page_size, None)
        identity = self.query.community_identity(self.community_did)
        state = self.query.projection_state()
        banner = None if state.fresh else STALE_AUDIT_BANNER
        html = render_audit_page(identity, page.items, degraded_banner=banner)
        return Response(200, HTML_CONTENT_TYPE, html.encode("utf-8"))

    def _posts_json(
        self, community_did: str, params: Mapping[str, list[str]]
    ) -> Response:
        did = self._check_did(community_did)
        page = self.query.list_visible(did, self._limit(params), self._cursor(params))
        identity = self.query.community_identity(did)
        return self._json(
            200,
            {
                "community": identity,
                "entries": deep_thaw(list(page.items)),
                "cursor": page.cursor,
                "projectionVersion": PROJECTION_VERSION,
                "generatedAt": _wire_time(self.now()),
            },
        )

    def _discussions_json(self, community_did: str) -> Response:
        did = self._check_did(community_did)
        result = DiscussionQuery(self.query).list_discussions(did)
        return self._json(
            200,
            {
                "communityDid": did,
                "discussions": deep_thaw(list(result.items)),
                "cursor": result.cursor,
                "snapshot": result.snapshot.as_dict(),
            },
        )

    def _discussion_json(self, community_did: str, rkey: str) -> Response:
        did = self._check_did(community_did)
        result = DiscussionQuery(self.query).discussion(did, rkey)
        return self._json(
            200,
            {
                "communityDid": did,
                "discussion": deep_thaw(result.discussion),
                "replies": deep_thaw(list(result.replies)),
                "activity": deep_thaw(list(result.activity)),
                "snapshot": result.snapshot.as_dict(),
            },
        )

    def _participant_json(self, community_did: str, participant_did: str) -> Response:
        did = self._check_did(community_did)
        result = DiscussionQuery(self.query).participant_activity(did, participant_did)
        return self._json(
            200,
            {
                "communityDid": did,
                "participantDid": participant_did,
                "discussions": deep_thaw(list(result.discussions)),
                "activity": deep_thaw(list(result.activity)),
                "snapshot": result.snapshot.as_dict(),
            },
        )

    def _reply_candidates_json(self, community_did: str) -> Response:
        did = self._check_did(community_did)
        result = DiscussionQuery(self.query).reply_candidates(did)
        return self._json(
            200,
            {
                "communityDid": did,
                "candidates": deep_thaw(list(result.candidates)),
                "snapshot": result.snapshot.as_dict(),
            },
        )

    def _moderation_queue_json(
        self, community_did: str, params: Mapping[str, list[str]]
    ) -> Response:
        did = self._check_did(community_did)
        authors = params.get("authorDid")
        if authors is not None and len(authors) != 1:
            raise _HttpError(400, "bad_request", "malformed authorDid")
        result = DiscussionQuery(self.query).moderation_queue(
            did,
            limit=25 if "limit" not in params else self._limit(params),
            cursor=self._cursor(params),
            author_did=None if authors is None else authors[0],
        )
        return self._json(
            200,
            {
                "communityDid": did,
                "submissions": deep_thaw(list(result.submissions)),
                "nextCursor": result.cursor,
                "coverage": result.coverage,
                "snapshot": result.snapshot.as_dict(),
            },
        )

    def _members_json(self, community_did: str) -> Response:
        did = self._check_did(community_did)
        members = self.query.list_members(did)
        state = self.query.projection_state()
        return self._json(
            200,
            {
                "communityDid": did,
                "members": deep_thaw(list(members)),
                "projection": {
                    "generation": state.generation,
                    "version": PROJECTION_VERSION,
                    "fresh": state.fresh,
                },
                "generatedAt": _wire_time(self.now()),
            },
        )

    def _audit_json(
        self, community_did: str, params: Mapping[str, list[str]]
    ) -> Response:
        did = self._check_did(community_did)
        page = self.query.list_audit(did, self._limit(params), self._cursor(params))
        identity = self.query.community_identity(did)
        state = self.query.projection_state()
        return self._json(
            200,
            {
                "community": identity,
                "communityDid": did,
                "events": deep_thaw(list(page.items)),
                "cursor": page.cursor,
                "projection": {
                    "generation": state.generation,
                    "version": PROJECTION_VERSION,
                    "fresh": state.fresh,
                },
                "generatedAt": _wire_time(self.now()),
            },
        )

    def _health(self) -> Response:
        try:
            state = self.query.projection_state()
        except (sqlite3.Error, OSError):
            state = None
        if state is None:
            return self._json(
                503,
                {
                    "status": "unavailable",
                    "schemaVersion": SCHEMA_VERSION,
                    "projectionVersion": PROJECTION_VERSION,
                    "activeGeneration": None,
                    "projectionStatus": "missing",
                    "highWaterMatches": False,
                    "lastIngestAt": None,
                    "lastResolveAt": None,
                    "sources": [],
                    "generatedAt": _wire_time(self.now()),
                    "reasonCodes": ["projection_missing"],
                },
            )
        reason_codes = list(state.reason_codes)
        now = self.now()
        if state.fresh and self.stale_threshold_seconds > 0:
            threshold = timedelta(seconds=self.stale_threshold_seconds)
            heartbeat_staleness = (
                (state.last_ingest_at, "ingest_stale"),
                (state.last_resolve_at, "resolve_stale"),
            )
            for heartbeat, code in heartbeat_staleness:
                if (
                    heartbeat is not None
                    and now - _parse_stored_time(heartbeat) > threshold
                    and code not in reason_codes
                ):
                    reason_codes.append(code)
        if state.status != "complete" or not state.compatible:
            status = "unavailable"
        elif reason_codes:
            status = "stale"
        else:
            status = "ok"
        document = {
            "status": status,
            "schemaVersion": SCHEMA_VERSION,
            "projectionVersion": PROJECTION_VERSION,
            "activeGeneration": state.generation,
            "projectionStatus": state.status,
            "highWaterMatches": state.high_water_matches,
            "lastIngestAt": state.last_ingest_at,
            "lastResolveAt": state.last_resolve_at,
            "sources": [
                {
                    "name": source.name,
                    "committedCursor": source.committed_cursor,
                    "projectedCursor": source.projected_cursor,
                    "matches": source.matches,
                }
                for source in state.sources
            ],
            "generatedAt": _wire_time(now),
            "reasonCodes": reason_codes,
        }
        return self._json(200 if status == "ok" else 503, document)
