from __future__ import annotations

import base64
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
    SA9DB_FIXTURE_SHA256,
    BoundedDelegationReplayWindow,
    BoundedReplayWindow,
    DidBindingSelection,
    DidInterpretationProfile,
    DidResolutionMethod,
    DidResolutionProvenance,
    DpopNonceContext,
    DpopSessionKey,
    ResolvedDidDocument,
    SecretAccessToken,
    SecretDelegationToken,
    SpaceAction,
    SpaceIdentity,
    SpaceProtocolRequest,
    construct_dpop_get_request,
    evaluate_space_protocol_grant,
    qualify_delegation_token,
    qualify_did_document,
    qualify_oauth_grant,
)

NOW = datetime.fromisoformat("2026-08-21T21:00:20+00:00")
ISSUED = int((NOW - timedelta(seconds=20)).timestamp())
USER = "did:plc:sa9dbfixtureuser"
AUTHORITY = "did:plc:sa9dbspaceauthority"
SPACE = SpaceIdentity(AUTHORITY, "invalid.test.communityspace", "forum")
SCOPE_READ = (
    "space:invalid.test.communityspace?"
    "authority=did%3Aplc%3Asa9dbspaceauthority&skey=forum&action=read"
)
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
VECTOR = (
    Path(__file__).resolve().parents[3]
    / "tests/fixtures/spaces-alpha/sa9d-b-delegation.json"
)


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _base58(value: bytes) -> str:
    leading = len(value) - len(value.lstrip(b"\x00"))
    number = int.from_bytes(value, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = _B58[remainder] + encoded
    return "1" * leading + (encoded or "1")


def _account_key(label: bytes = b"sa9d-b account key") -> DpopSessionKey:
    return DpopSessionKey.from_test_seed(label, session_ref="account-signing-fixture")


def _dpop_key(label: bytes = b"sa9d-b dpop key") -> DpopSessionKey:
    return DpopSessionKey.from_test_seed(label, session_ref="oauth-session-fixture")


def _resolved_and_account_binding(account_key=None):
    account_key = account_key or _account_key()
    multibase = "z" + _base58(b"\x80\x24" + account_key.compressed_public_key)
    document = json.dumps(
        {
            "id": USER,
            "verificationMethod": [
                {
                    "id": "#atproto",
                    "type": "Multikey",
                    "controller": USER,
                    "publicKeyMultibase": multibase,
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    resolved = ResolvedDidDocument(
        expected_did=USER,
        document_bytes=document,
        document_sha256=hashlib.sha256(document).hexdigest(),
        method=DidResolutionMethod.PLC,
        method_receipt_id="sha256:" + "1" * 64,
        provenance=DidResolutionProvenance.PLC_OPERATION_HISTORY,
        verified_claims=frozenset({"fixture_plc_operation_history"}),
        observed_at=NOW,
    )
    binding = qualify_did_document(
        resolved.to_sa9b_input(),
        profile=DidInterpretationProfile.ACCOUNT_SIGNING_KEY,
        qualified_at=NOW,
    )
    return resolved, binding


def _grant_and_request(
    *,
    granted_scope: str | None = None,
    request_path: str = "com.atproto.space.getDelegationToken",
    evaluation_action: SpaceAction = SpaceAction.READ,
    dpop_key=None,
    space: SpaceIdentity = SPACE,
):
    dpop_key = dpop_key or _dpop_key()
    scope_read = (
        "space:"
        + space.space_type
        + "?"
        + urllib.parse.urlencode(
            {
                "authority": space.authority_did,
                "skey": space.skey,
                "action": "read",
            }
        )
    )
    granted_scope = granted_scope or f"atproto {scope_read}"
    access_token = SecretAccessToken(
        hashlib.sha256(b"sa9d-b synthetic oauth token").hexdigest()
    )
    grant = qualify_oauth_grant(
        expected_account_did=USER,
        token_subject=USER,
        authorization_server_issuer="https://auth.invalid.test",
        client_id="https://client.invalid.test/oauth.json",
        requested_scope=f"atproto {scope_read}",
        granted_scope=granted_scope,
        access_token=access_token,
        dpop_key=dpop_key,
        observed_at=NOW,
        provenance_ref="fixture:sa9d-b:oauth-token-response",
    )
    evaluation = evaluate_space_protocol_grant(
        grant.receipt,
        SpaceProtocolRequest(space, USER, evaluation_action),
        declaration_collections=frozenset({"invalid.test.spacepost"}),
        declaration_evidence_ref="fixture:space-type:current",
    )
    query = {"space": space.uri}
    if request_path != "com.atproto.space.getDelegationToken":
        query["repo"] = USER
    url = f"https://pds.invalid.test/xrpc/{request_path}?" + urllib.parse.urlencode(
        query
    )
    request = construct_dpop_get_request(
        grant=grant,
        dpop_key=dpop_key,
        url=url,
        nonce=DpopNonceContext(
            "https://pds.invalid.test",
            "oauth-session-fixture",
            "nonce-sa9db-fixture",
            NOW,
        ),
        jti="dpop-sa9db-0001",
        issued_at=NOW,
        evaluated_at=NOW,
        replay_window=BoundedReplayWindow("oauth-session-fixture"),
        space_evaluation=evaluation,
    )
    return grant, evaluation, request


def _jwt(
    account_key=None, *, space: SpaceIdentity = SPACE, **changes: object
) -> SecretDelegationToken:
    account_key = account_key or _account_key()
    header: dict[str, object] = {
        "typ": "atproto-space-delegation+jwt",
        "alg": "ES256",
        "kid": "#atproto",
    }
    payload: dict[str, object] = {
        "iss": USER,
        "sub": space.uri,
        "aud": f"{space.authority_did}#atproto_space_host",
        "iat": ISSUED,
        "exp": ISSUED + 60,
        "jti": "delegation-sa9db-0001",
    }
    for name, value in changes.items():
        target, _, key = name.partition("__")
        if target == "header":
            if value is None:
                header.pop(key, None)
            else:
                header[key] = value
        elif target == "payload":
            if value is None:
                payload.pop(key, None)
            else:
                payload[key] = value
        else:
            raise AssertionError(name)
    encoded_header = _b64url(
        json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    )
    encoded_payload = _b64url(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    )
    signing_input = f"{encoded_header}.{encoded_payload}".encode()
    signature = _b64url(account_key._sign_dpop_proof(signing_input))
    return SecretDelegationToken(f"{encoded_header}.{encoded_payload}.{signature}")


def _qualify(
    *,
    token=None,
    signer_key=None,
    replay=None,
    space: SpaceIdentity = SPACE,
    **context_changes,
):
    signer_key = signer_key or _account_key()
    resolved, binding = _resolved_and_account_binding(signer_key)
    grant, evaluation, request = _grant_and_request(space=space)
    values = {
        "token": token or _jwt(signer_key, space=space),
        "expected_space": space,
        "resolved_user": resolved,
        "account_key": binding,
        "oauth_grant": grant,
        "oauth_request": request,
        "scope_evaluation": evaluation,
        "evaluated_at": NOW,
        "replay_window": replay
        or BoundedDelegationReplayWindow("delegation-fixture-domain"),
    }
    values.update(context_changes)
    return qualify_delegation_token(**values)


def test_delegation_positive_exact_claims_and_sa9b_account_key_selection() -> None:
    qualified = _qualify()
    receipt = qualified.receipt

    assert receipt.issuer_did == USER
    assert receipt.space == SPACE
    assert receipt.audience == f"{AUTHORITY}#atproto_space_host"
    assert receipt.algorithm == "ES256" and receipt.key_id == "#atproto"
    assert receipt.expires_at - receipt.issued_at == 60
    assert len(receipt.verified_claims) == 12
    assert not receipt.space_authority_admission
    assert not receipt.space_credential and not receipt.space_access
    assert not receipt.standing and not receipt.governance_authority

    _, binding = _resolved_and_account_binding()
    assert binding.profile is DidInterpretationProfile.ACCOUNT_SIGNING_KEY
    assert binding.selection is DidBindingSelection.ACCOUNT_KEY


def test_delegation_public_manifest_replays_without_secret_material() -> None:
    manifest = json.loads(VECTOR.read_bytes())
    qualified = _qualify()
    fixture = manifest["fixture"]

    assert hashlib.sha256(VECTOR.read_bytes()).hexdigest() == SA9DB_FIXTURE_SHA256
    assert fixture["tokenSha256"] == qualified.receipt.token_sha256
    assert fixture["delegationReceiptId"] == qualified.receipt.receipt_id
    assert fixture["accountKeyReceiptId"] == qualified.receipt.account_key_receipt_id
    assert fixture["oauthGrantReceiptId"] == qualified.receipt.oauth_grant_receipt_id
    assert fixture["dpopRequestReceiptId"] == qualified.receipt.dpop_request_receipt_id
    assert fixture["issuedAt"] == qualified.receipt.issued_at
    assert fixture["expiresAt"] == qualified.receipt.expires_at
    assert not manifest["secretMaterialPresent"]


def test_delegation_binds_oauth_read_dpop_request_and_method_provenance() -> None:
    qualified = _qualify()
    resolved, binding = _resolved_and_account_binding()
    grant, evaluation, request = _grant_and_request()
    receipt = qualified.receipt

    assert receipt.account_key_receipt_id == binding.receipt_id
    assert receipt.did_resolution_receipt_id == resolved.method_receipt_id
    assert receipt.did_resolution_method == "did:plc"
    assert receipt.oauth_grant_receipt_id == grant.receipt.receipt_id
    assert receipt.dpop_request_receipt_id == request.receipt.receipt_id
    assert receipt.space_scope_evaluation_id == evaluation.evaluation_id
    assert receipt.dpop_jwk_thumbprint == grant.receipt.dpop_jwk_thumbprint


def test_delegation_runtime_secret_never_enters_receipt_repr_or_serialization() -> None:
    token = _jwt()
    raw = token._for_qualification()
    qualified = _qualify(token=token)
    surfaces = (
        repr(token) + repr(qualified) + json.dumps(qualified.receipt.to_provenance())
    )

    assert raw not in surfaces
    assert qualified.receipt.token_sha256 == hashlib.sha256(raw.encode()).hexdigest()
    with pytest.raises(TypeError):
        pickle.dumps(token)
    with pytest.raises(TypeError):
        pickle.dumps(qualified)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"header__typ": "JWT"}, "spaces_delegation_header_mismatch"),
        ({"header__alg": "none"}, "spaces_delegation_algorithm_unsupported"),
        ({"header__kid": "#atproto_space"}, "spaces_delegation_key_mismatch"),
        (
            {"payload__lxm": "com.atproto.space.getRepo"},
            "spaces_delegation_payload_mismatch",
        ),
        ({"payload__iss": "did:plc:other"}, "spaces_delegation_issuer_mismatch"),
        (
            {
                "payload__sub": "at://did:plc:other/space/invalid.test.communityspace/forum"
            },
            "spaces_delegation_space_mismatch",
        ),
        (
            {"payload__aud": "did:plc:other#atproto_space_host"},
            "spaces_delegation_audience_mismatch",
        ),
        ({"payload__exp": ISSUED + 61}, "spaces_delegation_time_invalid"),
        ({"payload__jti": "short"}, "spaces_delegation_jti_invalid"),
    ],
)
def test_delegation_hostile_header_and_payload_substitutions_refuse(
    mutation, reason
) -> None:
    with pytest.raises(ValidationError) as error:
        _qualify(token=_jwt(**mutation))
    assert error.value.reason_code == reason


def test_delegation_expired_and_future_tokens_refuse() -> None:
    expired = _jwt(payload__iat=ISSUED - 60, payload__exp=ISSUED)
    future = _jwt(payload__iat=ISSUED + 30, payload__exp=ISSUED + 90)

    with pytest.raises(ValidationError) as error:
        _qualify(token=expired)
    assert error.value.reason_code == "spaces_delegation_expired"
    with pytest.raises(ValidationError) as error:
        _qualify(token=future)
    assert error.value.reason_code == "spaces_delegation_expired"


def test_delegation_signature_and_account_key_substitution_refuse() -> None:
    token = _jwt()
    raw = token._for_qualification()
    header, payload, signature = raw.split(".")
    decoded = bytearray(
        base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
    )
    decoded[0] ^= 1
    replacement = f"{header}.{payload}.{_b64url(bytes(decoded))}"
    with pytest.raises(ValidationError) as error:
        _qualify(token=SecretDelegationToken(replacement))
    assert error.value.reason_code == "spaces_delegation_signature_invalid"

    other_key = _account_key(b"sa9d-b other account key")
    with pytest.raises(ValidationError) as error:
        _qualify(token=token, signer_key=other_key)
    assert error.value.reason_code == "spaces_delegation_signature_invalid"


def test_delegation_replay_is_bounded_and_explicit() -> None:
    replay = BoundedDelegationReplayWindow("delegation-fixture-domain")
    _qualify(replay=replay)
    with pytest.raises(ValidationError) as error:
        _qualify(replay=replay)
    assert error.value.reason_code == "spaces_delegation_replay"


def test_read_self_and_requested_scope_laundering_cannot_request_delegation() -> None:
    read_self = SCOPE_READ.replace("action=read", "action=read_self")
    with pytest.raises(ValidationError) as error:
        _grant_and_request(granted_scope=f"atproto {read_self}")
    assert error.value.reason_code == "spaces_oauth_scope_refused"

    grant, evaluation, _ = _grant_and_request()
    assert grant.receipt.requested_scope == grant.receipt.granted_scope
    assert evaluation.permitted


def test_get_repo_request_cannot_be_relabelled_as_delegation_acquisition() -> None:
    grant, evaluation, request = _grant_and_request(
        request_path="com.atproto.space.getRepo"
    )
    with pytest.raises(ValidationError) as error:
        _qualify(oauth_grant=grant, scope_evaluation=evaluation, oauth_request=request)
    assert error.value.reason_code == "spaces_delegation_request_mismatch"


def test_resolution_key_and_oauth_context_substitution_refuse() -> None:
    resolved, binding = _resolved_and_account_binding()
    wrong_resolved = replace(resolved, method_receipt_id="sha256:" + "2" * 64)
    with pytest.raises(ValidationError) as error:
        _qualify(resolved_user=wrong_resolved, account_key=binding)
    assert error.value.reason_code == "spaces_delegation_key_provenance_mismatch"

    other_dpop = _dpop_key(b"other oauth session")
    other_grant, _, _ = _grant_and_request(dpop_key=other_dpop)
    with pytest.raises(ValidationError) as error:
        _qualify(oauth_grant=other_grant)
    assert error.value.reason_code == "spaces_delegation_oauth_binding_mismatch"

    _, _, request = _grant_and_request()
    relabelled = replace(
        request,
        url=request.url.replace(urllib.parse.quote(SPACE.uri, safe=""), "wrong-space"),
    )
    with pytest.raises(ValidationError) as error:
        _qualify(oauth_request=relabelled)
    assert error.value.reason_code == "spaces_delegation_oauth_binding_mismatch"


def test_space_authority_key_profile_cannot_substitute_for_account_key_profile() -> (
    None
):
    resolved, _ = _resolved_and_account_binding()
    fallback_space_key = qualify_did_document(
        resolved.to_sa9b_input(),
        profile=DidInterpretationProfile.SPACE_AUTHORITY_SIGNING_KEY,
        qualified_at=NOW,
    )

    with pytest.raises(ValidationError) as error:
        _qualify(resolved_user=resolved, account_key=fallback_space_key)
    assert error.value.reason_code == "spaces_delegation_key_provenance_mismatch"


def test_delegation_receipt_authority_relabeling_and_token_substitution_refuse() -> (
    None
):
    qualified = _qualify()
    with pytest.raises(ValidationError):
        replace(qualified.receipt, space_authority_admission=True)
    with pytest.raises(ValidationError):
        replace(qualified.receipt, governance_authority=True)

    other = _jwt(payload__jti="delegation-sa9db-0002")
    with pytest.raises(ValidationError) as error:
        replace(qualified, token=other)
    assert error.value.reason_code == "spaces_delegation_token_mismatch"
