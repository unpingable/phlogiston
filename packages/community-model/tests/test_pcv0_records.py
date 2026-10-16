from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from community_model import (
    ADMISSION_COLLECTION,
    REPLY_ACTION_COLLECTION,
    REPLY_ADMISSION_COLLECTION,
    REPLY_POLICY_COLLECTION,
    SUBMISSION_COLLECTION,
    AdmissionRecord,
    RecordRef,
    ReplyActionRecord,
    ReplyAdmissionRecord,
    ReplyModerationState,
    ReplyPolicyRecord,
    SubmissionRecord,
    ValidationContext,
    ValidationError,
    apply_reply_action,
    reply_action_rkey,
    reply_admission_rkey,
    reply_moderation_key,
    reply_policy_rkey,
    validate_admission_references,
    validate_record,
    validate_reply_admission_references,
    validate_reply_policy_references,
    validate_reply_submission_references,
)

COMMUNITY = "did:web:community.invalid"
ADMIN = "did:web:admin.invalid"
ALICE = "did:web:alice.invalid"
CID1 = "bafyreidfayvfuwqa7qlnopdjiqrxzs6blmoeu4rujcjtnci5beludirz2a"
CID2 = "bafyreigoxt64qghytzkr6ik7qvtzc7lyytiq5xbbrokbxjows2wp7vmo6q"
CID3 = "bafyreiaizynclnqiolq7byfpjjtgqzn4sfrsgn7z2hhf6bo4utdwkin7ke"
NOW = datetime(2026, 9, 7, 14, tzinfo=UTC)
RAW_NOW = "2026-09-07T14:00:00Z"
ROOT = RecordRef(f"at://{ALICE}/app.bsky.feed.post/3jzfcijpj2z2a", CID1)
REPLY_V1 = RecordRef(f"at://{ALICE}/app.bsky.feed.post/3jzfcijpj2z2c", CID2)
REPLY_V2 = RecordRef(REPLY_V1.uri, CID3)
ROOT_SUBMISSION = RecordRef(f"at://{ALICE}/{SUBMISSION_COLLECTION}/3jzfcijpj2z2b", CID2)
ROOT_ADMISSION = RecordRef(
    f"at://{COMMUNITY}/{ADMISSION_COLLECTION}/admit-{'1' * 64}", CID3
)
REPLY_SUBMISSION = RecordRef(
    f"at://{ALICE}/{SUBMISSION_COLLECTION}/3jzfcijpj2z2d", CID1
)
POLICY = RecordRef(
    f"at://{COMMUNITY}/{REPLY_POLICY_COLLECTION}/{reply_policy_rkey(ROOT_ADMISSION)}",
    CID2,
)
REPLY_ADMISSION_V1 = RecordRef(
    f"at://{COMMUNITY}/{REPLY_ADMISSION_COLLECTION}/{reply_admission_rkey(REPLY_SUBMISSION)}",
    CID3,
)


def _context(collection: str, rkey: str, repo: str = COMMUNITY) -> ValidationContext:
    return ValidationContext(
        community_did=COMMUNITY,
        repo_did=repo,
        collection=collection,
        rkey=rkey,
        operation="create",
        record_cid=CID1,
        administrator_did=ADMIN,
    )


def _root_admission() -> AdmissionRecord:
    return AdmissionRecord(
        submission=ROOT_SUBMISSION,
        subject=ROOT,
        actor=ADMIN,
        created_at=NOW,
        created_at_raw=RAW_NOW,
    )


def _submission(subject: RecordRef = REPLY_V1) -> SubmissionRecord:
    return SubmissionRecord(
        community=COMMUNITY,
        subject=subject,
        discussion=ROOT_ADMISSION,
        created_at=NOW,
        created_at_raw=RAW_NOW,
    )


def _policy() -> ReplyPolicyRecord:
    return ReplyPolicyRecord(
        discussion=ROOT_ADMISSION,
        mode="authorOptIn",
        actor=ADMIN,
        created_at=NOW,
        created_at_raw=RAW_NOW,
    )


def _admission(subject: RecordRef = REPLY_V1) -> ReplyAdmissionRecord:
    return ReplyAdmissionRecord(
        submission=REPLY_SUBMISSION,
        subject=subject,
        discussion=ROOT_ADMISSION,
        policy=POLICY,
        actor=ADMIN,
        created_at=NOW,
        created_at_raw=RAW_NOW,
    )


def test_submission_legacy_shape_round_trips_and_reply_shape_is_unambiguous() -> None:
    root = SubmissionRecord(
        community=COMMUNITY,
        subject=ROOT,
        created_at=NOW,
        created_at_raw=RAW_NOW,
    )
    assert SubmissionRecord.from_legacy_record(root.to_record()) == root
    reply = _submission()
    assert SubmissionRecord.from_record(reply.to_record()) == reply
    with pytest.raises(ValidationError) as captured:
        SubmissionRecord.from_legacy_record(reply.to_record())
    assert (captured.value.reason_code, captured.value.path) == (
        "schema_incompatible",
        ("discussion",),
    )
    root_style_admission = AdmissionRecord(
        submission=REPLY_SUBMISSION,
        subject=REPLY_V1,
        actor=ADMIN,
        created_at=NOW,
        created_at_raw=RAW_NOW,
    )
    with pytest.raises(ValidationError, match="schema_incompatible"):
        validate_admission_references(root_style_admission, reply)


def test_new_records_validate_as_create_only_authority_records() -> None:
    records = (
        (_policy(), REPLY_POLICY_COLLECTION, reply_policy_rkey(ROOT_ADMISSION)),
        (
            _admission(),
            REPLY_ADMISSION_COLLECTION,
            reply_admission_rkey(REPLY_SUBMISSION),
        ),
    )
    for record, collection, rkey in records:
        validated = validate_record(
            record.to_record(), context=_context(collection, rkey)
        )
        assert validated.record == record
        with pytest.raises(ValidationError, match="authority_record_mutated"):
            validate_record(
                record.to_record(),
                context=replace(_context(collection, rkey), operation="update"),
            )


def test_reply_authorship_policy_and_thread_relationships_are_explicit() -> None:
    submission = _submission()
    validate_reply_submission_references(
        submission,
        _root_admission(),
        root_admission_ref=ROOT_ADMISSION,
        reply_root=ROOT,
        reply_parent=ROOT,
    )
    validate_reply_policy_references(_policy(), ROOT_ADMISSION)
    validate_reply_admission_references(
        _admission(),
        submission,
        _policy(),
        submission_ref=REPLY_SUBMISSION,
        policy_ref=POLICY,
    )
    with pytest.raises(ValidationError, match="reply_ancestry_invalid"):
        validate_reply_submission_references(
            submission,
            _root_admission(),
            root_admission_ref=ROOT_ADMISSION,
            reply_root=ROOT,
            reply_parent=RecordRef(
                "at://did:web:mallory.invalid/app.bsky.feed.post/3jzfcijpj2z2e", CID1
            ),
        )


def test_logical_moderation_key_ignores_reply_cid_but_pins_discussion() -> None:
    first = reply_moderation_key(
        community_did=COMMUNITY,
        root_admission=ROOT_ADMISSION,
        reply_uri=REPLY_V1.uri,
    )
    edited = reply_moderation_key(
        community_did=COMMUNITY,
        root_admission=ROOT_ADMISSION,
        reply_uri=REPLY_V2.uri,
    )
    assert reply_policy_rkey(ROOT_ADMISSION) == (
        "reply-policy-c59d903d3ca2cc2ccb21b5fbd9f08b44adc1ebb7811bb4e4ddaf10dda760456c"
    )
    assert reply_admission_rkey(REPLY_SUBMISSION) == (
        "reply-admit-af58781640fa4ec81319d2e4444eb461796713a31396912fa507b0978876c759"
    )
    assert (
        first
        == "sha256:9038d791ceeb6ba76e0d7b3ab64f4bcbe0183571698148af3c54af7f09efb470"
    )
    assert reply_action_rkey(action="remove", moderation_key=first) == (
        "reply-remove-35c57e6017318f394fcccc3b142427abe34197b14e42eeed1ebda104ee58e1dd"
    )
    assert first == edited
    other_root = RecordRef(ROOT_ADMISSION.uri, CID1)
    assert first != reply_moderation_key(
        community_did=COMMUNITY,
        root_admission=other_root,
        reply_uri=REPLY_V1.uri,
    )


def test_remove_edit_resubmit_new_admission_stays_on_same_removed_chain() -> None:
    key = reply_moderation_key(
        community_did=COMMUNITY,
        root_admission=ROOT_ADMISSION,
        reply_uri=REPLY_V1.uri,
    )
    removal = ReplyActionRecord(
        action="remove",
        admission=REPLY_ADMISSION_V1,
        subject=REPLY_V1,
        moderation_key=key,
        previous_action=None,
        actor=ADMIN,
        reason="Off topic",
        created_at=NOW,
        created_at_raw=RAW_NOW,
    )
    removal_ref = RecordRef(
        f"at://{COMMUNITY}/{REPLY_ACTION_COLLECTION}/"
        f"{reply_action_rkey(action='remove', moderation_key=key)}",
        CID1,
    )
    validated = validate_record(
        removal.to_record(),
        context=_context(REPLY_ACTION_COLLECTION, removal_ref.rkey),
    )
    assert validated.record == removal
    state = apply_reply_action(
        None,
        removal,
        action_ref=removal_ref,
        admission=_admission(),
        admission_ref=REPLY_ADMISSION_V1,
        community_did=COMMUNITY,
    )
    assert state == ReplyModerationState(key, True, removal_ref)

    edited_admission = _admission(REPLY_V2)
    edited_admission_ref = RecordRef(REPLY_ADMISSION_V1.uri, CID2)
    bypass = replace(
        removal,
        admission=edited_admission_ref,
        subject=REPLY_V2,
    )
    with pytest.raises(ValidationError, match="action_chain_invalid"):
        apply_reply_action(
            state,
            bypass,
            action_ref=RecordRef(removal_ref.uri, CID2),
            admission=edited_admission,
            admission_ref=edited_admission_ref,
            community_did=COMMUNITY,
        )

    restoration = ReplyActionRecord(
        action="restore",
        admission=edited_admission_ref,
        subject=REPLY_V2,
        moderation_key=key,
        previous_action=removal_ref,
        actor=ADMIN,
        reason=None,
        created_at=NOW,
        created_at_raw=RAW_NOW,
    )
    restoration_ref = RecordRef(
        f"at://{COMMUNITY}/{REPLY_ACTION_COLLECTION}/"
        f"{reply_action_rkey(action='restore', moderation_key=key, previous_action=removal_ref)}",
        CID3,
    )
    state = apply_reply_action(
        state,
        restoration,
        action_ref=restoration_ref,
        admission=edited_admission,
        admission_ref=edited_admission_ref,
        community_did=COMMUNITY,
    )
    assert not state.removed


def test_substitution_and_invalid_action_chains_fail_closed() -> None:
    with pytest.raises(ValidationError, match="reply_policy_mismatch"):
        ReplyPolicyRecord(
            discussion=ROOT_ADMISSION,
            mode="fetchAll",
            actor=ADMIN,
            created_at=NOW,
            created_at_raw=RAW_NOW,
        )
    with pytest.raises(ValidationError, match="action_chain_invalid"):
        ReplyActionRecord(
            action="restore",
            admission=REPLY_ADMISSION_V1,
            subject=REPLY_V1,
            moderation_key="sha256:" + "0" * 64,
            previous_action=None,
            actor=ADMIN,
            reason=None,
            created_at=NOW,
            created_at_raw=RAW_NOW,
        )
