from __future__ import annotations

import base64
import hashlib
import json
import pickle
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from community_model import ValidationError
from communitywatch_spaces_alpha import (
    SA9DC_FIXTURE_SHA256,
    BoundedCredentialIssuanceReplayWindow,
    CredentialAccessSemantics,
    CredentialAudienceSemantics,
    DidBindingSelection,
    DidInterpretationProfile,
    DidResolutionMethod,
    DidResolutionProvenance,
    DpopSessionKey,
    ResolvedDidDocument,
    SecretSpaceCredential,
    SpaceIdentity,
    qualify_did_document,
    qualify_space_credential,
)
from test_sa9d_delegation import AUTHORITY, NOW, SPACE, USER
from test_sa9d_delegation import _base58 as _base58
from test_sa9d_delegation import _qualify as _qualify_delegation

CREDENTIAL_ISSUED = int((NOW - timedelta(seconds=5)).timestamp())
VECTOR = (
    Path(__file__).resolve().parents[3]
    / "tests/fixtures/spaces-alpha/sa9d-c-credential.json"
)


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _authority_key(label: bytes = b"sa9d-c authority key") -> DpopSessionKey:
    return DpopSessionKey.from_test_seed(label, session_ref="authority-signing-fixture")


def _credential_key(label: bytes = b"sa9d-c credential dpop key") -> DpopSessionKey:
    return DpopSessionKey.from_test_seed(label, session_ref="space-credential-fixture")


def _authority_context(*, authority_key=None, dedicated: bool = True, space=SPACE):
    authority_key = authority_key or _authority_key()
    multibase = "z" + _base58(b"\x80\x24" + authority_key.compressed_public_key)
    methods = [
        {
            "id": "#atproto",
            "type": "Multikey",
            "controller": space.authority_did,
            "publicKeyMultibase": multibase,
        }
    ]
    services = [
        {
            "id": "#atproto_pds",
            "type": "AtprotoPersonalDataServer",
            "serviceEndpoint": "https://authority-pds.invalid.test",
        }
    ]
    if dedicated:
        methods.insert(
            0,
            {
                "id": "#atproto_space",
                "type": "Multikey",
                "controller": space.authority_did,
                "publicKeyMultibase": multibase,
            },
        )
        services.insert(
            0,
            {
                "id": "#atproto_space_host",
                "type": "AtprotoSpaceHost",
                "serviceEndpoint": "https://space-host.invalid.test",
            },
        )
    document = json.dumps(
        {"id": space.authority_did, "verificationMethod": methods, "service": services},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    method = (
        DidResolutionMethod.WEB
        if space.authority_did.startswith("did:web:")
        else DidResolutionMethod.PLC
    )
    provenance = (
        DidResolutionProvenance.WEBPKI_HTTPS
        if method is DidResolutionMethod.WEB
        else DidResolutionProvenance.PLC_OPERATION_HISTORY
    )
    resolved = ResolvedDidDocument(
        expected_did=space.authority_did,
        document_bytes=document,
        document_sha256=hashlib.sha256(document).hexdigest(),
        method=method,
        method_receipt_id="sha256:" + "3" * 64,
        provenance=provenance,
        verified_claims=frozenset({"fixture_plc_operation_history"}),
        observed_at=NOW,
    )
    key = qualify_did_document(
        resolved.to_sa9b_input(),
        profile=DidInterpretationProfile.SPACE_AUTHORITY_SIGNING_KEY,
        qualified_at=NOW,
    )
    host = qualify_did_document(
        resolved.to_sa9b_input(),
        profile=DidInterpretationProfile.SPACE_AUTHORITY_HOST,
        qualified_at=NOW,
    )
    return resolved, key, host


def _credential_jwt(
    *,
    authority_key=None,
    credential_key=None,
    dedicated: bool = True,
    space=SPACE,
    **changes,
) -> SecretSpaceCredential:
    authority_key = authority_key or _authority_key()
    credential_key = credential_key or _credential_key()
    header: dict[str, object] = {
        "typ": "atproto-space-credential+jwt",
        "alg": "ES256",
        "kid": "#atproto_space" if dedicated else "#atproto",
    }
    payload: dict[str, object] = {
        "iss": space.authority_did,
        "sub": space.uri,
        "cnf": {"jkt": credential_key.thumbprint},
        "iat": CREDENTIAL_ISSUED,
        "exp": CREDENTIAL_ISSUED + 7200,
        "jti": "credential-sa9dc-0001",
    }
    for name, value in changes.items():
        target, _, key = name.partition("__")
        values = header if target == "header" else payload
        if value is None:
            values.pop(key, None)
        else:
            values[key] = value
    header_part = _b64url(
        json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    )
    payload_part = _b64url(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    )
    signing_input = f"{header_part}.{payload_part}".encode()
    signature = _b64url(authority_key._sign_dpop_proof(signing_input))
    return SecretSpaceCredential(f"{header_part}.{payload_part}.{signature}")


def _qualify(
    *,
    credential=None,
    authority_signer=None,
    credential_key=None,
    dedicated: bool = True,
    space=SPACE,
    replay=None,
    **changes,
):
    authority_signer = authority_signer or _authority_key()
    credential_key = credential_key or _credential_key()
    resolved, authority_key, authority_host = _authority_context(
        authority_key=authority_signer, dedicated=dedicated, space=space
    )
    values = {
        "credential": credential
        or _credential_jwt(
            authority_key=authority_signer,
            credential_key=credential_key,
            dedicated=dedicated,
            space=space,
        ),
        "expected_space": space,
        "expected_applicant_did": USER,
        "delegation": _qualify_delegation(space=space).receipt,
        "resolved_authority": resolved,
        "authority_key": authority_key,
        "authority_host": authority_host,
        "credential_dpop_key": credential_key,
        "evaluated_at": NOW,
        "replay_window": replay
        or BoundedCredentialIssuanceReplayWindow("credential-issuance-fixture"),
    }
    values.update(changes)
    return qualify_space_credential(**values)


def test_space_credential_positive_dedicated_key_host_and_access_semantics() -> None:
    qualified = _qualify()
    receipt = qualified.receipt

    assert receipt.authority_did == AUTHORITY and receipt.space == SPACE
    assert receipt.applicant_context_did == USER
    assert receipt.key_id == "#atproto_space" and receipt.algorithm == "ES256"
    assert receipt.cnf_jkt == _credential_key().thumbprint
    assert receipt.access_semantics is CredentialAccessSemantics.WHOLE_SPACE_READ_SYNC
    assert (
        receipt.audience_semantics
        is CredentialAudienceSemantics.NO_JWT_AUDIENCE_ANY_SPACE_REPO_HOST
    )
    assert receipt.protocol_whole_space_read_sync and not receipt.protocol_write
    assert not receipt.live_host_acceptance and not receipt.space_membership
    assert not receipt.community_standing and not receipt.governance_authority


def test_space_credential_public_manifest_replays_without_secret_material() -> None:
    manifest = json.loads(VECTOR.read_bytes())
    qualified = _qualify()
    fixture = manifest["fixture"]

    assert hashlib.sha256(VECTOR.read_bytes()).hexdigest() == SA9DC_FIXTURE_SHA256
    assert fixture["credentialSha256"] == qualified.receipt.credential_sha256
    assert fixture["credentialAth"] == qualified.receipt.credential_ath
    assert fixture["credentialReceiptId"] == qualified.receipt.receipt_id
    assert (
        fixture["authorityKeyReceiptId"] == qualified.receipt.authority_key_receipt_id
    )
    assert (
        fixture["authorityHostReceiptId"] == qualified.receipt.authority_host_receipt_id
    )
    assert fixture["delegationReceiptId"] == qualified.receipt.delegation_receipt_id
    assert not manifest["secretMaterialPresent"]


def test_space_credential_positive_explicit_fallback_key_and_host() -> None:
    qualified = _qualify(dedicated=False)
    _, key, host = _authority_context(dedicated=False)

    assert key.selection is DidBindingSelection.FALLBACK_ACCOUNT_KEY
    assert host.selection is DidBindingSelection.FALLBACK_ACCOUNT_PDS
    assert qualified.receipt.key_id == "#atproto"
    assert (
        qualified.receipt.issuance_host_origin == "https://authority-pds.invalid.test"
    )


def test_space_credential_binds_delegation_resolution_key_host_and_dpop() -> None:
    qualified = _qualify()
    resolved, key, host = _authority_context()
    delegation = _qualify_delegation().receipt
    receipt = qualified.receipt

    assert receipt.did_resolution_receipt_id == resolved.method_receipt_id
    assert receipt.authority_key_receipt_id == key.receipt_id
    assert receipt.authority_host_receipt_id == host.receipt_id
    assert receipt.delegation_receipt_id == delegation.receipt_id
    assert receipt.delegation_token_sha256 == delegation.token_sha256
    assert receipt.credential_ath == qualified.credential.ath


def test_space_credential_runtime_secrets_are_redacted_and_nonserializable() -> None:
    qualified = _qualify()
    raw = qualified.credential._for_authenticated_request()
    surface = (
        repr(qualified)
        + repr(qualified.credential)
        + json.dumps(qualified.receipt.to_provenance())
    )

    assert raw not in surface
    with pytest.raises(TypeError):
        pickle.dumps(qualified.credential)
    with pytest.raises(TypeError):
        pickle.dumps(qualified)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"header__typ": "JWT"}, "spaces_credential_header_mismatch"),
        ({"header__kid": "#atproto"}, "spaces_credential_signing_key_mismatch"),
        ({"payload__iss": "did:plc:other"}, "spaces_credential_authority_mismatch"),
        (
            {
                "payload__sub": "at://did:plc:other/space/invalid.test.communityspace/forum"
            },
            "spaces_credential_space_mismatch",
        ),
        ({"payload__aud": AUTHORITY}, "spaces_credential_payload_mismatch"),
        ({"payload__exp": CREDENTIAL_ISSUED + 7201}, "spaces_credential_time_invalid"),
        ({"payload__jti": "short"}, "spaces_credential_jti_invalid"),
    ],
)
def test_space_credential_hostile_claim_mutations_refuse(mutation, reason) -> None:
    with pytest.raises(ValidationError) as error:
        _qualify(credential=_credential_jwt(**mutation))
    assert error.value.reason_code == reason


def test_space_credential_wrong_applicant_and_delegation_time_refuse() -> None:
    with pytest.raises(ValidationError) as error:
        _qualify(expected_applicant_did="did:plc:other")
    assert error.value.reason_code == "spaces_credential_applicant_mismatch"

    token = _credential_jwt(
        payload__iat=CREDENTIAL_ISSUED + 60,
        payload__exp=CREDENTIAL_ISSUED + 7260,
    )
    with pytest.raises(ValidationError) as error:
        _qualify(credential=token)
    assert error.value.reason_code == "spaces_credential_delegation_time_mismatch"


def test_space_credential_matching_delegation_for_another_space_refuses() -> None:
    other_space = SpaceIdentity(
        AUTHORITY, "invalid.test.communityspace", "another-forum"
    )
    other_delegation = _qualify_delegation(space=other_space).receipt

    with pytest.raises(ValidationError) as error:
        _qualify(delegation=other_delegation)
    assert error.value.reason_code == "spaces_credential_delegation_mismatch"


def test_space_credential_stale_or_future_evaluation_refuses() -> None:
    with pytest.raises(ValidationError) as error:
        _qualify(evaluated_at=NOW + timedelta(hours=3))
    assert error.value.reason_code == "spaces_credential_expired"
    with pytest.raises(ValidationError) as error:
        _qualify(evaluated_at=NOW - timedelta(minutes=1))
    assert error.value.reason_code == "spaces_credential_expired"


def test_space_credential_dpop_and_signing_key_substitution_refuse() -> None:
    other_dpop = _credential_key(b"other credential dpop key")
    with pytest.raises(ValidationError) as error:
        _qualify(credential_key=other_dpop, credential=_credential_jwt())
    assert error.value.reason_code == "spaces_credential_dpop_key_mismatch"

    other_authority = _authority_key(b"other authority key")
    with pytest.raises(ValidationError) as error:
        _qualify(authority_signer=other_authority, credential=_credential_jwt())
    assert error.value.reason_code == "spaces_credential_signature_invalid"


def test_space_credential_issuance_replay_is_bounded_not_use_semantics() -> None:
    replay = BoundedCredentialIssuanceReplayWindow("credential-issuance-fixture")
    first = _qualify(replay=replay)
    with pytest.raises(ValidationError) as error:
        _qualify(replay=replay)
    assert error.value.reason_code == "spaces_credential_issuance_replay"
    assert (
        first.receipt.audience_semantics
        is CredentialAudienceSemantics.NO_JWT_AUDIENCE_ANY_SPACE_REPO_HOST
    )


def test_space_credential_authority_host_and_resolution_substitution_refuse() -> None:
    resolved, key, host = _authority_context()
    wrong_resolved = replace(resolved, method_receipt_id="sha256:" + "4" * 64)
    with pytest.raises(ValidationError) as error:
        _qualify(
            resolved_authority=wrong_resolved,
            authority_key=key,
            authority_host=host,
        )
    assert error.value.reason_code == "spaces_credential_authority_provenance_mismatch"

    _, _, fallback_host = _authority_context(dedicated=False)
    with pytest.raises(ValidationError) as error:
        _qualify(authority_host=fallback_host)
    assert error.value.reason_code == "spaces_credential_authority_provenance_mismatch"


def test_space_credential_receipt_relabel_and_runtime_substitution_refuse() -> None:
    qualified = _qualify()
    for change in (
        {"space_membership": True},
        {"community_standing": True},
        {"governance_authority": True},
        {"effect_authorized": True},
        {"protocol_write": True},
    ):
        with pytest.raises(ValidationError):
            replace(qualified.receipt, **change)

    other = _credential_jwt(payload__jti="credential-sa9dc-0002")
    with pytest.raises(ValidationError) as error:
        replace(qualified, credential=other)
    assert error.value.reason_code == "spaces_credential_runtime_mismatch"
