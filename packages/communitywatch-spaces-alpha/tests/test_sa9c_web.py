from __future__ import annotations

import hashlib
import json
from datetime import datetime

from communitywatch_spaces_alpha import (
    DidDocumentProvenanceKind,
    DidInterpretationProfile,
    DidResolutionMethod,
    DidResolutionProvenance,
    DidWebResolver,
    derive_atproto_did_web_url,
    qualify_did_document,
)
from spaces_http_support import HttpFixtureResponse

_NOW = datetime.fromisoformat("2026-08-21T19:00:00+00:00")


def _loopback_did(server) -> str:
    port = server.server.server_address[1]
    return f"did:web:127.0.0.1%3A{port}"


def _document(did: str, endpoint: str | None = None) -> bytes:
    value: dict[str, object] = {"id": did}
    if endpoint is not None:
        value["service"] = [
            {
                "id": "#atproto_pds",
                "type": "AtprotoPersonalDataServer",
                "serviceEndpoint": endpoint,
            }
        ]
    return json.dumps(value, separators=(",", ":")).encode()


def test_web1_hostname_did_derives_standard_document_location() -> None:
    assert derive_atproto_did_web_url("did:web:identity.invalid.test") == (
        "https://identity.invalid.test/.well-known/did.json"
    )


def test_web2_exact_document_bytes_are_preserved(http_fixture_factory) -> None:
    holder: dict[str, bytes] = {}

    def dispatch(_):
        return HttpFixtureResponse(
            body=holder["body"], headers={"Content-Type": "application/did+ld+json"}
        )

    server = http_fixture_factory(dispatch)
    did = _loopback_did(server)
    holder["body"] = b'{"service":[],"id":"' + did.encode() + b'"}'
    result = DidWebResolver(development_loopback=True, now=lambda: _NOW).resolve(did)

    assert result.resolved_document.document_bytes == holder["body"]
    assert (
        result.resolved_document.document_sha256
        == hashlib.sha256(holder["body"]).hexdigest()
    )
    assert result.resolved_document.method is DidResolutionMethod.WEB
    assert result.resolved_document.provenance is (
        DidResolutionProvenance.DEVELOPMENT_LOOPBACK
    )


def test_web3_sa9b_composition_preserves_separate_receipts(
    http_fixture_factory,
) -> None:
    body_holder: dict[str, bytes] = {}
    server = http_fixture_factory(
        lambda _: HttpFixtureResponse(body=body_holder["body"])
    )
    did = _loopback_did(server)
    body_holder["body"] = _document(did, server.base_url)
    resolution = DidWebResolver(development_loopback=True, now=lambda: _NOW).resolve(
        did
    )
    binding_input = resolution.resolved_document.to_sa9b_input()
    binding = qualify_did_document(
        binding_input,
        profile=DidInterpretationProfile.ACCOUNT_REPO_HOST,
        qualified_at=_NOW,
    )

    assert binding.document_sha256 == resolution.resolved_document.document_sha256
    assert binding.document_provenance_ref == resolution.receipt.receipt_id
    assert binding.document_provenance_kind is (
        DidDocumentProvenanceKind.FUTURE_VERIFIED_DID_RESOLUTION
    )
    assert binding.did_resolution_verified is False
    assert resolution.receipt.governance_authority is False


def test_web4_localhost_encoded_port_is_development_only(http_fixture_factory) -> None:
    holder: dict[str, bytes] = {}
    server = http_fixture_factory(lambda _: HttpFixtureResponse(body=holder["body"]))
    did = _loopback_did(server)
    holder["body"] = _document(did)

    result = DidWebResolver(development_loopback=True, now=lambda: _NOW).resolve(did)

    assert result.receipt.development_loopback is True
    assert "webpki_hostname_verified" not in result.receipt.verified_claims
    assert result.receipt.automatic_retries == 0
    assert server.requests[0].target == "/.well-known/did.json"
    assert server.requests[0].headers["accept-encoding"] == "identity"
    assert "authorization" not in server.requests[0].headers
    assert "cookie" not in server.requests[0].headers


def test_same_origin_redirect_is_retained_without_identity_upgrade(
    http_fixture_factory,
) -> None:
    holder: dict[str, str] = {}

    def dispatch(request):
        if request.target == "/.well-known/did.json":
            return HttpFixtureResponse(status=302, headers={"Location": "/did.json"})
        return HttpFixtureResponse(body=_document(holder["did"]))

    server = http_fixture_factory(dispatch)
    holder["did"] = _loopback_did(server)
    result = DidWebResolver(development_loopback=True, now=lambda: _NOW).resolve(
        holder["did"]
    )

    assert len(result.receipt.redirects) == 1
    assert result.receipt.final_url.endswith("/did.json")
    assert result.receipt.perpetual_control is False
