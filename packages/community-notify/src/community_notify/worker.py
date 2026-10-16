"""Poll the read-only projection and post one fixed message per new event.

The worker holds no credential and writes only its own cursor file. Delivery
is best-effort and at-least-once: every new event is attempted each poll, a
failed POST is logged and retried on the next poll without holding back the
others, and the cursor records an event only after its message was accepted.
A crash between the room accepting a message and the cursor write re-sends
that one message once on the next poll; an event is never silently dropped.
The first poll ever baselines what already exists instead of announcing the
community's history, and does so only from a successful read: if the
projection cannot be reached, no cursor is written and the next start
baselines from a real read. The cursor is never an authority record.
"""

from __future__ import annotations

import http.client
import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

_POST_URI = re.compile(
    r"^at://(did:[a-z]+:[A-Za-z0-9._:%-]{1,512})/app\.bsky\.feed\.post/"
    r"([A-Za-z0-9._:~-]{1,512})$"
)
_ADMISSION_URI = re.compile(
    r"^at://(did:[a-z]+:[A-Za-z0-9._:%-]{1,512})/app\.phlogiston\.community\.admission/"
    r"([A-Za-z0-9._:~-]{1,512})$"
)
_SUBMISSION_URI = re.compile(
    r"^at://did:[a-z]+:[A-Za-z0-9._:%-]{1,512}/app\.phlogiston\.community\.submit/"
    r"[A-Za-z0-9._:~-]{1,512}$"
)
_CID = re.compile(r"^[A-Za-z0-9]{8,256}$")
_CURSOR_VERSION = 1


class ProjectionSource(Protocol):
    def get(self, path: str) -> Mapping[str, object]: ...


class WebhookSender(Protocol):
    def send(self, payload: Mapping[str, str]) -> None: ...


@dataclass(frozen=True, slots=True)
class Event:
    kind: str  # "pending" | "admitted"
    uri: str
    cid: str
    link: str
    extra_link: str | None = None

    @property
    def key(self) -> str:
        return f"{self.kind} {self.uri} {self.cid}"


class Cursor:
    """Durable set of already-delivered event keys in one local JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.exists = path.exists()
        self.sent: set[str] = set()
        if self.exists:
            document = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(document, dict)
                or document.get("version") != _CURSOR_VERSION
                or not isinstance(document.get("sent"), list)
                or not all(isinstance(item, str) for item in document["sent"])
            ):
                raise ValueError("notifier cursor file is malformed")
            self.sent = set(document["sent"])

    def __contains__(self, key: str) -> bool:
        return key in self.sent

    def record(self, keys: list[str]) -> None:
        self.sent.update(keys)
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            {"version": _CURSOR_VERSION, "sent": sorted(self.sent)},
            separators=(",", ":"),
        ).encode()
        temporary = self.path.with_name(self.path.name + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, self.path)
        self.exists = True


class NotifyWorker:
    def __init__(
        self,
        *,
        community_did: str,
        community_name: str,
        public_base_url: str,
        payload_key: str,
        source: ProjectionSource,
        sender: WebhookSender,
        cursor: Cursor,
        log: Callable[[str], None],
    ) -> None:
        self.community_did = community_did
        self.community_name = community_name
        self.public_base_url = public_base_url.rstrip("/")
        self.payload_key = payload_key
        self.source = source
        self.sender = sender
        self.cursor = cursor
        self.log = log

    def run_once(self) -> dict[str, int]:
        counts = {"observed": 0, "sent": 0, "failed": 0, "baselined": 0}
        try:
            events = self._events()
        except (OSError, ValueError) as exc:
            self.log(f"projection unavailable: {type(exc).__name__}")
            counts["failed"] = 1
            return counts
        counts["observed"] = len(events)
        if not self.cursor.exists:
            # First start: record what already exists instead of announcing
            # the community's whole history into the room.
            self.cursor.record([event.key for event in events])
            counts["baselined"] = len(events)
            self.log(f"baselined {len(events)} existing events")
            return counts
        for event in events:
            if event.key in self.cursor:
                continue
            try:
                self.sender.send({self.payload_key: self.message(event)})
            except (OSError, http.client.HTTPException) as exc:
                # Includes a response that could not be read after the POST
                # was sent: not confirmed means not delivered.
                self.log(
                    f"webhook delivery failed: {type(exc).__name__}: {exc};"
                    " will retry next poll"
                )
                counts["failed"] += 1
                continue
            self.cursor.record([event.key])
            counts["sent"] += 1
        return counts

    def message(self, event: Event) -> str:
        if event.kind == "pending":
            line = "A new post is waiting for the moderator."
        else:
            line = "A new discussion was admitted."
        lines = [f"[{self.community_name}] {event.kind}: {line}", event.link]
        if event.extra_link is not None:
            lines.append(f"Public post: {event.extra_link}")
        return "\n".join(lines)

    def _events(self) -> list[Event]:
        base = f"/api/v0/communities/{quote(self.community_did, safe=':')}"
        queue = self._document(f"{base}/moderation-queue", "submissions")
        discussions = self._document(f"{base}/discussions", "discussions")
        events = [
            event
            for event in (self._pending(item) for item in queue)
            if event is not None
        ]
        # The discussions list is newest first; announce oldest first.
        events.extend(
            event
            for event in (self._admitted(item) for item in reversed(discussions))
            if event is not None
        )
        return events

    def _document(self, path: str, field: str) -> list[object]:
        document = self.source.get(path)
        if document.get("communityDid") != self.community_did:
            raise ValueError("projection answered for a different community")
        items = document.get(field)
        if not isinstance(items, list):
            raise ValueError(f"projection {field} is not a list")
        return items

    def _pending(self, item: object) -> Event | None:
        submission = _ref(item, "submission")
        if submission is None or not _SUBMISSION_URI.fullmatch(submission[0]):
            return None
        subject = _ref(item, "subject")
        public_post = None
        if subject is not None:
            match = _POST_URI.fullmatch(subject[0])
            if match is not None:
                public_post = f"https://bsky.app/profile/{match[1]}/post/{match[2]}"
        return Event(
            "pending",
            submission[0],
            submission[1],
            f"{self.public_base_url}/",
            public_post,
        )

    def _admitted(self, item: object) -> Event | None:
        admission = _ref(item, "discussion")
        if admission is None:
            return None
        match = _ADMISSION_URI.fullmatch(admission[0])
        if match is None or match[1] != self.community_did:
            return None
        link = f"{self.public_base_url}/d/{quote(match[2], safe='')}"
        return Event("admitted", admission[0], admission[1], link)


def _ref(item: object, field: str) -> tuple[str, str] | None:
    if not isinstance(item, dict):
        return None
    value = item.get(field)
    if not isinstance(value, dict):
        return None
    uri, cid = value.get("uri"), value.get("cid")
    if not isinstance(uri, str) or not isinstance(cid, str) or not _CID.fullmatch(cid):
        return None
    return uri, cid
