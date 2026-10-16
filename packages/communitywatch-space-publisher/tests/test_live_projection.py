from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from community_model import (
    ValidationError,
    cid_for_dag_cbor,
    decode_dag_cbor,
    encode_dag_cbor,
)
from community_space_artifact import DisclosureMode, DisclosurePolicy
from community_space_model import (
    AuthorizedAction,
    CommunityIdentity,
    ExactSpaceRecordReference,
    ModeratorAuthorization,
    SpaceIdentity,
)
from community_space_wire import (
    ADMISSION_COLLECTION,
    CONSENT_PROFILE,
    POST_COLLECTION,
    REMOVAL_COLLECTION,
    SPACE_TYPE,
    SUBMISSION_COLLECTION,
    WITHDRAWAL_COLLECTION,
    adapt_live_post,
    adapt_live_submission,
)
from communitywatch_space_publisher import (
    AtomicProjectionPublisher,
    AuthorityWriteReceipt,
    LiveProjectionCompiler,
    QualifiedRepoHistory,
    QualifiedSnapshot,
    SourceUnavailableEvidence,
)
from communitywatch_spaces_alpha import (
    ALPHA_LABEL,
    PERMISSIONED_REPO_PROOF_KIND,
    QualificationSourceContext,
    SpaceRecordBlock,
    SpaceRepoEvidence,
    encode_commit_context,
    qualify_repo_state,
)
from communitywatch_spaces_alpha.crypto import (
    _SECP_GENERATOR,
    _SECP_ORDER,
    _point_multiply,
    commit_mac,
    lthash_add,
    lthash_digest,
)

AUTHORITY = "did:plc:dddddddddddddddddddddddd"
AUTHOR = "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa"
ACTOR = "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb"
MODERATOR = "did:plc:cccccccccccccccccccccccc"
SPACE = SpaceIdentity(AUTHORITY, SPACE_TYPE, "self")
COMMUNITY = CommunityIdentity(SPACE, ACTOR)
ALPHA_SPACE = __import__("communitywatch_spaces_alpha").SpaceIdentity(
    AUTHORITY, SPACE_TYPE, "self"
)
PRIVATE_SCALAR = 7
BASE = datetime(2026, 8, 24, 12, tzinfo=UTC)
DIGEST = "sha256:" + "d" * 64


def _sign(message: bytes) -> bytes:
    z = int.from_bytes(__import__("hashlib").sha256(message).digest(), "big")
    nonce = (
        int.from_bytes(
            __import__("hashlib").sha256(b"publisher-fixture" + message).digest(),
            "big",
        )
        % (_SECP_ORDER - 1)
        + 1
    )
    point = _point_multiply(nonce, _SECP_GENERATOR)
    assert point is not None
    r = point[0] % _SECP_ORDER
    s = (pow(nonce, -1, _SECP_ORDER) * (z + r * PRIVATE_SCALAR)) % _SECP_ORDER
    s = min(s, _SECP_ORDER - s)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def _public_key() -> bytes:
    point = _point_multiply(PRIVATE_SCALAR, _SECP_GENERATOR)
    assert point is not None
    return bytes([2 | (point[1] & 1)]) + point[0].to_bytes(32, "big")


def _state(author: str, rev: str, records: dict[tuple[str, str], dict], when: datetime):
    encoded = {
        f"{collection}/{rkey}": encode_dag_cbor(value)
        for (collection, rkey), value in records.items()
    }
    cids = {path: cid_for_dag_cbor(value) for path, value in encoded.items()}
    index_bytes = encode_dag_cbor({path: {"$link": cid} for path, cid in cids.items()})
    canonical_index = decode_dag_cbor(index_bytes)
    state = bytes(2048)
    blocks = []
    for path, link in canonical_index.items():
        collection, rkey = path.split("/", 1)
        cid = link["$link"]
        state = lthash_add(state, f"{path}/{cid}")
        blocks.append(SpaceRecordBlock(collection, rkey, cid, encoded[path]))
    state_hash = lthash_digest(state)
    ikm = bytes.fromhex(hashlib_sha(rev))
    context = encode_commit_context(ALPHA_SPACE, author, rev, ikm)
    commit = encode_dag_cbor(
        {
            "ver": 1,
            "hash": state_hash,
            "mac": commit_mac(ikm, context, state_hash),
            "ikm": ikm,
            "sig": _sign(context),
            "rev": rev,
        }
    )
    return qualify_repo_state(
        SpaceRepoEvidence(
            f"fixture:{author}:{rev}",
            PERMISSIONED_REPO_PROOF_KIND,
            ALPHA_LABEL,
            commit,
            index_bytes,
            tuple(blocks),
        ),
        expected_space=ALPHA_SPACE,
        expected_author_did=author,
        author_public_key=_public_key(),
        signature_algorithm="ES256K",
        source=QualificationSourceContext(
            "https://pds.invalid.test",
            f"fixture:key:{author}",
            "fixture-qualified-key",
            f"fixture:{author}:{rev}",
        ),
        verified_at=when,
    )


def hashlib_sha(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()


def _snapshot(state, when: datetime, marker: str) -> QualifiedSnapshot:
    return QualifiedSnapshot(
        state,
        "sha256:" + marker * 64,
        "sha256:" + marker.upper().lower() * 64,
        when,
    )


def _ref(state, collection: str, rkey: str):
    record = next(
        item
        for item in state.records
        if item.identity.collection == collection and item.identity.rkey == rkey
    )
    return ExactSpaceRecordReference(
        SPACE, state.author_did, collection, rkey, record.cid
    )


def _authority_payload(record, authorization) -> bytes:
    return json.dumps(
        {
            "authorization": {
                "action": authorization.action.value,
                "authorizationBasisReceiptId": authorization.authorization_basis_receipt_id,
                "authorizationId": authorization.authorization_id,
                "authorizedAt": authorization.authorized_at,
                "communityIdentityId": authorization.community.identity_id,
                "decisionId": authorization.decision_id,
                "expiresAt": authorization.expires_at,
                "moderatorDid": authorization.moderator_did,
                "provenanceReceiptId": authorization.provenance_receipt_id,
                "targetOccurrenceId": authorization.target_occurrence_id,
            },
            "record": {"cid": record.cid, "uri": record.uri},
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _fixture():
    post = {
        "$type": POST_COLLECTION,
        "title": "A shelf for shared tools",
        "body": "Built from reclaimed oak.",
        "createdAt": BASE.isoformat().replace("+00:00", "Z"),
    }
    post_bytes = encode_dag_cbor(post)
    post_cid = cid_for_dag_cbor(post_bytes)
    post_uri = f"{SPACE.uri}/{AUTHOR}/{POST_COLLECTION}/post"
    submission = {
        "$type": SUBMISSION_COLLECTION,
        "subject": {"uri": post_uri, "cid": post_cid},
        "communityActor": ACTOR,
        "consentProfile": CONSENT_PROFILE,
        "presentation": {
            "title": post["title"],
            "body": post["body"],
            "authorDisplayReference": "@alex.invalid.test",
        },
        "createdAt": (BASE + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
    }
    author_v1 = _state(
        AUTHOR,
        "3mtaaaabbbbbf",
        {
            (POST_COLLECTION, "post"): post,
            (SUBMISSION_COLLECTION, "submission"): submission,
        },
        BASE + timedelta(minutes=1),
    )
    post_ref = _ref(author_v1, POST_COLLECTION, "post")
    post_receipt = next(
        receipt for receipt in author_v1.receipts if receipt.record_cid == post_ref.cid
    )
    adapted_post = adapt_live_post(
        post,
        record=post_ref,
        qualification_receipt_id=post_receipt.receipt_id,
        expected_author_did=AUTHOR,
    )
    submission_ref = _ref(author_v1, SUBMISSION_COLLECTION, "submission")
    submission_receipt = next(
        receipt
        for receipt in author_v1.receipts
        if receipt.record_cid == submission_ref.cid
    )
    adapted_submission = adapt_live_submission(
        submission,
        record=submission_ref,
        post=adapted_post.post,
        qualification_receipt_id=submission_receipt.receipt_id,
        expected_community=COMMUNITY,
    )
    authorization = ModeratorAuthorization(
        COMMUNITY,
        "admit-live-1",
        MODERATOR,
        AuthorizedAction.ADMIT,
        adapted_submission.submission.submission_id,
        DIGEST,
        (BASE + timedelta(minutes=1, seconds=30)).isoformat(),
        (BASE + timedelta(minutes=6)).isoformat(),
        "sha256:" + "e" * 64,
    )
    admission_rkey = authorization.authorization_id.removeprefix("sha256:")
    admission = {
        "$type": ADMISSION_COLLECTION,
        "submission": {"uri": submission_ref.uri, "cid": submission_ref.cid},
        "subject": {"uri": post_ref.uri, "cid": post_ref.cid},
        "authorizationOccurrence": authorization.authorization_id,
        "sourceObservationReceipt": post_receipt.receipt_id,
        "createdAt": (BASE + timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
    }
    community_v1 = _state(
        ACTOR,
        "3mtaaaabbbbbf",
        {(ADMISSION_COLLECTION, admission_rkey): admission},
        BASE + timedelta(minutes=2),
    )
    admission_ref = _ref(community_v1, ADMISSION_COLLECTION, admission_rkey)
    authority_receipt = AuthorityWriteReceipt.parse(
        _authority_payload(admission_ref, authorization), community=COMMUNITY
    )
    return locals()


def _policies():
    return (
        DisclosurePolicy(
            DisclosureMode.ORDINARY, "sha256:" + "1" * 64, "sha256:" + "2" * 64
        ),
        DisclosurePolicy(
            DisclosureMode.TECHNICAL_AUDIT, "sha256:" + "3" * 64, "sha256:" + "4" * 64
        ),
    )


def _compile(fixture, *, authors, community, receipts):
    ordinary, audit = _policies()
    return LiveProjectionCompiler(COMMUNITY).compile(
        authors=authors,
        community_history=community,
        authority_receipts=receipts,
        ordinary_policy=ordinary,
        audit_policy=audit,
        published_at="2026-08-24T12:10:00Z",
    )


def test_qualified_addition_compiles_exact_public_and_audit_feeds(tmp_path) -> None:
    f = _fixture()
    result = _compile(
        f,
        authors=(
            QualifiedRepoHistory(
                (_snapshot(f["author_v1"], BASE + timedelta(minutes=1), "a"),)
            ),
        ),
        community=QualifiedRepoHistory(
            (_snapshot(f["community_v1"], BASE + timedelta(minutes=2), "b"),)
        ),
        receipts=(f["authority_receipt"],),
    )
    assert result.ordinary_feed is not None and result.audit_feed is not None
    entry = result.ordinary_feed.entries[0]
    assert entry.lifecycle_state == "added"
    assert entry.presentation.title == "A shelf for shared tools"
    audit = result.audit_feed.entries[0].technical_receipts
    assert audit.admission_record_uri == f["admission_ref"].uri
    assert audit.admission_record_cid == f["admission_ref"].cid
    generation = AtomicProjectionPublisher().publish(
        tmp_path, result.ordinary_feed, result.audit_feed
    )
    assert (tmp_path / "current").resolve() == generation.generation_directory
    assert (
        tmp_path / "current" / "ordinary.json"
    ).read_bytes() == result.ordinary_feed.to_bytes()


def test_source_edit_and_delete_are_distinct_and_never_republish_presentation() -> None:
    f = _fixture()
    updated = {
        "$type": POST_COLLECTION,
        "title": "A shelf for shared tools — updated",
        "body": "The author changed this.",
        "createdAt": (BASE + timedelta(minutes=3)).isoformat().replace("+00:00", "Z"),
    }
    author_v2 = _state(
        AUTHOR,
        "3mtaaaabbbbbg",
        {
            (POST_COLLECTION, "post"): updated,
            (SUBMISSION_COLLECTION, "submission"): f["submission"],
        },
        BASE + timedelta(minutes=3),
    )
    changed = _compile(
        f,
        authors=(
            QualifiedRepoHistory(
                (
                    _snapshot(f["author_v1"], BASE + timedelta(minutes=1), "a"),
                    _snapshot(author_v2, BASE + timedelta(minutes=3), "c"),
                )
            ),
        ),
        community=QualifiedRepoHistory(
            (_snapshot(f["community_v1"], BASE + timedelta(minutes=2), "b"),)
        ),
        receipts=(f["authority_receipt"],),
    )
    assert changed.ordinary_feed.entries[0].lifecycle_state == "changed_at_source"
    assert changed.ordinary_feed.entries[0].presentation is None

    author_v3 = _state(
        AUTHOR,
        "3mtaaaabbbbbh",
        {(SUBMISSION_COLLECTION, "submission"): f["submission"]},
        BASE + timedelta(minutes=4),
    )
    deleted = _compile(
        f,
        authors=(
            QualifiedRepoHistory(
                (
                    _snapshot(f["author_v1"], BASE + timedelta(minutes=1), "a"),
                    _snapshot(author_v2, BASE + timedelta(minutes=3), "c"),
                    _snapshot(author_v3, BASE + timedelta(minutes=4), "d"),
                )
            ),
        ),
        community=QualifiedRepoHistory(
            (_snapshot(f["community_v1"], BASE + timedelta(minutes=2), "b"),)
        ),
        receipts=(f["authority_receipt"],),
    )
    entry = deleted.ordinary_feed.entries[0]
    assert entry.lifecycle_state == "source_unavailable"
    assert entry.source_relationship == "deleted_by_author"
    assert entry.presentation is None

    ordinary, audit = _policies()
    unavailable = LiveProjectionCompiler(COMMUNITY).compile(
        authors=(
            QualifiedRepoHistory(
                (_snapshot(f["author_v1"], BASE + timedelta(minutes=1), "a"),)
            ),
        ),
        community_history=QualifiedRepoHistory(
            (_snapshot(f["community_v1"], BASE + timedelta(minutes=2), "b"),)
        ),
        authority_receipts=(f["authority_receipt"],),
        ordinary_policy=ordinary,
        audit_policy=audit,
        published_at="2026-08-24T12:10:00Z",
        unavailable=(
            SourceUnavailableEvidence(
                AUTHOR,
                "sha256:" + "8" * 64,
                "sha256:" + "9" * 64,
                BASE + timedelta(minutes=5),
            ),
        ),
    )
    unavailable_entry = unavailable.ordinary_feed.entries[0]
    assert unavailable_entry.lifecycle_state == "source_unavailable"
    assert unavailable_entry.source_relationship == "unavailable"


def test_author_withdrawal_and_community_removal_remain_distinct_exact_events() -> None:
    f = _fixture()
    initial = _compile(
        f,
        authors=(
            QualifiedRepoHistory(
                (_snapshot(f["author_v1"], BASE + timedelta(minutes=1), "a"),)
            ),
        ),
        community=QualifiedRepoHistory(
            (_snapshot(f["community_v1"], BASE + timedelta(minutes=2), "b"),)
        ),
        receipts=(f["authority_receipt"],),
    )
    admission = initial.lifecycles[0].admission
    assert admission is not None

    withdrawal_record = {
        "$type": WITHDRAWAL_COLLECTION,
        "submission": {
            "uri": admission.submission.record.uri,
            "cid": admission.submission.record.cid,
        },
        "admission": {"uri": admission.record.uri, "cid": admission.record.cid},
        "subject": {"uri": admission.post.record.uri, "cid": admission.post.record.cid},
        "communityActor": ACTOR,
        "createdAt": (BASE + timedelta(minutes=4)).isoformat().replace("+00:00", "Z"),
    }
    author_withdrawn = _state(
        AUTHOR,
        "3mtaaaabbbbbg",
        {
            (POST_COLLECTION, "post"): f["post"],
            (SUBMISSION_COLLECTION, "submission"): f["submission"],
            (WITHDRAWAL_COLLECTION, "withdrawal"): withdrawal_record,
        },
        BASE + timedelta(minutes=4),
    )
    withdrawn = _compile(
        f,
        authors=(
            QualifiedRepoHistory(
                (
                    _snapshot(f["author_v1"], BASE + timedelta(minutes=1), "a"),
                    _snapshot(author_withdrawn, BASE + timedelta(minutes=4), "c"),
                )
            ),
        ),
        community=QualifiedRepoHistory(
            (_snapshot(f["community_v1"], BASE + timedelta(minutes=2), "b"),)
        ),
        receipts=(f["authority_receipt"],),
    )
    withdrawn_entry = withdrawn.ordinary_feed.entries[0]
    assert withdrawn_entry.lifecycle_state == "author_withdrawn"
    assert withdrawn_entry.presentation is None

    remove_authorization = ModeratorAuthorization(
        COMMUNITY,
        "remove-live-1",
        MODERATOR,
        AuthorizedAction.REMOVE,
        admission.admission_id,
        DIGEST,
        (BASE + timedelta(minutes=5)).isoformat(),
        (BASE + timedelta(minutes=10)).isoformat(),
        "sha256:" + "f" * 64,
    )
    removal_record = {
        "$type": REMOVAL_COLLECTION,
        "admission": {"uri": admission.record.uri, "cid": admission.record.cid},
        "subject": {"uri": admission.post.record.uri, "cid": admission.post.record.cid},
        "authorizationOccurrence": remove_authorization.authorization_id,
        "reasonCategory": "editorial-removal",
        "createdAt": (BASE + timedelta(minutes=6)).isoformat().replace("+00:00", "Z"),
    }
    removal_rkey = remove_authorization.authorization_id.removeprefix("sha256:")
    community_removed = _state(
        ACTOR,
        "3mtaaaabbbbbg",
        {
            (ADMISSION_COLLECTION, admission.record.rkey): f["admission"],
            (REMOVAL_COLLECTION, removal_rkey): removal_record,
        },
        BASE + timedelta(minutes=6),
    )
    removal_ref = _ref(community_removed, REMOVAL_COLLECTION, removal_rkey)
    removal_receipt = AuthorityWriteReceipt.parse(
        _authority_payload(removal_ref, remove_authorization), community=COMMUNITY
    )
    removed = _compile(
        f,
        authors=(
            QualifiedRepoHistory(
                (_snapshot(f["author_v1"], BASE + timedelta(minutes=1), "a"),)
            ),
        ),
        community=QualifiedRepoHistory(
            (
                _snapshot(f["community_v1"], BASE + timedelta(minutes=2), "b"),
                _snapshot(community_removed, BASE + timedelta(minutes=6), "d"),
            )
        ),
        receipts=(f["authority_receipt"], removal_receipt),
    )
    removed_entry = removed.ordinary_feed.entries[0]
    assert removed_entry.lifecycle_state == "removed"
    assert removed_entry.presentation is None
    assert removed.lifecycles[0].admission == admission
    assert removed.lifecycles[0].submission.post.record == admission.post.record


def test_authority_substitution_and_snapshot_rollback_refuse() -> None:
    f = _fixture()
    payload = json.loads(_authority_payload(f["admission_ref"], f["authorization"]))
    payload["authorization"]["governanceAuthority"] = True
    with pytest.raises(ValidationError, match="live_projection_input_invalid"):
        AuthorityWriteReceipt.parse(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
            community=COMMUNITY,
        )

    newer = _snapshot(f["author_v1"], BASE + timedelta(minutes=2), "a")
    older = _snapshot(f["author_v1"], BASE + timedelta(minutes=1), "a")
    with pytest.raises(ValidationError, match="live_projection_history_invalid"):
        QualifiedRepoHistory((newer, older))
