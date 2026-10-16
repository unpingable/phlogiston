"""V0-M6 observer ingestion: verify-at-ingest over fully offline fakes.

Every test runs against programmatically built fixture repositories, a
loopback fake PDS/PLC HTTP server, and a loopback fake Jetstream WebSocket
server.  No test touches the real network.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from ingest_fixtures import (
    FakeAtprotoServer,
    FakeJetstreamServer,
    FixtureRepo,
    mint_tid,
)

from community_model import (
    ADMISSION_COLLECTION,
    COMMUNITY_COLLECTIONS,
    POST_COLLECTION,
    PROFILE_COLLECTION,
    SUBMISSION_COLLECTION,
    IncomingDelivery,
    RecordRef,
    admission_rkey,
    sha256_digest,
)
from communitywatch import (
    ObserverStore,
    ProjectionQuery,
)
from communitywatch.fakes import FakeEventSource
from communitywatch.jetstream import JetstreamEventSource
from communitywatch.runner import ObserverRunner
from communitywatch.syncclient import DidResolver, PdsClient, UrllibHttpGetter
from communitywatch.verifying import (
    METHOD_REPO_PROOF,
    METHOD_REPO_RESYNC,
    VerifiedSubjectResolver,
    VerifyingEventSource,
)

COMMUNITY_DID = "did:plc:community"
ADMIN_DID = "did:plc:admin"
AUTHOR_DID = "did:plc:author"
COMMUNITY_KEY = 0xC0A1
AUTHOR_KEY = 0xB0B5
POST_RKEY = "3jzfcijpj2z2a"
SUBMISSION_RKEY = "3jzfcijpj2z2b"
T0 = datetime(2026, 8, 14, 10, 0, 0, tzinfo=UTC)
SOURCE = "jetstream"


# --- shared fixture builders --------------------------------------------------


def _post_record() -> dict[str, object]:
    return {
        "$type": POST_COLLECTION,
        "text": "hello homelab",
        "createdAt": "2026-08-13T12:00:00Z",
    }


def _author_repo() -> FixtureRepo:
    repo = FixtureRepo(AUTHOR_DID, AUTHOR_KEY)
    repo.put(POST_COLLECTION, POST_RKEY, _post_record())
    return repo


def _post_ref(repo: FixtureRepo) -> dict[str, str]:
    return {
        "uri": f"at://{AUTHOR_DID}/{POST_COLLECTION}/{POST_RKEY}",
        "cid": repo.record_cid(POST_COLLECTION, POST_RKEY),
    }


def _submit(repo: FixtureRepo) -> str:
    submission = {
        "$type": SUBMISSION_COLLECTION,
        "community": COMMUNITY_DID,
        "subject": _post_ref(repo),
        "createdAt": "2026-08-13T12:01:00Z",
    }
    return repo.put(SUBMISSION_COLLECTION, SUBMISSION_RKEY, submission)


def _submission_ref(repo: FixtureRepo) -> dict[str, str]:
    return {
        "uri": f"at://{AUTHOR_DID}/{SUBMISSION_COLLECTION}/{SUBMISSION_RKEY}",
        "cid": repo.record_cid(SUBMISSION_COLLECTION, SUBMISSION_RKEY),
    }


def _community_repo(author: FixtureRepo) -> FixtureRepo:
    repo = FixtureRepo(COMMUNITY_DID, COMMUNITY_KEY)
    repo.put(
        PROFILE_COLLECTION,
        "self",
        {
            "$type": PROFILE_COLLECTION,
            "displayName": "Homelab",
            "createdAt": "2026-08-13T11:00:00Z",
        },
    )
    repo.put(
        ADMISSION_COLLECTION,
        admission_rkey(RecordRef(**_submission_ref(author))),
        {
            "$type": ADMISSION_COLLECTION,
            "submission": _submission_ref(author),
            "subject": _post_ref(author),
            "actor": ADMIN_DID,
            "createdAt": "2026-08-13T12:02:00Z",
        },
    )
    return repo


def _admission_rkey(author: FixtureRepo) -> str:
    return admission_rkey(RecordRef(**_submission_ref(author)))


def _claim(
    repo_did: str,
    rev: str,
    operation: str,
    collection: str,
    rkey: str,
    *,
    cursor: str,
    cid: str | None = None,
    record: dict[str, object] | None = None,
) -> IncomingDelivery:
    envelope: dict[str, object] = {
        "repo": repo_did,
        "rev": rev,
        "operation": operation,
        "collection": collection,
        "rkey": rkey,
    }
    if cid is not None:
        envelope["cid"] = cid
    if record is not None:
        envelope["record"] = record
    return IncomingDelivery(
        source=SOURCE,
        cursor=cursor,
        source_event_time=T0,
        received_at=T0,
        raw_envelope=envelope,
        trust_mode="verify_repo",
        verification_outcome="unverified",
        verification_method="jetstream-v2-transport",
        verifier_version="1",
    )


def _verifier(server: FakeAtprotoServer) -> VerifyingEventSource:
    http = UrllibHttpGetter(timeout_seconds=5.0)
    return VerifyingEventSource(
        FakeEventSource(()),
        DidResolver(http, plc_url=server.url),
        PdsClient(http),
    )


def _resolver(server: FakeAtprotoServer) -> VerifiedSubjectResolver:
    http = UrllibHttpGetter(timeout_seconds=5.0)
    return VerifiedSubjectResolver(
        DidResolver(http, plc_url=server.url), PdsClient(http)
    )


def _store(tmp_path: Path) -> ObserverStore:
    return ObserverStore(
        tmp_path / "observer.sqlite3",
        community_did=COMMUNITY_DID,
        administrator_did=ADMIN_DID,
    )


@pytest.fixture
def world():
    author = _author_repo()
    _submit(author)
    community = _community_repo(author)
    server = FakeAtprotoServer({AUTHOR_DID: author, COMMUNITY_DID: community})
    server.start()
    try:
        yield author, community, server
    finally:
        server.stop()


# --- repository proof verification --------------------------------------------


def test_record_proof_membership_and_non_membership(world) -> None:
    author, _, _ = world
    car = author.record_car(SUBMISSION_COLLECTION, SUBMISSION_RKEY)
    from communitywatch.repoproof import ProofError, verify_record_proof

    proof = verify_record_proof(
        car,
        repo_did=AUTHOR_DID,
        collection=SUBMISSION_COLLECTION,
        rkey=SUBMISSION_RKEY,
        public_key=author.public_key,
    )
    assert proof.present
    assert proof.record_cid == author.record_cid(SUBMISSION_COLLECTION, SUBMISSION_RKEY)
    assert proof.commit.rev == author.current_rev

    absent = verify_record_proof(
        author.repo_car(),
        repo_did=AUTHOR_DID,
        collection=SUBMISSION_COLLECTION,
        rkey="3jzfcijpj2z9z",
        public_key=author.public_key,
    )
    assert not absent.present

    with pytest.raises(ProofError):
        verify_record_proof(
            car,
            repo_did=AUTHOR_DID,
            collection=SUBMISSION_COLLECTION,
            rkey=SUBMISSION_RKEY,
            public_key=FixtureRepo("did:plc:other", 0xDEAD).public_key,
        )
    with pytest.raises(ProofError):
        verify_record_proof(
            car,
            repo_did="did:plc:someoneelse",
            collection=SUBMISSION_COLLECTION,
            rkey=SUBMISSION_RKEY,
            public_key=author.public_key,
        )
    tampered = bytearray(car)
    tampered[-1] ^= 0x01
    with pytest.raises(ProofError):
        verify_record_proof(
            bytes(tampered),
            repo_did=AUTHOR_DID,
            collection=SUBMISSION_COLLECTION,
            rkey=SUBMISSION_RKEY,
            public_key=author.public_key,
        )
    # A record CAR missing a needed MST proof node cannot prove anything.
    commit_cid, blocks, root = author._commit()
    from ingest_fixtures import _mst_path, build_car

    path = _mst_path(
        blocks, root, f"{SUBMISSION_COLLECTION}/{SUBMISSION_RKEY}".encode()
    )
    record_cid = author.record_cid(SUBMISSION_COLLECTION, SUBMISSION_RKEY)
    drop = next(iter(path - {root}), root)
    partial = {
        cid: data
        for cid, data in blocks.items()
        if cid != drop and cid in (path | {commit_cid, record_cid})
    }
    with pytest.raises(ProofError):
        verify_record_proof(
            build_car(commit_cid, partial),
            repo_did=AUTHOR_DID,
            collection=SUBMISSION_COLLECTION,
            rkey=SUBMISSION_RKEY,
            public_key=author.public_key,
        )


def _mst_node(entries: list[tuple[bytes, str]], left: str | None = None) -> bytes:
    """Encode one MST node block; entries are (full key, value CID) pairs."""
    from community_model import encode_dag_cbor

    encoded_entries = []
    previous = b""
    for key, value in entries:
        prefix = 0
        while (
            prefix < len(previous)
            and prefix < len(key)
            and previous[prefix] == key[prefix]
        ):
            prefix += 1
        encoded_entries.append(
            {
                "p": prefix,
                "k": key[prefix:],
                "v": {"$link": value},
                "t": None,
            }
        )
        previous = key
    node: dict[str, object] = {
        "l": {"$link": left} if left is not None else None,
        "e": encoded_entries,
    }
    return encode_dag_cbor(node)


def test_mst_lookup_empty_intermediate_node() -> None:
    """Spec-legal empty intermediates must not reject an otherwise valid proof.

    ATProto repository spec: "Empty intermediate nodes are allowed, as long
    as they point to a sub-tree which does contain entries." Regression:
    the live participant repository's submit proof path crosses exactly such a
    node, and the verifier previously failed it closed.
    """
    from community_model import cid_for_dag_cbor, encode_dag_cbor
    from communitywatch.repoproof import mst_lookup

    key_lo = b"app.bsky.feed.post/3jzfcijpj2z0"  # depth 0, sorts first
    key_hi = b"app.bsky.feed.post/3jzfcijpj2z80"  # depth 2, in the root
    value_lo = cid_for_dag_cbor(encode_dag_cbor({"text": "lo"}))
    value_hi = cid_for_dag_cbor(encode_dag_cbor({"text": "hi"}))

    leaf = _mst_node([(key_lo, value_lo)])
    leaf_cid = cid_for_dag_cbor(leaf)
    intermediate = _mst_node([], left=leaf_cid)
    intermediate_cid = cid_for_dag_cbor(intermediate)
    root = _mst_node([(key_hi, value_hi)], left=intermediate_cid)
    root_cid = cid_for_dag_cbor(root)
    blocks = {
        root_cid: root,
        intermediate_cid: intermediate,
        leaf_cid: leaf,
    }

    # Membership through the empty intermediate.
    assert mst_lookup(blocks, root_cid, key_lo) == value_lo
    assert mst_lookup(blocks, root_cid, key_hi) == value_hi
    # Non-membership through the empty intermediate proves absence.
    assert mst_lookup(blocks, root_cid, b"app.bsky.feed.post/3jzfcijpj2z1") is None


def test_mst_lookup_rejects_pruned_shapes() -> None:
    """Empty nodes pruned by the spec (top and bottom) stay fail-closed."""
    from community_model import cid_for_dag_cbor, encode_dag_cbor
    from communitywatch.repoproof import ProofError, mst_lookup

    key_lo = b"app.bsky.feed.post/3jzfcijpj2z0"
    key_hi = b"app.bsky.feed.post/3jzfcijpj2z80"
    value_hi = cid_for_dag_cbor(encode_dag_cbor({"text": "hi"}))

    # The wholly empty tree proves absence.
    empty_root = _mst_node([])
    empty_root_cid = cid_for_dag_cbor(empty_root)
    assert mst_lookup({empty_root_cid: empty_root}, empty_root_cid, key_lo) is None

    # An empty root pointing at a subtree must have been pruned: reject.
    leaf = _mst_node([(key_lo, value_hi)])
    leaf_cid = cid_for_dag_cbor(leaf)
    bad_root = _mst_node([], left=leaf_cid)
    bad_root_cid = cid_for_dag_cbor(bad_root)
    with pytest.raises(ProofError):
        mst_lookup({bad_root_cid: bad_root, leaf_cid: leaf}, bad_root_cid, key_lo)

    # An empty leaf below the root (no entries, no subtree): reject.
    empty_leaf = _mst_node([])
    empty_leaf_cid = cid_for_dag_cbor(empty_leaf)
    root = _mst_node([(key_hi, value_hi)], left=empty_leaf_cid)
    root_cid = cid_for_dag_cbor(root)
    with pytest.raises(ProofError):
        mst_lookup({root_cid: root, empty_leaf_cid: empty_leaf}, root_cid, key_lo)

    # A cycle of empty intermediates must not spin the lookup forever.
    # (Hash-verified CARs cannot contain cycles, but mst_lookup also serves
    # callers with unverified block maps; the guard stays fail-closed.)
    cid_a = cid_for_dag_cbor(encode_dag_cbor({"mark": "a"}))
    cid_b = cid_for_dag_cbor(encode_dag_cbor({"mark": "b"}))
    node_a = _mst_node([], left=cid_b)
    node_b = _mst_node([], left=cid_a)
    root2 = _mst_node([(key_hi, value_hi)], left=cid_a)
    with pytest.raises(ProofError):
        mst_lookup(
            {"root": root2, cid_a: node_a, cid_b: node_b},
            "root",
            key_lo,
        )


def test_real_car_with_empty_intermediate_verifies() -> None:
    """The retained X7 -05 submit CAR is a valid proof (golden regression).

    These are the exact bytes the governed exercise fetched from the participant
    repository's production PDS; the proof path crosses an empty
    intermediate MST node.
    """
    from communitywatch.repoproof import extract_verification_key, verify_record_proof

    fixture_dir = (
        Path(__file__).resolve().parent.parent / "fixtures" / "mst-empty-intermediate"
    )
    if not (fixture_dir / "submit.car").exists():
        pytest.skip("real-repository fixture is kept out of the public source cut")
    document = json.loads((fixture_dir / "did_doc.json").read_text(encoding="utf-8"))
    proof = verify_record_proof(
        (fixture_dir / "submit.car").read_bytes(),
        repo_did=document["id"],
        # Exact historical signed bytes; generic proof is independent of the
        # current collection allowlist. This grants no legacy runtime support.
        collection="zone.neutral.community.submit",
        rkey="a5nxtzzzzf4at",
        public_key=extract_verification_key(document),
    )
    assert proof.present
    assert (
        proof.record_cid
        == "bafyreidvckx7igbqw4wijkukcsu6ghvohskybvwxlvop6nkm277zbhyoci"
    )
    assert proof.commit.rev == "3mt3qdt3cr62r"


def test_secp256k1_openssl_known_answer() -> None:
    """Vectors minted with OpenSSL 3.0 (secp256k1, SHA-256, low-S compact)."""

    from communitywatch.secp256k1 import verify_signature

    public = bytes.fromhex(
        "02166c0aec7b54642b2cc5d5b05331fc9ad1fc23ee7a89458a086abea23f5c602e"
    )
    digest_one = bytes.fromhex(
        "28fb6adc6506c20ab405c810f5cc06c22e6e964b66547ac528fe821c31b0ea6f"
    )
    sig_one = bytes.fromhex(
        "f257c3af718fc616e17c9df6374c543d36ddf2b0133fcea5170f2e8a97beb012"
        "32033de8d1b2c189478d1063a81d0135cd3589eab07d6a6c85d00296bbea422e"
    )
    digest_two = bytes.fromhex(
        "3c51af299e705b097a009b1bfc658d26b9fbccf1eb9a542e9ea1f3b961395561"
    )
    sig_two = bytes.fromhex(
        "e6b7cc082580eac71ff728f6a2895079187d595c618ec648477fbdd57991e5ca"
        "26bc1d6a466ae7ee0dfa69cb0f2e94fbf90e69695ee792ac6086c7acc5ef21eb"
    )
    assert verify_signature(public, digest_one, sig_one)
    assert verify_signature(public, digest_two, sig_two)
    assert not verify_signature(public, digest_one, sig_two)
    assert not verify_signature(public, digest_two, sig_one)
    order = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
    high_s = sig_one[:32] + (order - int.from_bytes(sig_one[32:], "big")).to_bytes(
        32, "big"
    )
    assert not verify_signature(public, digest_one, high_s)
    assert not verify_signature(public, digest_one, sig_one[:63])
    assert not verify_signature(b"\x02" + b"\x00" * 32, digest_one, sig_one)


# --- Jetstream v2 source adapter ----------------------------------------------


def _event(seq: int, **fields: object) -> dict[str, object]:
    """One v2 ``subscribeEvents#commit`` message envelope."""

    payload = {
        "$type": "network.bsky.jetstream.subscribeEvents#commit",
        "did": AUTHOR_DID,
        "seq": seq,
        "time": "2026-08-14T09:59:59Z",
        **fields,
    }
    return {"$type": "message", "payload": payload}


def _payload_event(seq: int, payload_type: str, **fields: object) -> dict[str, object]:
    """One v2 message envelope with a non-commit payload type."""

    payload = {"$type": payload_type, "did": AUTHOR_DID, "seq": seq, **fields}
    return {"$type": "message", "payload": payload}


def test_jetstream_source_filters_and_quarantines() -> None:
    tick = {"value": 0}

    def _now() -> datetime:
        tick["value"] += 1
        return datetime(2026, 8, 14, 10, 0, tick["value"], tzinfo=UTC)

    v1_flat_message = {
        "kind": "commit",
        "time_us": 1755180000000000,
        "commit": {"rev": mint_tid(9), "operation": "create"},
    }
    events: list[dict[str, object] | bytes] = [
        _payload_event(1, "network.bsky.jetstream.subscribeEvents#identity"),
        _event(
            2,
            rev=mint_tid(1),
            operation="create",
            collection="app.bsky.feed.like",
            rkey="abc",
        ),
        _event(
            3,
            rev=mint_tid(2),
            operation="create",
            collection=SUBMISSION_COLLECTION,
            rkey=SUBMISSION_RKEY,
            cid="bafyreih2es6k3smmr67fqu6gc2mv7qvf5ge6bf6uzvkye6pbkfu2qgu6ze",
            record={"$type": SUBMISSION_COLLECTION},
        ),
        b"this is not json",
        _event(
            5,
            operation="create",
            collection=SUBMISSION_COLLECTION,
            rkey=SUBMISSION_RKEY,
        ),
        # The frozen v1 wire (flat kind/commit, time_us) must not be
        # silently accepted: it is unrecognized input and quarantines.
        v1_flat_message,
    ]
    server = FakeJetstreamServer(events)
    server.start()
    try:
        source = JetstreamEventSource(
            server.url, source_name=SOURCE, receive_timeout=2.0, now=_now
        )
        batch = source.read(None)
    finally:
        server.stop()
    assert len(batch.items) == 4
    claim = batch.items[0]
    assert claim.cursor == "3"
    assert claim.verification_outcome.value == "unverified"
    envelope = dict(claim.raw_envelope)  # type: ignore[arg-type]
    assert envelope["repo"] == AUTHOR_DID
    assert envelope["rev"] == mint_tid(2)
    assert envelope["operation"] == "create"
    assert claim.source_event_time == datetime(2026, 8, 14, 9, 59, 59, tzinfo=UTC)
    assert batch.items[1].cursor.startswith("unsequenced-")
    assert isinstance(batch.items[1].raw_envelope, bytes)
    assert batch.items[2].cursor == "5"
    assert isinstance(batch.items[2].raw_envelope, bytes)
    # The v1-shaped message quarantines as raw bytes, never as an event.
    assert batch.items[3].cursor.startswith("unsequenced-")
    assert isinstance(batch.items[3].raw_envelope, bytes)
    assert json.loads(batch.items[3].raw_envelope) == v1_flat_message

    path = server.request_paths[0]
    assert path.startswith("/xrpc/network.bsky.jetstream.subscribeEvents?")
    query = path.split("?", 1)[1]
    assert query.count("collections=") == len(COMMUNITY_COLLECTIONS)
    assert "kinds=commit" in query
    assert "cursor=" not in query


def test_jetstream_source_resume_cursor_and_wanted_dids() -> None:
    events: list[dict[str, object] | bytes] = [
        _event(
            7,
            rev=mint_tid(1),
            operation="create",
            collection=SUBMISSION_COLLECTION,
            rkey=SUBMISSION_RKEY,
        ),
        _event(
            8,
            did=COMMUNITY_DID,
            rev=mint_tid(2),
            operation="create",
            collection=ADMISSION_COLLECTION,
            rkey="admit-x",
        ),
    ]
    server = FakeJetstreamServer(events)
    server.start()
    try:
        source = JetstreamEventSource(
            server.url,
            wanted_dids=(COMMUNITY_DID,),
            source_name=SOURCE,
            receive_timeout=2.0,
        )
        batch = source.read("6%resync%3jzfcijpj2z2q")
    finally:
        server.stop()
    # The author submission is outside wanted_dids and skipped; resume
    # started one past the base sequence of the resync-suffixed cursor.
    assert [item.cursor for item in batch.items] == ["8"]
    query = server.request_paths[0].split("?", 1)[1]
    assert "cursor=7" in query
    assert "dids=did%3Aplc%3Acommunity" in query


# --- verify-at-ingest (OQ-2 answer A) ------------------------------------------


def test_create_claim_verified_at_exact_revision(world, tmp_path: Path) -> None:
    author, _, server = world
    verifier = _verifier(server)
    delivery = _claim(
        AUTHOR_DID,
        author.current_rev,
        "create",
        SUBMISSION_COLLECTION,
        SUBMISSION_RKEY,
        cursor="11",
        cid=author.record_cid(SUBMISSION_COLLECTION, SUBMISSION_RKEY),
        record=dict(author.records[(SUBMISSION_COLLECTION, SUBMISSION_RKEY)]),
    )
    (verified,) = verifier.verify_delivery(delivery)
    assert verified.verification_outcome.value == "verified"
    assert verified.verification_method == METHOD_REPO_PROOF
    assert verified.cursor == "11"
    assert verified.evidence_hash == sha256_digest(
        author.record_car(SUBMISSION_COLLECTION, SUBMISSION_RKEY)
    )
    assert verified.evidence_ref is not None
    assert "getRecord" in verified.evidence_ref
    envelope = dict(verified.raw_envelope)  # type: ignore[arg-type]
    assert envelope["rev"] == author.current_rev
    assert envelope["commitCid"]
    assert envelope["recordBytesHex"]

    store = _store(tmp_path)
    result = store.ingest(verified)
    assert result.kind == "event"
    with store.read_connection() as connection:
        row = connection.execute(
            "SELECT verification_outcome, payload_hash_scope, evidence_hash,"
            " commit_rev FROM event_receipts JOIN repo_events USING(event_variant_key)"
        ).fetchone()
    assert row["verification_outcome"] == "verified"
    assert row["payload_hash_scope"] == "dag_cbor"
    assert row["evidence_hash"] == verified.evidence_hash
    assert row["commit_rev"] == author.current_rev


def test_later_revision_records_distinction_and_resyncs(world, tmp_path: Path) -> None:
    """OQ-2 qualification: a later proof never authenticates the event."""

    author, community, server = world
    admission_cid = community.record_cid(ADMISSION_COLLECTION, _admission_rkey(author))
    claimed_rev = community.current_rev
    # A second commit lands before the proof fetch: the head advances.
    community.put(
        PROFILE_COLLECTION,
        "self",
        {
            "$type": PROFILE_COLLECTION,
            "displayName": "Homelab Two",
            "createdAt": "2026-08-13T11:05:00Z",
        },
    )
    head_rev = community.current_rev
    verifier = _verifier(server)
    delivery = _claim(
        COMMUNITY_DID,
        claimed_rev,
        "create",
        ADMISSION_COLLECTION,
        _admission_rkey(author),
        cursor="12",
        cid=admission_cid,
        record={
            "$type": ADMISSION_COLLECTION,
            "submission": _submission_ref(author),
            "subject": _post_ref(author),
            "actor": ADMIN_DID,
            "createdAt": "2026-08-13T12:02:00Z",
        },
    )
    historical, resync = verifier.verify_delivery(delivery)
    assert historical.verification_outcome.value == "unverified"
    assert historical.verification_method == METHOD_REPO_PROOF
    assert historical.evidence_hash == resync.evidence_hash
    assert resync.verification_outcome.value == "verified"
    assert resync.verification_method == METHOD_REPO_RESYNC
    assert resync.cursor == f"12%resync%{head_rev}"
    envelope = dict(resync.raw_envelope)  # type: ignore[arg-type]
    assert envelope["rev"] == head_rev
    assert envelope["operation"] == "create"
    assert envelope["cid"] == admission_cid

    store = _store(tmp_path)
    store.ingest_batch((historical, resync))
    snapshot = store.projection_snapshot()
    findings = {row["reason_code"] for row in snapshot["projection_findings"]}
    assert "authenticity_unverified" in findings
    assert "authority_record_mutated" not in findings
    ledger = {
        row["operation"]: row["outcome"]
        for row in snapshot["ledger_records"]
        if row["kind"] == "admission"
    }
    assert ledger == {"create": "valid"}
    current = next(
        row
        for row in snapshot["records_current"]
        if row["record_uri"].endswith(_admission_rkey(author))
    )
    assert current["repo_order"] == head_rev


def test_forged_update_claim_cannot_convict_authority_record(
    world, tmp_path: Path
) -> None:
    """A state proof attests presence, never the claimed operation."""

    author, community, server = world
    admission_cid = community.record_cid(ADMISSION_COLLECTION, _admission_rkey(author))
    verifier = _verifier(server)
    forged = _claim(
        COMMUNITY_DID,
        community.current_rev,
        "update",
        ADMISSION_COLLECTION,
        _admission_rkey(author),
        cursor="13",
        cid=admission_cid,
        record=dict(community.records[(ADMISSION_COLLECTION, _admission_rkey(author))]),
    )
    historical, resync = verifier.verify_delivery(forged)
    assert historical.verification_outcome.value == "unverified"
    assert resync.verification_outcome.value == "verified"
    assert dict(resync.raw_envelope)["operation"] == "create"  # type: ignore[arg-type]

    store = _store(tmp_path)
    real_create = _claim(
        COMMUNITY_DID,
        community.current_rev,
        "create",
        ADMISSION_COLLECTION,
        _admission_rkey(author),
        cursor="14",
        cid=admission_cid,
        record={
            "$type": ADMISSION_COLLECTION,
            "submission": _submission_ref(author),
            "subject": _post_ref(author),
            "actor": ADMIN_DID,
            "createdAt": "2026-08-13T12:02:00Z",
        },
    )
    (verified_create,) = verifier.verify_delivery(real_create)
    store.ingest_batch((historical, resync))
    store.ingest(verified_create)
    snapshot = store.projection_snapshot()
    findings = {row["reason_code"] for row in snapshot["projection_findings"]}
    assert "authority_record_mutated" not in findings
    admissions = [
        row
        for row in snapshot["ledger_records"]
        if row["kind"] == "admission" and row["outcome"] == "valid"
    ]
    assert len(admissions) == 1


def test_contradicted_claim_fails_and_resyncs_current_state(
    world, tmp_path: Path
) -> None:
    author, community, server = world
    verifier = _verifier(server)
    wrong_cid = community.record_cid(PROFILE_COLLECTION, "self")
    delivery = _claim(
        COMMUNITY_DID,
        community.current_rev,
        "create",
        ADMISSION_COLLECTION,
        _admission_rkey(author),
        cursor="15",
        cid=wrong_cid,
        record=dict(community.records[(ADMISSION_COLLECTION, _admission_rkey(author))]),
    )
    historical, resync = verifier.verify_delivery(delivery)
    assert historical.verification_outcome.value == "failed"
    assert resync.verification_outcome.value == "verified"
    envelope = dict(resync.raw_envelope)  # type: ignore[arg-type]
    assert envelope["cid"] == community.record_cid(
        ADMISSION_COLLECTION, _admission_rkey(author)
    )

    store = _store(tmp_path)
    store.ingest_batch((historical, resync))
    snapshot = store.projection_snapshot()
    findings = {row["reason_code"] for row in snapshot["projection_findings"]}
    assert "authenticity_failed" in findings


def test_bad_commit_signature_fails_closed(world) -> None:
    author, _, _ = world
    server = FakeAtprotoServer({AUTHOR_DID: author}, sign_with={AUTHOR_DID: 0xBAD5})
    server.start()
    try:
        verifier = _verifier(server)
        delivery = _claim(
            AUTHOR_DID,
            author.current_rev,
            "create",
            SUBMISSION_COLLECTION,
            SUBMISSION_RKEY,
            cursor="16",
            cid=author.record_cid(SUBMISSION_COLLECTION, SUBMISSION_RKEY),
        )
        (failed,) = verifier.verify_delivery(delivery)
    finally:
        server.stop()
    assert failed.verification_outcome.value == "failed"
    assert failed.verification_method == METHOD_REPO_PROOF
    # The bad proof CAR is still retained as hashed evidence.
    assert failed.evidence_hash is not None


def test_unreachable_pds_stays_unverified(world) -> None:
    author, _, server = world
    server.stop()
    http = UrllibHttpGetter(timeout_seconds=1.0)
    verifier = VerifyingEventSource(
        FakeEventSource(()),
        DidResolver(http, plc_url=server.url),
        PdsClient(http),
    )
    delivery = _claim(
        AUTHOR_DID,
        author.current_rev,
        "create",
        SUBMISSION_COLLECTION,
        SUBMISSION_RKEY,
        cursor="17",
        cid=author.record_cid(SUBMISSION_COLLECTION, SUBMISSION_RKEY),
    )
    (unverified,) = verifier.verify_delivery(delivery)
    assert unverified.verification_outcome.value == "unverified"
    assert unverified.evidence_hash is None


def test_delete_verified_through_repo_non_membership(world, tmp_path: Path) -> None:
    author, _, server = world
    deleted_rev = author.delete(SUBMISSION_COLLECTION, SUBMISSION_RKEY)
    verifier = _verifier(server)
    delivery = _claim(
        AUTHOR_DID,
        deleted_rev,
        "delete",
        SUBMISSION_COLLECTION,
        SUBMISSION_RKEY,
        cursor="18",
    )
    (verified,) = verifier.verify_delivery(delivery)
    assert verified.verification_outcome.value == "verified"
    envelope = dict(verified.raw_envelope)  # type: ignore[arg-type]
    assert envelope["operation"] == "delete"
    assert envelope["rev"] == deleted_rev

    store = _store(tmp_path)
    store.ingest(verified)
    with store.read_connection() as connection:
        row = connection.execute(
            "SELECT payload_hash_scope, record_cid FROM repo_events"
        ).fetchone()
    assert row["payload_hash_scope"] == "delete_envelope_v0"
    assert row["record_cid"] is None


def test_later_revision_delete_resyncs_as_absence(world) -> None:
    author, _, server = world
    deleted_rev = author.delete(SUBMISSION_COLLECTION, SUBMISSION_RKEY)
    author.put(POST_COLLECTION, "3jzfcijpj2z2c", _post_record())
    verifier = _verifier(server)
    delivery = _claim(
        AUTHOR_DID,
        deleted_rev,
        "delete",
        SUBMISSION_COLLECTION,
        SUBMISSION_RKEY,
        cursor="19",
    )
    historical, resync = verifier.verify_delivery(delivery)
    assert historical.verification_outcome.value == "unverified"
    assert resync.verification_outcome.value == "verified"
    assert resync.cursor == f"19%resync%{author.current_rev}"
    assert dict(resync.raw_envelope)["operation"] == "delete"  # type: ignore[arg-type]


# --- verified subject resolution ----------------------------------------------


def test_verified_subject_resolver_exact_mismatch_missing_error(world) -> None:
    author, _, server = world
    resolver = _resolver(server)
    ref = RecordRef(**_post_ref(author))
    exact = resolver.resolve_exact(ref)
    assert exact.status.value == "exact"
    assert exact.verification_outcome.value == "verified"
    assert exact.trust_mode.value == "verify_repo"
    assert exact.resolution_method == METHOD_REPO_PROOF
    assert exact.evidence_hash is not None
    assert exact.record is not None

    author.put(POST_COLLECTION, POST_RKEY, {**_post_record(), "text": "edited"})
    mismatch = resolver.resolve_exact(ref)
    assert mismatch.status.value == "mismatch"
    assert mismatch.verification_outcome.value == "verified"
    assert mismatch.current_cid != ref.cid

    author.delete(POST_COLLECTION, POST_RKEY)
    missing = resolver.resolve_exact(ref)
    assert missing.status.value == "missing"
    assert missing.verification_outcome.value == "verified"

    server.stop()
    http = UrllibHttpGetter(timeout_seconds=1.0)
    down = VerifiedSubjectResolver(
        DidResolver(http, plc_url=server.url), PdsClient(http)
    )
    errored = down.resolve_exact(ref)
    assert errored.status.value == "error"
    assert errored.verification_outcome.value == "unverified"
    assert errored.evidence_hash is None


def test_resolver_provenance_persists_without_relabeling(world, tmp_path: Path) -> None:
    author, _, server = world
    resolver = _resolver(server)
    store = _store(tmp_path)
    ref = RecordRef(**_post_ref(author))
    result = resolver.resolve_exact(ref)
    key = store.record_subject_observation(result)
    with store.read_connection() as connection:
        row = connection.execute(
            "SELECT trust_mode, verification_outcome, resolution_method,"
            " resolver_version, evidence_ref, evidence_hash"
            " FROM subject_observations WHERE observation_key = ?",
            (key,),
        ).fetchone()
    assert row["trust_mode"] == "verify_repo"
    assert row["verification_outcome"] == "verified"
    assert row["resolution_method"] == METHOD_REPO_PROOF
    assert row["evidence_hash"] == result.evidence_hash


# --- runner: durable cursor, heartbeats, end to end ----------------------------


def _runner(
    tmp_path: Path, server: FakeAtprotoServer, stream_url: str
) -> tuple[ObserverStore, ObserverRunner]:
    store = _store(tmp_path)
    http = UrllibHttpGetter(timeout_seconds=5.0)
    did_resolver = DidResolver(http, plc_url=server.url)
    pds = PdsClient(http)
    source = JetstreamEventSource(stream_url, source_name=SOURCE, receive_timeout=2.0)
    verifying = VerifyingEventSource(source, did_resolver, pds)
    runner = ObserverRunner(
        store=store,
        event_source=verifying,
        source_name=SOURCE,
        resolver=VerifiedSubjectResolver(did_resolver, pds),
        subject_refresh_seconds=0,
    )
    return store, runner


def test_runner_end_to_end_with_loopback_stream(tmp_path: Path) -> None:
    author = _author_repo()
    _submit(author)
    community = _community_repo(author)
    pds = FakeAtprotoServer({AUTHOR_DID: author, COMMUNITY_DID: community})
    events: list[dict[str, object] | bytes] = [
        _event(
            1,
            rev=author.current_rev,
            operation="create",
            collection=SUBMISSION_COLLECTION,
            rkey=SUBMISSION_RKEY,
            cid=author.record_cid(SUBMISSION_COLLECTION, SUBMISSION_RKEY),
            record=dict(author.records[(SUBMISSION_COLLECTION, SUBMISSION_RKEY)]),
        ),
        _event(
            2,
            did=COMMUNITY_DID,
            rev=community.current_rev,
            operation="create",
            collection=ADMISSION_COLLECTION,
            rkey=_admission_rkey(author),
            cid=community.record_cid(ADMISSION_COLLECTION, _admission_rkey(author)),
            record=dict(
                community.records[(ADMISSION_COLLECTION, _admission_rkey(author))]
            ),
        ),
    ]
    stream = FakeJetstreamServer(events)
    pds.start()
    stream.start()
    try:
        store, runner = _runner(tmp_path, pds, stream.url)
        assert runner.run_ingest_once() == 2
        assert store.source_cursor(SOURCE) == "2"

        query = ProjectionQuery(store, slug="homelab")
        state = query.projection_state()
        assert state.last_ingest_at is not None
        assert [source.name for source in state.sources] == [SOURCE]
        assert state.sources[0].committed_cursor == "2"
        assert state.sources[0].matches

        # The admission is pending until the admission-triggered subject
        # check runs through the verified resolver.
        assert query.list_visible(COMMUNITY_DID, 50, None).items == ()
        assert runner.run_resolve_once() == 1
        assert query.projection_state().last_resolve_at is not None
        page = query.list_visible(COMMUNITY_DID, 50, None)
        assert len(page.items) == 1
        entry = dict(page.items[0])
        assert entry["subject"]["uri"] == _post_ref(author)["uri"]
        assert entry["post"]["text"] == "hello homelab"

        # Deleting the post on the author's repo hides it on refresh,
        # verified through getRepo non-membership; nothing mutates the
        # author's repository from either side.
        author.delete(POST_COLLECTION, POST_RKEY)
        assert runner.run_resolve_once() == 1
        assert query.list_visible(COMMUNITY_DID, 50, None).items == ()
        lifecycle = store.projection_snapshot()["admission_lifecycles"][0]
        assert lifecycle["status"] == "subject_deleted"

        # Replay from the committed cursor: no duplicate application.
        assert runner.run_ingest_once() == 0
        assert store.counts()["event_receipts"] == 2
    finally:
        stream.stop()
        pds.stop()


def test_runner_records_source_errors(tmp_path: Path) -> None:
    store = _store(tmp_path)

    class Down:
        def read(self, after_cursor: str | None) -> object:
            from community_model import PortUnavailableError

            raise PortUnavailableError("relay down")

    runner = ObserverRunner(store=store, event_source=Down(), source_name=SOURCE)
    delivery = _claim(
        AUTHOR_DID,
        mint_tid(1),
        "create",
        SUBMISSION_COLLECTION,
        SUBMISSION_RKEY,
        cursor="1",
        cid="bafyreih2es6k3smmr67fqu6gc2mv7qvf5ge6bf6uzvkye6pbkfu2qgu6ze",
    )
    store.ingest(delivery)  # creates the source row with its cursor
    assert runner.run_ingest_once() == 0
    with store.read_connection() as connection:
        row = connection.execute(
            "SELECT committed_cursor, last_error FROM ingest_sources WHERE source = ?",
            (SOURCE,),
        ).fetchone()
    assert row["committed_cursor"] == "1"
    assert row["last_error"] == "PortUnavailableError"


# --- configuration strictness ---------------------------------------------------


def test_observer_config_administrator_and_credential_rejection() -> None:
    from communitywatch.config import ConfigError, parse_config

    document = {
        "community_did": COMMUNITY_DID,
        "community_slug": "homelab",
        "administrator_did": ADMIN_DID,
        "sqlite_path": "observer.sqlite3",
        "event_source_url": "wss://relay.invalid",
        "resolver_url": "https://plc.directory",
    }
    config = parse_config(document)
    assert config.administrator_did == ADMIN_DID
    assert (
        parse_config(
            {k: v for k, v in document.items() if k != "administrator_did"}
        ).administrator_did
        is None
    )
    with pytest.raises(ConfigError):
        parse_config({**document, "admin_token": "secret"})
    with pytest.raises(ConfigError):
        parse_config({**document, "writer_url": "https://pds.invalid"})
    with pytest.raises(ConfigError):
        parse_config({**document, "administrator_did": "not-a-did"})


def test_did_web_document_url_construction() -> None:
    from communitywatch.syncclient import _did_web_url

    assert (
        _did_web_url("did:web:example.com")
        == "https://example.com/.well-known/did.json"
    )
    assert (
        _did_web_url("did:web:localhost%3A8080")
        == "https://localhost:8080/.well-known/did.json"
    )
    assert (
        _did_web_url("did:web:example.com:u:alice")
        == "https://example.com/u/alice/did.json"
    )
