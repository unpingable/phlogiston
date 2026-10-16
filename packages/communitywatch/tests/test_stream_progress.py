"""Bounded identity progress is transport custody, never repository authority."""

import json
import struct
from urllib.parse import parse_qs, urlsplit

import pytest

from communitywatch.jetstream import JetstreamEventSource
from communitywatch.runner import ObserverRunner
from communitywatch.storage import ObserverStore


def frame(value, opcode=1):
    body = json.dumps(value).encode() if opcode == 1 else value
    header = (
        bytes([0x80 | opcode, len(body)])
        if len(body) < 126
        else bytes([0x80 | opcode, 126]) + struct.pack("!H", len(body))
    )
    return header + body


def identity(seq, kind="identity"):
    return {
        "$type": "message",
        "payload": {
            "$type": "network.bsky.jetstream.subscribeEvents#" + kind,
            "seq": seq,
        },
    }


class ClockSocket:
    def __init__(self, data, clock):
        self.data = data
        self.clock = clock
        self.timeouts = []
        self.closed = False

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def recv(self, size):
        self.clock[0] += 0.25
        result, self.data = self.data[:size], self.data[size:]
        return result

    def sendall(self, data):
        self.clock[0] += 0.25

    def close(self):
        self.closed = True


@pytest.mark.parametrize("kind", ["identity", "account", "sync"])
def test_noncommit_stream_deadline_commits_only_observed_prefix(tmp_path, kind):
    clock = [0.0]
    sock = ClockSocket(b"".join(frame(identity(i, kind)) for i in range(1, 101)), clock)
    source = JetstreamEventSource(
        "wss://fixture.example",
        receive_timeout=2,
        clock=lambda: clock[0],
        connect=lambda *args, **kwargs: sock,
    )
    query = parse_qs(urlsplit(source.subscribe_url(None)).query)
    assert query["kinds"] == ["commit", "identity", "account", "sync"]
    store = ObserverStore(
        tmp_path / "observer.sqlite",
        community_did="did:plc:community",
        administrator_did="did:plc:admin",
    )
    runner = ObserverRunner(store, source, source.source_name)
    runner.run_ingest_once()
    assert store.source_cursor(source.source_name) == "5"
    assert sock.closed and clock[0] == 2.5
    with store._connect() as conn:
        assert (
            conn.execute("SELECT count(*) FROM quarantined_deliveries").fetchone()[0]
            == 1
        )
        assert conn.execute("SELECT count(*) FROM ledger_records").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT verification_outcome FROM quarantined_deliveries"
            ).fetchone()[0]
            == "unverified"
        )


def test_pings_cannot_extend_batch_deadline():
    clock = [0.0]
    sock = ClockSocket(frame(b"ping", 9) * 100, clock)
    source = JetstreamEventSource(
        "wss://fixture.example",
        receive_timeout=2,
        first_frame_timeout=2,
        clock=lambda: clock[0],
        connect=lambda *args, **kwargs: sock,
    )
    batch = source.read("10")
    assert batch.items == () and batch.next_cursor == "10"
    assert sock.closed and clock[0] == 2


def test_backwards_identity_does_not_rewind_checkpoint():
    clock = [0.0]
    sock = ClockSocket(
        frame(identity(9)) + frame(identity(12)) + frame(identity(11)) + frame(b"", 8),
        clock,
    )
    source = JetstreamEventSource(
        "wss://fixture.example",
        clock=lambda: clock[0],
        connect=lambda *args, **kwargs: sock,
    )
    batch = source.read("10")
    assert len(batch.items) == 1 and batch.next_cursor == "12"
    assert batch.items[0].verification_outcome == "unverified"


class DelayedSocket(ClockSocket):
    def __init__(self, data, clock, delay):
        super().__init__(data, clock)
        self.delay = delay

    def recv(self, size):
        if self.delay:
            delay, self.delay = self.delay, 0
            if delay >= self.timeouts[-1]:
                self.clock[0] += self.timeouts[-1]
                raise TimeoutError("fixture receive deadline")
            self.clock[0] += delay
        return super().recv(size)


def test_sparse_first_frame_has_separate_wait_then_short_drain():
    clock = [0.0]
    sock = DelayedSocket(
        b"".join(frame(identity(i)) for i in range(11, 111)), clock, 16
    )
    source = JetstreamEventSource(
        "wss://fixture.example",
        receive_timeout=2,
        clock=lambda: clock[0],
        connect=lambda *args, **kwargs: sock,
    )
    batch = source.read("10")
    assert batch.next_cursor == "15"
    assert clock[0] == 18.5 and sock.closed
    assert max(sock.timeouts) == 90


def test_no_first_frame_preserves_cursor_at_first_phase_deadline():
    clock = [0.0]
    sock = DelayedSocket(frame(identity(11)), clock, 100)
    source = JetstreamEventSource(
        "wss://fixture.example",
        clock=lambda: clock[0],
        connect=lambda *args, **kwargs: sock,
    )
    batch = source.read("10")
    assert batch.items == () and batch.next_cursor == "10"
    assert clock[0] == 90 and sock.closed


def test_partial_frame_cannot_extend_first_phase_deadline():
    clock = [0.0]

    class PartialSocket(ClockSocket):
        def recv(self, size):
            # One byte per read keeps a data frame incomplete.
            return super().recv(min(size, 1))

    sock = PartialSocket(frame(identity(11)), clock)
    source = JetstreamEventSource(
        "wss://fixture.example",
        first_frame_timeout=2,
        clock=lambda: clock[0],
        connect=lambda *args, **kwargs: sock,
    )
    batch = source.read("10")
    assert batch.items == () and batch.next_cursor == "10"
    assert clock[0] == 2 and sock.closed


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True])
@pytest.mark.parametrize("field", ["receive_timeout", "first_frame_timeout"])
def test_phase_deadline_requires_finite_positive_timeout(field, timeout):
    from community_model import ValidationError

    with pytest.raises(ValidationError, match="finite and positive"):
        JetstreamEventSource("wss://fixture.example", **{field: timeout})
