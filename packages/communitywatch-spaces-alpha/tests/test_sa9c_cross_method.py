from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path

import pytest

from community_model import ValidationError
from communitywatch_spaces_alpha import (
    DidInterpretationProfile,
    DidResolutionMethod,
    DidWebResolver,
    PlcAuditEntry,
    PlcHistoryEvidence,
    qualify_did_document,
    qualify_plc_history,
    require_resolution_method,
)
from spaces_http_support import HttpFixtureResponse

_NOW = datetime.fromisoformat("2026-08-21T20:00:00+00:00")
_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests/fixtures/spaces-alpha/reference/sa9c-plc-reference.json"
)


def test_cross_h1_analogous_bindings_do_not_make_method_receipts_interchangeable(
    http_fixture_factory,
) -> None:
    fixture = json.loads(_FIXTURE.read_bytes())
    vector = fixture["histories"]["modern"]
    entries = tuple(
        PlcAuditEntry(
            base64.b64decode(item["operationDagCborBase64"]),
            item["cid"],
            datetime.fromisoformat(item["createdAt"].replace("Z", "+00:00")),
            item["nullified"],
        )
        for item in vector["entries"]
    )
    plc = qualify_plc_history(
        PlcHistoryEvidence(vector["did"], entries, "fixture:cross:plc"),
        evaluated_at=_NOW,
    )
    assert plc.resolved_document is not None
    plc_binding = qualify_did_document(
        plc.resolved_document.to_sa9b_input(),
        profile=DidInterpretationProfile.ACCOUNT_REPO_HOST,
        qualified_at=_NOW,
    )

    holder: dict[str, bytes] = {}
    server = http_fixture_factory(lambda _: HttpFixtureResponse(body=holder["body"]))
    web_did = f"did:web:127.0.0.1%3A{server.server.server_address[1]}"
    plc_document = json.loads(plc.resolved_document.document_bytes)
    holder["body"] = json.dumps(
        {
            "id": web_did,
            "service": plc_document["service"],
        },
        separators=(",", ":"),
    ).encode()
    web = DidWebResolver(development_loopback=True, now=lambda: _NOW).resolve(web_did)
    web_binding = qualify_did_document(
        web.resolved_document.to_sa9b_input(),
        profile=DidInterpretationProfile.ACCOUNT_REPO_HOST,
        qualified_at=_NOW,
    )

    assert web_binding.selected_origin == plc_binding.selected_origin
    assert web_binding.document_provenance_ref != plc_binding.document_provenance_ref
    with pytest.raises(ValidationError):
        require_resolution_method(web.resolved_document, DidResolutionMethod.PLC)
    with pytest.raises(ValidationError):
        require_resolution_method(plc.resolved_document, DidResolutionMethod.WEB)
