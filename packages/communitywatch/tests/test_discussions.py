from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from community_model import (
    ADMISSION_COLLECTION,
    POST_COLLECTION,
    REPLY_ACTION_COLLECTION,
    REPLY_ADMISSION_COLLECTION,
    REPLY_POLICY_COLLECTION,
    SUBMISSION_COLLECTION,
    IncomingDelivery,
    RecordRef,
    ResolveResult,
    admission_rkey,
    canonical_json_bytes,
    cid_for_dag_cbor,
    reply_action_rkey,
    reply_admission_rkey,
    reply_moderation_key,
    reply_policy_rkey,
)
from communitywatch import DiscussionQuery, ObserverStore, ProjectionQuery

COMMUNITY = "did:web:community.invalid"
ADMIN = "did:web:admin.invalid"
AUTHOR = "did:web:alice.invalid"
OTHER = "did:web:bob.invalid"
BASE = datetime(2026, 9, 7, 12, tzinfo=UTC)


def _cid(record: dict[str, object]) -> str:
    return cid_for_dag_cbor(canonical_json_bytes(record))


class Fixture:
    def __init__(self, store: ObserverStore) -> None:
        self.store = store
        self.cursor = 0
        self.rev: dict[str, int] = {}

    def ingest(
        self,
        repo: str,
        collection: str,
        rkey: str,
        record: dict[str, object],
        *,
        offset: int,
    ):
        self.cursor += 1
        self.rev[repo] = self.rev.get(repo, 0) + 1
        # TIDs need only be ordered and syntactically valid in this fixture.
        alphabet = "234567abcdefghijklmnopqrstuvwxyz"
        rev = "2" * 12 + alphabet[self.rev[repo]]
        envelope = {
            "repo": repo,
            "rev": rev,
            "operation": "create",
            "collection": collection,
            "rkey": rkey,
            "cid": _cid(record),
            "record": record,
        }
        return self.store.ingest(
            IncomingDelivery(
                source="fixture",
                cursor=str(self.cursor),
                source_event_time=BASE + timedelta(seconds=offset),
                received_at=BASE + timedelta(seconds=offset),
                raw_envelope=envelope,
                trust_mode="test_fixture",
                verification_outcome="verified",
                verification_method="fixture",
                verifier_version="1",
            )
        )

    def observe(
        self, subject: RecordRef, record: dict[str, object], trigger: str, offset: int
    ) -> None:
        self.store.record_subject_observation(
            ResolveResult(
                status="exact",
                requested=subject,
                current_cid=subject.cid,
                record=record,
                checked_at=BASE + timedelta(seconds=offset),
                trust_mode="test_fixture",
                verification_outcome="verified",
                resolution_method="fixture",
                resolver_version="1",
            ),
            triggering_event_variant_key=trigger,
        )


def _setup_root(fx: Fixture) -> tuple[RecordRef, RecordRef]:
    post = {
        "$type": POST_COLLECTION,
        "text": "root",
        "createdAt": "2026-09-07T12:00:00Z",
    }
    subject = RecordRef(f"at://{AUTHOR}/{POST_COLLECTION}/3jzfcijpj2z2a", _cid(post))
    submit_record = {
        "$type": SUBMISSION_COLLECTION,
        "community": COMMUNITY,
        "subject": subject.as_dict(),
        "createdAt": "2026-09-07T12:00:01Z",
    }
    submission = RecordRef(
        f"at://{AUTHOR}/{SUBMISSION_COLLECTION}/3jzfcijpj2z2b", _cid(submit_record)
    )
    fx.ingest(AUTHOR, SUBMISSION_COLLECTION, "3jzfcijpj2z2b", submit_record, offset=1)
    admission_record = {
        "$type": ADMISSION_COLLECTION,
        "submission": submission.as_dict(),
        "subject": subject.as_dict(),
        "actor": ADMIN,
        "createdAt": "2026-09-07T12:00:02Z",
    }
    admission = RecordRef(
        f"at://{COMMUNITY}/{ADMISSION_COLLECTION}/{admission_rkey(submission)}",
        _cid(admission_record),
    )
    result = fx.ingest(
        COMMUNITY, ADMISSION_COLLECTION, admission.rkey, admission_record, offset=2
    )
    fx.observe(subject, post, result.key, 3)
    policy_record = {
        "$type": REPLY_POLICY_COLLECTION,
        "discussion": admission.as_dict(),
        "mode": "authorOptIn",
        "actor": ADMIN,
        "createdAt": "2026-09-07T12:00:04Z",
    }
    policy = RecordRef(
        f"at://{COMMUNITY}/{REPLY_POLICY_COLLECTION}/{reply_policy_rkey(admission)}",
        _cid(policy_record),
    )
    fx.ingest(COMMUNITY, REPLY_POLICY_COLLECTION, policy.rkey, policy_record, offset=4)
    return admission, policy


def _admit_reply(
    fx: Fixture,
    discussion: RecordRef,
    policy: RecordRef,
    *,
    cid_version: int,
    parent: RecordRef,
) -> tuple[RecordRef, RecordRef]:
    reply_record = {
        "$type": POST_COLLECTION,
        "text": f"reply version {cid_version}",
        "createdAt": f"2026-09-07T12:00:{10 + cid_version:02d}Z",
        "reply": {
            "root": {
                "uri": f"at://{AUTHOR}/{POST_COLLECTION}/3jzfcijpj2z2a",
                "cid": discussion.cid if False else parent.cid,
            },
            "parent": parent.as_dict(),
        },
    }
    # The root ref is the admitted root subject, not the admission record.
    root_subject = RecordRef(
        f"at://{AUTHOR}/{POST_COLLECTION}/3jzfcijpj2z2a", parent.cid
    )
    reply_record["reply"] = {"root": root_subject.as_dict(), "parent": parent.as_dict()}
    reply = RecordRef(
        f"at://{OTHER}/{POST_COLLECTION}/3jzfcijpj2z2c", _cid(reply_record)
    )
    submission_record = {
        "$type": SUBMISSION_COLLECTION,
        "community": COMMUNITY,
        "subject": reply.as_dict(),
        "discussion": discussion.as_dict(),
        "createdAt": f"2026-09-07T12:00:{12 + cid_version:02d}Z",
    }
    srkey = f"3jzfcijpj2z{2 + cid_version}d"
    submission = RecordRef(
        f"at://{OTHER}/{SUBMISSION_COLLECTION}/{srkey}", _cid(submission_record)
    )
    fx.ingest(
        OTHER, SUBMISSION_COLLECTION, srkey, submission_record, offset=12 + cid_version
    )
    candidates = (
        DiscussionQuery(ProjectionQuery(fx.store, "test"))
        .reply_candidates(COMMUNITY)
        .candidates
    )
    assert any(item["submission"] == submission.as_dict() for item in candidates)
    admission_record = {
        "$type": REPLY_ADMISSION_COLLECTION,
        "submission": submission.as_dict(),
        "subject": reply.as_dict(),
        "discussion": discussion.as_dict(),
        "policy": policy.as_dict(),
        "actor": ADMIN,
        "createdAt": f"2026-09-07T12:00:{14 + cid_version:02d}Z",
    }
    admission = RecordRef(
        f"at://{COMMUNITY}/{REPLY_ADMISSION_COLLECTION}/{reply_admission_rkey(submission)}",
        _cid(admission_record),
    )
    result = fx.ingest(
        COMMUNITY,
        REPLY_ADMISSION_COLLECTION,
        admission.rkey,
        admission_record,
        offset=14 + cid_version,
    )
    fx.observe(reply, reply_record, result.key, 16 + cid_version)
    return admission, reply


def test_reply_removal_is_sticky_across_edit_and_resubmission(tmp_path: Path) -> None:
    store = ObserverStore(
        tmp_path / "observer.db", community_did=COMMUNITY, administrator_did=ADMIN
    )
    fx = Fixture(store)
    discussion, policy = _setup_root(fx)
    root_subject = RecordRef(
        f"at://{AUTHOR}/{POST_COLLECTION}/3jzfcijpj2z2a",
        next(
            iter(
                DiscussionQuery(ProjectionQuery(store, "test"))
                .list_discussions(COMMUNITY)
                .items
            )
        )["root"]["cid"],
    )
    first_admission, first_reply = _admit_reply(
        fx, discussion, policy, cid_version=1, parent=root_subject
    )
    moderation_key = reply_moderation_key(
        community_did=COMMUNITY, root_admission=discussion, reply_uri=first_reply.uri
    )
    removal_record = {
        "$type": REPLY_ACTION_COLLECTION,
        "action": "remove",
        "admission": first_admission.as_dict(),
        "subject": first_reply.as_dict(),
        "moderationKey": moderation_key,
        "actor": ADMIN,
        "reason": "off topic",
        "createdAt": "2026-09-07T12:00:20Z",
    }
    removal = RecordRef(
        f"at://{COMMUNITY}/{REPLY_ACTION_COLLECTION}/{reply_action_rkey(action='remove', moderation_key=moderation_key)}",
        _cid(removal_record),
    )
    fx.ingest(
        COMMUNITY, REPLY_ACTION_COLLECTION, removal.rkey, removal_record, offset=20
    )

    detail = DiscussionQuery(ProjectionQuery(store, "test")).discussion(
        COMMUNITY, discussion.rkey
    )
    assert len(detail.replies) == 1
    assert detail.replies[0]["status"] == "removed"
    assert detail.replies[0]["post"] == {}
    assert detail.replies[0]["reason"] == "off topic"
    assert detail.replies[0]["controllingAction"] == removal.as_dict()

    second_admission, _ = _admit_reply(
        fx, discussion, policy, cid_version=2, parent=root_subject
    )
    detail = DiscussionQuery(ProjectionQuery(store, "test")).discussion(
        COMMUNITY, discussion.rkey
    )
    assert len(detail.replies) == 1
    assert detail.replies[0]["admission"] == second_admission.as_dict()
    assert detail.replies[0]["status"] == "removed"
    assert detail.replies[0]["controllingAction"] == removal.as_dict()
    assert "reply version" not in str(detail.replies)

    restore_record = {
        "$type": REPLY_ACTION_COLLECTION,
        "action": "restore",
        "admission": second_admission.as_dict(),
        "subject": detail.replies[0]["subject"],
        "moderationKey": moderation_key,
        "previousAction": removal.as_dict(),
        "actor": ADMIN,
        "reason": "reviewed",
        "createdAt": "2026-09-07T12:00:30Z",
    }
    restore = RecordRef(
        f"at://{COMMUNITY}/{REPLY_ACTION_COLLECTION}/"
        f"{reply_action_rkey(action='restore', moderation_key=moderation_key, previous_action=removal)}",
        _cid(restore_record),
    )
    fx.ingest(
        COMMUNITY, REPLY_ACTION_COLLECTION, restore.rkey, restore_record, offset=30
    )
    restored = DiscussionQuery(ProjectionQuery(store, "test")).discussion(
        COMMUNITY, discussion.rkey
    )
    assert restored.replies[0]["status"] == "visible"
    assert restored.replies[0]["controllingAction"] is None
    assert restored.replies[0]["post"]["text"] == "reply version 2"
