from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from community_model import (
    REPLY_ACTION_COLLECTION,
    REPLY_ADMISSION_COLLECTION,
    REPLY_POLICY_COLLECTION,
    RecordRef,
    ReplyActionRecord,
    ReplyModerationState,
    ValidationError,
    reply_admission_rkey,
    reply_moderation_key,
)
from communityd.fakes import FakeRepoState
from communityd.operations import admit, remove
from communityd.reply_operations import (
    admit_reply,
    create_reply_policy,
    moderate_reply,
)
from fakes_support import (
    ALICE_DID,
    BASE_TIME,
    COMMUNITY_DID,
    POST_COLLECTION,
    SUBMISSION_COLLECTION,
    make_config,
    make_ports,
    seed_author_repo,
)


@dataclass
class ReplyLedger:
    eligible: set[str] = field(default_factory=set)
    states: dict[str, ReplyModerationState] = field(default_factory=dict)

    def eligible_reply_uris(self, community_did, discussion):
        assert community_did == COMMUNITY_DID
        return frozenset(self.eligible)

    def moderation_state(self, community_did, moderation_key):
        assert community_did == COMMUNITY_DID
        return self.states.get(moderation_key)


def _discussion(state: FakeRepoState):
    root, root_submission = seed_author_repo(state)
    ports = make_ports(state)
    admission = admit(ports, make_config(), root_submission, now=BASE_TIME).record
    policy = create_reply_policy(
        ports,
        make_config(),
        admission,
        now=BASE_TIME,
        operation_id="policy-1",
    ).record
    assert policy.collection == REPLY_POLICY_COLLECTION
    return ports, root, admission, policy


def _reply_submission(
    state: FakeRepoState,
    root: RecordRef,
    discussion: RecordRef,
    *,
    reply_rkey: str,
    submit_rkey: str,
    parent: RecordRef | None = None,
    text: str = "A useful answer",
) -> tuple[RecordRef, RecordRef]:
    reply = {
        "$type": POST_COLLECTION,
        "text": text,
        "reply": {
            "root": root.as_dict(),
            "parent": (parent or root).as_dict(),
        },
        "createdAt": "2026-08-13T12:01:00Z",
    }
    reply_ref = state.seed(ALICE_DID, POST_COLLECTION, reply_rkey, reply)
    submission = {
        "$type": SUBMISSION_COLLECTION,
        "community": COMMUNITY_DID,
        "subject": reply_ref.as_dict(),
        "discussion": discussion.as_dict(),
        "createdAt": "2026-08-13T12:01:01Z",
    }
    submission_ref = state.seed(
        ALICE_DID, SUBMISSION_COLLECTION, submit_rkey, submission
    )
    return reply_ref, submission_ref


def test_policy_worker_admits_only_exact_connected_opt_in() -> None:
    state = FakeRepoState()
    ports, root, discussion, policy = _discussion(state)
    _, submission = _reply_submission(
        state,
        root,
        discussion,
        reply_rkey="3jzfcijpj2z2d",
        submit_rkey="3jzfcijpj2z2e",
    )
    outcome = admit_reply(
        ports,
        ReplyLedger(),
        make_config(),
        submission,
        discussion,
        policy,
        now=BASE_TIME,
        operation_id="reply-admit-1",
    )
    assert outcome.record.collection == REPLY_ADMISSION_COLLECTION
    assert outcome.record.rkey == reply_admission_rkey(submission)


def test_root_closure_observed_before_write_refuses_reply() -> None:
    state = FakeRepoState()
    ports, root, discussion, policy = _discussion(state)
    _, submission = _reply_submission(
        state,
        root,
        discussion,
        reply_rkey="3jzfcijpj2z2d",
        submit_rkey="3jzfcijpj2z2e",
    )
    remove(ports, make_config(), discussion, "closed", now=BASE_TIME)
    with pytest.raises(ValidationError, match="closed"):
        admit_reply(
            ports,
            ReplyLedger(),
            make_config(),
            submission,
            discussion,
            policy,
            now=BASE_TIME,
            operation_id="reply-after-close",
        )


def test_reply_admission_committed_before_closure_remains_historical() -> None:
    state = FakeRepoState()
    ports, root, discussion, policy = _discussion(state)
    _, submission = _reply_submission(
        state,
        root,
        discussion,
        reply_rkey="3jzfcijpj2z2d",
        submit_rkey="3jzfcijpj2z2e",
    )
    admitted = admit_reply(
        ports,
        ports.ledger,
        make_config(),
        submission,
        discussion,
        policy,
        now=BASE_TIME,
        operation_id="reply-before-close",
    ).record
    remove(ports, make_config(), discussion, "closed", now=BASE_TIME)
    assert (
        COMMUNITY_DID,
        REPLY_ADMISSION_COLLECTION,
        admitted.rkey,
    ) in state.records


def test_remove_edit_resubmit_new_admission_inherits_logical_tombstone() -> None:
    state = FakeRepoState()
    ports, root, discussion, policy = _discussion(state)
    ledger = ReplyLedger()
    reply, submission = _reply_submission(
        state,
        root,
        discussion,
        reply_rkey="3jzfcijpj2z2d",
        submit_rkey="3jzfcijpj2z2e",
    )
    first = admit_reply(
        ports,
        ledger,
        make_config(),
        submission,
        discussion,
        policy,
        now=BASE_TIME,
        operation_id="reply-admit-1",
    ).record
    removal = moderate_reply(
        ports,
        ledger,
        make_config(),
        first,
        "remove",
        "off topic",
        controlling_action=None,
        now=BASE_TIME,
        operation_id="reply-remove-1",
    ).record
    removal_record = ReplyActionRecord.from_record(
        dict(
            state.records[(COMMUNITY_DID, REPLY_ACTION_COLLECTION, removal.rkey)].record
        )
    )
    key = reply_moderation_key(
        community_did=COMMUNITY_DID,
        root_admission=discussion,
        reply_uri=reply.uri,
    )
    ledger.states[key] = ReplyModerationState(key, True, removal)

    edited_reply, second_submission = _reply_submission(
        state,
        root,
        discussion,
        reply_rkey=reply.rkey,
        submit_rkey="3jzfcijpj2z2f",
        text="A corrected useful answer",
    )
    assert edited_reply.uri == reply.uri and edited_reply.cid != reply.cid
    second = admit_reply(
        ports,
        ledger,
        make_config(),
        second_submission,
        discussion,
        policy,
        now=BASE_TIME,
        operation_id="reply-admit-2",
    ).record
    second_record = state.records[
        (COMMUNITY_DID, REPLY_ADMISSION_COLLECTION, second.rkey)
    ].record
    assert second_record["subject"]["cid"] == edited_reply.cid  # type: ignore[index]
    assert ledger.moderation_state(COMMUNITY_DID, key).removed is True  # type: ignore[union-attr]
    assert removal_record.moderation_key == key

    restored = moderate_reply(
        ports,
        ledger,
        make_config(),
        second,
        "restore",
        None,
        controlling_action=removal,
        now=BASE_TIME,
        operation_id="reply-restore-1",
    )
    assert restored.record.collection == REPLY_ACTION_COLLECTION
