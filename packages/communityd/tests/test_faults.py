from __future__ import annotations

import pytest

from communityd.fakes import FakeAuthorityWriter, FakeRepoState
from communityd.faults import PostCommitFaultAuthorityWriter


def test_authority_fault_is_consumed_only_after_commit(tmp_path) -> None:
    state = FakeRepoState()
    delegate = FakeAuthorityWriter(state)
    (tmp_path / "authority.once").write_text("armed\n", encoding="utf-8")

    def terminate() -> None:
        raise RuntimeError("terminated")

    writer = PostCommitFaultAuthorityWriter(delegate, tmp_path, terminate=terminate)
    with pytest.raises(RuntimeError, match="terminated"):
        writer.create_immutable(
            "did:web:community.invalid",
            "app.phlogiston.community.test",
            "fixed",
            {"$type": "app.phlogiston.community.test"},
        )
    assert len(state.emitted) == 1
    assert (tmp_path / "authority.consumed").is_file()

    outcome = writer.create_immutable(
        "did:web:community.invalid",
        "app.phlogiston.community.test",
        "fixed",
        {"$type": "app.phlogiston.community.test"},
    )
    assert outcome.created is False
    assert len(state.emitted) == 1
