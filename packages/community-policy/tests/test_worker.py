from __future__ import annotations

from pathlib import Path

import pytest

from community_model import RecordRef, ValidationError
from community_policy.worker import (
    PolicyState,
    PolicyWorker,
    ReplyCandidate,
    operation_id,
)

CID1 = "bafyreidfayvfuwqa7qlnopdjiqrxzs6blmoeu4rujcjtnci5beludirz2a"
CID2 = "bafyreigoxt64qghytzkr6ik7qvtzc7lyytiq5xbbrokbxjows2wp7vmo6q"
COMMUNITY = "did:web:community.invalid"


def ref(repo: str, collection: str, rkey: str, cid: str = CID1) -> RecordRef:
    return RecordRef(f"at://{repo}/{collection}/{rkey}", cid)


def candidate() -> ReplyCandidate:
    return ReplyCandidate(
        submission=ref(
            "did:web:alice.invalid", "app.phlogiston.community.submit", "3jzfcijpj2z2a"
        ),
        subject=ref(
            "did:web:alice.invalid", "app.bsky.feed.post", "3jzfcijpj2z2b", CID2
        ),
        root_admission=ref(
            COMMUNITY, "app.phlogiston.community.admission", "admit-" + "1" * 64
        ),
        reply_policy=ref(
            COMMUNITY,
            "app.phlogiston.community.replyPolicy",
            "reply-policy-" + "2" * 64,
            CID2,
        ),
    )


class Source:
    def fetch(self, community_did: str):
        assert community_did == COMMUNITY
        return (candidate(),)


class Authority:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def send(self, request):
        self.requests.append(dict(request))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_request_is_deterministic_bounded_and_carries_no_human_identity() -> None:
    request = candidate().request()
    assert set(request) == {
        "operationId",
        "action",
        "target",
        "rootAdmission",
        "replyPolicy",
    }
    assert request["action"] == "reply_admit"
    assert "authenticatedDid" not in request
    assert request["target"] == candidate().submission.as_dict()
    assert operation_id(candidate()) == request["operationId"]
    assert len(str(request["operationId"])) < 200


def test_ambiguous_send_retries_same_operation_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "policy.sqlite3"
    first_authority = Authority([TimeoutError()])
    first = PolicyWorker(COMMUNITY, Source(), first_authority, PolicyState(path))
    assert first.run_once() == {
        "candidates": 1,
        "committed": 0,
        "refused": 0,
        "pending": 1,
    }
    operation = operation_id(candidate())
    assert first.state.state(operation) == "attempted_unknown"

    second_authority = Authority([{"ok": True, "result": {"operation": "existing"}}])
    restarted = PolicyWorker(COMMUNITY, Source(), second_authority, PolicyState(path))
    assert restarted.run_once()["committed"] == 1
    assert second_authority.requests == first_authority.requests
    assert restarted.state.state(operation) == "committed"

    no_more_calls = Authority([])
    assert (
        PolicyWorker(COMMUNITY, Source(), no_more_calls, PolicyState(path)).run_once()[
            "committed"
        ]
        == 0
    )
    assert no_more_calls.requests == []


def test_restart_retries_pending_work_while_observer_is_down(tmp_path: Path) -> None:
    path = tmp_path / "policy.sqlite3"
    PolicyWorker(
        COMMUNITY, Source(), Authority([TimeoutError()]), PolicyState(path)
    ).run_once()

    class DownSource:
        def fetch(self, community_did: str):
            raise OSError("observer down")

    authority = Authority([{"ok": True, "result": {"operation": "existing"}}])
    result = PolicyWorker(
        COMMUNITY, DownSource(), authority, PolicyState(path)
    ).run_once()
    assert result["committed"] == 1
    assert authority.requests[0]["operationId"] == operation_id(candidate())


def test_semantic_refusal_is_terminal_but_unavailability_is_retryable(
    tmp_path: Path,
) -> None:
    unavailable = Authority([{"ok": False, "error": "authority_unavailable"}])
    state = PolicyState(tmp_path / "state.sqlite3")
    assert (
        PolicyWorker(COMMUNITY, Source(), unavailable, state).run_once()["pending"] == 1
    )
    refusal = Authority([{"ok": False, "error": "reply_ancestry_invalid"}])
    assert PolicyWorker(COMMUNITY, Source(), refusal, state).run_once()["refused"] == 1
    assert state.state(operation_id(candidate())) == "refused"


def test_candidate_collection_substitution_refuses() -> None:
    with pytest.raises(ValidationError, match="candidate submission collection"):
        ReplyCandidate(
            submission=ref(
                "did:web:alice.invalid", "app.bsky.feed.like", "3jzfcijpj2z2a"
            ),
            subject=candidate().subject,
            root_admission=candidate().root_admission,
            reply_policy=candidate().reply_policy,
        )
