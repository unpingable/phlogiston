from __future__ import annotations

import io
import json

import pytest

from community_model import ValidationError
from community_policy.adapters import HttpCandidateSource, UnixAuthorityClient
from community_policy.worker import ReplyCandidate

CID = "bafyreidfayvfuwqa7qlnopdjiqrxzs6blmoeu4rujcjtnci5beludirz2a"
COMMUNITY = "did:web:community.invalid"


def ref(repo: str, collection: str, rkey: str):
    return {"uri": f"at://{repo}/{collection}/{rkey}", "cid": CID}


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def test_http_source_parses_exact_observer_candidate_shape(monkeypatch) -> None:
    document = {
        "communityDid": COMMUNITY,
        "candidates": [
            {
                "submission": ref(
                    "did:web:alice.invalid",
                    "app.phlogiston.community.submit",
                    "3jzfcijpj2z2a",
                ),
                "subject": ref(
                    "did:web:alice.invalid", "app.bsky.feed.post", "3jzfcijpj2z2b"
                ),
                "rootAdmission": ref(
                    COMMUNITY, "app.phlogiston.community.admission", "admit-" + "1" * 64
                ),
                "replyPolicy": ref(
                    COMMUNITY,
                    "app.phlogiston.community.replyPolicy",
                    "reply-policy-" + "2" * 64,
                ),
            }
        ],
        "snapshot": {"generation": "g1", "highWater": 7},
    }
    seen = []

    def open_url(url, timeout):
        seen.append((url, timeout))
        return Response(json.dumps(document).encode())

    monkeypatch.setattr("urllib.request.urlopen", open_url)
    result = HttpCandidateSource("http://observer.invalid", 3).fetch(COMMUNITY)
    assert len(result) == 1 and isinstance(result[0], ReplyCandidate)
    assert seen == [
        (f"http://observer.invalid/api/v0/communities/{COMMUNITY}/reply-candidates", 3)
    ]


def test_http_source_rejects_extra_candidate_fields(monkeypatch) -> None:
    document = {
        "communityDid": COMMUNITY,
        "candidates": [{"surprise": True}],
        "snapshot": {},
    }
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: Response(json.dumps(document).encode()),
    )
    with pytest.raises(ValidationError, match="candidate shape"):
        HttpCandidateSource("http://observer.invalid", 3).fetch(COMMUNITY)


def test_unix_client_refuses_any_broader_request() -> None:
    client = UnixAuthorityClient("/tmp/not-used.sock", 1)
    with pytest.raises(ValidationError, match="only sends reply_admit"):
        client.send(
            {
                "operationId": "x",
                "action": "reply_admit",
                "authenticatedDid": "did:web:admin.invalid",
                "target": ref(
                    "did:web:alice.invalid", "app.phlogiston.community.submit", "x"
                ),
                "rootAdmission": ref(
                    COMMUNITY, "app.phlogiston.community.admission", "x"
                ),
                "replyPolicy": ref(
                    COMMUNITY, "app.phlogiston.community.replyPolicy", "x"
                ),
            }
        )
