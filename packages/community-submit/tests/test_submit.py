"""Self-submission semantics against a fake PDS; no network, no credentials."""

from __future__ import annotations

import pytest

from community_model import POST_COLLECTION, SUBMISSION_COLLECTION, RecordRef
from community_submit.submit import parse_post_reference, submission_rkey, submit
from community_submit.transport import (
    AuthorizationFailed,
    ReadUnavailable,
    Session,
    SubmitError,
    WriteAmbiguous,
)
from submit_support import (
    ALICE,
    COMMUNITY,
    CREDENTIAL,
    MALLORY,
    NOW,
    POST_CID,
    POST_RKEY,
    FakePds,
    _do,
    _pds_with_post,
    _post_entry,
)


def test_valid_self_submission_writes_the_v0_record() -> None:
    pds = _pds_with_post()
    outcome = _do(pds)

    assert outcome.result == "submitted"
    assert outcome.subject == RecordRef(
        uri=f"at://{ALICE}/{POST_COLLECTION}/{POST_RKEY}", cid=POST_CID
    )
    repo, collection, rkey, record = pds.creates[0]
    assert repo == ALICE, "the record lands in the participant's own repository"
    assert collection == SUBMISSION_COLLECTION
    assert rkey == submission_rkey(COMMUNITY, outcome.subject)
    # Exactly the existing V0 record shape; no new fields.
    assert record == {
        "$type": SUBMISSION_COLLECTION,
        "community": COMMUNITY,
        "subject": {
            "uri": f"at://{ALICE}/{POST_COLLECTION}/{POST_RKEY}",
            "cid": POST_CID,
        },
        "createdAt": "2026-08-17T12:00:00Z",
    }


def test_submitting_someone_elses_post_is_refused_before_any_write() -> None:
    pds = _pds_with_post(author=MALLORY)
    with pytest.raises(SubmitError) as caught:
        _do(pds, authority=MALLORY)
    assert caught.value.code == "not_your_post"
    assert pds.creates == [], "nothing may be written for a foreign post"


def test_malformed_links_are_refused() -> None:
    for value in (
        "not a link",
        "https://bsky.app/profile/alice",
        "at://did:plc:x/app.bsky.feed.like/abc",
        "",
    ):
        with pytest.raises(SubmitError) as caught:
            parse_post_reference(value)
        assert caught.value.code in {"malformed_link", "not_a_post"}, value


def test_at_uri_form_is_accepted() -> None:
    located = parse_post_reference(f"at://{ALICE}/{POST_COLLECTION}/{POST_RKEY}")
    assert (located.authority, located.rkey) == (ALICE, POST_RKEY)


def test_missing_post_is_reported_not_written() -> None:
    pds = FakePds()
    with pytest.raises(ReadUnavailable) as caught:
        _do(pds)
    assert caught.value.code == "post_missing"
    assert pds.creates == []


def test_unreadable_post_does_not_write() -> None:
    pds = _pds_with_post(read_error=ReadUnavailable("read_failed", "boom"))
    with pytest.raises(ReadUnavailable):
        _do(pds)
    assert pds.creates == []


def test_exact_cid_comes_from_the_repository_not_the_caller() -> None:
    """A later edit changes the CID, which changes the submission subject."""

    pds = _pds_with_post()
    first = _do(pds)
    edited = _post_entry()
    edited["cid"] = "bafyreib5xz4c2mqplwudhviolnnzgmu6ci3ywljvfhkfyunu6twtcwsinq"
    pds.records[(ALICE, POST_COLLECTION, POST_RKEY)] = edited
    second = _do(pds)

    assert first.subject.cid != second.subject.cid
    assert submission_rkey(COMMUNITY, first.subject) != submission_rkey(
        COMMUNITY, second.subject
    )


def test_repeat_submission_is_idempotent_not_duplicated() -> None:
    pds = _pds_with_post()
    first = _do(pds)
    second = _do(pds)

    assert first.result == "submitted"
    assert second.result == "already_submitted"
    assert len(pds.creates) == 1, "a compatible repeat must not write again"
    assert second.submission_uri == first.submission_uri


def test_incompatible_occupant_at_the_rkey_is_a_conflict() -> None:
    pds = _pds_with_post()
    subject = RecordRef(uri=f"at://{ALICE}/{POST_COLLECTION}/{POST_RKEY}", cid=POST_CID)
    rkey = submission_rkey(COMMUNITY, subject)
    pds.records[(ALICE, SUBMISSION_COLLECTION, rkey)] = {
        "uri": f"at://{ALICE}/{SUBMISSION_COLLECTION}/{rkey}",
        "cid": "bafyother",
        "value": {
            "$type": SUBMISSION_COLLECTION,
            "community": "did:plc:dddddddddddddddddddddddd",
            "subject": {"uri": "at://x/y/z", "cid": "bafyz"},
            "createdAt": "2026-08-17T10:00:00Z",
        },
    }
    with pytest.raises(SubmitError) as caught:
        _do(pds)
    assert caught.value.code == "rkey_conflict"
    assert pds.creates == []


def test_authentication_failure_stops_before_reading_or_writing() -> None:
    pds = _pds_with_post(
        session_error=AuthorizationFailed("authorization_failed", "nope")
    )
    with pytest.raises(AuthorizationFailed):
        _do(pds)
    assert pds.creates == []


def test_ambiguous_write_resolves_by_readback_never_by_retry() -> None:
    """A dropped response whose commit landed is settled, not retried."""

    pds = _pds_with_post(create_error=WriteAmbiguous("write_unsettled", "dropped"))

    original_create = pds.create_record

    def create_then_land(repo, collection, rkey, record, token):
        try:
            return original_create(repo, collection, rkey, record, token)
        except WriteAmbiguous:
            # The commit landed even though the response was lost.
            uri = f"at://{repo}/{collection}/{rkey}"
            pds.records[(repo, collection, rkey)] = {
                "uri": uri,
                "cid": "bafylanded",
                "value": dict(record),
            }
            raise

    pds.create_record = create_then_land  # type: ignore[method-assign]
    outcome = _do(pds)

    assert outcome.result == "already_submitted"
    assert outcome.submission_cid == "bafylanded"
    assert len(pds.creates) == 1, "the write is attempted exactly once"


def test_ambiguous_write_that_did_not_land_is_reported_as_unsettled() -> None:
    pds = _pds_with_post(create_error=WriteAmbiguous("write_unsettled", "dropped"))
    with pytest.raises(WriteAmbiguous) as caught:
        _do(pds)
    assert caught.value.code == "write_failed"
    assert len(pds.creates) == 1


def test_community_must_be_a_did() -> None:
    from community_model import ValidationError

    pds = _pds_with_post()
    with pytest.raises(ValidationError):
        submit(
            pds,
            CREDENTIAL,
            community_did="not-a-did",
            post=parse_post_reference(
                f"https://bsky.app/profile/{ALICE}/post/{POST_RKEY}"
            ),
            now=NOW,
        )
    assert pds.creates == []


def test_credentials_are_never_repr_leaked() -> None:
    assert "app-pass" not in repr(CREDENTIAL)
    assert "token-value" not in repr(Session(did=ALICE, token="token-value"))
