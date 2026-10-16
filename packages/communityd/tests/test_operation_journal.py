from __future__ import annotations

from dataclasses import replace

import pytest

from community_model import PortUnavailableError, WriteFailedError
from communityd.fakes import FakeAuthorityWriter, FakeRepoState
from communityd.faults import PostCommitFaultAuthorityWriter
from communityd.journal import JournalConflictError, SQLiteOperationJournal
from communityd.operations import admit
from fakes_support import BASE_TIME, make_config, make_ports, seed_author_repo


def test_journal_persists_all_states_and_refuses_terminal_change(tmp_path) -> None:
    journal = SQLiteOperationJournal(tmp_path / "private" / "authority.sqlite3")
    record = {"$type": "app.phlogiston.community.test", "value": "one"}
    entry = journal.prepare(
        operation_id="op-1",
        action="root_admit",
        repo_did="did:web:community.invalid",
        collection="app.phlogiston.community.test",
        rkey="fixed",
        intended_record=record,
    )
    assert entry.state == "prepared"
    assert (tmp_path / "private").stat().st_mode & 0o777 == 0o700
    assert journal.path.stat().st_mode & 0o777 == 0o600

    SQLiteOperationJournal(journal.path).transition("op-1", "attempted_unknown")
    restarted = SQLiteOperationJournal(journal.path)
    assert restarted.get("op-1").state == "attempted_unknown"  # type: ignore[union-attr]
    restarted.transition("op-1", "refused", refusal_code="root_closed")
    with pytest.raises(JournalConflictError):
        restarted.transition("op-1", "committed")


def test_operation_id_and_rkey_cannot_be_rebound(tmp_path) -> None:
    journal = SQLiteOperationJournal(tmp_path / "authority.sqlite3")
    arguments = dict(
        action="reply_admit",
        repo_did="did:web:community.invalid",
        collection="app.phlogiston.community.replyAdmission",
        rkey="fixed",
        intended_record={"value": "one"},
    )
    journal.prepare(operation_id="op-1", **arguments)
    with pytest.raises(JournalConflictError):
        journal.prepare(
            operation_id="op-1", **{**arguments, "intended_record": {"value": "two"}}
        )
    with pytest.raises(JournalConflictError):
        journal.prepare(operation_id="op-2", **arguments)


class _CommitThenLoseResponse:
    def __init__(self, delegate: FakeAuthorityWriter) -> None:
        self.delegate = delegate
        self.calls = 0

    def create_immutable(self, *args, **kwargs):
        self.calls += 1
        self.delegate.create_immutable(*args, **kwargs)
        raise PortUnavailableError("response lost after commit")


def test_lost_write_response_is_reconciled_without_duplicate_after_restart(
    tmp_path,
) -> None:
    state = FakeRepoState()
    _, submission = seed_author_repo(state)
    base = make_ports(state)
    writer = _CommitThenLoseResponse(FakeAuthorityWriter(state))
    path = tmp_path / "authority.sqlite3"
    first_ports = replace(
        base, writer=writer, operation_journal=SQLiteOperationJournal(path)
    )

    outcome = admit(
        first_ports,
        make_config(),
        submission,
        now=BASE_TIME,
        operation_id="browser-op-1",
    )
    assert outcome.operation == "created"
    assert writer.calls == 1
    assert SQLiteOperationJournal(path).get("browser-op-1").state == "committed"  # type: ignore[union-attr]

    restarted = replace(
        make_ports(state), operation_journal=SQLiteOperationJournal(path)
    )
    repeated = admit(
        restarted,
        make_config(),
        submission,
        now=BASE_TIME,
        operation_id="browser-op-1",
    )
    assert repeated.operation == "existing"
    assert restarted.writer.calls == []
    assert len(state.emitted) == 1


def test_unknown_outcome_without_readback_remains_pending(tmp_path) -> None:
    state = FakeRepoState()
    _, submission = seed_author_repo(state)
    ports = make_ports(state)
    ports.writer.unavailable = True
    journal = SQLiteOperationJournal(tmp_path / "authority.sqlite3")
    ports = replace(ports, operation_journal=journal)

    with pytest.raises(WriteFailedError, match="ambiguous"):
        admit(
            ports,
            make_config(),
            submission,
            now=BASE_TIME,
            operation_id="pending-op",
        )
    assert journal.get("pending-op").state == "attempted_unknown"  # type: ignore[union-attr]

    # Restart with a healthy writer: direct readback establishes absence,
    # permits one controlled attempt, and commits under the same operation id.
    restarted = replace(
        make_ports(state), operation_journal=SQLiteOperationJournal(journal.path)
    )
    recovered = admit(
        restarted,
        make_config(),
        submission,
        now=BASE_TIME,
        operation_id="pending-op",
    )
    assert recovered.operation == "created"
    assert len(restarted.writer.calls) == 1
    assert journal.get("pending-op").state == "committed"  # type: ignore[union-attr]


def test_abrupt_post_commit_stop_leaves_reconcilable_journal(tmp_path) -> None:
    state = FakeRepoState()
    _, submission = seed_author_repo(state)
    path = tmp_path / "authority.sqlite3"
    fault_dir = tmp_path / "faults"
    fault_dir.mkdir()
    (fault_dir / "authority.once").write_text("armed\n", encoding="utf-8")

    def terminate() -> None:
        raise RuntimeError("simulated abrupt stop")

    base = make_ports(state)
    first_ports = replace(
        base,
        writer=PostCommitFaultAuthorityWriter(
            FakeAuthorityWriter(state), fault_dir, terminate=terminate
        ),
        operation_journal=SQLiteOperationJournal(path),
    )
    with pytest.raises(RuntimeError, match="abrupt stop"):
        admit(
            first_ports,
            make_config(),
            submission,
            now=BASE_TIME,
            operation_id="crashed-op",
        )
    assert SQLiteOperationJournal(path).get("crashed-op").state == "attempted_unknown"  # type: ignore[union-attr]

    restarted = replace(
        make_ports(state), operation_journal=SQLiteOperationJournal(path)
    )
    recovered = admit(
        restarted,
        make_config(),
        submission,
        now=BASE_TIME,
        operation_id="crashed-op",
    )
    assert recovered.operation == "created"
    assert restarted.writer.calls == []
    assert len(state.emitted) == 1
