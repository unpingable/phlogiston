from __future__ import annotations

import hashlib
import json
from datetime import datetime

import pytest

from community_model import ValidationError
from communitywatch_spaces_alpha import (
    AccessContext,
    ArtifactRequestIdentity,
    AuthenticatedSpaceArtifactProvider,
    BoundedReadOnlySpacesObserver,
    BoundedReplayWindow,
    DidInterpretationProfile,
    DidResolutionMethod,
    DidResolutionProvenance,
    DurableSyncStore,
    FullRepoArtifactRequest,
    OperationUnavailableReason,
    RepoOpsArtifactRequest,
    ResolvedDidDocument,
    WriterSetClaim,
    construct_credential_get_request,
    identify_qualified_repo_state,
    qualify_did_document,
)
from spaces_http_support import HttpFixtureResponse
from spaces_support import (
    qualified_sa4_snapshot,
    sa4_author,
    sa4_car,
    sa4_public_key,
    sa4_space,
    sa5_pages,
    sa5_responses,
    timestamp,
)
from test_sa9d_credential import (
    _base58,
    _credential_jwt,
    _credential_key,
    _qualify,
)

NOW = timestamp("2026-08-21T21:00:20Z")
REPO_ORIGIN = "https://repo-transition.test.invalid"


def _identity(sa4_source_vectors):
    author = sa4_author(sa4_source_vectors)
    public_key = sa4_public_key(sa4_source_vectors)
    document = json.dumps(
        {
            "id": author,
            "verificationMethod": [
                {
                    "id": "#atproto",
                    "type": "Multikey",
                    "controller": author,
                    "publicKeyMultibase": "z" + _base58(b"\xe7\x01" + public_key),
                }
            ],
            "service": [
                {
                    "id": "#atproto_pds",
                    "type": "AtprotoPersonalDataServer",
                    "serviceEndpoint": REPO_ORIGIN,
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    resolved = ResolvedDidDocument(
        author,
        document,
        hashlib.sha256(document).hexdigest(),
        DidResolutionMethod.PLC,
        "sha256:" + "a" * 64,
        DidResolutionProvenance.PLC_OPERATION_HISTORY,
        frozenset({"fixture_plc_operation_history"}),
        NOW,
    )
    host = qualify_did_document(
        resolved.to_sa9b_input(),
        profile=DidInterpretationProfile.ACCOUNT_REPO_HOST,
        qualified_at=NOW,
    )
    key = qualify_did_document(
        resolved.to_sa9b_input(),
        profile=DidInterpretationProfile.ACCOUNT_SIGNING_KEY,
        qualified_at=NOW,
    )
    return resolved, host, key


def _observer(tmp_path, source):
    resolved, host, key = _identity(source)
    credential = _qualify(space=sa4_space(source))
    store = DurableSyncStore(tmp_path / "sync.sqlite")
    observer = BoundedReadOnlySpacesObserver(
        sa4_space(source),
        sa4_author(source),
        resolved,
        host,
        key,
        credential,
        store,
        True,
    )
    return observer, credential, store


def _request(source, name):
    return FullRepoArtifactRequest(
        ArtifactRequestIdentity(name, sa4_space(source), sa4_author(source))
    )


def _auth(credential, request, base_url, jti):
    return construct_credential_get_request(
        credential=credential,
        artifact_request=request,
        base_url=base_url,
        attempt_id=jti,
        jti=jti,
        issued_at=NOW,
        evaluated_at=NOW,
        replay_window=BoundedReplayWindow("sa10d:" + jti),
        allow_insecure_loopback_fixture=True,
    )


def _access(credential):
    receipt = credential.receipt
    return AccessContext(
        receipt.space,
        receipt.authority_did,
        receipt.applicant_context_did,
        "https://client.invalid.test/metadata.json",
        datetime.fromtimestamp(receipt.issued_at, tz=NOW.tzinfo),
        datetime.fromtimestamp(receipt.expires_at, tz=NOW.tzinfo),
        NOW,
    )


def test_sa10d_full_read_only_path_reaches_existing_admission_and_store(
    tmp_path, http_fixture_factory, sa4_source_vectors, sa4_vectors
) -> None:
    server = http_fixture_factory(
        lambda request: HttpFixtureResponse(body=sa4_car(sa4_vectors, "n"))
    )
    observer, credential, store = _observer(tmp_path, sa4_source_vectors)
    request = _request(sa4_source_vectors, "sa10d-initial")
    auth = _auth(credential, request, server.base_url, "sa10d-initial-0001")
    provider = AuthenticatedSpaceArtifactProvider(
        source_endpoint=REPO_ORIGIN, clock=lambda: NOW
    )
    expected = sa4_vectors["states"]["n"]
    assert isinstance(expected, dict)
    expected_state = qualified_sa4_snapshot(
        sa4_source_vectors, sa4_vectors, "n", "2026-08-21T21:00:20Z"
    )
    discovery = WriterSetClaim(
        sa4_space(sa4_source_vectors),
        credential.receipt.issuance_host_origin,
        sa4_author(sa4_source_vectors),
        str(expected["rev"]),
        expected_state.commit.state_hash.hex(),
        NOW,
    )

    result = observer.synchronize_snapshot(
        provider,
        request,
        auth,
        writer_discovery=discovery,
        access=_access(credential),
        admitted_collections=frozenset({"invalid.test.spacepost"}),
    )

    assert result.state.commit.rev == expected["rev"]
    assert len(result.admissions) == len(result.state.records) == 2
    assert store.head(identify_qualified_repo_state(result.state)) is not None
    provenance = json.dumps(result.receipt.to_provenance())
    assert result.receipt.acquisition_receipt_id == result.artifact.source.artifact_ref
    assert result.receipt.endpoint_binding_established is False
    assert result.receipt.loopback_fixture_override is True
    assert "governance_authority" in provenance
    assert credential.credential._for_authenticated_request() not in provenance
    store.close()


def test_sa10d_operation_path_uses_sa5_then_unchanged_sa8(
    tmp_path, http_fixture_factory, sa4_source_vectors, sa4_vectors, sa5_vectors
) -> None:
    initial_server = http_fixture_factory(
        lambda request: HttpFixtureResponse(body=sa4_car(sa4_vectors, "n"))
    )
    observer, credential, store = _observer(tmp_path, sa4_source_vectors)
    initial_request = _request(sa4_source_vectors, "sa10d-n")
    initial = observer.synchronize_snapshot(
        AuthenticatedSpaceArtifactProvider(
            source_endpoint=REPO_ORIGIN, clock=lambda: NOW
        ),
        initial_request,
        _auth(credential, initial_request, initial_server.base_url, "sa10d-n-0001"),
    )
    wire = sa5_responses(sa5_vectors, "o1CompleteBatch")[0]
    ops_server = http_fixture_factory(
        lambda request: HttpFixtureResponse(body=json.dumps(wire).encode())
    )
    page = sa5_pages(sa5_vectors, "o1CompleteBatch")[0]
    op_request = RepoOpsArtifactRequest(
        ArtifactRequestIdentity(
            "sa10d-ops", sa4_space(sa4_source_vectors), sa4_author(sa4_source_vectors)
        ),
        since=page.request_since,
    )
    acquisition = observer.acquire_operations(
        AuthenticatedSpaceArtifactProvider(
            source_endpoint=REPO_ORIGIN, clock=lambda: NOW
        ),
        (
            (
                op_request,
                _auth(credential, op_request, ops_server.base_url, "sa10d-ops-0001"),
            ),
        ),
        known_state=initial.state,
    )
    target_server = http_fixture_factory(
        lambda request: HttpFixtureResponse(body=sa4_car(sa4_vectors, "n1"))
    )
    target_request = _request(sa4_source_vectors, "sa10d-n1")
    target_provider = AuthenticatedSpaceArtifactProvider(
        source_endpoint=REPO_ORIGIN, clock=lambda: NOW
    )
    artifact = target_provider.get_repo(
        target_request,
        _auth(credential, target_request, target_server.base_url, "sa10d-n1-0001"),
    )
    trace = observer.record_recovery(
        initial.state,
        acquisition,
        artifact,
        unavailable_reason=None,
        decided_at=NOW,
    )
    assert trace.outcome.value == "qualified_transition"
    assert trace.complete_history is False and trace.authorization is False
    head = store.head(identify_qualified_repo_state(initial.state))
    assert head is not None and head.state["repoRev"] == trace.observed_state.repo_rev
    store.close()


def test_sa10d_hostile_context_and_snapshot_recovery_do_not_upgrade_claims(
    tmp_path, http_fixture_factory, sa4_source_vectors, sa4_vectors
) -> None:
    server = http_fixture_factory(
        lambda request: HttpFixtureResponse(body=sa4_car(sa4_vectors, "n"))
    )
    observer, credential, store = _observer(tmp_path, sa4_source_vectors)
    request = _request(sa4_source_vectors, "sa10d-hostile")
    auth = _auth(credential, request, server.base_url, "sa10d-hostile-0001")
    wrong_provider = AuthenticatedSpaceArtifactProvider(
        source_endpoint="https://substitute.invalid.test", clock=lambda: NOW
    )
    with pytest.raises(ValidationError) as error:
        observer.synchronize_snapshot(wrong_provider, request, auth)
    assert error.value.reason_code == "spaces_read_only_sync_source_mismatch"

    provider = AuthenticatedSpaceArtifactProvider(
        source_endpoint=REPO_ORIGIN, clock=lambda: NOW
    )
    observer.allow_loopback_fixture_transport = False
    with pytest.raises(ValidationError) as error:
        observer.synchronize_snapshot(provider, request, auth)
    assert error.value.reason_code == "spaces_read_only_sync_endpoint_mismatch"
    observer.allow_loopback_fixture_transport = True

    other_key = _credential_key(b"sa10d substituted credential key")
    other_credential = _qualify(
        space=sa4_space(sa4_source_vectors),
        credential_key=other_key,
        credential=_credential_jwt(
            credential_key=other_key, space=sa4_space(sa4_source_vectors)
        ),
    )
    other_auth = _auth(
        other_credential, request, server.base_url, "sa10d-hostile-other-credential"
    )
    with pytest.raises(ValidationError) as error:
        observer.synchronize_snapshot(provider, request, other_auth)
    assert error.value.reason_code == "spaces_read_only_sync_credential_mismatch"

    result = observer.synchronize_snapshot(provider, request, auth)
    wrong_discovery = WriterSetClaim(
        sa4_space(sa4_source_vectors),
        credential.receipt.issuance_host_origin,
        sa4_author(sa4_source_vectors),
        result.state.commit.rev,
        "f" * 64,
        NOW,
    )
    request2 = _request(sa4_source_vectors, "sa10d-hostile-2")
    auth2 = _auth(credential, request2, server.base_url, "sa10d-hostile-0002")
    with pytest.raises(ValidationError) as error:
        observer.synchronize_snapshot(
            provider,
            request2,
            auth2,
            known_state=result.state,
            writer_discovery=wrong_discovery,
            access=_access(credential),
            admitted_collections=frozenset({"invalid.test.spacepost"}),
        )
    assert error.value.reason_code == "spaces_read_only_sync_admission_context_mismatch"

    request3 = _request(sa4_source_vectors, "sa10d-hostile-3")
    auth3 = _auth(credential, request3, server.base_url, "sa10d-hostile-0003")
    artifact = provider.get_repo(request3, auth3)
    trace = observer.record_recovery(
        result.state,
        None,
        artifact,
        unavailable_reason=OperationUnavailableReason.COMPACTED_OR_UNAVAILABLE,
        decided_at=NOW,
    )
    assert trace.outcome.value == "equal_state"
    assert trace.transition_receipt_id is None
    store.close()
