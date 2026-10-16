from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from community_model import (
    AuthorizationError,
    PortUnavailableError,
    ValidationError,
    WriteFailedError,
)
from communityd.authority_server import (
    AuthorityRequest,
    CommunityAuthorityHandler,
    PeerIdentity,
    _authorize_request,
)
from communityd.fakes import FakeAuthorityWriter, FakeRecordReader, FakeRepoState
from communityd.journal import JournalConflictError, SQLiteOperationJournal
from communityd.p0_decisions import P0DecisionStore
from fakes_support import (
    ADMIN_DID,
    ALICE_DID,
    COMMUNITY_DID,
    SUBMISSION_COLLECTION,
    make_config,
    make_ports,
    make_submission,
    seed_author_repo,
)

WEB = PeerIdentity(pid=10, uid=1001, gid=1001, role="community-web")
POLICY = PeerIdentity(pid=11, uid=1002, gid=1002, role="community-policy")


def _harness(tmp_path):
    state = FakeRepoState()
    subject, submission = seed_author_repo(state)
    pause = tmp_path / "admission.state"
    pause.write_bytes(b"open\n")
    pause.chmod(0o644)
    journal_path = tmp_path / "authority.sqlite3"
    config = replace(
        make_config(),
        operation_journal_path=str(journal_path),
        p0_profile="root_only",
        p0_admission_pause_path=str(pause),
    )
    ports = replace(
        make_ports(state), operation_journal=SQLiteOperationJournal(journal_path)
    )
    return state, subject, submission, pause, config, ports


def _handler(config, ports):
    return CommunityAuthorityHandler(
        ports=ports, reply_ledger=ports.ledger, config=config
    )


def _request(action, submission, operation_id="op", *, actor=ADMIN_DID, reason=None):
    return AuthorityRequest(
        operation_id=operation_id,
        action=action,
        authenticated_did=actor,
        target=submission,
        reason=reason,
    )


def test_p0_root_admission_is_one_record_and_status_survives_restart(tmp_path) -> None:
    state, subject, submission, _, config, ports = _harness(tmp_path)
    handler = _handler(config, ports)
    result = handler.execute(_request("root_admit", submission), WEB)
    assert set(result) == {"admission"}
    assert len(state.emitted) == 1
    assert state.emitted[0]["collection"] == "app.phlogiston.community.admission"

    restarted = _handler(
        config,
        replace(
            make_ports(state),
            operation_journal=SQLiteOperationJournal(config.operation_journal_path),
        ),
    )
    status = restarted.execute(
        _request("root_status", submission, actor=ALICE_DID), WEB
    )
    assert status["decision"] == "admitted"
    assert status["subject"] == subject.as_dict()
    assert status["admission"] == result["admission"]
    assert restarted.execute(_request("root_admit", submission, "op-2"), WEB) == result
    assert len(state.emitted) == 1


def test_undecided_status_resolves_exact_submission_once(tmp_path) -> None:
    _, subject, submission, _, config, ports = _harness(tmp_path)
    status = _handler(config, ports).execute(
        _request("root_status", submission, actor=ALICE_DID), WEB
    )
    assert status["decision"] == "none"
    assert status["subject"] == subject.as_dict()
    assert ports.reader.calls.count(("get_exact", submission.uri)) == 1


@pytest.mark.parametrize("change", ["missing", "cid_changed"])
def test_undecided_status_reports_unavailable_exact_submission(
    tmp_path, change
) -> None:
    state, subject, submission, _, config, ports = _harness(tmp_path)
    if change == "missing":
        state.drop(submission.repo_did, submission.collection, submission.rkey)
    else:
        state.move(
            submission.repo_did, submission.collection, submission.rkey, subject.cid
        )
    status = _handler(config, ports).execute(
        _request("root_status", submission, actor=ALICE_DID), WEB
    )
    assert status == {
        "decision": "submission_unavailable",
        "submission": submission.as_dict(),
        "subject": None,
        "admission": None,
        "reason": "Exact submission is no longer current or available",
        "operationId": None,
        "actorDid": None,
        "decidedAt": None,
    }
    assert ports.reader.calls.count(("get_exact", submission.uri)) == 1


def test_failed_submission_read_is_not_reported_as_unavailable(tmp_path) -> None:
    _, _, submission, _, config, ports = _harness(tmp_path)
    ports.reader.unavailable = True
    with pytest.raises(PortUnavailableError):
        _handler(config, ports).execute(
            _request("root_status", submission, actor=ALICE_DID), WEB
        )


def test_private_pending_decision_survives_source_deletion(tmp_path) -> None:
    state, _, submission, _, config, ports = _harness(tmp_path)
    ports.writer.unavailable = True
    handler = _handler(config, ports)
    with pytest.raises(WriteFailedError):
        handler.execute(_request("root_admit", submission), WEB)
    state.drop(submission.repo_did, submission.collection, submission.rkey)
    status = handler.execute(_request("root_status", submission, actor=ALICE_DID), WEB)
    assert status["decision"] == "admit_pending"
    assert status["subject"] is not None
    assert ports.operation_journal.get("op:admission").state == "attempted_unknown"


def test_private_decline_blocks_duplicate_operation_and_admission(tmp_path) -> None:
    state, subject, submission, _, config, ports = _harness(tmp_path)
    handler = _handler(config, ports)
    result = handler.execute(
        _request("root_decline", submission, reason="out of scope"), WEB
    )
    assert result["decision"] == "declined"
    assert result["subject"] == subject.as_dict()
    assert result["actorDid"] == ADMIN_DID
    assert result["decidedAt"]
    assert state.emitted == []
    with pytest.raises(JournalConflictError):
        handler.execute(_request("root_admit", submission, "op-2"), WEB)
    assert (
        handler.execute(
            _request("root_decline", submission, reason="out of scope"), WEB
        )
        == result
    )
    with pytest.raises(JournalConflictError):
        handler.execute(_request("root_decline", submission, reason="different"), WEB)
    duplicate = state.seed(
        ALICE_DID, SUBMISSION_COLLECTION, "3jzfcijpj2z2c", make_submission(subject)
    )
    duplicate_status = handler.execute(
        _request("root_status", duplicate, actor=ALICE_DID), WEB
    )
    assert duplicate_status["decision"] == "declined"
    assert duplicate_status["submission"] == duplicate.as_dict()
    with pytest.raises(JournalConflictError):
        handler.execute(_request("root_admit", duplicate, "duplicate"), WEB)


def test_pause_refuses_new_admission_but_allows_status_and_removal_path(
    tmp_path,
) -> None:
    state, _, submission, pause, config, ports = _harness(tmp_path)
    handler = _handler(config, ports)
    pause.write_bytes(b"paused\n")
    with pytest.raises(ValidationError, match="paused"):
        handler.execute(_request("root_admit", submission), WEB)
    assert (
        handler.execute(_request("root_status", submission, actor=ALICE_DID), WEB)[
            "decision"
        ]
        == "none"
    )
    pause.write_bytes(b"invalid\n")
    with pytest.raises(ValidationError, match="invalid"):
        handler.execute(_request("root_admit", submission), WEB)
    pause.unlink()
    with pytest.raises(ValidationError, match="unavailable"):
        handler.execute(_request("root_admit", submission), WEB)
    assert state.emitted == []


def test_pause_during_source_read_refuses_fresh_dispatch(tmp_path) -> None:
    state, _, submission, pause, config, ports = _harness(tmp_path)

    class PauseDuringRead:
        def get_exact(self, ref):
            pause.write_bytes(b"paused\n")
            return ports.reader.get_exact(ref)

        def get_current(self, uri):
            return ports.reader.get_current(uri)

    handler = _handler(config, replace(ports, reader=PauseDuringRead()))
    with pytest.raises(ValidationError, match="paused"):
        handler.execute(_request("root_admit", submission), WEB)
    assert state.emitted == []
    assert ports.operation_journal.get("op:admission") is None
    assert (
        handler.execute(_request("root_status", submission), WEB)["decision"] == "none"
    )
    declined = handler.execute(
        _request("root_decline", submission, "after-pause", reason="not selected"), WEB
    )
    assert declined["decision"] == "declined"


def test_known_prewrite_refusal_releases_subject_reservation(tmp_path) -> None:
    state, subject, submission, _, config, ports = _harness(tmp_path)
    key = (subject.repo_did, subject.collection, subject.rkey)
    original = state.records.pop(key)
    handler = _handler(config, ports)
    with pytest.raises(ValidationError, match="not in its repository"):
        handler.execute(_request("root_admit", submission), WEB)
    assert state.emitted == []
    assert ports.operation_journal.get("op:admission") is None
    state.records[key] = original
    result = handler.execute(
        _request(
            "root_decline", submission, "decline-after-refusal", reason="not selected"
        ),
        WEB,
    )
    assert result["decision"] == "declined"


def test_unknown_write_blocks_decline_and_readback_remains_available_under_pause(
    tmp_path,
) -> None:
    state, _, submission, pause, config, ports = _harness(tmp_path)
    ports.writer.unavailable = True
    handler = _handler(config, ports)
    with pytest.raises(WriteFailedError):
        handler.execute(_request("root_admit", submission), WEB)
    with pytest.raises(JournalConflictError):
        handler.execute(
            _request("root_decline", submission, "decline", reason="no"), WEB
        )
    pause.write_bytes(b"paused\n")
    restarted = _handler(
        config,
        replace(
            make_ports(state),
            operation_journal=SQLiteOperationJournal(config.operation_journal_path),
        ),
    )
    assert (
        restarted.execute(_request("root_status", submission, actor=ALICE_DID), WEB)[
            "decision"
        ]
        == "admit_pending"
    )
    with pytest.raises(ValidationError, match="paused"):
        restarted.execute(_request("root_admit", submission), WEB)
    assert state.emitted == []
    pause.write_bytes(b"open\n")
    result = restarted.execute(_request("root_admit", submission), WEB)
    assert result["admission"] is not None
    assert len(state.emitted) == 1


class _CommitThenHideReadback:
    def __init__(self, state, reader):
        self.delegate = FakeAuthorityWriter(state)
        self.reader = reader

    def create_immutable(self, *args, **kwargs):
        self.delegate.create_immutable(*args, **kwargs)
        self.reader.unavailable = True
        raise PortUnavailableError("response lost after repository commit")


def test_postcommit_unknown_is_reconciled_by_status_during_pause(tmp_path) -> None:
    state, _, submission, pause, config, ports = _harness(tmp_path)
    readback = FakeRecordReader(state)
    ports = replace(
        ports,
        authority_reader=readback,
        writer=_CommitThenHideReadback(state, readback),
    )
    with pytest.raises(WriteFailedError):
        _handler(config, ports).execute(_request("root_admit", submission), WEB)
    assert len(state.emitted) == 1
    pause.write_bytes(b"paused\n")
    restarted = _handler(
        config,
        replace(
            make_ports(state),
            operation_journal=SQLiteOperationJournal(config.operation_journal_path),
        ),
    )
    status = restarted.execute(
        _request("root_status", submission, actor=ALICE_DID), WEB
    )
    assert status["decision"] == "admitted"
    assert status["admission"] is not None
    assert restarted.execute(_request("root_admit", submission), WEB) == {
        "admission": status["admission"]
    }
    assert len(state.emitted) == 1


def test_exact_subject_reservations_serialize_across_store_instances(tmp_path) -> None:
    _, subject, submission, _, _, _ = _harness(tmp_path)
    path = tmp_path / "decisions.sqlite3"
    stores = (P0DecisionStore(path), P0DecisionStore(path))

    def reserve(operation_id):
        store = stores[0] if operation_id == "first" else stores[1]
        return store.reserve(
            community_did=COMMUNITY_DID,
            author_did=ALICE_DID,
            subject=subject,
            actor_did=ADMIN_DID,
            submission=submission,
            operation_id=operation_id,
            state="admit_pending",
            decided_at="2026-10-11T00:00:00+00:00",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(reserve, operation_id) for operation_id in ("first", "second")
        ]
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result())
            except JournalConflictError:
                outcomes.append("refused")
    assert sum(item == "refused" for item in outcomes) == 1


def test_private_decision_custody_refuses_test_to_public_mode_reuse(tmp_path) -> None:
    path = tmp_path / "authority.sqlite3"
    P0DecisionStore(path, test_origin="https://juche.social")
    with pytest.raises(ValueError, match="another provider mode"):
        P0DecisionStore(path)


def test_status_requires_exact_author_or_moderator_and_p0_refuses_policy_actions(
    tmp_path,
) -> None:
    _, _, submission, _, config, ports = _harness(tmp_path)
    handler = _handler(config, ports)
    status = _request("root_status", submission, actor=ALICE_DID)
    _authorize_request(WEB, status, ADMIN_DID)
    with pytest.raises(AuthorizationError):
        _authorize_request(
            WEB, replace(status, authenticated_did="did:web:other.invalid"), ADMIN_DID
        )
    with pytest.raises(ValidationError, match="outside the P0 profile"):
        handler.execute(_request("reply_admit", submission), POLICY)
