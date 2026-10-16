from __future__ import annotations

import http.client
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from community_notify.adapters import WebhookError
from community_notify.worker import Cursor, NotifyWorker

COMMUNITY = "did:plc:exampleparticipantabcdef"
CID_A = "bafyreidfayvfuwqa7qlnopdjiqrxzs6blmoeu4rujcjtnci5beludirz2a"
CID_B = "bafyreigoxt64qghytzkr6ik7qvtzc7lyytiq5xbbrokbxjows2wp7vmo6q"
QUEUE = f"/api/v0/communities/{COMMUNITY}/moderation-queue"
DISCUSSIONS = f"/api/v0/communities/{COMMUNITY}/discussions"
BASE = "https://community.example.test"


def pending(rkey: str, cid: str = CID_A) -> dict[str, object]:
    return {
        "submission": {
            "uri": f"at://did:plc:alice/app.phlogiston.community.submit/{rkey}",
            "cid": cid,
        },
        "subject": {
            "uri": f"at://did:plc:alice/app.bsky.feed.post/{rkey}",
            "cid": CID_B,
        },
        "authorDid": "did:plc:alice",
        "observerSequence": 1,
    }


def admitted(rkey: str, cid: str = CID_A) -> dict[str, object]:
    return {
        "discussion": {
            "uri": f"at://{COMMUNITY}/app.phlogiston.community.admission/{rkey}",
            "cid": cid,
        },
        "root": {"uri": f"at://did:plc:alice/app.bsky.feed.post/{rkey}", "cid": CID_B},
        "post": {"text": "never forwarded <b>text</b>"},
        "authorDid": "did:plc:alice",
    }


class Projection:
    def __init__(self) -> None:
        self.queue: list[object] = []
        self.discussions: list[object] = []
        self.down = False
        self.paths: list[str] = []

    def get(self, path: str) -> Mapping[str, object]:
        self.paths.append(path)
        if self.down:
            raise OSError("projection acquisition failed")
        if path == QUEUE:
            return {
                "communityDid": COMMUNITY,
                "submissions": self.queue,
                "snapshot": {},
            }
        if path == DISCUSSIONS:
            return {
                "communityDid": COMMUNITY,
                "discussions": self.discussions,
                "cursor": None,
                "snapshot": {},
            }
        raise AssertionError(path)


class Sender:
    def __init__(self) -> None:
        self.payloads: list[dict[str, str]] = []
        self.fail = False

    def send(self, payload: Mapping[str, str]) -> None:
        if self.fail:
            raise WebhookError("webhook answered HTTP 500")
        self.payloads.append(dict(payload))


def worker(
    cursor_path: Path,
    projection: Projection,
    sender: Sender,
    key: str = "content",
    logs: list[str] | None = None,
) -> NotifyWorker:
    return NotifyWorker(
        community_did=COMMUNITY,
        community_name="Test Community",
        public_base_url=BASE,
        payload_key=key,
        source=projection,
        sender=sender,
        cursor=Cursor(cursor_path),
        log=(logs if logs is not None else []).append,
    )


def started(tmp_path: Path, projection: Projection, sender: Sender) -> Path:
    """Run the first (baseline) poll against an empty community."""
    path = tmp_path / "state" / "cursor.json"
    assert worker(path, projection, sender).run_once()["baselined"] == 0
    return path


def test_first_start_baselines_existing_events_without_sending(tmp_path: Path) -> None:
    projection, sender = Projection(), Sender()
    projection.queue = [pending("old1")]
    projection.discussions = [admitted("old2")]
    path = tmp_path / "cursor.json"
    counts = worker(path, projection, sender).run_once()
    assert counts == {"observed": 2, "sent": 0, "failed": 0, "baselined": 2}
    assert sender.payloads == []
    assert path.stat().st_mode & 0o777 == 0o600
    assert worker(path, projection, sender).run_once()["sent"] == 0


def test_messages_have_the_fixed_minimal_shape(tmp_path: Path) -> None:
    projection, sender = Projection(), Sender()
    path = started(tmp_path, projection, sender)
    projection.queue = [pending("p1")]
    projection.discussions = [admitted("3kadmit")]
    assert worker(path, projection, sender).run_once()["sent"] == 2
    assert sender.payloads == [
        {
            "content": "[Test Community] pending: A new post is waiting for the "
            "moderator.\nhttps://community.example.test/\n"
            "Public post: https://bsky.app/profile/did:plc:alice/post/p1"
        },
        {
            "content": "[Test Community] admitted: A new discussion was admitted.\n"
            "https://community.example.test/d/3kadmit"
        },
    ]
    assert "never forwarded" not in json.dumps(sender.payloads)
    assert projection.paths[-2:] == [QUEUE, DISCUSSIONS]


def test_slack_style_payload_key(tmp_path: Path) -> None:
    projection, sender = Projection(), Sender()
    path = started(tmp_path, projection, sender)
    projection.discussions = [admitted("r1")]
    worker(path, projection, sender, key="text").run_once()
    assert list(sender.payloads[0]) == ["text"]
    assert sender.payloads[0]["text"].endswith("/d/r1")


def test_restarts_never_resend_and_new_cids_are_new_events(tmp_path: Path) -> None:
    projection, sender = Projection(), Sender()
    path = started(tmp_path, projection, sender)
    projection.queue = [pending("p1")]
    projection.discussions = [admitted("r1")]
    assert worker(path, projection, sender).run_once()["sent"] == 2
    for _ in range(3):
        assert worker(path, projection, sender).run_once()["sent"] == 0
    assert len(sender.payloads) == 2
    projection.queue = [pending("p1", CID_B)]
    assert worker(path, projection, sender).run_once()["sent"] == 1
    assert len(sender.payloads) == 3


def test_pending_then_admitted_announces_each_once(tmp_path: Path) -> None:
    projection, sender = Projection(), Sender()
    path = started(tmp_path, projection, sender)
    projection.queue = [pending("p1")]
    worker(path, projection, sender).run_once()
    projection.queue = []
    projection.discussions = [admitted("r1")]
    worker(path, projection, sender).run_once()
    worker(path, projection, sender).run_once()
    kinds = [payload["content"].split(":", 1)[0] for payload in sender.payloads]
    assert kinds == ["[Test Community] pending", "[Test Community] admitted"]


def test_admitted_are_announced_oldest_first(tmp_path: Path) -> None:
    projection, sender = Projection(), Sender()
    path = started(tmp_path, projection, sender)
    projection.discussions = [admitted("newer"), admitted("older")]
    worker(path, projection, sender).run_once()
    assert [p["content"].rsplit("/", 1)[1] for p in sender.payloads] == [
        "older",
        "newer",
    ]


def test_webhook_failure_is_logged_and_retried_next_poll(tmp_path: Path) -> None:
    projection, sender = Projection(), Sender()
    path = started(tmp_path, projection, sender)
    projection.queue = [pending("p1"), pending("p2")]
    sender.fail = True
    logs: list[str] = []
    counts = worker(path, projection, sender, logs=logs).run_once()
    assert counts["sent"] == 0 and counts["failed"] == 2
    assert any("retry next poll" in line for line in logs)
    assert not any("room.example" in line for line in logs)
    sender.fail = False
    assert worker(path, projection, sender).run_once()["sent"] == 2
    assert worker(path, projection, sender).run_once()["sent"] == 0


def test_one_rejected_event_does_not_hold_back_the_others(tmp_path: Path) -> None:
    projection, sender = Projection(), Sender()
    path = started(tmp_path, projection, sender)

    class RejectsOne(Sender):
        def send(self, payload: Mapping[str, str]) -> None:
            if "/post/bad" in next(iter(payload.values())):
                raise WebhookError("webhook answered HTTP 400")
            super().send(payload)

    rejecting = RejectsOne()
    projection.queue = [pending("bad"), pending("p2")]
    projection.discussions = [admitted("r1")]
    logs: list[str] = []
    counts = worker(path, projection, rejecting, logs=logs).run_once()
    assert counts["sent"] == 2 and counts["failed"] == 1
    assert len(logs) == 1 and "retry next poll" in logs[0]
    counts = worker(path, projection, rejecting).run_once()
    assert counts["sent"] == 0 and counts["failed"] == 1
    assert len(rejecting.payloads) == 2
    assert not any("/post/bad" in p["content"] for p in rejecting.payloads)


def test_unreadable_webhook_answer_counts_as_failed_and_is_retried(
    tmp_path: Path,
) -> None:
    projection, sender = Projection(), Sender()
    path = started(tmp_path, projection, sender)

    class TruncatedAnswer(Sender):
        def send(self, payload: Mapping[str, str]) -> None:
            if self.fail:
                raise http.client.IncompleteRead(b"")
            super().send(payload)

    truncated = TruncatedAnswer()
    truncated.fail = True
    projection.queue = [pending("p1")]
    logs: list[str] = []
    counts = worker(path, projection, truncated, logs=logs).run_once()
    assert counts["sent"] == 0 and counts["failed"] == 1
    assert logs == [
        "webhook delivery failed: IncompleteRead: IncompleteRead(0 bytes read);"
        " will retry next poll"
    ]
    truncated.fail = False
    assert worker(path, projection, truncated).run_once()["sent"] == 1
    assert worker(path, projection, truncated).run_once()["sent"] == 0


def test_first_poll_partial_outage_leaves_no_cursor(tmp_path: Path) -> None:
    """The queue read succeeds but the discussions read fails: no baseline."""

    class QueueOnly(Projection):
        def get(self, path: str) -> Mapping[str, object]:
            if path == DISCUSSIONS:
                raise OSError("projection acquisition failed")
            return super().get(path)

    projection, sender = QueueOnly(), Sender()
    projection.queue = [pending("p1")]
    path = tmp_path / "state" / "cursor.json"
    logs: list[str] = []
    counts = worker(path, projection, sender, logs=logs).run_once()
    assert counts == {"observed": 0, "sent": 0, "failed": 1, "baselined": 0}
    assert not path.exists() and not path.parent.exists()
    assert sender.payloads == []
    assert logs == ["projection unavailable: OSError"]
    healthy = Projection()
    healthy.queue = [pending("p1")]
    healthy.discussions = [admitted("r1")]
    assert worker(path, healthy, sender).run_once()["baselined"] == 2
    assert sender.payloads == []


def test_projection_outage_changes_nothing_and_first_start_waits(
    tmp_path: Path,
) -> None:
    projection, sender = Projection(), Sender()
    projection.down = True
    path = tmp_path / "cursor.json"
    logs: list[str] = []
    counts = worker(path, projection, sender, logs=logs).run_once()
    assert counts["failed"] == 1 and not path.exists()
    assert logs == ["projection unavailable: OSError"]
    projection.down = False
    projection.queue = [pending("p1")]
    assert worker(path, projection, sender).run_once()["baselined"] == 1
    assert sender.payloads == []


def test_foreign_community_and_malformed_items_are_ignored(tmp_path: Path) -> None:
    projection, sender = Projection(), Sender()
    path = started(tmp_path, projection, sender)
    foreign = admitted("r1")
    foreign["discussion"] = {
        "uri": "at://did:plc:other/app.phlogiston.community.admission/r1",
        "cid": CID_A,
    }
    projection.discussions = [
        foreign,
        {
            "discussion": {
                "uri": f"at://{COMMUNITY}/app.phlogiston.community.admission/a b",
                "cid": CID_A,
            }
        },
        {
            "discussion": {
                "uri": f"at://{COMMUNITY}/app.phlogiston.community.admission/r2",
                "cid": "bad cid",
            }
        },
        "garbage",
    ]
    projection.queue = [{"submission": {"uri": "https://evil.test/x", "cid": CID_A}}]
    assert worker(path, projection, sender).run_once()["sent"] == 0

    class Mismatched(Projection):
        def get(self, path: str) -> Mapping[str, object]:
            return {**super().get(path), "communityDid": "did:plc:other"}

    counts = worker(path, Mismatched(), sender).run_once()
    assert counts["failed"] == 1


def test_malformed_cursor_refuses_to_start(tmp_path: Path) -> None:
    path = tmp_path / "cursor.json"
    path.write_text('{"version": 2, "sent": []}')
    with pytest.raises(ValueError, match="malformed"):
        Cursor(path)
