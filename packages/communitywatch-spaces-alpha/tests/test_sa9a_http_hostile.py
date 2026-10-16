from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass, fields, replace
from datetime import datetime

import pytest

from community_model import ValidationError
from communitywatch_spaces_alpha import (
    ArtifactRequestIdentity,
    FullRepoArtifactRequest,
    HttpAcquisitionError,
    HttpSpaceArtifactProvider,
    OperationUnavailableReason,
    RecoveryOutcome,
    RepoOpsArtifactRequest,
    extract_space_repo_evidence,
    qualify_recovery_decision,
    qualify_repo_state,
)
from spaces_http_support import HttpFixtureRequest, HttpFixtureResponse
from spaces_support import (
    qualified_sa4_snapshot,
    qualified_sa4_transition,
    sa4_algorithm,
    sa4_author,
    sa4_car,
    sa4_public_key,
    sa4_source_context,
    sa4_space,
    sa5_responses,
    timestamp,
)

_REPO_HOST = "https://repo-transition.test.invalid"


@dataclass(slots=True)
class _Clock:
    values: list[datetime]

    def __call__(self) -> datetime:
        assert self.values, "test clock exhausted"
        return self.values.pop(0)


def _provider(server, *times: datetime, **options) -> HttpSpaceArtifactProvider:
    values = list(times) or [timestamp("2026-08-21T15:00:00Z")]
    return HttpSpaceArtifactProvider(
        server.base_url,
        source_endpoint=_REPO_HOST,
        now=_Clock(values),
        **options,
    )


def _car_request(source_vectors, request_id: str = "hostile-car"):
    return FullRepoArtifactRequest(
        ArtifactRequestIdentity(
            request_id=request_id,
            space=sa4_space(source_vectors),
            repo_did=sa4_author(source_vectors),
        )
    )


def _ops_request(source_vectors, since: str, request_id: str = "hostile-ops"):
    return RepoOpsArtifactRequest(
        ArtifactRequestIdentity(
            request_id=request_id,
            space=sa4_space(source_vectors),
            repo_did=sa4_author(source_vectors),
        ),
        since=since,
    )


def _qualification_source(source_vectors, artifact):
    return replace(
        sa4_source_context(source_vectors),
        repo_host=artifact.source.source_endpoint,
        evidence_ref=artifact.source.artifact_ref,
    )


def _reason(caught: pytest.ExceptionInfo[HttpAcquisitionError]) -> str | None:
    return caught.value.receipt.failure_reason_code


def test_http_h1_cross_origin_redirect_is_refused_without_fetching_target(
    http_fixture_factory, sa4_source_vectors
) -> None:
    target = http_fixture_factory(lambda _: HttpFixtureResponse(body=b"not reached"))
    source = http_fixture_factory(
        lambda _: HttpFixtureResponse(
            status=302, headers={"Location": f"{target.base_url}/elsewhere"}
        )
    )
    provider = _provider(source)

    with pytest.raises(HttpAcquisitionError) as caught:
        provider.get_repo(_car_request(sa4_source_vectors, "h1"))

    assert _reason(caught) == "spaces_http_cross_origin_redirect"
    assert target.requests == ()
    hop = caught.value.receipt.redirects[-1]
    assert hop.target_url.startswith(target.base_url)
    assert caught.value.receipt.source_authority is False


def test_http_h2_same_origin_redirect_is_preserved_but_untrusted(
    http_fixture_factory, sa4_source_vectors, sa4_vectors
) -> None:
    raw = sa4_car(sa4_vectors, "n")

    def dispatch(request: HttpFixtureRequest) -> HttpFixtureResponse:
        if urllib.parse.urlsplit(request.target).path.endswith("getRepo"):
            return HttpFixtureResponse(status=302, headers={"Location": "/car"})
        return HttpFixtureResponse(body=raw)

    server = http_fixture_factory(dispatch)
    provider = _provider(server)
    artifact = provider.get_repo(_car_request(sa4_source_vectors, "h2"))
    receipt = provider.receipts_for(artifact.source.artifact_ref)[0]

    assert artifact.car_bytes == raw
    assert len(receipt.redirects) == 1
    assert receipt.final_url.endswith("/car")
    assert receipt.did_service_binding_verified is False


def test_http_h3_redirect_loop_has_bounded_refusal(
    http_fixture_factory, sa4_source_vectors
) -> None:
    def dispatch(request: HttpFixtureRequest) -> HttpFixtureResponse:
        path = urllib.parse.urlsplit(request.target).path
        return HttpFixtureResponse(
            status=302,
            headers={"Location": "/b" if path != "/b" else "/a"},
        )

    server = http_fixture_factory(dispatch)
    provider = _provider(server)
    with pytest.raises(HttpAcquisitionError) as caught:
        provider.get_repo(_car_request(sa4_source_vectors, "h3"))
    assert _reason(caught) == "spaces_http_redirect_loop"
    assert len(server.requests) == 3


def test_http_h4_truncated_car_is_a_transport_refusal(
    http_fixture_factory, sa4_source_vectors, sa4_vectors
) -> None:
    raw = sa4_car(sa4_vectors, "n")
    server = http_fixture_factory(
        lambda _: HttpFixtureResponse(
            body=raw,
            declared_length=len(raw),
            close_after_bytes=len(raw) // 2,
        )
    )
    provider = _provider(server)
    with pytest.raises(HttpAcquisitionError) as caught:
        provider.get_repo(_car_request(sa4_source_vectors, "h4"))
    assert _reason(caught) in {
        "spaces_http_truncated_body",
        "spaces_http_content_length_mismatch",
    }
    assert caught.value.receipt.body_complete is False


def test_http_h5_oversized_body_is_bounded(
    http_fixture_factory, sa4_source_vectors
) -> None:
    server = http_fixture_factory(lambda _: HttpFixtureResponse(body=b"x" * 33))
    provider = _provider(server, maximum_car_bytes=32)
    with pytest.raises(HttpAcquisitionError) as caught:
        provider.get_repo(_car_request(sa4_source_vectors, "h5"))
    assert _reason(caught) == "spaces_http_body_too_large"
    assert caught.value.receipt.body_length == 33
    assert caught.value.receipt.maximum_body_bytes == 32


def test_http_h6_json_error_with_car_media_type_is_not_artifact_validity(
    http_fixture_factory, sa4_source_vectors
) -> None:
    server = http_fixture_factory(
        lambda _: HttpFixtureResponse(
            body=b'{"error":"lol no"}',
            headers={"Content-Type": "application/vnd.ipld.car"},
        )
    )
    provider = _provider(server)
    artifact = provider.get_repo(_car_request(sa4_source_vectors, "h6"))
    assert (
        provider.receipts_for(artifact.source.artifact_ref)[0].artifact_validity
        is False
    )
    with pytest.raises(ValidationError):
        extract_space_repo_evidence(
            artifact.sa2_input(), source_vector_identifier="sa9a:h6"
        )


def test_http_h7_valid_car_with_misleading_media_type_is_qualified_only_by_sa2_sa1(
    http_fixture_factory, sa4_source_vectors, sa4_vectors
) -> None:
    raw = sa4_car(sa4_vectors, "n")
    server = http_fixture_factory(
        lambda _: HttpFixtureResponse(body=raw, headers={"Content-Type": "text/plain"})
    )
    provider = _provider(server)
    artifact = provider.get_repo(_car_request(sa4_source_vectors, "h7"))
    receipt = provider.receipts_for(artifact.source.artifact_ref)[0]
    extraction = extract_space_repo_evidence(
        artifact.sa2_input(), source_vector_identifier=artifact.source.artifact_ref
    )
    qualified = qualify_repo_state(
        extraction.evidence,
        expected_space=sa4_space(sa4_source_vectors),
        expected_author_did=sa4_author(sa4_source_vectors),
        author_public_key=sa4_public_key(sa4_source_vectors),
        signature_algorithm=sa4_algorithm(sa4_source_vectors),
        source=_qualification_source(sa4_source_vectors, artifact),
        verified_at=timestamp("2026-08-21T15:00:01Z"),
    )
    assert receipt.response_headers["content-type"] == "text/plain"
    assert receipt.artifact_validity is False
    assert qualified.commit.rev == "3mtaaaabbbbbf"


def test_http_h8_operation_page_cannot_redirect_to_a_new_origin(
    http_fixture_factory, sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    responses = sa5_responses(sa5_vectors, "o2MultiPage")
    target = http_fixture_factory(lambda _: HttpFixtureResponse(body=b"not reached"))

    def dispatch(request: HttpFixtureRequest) -> HttpFixtureResponse:
        cursor = urllib.parse.parse_qs(urllib.parse.urlsplit(request.target).query).get(
            "cursor"
        )
        if cursor is None:
            return HttpFixtureResponse(
                body=json.dumps(responses[0]).encode(),
                headers={"Content-Type": "application/json"},
            )
        return HttpFixtureResponse(
            status=302, headers={"Location": f"{target.base_url}/ops"}
        )

    server = http_fixture_factory(dispatch)
    provider = _provider(
        server,
        timestamp("2026-08-21T15:01:00Z"),
        timestamp("2026-08-21T15:01:01Z"),
    )
    n = qualified_sa4_snapshot(
        sa4_source_vectors, sa4_vectors, "n", "2026-08-20T15:00:02Z"
    )
    with pytest.raises(HttpAcquisitionError) as caught:
        provider.list_repo_ops(_ops_request(sa4_source_vectors, n.commit.rev, "h8"))
    assert _reason(caught) == "spaces_http_cross_origin_redirect"
    assert target.requests == ()


def test_http_h9_retry_is_two_observations_and_neither_is_canonical(
    http_fixture_factory, sa4_source_vectors, sa4_vectors
) -> None:
    bodies = [sa4_car(sa4_vectors, "n"), sa4_car(sa4_vectors, "n1")]

    def dispatch(_: HttpFixtureRequest) -> HttpFixtureResponse:
        return HttpFixtureResponse(body=bodies.pop(0))

    server = http_fixture_factory(dispatch)
    provider = _provider(
        server,
        timestamp("2026-08-21T15:02:00Z"),
        timestamp("2026-08-21T15:03:00Z"),
    )
    first = provider.get_repo(_car_request(sa4_source_vectors, "h9-a"))
    second = provider.get_repo(_car_request(sa4_source_vectors, "h9-b"))
    receipts = (
        provider.receipts_for(first.source.artifact_ref)[0],
        provider.receipts_for(second.source.artifact_ref)[0],
    )
    assert receipts[0].body_sha256 != receipts[1].body_sha256
    assert all(not item.currentness and not item.source_authority for item in receipts)
    assert provider.automatic_retries == 0


def test_http_h10_later_acquisition_time_cannot_launder_stale_snapshot(
    http_fixture_factory, sa4_source_vectors, sa4_vectors
) -> None:
    server = http_fixture_factory(
        lambda _: HttpFixtureResponse(body=sa4_car(sa4_vectors, "n1"))
    )
    provider = _provider(server, timestamp("2030-01-01T00:00:00Z"))
    n = qualified_sa4_snapshot(
        sa4_source_vectors, sa4_vectors, "n", "2026-08-20T15:00:02Z"
    )
    n1 = qualified_sa4_transition(
        n,
        sa4_source_vectors,
        sa4_vectors,
        "n1",
        "n-to-n1",
        "2026-08-20T15:01:02Z",
    ).target
    n2 = qualified_sa4_transition(
        n1,
        sa4_source_vectors,
        sa4_vectors,
        "n2",
        "n1-to-n2",
        "2026-08-20T15:02:02Z",
    ).target
    artifact = provider.get_repo(_car_request(sa4_source_vectors, "h10"))
    trace = qualify_recovery_decision(
        n2,
        operation_acquisition=None,
        operation_unavailable_reason=OperationUnavailableReason.COMPACTED_OR_UNAVAILABLE,
        full_repo_artifact=artifact,
        author_public_key=sa4_public_key(sa4_source_vectors),
        signature_algorithm=sa4_algorithm(sa4_source_vectors),
        qualification_source=_qualification_source(sa4_source_vectors, artifact),
        qualified_at=timestamp("2030-01-01T00:00:01Z"),
        decided_at=timestamp("2030-01-01T00:00:02Z"),
    )
    assert trace.outcome is RecoveryOutcome.INSUFFICIENT_EVIDENCE
    assert trace.currentness is False


def test_http_h11_authority_headers_are_discarded(
    http_fixture_factory, sa4_source_vectors, sa4_vectors
) -> None:
    server = http_fixture_factory(
        lambda _: HttpFixtureResponse(
            body=sa4_car(sa4_vectors, "n"),
            headers={
                "X-Authoritative": "true",
                "X-Space-Authority": "did:plc:attacker",
                "X-Complete-History": "yes",
            },
        )
    )
    provider = _provider(server)
    artifact = provider.get_repo(_car_request(sa4_source_vectors, "h11"))
    provenance = provider.receipts_for(artifact.source.artifact_ref)[0].to_provenance()
    retained = provenance["responseHeaders"]
    assert "x-authoritative" not in retained
    assert "x-space-authority" not in retained
    assert "x-complete-history" not in retained
    assert provenance["sourceAuthority"] is False
    assert provenance["governanceAuthority"] is False


def test_http_h12_secret_headers_never_enter_requests_receipts_or_logs(
    http_fixture_factory, sa4_source_vectors, sa4_vectors, caplog
) -> None:
    secrets = {
        "Authorization": "Bearer fixture-secret",
        "Cookie": "session=fixture-cookie",
        "Set-Cookie": "server=fixture-set-cookie",
    }
    server = http_fixture_factory(
        lambda _: HttpFixtureResponse(body=sa4_car(sa4_vectors, "n"), headers=secrets)
    )
    provider = _provider(server)
    artifact = provider.get_repo(_car_request(sa4_source_vectors, "h12"))
    receipt = provider.receipts_for(artifact.source.artifact_ref)[0]
    serialized = repr(receipt.to_provenance()) + caplog.text

    assert "fixture-secret" not in serialized
    assert "fixture-cookie" not in serialized
    assert "fixture-set-cookie" not in serialized
    assert "authorization" not in receipt.request_headers
    assert "cookie" not in receipt.request_headers
    assert "set-cookie" not in receipt.response_headers
    assert "authorization" not in server.requests[0].headers
    assert "cookie" not in server.requests[0].headers
    names = {item.name.lower() for item in fields(type(receipt))}
    assert not names & {"credential", "access_token", "private_key", "cookie"}


def test_http_timeout_is_explicit_and_no_hidden_retry_occurs(
    http_fixture_factory, sa4_source_vectors
) -> None:
    server = http_fixture_factory(
        lambda _: HttpFixtureResponse(body=b"late", delay_seconds=0.2)
    )
    provider = _provider(server, timeout_seconds=0.05)
    with pytest.raises(HttpAcquisitionError) as caught:
        provider.get_repo(_car_request(sa4_source_vectors, "timeout"))
    assert _reason(caught) == "spaces_http_timeout"
    assert len(server.requests) == 1
    assert caught.value.receipt.automatic_retries == 0


def test_non_identity_content_encoding_is_refused_without_transformation(
    http_fixture_factory, sa4_source_vectors
) -> None:
    server = http_fixture_factory(
        lambda _: HttpFixtureResponse(
            body=b"not-gzip", headers={"Content-Encoding": "gzip"}
        )
    )
    provider = _provider(server)
    with pytest.raises(HttpAcquisitionError) as caught:
        provider.get_repo(_car_request(sa4_source_vectors, "encoding"))
    assert _reason(caught) == "spaces_http_content_encoding_unsupported"
    assert caught.value.receipt.content_transformation == "identity-only"


def test_redirect_url_credentials_are_never_followed_or_retained(
    http_fixture_factory, sa4_source_vectors
) -> None:
    def dispatch(_: HttpFixtureRequest) -> HttpFixtureResponse:
        return HttpFixtureResponse(
            status=302,
            headers={"Location": "/next"},
        )

    server = http_fixture_factory(dispatch)
    secret_target = (
        f"http://user:synthetic-secret@{server.base_url.removeprefix('http://')}/next"
    )

    def credential_redirect(_: HttpFixtureRequest) -> HttpFixtureResponse:
        return HttpFixtureResponse(status=302, headers={"Location": secret_target})

    server.server.dispatch = credential_redirect
    provider = _provider(server)
    with pytest.raises(HttpAcquisitionError) as caught:
        provider.get_repo(_car_request(sa4_source_vectors, "redirect-secret"))
    assert _reason(caught) == "spaces_http_redirect_credentials"
    assert "synthetic-secret" not in repr(caught.value.receipt.to_provenance())
    assert len(server.requests) == 1
