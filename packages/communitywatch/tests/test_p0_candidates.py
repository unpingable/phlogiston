"""Local P0 qualification fixtures; no live Bluesky qualification claim."""

import sys
from pathlib import Path

from community_model import POST_COLLECTION, SUBMISSION_COLLECTION
from communitywatch import DiscussionQuery, ObserverStore, ProjectionQuery
from test_discussions import ADMIN, AUTHOR, COMMUNITY, OTHER, Fixture, _cid


def test_candidate_fairness_continuation_and_author_filter(tmp_path):
    store = ObserverStore(
        tmp_path / "q.db", community_did=COMMUNITY, administrator_did=ADMIN
    )
    fx = Fixture(store)
    alphabet = "234567abcdefghijklmnopqrstuvwxyz"
    for did, count in ((AUTHOR, 8), (OTHER, 1)):
        for index in range(count):
            rkey = "3jzfcijpj2z2" + alphabet[index]
            post = {
                "$type": POST_COLLECTION,
                "text": str(index),
                "createdAt": "2026-09-07T12:00:00Z",
            }
            record = {
                "$type": SUBMISSION_COLLECTION,
                "community": COMMUNITY,
                "subject": {
                    "uri": f"at://{did}/{POST_COLLECTION}/{rkey}",
                    "cid": _cid(post),
                },
                "createdAt": "2026-09-07T12:00:01Z",
            }
            fx.ingest(did, SUBMISSION_COLLECTION, rkey, record, offset=index)
    query = DiscussionQuery(ProjectionQuery(store, "test"))
    page = query.moderation_queue(COMMUNITY)
    assert [item["authorDid"] for item in page.submissions].count(AUTHOR) == 3
    assert any(item["authorDid"] == OTHER for item in page.submissions)
    assert page.coverage["incomplete"] is True
    own = query.moderation_queue(
        COMMUNITY, author_did=AUTHOR, cursor=page.coverage["authorCursors"][AUTHOR]
    )
    assert len(own.submissions) == 3
    assert all(item["authorDid"] == AUTHOR for item in own.submissions)
    assert not (
        {item["submission"]["uri"] for item in own.submissions}
        & {item["submission"]["uri"] for item in page.submissions}
    )
    # Pages with one slot still progress beyond a noisy first repository.
    first = query.moderation_queue(COMMUNITY, limit=1)
    later = query.moderation_queue(COMMUNITY, limit=1, cursor=first.cursor)
    assert later.submissions[0]["authorDid"] == OTHER


def test_unseen_did_real_stream_verifier_runner_recovery_local_fixture(tmp_path):
    sys.path.insert(
        0, str(Path(__file__).resolve().parents[3] / "tests" / "acceptance")
    )
    from ingest_fixtures import FakeAtprotoServer, FakeJetstreamServer, FixtureRepo

    from communitywatch.jetstream import JetstreamEventSource
    from communitywatch.runner import ObserverRunner
    from communitywatch.syncclient import DidResolver, PdsClient, UrllibHttpGetter
    from communitywatch.verifying import VerifyingEventSource

    did = "did:plc:previouslyunseen"
    community = "did:plc:community"
    repo = FixtureRepo(did, 0xBABE)
    rkey = "3jzfcijpj2z2a"
    post = {
        "$type": POST_COLLECTION,
        "text": "local fixture",
        "createdAt": "2026-09-07T12:00:00Z",
    }
    repo.put(POST_COLLECTION, rkey, post)
    record = {
        "$type": SUBMISSION_COLLECTION,
        "community": community,
        "subject": {
            "uri": f"at://{did}/{POST_COLLECTION}/{rkey}",
            "cid": repo.record_cid(POST_COLLECTION, rkey),
        },
        "createdAt": "2026-09-07T12:00:01Z",
    }
    repo.put(SUBMISSION_COLLECTION, rkey, record)
    event = {
        "$type": "message",
        "payload": {
            "$type": "network.bsky.jetstream.subscribeEvents#commit",
            "did": did,
            "seq": 1,
            "time": "2026-09-07T12:00:02Z",
            "rev": repo.current_rev,
            "operation": "create",
            "collection": SUBMISSION_COLLECTION,
            "rkey": rkey,
            "cid": repo.record_cid(SUBMISSION_COLLECTION, rkey),
            "record": record,
        },
    }
    pds = FakeAtprotoServer({did: repo})
    stream = FakeJetstreamServer([event])
    pds.start()
    stream.start()
    try:
        store = ObserverStore(
            tmp_path / "stream.db",
            community_did=community,
            administrator_did="did:plc:admin",
        )
        http = UrllibHttpGetter(timeout_seconds=1)
        source = JetstreamEventSource(stream.url, max_batch=1, receive_timeout=0.1)
        assert source.wanted_dids == ()
        verifier = VerifyingEventSource(
            source, DidResolver(http, plc_url=pds.url), PdsClient(http)
        )
        runner = ObserverRunner(store, verifier, "jetstream")
        assert runner.run_ingest_once() == 1
        assert store.source_cursor("jetstream") == "1"
        queue = DiscussionQuery(ProjectionQuery(store, "local")).moderation_queue(
            community
        )
        assert queue.submissions[0]["authorDid"] == did
        recovered = ObserverStore(
            store.path, community_did=community, administrator_did="did:plc:admin"
        )
        assert ObserverRunner(recovered, verifier, "jetstream").run_ingest_once() == 0
        assert recovered.counts()["event_receipts"] == 1
    finally:
        stream.stop()
        pds.stop()


def test_p0_supported_host_refusal_before_repository_fetch():
    sys.path.insert(
        0, str(Path(__file__).resolve().parents[3] / "tests" / "acceptance")
    )
    from ingest_fixtures import FixtureRepo

    from communitywatch.verifying import _Claim, _ProofFetcher, supported_bluesky_pds

    assert supported_bluesky_pds("https://porcini.us-east.host.bsky.network")
    for url in (
        "https://host.bsky.network",
        "https://pds.invalid",
        "http://a.host.bsky.network",
        "https://a.host.bsky.network:444",
        "https://a.host.bsky.network.evil.invalid",
    ):
        assert not supported_bluesky_pds(url)
    repo = FixtureRepo("did:plc:fixture", 0x1234)

    class Resolver:
        def resolve(self, did):
            return repo.did_document("https://unsupported.invalid")

    class NoFetch:
        def get_record_car(self, *args, **kwargs):
            raise AssertionError("unsupported PDS must not be fetched")

        def get_repo_car(self, *args, **kwargs):
            raise AssertionError("unsupported PDS must not be fetched")

    result = _ProofFetcher(Resolver(), NoFetch(), p0_bluesky_only=True).fetch(
        _Claim(
            repo.did,
            "2222222222222",
            "create",
            SUBMISSION_COLLECTION,
            "3jzfcijpj2z2a",
            None,
        )
    )
    assert result == (None, "p0:unsupported-pds-host", None, "unverified")


def test_isolated_provider_override_is_explicit_and_loopback_only():
    import pytest

    from communitywatch.config import ConfigError, parse_config

    document = {
        "community_did": COMMUNITY,
        "community_slug": "local",
        "sqlite_path": "fixture.db",
        "event_source_url": "wss://stream.invalid",
        "resolver_url": "https://plc.directory",
        "p0_bluesky_only": True,
        "p0_test_pds_origin": "https://juche.social",
    }
    with pytest.raises(ConfigError):
        parse_config(document)
    document["p0_isolated_test"] = True
    assert parse_config(document).p0_test_pds_origin == "https://juche.social"
    document["bind"] = "0.0.0.0"
    with pytest.raises(ConfigError):
        parse_config(document)


def test_candidate_requires_current_exact_submission_variant(tmp_path):
    from community_model import IncomingDelivery
    from test_discussions import BASE

    for operation in ("delete", "update"):
        store = ObserverStore(
            tmp_path / f"{operation}.db",
            community_did=COMMUNITY,
            administrator_did=ADMIN,
        )
        fx = Fixture(store)
        rkey = "3jzfcijpj2z2a"
        record = {
            "$type": SUBMISSION_COLLECTION,
            "community": COMMUNITY,
            "subject": {
                "uri": f"at://{AUTHOR}/{POST_COLLECTION}/{rkey}",
                "cid": _cid({"version": 1}),
            },
            "createdAt": "2026-09-07T12:00:01Z",
        }
        fx.ingest(AUTHOR, SUBMISSION_COLLECTION, rkey, record, offset=1)
        query = DiscussionQuery(ProjectionQuery(store, "local"))
        assert len(query.moderation_queue(COMMUNITY).submissions) == 1
        envelope = {
            "repo": AUTHOR,
            "rev": "2222222222225",
            "operation": operation,
            "collection": SUBMISSION_COLLECTION,
            "rkey": rkey,
        }
        if operation == "update":
            changed = {
                **record,
                "subject": {**record["subject"], "cid": _cid({"version": 2})},
            }
            envelope.update(record=changed, cid=_cid(changed))
        store.ingest(
            IncomingDelivery(
                source="fixture",
                cursor="2",
                source_event_time=BASE,
                received_at=BASE,
                raw_envelope=envelope,
                trust_mode="test_fixture",
                verification_outcome="verified",
                verification_method="fixture",
                verifier_version="1",
            )
        )
        candidates = query.moderation_queue(COMMUNITY).submissions
        if operation == "delete":
            assert candidates == ()
        else:
            assert len(candidates) == 1
            assert candidates[0]["subject"] == changed["subject"]
            assert candidates[0]["submission"]["cid"] != _cid(record)


def test_filtered_prefix_checkpoints_and_reaches_unseen_did_after_restart(
    tmp_path, monkeypatch
):
    """Local signed-proof fixture over real source/verifier/runner, no sockets."""
    import json
    from urllib.parse import parse_qs, urlsplit

    sys.path.insert(
        0, str(Path(__file__).resolve().parents[3] / "tests" / "acceptance")
    )
    from ingest_fixtures import FixtureRepo

    import communitywatch.jetstream as jetstream
    from communitywatch.runner import ObserverRunner
    from communitywatch.verifying import VerifyingEventSource

    did = "did:plc:unseencursorfixture"
    repo = FixtureRepo(did, 0xBABE)
    rkey = "3jzfcijpj2z2a"
    post = {
        "$type": POST_COLLECTION,
        "text": "local",
        "createdAt": "2026-09-07T12:00:00Z",
    }
    repo.put(POST_COLLECTION, rkey, post)
    record = {
        "$type": SUBMISSION_COLLECTION,
        "community": COMMUNITY,
        "subject": {
            "uri": f"at://{did}/{POST_COLLECTION}/{rkey}",
            "cid": repo.record_cid(POST_COLLECTION, rkey),
        },
        "createdAt": "2026-09-07T12:00:01Z",
    }
    repo.put(SUBMISSION_COLLECTION, rkey, record)
    events = [
        {
            "$type": "message",
            "payload": {
                "$type": "network.bsky.jetstream.subscribeEvents#identity",
                "seq": seq,
                "did": did,
            },
        }
        for seq in range(1, 6)
    ]
    events.append(
        {
            "$type": "message",
            "payload": {
                "$type": jetstream.COMMIT_PAYLOAD_TYPE,
                "seq": 6,
                "did": did,
                "time": "2026-09-07T12:00:02Z",
                "rev": repo.current_rev,
                "operation": "create",
                "collection": SUBMISSION_COLLECTION,
                "rkey": rkey,
                "record": record,
                "cid": repo.record_cid(SUBMISSION_COLLECTION, rkey),
            },
        }
    )

    class Stream:
        def __init__(self, frames):
            self.frames = frames

        def settimeout(self, timeout):
            pass

        def close(self):
            pass

    def connect(url, **kwargs):
        after = int(parse_qs(urlsplit(url).query).get("cursor", ["0"])[0])
        return Stream(
            [
                json.dumps(event).encode()
                for event in events
                if event["payload"]["seq"] >= after
            ]
        )

    class Did:
        def resolve(self, requested):
            assert requested == did
            return repo.did_document("https://fixture.invalid")

    class Pds:
        def get_record_car(self, origin, *, repo: str, collection, rkey):
            return fixture_repo.record_car(collection, rkey)

    fixture_repo = repo
    monkeypatch.setattr(jetstream, "iter_messages", lambda sock: iter(sock.frames))
    source = jetstream.JetstreamEventSource(
        "wss://fixture.invalid", max_batch=1, connect=connect
    )
    verifier = VerifyingEventSource(source, Did(), Pds())
    store = ObserverStore(
        tmp_path / "progress.db", community_did=COMMUNITY, administrator_did=ADMIN
    )
    assert ObserverRunner(store, verifier, "jetstream").run_ingest_once() == 1
    assert store.source_cursor("jetstream") == "4"
    assert (
        DiscussionQuery(ProjectionQuery(store, "local"))
        .moderation_queue(COMMUNITY)
        .submissions
        == ()
    )
    reopened = ObserverStore(
        store.path, community_did=COMMUNITY, administrator_did=ADMIN
    )
    assert ObserverRunner(reopened, verifier, "jetstream").run_ingest_once() == 1
    assert reopened.source_cursor("jetstream") == "6"
    queue = DiscussionQuery(ProjectionQuery(reopened, "local")).moderation_queue(
        COMMUNITY
    )
    assert queue.submissions[0]["authorDid"] == did


def test_filtered_progress_never_rewinds_durable_cursor(monkeypatch):
    import json

    import communitywatch.jetstream as jetstream

    class Stream:
        def settimeout(self, timeout):
            pass

        def close(self):
            pass

    def frames(sequences):
        return [
            json.dumps(
                {
                    "$type": "message",
                    "payload": {
                        "$type": "network.bsky.jetstream.subscribeEvents#identity",
                        "seq": seq,
                    },
                }
            ).encode()
            for seq in sequences
        ]

    source = jetstream.JetstreamEventSource(
        "wss://fixture.invalid", max_batch=1, connect=lambda *args, **kwargs: Stream()
    )
    monkeypatch.setattr(
        jetstream, "iter_messages", lambda sock: iter(frames([3, 4, 5, 6, 12]))
    )
    batch = source.read("10")
    assert batch.items == ()
    assert batch.next_cursor == "10"
    monkeypatch.setattr(
        jetstream, "iter_messages", lambda sock: iter(frames([12, 11, False, None]))
    )
    batch = source.read("10")
    assert [item.cursor for item in batch.items] == ["12"]
    assert batch.items[0].verification_outcome.value == "unverified"
    assert isinstance(batch.items[0].raw_envelope, bytes)


def test_filtered_checkpoint_is_only_trailing_after_quarantine(monkeypatch):
    import json

    import communitywatch.jetstream as jetstream

    class Stream:
        def settimeout(self, timeout):
            pass

        def close(self):
            pass

    def event(sequence, collection=SUBMISSION_COLLECTION, **fields):
        return {
            "$type": "message",
            "payload": {
                "$type": jetstream.COMMIT_PAYLOAD_TYPE,
                "did": AUTHOR,
                "seq": sequence,
                "time": "2026-09-07T12:00:00Z",
                "collection": collection,
                "operation": "create",
                "rkey": "3jzfcijpj2z2a",
                **fields,
            },
        }

    identity = {
        "$type": "message",
        "payload": {
            "$type": "network.bsky.jetstream.subscribeEvents#identity",
            "seq": 1,
        },
    }
    v1 = {
        "kind": "commit",
        "time_us": 1755180000000000,
        "commit": {"operation": "create"},
    }
    frames = [
        json.dumps(identity).encode(),
        json.dumps(event(2, "app.bsky.feed.like")).encode(),
        json.dumps(event(3, rev="2222222222225", cid=_cid({}), record={})).encode(),
        b"this is not json",
        json.dumps(event(5)).encode(),
        json.dumps(v1).encode(),
    ]
    monkeypatch.setattr(jetstream, "iter_messages", lambda sock: iter(frames))
    source = jetstream.JetstreamEventSource(
        "wss://fixture.invalid", max_batch=100, connect=lambda *args, **kwargs: Stream()
    )
    batch = source.read(None)
    assert len(batch.items) == 4
    assert [item.cursor for item in batch.items if item.cursor.isdigit()] == ["3", "5"]
    assert all(
        item.verification_method != "jetstream-v2-filtered-progress"
        for item in batch.items
    )
    # A genuinely later trailing sequence remains durable transport progress.
    frames.append(
        json.dumps(
            {
                "$type": "message",
                "payload": {
                    "$type": "network.bsky.jetstream.subscribeEvents#identity",
                    "seq": 6,
                },
            }
        ).encode()
    )
    batch = source.read(None)
    assert len(batch.items) == 5
    assert batch.items[-1].cursor == "6"
    assert batch.next_cursor == "6"


def test_unsequenced_quarantine_runner_restart_preserves_numeric_or_no_position(
    tmp_path, monkeypatch
):
    """Malformed receipts retain custody but do not manufacture relay progress."""
    import json
    from urllib.parse import parse_qs, urlsplit

    import communitywatch.jetstream as jetstream
    from communitywatch.runner import ObserverRunner
    from communitywatch.verifying import VerifyingEventSource

    sys.path.insert(
        0, str(Path(__file__).resolve().parents[3] / "tests" / "acceptance")
    )
    from ingest_fixtures import FixtureRepo

    did = "did:plc:quarantinerecoveryfixture"
    fixture = FixtureRepo(did, 0xBABE)
    rkey = "3jzfcijpj2z2a"
    post = {
        "$type": POST_COLLECTION,
        "text": "local",
        "createdAt": "2026-09-07T12:00:00Z",
    }
    fixture.put(POST_COLLECTION, rkey, post)
    record = {
        "$type": SUBMISSION_COLLECTION,
        "community": COMMUNITY,
        "subject": {
            "uri": f"at://{did}/{POST_COLLECTION}/{rkey}",
            "cid": fixture.record_cid(POST_COLLECTION, rkey),
        },
        "createdAt": "2026-09-07T12:00:01Z",
    }
    fixture.put(SUBMISSION_COLLECTION, rkey, record)

    class Stream:
        def __init__(self, frames):
            self.frames = frames

        def settimeout(self, timeout):
            pass

        def close(self):
            pass

    class Did:
        def resolve(self, requested):
            assert requested == did
            return fixture.did_document("https://fixture.invalid")

    class Pds:
        def get_record_car(self, origin, *, repo, collection, rkey):
            return fixture.record_car(collection, rkey)

    monkeypatch.setattr(jetstream, "iter_messages", lambda sock: iter(sock.frames))
    malformed_cases = [
        b"malformed local fixture",
        json.dumps(
            {
                "$type": "message",
                "payload": {"$type": jetstream.COMMIT_PAYLOAD_TYPE, "seq": True},
            }
        ).encode(),
        json.dumps(
            {
                "$type": "message",
                "payload": {"$type": jetstream.COMMIT_PAYLOAD_TYPE, "seq": -1},
            }
        ).encode(),
    ]
    for case, prior in enumerate((None, 4, None, None)):
        malformed = malformed_cases[max(0, case - 1)]
        requested = []
        sequence = 1 if prior is None else prior + 1
        valid = {
            "$type": "message",
            "payload": {
                "$type": jetstream.COMMIT_PAYLOAD_TYPE,
                "did": did,
                "seq": sequence,
                "time": "2026-09-07T12:00:02Z",
                "rev": fixture.current_rev,
                "operation": "create",
                "collection": SUBMISSION_COLLECTION,
                "rkey": rkey,
                "record": record,
                "cid": fixture.record_cid(SUBMISSION_COLLECTION, rkey),
            },
        }
        initial = (
            []
            if prior is None
            else [
                json.dumps(
                    {
                        "$type": "message",
                        "payload": {
                            "$type": "network.bsky.jetstream.subscribeEvents#identity",
                            "seq": prior,
                        },
                    }
                ).encode()
            ]
        )
        initial.append(malformed)
        batches = [initial, [json.dumps(valid).encode()], []]

        def connect(url, **kwargs):
            requested.append(parse_qs(urlsplit(url).query).get("cursor"))
            return Stream(batches.pop(0))

        source = jetstream.JetstreamEventSource(
            "wss://fixture.invalid", connect=connect, max_batch=2
        )
        verifier = VerifyingEventSource(source, Did(), Pds())
        store = ObserverStore(
            tmp_path / f"resume-{case}.db",
            community_did=COMMUNITY,
            administrator_did=ADMIN,
        )
        assert ObserverRunner(store, verifier, "jetstream").run_ingest_once() == 1
        cursor = store.source_cursor("jetstream")
        assert cursor.endswith("%resume%none" if prior is None else "%resume%4")
        assert jetstream.resume_sequence(cursor) == prior
        with store.read_connection() as connection:
            raw = connection.execute(
                "SELECT raw_envelope FROM quarantined_deliveries"
            ).fetchone()[0]
            assert raw == malformed
        reopened = ObserverStore(
            store.path, community_did=COMMUNITY, administrator_did=ADMIN
        )
        assert ObserverRunner(reopened, verifier, "jetstream").run_ingest_once() == 1
        assert requested == [None, None if prior is None else ["5"]]
        assert reopened.source_cursor("jetstream") == str(sequence)
        assert (
            DiscussionQuery(ProjectionQuery(reopened, "local"))
            .moderation_queue(COMMUNITY)
            .submissions[0]["authorDid"]
            == did
        )
        assert ObserverRunner(reopened, verifier, "jetstream").run_ingest_once() == 0
