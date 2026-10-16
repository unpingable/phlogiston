from __future__ import annotations

import json
import urllib.request
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from community_model import ValidationError
from communitywatch_spaces_alpha import (
    DidWebResolutionError,
    DidWebResolver,
    derive_atproto_did_web_url,
    require_resolved_document_binding,
)
from communitywatch_spaces_alpha.did_web import _RedirectPolicy, _WebRedirectRefusal
from spaces_http_support import HttpFixtureResponse

_NOW = datetime.fromisoformat("2026-08-21T19:30:00+00:00")


def _did(server) -> str:
    return f"did:web:127.0.0.1%3A{server.server.server_address[1]}"


def _json(did: str, **extra: object) -> bytes:
    return json.dumps({"id": did, **extra}, separators=(",", ":")).encode()


def _reason(caught: pytest.ExceptionInfo[ValidationError]) -> str:
    return caught.value.reason_code


def test_web_h1_path_based_atproto_did_web_refuses() -> None:
    with pytest.raises(ValidationError) as caught:
        derive_atproto_did_web_url("did:web:identity.invalid.test:path")
    assert _reason(caught) == "spaces_did_web_path_unsupported"


def test_web_h2_returned_document_did_mismatch_refuses(http_fixture_factory) -> None:
    server = http_fixture_factory(
        lambda _: HttpFixtureResponse(body=_json("did:web:other.invalid.test"))
    )
    with pytest.raises(ValidationError) as caught:
        DidWebResolver(development_loopback=True).resolve(_did(server))
    assert _reason(caught) == "spaces_did_web_document_id_mismatch"


def test_web_h3_cross_origin_redirect_refuses(http_fixture_factory) -> None:
    target = http_fixture_factory(lambda _: HttpFixtureResponse(body=b"not reached"))
    source = http_fixture_factory(
        lambda _: HttpFixtureResponse(
            status=302,
            headers={"Location": f"{target.base_url}/.well-known/did.json"},
        )
    )
    with pytest.raises(ValidationError) as caught:
        DidWebResolver(development_loopback=True).resolve(_did(source))
    assert _reason(caught) == "spaces_did_web_cross_origin_redirect"
    assert target.requests == ()


def test_web_h4_http_and_encoded_port_are_not_production_identity() -> None:
    with pytest.raises(ValidationError) as caught:
        derive_atproto_did_web_url("did:web:localhost%3A8080")
    assert _reason(caught) == "spaces_did_web_development_only"

    redirect_policy = _RedirectPolicy(maximum=3)
    with pytest.raises(_WebRedirectRefusal) as downgrade:
        redirect_policy.redirect_request(
            urllib.request.Request("https://identity.invalid.test/did.json"),
            None,
            302,
            "Found",
            {},
            "http://identity.invalid.test/did.json",
        )
    assert str(downgrade.value) == "spaces_did_web_http_downgrade"


def test_web_h5_modified_bytes_cannot_reuse_receipt(http_fixture_factory) -> None:
    holder: dict[str, bytes] = {}
    server = http_fixture_factory(lambda _: HttpFixtureResponse(body=holder["body"]))
    did = _did(server)
    holder["body"] = _json(did)
    result = DidWebResolver(development_loopback=True, now=lambda: _NOW).resolve(did)

    with pytest.raises(ValidationError) as caught:
        require_resolved_document_binding(
            result.resolved_document, _json(did, mutated=True)
        )
    assert _reason(caught) == "spaces_did_resolution_document_mismatch"


def test_web_h6_html_error_payload_with_200_refuses(http_fixture_factory) -> None:
    server = http_fixture_factory(
        lambda _: HttpFixtureResponse(
            body=b"<html>not a DID</html>", headers={"Content-Type": "text/html"}
        )
    )
    with pytest.raises(ValidationError) as caught:
        DidWebResolver(development_loopback=True).resolve(_did(server))
    assert _reason(caught) == "spaces_did_web_document_invalid"


def test_web_h7_duplicate_json_keys_refuse(http_fixture_factory) -> None:
    holder: dict[str, bytes] = {}
    server = http_fixture_factory(lambda _: HttpFixtureResponse(body=holder["body"]))
    did = _did(server)
    holder["body"] = b'{"id":"' + did.encode() + b'","id":"' + did.encode() + b'"}'
    with pytest.raises(ValidationError) as caught:
        DidWebResolver(development_loopback=True).resolve(did)
    assert _reason(caught) == "spaces_did_web_document_invalid"


def test_web_h8_oversized_document_refuses_boundedly(http_fixture_factory) -> None:
    holder: dict[str, bytes] = {}
    server = http_fixture_factory(lambda _: HttpFixtureResponse(body=holder["body"]))
    did = _did(server)
    holder["body"] = _json(did, padding="x" * 1000)
    with pytest.raises(ValidationError) as caught:
        DidWebResolver(development_loopback=True, maximum_document_bytes=128).resolve(
            did
        )
    assert _reason(caught) == "spaces_did_web_oversized"


def test_did_web_read_timeout_is_explicit_and_has_no_hidden_retry(
    http_fixture_factory,
) -> None:
    server = http_fixture_factory(
        lambda _: HttpFixtureResponse(body=b"{}", delay_seconds=0.2)
    )
    with pytest.raises(DidWebResolutionError):
        DidWebResolver(development_loopback=True, timeout_seconds=0.05).resolve(
            _did(server)
        )
    assert len(server.requests) == 1


def test_web_h9_repeated_different_documents_are_separate_observations(
    http_fixture_factory,
) -> None:
    holder: dict[str, object] = {"count": 0}

    def dispatch(_):
        holder["count"] = int(holder["count"]) + 1
        did = str(holder["did"])
        return HttpFixtureResponse(
            body=_json(did, state=holder["count"]),
        )

    server = http_fixture_factory(dispatch)
    did = _did(server)
    holder["did"] = did
    first = DidWebResolver(development_loopback=True, now=lambda: _NOW).resolve(did)
    second = DidWebResolver(
        development_loopback=True, now=lambda: _NOW + timedelta(seconds=1)
    ).resolve(did)

    assert first.receipt.receipt_id != second.receipt.receipt_id
    assert first.resolved_document.document_sha256 != (
        second.resolved_document.document_sha256
    )
    assert first.resolved_document.globally_current is False
    assert second.resolved_document.globally_current is False


@pytest.mark.parametrize(
    "field_name",
    [
        "historical_continuity",
        "perpetual_control",
        "globally_current",
        "governance_authority",
    ],
)
def test_web_h10_webpki_or_caller_labels_cannot_upgrade_claims(
    http_fixture_factory, field_name: str
) -> None:
    holder: dict[str, bytes] = {}
    server = http_fixture_factory(lambda _: HttpFixtureResponse(body=holder["body"]))
    did = _did(server)
    holder["body"] = _json(did)
    receipt = (
        DidWebResolver(development_loopback=True, now=lambda: _NOW).resolve(did).receipt
    )

    with pytest.raises(ValidationError) as caught:
        replace(receipt, **{field_name: True})
    assert _reason(caught) == "spaces_did_web_receipt_invalid"
