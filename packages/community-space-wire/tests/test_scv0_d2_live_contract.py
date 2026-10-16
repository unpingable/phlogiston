from __future__ import annotations

from dataclasses import replace

import pytest

from community_model import ValidationError
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
    EXPERIMENTAL_LEXICONS,
    POST_COLLECTION,
    REMOVAL_COLLECTION,
    SPACE_TYPE,
    SUBMISSION_COLLECTION,
    WITHDRAWAL_COLLECTION,
    adapt_live_admission,
    adapt_live_post,
    adapt_live_removal,
    adapt_live_submission,
    adapt_live_withdrawal,
    load_experimental_lexicon,
)

AUTHORITY = "did:plc:wklgd4ebjiajx4gj3fthp62m"
AUTHOR = "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa"
COMMUNITY_ACTOR = "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb"
MODERATOR = "did:plc:cccccccccccccccccccccccc"
CIDS = (
    "bafyreicl6ujc6ncfktctxxroxognfn7d2fqavvrryoc2lv6m4i6hpbkfti",
    "bafyreig3yg2msah74sgvow25uxddqbabex3f3mh6hysess3w5kmgiv6zqy",
    "bafyreiaij7wqrolyv5gx2glkordkq22yacpgg23bdwyweenwlknk37zjyu",
    "bafyreihffwofbdcqendtitmma6wzds6wa2fpy5p7mkjpayvatsrydse6oe",
    "bafyreihhponjv2pdbmg33nxvccrgj34546avahl3nojk5cplawofvn2d3m",
)
POST_RECEIPT = "sha256:" + "1" * 64


def _record(
    space: SpaceIdentity, author: str, collection: str, rkey: str, cid: str
) -> ExactSpaceRecordReference:
    return ExactSpaceRecordReference(space, author, collection, rkey, cid)


@pytest.fixture
def live_contract() -> dict[str, object]:
    space = SpaceIdentity(AUTHORITY, SPACE_TYPE, "self")
    community = CommunityIdentity(space, COMMUNITY_ACTOR)
    post_record = _record(space, AUTHOR, POST_COLLECTION, "post-1", CIDS[0])
    post_value = {
        "$type": POST_COLLECTION,
        "title": "A shelf for shared tools",
        "body": "Built from reclaimed oak.",
        "createdAt": "2026-08-24T12:00:00Z",
    }
    post = adapt_live_post(
        post_value,
        record=post_record,
        qualification_receipt_id=POST_RECEIPT,
        expected_author_did=AUTHOR,
    )
    submission_record = _record(
        space, AUTHOR, SUBMISSION_COLLECTION, "submission-1", CIDS[1]
    )
    submission_value = {
        "$type": SUBMISSION_COLLECTION,
        "subject": {"uri": post_record.uri, "cid": post_record.cid},
        "communityActor": COMMUNITY_ACTOR,
        "consentProfile": CONSENT_PROFILE,
        "presentation": {
            "title": post.content.title,
            "body": post.content.body,
            "authorDisplayReference": "@alex.invalid.test",
        },
        "createdAt": "2026-08-24T12:01:00Z",
    }
    submission = adapt_live_submission(
        submission_value,
        record=submission_record,
        post=post.post,
        qualification_receipt_id="sha256:" + "2" * 64,
        expected_community=community,
    )
    admit_auth = ModeratorAuthorization(
        community=community,
        decision_id="admit-live-1",
        moderator_did=MODERATOR,
        action=AuthorizedAction.ADMIT,
        target_occurrence_id=submission.submission.submission_id,
        authorization_basis_receipt_id="sha256:" + "3" * 64,
        authorized_at="2026-08-24T12:01:30Z",
        expires_at="2026-08-24T12:06:30Z",
        provenance_receipt_id="sha256:" + "4" * 64,
    )
    admission_record = _record(
        space, COMMUNITY_ACTOR, ADMISSION_COLLECTION, "admission-1", CIDS[2]
    )
    admission_value = {
        "$type": ADMISSION_COLLECTION,
        "submission": {
            "uri": submission_record.uri,
            "cid": submission_record.cid,
        },
        "subject": {"uri": post_record.uri, "cid": post_record.cid},
        "authorizationOccurrence": admit_auth.authorization_id,
        "sourceObservationReceipt": POST_RECEIPT,
        "createdAt": "2026-08-24T12:02:00Z",
    }
    admission = adapt_live_admission(
        admission_value,
        record=admission_record,
        post=post.post,
        submission=submission.submission,
        authorization=admit_auth,
        community=community,
    )
    withdrawal_record = _record(
        space, AUTHOR, WITHDRAWAL_COLLECTION, "withdrawal-1", CIDS[3]
    )
    withdrawal_value = {
        "$type": WITHDRAWAL_COLLECTION,
        "submission": {
            "uri": submission_record.uri,
            "cid": submission_record.cid,
        },
        "admission": {"uri": admission_record.uri, "cid": admission_record.cid},
        "subject": {"uri": post_record.uri, "cid": post_record.cid},
        "communityActor": COMMUNITY_ACTOR,
        "createdAt": "2026-08-24T12:03:00Z",
    }
    withdrawal = adapt_live_withdrawal(
        withdrawal_value,
        record=withdrawal_record,
        admission=admission,
        qualification_receipt_id="sha256:" + "5" * 64,
    )
    remove_auth = ModeratorAuthorization(
        community=community,
        decision_id="remove-live-1",
        moderator_did=MODERATOR,
        action=AuthorizedAction.REMOVE,
        target_occurrence_id=admission.admission_id,
        authorization_basis_receipt_id="sha256:" + "6" * 64,
        authorized_at="2026-08-24T12:03:30Z",
        expires_at="2026-08-24T12:08:30Z",
        provenance_receipt_id="sha256:" + "7" * 64,
    )
    removal_record = _record(
        space, COMMUNITY_ACTOR, REMOVAL_COLLECTION, "removal-1", CIDS[4]
    )
    removal_value = {
        "$type": REMOVAL_COLLECTION,
        "admission": {"uri": admission_record.uri, "cid": admission_record.cid},
        "subject": {"uri": post_record.uri, "cid": post_record.cid},
        "authorizationOccurrence": remove_auth.authorization_id,
        "reasonCategory": "community_editorial",
        "createdAt": "2026-08-24T12:04:00Z",
    }
    removal = adapt_live_removal(
        removal_value,
        record=removal_record,
        admission=admission,
        authorization=remove_auth,
    )
    return locals()


def test_experimental_lexicons_are_exact_and_loadable() -> None:
    assert len(EXPERIMENTAL_LEXICONS) == 7
    for nsid in EXPERIMENTAL_LEXICONS:
        assert load_experimental_lexicon(nsid)["id"] == nsid
    space = load_experimental_lexicon(SPACE_TYPE)
    collections = space["defs"]["main"]["collections"]
    assert collections == [
        POST_COLLECTION,
        SUBMISSION_COLLECTION,
        ADMISSION_COLLECTION,
        REMOVAL_COLLECTION,
        WITHDRAWAL_COLLECTION,
    ]


def test_live_record_flow_composes_existing_exact_models(
    live_contract: dict[str, object],
) -> None:
    post = live_contract["post"]
    submission = live_contract["submission"]
    admission = live_contract["admission"]
    withdrawal = live_contract["withdrawal"]
    removal = live_contract["removal"]
    assert submission.submission.post is post.post
    assert admission.submission is submission.submission
    assert admission.post is post.post
    assert withdrawal.admission is admission
    assert removal.admission is admission
    assert submission.consent_profile == CONSENT_PROFILE


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("consentProfile", "broad-public-consent", "consent_profile_invalid"),
        ("communityActor", AUTHOR, "community_binding_mismatch"),
        ("approved", True, "live_record_fields_invalid"),
    ],
)
def test_submission_cannot_launder_consent_or_approval(
    live_contract: dict[str, object], field: str, value: object, reason: str
) -> None:
    raw = dict(live_contract["submission_value"])
    raw[field] = value
    with pytest.raises(ValidationError, match=rf"^{reason} at"):
        adapt_live_submission(
            raw,
            record=live_contract["submission_record"],
            post=live_contract["post"].post,
            qualification_receipt_id="sha256:" + "2" * 64,
            expected_community=live_contract["community"],
        )


def test_admission_and_withdrawal_are_exact_occurrences(
    live_contract: dict[str, object],
) -> None:
    altered_admission = dict(live_contract["admission_value"])
    altered_admission["authorizationOccurrence"] = "sha256:" + "f" * 64
    with pytest.raises(ValidationError, match=r"^authorization_occurrence_mismatch at"):
        adapt_live_admission(
            altered_admission,
            record=live_contract["admission_record"],
            post=live_contract["post"].post,
            submission=live_contract["submission"].submission,
            authorization=live_contract["admit_auth"],
            community=live_contract["community"],
        )

    foreign = replace(live_contract["admission_record"], rkey="admission-other")
    altered_withdrawal = dict(live_contract["withdrawal_value"])
    altered_withdrawal["admission"] = {"uri": foreign.uri, "cid": foreign.cid}
    with pytest.raises(ValidationError, match=r"^withdrawal_occurrence_mismatch at"):
        adapt_live_withdrawal(
            altered_withdrawal,
            record=live_contract["withdrawal_record"],
            admission=live_contract["admission"],
            qualification_receipt_id="sha256:" + "5" * 64,
        )


def test_community_writer_records_cannot_be_authored_by_source_author(
    live_contract: dict[str, object],
) -> None:
    wrong = replace(live_contract["removal_record"], author_did=AUTHOR)
    with pytest.raises(ValidationError, match=r"^author_binding_mismatch at"):
        adapt_live_removal(
            live_contract["removal_value"],
            record=wrong,
            admission=live_contract["admission"],
            authorization=live_contract["remove_auth"],
        )
