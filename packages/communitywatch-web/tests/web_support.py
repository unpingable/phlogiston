"""Seeded-observer helpers for the web AppView package tests.

One writable store seeds the database exactly the way the index writer
would; every test then reopens it through the read-only web path.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from community_model import (
    ADMISSION_COLLECTION,
    MOD_ACTION_COLLECTION,
    POST_COLLECTION,
    PROFILE_COLLECTION,
    SUBMISSION_COLLECTION,
    IncomingDelivery,
    RecordRef,
    ResolveResult,
    admission_rkey,
    canonical_json_bytes,
    cid_for_dag_cbor,
    removal_rkey,
)
from communitywatch import ObserverStore

COMMUNITY_DID = "did:web:community.invalid"
ADMIN_DID = "did:web:admin.invalid"
SLUG = "homelab"
SOURCE = "fixture-source"
BASE_TIME = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)
APP_TIME = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)

_TID_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"


def tid(sequence: int) -> str:
    digits = ""
    value = sequence
    while True:
        digits = _TID_ALPHABET[value % 32] + digits
        value //= 32
        if not value:
            break
    return digits.rjust(13, "2")


def cid(record: dict[str, object]) -> str:
    return cid_for_dag_cbor(canonical_json_bytes(record))


class Sequencer:
    def __init__(self) -> None:
        self.cursor = 0
        self.revs: dict[str, int] = {}

    def next_cursor(self) -> str:
        self.cursor += 1
        return str(self.cursor)

    def next_rev(self, repo: str) -> str:
        self.revs[repo] = self.revs.get(repo, 0) + 1
        return tid(self.revs[repo])


def delivery(
    sequencer: Sequencer,
    *,
    repo: str,
    collection: str,
    rkey: str,
    record: dict[str, object] | None,
    operation: str = "create",
    record_cid: str | None = None,
    outcome: str = "verified",
    rev: str | None = None,
    at: datetime,
) -> IncomingDelivery:
    envelope: dict[str, object] = {
        "repo": repo,
        "rev": rev if rev is not None else sequencer.next_rev(repo),
        "operation": operation,
        "collection": collection,
        "rkey": rkey,
    }
    if operation != "delete":
        envelope["cid"] = record_cid or cid(record or {})
        envelope["record"] = record
    return IncomingDelivery(
        source=SOURCE,
        cursor=sequencer.next_cursor(),
        source_event_time=at,
        received_at=at,
        raw_envelope=envelope,
        trust_mode="test_fixture",
        verification_outcome=outcome,
        verification_method="fixture",
        verifier_version="1",
    )


def exact_observation(
    subject: RecordRef, record: dict[str, object], *, at: datetime
) -> ResolveResult:
    return ResolveResult(
        status="exact",
        requested=subject,
        current_cid=subject.cid,
        record=record,
        checked_at=at,
        trust_mode="test_fixture",
        verification_outcome="verified",
        resolution_method="fixture",
        resolver_version="1",
    )


def seed_visible_entry(
    store: ObserverStore,
    sequencer: Sequencer,
    *,
    author_did: str,
    post_rkey: str,
    submission_rkey: str,
    text: str,
    admitted_at: str,
    observed_at: datetime,
) -> dict[str, RecordRef]:
    """Drive one submission/admission/exact-observation flow; return refs."""

    post = {"$type": POST_COLLECTION, "text": text, "createdAt": admitted_at}
    subject = RecordRef(
        uri=f"at://{author_did}/{POST_COLLECTION}/{post_rkey}", cid=cid(post)
    )
    submission_record = {
        "$type": SUBMISSION_COLLECTION,
        "community": COMMUNITY_DID,
        "subject": subject.as_dict(),
        "createdAt": admitted_at,
    }
    submission = RecordRef(
        uri=f"at://{author_did}/{SUBMISSION_COLLECTION}/{submission_rkey}",
        cid=cid(submission_record),
    )
    store.ingest(
        delivery(
            sequencer,
            repo=author_did,
            collection=SUBMISSION_COLLECTION,
            rkey=submission_rkey,
            record=submission_record,
            at=observed_at,
        )
    )
    admission_record = {
        "$type": ADMISSION_COLLECTION,
        "submission": submission.as_dict(),
        "subject": subject.as_dict(),
        "actor": ADMIN_DID,
        "createdAt": admitted_at,
    }
    admission = RecordRef(
        uri=(
            f"at://{COMMUNITY_DID}/{ADMISSION_COLLECTION}/{admission_rkey(submission)}"
        ),
        cid=cid(admission_record),
    )
    result = store.ingest(
        delivery(
            sequencer,
            repo=COMMUNITY_DID,
            collection=ADMISSION_COLLECTION,
            rkey=admission_rkey(submission),
            record=admission_record,
            record_cid=admission.cid,
            at=observed_at + timedelta(seconds=1),
        )
    )
    store.record_subject_observation(
        exact_observation(subject, post, at=observed_at + timedelta(seconds=2)),
        triggering_event_variant_key=result.key,
    )
    return {"subject": subject, "submission": submission, "admission": admission}


def seed_removal(
    store: ObserverStore,
    sequencer: Sequencer,
    *,
    subject: RecordRef,
    admission: RecordRef,
    reason: str,
    at: datetime,
) -> None:
    removal_record = {
        "$type": MOD_ACTION_COLLECTION,
        "action": "remove",
        "admission": admission.as_dict(),
        "subject": subject.as_dict(),
        "actor": ADMIN_DID,
        "reason": reason,
        "createdAt": "2026-08-13T12:05:00Z",
    }
    store.ingest(
        delivery(
            sequencer,
            repo=COMMUNITY_DID,
            collection=MOD_ACTION_COLLECTION,
            rkey=removal_rkey(admission),
            record=removal_record,
            at=at,
        )
    )


def seed_observer_db(path: Path) -> dict[str, RecordRef]:
    """Seed profile, visible, removed, quarantined, and conflicting material."""

    store = ObserverStore(
        path, community_did=COMMUNITY_DID, administrator_did=ADMIN_DID
    )
    sequencer = Sequencer()
    profile = {
        "$type": PROFILE_COLLECTION,
        "displayName": "Homelab <Friends>",
        "description": "Tiny computers. </p><script>alert(2)</script>",
        "createdAt": "2026-08-13T12:00:00Z",
    }
    store.ingest(
        delivery(
            sequencer,
            repo=COMMUNITY_DID,
            collection=PROFILE_COLLECTION,
            rkey="self",
            record=profile,
            at=BASE_TIME,
        )
    )
    seed_visible_entry(
        store,
        sequencer,
        author_did="did:web:alice.invalid",
        post_rkey="3jzfcijpj2z2a",
        submission_rkey="3jzfcijpj2z2k",
        text='<script>alert("xss")</script> loud fans',
        admitted_at="2026-08-13T12:01:00Z",
        observed_at=BASE_TIME + timedelta(minutes=1),
    )
    removed = seed_visible_entry(
        store,
        sequencer,
        author_did="did:web:carol.invalid",
        post_rkey="3jzfcijpj2z2c",
        submission_rkey="3jzfcijpj2z2m",
        text="off-topic noise",
        admitted_at="2026-08-13T12:01:00Z",
        observed_at=BASE_TIME + timedelta(minutes=2),
    )
    seed_removal(
        store,
        sequencer,
        subject=removed["subject"],
        admission=removed["admission"],
        reason='off-topic <script>alert("reason")</script>',
        at=BASE_TIME + timedelta(minutes=3),
    )
    # Quarantine: a delivery whose revision cannot form a semantic event.
    store.ingest(
        delivery(
            sequencer,
            repo="did:web:dave.invalid",
            collection=SUBMISSION_COLLECTION,
            rkey="3jzfcijpj2z2n",
            record={"$type": SUBMISSION_COLLECTION},
            rev="not a tid",
            at=BASE_TIME + timedelta(minutes=4),
        )
    )
    # Conflict: one semantic event, two incompatible accepted payloads.
    conflict_record = {
        "$type": SUBMISSION_COLLECTION,
        "community": COMMUNITY_DID,
        "subject": {
            "uri": f"at://did:web:eve.invalid/{POST_COLLECTION}/3jzfcijpj2z2d",
            "cid": cid({"$type": POST_COLLECTION, "text": "a"}),
        },
        "createdAt": "2026-08-13T12:06:00Z",
    }
    conflict_rev = sequencer.next_rev("did:web:eve.invalid")
    for text in ("first claim", "second claim"):
        store.ingest(
            delivery(
                sequencer,
                repo="did:web:eve.invalid",
                collection=SUBMISSION_COLLECTION,
                rkey="3jzfcijpj2z2o",
                record={**conflict_record, "note": text},
                rev=conflict_rev,
                at=BASE_TIME + timedelta(minutes=5),
            )
        )
    return {
        "removed_subject": removed["subject"],
        "removed_admission": removed["admission"],
    }


def body_json(response) -> dict[str, object]:
    assert response.content_type.startswith("application/json")
    return json.loads(response.body.decode("utf-8"))


def body_text(response) -> str:
    """Decode an HTML response body (browser routes render HTML errors)."""

    assert response.content_type.startswith("text/html")
    return response.body.decode("utf-8")
