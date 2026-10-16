from __future__ import annotations

import json
from dataclasses import replace

from communitywatch_spaces_alpha import (
    PROPOSAL_COMMIT,
    SA9B_BINDING_DOCTRINE,
    SA9B_BINDING_METHOD,
    SA9B_BINDING_VERSION,
    SA9B_DID_SPEC_OBSERVED_DATE,
    SA9B_DID_SPEC_URL,
    SA9B_SOURCE_VECTOR_FORMAT,
    ArtifactRequestIdentity,
    DidBindingSelection,
    DidDocumentInput,
    DidDocumentProvenanceKind,
    DidInterpretationProfile,
    EndpointBindingDisposition,
    FullRepoArtifactRequest,
    HttpSpaceArtifactProvider,
    VerifiedDidBindingClaim,
    assess_http_endpoint_binding,
    extract_space_repo_evidence,
    qualify_did_document,
    qualify_repo_state,
)
from spaces_http_support import HttpFixtureResponse
from spaces_support import (
    sa4_algorithm,
    sa4_author,
    sa4_car,
    sa4_public_key,
    sa4_source_context,
    sa4_space,
    sa9b_document_bytes,
    timestamp,
)

_UNVERIFIED_REPO_CONTEXT = "https://repo-transition.test.invalid"


def _input(vectors, name: str, expected_did: str) -> DidDocumentInput:
    return DidDocumentInput(
        expected_did=expected_did,
        document_bytes=sa9b_document_bytes(vectors, name),
        provenance_kind=DidDocumentProvenanceKind.FIXTURE,
        provenance_ref=f"fixture:sa9b:{name}",
        media_type="application/did+json",
    )


def _qualify(vectors, name, expected_did, profile):
    return qualify_did_document(
        _input(vectors, name, expected_did),
        profile=profile,
        qualified_at=timestamp("2026-08-21T16:00:00Z"),
    )


def test_sa9b_fixture_pins_current_interpretation(sa9b_vectors) -> None:
    assert sa9b_vectors["format"] == SA9B_SOURCE_VECTOR_FORMAT
    assert sa9b_vectors["doctrine"] == SA9B_BINDING_DOCTRINE
    assert sa9b_vectors["compatibility"] == {
        "atprotoDidSpec": SA9B_DID_SPEC_URL,
        "didSpecObservedDate": SA9B_DID_SPEC_OBSERVED_DATE,
        "proposalCommit": PROPOSAL_COMMIT,
        "bindingVersion": SA9B_BINDING_VERSION,
        "method": SA9B_BINDING_METHOD,
    }


def test_did1_ordinary_account_pds_selects_first_valid_origin(sa9b_vectors) -> None:
    receipt = _qualify(
        sa9b_vectors,
        "ordinaryAccount",
        str(sa9b_vectors["accountDid"]),
        DidInterpretationProfile.ACCOUNT_REPO_HOST,
    )

    assert receipt.selection is DidBindingSelection.ACCOUNT_PDS
    assert receipt.selected_identifier == "#atproto_pds"
    assert receipt.selected_type == "AtprotoPersonalDataServer"
    assert receipt.selected_origin == "https://pds.invalid.test"
    assert receipt.endpoint_policy == "https_origin"
    assert receipt.verified_claims == frozenset(
        {
            VerifiedDidBindingClaim.DOCUMENT_ID,
            VerifiedDidBindingClaim.SERVICE_ENTRY,
            VerifiedDidBindingClaim.PDS_SERVICE_TYPE,
            VerifiedDidBindingClaim.SERVICE_ENDPOINT,
        }
    )
    assert receipt.did_resolution_verified is False


def test_did2_dedicated_space_host_is_preferred(sa9b_vectors) -> None:
    receipt = _qualify(
        sa9b_vectors,
        "dedicatedSpaceAuthority",
        str(sa9b_vectors["spaceDid"]),
        DidInterpretationProfile.SPACE_AUTHORITY_HOST,
    )

    assert receipt.selection is DidBindingSelection.DEDICATED_SPACE_HOST
    assert receipt.selected_identifier == "#atproto_space_host"
    assert receipt.selected_type == "AtprotoSpaceHost"
    assert receipt.selected_origin == "https://spaces.invalid.test:8443"
    assert VerifiedDidBindingClaim.SPACE_HOST_FALLBACK not in receipt.verified_claims


def test_did3_space_host_fallback_is_explicit(sa9b_vectors) -> None:
    receipt = _qualify(
        sa9b_vectors,
        "fallbackSpaceAuthority",
        str(sa9b_vectors["spaceDid"]),
        DidInterpretationProfile.SPACE_AUTHORITY_HOST,
    )

    assert receipt.selection is DidBindingSelection.FALLBACK_ACCOUNT_PDS
    assert receipt.selected_identifier == "#atproto_pds"
    assert receipt.selected_origin == "https://fallback.invalid.test"
    assert VerifiedDidBindingClaim.SPACE_HOST_FALLBACK in receipt.verified_claims
    assert VerifiedDidBindingClaim.PDS_SERVICE_TYPE in receipt.verified_claims


def test_did4_dedicated_space_key_is_preferred(sa9b_vectors) -> None:
    receipt = _qualify(
        sa9b_vectors,
        "dedicatedSpaceAuthority",
        str(sa9b_vectors["spaceDid"]),
        DidInterpretationProfile.SPACE_AUTHORITY_SIGNING_KEY,
    )

    keys = sa9b_vectors["publicKeys"]
    assert isinstance(keys, dict)
    assert receipt.selection is DidBindingSelection.DEDICATED_SPACE_KEY
    assert receipt.selected_identifier.endswith("#atproto_space")
    assert receipt.selected_public_key_multibase == keys["spaceP256"]
    assert receipt.selected_key_curve == "p256"
    assert receipt.selected_key_controller == sa9b_vectors["spaceDid"]
    assert VerifiedDidBindingClaim.SPACE_KEY_FALLBACK not in receipt.verified_claims
    assert receipt.did_resolution_verified is False


def test_did5_space_key_fallback_is_explicit(sa9b_vectors) -> None:
    receipt = _qualify(
        sa9b_vectors,
        "fallbackSpaceAuthority",
        str(sa9b_vectors["spaceDid"]),
        DidInterpretationProfile.SPACE_AUTHORITY_SIGNING_KEY,
    )

    assert receipt.selection is DidBindingSelection.FALLBACK_ACCOUNT_KEY
    assert receipt.selected_identifier == "#atproto"
    assert receipt.selected_key_curve == "k256"
    assert VerifiedDidBindingClaim.SPACE_KEY_FALLBACK in receipt.verified_claims


def _loopback_binding(server, expected_did: str):
    document = {
        "id": expected_did,
        "service": [
            {
                "id": "#atproto_pds",
                "type": "AtprotoPersonalDataServer",
                "serviceEndpoint": server.base_url,
            }
        ],
    }
    evidence = DidDocumentInput(
        expected_did=expected_did,
        document_bytes=json.dumps(
            document, sort_keys=True, separators=(",", ":")
        ).encode(),
        provenance_kind=DidDocumentProvenanceKind.FIXTURE,
        provenance_ref="fixture:sa9b:loopback-equivalent",
        allow_insecure_loopback_fixture=True,
    )
    return qualify_did_document(
        evidence,
        profile=DidInterpretationProfile.ACCOUNT_REPO_HOST,
        qualified_at=timestamp("2026-08-21T16:01:00Z"),
    )


def _http_artifact(server, source_vectors, vectors):
    provider = HttpSpaceArtifactProvider(
        server.base_url,
        source_endpoint=_UNVERIFIED_REPO_CONTEXT,
        now=lambda: timestamp("2026-08-21T16:01:01Z"),
    )
    request = FullRepoArtifactRequest(
        ArtifactRequestIdentity(
            request_id="bind-e2e1",
            space=sa4_space(source_vectors),
            repo_did=sa4_author(source_vectors),
        )
    )
    artifact = provider.get_repo(request)
    return provider, artifact


def test_did6_sa9a_contacted_origin_matches_fixture_service_binding(
    http_fixture_factory, sa4_source_vectors, sa4_vectors
) -> None:
    raw = sa4_car(sa4_vectors, "n")
    server = http_fixture_factory(lambda _: HttpFixtureResponse(body=raw))
    binding = _loopback_binding(server, sa4_author(sa4_source_vectors))
    provider, artifact = _http_artifact(server, sa4_source_vectors, sa4_vectors)
    acquisition = provider.receipts_for(artifact.source.artifact_ref)[0]
    assessment = assess_http_endpoint_binding(binding, acquisition)

    assert assessment.disposition is EndpointBindingDisposition.ENDPOINT_MATCH
    assert assessment.selected_origin == server.base_url
    assert assessment.requested_origin == assessment.final_origin == server.base_url
    assert assessment.did_resolution_verified is False
    assert assessment.artifact_validity is False


def test_bind_e2e1_endpoint_match_and_sa1_artifact_qualification_remain_separate(
    http_fixture_factory, sa4_source_vectors, sa4_vectors
) -> None:
    server = http_fixture_factory(
        lambda _: HttpFixtureResponse(body=sa4_car(sa4_vectors, "n"))
    )
    binding = _loopback_binding(server, sa4_author(sa4_source_vectors))
    provider, artifact = _http_artifact(server, sa4_source_vectors, sa4_vectors)
    acquisition = provider.receipts_for(artifact.source.artifact_ref)[0]
    assessment = assess_http_endpoint_binding(binding, acquisition)
    extraction = extract_space_repo_evidence(
        artifact.sa2_input(), source_vector_identifier=artifact.source.artifact_ref
    )
    qualified = qualify_repo_state(
        extraction.evidence,
        expected_space=artifact.request.identity.space,
        expected_author_did=artifact.request.identity.repo_did,
        author_public_key=sa4_public_key(sa4_source_vectors),
        signature_algorithm=sa4_algorithm(sa4_source_vectors),
        source=replace(
            sa4_source_context(sa4_source_vectors),
            repo_host=artifact.source.source_endpoint,
            evidence_ref=artifact.source.artifact_ref,
        ),
        verified_at=timestamp("2026-08-21T16:01:02Z"),
    )

    assert assessment.disposition is EndpointBindingDisposition.ENDPOINT_MATCH
    assert qualified.commit.rev == "3mtaaaabbbbbf"
    assert assessment.artifact_validity is False
    assert binding.did_resolution_verified is False
    assert all(receipt.governance_authority is False for receipt in qualified.receipts)


def test_bind_e2e2_dedicated_space_host_and_key_are_independent(sa9b_vectors) -> None:
    expected = str(sa9b_vectors["spaceDid"])
    host = _qualify(
        sa9b_vectors,
        "dedicatedSpaceAuthority",
        expected,
        DidInterpretationProfile.SPACE_AUTHORITY_HOST,
    )
    key = _qualify(
        sa9b_vectors,
        "dedicatedSpaceAuthority",
        expected,
        DidInterpretationProfile.SPACE_AUTHORITY_SIGNING_KEY,
    )

    assert host.selection is DidBindingSelection.DEDICATED_SPACE_HOST
    assert key.selection is DidBindingSelection.DEDICATED_SPACE_KEY
    assert host.receipt_id != key.receipt_id
    assert host.selected_public_key_multibase is None
    assert key.selected_origin is None


def test_bind_e2e3_both_space_fallbacks_remain_explicit(sa9b_vectors) -> None:
    expected = str(sa9b_vectors["spaceDid"])
    host = _qualify(
        sa9b_vectors,
        "fallbackSpaceAuthority",
        expected,
        DidInterpretationProfile.SPACE_AUTHORITY_HOST,
    )
    key = _qualify(
        sa9b_vectors,
        "fallbackSpaceAuthority",
        expected,
        DidInterpretationProfile.SPACE_AUTHORITY_SIGNING_KEY,
    )

    assert host.selection is DidBindingSelection.FALLBACK_ACCOUNT_PDS
    assert key.selection is DidBindingSelection.FALLBACK_ACCOUNT_KEY
    assert VerifiedDidBindingClaim.SPACE_HOST_FALLBACK in host.verified_claims
    assert VerifiedDidBindingClaim.SPACE_KEY_FALLBACK in key.verified_claims
