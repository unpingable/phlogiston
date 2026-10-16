from __future__ import annotations

import hashlib
import json
import urllib.parse
from dataclasses import dataclass, replace
from datetime import datetime

from communitywatch_spaces_alpha import (
    REFERENCE_COMMIT,
    SA9A_HTTP_DOCTRINE,
    SA9A_HTTP_METHOD,
    SA9A_HTTP_VERSION,
    SA9A_SOURCE_VECTOR_FORMAT,
    ArtifactRequestIdentity,
    FullRepoArtifactRequest,
    HttpSpaceArtifactProvider,
    OperationAcquisitionStatus,
    OperationSourceContext,
    RecoveryOutcome,
    RepoOpsArtifactRequest,
    SpaceRepoEvidence,
    acquire_repo_transition_candidate,
    extract_space_repo_evidence,
    qualify_recovery_decision,
    qualify_repo_state,
    qualify_repo_transition,
)
from spaces_http_support import HttpFixtureRequest, HttpFixtureResponse
from spaces_support import (
    qualified_sa4_snapshot,
    qualified_sa4_transition,
    sa4_algorithm,
    sa4_author,
    sa4_car,
    sa4_evidence,
    sa4_public_key,
    sa4_source_context,
    sa4_space,
    sa5_pages,
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


def _identity(source_vectors, request_id: str) -> ArtifactRequestIdentity:
    return ArtifactRequestIdentity(
        request_id=request_id,
        space=sa4_space(source_vectors),
        repo_did=sa4_author(source_vectors),
    )


def _provider(server, *times: datetime, **options) -> HttpSpaceArtifactProvider:
    values = list(times) or [timestamp("2026-08-21T14:00:00Z")]
    return HttpSpaceArtifactProvider(
        server.base_url,
        source_endpoint=_REPO_HOST,
        now=_Clock(values),
        **options,
    )


def _json_response(value: object) -> HttpFixtureResponse:
    return HttpFixtureResponse(
        body=json.dumps(value, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json"},
    )


def _qualification_source(source_vectors, artifact):
    return replace(
        sa4_source_context(source_vectors),
        repo_host=artifact.source.source_endpoint,
        evidence_ref=artifact.source.artifact_ref,
    )


def _qualify_snapshot(source_vectors, artifact, verified_at: str):
    extracted = extract_space_repo_evidence(
        artifact.sa2_input(),
        source_vector_identifier=artifact.source.artifact_ref,
    )
    return qualify_repo_state(
        extracted.evidence,
        expected_space=artifact.request.identity.space,
        expected_author_did=artifact.request.identity.repo_did,
        author_public_key=sa4_public_key(source_vectors),
        signature_algorithm=sa4_algorithm(source_vectors),
        source=_qualification_source(source_vectors, artifact),
        verified_at=timestamp(verified_at),
    )


def _acquire(source_vectors, source_state, artifact):
    return acquire_repo_transition_candidate(
        artifact.sa5_input(),
        source_state=source_state,
        context=OperationSourceContext(
            space=artifact.request.identity.space,
            repo_did=artifact.request.identity.repo_did,
            repo_host=artifact.source.source_endpoint,
            source_ref=artifact.source.artifact_ref,
            acquired_at=artifact.source.observed_at,
        ),
    )


def test_sa9a_fixture_pins_transport_contract(sa9a_vectors) -> None:
    assert sa9a_vectors["format"] == SA9A_SOURCE_VECTOR_FORMAT
    assert sa9a_vectors["doctrine"] == SA9A_HTTP_DOCTRINE
    assert sa9a_vectors["compatibility"] == {
        "referenceCommit": REFERENCE_COMMIT,
        "transportVersion": SA9A_HTTP_VERSION,
        "method": SA9A_HTTP_METHOD,
    }
    assert sa9a_vectors["policy"] == {
        "methods": ["GET"],
        "redirects": "same-origin-only",
        "automaticRetries": 0,
        "contentTransformation": "identity-only",
        "contentTypeAuthority": False,
        "tlsDidBinding": False,
    }


def test_http1_and_e2e1_full_car_acquisition_reproduces_sa1_claims(
    http_fixture_factory, sa4_source_vectors, sa4_vectors
) -> None:
    raw = sa4_car(sa4_vectors, "n")
    server = http_fixture_factory(
        lambda _: HttpFixtureResponse(
            body=raw, headers={"Content-Type": "application/vnd.ipld.car"}
        )
    )
    provider = _provider(server)
    artifact = provider.get_repo(
        FullRepoArtifactRequest(_identity(sa4_source_vectors, "http1"))
    )

    assert artifact.sa2_input() == raw
    receipt = provider.receipts_for(artifact.source.artifact_ref)[0]
    assert receipt.body_sha256 == hashlib.sha256(raw).hexdigest()
    assert receipt.status == 200
    assert receipt.artifact_validity is False
    qualified = _qualify_snapshot(sa4_source_vectors, artifact, "2026-08-21T14:00:01Z")
    direct = qualified_sa4_snapshot(
        sa4_source_vectors, sa4_vectors, "n", "2026-08-21T14:00:01Z"
    )
    assert qualified.commit == direct.commit
    assert qualified.lthash_state == direct.lthash_state
    assert qualified.records == direct.records
    assert tuple(item.verified_claims for item in qualified.receipts) == tuple(
        item.verified_claims for item in direct.receipts
    )


def test_http2_operation_page_reproduces_sa5_candidate(
    http_fixture_factory, sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    response = sa5_responses(sa5_vectors, "o1CompleteBatch")[0]
    expected_pages = sa5_pages(sa5_vectors, "o1CompleteBatch")
    server = http_fixture_factory(lambda _: _json_response(response))
    provider = _provider(server, expected_pages[0].received_at)
    source = qualified_sa4_snapshot(
        sa4_source_vectors, sa4_vectors, "n", "2026-08-20T15:00:02Z"
    )
    artifact = provider.list_repo_ops(
        RepoOpsArtifactRequest(
            _identity(sa4_source_vectors, "http2"), since=source.commit.rev
        )
    )

    assert artifact.pages == expected_pages
    acquisition = _acquire(sa4_source_vectors, source, artifact)
    assert acquisition.status is OperationAcquisitionStatus.TRANSITION_CANDIDATE
    assert (
        acquisition.transition
        == sa4_evidence(
            sa4_source_vectors,
            sa4_vectors,
            "n1",
            transition_name="n-to-n1",
        ).transition
    )


def test_http3_multi_page_sequence_is_explicit_and_preserved(
    http_fixture_factory, sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    responses = sa5_responses(sa5_vectors, "o2MultiPage")
    expected_pages = sa5_pages(sa5_vectors, "o2MultiPage")

    def dispatch(request: HttpFixtureRequest) -> HttpFixtureResponse:
        cursor = urllib.parse.parse_qs(urllib.parse.urlsplit(request.target).query).get(
            "cursor", [None]
        )[0]
        ordinal = {None: 0, "3mtaaaabbbbbh/0": 1, "3mtaaaabbbbbh/1": 2}[cursor]
        return _json_response(responses[ordinal])

    server = http_fixture_factory(dispatch)
    provider = _provider(server, *(page.received_at for page in expected_pages))
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
    artifact = provider.list_repo_ops(
        RepoOpsArtifactRequest(
            _identity(sa4_source_vectors, "http3"), since=n1.commit.rev
        )
    )

    assert artifact.pages == expected_pages
    assert len(server.requests) == 3
    assert tuple(
        urllib.parse.parse_qs(urllib.parse.urlsplit(item.target).query).get("cursor")
        for item in server.requests
    ) == (None, ["3mtaaaabbbbbh/0"], ["3mtaaaabbbbbh/1"])
    assert len(provider.receipts_for(artifact.source.artifact_ref)) == 3
    assert (
        _acquire(sa4_source_vectors, n1, artifact).transition
        == sa4_evidence(
            sa4_source_vectors,
            sa4_vectors,
            "n2",
            transition_name="n1-to-n2",
        ).transition
    )


def test_http4_repeat_acquisition_is_two_events_without_confidence_upgrade(
    http_fixture_factory, sa4_source_vectors, sa4_vectors
) -> None:
    raw = sa4_car(sa4_vectors, "n")
    server = http_fixture_factory(lambda _: HttpFixtureResponse(body=raw))
    provider = _provider(
        server,
        timestamp("2026-08-21T14:03:00Z"),
        timestamp("2026-08-21T14:04:00Z"),
    )
    first = provider.get_repo(
        FullRepoArtifactRequest(_identity(sa4_source_vectors, "http4-a"))
    )
    second = provider.get_repo(
        FullRepoArtifactRequest(_identity(sa4_source_vectors, "http4-b"))
    )
    first_receipt = provider.receipts_for(first.source.artifact_ref)[0]
    second_receipt = provider.receipts_for(second.source.artifact_ref)[0]

    assert first_receipt.receipt_id != second_receipt.receipt_id
    assert first_receipt.observed_at != second_receipt.observed_at
    assert first_receipt.body_sha256 == second_receipt.body_sha256
    assert first_receipt.currentness is second_receipt.currentness is False
    assert provider.automatic_retries == 0


def test_e2e2_http_ops_qualify_the_same_sa4_transition(
    http_fixture_factory, sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    expected_page = sa5_pages(sa5_vectors, "o1CompleteBatch")[0]
    response = sa5_responses(sa5_vectors, "o1CompleteBatch")[0]
    server = http_fixture_factory(lambda _: _json_response(response))
    provider = _provider(server, expected_page.received_at)
    source = qualified_sa4_snapshot(
        sa4_source_vectors, sa4_vectors, "n", "2026-08-20T15:00:02Z"
    )
    artifact = provider.list_repo_ops(
        RepoOpsArtifactRequest(
            _identity(sa4_source_vectors, "e2e2"), since=source.commit.rev
        )
    )
    acquisition = _acquire(sa4_source_vectors, source, artifact)
    target = sa4_evidence(sa4_source_vectors, sa4_vectors, "n1")
    evidence = SpaceRepoEvidence(
        source_vector_identifier=target.source_vector_identifier,
        proof_kind=target.proof_kind,
        protocol_assumption=target.protocol_assumption,
        commit_bytes=target.commit_bytes,
        index_bytes=target.index_bytes,
        record_blocks=target.record_blocks,
        transition=acquisition.transition,
    )
    qualified = qualify_repo_transition(
        source,
        evidence,
        expected_space=sa4_space(sa4_source_vectors),
        expected_author_did=sa4_author(sa4_source_vectors),
        author_public_key=sa4_public_key(sa4_source_vectors),
        signature_algorithm=sa4_algorithm(sa4_source_vectors),
        source=sa4_source_context(sa4_source_vectors),
        verified_at=timestamp("2026-08-21T14:05:00Z"),
    )
    assert qualified.target.commit.rev == "3mtaaaabbbbbg"
    assert qualified.receipt.verified_claims
    assert qualified.receipt.authorization is False


def test_e2e3_partial_http_ops_and_http_car_remain_snapshot_only(
    http_fixture_factory, sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    responses = sa5_responses(sa5_vectors, "o2MultiPage")
    pages = sa5_pages(sa5_vectors, "o2MultiPage")

    def dispatch(request: HttpFixtureRequest) -> HttpFixtureResponse:
        path = urllib.parse.urlsplit(request.target).path
        if path.endswith("getRepo"):
            return HttpFixtureResponse(body=sa4_car(sa4_vectors, "n2"))
        cursor = urllib.parse.parse_qs(urllib.parse.urlsplit(request.target).query).get(
            "cursor", [None]
        )[0]
        ordinal = 0 if cursor is None else 1
        return _json_response(responses[ordinal])

    server = http_fixture_factory(dispatch)
    provider = _provider(
        server,
        pages[0].received_at,
        pages[1].received_at,
        timestamp("2026-08-21T14:06:00Z"),
        maximum_operation_pages=2,
    )
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
    ops_artifact = provider.list_repo_ops(
        RepoOpsArtifactRequest(
            _identity(sa4_source_vectors, "e2e3-ops"), since=n1.commit.rev
        )
    )
    acquisition = _acquire(sa4_source_vectors, n1, ops_artifact)
    assert acquisition.status is OperationAcquisitionStatus.PARTIAL_RETRIEVAL
    car_artifact = provider.get_repo(
        FullRepoArtifactRequest(_identity(sa4_source_vectors, "e2e3-car"))
    )
    trace = qualify_recovery_decision(
        n1,
        operation_acquisition=acquisition,
        operation_unavailable_reason=None,
        full_repo_artifact=car_artifact,
        author_public_key=sa4_public_key(sa4_source_vectors),
        signature_algorithm=sa4_algorithm(sa4_source_vectors),
        qualification_source=_qualification_source(sa4_source_vectors, car_artifact),
        qualified_at=timestamp("2026-08-21T14:06:01Z"),
        decided_at=timestamp("2026-08-21T14:06:02Z"),
    )
    assert trace.outcome is RecoveryOutcome.SNAPSHOT_ONLY
    assert trace.transition_receipt_id is None
