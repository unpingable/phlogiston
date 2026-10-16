from __future__ import annotations

import pytest

from community_model import (
    ADMISSION_COLLECTION,
    MEMBER_ACTION_COLLECTION,
    MOD_ACTION_COLLECTION,
    AuthorizationError,
    CredentialUnavailableError,
    ImmutableConflictError,
    PortUnavailableError,
    RecordRef,
    UnsupportedReadmissionError,
    ValidationError,
    WriteFailedError,
    admission_rkey,
    member_action_rkey,
    removal_rkey,
)
from communityd.fakes import FakeAuthorityWriter, FakeRepoState
from communityd.operations import admit, change_membership, remove
from fakes_support import (
    ADMIN_DID,
    BASE_TIME,
    COMMUNITY_DID,
    POST_COLLECTION,
    make_config,
    make_ports,
    mint_cid,
    seed_author_repo,
)


def test_admit_creates_exact_admission_record() -> None:
    state = FakeRepoState()
    post_ref, submission_ref = seed_author_repo(state)
    ports = make_ports(state)

    outcome = admit(ports, make_config(), submission_ref, now=BASE_TIME)

    assert outcome.operation == "created"
    expected_rkey = admission_rkey(submission_ref)
    assert outcome.record.uri == (
        f"at://{COMMUNITY_DID}/{ADMISSION_COLLECTION}/{expected_rkey}"
    )
    stored = state.records[(COMMUNITY_DID, ADMISSION_COLLECTION, expected_rkey)]
    assert stored.record["submission"] == submission_ref.as_dict()
    assert stored.record["subject"] == post_ref.as_dict()
    assert stored.record["actor"] == ADMIN_DID
    assert ports.writer.calls == [
        ("create_immutable", COMMUNITY_DID, ADMISSION_COLLECTION)
    ]


def test_membership_transition_is_authority_owned_and_deterministic() -> None:
    state = FakeRepoState()
    ports = make_ports(state)
    config = make_config()

    added = change_membership(
        ports, config, "did:web:member.invalid", "add", None, now=BASE_TIME
    )
    repeated = change_membership(
        ports, config, "did:web:member.invalid", "add", None, now=BASE_TIME
    )

    rkey = member_action_rkey("did:web:member.invalid", "add")
    assert added.operation == "created"
    assert repeated.operation == "existing"
    assert added.record.uri == f"at://{COMMUNITY_DID}/{MEMBER_ACTION_COLLECTION}/{rkey}"
    stored = state.records[(COMMUNITY_DID, MEMBER_ACTION_COLLECTION, rkey)]
    assert stored.record["subject"] == "did:web:member.invalid"
    assert stored.record["actor"] == ADMIN_DID
    assert ports.authorizer.calls == ["membership", "membership"]


def test_membership_refuses_unauthorized_principal_before_credentials_or_write() -> (
    None
):
    state = FakeRepoState()
    ports = make_ports(state, effective_uid=9999)
    with pytest.raises(AuthorizationError):
        change_membership(
            ports,
            make_config(),
            "did:web:member.invalid",
            "remove",
            "left",
            now=BASE_TIME,
        )
    assert ports.credentials.calls == []
    assert ports.writer.calls == []


def test_membership_remove_requires_add_and_terminalizes_reenrollment() -> None:
    state = FakeRepoState()
    ports = make_ports(state)
    config = make_config()
    with pytest.raises(ValidationError) as missing:
        change_membership(
            ports, config, "did:web:member.invalid", "remove", "left", now=BASE_TIME
        )
    assert missing.value.reason_code == "reference_missing"

    change_membership(
        ports, config, "did:web:member.invalid", "add", None, now=BASE_TIME
    )
    removed = change_membership(
        ports, config, "did:web:member.invalid", "remove", "left", now=BASE_TIME
    )
    assert removed.operation == "created"
    with pytest.raises(ValidationError) as terminal:
        change_membership(
            ports, config, "did:web:member.invalid", "add", None, now=BASE_TIME
        )
    assert terminal.value.reason_code == "unsupported_readmission"


def test_admit_repeat_returns_identical_reference_as_existing() -> None:
    state = FakeRepoState()
    _, submission_ref = seed_author_repo(state)
    ports = make_ports(state)
    config = make_config()

    first = admit(ports, config, submission_ref, now=BASE_TIME)
    second = admit(ports, config, submission_ref, now=BASE_TIME)

    assert first.operation == "created"
    assert second.operation == "existing"
    assert second.record == first.record
    assert len(ports.writer.calls) == 2
    assert len(state.emitted) == 1


def test_admit_rejects_unauthorized_principal_before_any_port_call() -> None:
    state = FakeRepoState()
    _, submission_ref = seed_author_repo(state)
    ports = make_ports(state, effective_uid=9999)

    with pytest.raises(AuthorizationError):
        admit(ports, make_config(), submission_ref, now=BASE_TIME)

    assert ports.authorizer.calls == ["admit"]
    assert ports.credentials.calls == []
    assert ports.reader.calls == []
    assert ports.ledger.calls == []
    assert ports.writer.calls == []


def test_admit_requires_credentials_after_authorization() -> None:
    state = FakeRepoState()
    _, submission_ref = seed_author_repo(state)
    ports = make_ports(state, credentials={})

    with pytest.raises(CredentialUnavailableError):
        admit(ports, make_config(), submission_ref, now=BASE_TIME)

    assert ports.authorizer.calls == ["admit"]
    assert ports.credentials.calls == ["fake://communityd-admin"]
    assert ports.writer.calls == []


def test_admit_rejects_submission_for_another_community() -> None:
    state = FakeRepoState()
    _, submission_ref = seed_author_repo(state)
    key = (submission_ref.repo_did, submission_ref.collection, submission_ref.rkey)
    foreign = dict(state.records[key].record)
    foreign["community"] = "did:web:elsewhere.invalid"
    state.seed(*key, foreign, cid=submission_ref.cid)
    ports = make_ports(state)

    with pytest.raises(ValidationError) as caught:
        admit(ports, make_config(), submission_ref, now=BASE_TIME)
    assert caught.value.reason_code == "community_mismatch"
    assert ports.writer.calls == []


def test_admit_rejects_submission_not_owned_by_subject_repo() -> None:
    state = FakeRepoState()
    post_ref, submission_ref = seed_author_repo(state)
    key = (submission_ref.repo_did, submission_ref.collection, submission_ref.rkey)
    record = dict(state.records[key].record)
    record["subject"] = {
        "uri": f"at://did:web:mallory.invalid/{POST_COLLECTION}/3jzfcijpj2z2a",
        "cid": post_ref.cid,
    }
    state.seed(*key, record, cid=submission_ref.cid)
    ports = make_ports(state)

    with pytest.raises(ValidationError) as caught:
        admit(ports, make_config(), submission_ref, now=BASE_TIME)
    assert caught.value.reason_code == "repo_mismatch"
    assert ports.writer.calls == []


def test_admit_rejects_stale_subject() -> None:
    state = FakeRepoState()
    post_ref, submission_ref = seed_author_repo(state)
    state.move(
        post_ref.repo_did,
        post_ref.collection,
        post_ref.rkey,
        mint_cid({"text": "edited"}),
    )
    ports = make_ports(state)

    with pytest.raises(ValidationError) as caught:
        admit(ports, make_config(), submission_ref, now=BASE_TIME)
    assert caught.value.reason_code == "strong_ref_mismatch"
    assert ports.writer.calls == []


def test_admit_after_valid_removal_is_refused() -> None:
    state = FakeRepoState()
    _, submission_ref = seed_author_repo(state)
    ports = make_ports(state)
    config = make_config()

    admission = admit(ports, config, submission_ref, now=BASE_TIME)
    remove(ports, config, admission.record, "off-topic", now=BASE_TIME)

    with pytest.raises(UnsupportedReadmissionError):
        admit(ports, config, submission_ref, now=BASE_TIME)


def test_new_submission_lifecycle_may_be_admitted_before_removal() -> None:
    state = FakeRepoState()
    post_ref, first_submission = seed_author_repo(state)
    ports = make_ports(state)
    config = make_config()
    admit(ports, config, first_submission, now=BASE_TIME)

    second_submission_record = {
        "$type": "app.phlogiston.community.submit",
        "community": COMMUNITY_DID,
        "subject": post_ref.as_dict(),
        "createdAt": "2026-08-13T11:59:45Z",
    }
    second_submission = state.seed(
        post_ref.repo_did,
        "app.phlogiston.community.submit",
        "3jzfcijpj2z2c",
        second_submission_record,
    )
    outcome = admit(ports, config, second_submission, now=BASE_TIME)
    assert outcome.operation == "created"
    assert outcome.record.uri.endswith(admission_rkey(second_submission))


def test_admission_rkey_conflict_fails_without_overwrite() -> None:
    state = FakeRepoState()
    _, submission_ref = seed_author_repo(state)
    ports = make_ports(state)
    config = make_config()
    created = admit(ports, config, submission_ref, now=BASE_TIME)

    rkey = admission_rkey(submission_ref)
    tampered = {
        "$type": ADMISSION_COLLECTION,
        "submission": submission_ref.as_dict(),
        "subject": {
            "uri": f"at://did:web:mallory.invalid/{POST_COLLECTION}/3jzfcijpj2z2a",
            "cid": mint_cid({"text": "other"}),
        },
        "actor": ADMIN_DID,
        "createdAt": "2026-08-13T11:59:59Z",
    }
    with pytest.raises(ImmutableConflictError):
        FakeAuthorityWriter(state).create_immutable(
            COMMUNITY_DID, ADMISSION_COLLECTION, rkey, tampered
        )
    stored = state.records[(COMMUNITY_DID, ADMISSION_COLLECTION, rkey)]
    assert stored.cid == created.record.cid
    assert stored.record["createdAt"] == "2026-08-13T12:00:00Z"


def test_remove_creates_admission_derived_removal() -> None:
    state = FakeRepoState()
    post_ref, submission_ref = seed_author_repo(state)
    ports = make_ports(state)
    config = make_config()
    admission = admit(ports, config, submission_ref, now=BASE_TIME)

    outcome = remove(ports, config, admission.record, "off-topic", now=BASE_TIME)

    assert outcome.operation == "created"
    expected_rkey = removal_rkey(admission.record)
    assert outcome.record.uri == (
        f"at://{COMMUNITY_DID}/{MOD_ACTION_COLLECTION}/{expected_rkey}"
    )
    stored = state.records[(COMMUNITY_DID, MOD_ACTION_COLLECTION, expected_rkey)]
    assert stored.record["action"] == "remove"
    assert stored.record["admission"] == admission.record.as_dict()
    assert stored.record["subject"] == post_ref.as_dict()
    assert stored.record["actor"] == ADMIN_DID
    assert stored.record["reason"] == "off-topic"


def test_remove_allowed_when_subject_is_stale_or_missing() -> None:
    for mutate in ("move", "drop"):
        state = FakeRepoState()
        post_ref, submission_ref = seed_author_repo(state)
        ports = make_ports(state)
        config = make_config()
        admission = admit(ports, config, submission_ref, now=BASE_TIME)
        if mutate == "move":
            state.move(
                post_ref.repo_did,
                post_ref.collection,
                post_ref.rkey,
                mint_cid({"text": "edited"}),
            )
        else:
            state.drop(post_ref.repo_did, post_ref.collection, post_ref.rkey)

        ports.reader.calls.clear()
        outcome = remove(ports, config, admission.record, None, now=BASE_TIME)

        assert outcome.operation == "created"
        # The subject is never read during removal: stale/missing is fine.
        assert ("get_exact", post_ref.uri) not in ports.reader.calls
        assert ("get_current", post_ref.uri) not in ports.reader.calls


def test_remove_repeat_returns_existing_with_unchanged_reason() -> None:
    state = FakeRepoState()
    _, submission_ref = seed_author_repo(state)
    ports = make_ports(state)
    config = make_config()
    admission = admit(ports, config, submission_ref, now=BASE_TIME)

    first = remove(ports, config, admission.record, "off-topic", now=BASE_TIME)
    second = remove(ports, config, admission.record, "off-topic", now=BASE_TIME)

    assert second.operation == "existing"
    assert second.record == first.record
    rkey = removal_rkey(admission.record)
    stored = state.records[(COMMUNITY_DID, MOD_ACTION_COLLECTION, rkey)]
    assert stored.record["reason"] == "off-topic"

    with pytest.raises(ImmutableConflictError):
        remove(ports, config, admission.record, "different reason", now=BASE_TIME)


def test_remove_unknown_admission_is_a_validation_failure() -> None:
    state = FakeRepoState()
    _, submission_ref = seed_author_repo(state)
    ports = make_ports(state)
    missing = RecordRef(
        uri=f"at://{COMMUNITY_DID}/{ADMISSION_COLLECTION}/{admission_rkey(submission_ref)}",
        cid=mint_cid({"text": "never written"}),
    )

    with pytest.raises(ValidationError) as caught:
        remove(ports, make_config(), missing, None, now=BASE_TIME)
    assert caught.value.reason_code == "reference_missing"
    assert ports.writer.calls == []


def test_reader_unavailable_surfaces_as_port_unavailable() -> None:
    state = FakeRepoState()
    _, submission_ref = seed_author_repo(state)
    ports = make_ports(state)
    ports.reader.unavailable = True

    with pytest.raises(PortUnavailableError):
        admit(ports, make_config(), submission_ref, now=BASE_TIME)
    assert ports.writer.calls == []


def test_writer_unavailable_surfaces_as_write_failed() -> None:
    state = FakeRepoState()
    _, submission_ref = seed_author_repo(state)
    ports = make_ports(state)
    ports.writer.unavailable = True

    with pytest.raises(WriteFailedError):
        admit(ports, make_config(), submission_ref, now=BASE_TIME)
