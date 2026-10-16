from __future__ import annotations

import json
import urllib.parse
from copy import deepcopy
from dataclasses import replace

import pytest

from community_model import ValidationError
from communitywatch_spaces_alpha import (
    ArtifactRequestIdentity,
    DidBindingSelection,
    DidDocumentInput,
    DidDocumentProvenanceKind,
    DidInterpretationProfile,
    EndpointBindingDisposition,
    FullRepoArtifactRequest,
    HttpAcquisitionError,
    HttpSpaceArtifactProvider,
    assess_http_endpoint_binding,
    qualify_did_document,
    require_receipt_document_binding,
)
from spaces_http_support import HttpFixtureRequest, HttpFixtureResponse
from spaces_support import sa4_author, sa4_space, timestamp

_DID = "did:plc:sa9bhostileaaaaaaaaaaaa"
_KEY = "zQ3shqwJEJyMBsBXCWyCBpUBMqxcon9oHB7mCvx4sSpMdLJwc"


def _bytes(document: object) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()


def _evidence(
    document: object,
    *,
    expected_did: str = _DID,
    reference: str = "fixture:sa9b:hostile",
    allow_loopback: bool = False,
) -> DidDocumentInput:
    return DidDocumentInput(
        expected_did=expected_did,
        document_bytes=_bytes(document),
        provenance_kind=DidDocumentProvenanceKind.FIXTURE,
        provenance_ref=reference,
        allow_insecure_loopback_fixture=allow_loopback,
    )


def _service(endpoint: str, *, identifier="#atproto_pds", service_type=None):
    return {
        "id": identifier,
        "type": service_type or "AtprotoPersonalDataServer",
        "serviceEndpoint": endpoint,
    }


def _pds_document(endpoint: str, **service_changes):
    service = _service(endpoint)
    service.update(service_changes)
    return {"id": _DID, "service": [service]}


def _qualify_service(document, *, profile=DidInterpretationProfile.ACCOUNT_REPO_HOST):
    return qualify_did_document(
        _evidence(document),
        profile=profile,
        qualified_at=timestamp("2026-08-21T17:00:00Z"),
    )


def _reason(caught: pytest.ExceptionInfo[ValidationError]) -> str:
    return caught.value.reason_code


def test_did_h1_document_id_must_match_expected_did() -> None:
    document = _pds_document("https://pds.invalid.test")
    document["id"] = "did:plc:someoneelseaaaaaaaaaaa"

    with pytest.raises(ValidationError) as caught:
        _qualify_service(document)
    assert _reason(caught) == "spaces_did_document_id_mismatch"


def test_did_h2_foreign_fully_qualified_service_fragment_refuses() -> None:
    document = {
        "id": _DID,
        "service": [
            _service(
                "https://foreign.invalid.test",
                identifier="did:plc:someoneelseaaaaaaaaaaa#atproto_pds",
            )
        ],
    }
    with pytest.raises(ValidationError) as caught:
        _qualify_service(document)
    assert _reason(caught) == "spaces_did_foreign_fragment"


def test_did_h3_correct_fragment_with_wrong_service_type_is_not_selected() -> None:
    document = _pds_document(
        "https://pds.invalid.test", type="DefinitelyNotAPersonalDataServer"
    )
    with pytest.raises(ValidationError) as caught:
        _qualify_service(document)
    assert _reason(caught) == "spaces_did_pds_not_found"


def test_did_h4_path_bearing_endpoint_refuses() -> None:
    with pytest.raises(ValidationError) as caught:
        _qualify_service(_pds_document("https://pds.invalid.test/sneaky/prefix"))
    assert _reason(caught) == "spaces_did_pds_not_found"


def test_did_h5_userinfo_endpoint_refuses_before_sa9a() -> None:
    with pytest.raises(ValidationError) as caught:
        _qualify_service(_pds_document("https://user:pass@pds.invalid.test"))
    assert _reason(caught) == "spaces_did_pds_not_found"


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://pds.invalid.test?substitution=yes",
        "https://pds.invalid.test#substitution",
    ],
)
def test_did_h6_query_or_fragment_endpoint_refuses(endpoint: str) -> None:
    with pytest.raises(ValidationError) as caught:
        _qualify_service(_pds_document(endpoint))
    assert _reason(caught) == "spaces_did_pds_not_found"


def test_did_h7_insecure_non_loopback_endpoint_refuses_even_for_fixture() -> None:
    document = _pds_document("http://pds.invalid.test")
    evidence = _evidence(document, allow_loopback=True)
    with pytest.raises(ValidationError) as caught:
        qualify_did_document(
            evidence,
            profile=DidInterpretationProfile.ACCOUNT_REPO_HOST,
            qualified_at=timestamp("2026-08-21T17:00:00Z"),
        )
    assert _reason(caught) == "spaces_did_pds_not_found"


def test_did_h8_invalid_present_dedicated_space_host_blocks_fallback() -> None:
    document = {
        "id": _DID,
        "service": [
            _service("https://fallback.invalid.test"),
            _service(
                "https://space.invalid.test/not-an-origin",
                identifier="#atproto_space_host",
                service_type="AtprotoSpaceHost",
            ),
        ],
    }
    with pytest.raises(ValidationError) as caught:
        _qualify_service(
            document, profile=DidInterpretationProfile.SPACE_AUTHORITY_HOST
        )
    assert _reason(caught) == "spaces_did_dedicated_service_invalid"


def test_did_h9_key_fragment_controlled_by_another_did_refuses() -> None:
    document = {
        "id": _DID,
        "verificationMethod": [
            {
                "id": "#atproto_space",
                "type": "Multikey",
                "controller": "did:plc:someoneelseaaaaaaaaaaa",
                "publicKeyMultibase": _KEY,
            }
        ],
    }
    with pytest.raises(ValidationError) as caught:
        qualify_did_document(
            _evidence(document),
            profile=DidInterpretationProfile.SPACE_AUTHORITY_SIGNING_KEY,
            qualified_at=timestamp("2026-08-21T17:00:00Z"),
        )
    assert _reason(caught) == "spaces_did_dedicated_key_invalid"


def _http_request(source_vectors, request_id: str):
    return FullRepoArtifactRequest(
        ArtifactRequestIdentity(
            request_id=request_id,
            space=sa4_space(source_vectors),
            repo_did=sa4_author(source_vectors),
        )
    )


def test_did_h10_endpoint_mismatch_is_explicit_and_does_not_reject_transport(
    http_fixture_factory, sa4_source_vectors
) -> None:
    binding = _qualify_service(_pds_document("https://a.invalid.test"))
    server = http_fixture_factory(lambda _: HttpFixtureResponse(body=b"transport-only"))
    provider = HttpSpaceArtifactProvider(
        server.base_url,
        source_endpoint="https://b.invalid.test",
        now=lambda: timestamp("2026-08-21T17:01:00Z"),
    )
    artifact = provider.get_repo(_http_request(sa4_source_vectors, "did-h10"))
    acquisition = provider.receipts_for(artifact.source.artifact_ref)[0]
    assessment = assess_http_endpoint_binding(binding, acquisition)

    assert assessment.disposition is EndpointBindingDisposition.ENDPOINT_MISMATCH
    assert acquisition.artifact_validity is False
    assert assessment.artifact_validity is False


def _loopback_binding(server) -> object:
    document = _pds_document(server.base_url)
    return qualify_did_document(
        _evidence(document, allow_loopback=True),
        profile=DidInterpretationProfile.ACCOUNT_REPO_HOST,
        qualified_at=timestamp("2026-08-21T17:02:00Z"),
    )


def test_did_h11_same_origin_redirect_matches_but_cross_origin_refusal_is_unqualified(
    http_fixture_factory, sa4_source_vectors
) -> None:
    def same_dispatch(request: HttpFixtureRequest) -> HttpFixtureResponse:
        if urllib.parse.urlsplit(request.target).path.endswith("getRepo"):
            return HttpFixtureResponse(status=302, headers={"Location": "/artifact"})
        return HttpFixtureResponse(body=b"same-origin")

    same = http_fixture_factory(same_dispatch)
    same_binding = _loopback_binding(same)
    same_provider = HttpSpaceArtifactProvider(
        same.base_url,
        source_endpoint="https://same.invalid.test",
        now=lambda: timestamp("2026-08-21T17:02:01Z"),
    )
    artifact = same_provider.get_repo(_http_request(sa4_source_vectors, "did-h11-a"))
    same_receipt = same_provider.receipts_for(artifact.source.artifact_ref)[0]
    same_assessment = assess_http_endpoint_binding(same_binding, same_receipt)
    assert same_assessment.disposition is EndpointBindingDisposition.ENDPOINT_MATCH
    assert same_receipt.redirects

    target = http_fixture_factory(lambda _: HttpFixtureResponse(body=b"not reached"))
    source = http_fixture_factory(
        lambda _: HttpFixtureResponse(
            status=302, headers={"Location": f"{target.base_url}/artifact"}
        )
    )
    cross_binding = _loopback_binding(source)
    cross_provider = HttpSpaceArtifactProvider(
        source.base_url,
        source_endpoint="https://source.invalid.test",
        now=lambda: timestamp("2026-08-21T17:02:02Z"),
    )
    with pytest.raises(HttpAcquisitionError) as caught:
        cross_provider.get_repo(_http_request(sa4_source_vectors, "did-h11-b"))
    cross_assessment = assess_http_endpoint_binding(cross_binding, caught.value.receipt)
    assert (
        cross_assessment.disposition
        is EndpointBindingDisposition.UNQUALIFIED_HTTP_ACQUISITION
    )
    assert target.requests == ()


@pytest.mark.parametrize(
    "field_name",
    [
        "did_resolution_verified",
        "did_state_current",
        "remote_service_control_verified",
        "canonical_service",
        "artifact_validity",
        "standing",
        "authorization",
        "governance_authority",
    ],
)
def test_did_h12_caller_relabeling_cannot_upgrade_receipt(field_name: str) -> None:
    receipt = _qualify_service(_pds_document("https://pds.invalid.test"))
    with pytest.raises(ValidationError) as caught:
        replace(receipt, **{field_name: True})
    assert _reason(caught) == "spaces_did_binding_receipt_invalid"


def test_did_h13_first_valid_duplicate_service_wins_without_sorting() -> None:
    document = {
        "id": _DID,
        "service": [
            _service(
                "https://wrong-type.invalid.test",
                service_type="WrongType",
            ),
            _service("https://first-valid.invalid.test"),
            _service("https://second-valid.invalid.test"),
        ],
    }
    receipt = _qualify_service(document)

    assert receipt.selection is DidBindingSelection.ACCOUNT_PDS
    assert receipt.selected_origin == "https://first-valid.invalid.test"


def test_did_h14_receipt_cannot_be_reused_after_document_mutation() -> None:
    document = _pds_document("https://pds.invalid.test")
    original = _evidence(document)
    receipt = qualify_did_document(
        original,
        profile=DidInterpretationProfile.ACCOUNT_REPO_HOST,
        qualified_at=timestamp("2026-08-21T17:00:00Z"),
    )
    mutated = deepcopy(document)
    assert isinstance(mutated["service"], list)
    assert isinstance(mutated["service"][0], dict)
    mutated["service"][0]["serviceEndpoint"] = "https://mutated.invalid.test"

    with pytest.raises(ValidationError) as caught:
        require_receipt_document_binding(receipt, _evidence(mutated))
    assert _reason(caught) == "spaces_did_receipt_document_mismatch"


def test_duplicate_json_keys_are_refused_as_ambiguous_input() -> None:
    raw = (
        b'{"id":"did:plc:sa9bhostileaaaaaaaaaaaa",'
        b'"id":"did:plc:sa9bhostileaaaaaaaaaaaa","service":[]}'
    )
    evidence = DidDocumentInput(
        expected_did=_DID,
        document_bytes=raw,
        provenance_kind=DidDocumentProvenanceKind.CALLER_SUPPLIED,
        provenance_ref="caller:duplicate-json",
    )
    with pytest.raises(ValidationError) as caught:
        qualify_did_document(
            evidence,
            profile=DidInterpretationProfile.ACCOUNT_REPO_HOST,
            qualified_at=timestamp("2026-08-21T17:00:00Z"),
        )
    assert _reason(caught) == "spaces_did_document_invalid"


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://pds.invalid.test.",
        "https://%70ds.invalid.test",
        "https://münich.invalid.test",
        "https://pds.invalid.test:99999",
    ],
)
def test_ambiguous_or_noncanonical_hostname_inputs_refuse(endpoint: str) -> None:
    with pytest.raises(ValidationError) as caught:
        _qualify_service(_pds_document(endpoint))
    assert _reason(caught) == "spaces_did_pds_not_found"


def test_first_valid_key_is_selected_without_reordering() -> None:
    document = {
        "id": _DID,
        "verificationMethod": [
            {
                "id": "#atproto",
                "type": "Multikey",
                "controller": "did:plc:someoneelseaaaaaaaaaaa",
                "publicKeyMultibase": _KEY,
            },
            {
                "id": "#atproto",
                "type": "Multikey",
                "controller": _DID,
                "publicKeyMultibase": _KEY,
            },
        ],
    }
    receipt = qualify_did_document(
        _evidence(document),
        profile=DidInterpretationProfile.SPACE_AUTHORITY_SIGNING_KEY,
        qualified_at=timestamp("2026-08-21T17:00:00Z"),
    )
    assert receipt.selection is DidBindingSelection.FALLBACK_ACCOUNT_KEY
    assert receipt.selected_key_controller == _DID


def test_endpoint_assessment_mutation_breaks_digest_binding(
    http_fixture_factory, sa4_source_vectors
) -> None:
    server = http_fixture_factory(lambda _: HttpFixtureResponse(body=b"transport-only"))
    binding = _loopback_binding(server)
    provider = HttpSpaceArtifactProvider(
        server.base_url,
        source_endpoint="https://context.invalid.test",
        now=lambda: timestamp("2026-08-21T17:03:00Z"),
    )
    artifact = provider.get_repo(_http_request(sa4_source_vectors, "assessment-bind"))
    acquisition = provider.receipts_for(artifact.source.artifact_ref)[0]
    assessment = assess_http_endpoint_binding(binding, acquisition)

    with pytest.raises(ValidationError) as caught:
        replace(assessment, reason="caller says canonical")
    assert _reason(caught) == "spaces_endpoint_binding_invalid"
