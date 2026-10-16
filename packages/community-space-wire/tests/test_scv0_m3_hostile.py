from __future__ import annotations

import copy

import pytest

from community_model import ValidationError, canonical_json_bytes
from community_space_model import CommunityIdentity, SpaceIdentity
from community_space_wire import (
    WireTranslationReceipt,
    adapt_source_post,
    adapt_submission,
    refuse_wire_claim_upgrade,
)


def _payload(value: object) -> bytes:
    return canonical_json_bytes(value)


def _reason(error: pytest.ExceptionInfo[ValidationError]) -> str:
    return error.value.reason_code


def test_m3_h1_malformed_source_reference_refuses(m3: dict[str, object]) -> None:
    value = copy.deepcopy(m3["source_value"])
    del value["record"]["rkey"]

    with pytest.raises(ValidationError) as error:
        adapt_source_post(
            _payload(value),
            expected_space=m3["space"],
            expected_author_did="did:web:author.invalid.test",
        )
    assert _reason(error) == "wire_fields_invalid"


def test_m3_h2_wrong_space_context_refuses(m3: dict[str, object]) -> None:
    other = SpaceIdentity(
        authority_did="did:web:other-space.invalid.test",
        space_type="test.invalid.community",
        skey="community-lab",
    )
    with pytest.raises(ValidationError) as error:
        adapt_source_post(
            m3["source_payload"],
            expected_space=other,
            expected_author_did="did:web:author.invalid.test",
        )
    assert _reason(error) == "wire_space_context_mismatch"


def test_m3_h3_wrong_author_context_refuses(m3: dict[str, object]) -> None:
    with pytest.raises(ValidationError) as error:
        adapt_source_post(
            m3["source_payload"],
            expected_space=m3["space"],
            expected_author_did="did:web:other-author.invalid.test",
        )
    assert _reason(error) == "wire_author_context_mismatch"


def test_m3_h4_invalid_cid_refuses(m3: dict[str, object]) -> None:
    value = copy.deepcopy(m3["source_value"])
    value["record"]["cid"] = "not-a-cid"

    with pytest.raises(ValidationError) as error:
        adapt_source_post(
            _payload(value),
            expected_space=m3["space"],
            expected_author_did="did:web:author.invalid.test",
        )
    assert _reason(error) == "cid_invalid"


def test_m3_h5_submission_cannot_reference_nonexistent_source(
    m3: dict[str, object],
) -> None:
    value = copy.deepcopy(m3["submission_value"])
    value["source"]["referenceId"] = "sha256:" + "f" * 64

    with pytest.raises(ValidationError) as error:
        adapt_submission(
            _payload(value),
            post=m3["adapted_post"].post,
            expected_community=m3["community"],
        )
    assert _reason(error) == "wire_source_reference_mismatch"


def test_m3_h6_cross_community_reference_refuses(m3: dict[str, object]) -> None:
    other = CommunityIdentity(
        space=m3["space"], community_actor_did="did:web:other-community.invalid.test"
    )
    with pytest.raises(ValidationError) as error:
        adapt_submission(
            m3["submission_payload"],
            post=m3["adapted_post"].post,
            expected_community=other,
        )
    assert _reason(error) == "wire_community_context_mismatch"


def test_m3_h7_missing_occurrence_identity_refuses(m3: dict[str, object]) -> None:
    value = copy.deepcopy(m3["submission_value"])
    del value["occurrenceId"]

    with pytest.raises(ValidationError) as error:
        adapt_submission(
            _payload(value),
            post=m3["adapted_post"].post,
            expected_community=m3["community"],
        )
    assert _reason(error) == "wire_fields_invalid"


def test_m3_h8_adapter_field_substitution_refuses(m3: dict[str, object]) -> None:
    value = copy.deepcopy(m3["source_value"])
    value["record"]["rkey"] = "substituted"

    with pytest.raises(ValidationError) as error:
        adapt_source_post(
            _payload(value),
            expected_space=m3["space"],
            expected_author_did="did:web:author.invalid.test",
        )
    assert _reason(error) == "wire_record_uri_mismatch"


def test_m3_h9_approved_field_cannot_bypass_admission(m3: dict[str, object]) -> None:
    value = copy.deepcopy(m3["submission_value"])
    value["approved"] = True

    with pytest.raises(ValidationError) as error:
        adapt_submission(
            _payload(value),
            post=m3["adapted_post"].post,
            expected_community=m3["community"],
        )
    assert _reason(error) == "wire_fields_invalid"


def test_m3_h10_ui_fields_cannot_become_authority(m3: dict[str, object]) -> None:
    value = copy.deepcopy(m3["submission_value"])
    value["display"] = {
        "score": 999,
        "moderator": True,
        "governanceAuthority": True,
    }

    with pytest.raises(ValidationError) as error:
        adapt_submission(
            _payload(value),
            post=m3["adapted_post"].post,
            expected_community=m3["community"],
        )
    assert _reason(error) == "wire_fields_invalid"
    with pytest.raises(ValidationError) as labels_error:
        refuse_wire_claim_upgrade({"visible": True})
    assert _reason(labels_error) == "wire_claim_upgrade_refused"


def test_duplicate_json_keys_refuse(m3: dict[str, object]) -> None:
    payload = b'{"profile":"scv0-m3-test-wire/1","profile":"evil"}'
    with pytest.raises(ValidationError) as error:
        adapt_source_post(
            payload,
            expected_space=m3["space"],
            expected_author_did="did:web:author.invalid.test",
        )
    assert _reason(error) == "wire_duplicate_key"


def test_noncanonical_wire_encoding_refuses(m3: dict[str, object]) -> None:
    payload = b" " + m3["source_payload"]
    with pytest.raises(ValidationError) as error:
        adapt_source_post(
            payload,
            expected_space=m3["space"],
            expected_author_did="did:web:author.invalid.test",
        )
    assert _reason(error) == "wire_noncanonical"


def test_live_namespace_refuses(m3: dict[str, object]) -> None:
    value = copy.deepcopy(m3["source_value"])
    value["record"]["collection"] = "com.example.real.post"
    with pytest.raises(ValidationError) as error:
        adapt_source_post(
            _payload(value),
            expected_space=m3["space"],
            expected_author_did="did:web:author.invalid.test",
        )
    assert _reason(error) == "wire_canonical_namespace_refused"


def test_translation_receipt_nonclaims_cannot_be_relabelled(
    m3: dict[str, object],
) -> None:
    receipt = m3["adapted_post"].receipt
    with pytest.raises(ValidationError) as error:
        WireTranslationReceipt(
            record_kind=receipt.record_kind,
            exact_wire_sha256=receipt.exact_wire_sha256,
            domain_value_id=receipt.domain_value_id,
            verified_claims=receipt.verified_claims,
            explicit_non_claims=("governance_authority",),
        )
    assert _reason(error) == "wire_claim_upgrade_refused"


def test_translation_receipt_verified_claims_cannot_be_relabelled(
    m3: dict[str, object],
) -> None:
    receipt = m3["adapted_post"].receipt
    with pytest.raises(ValidationError) as error:
        WireTranslationReceipt(
            record_kind=receipt.record_kind,
            exact_wire_sha256=receipt.exact_wire_sha256,
            domain_value_id=receipt.domain_value_id,
            verified_claims=(*receipt.verified_claims, "governance_authority"),
        )
    assert _reason(error) == "wire_claim_upgrade_refused"


def test_record_kind_cannot_be_paired_with_another_fixture_collection(
    m3: dict[str, object],
) -> None:
    value = copy.deepcopy(m3["source_value"])
    value["record"]["collection"] = "test.invalid.community.submit"
    value["record"]["uri"] = value["record"]["uri"].replace(
        "test.invalid.community.post", "test.invalid.community.submit"
    )
    with pytest.raises(ValidationError) as error:
        adapt_source_post(
            _payload(value),
            expected_space=m3["space"],
            expected_author_did="did:web:author.invalid.test",
        )
    assert _reason(error) == "wire_record_role_mismatch"
