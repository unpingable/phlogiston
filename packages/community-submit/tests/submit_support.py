"""Shared fakes for the community-submit tests.

Named uniquely so the flat pytest ``sys.path`` namespace never collides with
a sibling package's helpers.
"""

from __future__ import annotations

from datetime import UTC, datetime

from community_model import POST_COLLECTION
from community_submit.submit import parse_post_reference, submit
from community_submit.transport import Credential, Session

ALICE = "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa"
MALLORY = "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb"
COMMUNITY = "did:plc:cccccccccccccccccccccccc"
POST_RKEY = "3jzfcijpj2z2a"
POST_CID = "bafyreifjy3spsmt6fopbxzxijzkxxxcfnavowzjqi3rfnly2fwdyc47ici"
NOW = datetime(2026, 8, 17, 12, 0, 0, tzinfo=UTC)
CREDENTIAL = Credential(identifier="alice.test", app_password="app-pass")


class FakePds:
    """Records every call so tests can assert what was and was not written."""

    def __init__(
        self,
        *,
        session_did: str = ALICE,
        records: dict[tuple[str, str, str], dict] | None = None,
        session_error: Exception | None = None,
        create_error: Exception | None = None,
        read_error: Exception | None = None,
    ) -> None:
        self.session_did = session_did
        self.records = records or {}
        self.session_error = session_error
        self.create_error = create_error
        self.read_error = read_error
        self.creates: list[tuple[str, str, str, dict]] = []

    def create_session(self, credential: Credential) -> Session:
        if self.session_error is not None:
            raise self.session_error
        return Session(did=self.session_did, token="token-value")

    def get_record(self, repo, collection, rkey, token=None):
        if self.read_error is not None and collection == POST_COLLECTION:
            raise self.read_error
        return self.records.get((repo, collection, rkey))

    def create_record(self, repo, collection, rkey, record, token):
        self.creates.append((repo, collection, rkey, dict(record)))
        if self.create_error is not None:
            raise self.create_error
        uri = f"at://{repo}/{collection}/{rkey}"
        stored = {"uri": uri, "cid": "bafysubmission", "value": dict(record)}
        self.records[(repo, collection, rkey)] = stored
        return {"uri": uri, "cid": "bafysubmission"}


def _post_entry(author: str = ALICE) -> dict:
    uri = f"at://{author}/{POST_COLLECTION}/{POST_RKEY}"
    return {
        "uri": uri,
        "cid": POST_CID,
        "value": {
            "$type": POST_COLLECTION,
            "text": "hi",
            "createdAt": "2026-08-17T11:00:00Z",
        },
    }


def _pds_with_post(author: str = ALICE, **kwargs) -> FakePds:
    records = {(author, POST_COLLECTION, POST_RKEY): _post_entry(author)}
    records.update(kwargs.pop("records", {}))
    return FakePds(records=records, **kwargs)


def _do(pds: FakePds, authority: str = ALICE):
    return submit(
        pds,
        CREDENTIAL,
        community_did=COMMUNITY,
        post=parse_post_reference(
            f"https://bsky.app/profile/{authority}/post/{POST_RKEY}"
        ),
        now=NOW,
    )
