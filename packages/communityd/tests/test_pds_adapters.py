from __future__ import annotations

import json
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path

import pytest

import communityd.pds as pds_module
from community_model import (
    ADMISSION_COLLECTION,
    MOD_ACTION_COLLECTION,
    AuthorizationError,
    CredentialUnavailableError,
    ImmutableConflictError,
    PortUnavailableError,
    RecordRef,
    UnsupportedReadmissionError,
    WriteFailedError,
    admission_rkey,
    canonical_json_bytes,
    cid_for_dag_cbor,
    removal_rkey,
)
from communityd.config import DaemonConfig
from communityd.fakepds import FakePds
from communityd.operations import DaemonPorts, LocalAdminAuthorizer, admit, remove
from communityd.pds import (
    EnvFileCredentialProvider,
    PdsAuthorityLedgerReader,
    PdsAuthorityWriter,
    PdsRecordReader,
    PdsSession,
    PdsTransport,
    SessionCredential,
)
from fakes_support import (
    ADMIN_DID,
    ALICE_DID,
    ALLOWED_UID,
    COMMUNITY_DID,
    POST_COLLECTION,
    SUBMISSION_COLLECTION,
    make_post,
    make_submission,
)

NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)
CANARY = "canary-app-password-aaaa-bbbb"
ENV_VAR = "COMMUNITYD_TEST_CREDENTIAL"
CREDENTIAL_REF = f"env:{ENV_VAR}"
BOB_DID = "did:web:bob.invalid"


def _write_credential(
    tmp_path: Path, *, password: str = CANARY, identifier: str = "community.test"
) -> Path:
    path = tmp_path / "credential.json"
    path.write_text(
        json.dumps({"identifier": identifier, "app_password": password}),
        encoding="utf-8",
    )
    return path


def _config(pds_url: str, *, allowed_uid: int = ALLOWED_UID) -> DaemonConfig:
    return DaemonConfig(
        community_did=COMMUNITY_DID,
        administrator_did=ADMIN_DID,
        community_pds_url=pds_url,
        allowed_uid=allowed_uid,
        reader_adapter="pds",
        ledger_adapter="pds",
        writer_adapter="pds",
        credential_provider="env_file",
        credential_ref=CREDENTIAL_REF,
        request_timeout_ms=2000,
        max_retries=1,
    )


def _ports(
    server: FakePds, config: DaemonConfig, *, uid: int = ALLOWED_UID
) -> DaemonPorts:
    transport = PdsTransport(
        base_url=server.url,
        timeout_seconds=config.request_timeout_ms / 1000,
        max_retries=config.max_retries,
    )
    provider = EnvFileCredentialProvider()
    session = PdsSession(
        transport,
        lambda: provider.load(config.credential_ref),
        expected_did=config.community_did,
    )
    return DaemonPorts(
        reader=PdsRecordReader(transport),
        ledger=PdsAuthorityLedgerReader(transport),
        authorizer=LocalAdminAuthorizer(
            administrator_did=config.administrator_did,
            allowed_uid=config.allowed_uid,
            uid_reader=lambda: uid,
        ),
        writer=PdsAuthorityWriter(transport, session),
        credentials=provider,
    )


@pytest.fixture
def server() -> FakePds:
    with FakePds(
        session_did=COMMUNITY_DID, identifier="community.test", app_password=CANARY
    ) as pds:
        yield pds


@pytest.fixture
def credential(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = _write_credential(tmp_path)
    monkeypatch.setenv(ENV_VAR, str(path))
    return path


def _seed_alice(pds: FakePds) -> tuple[RecordRef, RecordRef]:
    post = make_post()
    post_ref = pds.seed(ALICE_DID, POST_COLLECTION, "3jzfcijpj2z2a", post)
    submission_ref = pds.seed(
        ALICE_DID, SUBMISSION_COLLECTION, "3jzfcijpj2z2b", make_submission(post_ref)
    )
    return post_ref, submission_ref


def _seed_bob(pds: FakePds) -> RecordRef:
    post = make_post("Bob's quieter post.")
    post_ref = pds.seed(BOB_DID, POST_COLLECTION, "3jzfcijpj2z2c", post)
    return pds.seed(
        BOB_DID, SUBMISSION_COLLECTION, "3jzfcijpj2z2d", make_submission(post_ref)
    )


def test_admit_happy_path_creates_signed_payload(
    server: FakePds, credential: Path
) -> None:
    post_ref, submission_ref = _seed_alice(server)
    config = _config(server.url)

    outcome = admit(_ports(server, config), config, submission_ref, now=NOW)

    assert outcome.operation == "created"
    rkey = admission_rkey(submission_ref)
    assert outcome.record.uri == f"at://{COMMUNITY_DID}/{ADMISSION_COLLECTION}/{rkey}"
    stored = server.records[(COMMUNITY_DID, ADMISSION_COLLECTION, rkey)][1]
    assert stored["submission"] == submission_ref.as_dict()
    assert stored["subject"] == post_ref.as_dict()
    assert stored["actor"] == ADMIN_DID
    # The write carried an authenticated capability and hit the community repo.
    assert server.session_attempts == 1
    assert server.created == [(COMMUNITY_DID, ADMISSION_COLLECTION, rkey)]


def test_readmit_returns_existing_identical_reference(
    server: FakePds, credential: Path
) -> None:
    _, submission_ref = _seed_alice(server)
    config = _config(server.url)
    ports = _ports(server, config)

    first = admit(ports, config, submission_ref, now=NOW)
    second = admit(ports, config, submission_ref, now=datetime(2026, 8, 14, tzinfo=UTC))

    assert second.operation == "existing"
    assert second.record == first.record
    assert server.create_record_attempts == 1
    # The stored createdAt from the first write is unchanged on retry.
    rkey = admission_rkey(submission_ref)
    assert (
        server.records[(COMMUNITY_DID, ADMISSION_COLLECTION, rkey)][1]["createdAt"]
        == "2026-08-13T12:00:00Z"
    )


def test_admit_after_valid_removal_is_unsupported_with_pagination(
    server: FakePds, credential: Path
) -> None:
    server.page_limit = 1
    _, submission_ref = _seed_alice(server)
    bob_submission = _seed_bob(server)
    config = _config(server.url)
    ports = _ports(server, config)

    admission = admit(ports, config, submission_ref, now=NOW)
    admit(ports, config, bob_submission, now=NOW)
    remove(ports, config, admission.record, "off-topic", now=NOW)

    server.requests.clear()
    with pytest.raises(UnsupportedReadmissionError):
        admit(ports, config, submission_ref, now=NOW)

    list_calls = [r for r in server.requests if "listRecords" in r]
    # Two authority collections, at least one paginated beyond one page.
    assert len(list_calls) >= 3
    # Only public/authenticated PDS XRPC paths were touched; no observer paths.
    assert all(
        r.split(" ")[1].startswith("/xrpc/com.atproto.") for r in server.requests
    )


def test_remove_allowed_when_subject_post_is_stale_or_missing(
    server: FakePds, credential: Path
) -> None:
    _, submission_ref = _seed_alice(server)
    config = _config(server.url)
    ports = _ports(server, config)
    admission = admit(ports, config, submission_ref, now=NOW)

    server.drop(ALICE_DID, POST_COLLECTION, "3jzfcijpj2z2a")
    outcome = remove(ports, config, admission.record, "stale content", now=NOW)

    assert outcome.operation == "created"
    assert outcome.record.collection == MOD_ACTION_COLLECTION


def _authority_gets(server: FakePds, collection: str) -> list[dict[str, str]]:
    """Decoded query params of getRecord requests against one collection."""
    found = []
    for request in server.requests:
        method, _, path = request.partition(" ")
        split = urllib.parse.urlsplit(path)
        params = dict(urllib.parse.parse_qsl(split.query))
        if (
            method == "GET"
            and split.path == "/xrpc/com.atproto.repo.getRecord"
            and params.get("collection") == collection
        ):
            found.append(params)
    return found


def test_deterministic_create_performs_one_existence_check(
    server: FakePds, credential: Path
) -> None:
    """One deterministic create costs one getRecord at its own rkey.

    The writer's existence check is the only pre-read; the operations layer
    must not re-read the same record through the reader port.
    """
    _, submission_ref = _seed_alice(server)
    config = _config(server.url)
    ports = _ports(server, config)

    admission = admit(ports, config, submission_ref, now=NOW)
    assert _authority_gets(server, ADMISSION_COLLECTION) == [
        {
            "repo": COMMUNITY_DID,
            "collection": ADMISSION_COLLECTION,
            "rkey": admission_rkey(submission_ref),
        }
    ]

    remove(ports, config, admission.record, "off-topic", now=NOW)
    assert _authority_gets(server, MOD_ACTION_COLLECTION) == [
        {
            "repo": COMMUNITY_DID,
            "collection": MOD_ACTION_COLLECTION,
            "rkey": removal_rkey(admission.record),
        }
    ]


def test_incompatible_rkey_occupant_is_hard_conflict(
    server: FakePds, credential: Path
) -> None:
    _, submission_ref = _seed_alice(server)
    config = _config(server.url)
    rkey = admission_rkey(submission_ref)
    # An occupant with identical shape but a different subject holds the rkey.
    intruder = {
        "$type": ADMISSION_COLLECTION,
        "submission": submission_ref.as_dict(),
        "subject": {
            "uri": "at://did:web:eve.invalid/app.bsky.feed.post/3jxfaaaaaaa",
            "cid": submission_ref.cid,
        },
        "actor": ADMIN_DID,
        "createdAt": "2026-08-13T11:00:00Z",
    }
    server.seed(COMMUNITY_DID, ADMISSION_COLLECTION, rkey, intruder)

    with pytest.raises(ImmutableConflictError):
        admit(_ports(server, config), config, submission_ref, now=NOW)

    assert server.create_record_attempts == 0
    assert server.records[(COMMUNITY_DID, ADMISSION_COLLECTION, rkey)][1] == intruder


def test_ambiguous_write_resolves_by_readback_without_retry(
    server: FakePds, credential: Path
) -> None:
    _, submission_ref = _seed_alice(server)
    config = _config(server.url)
    server.drop_mode = "after_commit"

    outcome = admit(_ports(server, config), config, submission_ref, now=NOW)

    assert outcome.operation == "created"
    assert outcome.record.uri.endswith(admission_rkey(submission_ref))
    assert server.create_record_attempts == 1


def test_ambiguous_write_without_commit_is_write_failed(
    server: FakePds, credential: Path
) -> None:
    _, submission_ref = _seed_alice(server)
    config = _config(server.url)
    server.drop_mode = "before_commit"

    with pytest.raises(WriteFailedError):
        admit(_ports(server, config), config, submission_ref, now=NOW)

    assert server.create_record_attempts == 1
    rkey = admission_rkey(submission_ref)
    assert (COMMUNITY_DID, ADMISSION_COLLECTION, rkey) not in server.records


def test_ambiguous_write_with_failed_readback_is_write_failed(
    server: FakePds, credential: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, submission_ref = _seed_alice(server)
    config = _config(server.url)
    server.drop_mode = "after_commit"

    # Reads behave until the commit attempt; the readback then fails too.
    original_get_record = pds_module._get_record

    def flaky_get_record(*args: object, **kwargs: object) -> object:
        if server.create_record_attempts:
            raise PortUnavailableError("readback unavailable")
        return original_get_record(*args, **kwargs)

    monkeypatch.setattr(pds_module, "_get_record", flaky_get_record)
    with pytest.raises(WriteFailedError):
        admit(_ports(server, config), config, submission_ref, now=NOW)
    assert server.create_record_attempts == 1


def test_unset_credential_env_fails_before_any_network(
    server: FakePds, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    _, submission_ref = _seed_alice(server)
    config = _config(server.url)

    with pytest.raises(CredentialUnavailableError):
        admit(_ports(server, config), config, submission_ref, now=NOW)
    assert server.requests == []


def test_missing_credential_file_fails_before_any_network(
    server: FakePds, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "absent.json"))
    _, submission_ref = _seed_alice(server)
    config = _config(server.url)

    with pytest.raises(CredentialUnavailableError):
        admit(_ports(server, config), config, submission_ref, now=NOW)
    assert server.requests == []


def test_malformed_credential_file_fails_before_any_network(
    server: FakePds, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text('{"identifier": "x", "app_password": "', encoding="utf-8")
    monkeypatch.setenv(ENV_VAR, str(broken))
    _, submission_ref = _seed_alice(server)
    config = _config(server.url)

    with pytest.raises(CredentialUnavailableError):
        admit(_ports(server, config), config, submission_ref, now=NOW)
    assert server.requests == []


def test_wrong_shape_credential_file_fails_before_any_network(
    server: FakePds, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"token": CANARY}), encoding="utf-8")
    monkeypatch.setenv(ENV_VAR, str(wrong))
    _, submission_ref = _seed_alice(server)
    config = _config(server.url)

    with pytest.raises(CredentialUnavailableError) as captured:
        admit(_ports(server, config), config, submission_ref, now=NOW)
    assert server.requests == []
    assert CANARY not in str(captured.value)


def test_uid_mismatch_performs_zero_network_io(
    server: FakePds, credential: Path
) -> None:
    _, submission_ref = _seed_alice(server)
    config = _config(server.url)

    with pytest.raises(AuthorizationError):
        admit(
            _ports(server, config, uid=ALLOWED_UID + 1), config, submission_ref, now=NOW
        )
    assert server.requests == []


def test_rejected_session_is_credential_unavailable(
    credential: Path,
) -> None:
    with FakePds(
        session_did=COMMUNITY_DID,
        identifier="community.test",
        app_password="a-different-password",
    ) as server:
        _, submission_ref = _seed_alice(server)
        config = _config(server.url)
        with pytest.raises(CredentialUnavailableError) as captured:
            admit(_ports(server, config), config, submission_ref, now=NOW)
        assert CANARY not in str(captured.value)


def test_session_for_wrong_did_is_credential_unavailable(credential: Path) -> None:
    with FakePds(
        session_did="did:web:someone-else.invalid",
        identifier="community.test",
        app_password=CANARY,
    ) as server:
        _, submission_ref = _seed_alice(server)
        config = _config(server.url)
        with pytest.raises(CredentialUnavailableError):
            admit(_ports(server, config), config, submission_ref, now=NOW)


def test_unreachable_pds_is_read_unavailable(credential: Path) -> None:
    # Nothing listens on this loopback port (the discard port).
    config = _config("http://127.0.0.1:9")
    submission = RecordRef(
        uri=f"at://{ALICE_DID}/{SUBMISSION_COLLECTION}/3jzfcijpj2z2b",
        cid=cid_for_dag_cbor(canonical_json_bytes({"x": 1})),
    )
    transport = PdsTransport(
        base_url=config.community_pds_url, timeout_seconds=1.0, max_retries=1
    )
    provider = EnvFileCredentialProvider()
    ports = DaemonPorts(
        reader=PdsRecordReader(transport),
        ledger=PdsAuthorityLedgerReader(transport),
        authorizer=LocalAdminAuthorizer(
            administrator_did=config.administrator_did,
            allowed_uid=config.allowed_uid,
            uid_reader=lambda: ALLOWED_UID,
        ),
        writer=PdsAuthorityWriter(
            transport,
            PdsSession(
                transport,
                lambda: provider.load(config.credential_ref),
                expected_did=config.community_did,
            ),
        ),
        credentials=provider,
    )
    with pytest.raises(PortUnavailableError):
        admit(ports, config, submission, now=NOW)


def test_credential_secret_never_appears_in_reprs_or_logs(
    server: FakePds, credential: Path
) -> None:
    provider = EnvFileCredentialProvider()
    loaded = provider.load(CREDENTIAL_REF)
    assert isinstance(loaded, SessionCredential)
    assert CANARY not in repr(loaded)
    assert CANARY not in repr(provider)

    transport = PdsTransport(base_url=server.url, timeout_seconds=2.0, max_retries=0)
    session = PdsSession(transport, lambda: loaded, expected_did=COMMUNITY_DID)
    session.token()
    assert CANARY not in repr(session)
    # The server request log records request lines only, never POST bodies.
    assert all(CANARY not in entry for entry in server.requests)
    assert all(server.token not in entry for entry in server.requests)
