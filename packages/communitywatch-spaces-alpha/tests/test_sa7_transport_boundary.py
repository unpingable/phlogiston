from __future__ import annotations

from dataclasses import fields, replace

import pytest

from community_model import ValidationError
from communitywatch_spaces_alpha import (
    SA7_TRANSPORT_BOUNDARY_VERSION,
    ArtifactRequestIdentity,
    FullRepoArtifactRequest,
    ObservedCarArtifact,
    ObservedRepoOpsArtifact,
    OperationSourceContext,
    RepoOpsArtifactRequest,
    SpaceArtifactTransport,
    TransportSourceContext,
    acquire_repo_transition_candidate,
    extract_space_repo_evidence,
    qualify_repo_state,
)
from spaces_support import (
    qualified_sa4_snapshot,
    sa4_algorithm,
    sa4_author,
    sa4_car,
    sa4_public_key,
    sa4_source_context,
    sa4_space,
    sa5_pages,
    timestamp,
)


def _identity(source_vectors: dict[str, object]) -> ArtifactRequestIdentity:
    return ArtifactRequestIdentity(
        request_id="fixture:sa7:request-1",
        space=sa4_space(source_vectors),
        repo_did=sa4_author(source_vectors),
    )


def _source() -> TransportSourceContext:
    return TransportSourceContext(
        transport_name="fixture-future-transport",
        source_endpoint="https://repo-transition.test.invalid",
        artifact_ref="fixture:sa7:artifact-1",
        observed_at=timestamp("2026-08-21T13:00:00Z"),
        asserted_transport_security="fixture-asserted-tls",
        asserted_service_identity="fixture-asserted-repo-host",
    )


def test_sa7_car_artifact_hands_exact_bytes_to_unchanged_sa2_and_sa1(
    sa4_source_vectors, sa4_vectors
) -> None:
    request = FullRepoArtifactRequest(identity=_identity(sa4_source_vectors))
    raw = sa4_car(sa4_vectors, "n")
    artifact = ObservedCarArtifact(request=request, source=_source(), car_bytes=raw)

    assert artifact.sa2_input() is raw
    extraction = extract_space_repo_evidence(
        artifact.sa2_input(), source_vector_identifier="sa7:fixture-car-handoff"
    )
    qualified = qualify_repo_state(
        extraction.evidence,
        expected_space=request.identity.space,
        expected_author_did=request.identity.repo_did,
        author_public_key=sa4_public_key(sa4_source_vectors),
        signature_algorithm=sa4_algorithm(sa4_source_vectors),
        source=sa4_source_context(sa4_source_vectors),
        verified_at=timestamp("2026-08-21T13:00:01Z"),
    )
    assert qualified.commit.rev == "3mtaaaabbbbbf"
    assert artifact.source.to_provenance()["serviceAuthenticated"] is False


def test_sa7_operation_artifact_hands_exact_pages_to_sa5(
    sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    state = qualified_sa4_snapshot(
        sa4_source_vectors, sa4_vectors, "n", "2026-08-20T15:00:02Z"
    )
    pages = sa5_pages(sa5_vectors, "o1CompleteBatch")
    request = RepoOpsArtifactRequest(
        identity=_identity(sa4_source_vectors),
        since=state.commit.rev,
        exclude_values=True,
    )
    artifact = ObservedRepoOpsArtifact(
        request=request,
        source=_source(),
        pages=pages,
    )
    acquisition = acquire_repo_transition_candidate(
        artifact.sa5_input(),
        source_state=state,
        context=OperationSourceContext(
            space=request.identity.space,
            repo_did=request.identity.repo_did,
            repo_host=artifact.source.source_endpoint,
            source_ref=artifact.source.artifact_ref,
            acquired_at=artifact.source.observed_at,
        ),
    )
    assert artifact.sa5_input() is pages
    assert acquisition.transition is not None
    assert acquisition.source_authority is False


def test_sa7_defines_only_a_protocol_and_no_concrete_transport() -> None:
    assert getattr(SpaceArtifactTransport, "_is_protocol", False) is True
    assert _source().boundary_version == SA7_TRANSPORT_BOUNDARY_VERSION
    with pytest.raises(TypeError):
        SpaceArtifactTransport()


def test_sa7_value_types_have_no_secret_or_token_payload_fields() -> None:
    names = {
        item.name.lower()
        for value_type in (
            ArtifactRequestIdentity,
            FullRepoArtifactRequest,
            RepoOpsArtifactRequest,
            TransportSourceContext,
            ObservedCarArtifact,
            ObservedRepoOpsArtifact,
        )
        for item in fields(value_type)
    }
    assert not (
        names
        & {
            "credential",
            "oauth_token",
            "access_token",
            "refresh_token",
            "dpop_private_key",
            "private_key",
            "authorization_header",
            "cookie",
        }
    )


@pytest.mark.parametrize(
    "claim",
    ["credential_material_present", "service_authenticated", "authority_conferred"],
)
def test_sa7_caller_assertions_cannot_upgrade_transport_context(claim: str) -> None:
    with pytest.raises(ValidationError) as caught:
        replace(_source(), **{claim: True})
    assert caught.value.reason_code == "spaces_transport_boundary_invalid"


def test_sa7_operation_artifact_refuses_request_page_mismatch(
    sa4_source_vectors, sa5_vectors
) -> None:
    pages = sa5_pages(sa5_vectors, "o1CompleteBatch")
    request = RepoOpsArtifactRequest(
        identity=_identity(sa4_source_vectors),
        since="3mtaaaabbbbbc",
    )
    with pytest.raises(ValidationError) as caught:
        ObservedRepoOpsArtifact(request=request, source=_source(), pages=pages)
    assert caught.value.reason_code == "spaces_transport_boundary_invalid"
