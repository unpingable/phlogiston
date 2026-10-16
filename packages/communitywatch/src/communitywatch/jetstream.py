"""Jetstream v2 filtered subscription adapter (transport/discovery only).

Jetstream v2 commit events carry record digests only — no commit CID, no
signed bytes — and deletes carry no CID.  Every event this source yields is
therefore an unverified claim with ``trust_mode=verify_repo`` and
``verification_outcome=unverified``; only the verifying wrapper
(``verifying.VerifyingEventSource``) may upgrade a claim after independent
repository proof verification (OQ-2, answer A).

Wire shape (verified live 2026-08-14 against the public v2 instances and
https://bsky.network/docs/jetstream/): the tail path is
``/xrpc/network.bsky.jetstream.subscribeEvents`` with repeated
``collections=<NSID>`` / ``dids=<did>`` query params plus ``kinds=commit`` / ``kinds=identity`` / ``kinds=account`` / ``kinds=sync``
(a collections filter constrains commit events only).  Every message is
``{"$type": "message", "payload": {...}}``; a commit payload has ``$type``
``network.bsky.jetstream.subscribeEvents#commit`` with ``did``, ``seq``
(monotonic integer cursor, inclusive on resume, at-least-once), ``time``
(RFC3339), ``operation``, ``collection``, ``rkey``, ``rev``, and — for
create/update only — ``cid`` and decoded ``record``.  ``#identity``,
``#account``, and ``#sync`` payloads carry no repository records and are
skipped, as are unknown payload types.  Events outside the pinned
collections/DIDs are relay misbehavior and are skipped; anything that is
not a well-typed v2 message (including the frozen v1 flat ``kind``/``time_us``
wire) becomes a raw-byte delivery so the store quarantines it with its
cursor instead of dropping or silently accepting it.
"""

from __future__ import annotations

import hashlib
import json
import math
import socket
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from urllib.parse import urlencode, urlsplit

from community_model import (
    COMMUNITY_COLLECTIONS,
    EventBatch,
    IncomingDelivery,
    ValidationError,
)
from community_model.identifiers import (
    parse_rfc3339,
    validate_did,
    validate_nsid,
    validate_rkey,
    validate_tid,
)

from .websocket import iter_messages, ws_connect

TRANSPORT_METHOD = "jetstream-v2-transport"
TRANSPORT_VERSION = "1"
RESYNC_CURSOR_MARK = "%resync%"
SUBSCRIBE_PATH = "/xrpc/network.bsky.jetstream.subscribeEvents"
COMMIT_PAYLOAD_TYPE = "network.bsky.jetstream.subscribeEvents#commit"

ConnectCallable = Callable[..., socket.socket]


class _DeadlineSocket:
    """Apply the current phase deadline to partial reads and control writes."""

    def __init__(self, sock, deadline: float, clock: Callable[[], float]):
        self.sock = sock
        self.deadline = deadline
        self.clock = clock

    def _remaining(self):
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise TimeoutError("Jetstream batch deadline")
        self.sock.settimeout(remaining)

    def recv(self, size):
        self._remaining()
        return self.sock.recv(size)

    def sendall(self, data):
        self._remaining()
        return self.sock.sendall(data)

    def __getattr__(self, name):
        return getattr(self.sock, name)


def base_sequence(cursor: str) -> int:
    """Extract the numeric Jetstream sequence from any owned cursor form."""

    base = cursor.split("%", 1)[0]
    try:
        sequence = int(base)
    except ValueError as exc:
        raise ValidationError("schema_invalid", "unknown Jetstream cursor") from exc
    if sequence < 0 or str(sequence) != base:
        raise ValidationError("schema_invalid", "unknown Jetstream cursor")
    return sequence


def resume_sequence(cursor: str | None) -> int | None:
    """Decode a relay position without treating quarantine identity as progress.

    An initial unsequenced quarantine has no relay position. A later one owns
    the last numeric position, separately from its deterministic raw-byte ID.
    """
    if cursor is None:
        return None
    if cursor.startswith("unsequenced-") and "%resume%" in cursor:
        identity, position = cursor.split("%resume%", 1)
        digest = identity.removeprefix("unsequenced-")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValidationError("schema_invalid", "unknown quarantine cursor")
        return None if position == "none" else base_sequence(position)
    return base_sequence(cursor)


@dataclass(slots=True)
class JetstreamEventSource:
    """Bounded synchronous batches from one filtered Jetstream v2 endpoint.

    ``wanted_dids`` pins repository DIDs when the operator knows them; the V0
    default is empty because submission authors are not known a priori.
    The first complete data frame has a 90-second wait bound; after it,
    the batch drains for at most 15 seconds by default. Control frames
    and partial reads cannot extend either deadline. These bounds do not
    guarantee progress through arbitrary sparse upstream history.
    """

    base_url: str
    wanted_collections: tuple[str, ...] = COMMUNITY_COLLECTIONS
    wanted_dids: tuple[str, ...] = ()
    source_name: str = "jetstream"
    max_batch: int = 100
    receive_timeout: float = 15.0
    connect: ConnectCallable = ws_connect
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    clock: Callable[[], float] = time.monotonic
    first_frame_timeout: float = 90.0

    def __post_init__(self) -> None:
        parts = urlsplit(self.base_url)
        if parts.scheme not in {"ws", "wss"} or not parts.hostname:
            raise ValidationError(
                "schema_invalid", "event source URL must use ws:// or wss://"
            )
        for collection in self.wanted_collections:
            validate_nsid(collection)
        for did in self.wanted_dids:
            validate_did(did)
        for timeout in (self.receive_timeout, self.first_frame_timeout):
            if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
                raise ValidationError(
                    "schema_invalid", "timeout must be finite and positive"
                )
        if isinstance(self.max_batch, bool) or not 1 <= self.max_batch <= 10_000:
            raise ValidationError("schema_invalid", "max_batch out of bounds")

    def subscribe_url(self, after_cursor: str | None) -> str:
        params: list[tuple[str, str]] = [
            ("collections", collection) for collection in self.wanted_collections
        ]
        params += [("dids", did) for did in self.wanted_dids]
        # A collections filter constrains commit events only; ask for commits
        # explicitly. Non-commit events expose ordered transport progress
        # through sparse commit history; they never become repository records.
        params += [
            ("kinds", kind) for kind in ("commit", "identity", "account", "sync")
        ]
        position = resume_sequence(after_cursor)
        if position is not None:
            # The stored cursor commits only after durable ingest, so the
            # inclusive-resume stream may safely restart one past it; replay
            # and redelivery stay idempotent at the store.
            params.append(("cursor", str(position + 1)))
        base = self.base_url.rstrip("/")
        return f"{base}{SUBSCRIBE_PATH}?{urlencode(params)}"

    def read(self, after_cursor: str | None) -> EventBatch[IncomingDelivery]:
        # Sparse replay may require upstream scanning before any matching frame.
        # Give that phase its own bound, then drain for receive_timeout only.
        deadline = self.clock() + self.first_frame_timeout
        sock = self.connect(
            self.subscribe_url(after_cursor), timeout=self.receive_timeout
        )
        deliveries: list[IncomingDelivery] = []
        skipped_checkpoint: IncomingDelivery | None = None
        position = resume_sequence(after_cursor)
        progress_sequence = -1 if position is None else position
        try:
            bounded_socket = _DeadlineSocket(sock, deadline, self.clock)
            messages: Iterator[bytes] = iter_messages(bounded_socket)
            messages_read = 0
            while (
                len(deliveries) < self.max_batch and messages_read < self.max_batch * 4
            ):
                try:
                    if self.clock() >= deadline:
                        break
                    message = next(messages)
                except (StopIteration, socket.timeout, TimeoutError):
                    break
                if messages_read == 0:
                    deadline = self.clock() + self.receive_timeout
                    bounded_socket.deadline = deadline
                messages_read += 1
                delivery = self._translate(message)
                if delivery is not None:
                    # A checkpoint represents only the trailing filtered prefix.
                    # Any later delivery (including unsequenced quarantine)
                    # supersedes an earlier filtered checkpoint in this batch.
                    skipped_checkpoint = None
                    if delivery.cursor.startswith("unsequenced-"):
                        raw_identity = hashlib.sha256(message).hexdigest()
                        resume = (
                            "none" if progress_sequence < 0 else str(progress_sequence)
                        )
                        delivery = replace(
                            delivery,
                            cursor=f"unsequenced-{raw_identity}%resume%{resume}",
                        )
                    deliveries.append(delivery)
                    if delivery.cursor.isdigit():
                        progress_sequence = max(progress_sequence, int(delivery.cursor))
                else:
                    # A safely filtered v2 sequence is transport progress only.
                    # Preserve an inert raw-byte quarantine receipt so runner
                    # ingestion durably checkpoints it, including across restart.
                    event = json.loads(message)
                    payload = event.get("payload", {})
                    sequence = payload.get("seq")
                    if (
                        isinstance(sequence, int)
                        and not isinstance(sequence, bool)
                        and sequence >= 0
                        and sequence > progress_sequence
                    ):
                        progress_sequence = sequence
                        skipped_checkpoint = IncomingDelivery(
                            source=self.source_name,
                            cursor=str(sequence),
                            source_event_time=None,
                            received_at=self.now(),
                            raw_envelope=message,
                            trust_mode="verify_repo",
                            verification_outcome="unverified",
                            verification_method="jetstream-v2-filtered-progress",
                            verifier_version=TRANSPORT_VERSION,
                        )
        finally:
            try:
                sock.close()
            except OSError:
                pass
        if skipped_checkpoint is not None:
            deliveries.append(skipped_checkpoint)
        next_cursor = deliveries[-1].cursor if deliveries else after_cursor
        return EventBatch(items=tuple(deliveries), next_cursor=next_cursor)

    def _translate(self, message: bytes) -> IncomingDelivery | None:
        """Map one v2 wire message to a claim delivery, or skip it."""

        received_at = self.now()
        try:
            event = json.loads(message.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            event = None
        payload: object = None
        if isinstance(event, dict):
            if event.get("$type") == "message" and isinstance(
                event.get("payload"), dict
            ):
                payload = event["payload"]
            else:
                # Not a v2 message envelope (including the frozen v1 flat
                # kind/commit wire): quarantine, never silently accept.
                payload = None
        if isinstance(payload, Mapping):
            payload_type = payload.get("$type")
            if isinstance(payload_type, str) and payload_type != COMMIT_PAYLOAD_TYPE:
                return None  # identity/account/sync/unknown payloads: no records
            if payload_type == COMMIT_PAYLOAD_TYPE:
                sequence = payload.get("seq")
                well_typed_sequence = isinstance(sequence, int) and not isinstance(
                    sequence, bool
                )
                if well_typed_sequence:
                    claim = self._claim_envelope(payload)
                    if claim is None:
                        return None  # outside the pinned collections/DIDs
                    if claim is not _QUARANTINE:
                        return IncomingDelivery(
                            source=self.source_name,
                            cursor=str(sequence),
                            source_event_time=_source_time(payload.get("time")),
                            received_at=received_at,
                            raw_envelope=claim,
                            trust_mode="verify_repo",
                            verification_outcome="unverified",
                            verification_method=TRANSPORT_METHOD,
                            verifier_version=TRANSPORT_VERSION,
                        )
        # Undecodable or wrongly typed input is still checkpointed: the store
        # quarantines these raw bytes with their cursor, never dropping them.
        cursor = None
        if (
            isinstance(payload, Mapping)
            and isinstance(payload.get("seq"), int)
            and not isinstance(payload.get("seq"), bool)
            and payload["seq"] >= 0
        ):
            cursor = str(payload["seq"])
        return IncomingDelivery(
            source=self.source_name,
            cursor=cursor or f"unsequenced-{received_at.isoformat()}",
            source_event_time=None,
            received_at=received_at,
            raw_envelope=message,
            trust_mode="verify_repo",
            verification_outcome="unverified",
            verification_method=TRANSPORT_METHOD,
            verifier_version=TRANSPORT_VERSION,
        )

    def _claim_envelope(self, payload: Mapping[str, object]) -> object:
        """Translate a commit payload to observer-envelope claims, if in scope.

        Returns ``None`` for out-of-scope events, the ``_QUARANTINE``
        sentinel for wrongly typed in-scope events (the caller retains the
        raw wire bytes), and the claim mapping otherwise.
        """

        did = payload.get("did")
        collection = payload.get("collection")
        if not isinstance(did, str) or not isinstance(collection, str):
            return _QUARANTINE
        if collection not in self.wanted_collections:
            return None
        if self.wanted_dids and did not in self.wanted_dids:
            return None
        rev = payload.get("rev")
        operation = payload.get("operation")
        rkey = payload.get("rkey")
        if not all(isinstance(value, str) for value in (rev, operation, rkey)):
            return _QUARANTINE
        assert isinstance(rev, str) and isinstance(operation, str)
        assert isinstance(rkey, str)
        try:
            validate_did(did)
            validate_nsid(collection)
            validate_rkey(rkey)
            validate_tid(rev)
        except ValidationError:
            return _QUARANTINE
        if operation not in {"create", "update", "delete"}:
            return _QUARANTINE
        claim: dict[str, object] = {
            "repo": did,
            "rev": rev,
            "operation": operation,
            "collection": collection,
            "rkey": rkey,
        }
        cid = payload.get("cid")
        if isinstance(cid, str):
            claim["cid"] = cid
        record = payload.get("record")
        if isinstance(record, Mapping):
            claim["record"] = dict(record)
        return claim


_QUARANTINE: object = object()


def _source_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return parse_rfc3339(value)
    except ValidationError:
        return None


__all__ = [
    "COMMIT_PAYLOAD_TYPE",
    "JetstreamEventSource",
    "RESYNC_CURSOR_MARK",
    "SUBSCRIBE_PATH",
    "TRANSPORT_METHOD",
    "TRANSPORT_VERSION",
    "base_sequence",
]
