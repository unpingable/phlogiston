from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from community_model import ValidationError
from communitywatch_spaces_alpha import (
    SA9DD_FIXTURE_SHA256,
    ArtifactRequestIdentity,
    AuthenticatedNonceChallenge,
    AuthenticatedSpaceArtifactProvider,
    BoundedReplayWindow,
    FullRepoArtifactRequest,
    RepoOpsArtifactRequest,
    construct_credential_get_request,
    extract_space_repo_evidence,
    qualify_repo_state,
)
from spaces_http_support import HttpFixtureResponse
from spaces_support import (
    qualified_sa4_snapshot,
    sa4_algorithm,
    sa4_author,
    sa4_car,
    sa4_public_key,
    sa4_source_context,
    sa4_space,
    sa5_pages,
    sa5_responses,
    timestamp,
)
from test_sa9d_credential import NOW, _qualify

VECTOR = (
    Path(__file__).resolve().parents[3]
    / "tests/fixtures/spaces-alpha/sa9d-d-authenticated-acquisition.json"
)


def test_sa9dd_public_manifest_is_pinned_and_secret_free() -> None:
    raw = VECTOR.read_bytes()
    document = json.loads(raw)
    assert hashlib.sha256(raw).hexdigest() == SA9DD_FIXTURE_SHA256
    assert not document["secretMaterialPresent"]


def _full(source, request_id="sa9dd-full"):
    return FullRepoArtifactRequest(
        ArtifactRequestIdentity(request_id, sa4_space(source), sa4_author(source))
    )


def _auth(credential, artifact, base_url, *, jti, nonce=None, replay=None):
    return construct_credential_get_request(
        credential=credential,
        artifact_request=artifact,
        base_url=base_url,
        attempt_id=jti,
        jti=jti,
        issued_at=NOW,
        evaluated_at=NOW,
        replay_window=replay or BoundedReplayWindow("sa9dd-attempts"),
        nonce=nonce,
        allow_insecure_loopback_fixture=True,
    )


def test_authenticated_car_reaches_unchanged_sa2_sa1(
    http_fixture_factory, sa4_source_vectors, sa4_vectors
) -> None:
    car = sa4_car(sa4_vectors, "n")
    server = http_fixture_factory(
        lambda request: HttpFixtureResponse(
            body=car, headers={"Content-Type": "application/vnd.ipld.car"}
        )
    )
    credential = _qualify(space=sa4_space(sa4_source_vectors))
    artifact_request = _full(sa4_source_vectors)
    auth = _auth(credential, artifact_request, server.base_url, jti="sa9dd-car-0001")
    provider = AuthenticatedSpaceArtifactProvider(
        source_endpoint="https://space-host.invalid.test"
    )
    artifact = provider.get_repo(artifact_request, auth)
    extraction = extract_space_repo_evidence(
        artifact.sa2_input(), source_vector_identifier="sa9dd:http:state-n"
    )
    qualified = qualify_repo_state(
        extraction.evidence,
        expected_space=sa4_space(sa4_source_vectors),
        expected_author_did=sa4_author(sa4_source_vectors),
        author_public_key=sa4_public_key(sa4_source_vectors),
        signature_algorithm=sa4_algorithm(sa4_source_vectors),
        source=sa4_source_context(sa4_source_vectors),
        verified_at=timestamp("2026-08-21T21:00:21Z"),
    )
    expected = qualified_sa4_snapshot(
        sa4_source_vectors, sa4_vectors, "n", "2026-08-21T21:00:21Z"
    )
    assert qualified.commit.rev == expected.commit.rev
    assert qualified.commit.state_hash == expected.commit.state_hash
    assert tuple(record.cid for record in qualified.records) == tuple(
        record.cid for record in expected.records
    )
    receipt = provider.receipt(artifact.source.artifact_ref)
    assert receipt.credential_sha256 == credential.receipt.credential_sha256
    assert not receipt.automatic_retries and not receipt.redirects_followed
    assert "Authorization" not in json.dumps(receipt.to_provenance())


def test_authenticated_operation_page_preserves_sa5_wire_result(
    http_fixture_factory, sa4_source_vectors, sa5_vectors
) -> None:
    response = sa5_responses(sa5_vectors, "o1CompleteBatch")[0]
    server = http_fixture_factory(
        lambda request: HttpFixtureResponse(
            body=json.dumps(response).encode(),
            headers={"Content-Type": "application/json"},
        )
    )
    credential = _qualify(space=sa4_space(sa4_source_vectors))
    artifact_request = RepoOpsArtifactRequest(
        _full(sa4_source_vectors, "sa9dd-ops").identity,
        since=sa5_pages(sa5_vectors, "o1CompleteBatch")[0].request_since,
    )
    auth = _auth(credential, artifact_request, server.base_url, jti="sa9dd-ops-0001")
    artifact = AuthenticatedSpaceArtifactProvider(
        source_endpoint="https://space-host.invalid.test"
    ).list_repo_ops(artifact_request, auth)
    assert len(artifact.pages) == 1
    assert tuple(op.cid for op in artifact.pages[0].operations) == tuple(
        op["cid"] for op in response["ops"]
    )


def test_nonce_challenge_requires_distinct_fresh_request_attempt(
    http_fixture_factory, sa4_source_vectors, sa4_vectors
) -> None:
    nonce_value = "server-nonce-sa9dd-2"
    car = sa4_car(sa4_vectors, "n")

    def dispatch(request):
        if len(server.requests) == 1:
            return HttpFixtureResponse(
                status=401, body=b"nonce", headers={"DPoP-Nonce": nonce_value}
            )
        return HttpFixtureResponse(body=car)

    server = http_fixture_factory(dispatch)
    credential = _qualify(space=sa4_space(sa4_source_vectors))
    artifact_request = _full(sa4_source_vectors, "sa9dd-nonce")
    provider = AuthenticatedSpaceArtifactProvider(
        source_endpoint="https://space-host.invalid.test"
    )
    first = _auth(credential, artifact_request, server.base_url, jti="sa9dd-nonce-0001")
    with pytest.raises(AuthenticatedNonceChallenge) as caught:
        provider.get_repo(artifact_request, first)
    second = _auth(
        credential,
        artifact_request,
        server.base_url,
        jti="sa9dd-nonce-0002",
        nonce=caught.value.nonce,
    )
    artifact = provider.get_repo(artifact_request, second)
    assert artifact.car_bytes == car
    assert first.receipt.receipt_id != second.receipt.receipt_id
    assert first.receipt.jti != second.receipt.jti
    assert caught.value.receipt.disposition.value == "nonce_challenge"
    assert len(server.requests) == 2


def test_hostile_request_binding_secret_and_transport_boundaries(
    http_fixture_factory, sa4_source_vectors, sa4_vectors
) -> None:
    credential = _qualify(space=sa4_space(sa4_source_vectors))
    artifact_request = _full(sa4_source_vectors)
    server = http_fixture_factory(
        lambda request: HttpFixtureResponse(body=b'{"error":"no car"}')
    )
    auth = _auth(credential, artifact_request, server.base_url, jti="sa9dd-hostile-1")
    provider = AuthenticatedSpaceArtifactProvider(
        source_endpoint="https://space-host.invalid.test"
    )
    artifact = provider.get_repo(artifact_request, auth)
    with pytest.raises(ValidationError):
        extract_space_repo_evidence(artifact.car_bytes, source_vector_identifier="bad")
    with pytest.raises(ValidationError):
        provider.get_repo(
            replace(
                artifact_request,
                identity=replace(artifact_request.identity, request_id="other"),
            ),
            auth,
        )
    secret = credential.credential._for_authenticated_request()
    surfaces = (
        repr(auth)
        + json.dumps(auth.receipt.to_provenance())
        + json.dumps(provider.receipt(artifact.source.artifact_ref).to_provenance())
    )
    assert secret not in surfaces and auth.proof not in surfaces
