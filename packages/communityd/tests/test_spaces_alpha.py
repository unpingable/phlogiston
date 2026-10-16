from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from community_model import (
    AuthorizationError,
    ValidationError,
)
from community_space_model import ExactSpaceRecordReference, SpaceIdentity
from communityd.fakes import FakeAdminAuthorizer, FakeCredentialProvider
from communityd.spaces_alpha import (
    AdmitOccurrence,
    RemoveOccurrence,
    SpacesAlphaAuthorityConfig,
    SpacesAlphaPorts,
    SpacesAlphaWriteOutcome,
    admit_space,
    remove_space,
)

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
CID = "bafyreicl6ujc6ncfktctxxroxognfn7d2fqavvrryoc2lv6m4i6hpbkfti"
AUTHOR = "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa"
ACTOR = "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb"
ADMIN = "did:plc:cccccccccccccccccccccccc"
SPACE = SpaceIdentity(
    "did:plc:dddddddddddddddddddddddd",
    "net.sp00ky.juniper-pds.authority.juniperCommunity",
    "self",
)


class Writer:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create_immutable(self, **input: object) -> SpacesAlphaWriteOutcome:
        self.calls.append(input)
        return SpacesAlphaWriteOutcome(
            uri=f"{SPACE.uri}/{input['repo_did']}/{input['collection']}/{input['rkey']}",
            cid=CID,
            created=True,
        )


class Occurrences:
    def __init__(self) -> None:
        self.used: set[str] = set()

    def consume(self, authorization_id: str) -> None:
        if authorization_id in self.used:
            raise AuthorizationError("authorization occurrence replay")
        self.used.add(authorization_id)


def ref(author: str, collection: str, rkey: str) -> ExactSpaceRecordReference:
    return ExactSpaceRecordReference(SPACE, author, collection, rkey, CID)


def ports() -> SpacesAlphaPorts:
    return SpacesAlphaPorts(
        authorizer=FakeAdminAuthorizer(ADMIN, 1000, 1000),
        credentials=FakeCredentialProvider({"runtime://community": "opaque"}),
        writer=Writer(),
        occurrences=Occurrences(),
    )


def config() -> SpacesAlphaAuthorityConfig:
    return SpacesAlphaAuthorityConfig(SPACE, ACTOR, ADMIN, "runtime://community")


def admit_request() -> AdmitOccurrence:
    return AdmitOccurrence(
        submission=ref(
            AUTHOR,
            "net.sp00ky.juniper-pds.authority.juniperSubmission",
            "submission",
        ),
        subject=ref(AUTHOR, "net.sp00ky.juniper-pds.authority.juniperPost", "post"),
        submission_occurrence_id=DIGEST,
        source_observation_receipt_id=DIGEST,
        decision_id="decision-1",
        authorization_basis_receipt_id=DIGEST,
        authorization_provenance_receipt_id=DIGEST,
        authorized_at="2026-08-24T11:59:00Z",
        expires_at="2026-08-24T12:01:00Z",
    )


def test_exact_admission_uses_one_occurrence_and_actor_writer() -> None:
    p = ports()
    result = admit_space(p, config(), admit_request(), now=NOW)
    assert result.record.author_did == ACTOR
    call = p.writer.calls[0]  # type: ignore[attr-defined]
    assert call["repo_did"] == ACTOR
    record = call["record"]
    assert isinstance(record, dict)
    assert record["subject"] == {"uri": admit_request().subject.uri, "cid": CID}
    assert record["authorizationOccurrence"] == result.authorization.authorization_id


def test_authorization_replay_refuses_before_second_write() -> None:
    p = ports()
    admit_space(p, config(), admit_request(), now=NOW)
    with pytest.raises(AuthorizationError):
        admit_space(p, config(), admit_request(), now=NOW)
    assert len(p.writer.calls) == 1  # type: ignore[attr-defined]


def test_cross_author_and_stale_authorization_refuse() -> None:
    p = ports()
    bad = admit_request()
    with pytest.raises(ValidationError, match="authors differ"):
        admit_space(
            p,
            config(),
            replace(
                bad,
                subject=ref(
                    "did:plc:eeeeeeeeeeeeeeeeeeeeeeee",
                    bad.subject.collection,
                    "post",
                ),
            ),
            now=NOW,
        )
    with pytest.raises(ValidationError, match="not valid"):
        admit_space(p, config(), bad, now=datetime(2026, 8, 24, 13, tzinfo=UTC))


def test_removal_targets_exact_admission_without_mutating_source() -> None:
    p = ports()
    result = remove_space(
        p,
        config(),
        RemoveOccurrence(
            admission=ref(
                ACTOR,
                "net.sp00ky.juniper-pds.authority.juniperAdmission",
                "admission",
            ),
            subject=ref(
                AUTHOR,
                "net.sp00ky.juniper-pds.authority.juniperPost",
                "post",
            ),
            admission_occurrence_id=DIGEST,
            reason="not a fit for this feed",
            decision_id="decision-remove",
            authorization_basis_receipt_id=DIGEST,
            authorization_provenance_receipt_id=DIGEST,
            authorized_at="2026-08-24T11:59:00Z",
            expires_at="2026-08-24T12:01:00Z",
        ),
        now=NOW,
    )
    assert result.record.author_did == ACTOR
    call = p.writer.calls[0]  # type: ignore[attr-defined]
    assert call["collection"] == "net.sp00ky.juniper-pds.authority.juniperRemoval"
    assert call["repo_did"] == ACTOR
