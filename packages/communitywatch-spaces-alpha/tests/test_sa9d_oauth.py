from __future__ import annotations

import hashlib
import json
import pickle
import urllib.parse
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from community_model import ValidationError
from communitywatch_spaces_alpha import (
    SA9D_FIXTURE_SHA256,
    BoundedReplayWindow,
    DidInterpretationProfile,
    DidResolutionMethod,
    DidResolutionProvenance,
    DpopNonceContext,
    DpopSessionKey,
    FrozenEffectAuthorization,
    ResolvedDidDocument,
    SecretAccessToken,
    SpaceAction,
    SpaceIdentity,
    SpaceProtocolRequest,
    canonical_dpop_htu,
    compose_identity_bound_request,
    construct_dpop_get_request,
    evaluate_space_protocol_grant,
    parse_space_scope,
    qualify_did_document,
    qualify_oauth_grant,
    verify_dpop_get_request,
)

NOW = datetime.fromisoformat("2026-08-21T20:00:00+00:00")
USER = "did:plc:sa9dfixtureuser"
AUTHORITY = "did:plc:sa9dspaceauthority"
SPACE = SpaceIdentity(AUTHORITY, "invalid.test.communityspace", "forum")
COLLECTION_A = "invalid.test.spacepost"
COLLECTION_B = "invalid.test.spaceeffect"
SCOPE_READ = (
    "space:invalid.test.communityspace?"
    "authority=did%3Aplc%3Asa9dspaceauthority&skey=forum&action=read"
)
SCOPE_READ_SELF = (
    "space:invalid.test.communityspace?"
    "authority=did%3Aplc%3Asa9dspaceauthority&skey=forum"
    "&collection=invalid.test.spacepost&action=read_self"
)
VECTOR = (
    Path(__file__).resolve().parents[3]
    / "tests/fixtures/spaces-alpha/sa9d-a-oauth-dpop.json"
)


def _key(label: bytes = b"sa9d-a fixture key A") -> DpopSessionKey:
    return DpopSessionKey.from_test_seed(label, session_ref="fixture-session-a")


def _token(label: bytes = b"sa9d-a fixture token A") -> SecretAccessToken:
    return SecretAccessToken(hashlib.sha256(label).hexdigest())


def _grant(
    *,
    granted_scope: str = f"atproto {SCOPE_READ}",
    requested_scope: str | None = None,
    token: SecretAccessToken | None = None,
    key: DpopSessionKey | None = None,
    subject: str = USER,
):
    return qualify_oauth_grant(
        expected_account_did=USER,
        token_subject=subject,
        authorization_server_issuer="https://auth.invalid.test",
        client_id="https://client.invalid.test/oauth.json",
        requested_scope=requested_scope or granted_scope,
        granted_scope=granted_scope,
        access_token=token or _token(),
        dpop_key=key or _key(),
        observed_at=NOW,
        provenance_ref="fixture:sa9d-a:token-response",
    )


def _protocol_evaluation(
    grant=None,
    *,
    action: SpaceAction = SpaceAction.READ,
    repo_did: str = USER,
    collection: str | None = COLLECTION_A,
    declarations: frozenset[str] = frozenset({COLLECTION_A}),
):
    grant = grant or _grant()
    return evaluate_space_protocol_grant(
        grant.receipt,
        SpaceProtocolRequest(SPACE, repo_did, action, collection),
        declaration_collections=declarations,
        declaration_evidence_ref="fixture:space-type:current",
    )


def _url(*, origin: str = "https://pds.invalid.test", repo: str = USER) -> str:
    return (
        origin
        + "/xrpc/com.atproto.space.getRepo?"
        + urllib.parse.urlencode({"space": SPACE.uri, "repo": repo})
    )


def _nonce(
    *, origin: str = "https://pds.invalid.test", value: str = "nonce-fixture-123"
) -> DpopNonceContext:
    return DpopNonceContext(origin, "fixture-session-a", value, NOW)


def _request(
    *,
    grant=None,
    key=None,
    token=None,
    url: str | None = None,
    nonce=None,
    jti: str = "jti-fixture-0001",
    issued_at: datetime = NOW,
    evaluation=None,
    replay=None,
):
    key = key or _key()
    grant = grant or _grant(token=token, key=key)
    return construct_dpop_get_request(
        grant=grant,
        dpop_key=key,
        url=url or _url(),
        nonce=nonce or _nonce(),
        jti=jti,
        issued_at=issued_at,
        evaluated_at=NOW,
        replay_window=replay or BoundedReplayWindow("fixture-session-a"),
        space_evaluation=evaluation or _protocol_evaluation(grant),
    )


def _resign(proof: str, key: DpopSessionKey, mutator) -> str:
    header, payload, _ = proof.split(".")
    padding = "=" * (-len(payload) % 4)
    import base64

    decoded = json.loads(base64.urlsafe_b64decode(payload + padding))
    mutator(decoded)
    encoded = (
        base64.urlsafe_b64encode(
            json.dumps(decoded, sort_keys=True, separators=(",", ":")).encode()
        )
        .rstrip(b"=")
        .decode()
    )
    signing = f"{header}.{encoded}".encode()
    signature = (
        base64.urlsafe_b64encode(key._sign_dpop_proof(signing)).rstrip(b"=").decode()
    )
    return f"{header}.{encoded}.{signature}"


def test_auth1_valid_bounded_get_and_auth7_protocol_read_is_not_governance() -> None:
    evaluation = _protocol_evaluation()
    request = _request(evaluation=evaluation)

    assert evaluation.permitted and evaluation.protocol_authorization_only
    assert not evaluation.governance_authority
    assert request.receipt.method == "GET"
    assert not request.receipt.governance_authority
    assert set(request.controlled_headers()) == {
        "Authorization",
        "DPoP",
        "Accept-Encoding",
    }


def test_fixture_public_vector_replays_without_secret_material() -> None:
    vector = json.loads(VECTOR.read_bytes())
    request = _request()

    assert hashlib.sha256(VECTOR.read_bytes()).hexdigest() == SA9D_FIXTURE_SHA256
    assert vector["publicJwk"] == dict(_key().public_jwk)
    assert vector["jwkThumbprint"] == _key().thumbprint
    assert vector["accessTokenSha256"] == request.receipt.access_token_sha256
    assert vector["ath"] == request.receipt.ath
    assert vector["grantReceiptId"] == request.grant.receipt.receipt_id
    assert vector["proofSha256"] == request.receipt.proof_sha256
    assert vector["requestReceiptId"] == request.receipt.receipt_id
    assert vector["request"]["nonceSha256"] == request.receipt.nonce_sha256
    assert not vector["secretMaterialPresent"]


def test_auth2_exact_ath_and_auth3_exact_method_and_auth4_exact_target() -> None:
    request = _request()
    assert request.receipt.ath == _token().ath
    assert request.receipt.canonical_htu == canonical_dpop_htu(_url())
    assert request.receipt.method == "GET"


def test_auth5_server_nonce_and_auth10_deterministic_proof() -> None:
    first = _request()
    second = _request()
    assert first.proof == second.proof
    assert first.receipt.proof_sha256 == second.receipt.proof_sha256
    assert first.receipt.nonce_sha256 == _nonce().digest


def test_auth6_only_returned_granted_scope_is_evaluated() -> None:
    requested = f"atproto {SCOPE_READ} space:invalid.test.other?authority=*"
    grant = _grant(
        granted_scope=f"atproto {SCOPE_READ_SELF}", requested_scope=requested
    )
    whole_space = _protocol_evaluation(
        grant, action=SpaceAction.READ, repo_did="did:plc:other"
    )
    assert not whole_space.permitted


def test_alpha_scope_parser_preserves_defaults_and_manage_without_using_it() -> None:
    parsed = parse_space_scope(
        "space:invalid.test.communityspace?manage=create&manage=delete"
    )

    assert parsed.authority == "self" and parsed.skey == "*"
    assert parsed.collection_default_dynamic
    assert tuple(action.value for action in parsed.actions) == (
        "read",
        "create",
        "update",
        "delete",
    )
    assert tuple(action.value for action in parsed.manage) == ("create", "delete")


def test_auth8_read_self_is_own_repo_and_collection_bound_while_read_implies_it() -> (
    None
):
    narrow = _grant(granted_scope=f"atproto {SCOPE_READ_SELF}")
    assert _protocol_evaluation(narrow, action=SpaceAction.READ_SELF).permitted
    assert not _protocol_evaluation(
        narrow, action=SpaceAction.READ_SELF, repo_did="did:plc:other"
    ).permitted
    assert not _protocol_evaluation(
        narrow, action=SpaceAction.READ_SELF, collection=COLLECTION_B
    ).permitted
    broad = _grant()
    assert _protocol_evaluation(
        broad, action=SpaceAction.READ_SELF, repo_did="did:plc:other"
    ).permitted


def test_auth9_and_e2e1_identity_receipts_compose_without_collapsing() -> None:
    document = json.dumps(
        {
            "id": USER,
            "service": [
                {
                    "id": "#atproto_pds",
                    "type": "AtprotoPersonalDataServer",
                    "serviceEndpoint": "https://pds.invalid.test",
                }
            ],
        },
        separators=(",", ":"),
    ).encode()
    resolved = ResolvedDidDocument(
        expected_did=USER,
        document_bytes=document,
        document_sha256=hashlib.sha256(document).hexdigest(),
        method=DidResolutionMethod.PLC,
        method_receipt_id="sha256:" + "1" * 64,
        provenance=DidResolutionProvenance.PLC_OPERATION_HISTORY,
        verified_claims=frozenset({"fixture_plc_history"}),
        observed_at=NOW,
    )
    binding = qualify_did_document(
        resolved.to_sa9b_input(),
        profile=DidInterpretationProfile.ACCOUNT_REPO_HOST,
        qualified_at=NOW,
    )
    request = _request()
    composition = compose_identity_bound_request(resolved, binding, request)

    assert composition.endpoint_matches
    assert composition.resolution_receipt_id != composition.did_binding_receipt_id
    assert composition.did_binding_receipt_id != composition.request_binding_receipt_id
    assert not composition.governance_authority


def test_auth_e2e2_request_shape_does_not_change_sa9a_semantics() -> None:
    request = _request()
    assert request.url == _url()
    assert request.method == "GET"
    assert "Authorization" not in request.receipt.to_provenance()


def test_auth_h15_and_e2e3_dynamic_protocol_widening_does_not_mutate_frozen_effect() -> (
    None
):
    bare = (
        "space:invalid.test.communityspace?"
        "authority=did%3Aplc%3Asa9dspaceauthority&skey=forum"
    )
    grant = _grant(granted_scope=f"atproto {bare}")
    write_b = SpaceProtocolRequest(SPACE, USER, SpaceAction.CREATE, COLLECTION_B)
    at_t0 = evaluate_space_protocol_grant(
        grant.receipt,
        write_b,
        declaration_collections=frozenset({COLLECTION_A}),
        declaration_evidence_ref="fixture:declaration:t0",
    )
    frozen = FrozenEffectAuthorization(
        authorization_id="fixture:frozen:t0",
        space=SPACE,
        effective_collections=frozenset({COLLECTION_A}),
        authorized_at=NOW,
        scope=bare,
        declaration_evidence_ref="fixture:declaration:t0",
        resolved_from_dynamic_default=True,
    )
    at_t1 = evaluate_space_protocol_grant(
        grant.receipt,
        write_b,
        declaration_collections=frozenset({COLLECTION_A, COLLECTION_B}),
        declaration_evidence_ref="fixture:declaration:t1",
    )

    assert not at_t0.permitted
    assert at_t1.permitted and at_t1.dynamic_collection_default
    assert not frozen.permits(COLLECTION_B)


def test_auth_h1_h2_h17_target_method_and_redirect_substitution_refuse() -> None:
    key = _key()
    grant = _grant(key=key)
    request = _request(grant=grant, key=key)
    for url, method in (
        (_url(origin="https://other.invalid.test"), "GET"),
        (
            _url().replace(
                "com.atproto.space.getRepo", "com.atproto.space.listRepoOps"
            ),
            "GET",
        ),
        (_url(), "POST"),
    ):
        with pytest.raises(ValidationError):
            verify_dpop_get_request(
                request_url=url,
                method=method,
                proof=request.proof,
                grant=grant,
                expected_key=key,
                expected_nonce=_nonce(),
                evaluated_at=NOW,
                replay_window=BoundedReplayWindow("hostile"),
                space_evaluation=_protocol_evaluation(grant),
            )


def test_auth_h3_access_token_substitution_refuses() -> None:
    request = _request()
    other = _grant(token=_token(b"different"))
    with pytest.raises(ValidationError):
        verify_dpop_get_request(
            request_url=request.url,
            method="GET",
            proof=request.proof,
            grant=other,
            expected_key=_key(),
            expected_nonce=_nonce(),
            evaluated_at=NOW,
            replay_window=BoundedReplayWindow("hostile"),
            space_evaluation=_protocol_evaluation(other),
        )


def test_auth_h4_key_substitution_and_h5_signature_mutation_refuse() -> None:
    request = _request()
    other_key = _key(b"other key")
    with pytest.raises(ValidationError):
        verify_dpop_get_request(
            request_url=request.url,
            method="GET",
            proof=request.proof,
            grant=request.grant,
            expected_key=other_key,
            expected_nonce=_nonce(),
            evaluated_at=NOW,
            replay_window=BoundedReplayWindow("hostile-key"),
            space_evaluation=_protocol_evaluation(request.grant),
        )
    mutated = request.proof[:-1] + ("A" if request.proof[-1] != "A" else "B")
    with pytest.raises(ValidationError):
        verify_dpop_get_request(
            request_url=request.url,
            method="GET",
            proof=mutated,
            grant=request.grant,
            expected_key=_key(),
            expected_nonce=_nonce(),
            evaluated_at=NOW,
            replay_window=BoundedReplayWindow("hostile-signature"),
            space_evaluation=_protocol_evaluation(request.grant),
        )


def test_auth_h6_bounded_jti_replay_refuses() -> None:
    replay = BoundedReplayWindow("same-session")
    _request(replay=replay)
    with pytest.raises(ValidationError, match="reused"):
        _request(replay=replay)


def test_auth_h7_h8_wrong_stale_or_missing_nonce_refuse() -> None:
    request = _request()
    key = _key()
    for nonce in (
        _nonce(value="wrong-nonce-123"),
        _nonce(origin="https://other.invalid.test"),
    ):
        with pytest.raises(ValidationError):
            verify_dpop_get_request(
                request_url=request.url,
                method="GET",
                proof=request.proof,
                grant=request.grant,
                expected_key=key,
                expected_nonce=nonce,
                evaluated_at=NOW,
                replay_window=BoundedReplayWindow("hostile-nonce"),
                space_evaluation=_protocol_evaluation(request.grant),
            )
    with pytest.raises(ValidationError, match="required"):
        construct_dpop_get_request(
            grant=request.grant,
            dpop_key=key,
            url=request.url,
            nonce=None,  # type: ignore[arg-type]
            jti="jti-missing-nonce",
            issued_at=NOW,
            evaluated_at=NOW,
            replay_window=BoundedReplayWindow("missing-nonce"),
            space_evaluation=_protocol_evaluation(request.grant),
        )
    with pytest.raises(ValidationError, match="another session"):
        construct_dpop_get_request(
            grant=request.grant,
            dpop_key=key,
            url=request.url,
            nonce=DpopNonceContext(
                "https://pds.invalid.test", "fixture-session-b", "nonce-fixture", NOW
            ),
            jti="jti-wrong-session",
            issued_at=NOW,
            evaluated_at=NOW,
            replay_window=BoundedReplayWindow("wrong-session"),
            space_evaluation=_protocol_evaluation(request.grant),
        )


def test_auth_h9_stale_and_future_iat_refuse() -> None:
    for issued in (NOW - timedelta(seconds=301), NOW + timedelta(seconds=31)):
        with pytest.raises(ValidationError, match="bounded window"):
            _request(issued_at=issued)


def test_auth_h10_missing_atproto_and_h11_wrong_sub_refuse() -> None:
    with pytest.raises(ValidationError, match="lacks atproto"):
        _grant(granted_scope=SCOPE_READ)
    with pytest.raises(ValidationError, match="subject"):
        _grant(subject="did:plc:anotheruser")


def test_auth_h12_requested_scope_laundering_refuses_request_construction() -> None:
    grant = _grant(
        granted_scope=f"atproto {SCOPE_READ_SELF}",
        requested_scope=f"atproto {SCOPE_READ}",
    )
    evaluation = _protocol_evaluation(
        grant, action=SpaceAction.READ, repo_did="did:plc:other"
    )
    assert not evaluation.permitted
    with pytest.raises(ValidationError, match="does not cover"):
        _request(grant=grant, evaluation=evaluation)


def test_auth_h13_space_mismatch_and_h14_read_self_laundering_refuse() -> None:
    grant = _grant(granted_scope=f"atproto {SCOPE_READ_SELF}")
    wrong_space = SpaceProtocolRequest(
        SpaceIdentity("did:plc:otherauthority", SPACE.space_type, SPACE.skey),
        USER,
        SpaceAction.READ_SELF,
        COLLECTION_A,
    )
    mismatch = evaluate_space_protocol_grant(
        grant.receipt,
        wrong_space,
        declaration_collections=frozenset({COLLECTION_A}),
        declaration_evidence_ref="fixture:declaration",
    )
    laundering = _protocol_evaluation(
        grant, action=SpaceAction.READ, repo_did="did:plc:other"
    )
    assert not mismatch.permitted and not laundering.permitted


def test_auth_h16_grant_cannot_be_relabelled_as_governance() -> None:
    with pytest.raises(ValidationError, match="governance"):
        replace(_grant().receipt, governance_authority=True)
    with pytest.raises(ValidationError, match="claim set"):
        replace(
            _grant().receipt,
            verified_claims=frozenset({"governance_authority"}),
        )


def test_auth_h18_default_port_is_normalized_but_path_is_exact() -> None:
    assert canonical_dpop_htu("https://PDS.invalid.test:443/a") == (
        "https://pds.invalid.test/a"
    )
    assert canonical_dpop_htu("https://pds.invalid.test/a?x=1") == (
        "https://pds.invalid.test/a"
    )
    assert canonical_dpop_htu("https://pds.invalid.test/a") != (
        canonical_dpop_htu("https://pds.invalid.test/b")
    )


def test_auth_h19_secrets_absent_from_receipts_repr_and_exceptions() -> None:
    token = _token()
    key = _key()
    grant = _grant(token=token, key=key)
    request = _request(grant=grant, key=key)
    secret = token.authorization_header().removeprefix("DPoP ")
    material = " ".join(
        (
            repr(token),
            repr(key),
            repr(grant),
            repr(request),
            json.dumps(grant.receipt.to_provenance()),
            json.dumps(request.receipt.to_provenance()),
        )
    )
    assert secret not in material
    with pytest.raises(TypeError, match="runtime-only"):
        pickle.dumps(token)
    with pytest.raises(TypeError, match="runtime-only"):
        pickle.dumps(key)
    with pytest.raises(ValidationError) as caught:
        construct_dpop_get_request(
            grant=grant,
            dpop_key=_key(b"wrong"),
            url=_url(),
            nonce=_nonce(),
            jti="jti-secret-test",
            issued_at=NOW,
            evaluated_at=NOW,
            replay_window=BoundedReplayWindow("secret-test"),
            space_evaluation=_protocol_evaluation(grant),
        )
    assert secret not in str(caught.value)


def test_auth_h20_bound_receipt_rejects_stronger_metadata() -> None:
    receipt = _request().receipt
    with pytest.raises(ValidationError):
        replace(receipt, effect_authorized=True)
    with pytest.raises(ValidationError):
        replace(receipt, client_id="https://stronger.invalid.test/client.json")


def test_nonce_update_is_a_new_proof_and_does_not_mutate_first_receipt() -> None:
    first = _request(nonce=_nonce(value="nonce-first-123"), jti="jti-first-0001")
    second = _request(nonce=_nonce(value="nonce-second-456"), jti="jti-second-0002")
    assert first.receipt.receipt_id != second.receipt.receipt_id
    assert first.receipt.nonce_sha256 == _nonce(value="nonce-first-123").digest
