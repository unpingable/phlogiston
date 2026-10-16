from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from community_model import (
    COMMUNITY_COLLECTIONS,
    AdmissionRecord,
    IncomingDelivery,
    ModActionRecord,
    ProfileRecord,
    RepositoryOperation,
    SubmissionRecord,
    ValidationContext,
    ValidationError,
    admission_rkey,
    normalized_created_at,
    removal_rkey,
    validate_admission_references,
    validate_record,
    validate_removal_references,
)

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "v0"


def _json(path: str) -> dict[str, object]:
    with (FIXTURES / path).open(encoding="utf-8") as handle:
        value = json.load(handle)
    assert isinstance(value, dict)
    return value


def _vectors() -> dict[str, dict[str, object]]:
    manifest = _json("record-vectors.json")
    return {item["name"]: item for item in manifest["records"]}  # type: ignore[index,misc]


def _context(
    vector: dict[str, object],
    *,
    accepted_at: datetime | None = None,
) -> ValidationContext:
    evidence = vector["dagCbor"]
    assert isinstance(evidence, dict)
    return ValidationContext(
        community_did="did:web:community.invalid",
        repo_did=vector["repoDid"],  # type: ignore[arg-type]
        collection=vector["collection"],  # type: ignore[arg-type]
        rkey=vector["rkey"],  # type: ignore[arg-type]
        operation=RepositoryOperation.CREATE,
        record_cid=evidence["cid"],  # type: ignore[arg-type]
        administrator_did="did:web:admin.invalid",
        first_accepted_at=accepted_at,
    )


def test_community_collection_inventory_is_exact_and_ordered() -> None:
    assert COMMUNITY_COLLECTIONS == (
        "app.phlogiston.community.profile",
        "app.phlogiston.community.submit",
        "app.phlogiston.community.admission",
        "app.phlogiston.community.modAction",
        "app.phlogiston.community.memberAction",
        "app.phlogiston.community.replyPolicy",
        "app.phlogiston.community.replyAdmission",
        "app.phlogiston.community.replyAction",
    )


def test_fixture_records_round_trip_and_validate_in_context() -> None:
    vectors = _vectors()
    expected_types = {
        "profile": ProfileRecord,
        "submit": SubmissionRecord,
        "admission": AdmissionRecord,
        "mod_action": ModActionRecord,
    }
    parsed: dict[str, object] = {}
    for name, expected_type in expected_types.items():
        vector = vectors[name]
        source = _json(vector["path"])  # type: ignore[arg-type]
        result = validate_record(source, context=_context(vector))
        assert isinstance(result.record, expected_type)
        assert result.record.to_record() == source
        parsed[name] = result.record

    submission = parsed["submit"]
    admission = parsed["admission"]
    removal = parsed["mod_action"]
    assert isinstance(submission, SubmissionRecord)
    assert isinstance(admission, AdmissionRecord)
    assert isinstance(removal, ModActionRecord)
    validate_admission_references(admission, submission)
    validate_removal_references(removal, admission)


def test_payload_type_must_match_envelope_collection() -> None:
    vectors = _vectors()
    source = _json(vectors["profile"]["path"])  # type: ignore[arg-type]
    mismatched = replace(
        _context(vectors["profile"]), collection="app.phlogiston.community.submit"
    )

    with pytest.raises(ValidationError, match="envelope collection") as captured:
        validate_record(source, context=mismatched)
    assert captured.value.path == ("$type",)


def test_normalized_created_at_preserves_signed_fractional_precision() -> None:
    source = _json(_vectors()["submit"]["path"])  # type: ignore[arg-type]
    source["createdAt"] = "2026-07-10T10:01:00.123456789-04:00"
    record = SubmissionRecord.from_record(source)

    assert record.created_at_raw == "2026-07-10T10:01:00.123456789-04:00"
    assert normalized_created_at(record) == "2026-07-10T14:01:00.123456789Z"


def test_context_enforces_self_submission_and_exact_collections() -> None:
    vector = _vectors()["submit"]
    source = _json(vector["path"])  # type: ignore[arg-type]
    wrong_repo = _context(vector)
    object.__setattr__(wrong_repo, "repo_did", "did:web:mallory.invalid")
    with pytest.raises(ValidationError, match="repo_mismatch"):
        validate_record(source, context=wrong_repo)

    source["subject"] = {
        **source["subject"],  # type: ignore[dict-item]
        "uri": "at://did:web:alice.invalid/app.bsky.feed.like/3jzfcijpj2z2a",
    }
    with pytest.raises(ValidationError, match="subject_collection_invalid"):
        validate_record(source, context=_context(vector))


def test_submission_rejects_community_mismatch_and_payload_submitter_override() -> None:
    vector = _vectors()["submit"]

    wrong_community = _json(vector["path"])  # type: ignore[arg-type]
    wrong_community["community"] = "did:web:other-community.invalid"
    with pytest.raises(ValidationError) as captured:
        validate_record(wrong_community, context=_context(vector))
    assert captured.value.reason_code == "community_mismatch"

    submitter_override = _json(vector["path"])  # type: ignore[arg-type]
    submitter_override["submitter"] = "did:web:mallory.invalid"
    with pytest.raises(ValidationError) as captured:
        validate_record(submitter_override, context=_context(vector))
    assert captured.value.reason_code == "schema_invalid"
    assert captured.value.path == ("submitter",)


def test_profile_requires_community_repo_and_self_rkey() -> None:
    vector = _vectors()["profile"]
    source = _json(vector["path"])  # type: ignore[arg-type]
    contexts = (
        (
            replace(_context(vector), repo_did="did:web:other.invalid"),
            "authority_repo_mismatch",
        ),
        (replace(_context(vector), rkey="not-self"), "schema_invalid"),
    )

    for context, expected_reason in contexts:
        with pytest.raises(ValidationError) as captured:
            validate_record(source, context=context)
        assert captured.value.reason_code == expected_reason


@pytest.mark.parametrize("name", ["admission", "mod_action"])
def test_authority_records_require_the_community_repository(name: str) -> None:
    vector = _vectors()[name]
    source = _json(vector["path"])  # type: ignore[arg-type]
    context = replace(_context(vector), repo_did="did:web:other.invalid")

    with pytest.raises(ValidationError) as captured:
        validate_record(source, context=context)
    assert captured.value.reason_code == "authority_repo_mismatch"


def test_admission_requires_a_submission_collection_reference() -> None:
    vector = _vectors()["admission"]
    source = _json(vector["path"])  # type: ignore[arg-type]
    submission = source["submission"]
    assert isinstance(submission, dict)
    submission["uri"] = (
        "at://did:web:alice.invalid/app.phlogiston.community.profile/3jzfcijpj2z2b"
    )

    with pytest.raises(ValidationError) as captured:
        validate_record(source, context=_context(vector))
    assert captured.value.reason_code == "strong_ref_mismatch"


def test_authority_records_require_community_repo_actor_and_deterministic_key() -> None:
    vector = _vectors()["admission"]
    source = _json(vector["path"])  # type: ignore[arg-type]
    parsed = AdmissionRecord.from_record(source)
    assert admission_rkey(parsed.submission) == vector["rkey"]

    context = _context(vector)
    object.__setattr__(context, "administrator_did", "did:web:other.invalid")
    with pytest.raises(ValidationError, match="actor_unauthorized"):
        validate_record(source, context=context)

    wrong_key = _context(vector)
    object.__setattr__(wrong_key, "rkey", "admit-" + "0" * 64)
    with pytest.raises(ValidationError, match="strong_ref_mismatch"):
        validate_record(source, context=wrong_key)


def test_removal_is_create_only_and_uses_exact_admission_key() -> None:
    vector = _vectors()["mod_action"]
    source = _json(vector["path"])  # type: ignore[arg-type]
    parsed = ModActionRecord.from_record(source)
    assert removal_rkey(parsed.admission) == vector["rkey"]

    updated = _context(vector)
    object.__setattr__(updated, "operation", RepositoryOperation.UPDATE)
    with pytest.raises(ValidationError, match="authority_record_mutated"):
        validate_record(source, context=updated)

    wrong_key = replace(_context(vector), rkey="remove-" + "0" * 64)
    with pytest.raises(ValidationError) as captured:
        validate_record(source, context=wrong_key)
    assert captured.value.reason_code == "strong_ref_mismatch"


def test_removal_and_admission_subjects_must_agree_exactly() -> None:
    vectors = _vectors()
    admission = AdmissionRecord.from_record(
        _json(vectors["admission"]["path"])  # type: ignore[arg-type]
    )
    removal_source = _json(vectors["mod_action"]["path"])  # type: ignore[arg-type]
    subject = removal_source["subject"]
    assert isinstance(subject, dict)
    subject["uri"] = "at://did:web:alice.invalid/app.bsky.feed.post/3jzfcijpj2z2c"
    removal = ModActionRecord.from_record(removal_source)

    with pytest.raises(ValidationError) as captured:
        validate_removal_references(removal, admission)
    assert captured.value.reason_code == "strong_ref_mismatch"


def test_unsupported_action_is_domain_invalid_even_though_known_values_are_open() -> (
    None
):
    vector = _vectors()["mod_action"]
    source = _json(vector["path"])  # type: ignore[arg-type]
    source["action"] = "lock"
    with pytest.raises(ValidationError, match="unsupported_action"):
        validate_record(source, context=_context(vector))


def test_timestamp_skew_boundary_and_fail_closed_removal_rule() -> None:
    vectors = _vectors()
    accepted = datetime(2026, 7, 10, 14, tzinfo=UTC)
    submission_source = _json(vectors["submit"]["path"])  # type: ignore[arg-type]
    submission_source["createdAt"] = "2026-07-10T14:05:00Z"
    assert not validate_record(
        submission_source,
        context=_context(vectors["submit"], accepted_at=accepted),
    ).findings

    submission_source["createdAt"] = "2026-07-10T14:05:00.0000001Z"
    with pytest.raises(ValidationError, match="created_at_future"):
        validate_record(
            submission_source,
            context=_context(vectors["submit"], accepted_at=accepted),
        )

    removal_source = _json(vectors["mod_action"]["path"])  # type: ignore[arg-type]
    removal_source["createdAt"] = "2026-07-10T15:00:00Z"
    removal = validate_record(
        removal_source,
        context=_context(vectors["mod_action"], accepted_at=accepted),
    )
    assert removal.findings == ("created_at_future",)


@pytest.mark.parametrize("name", ["profile", "admission"])
def test_future_signed_time_invalidates_profile_and_admission(name: str) -> None:
    vector = _vectors()[name]
    source = _json(vector["path"])  # type: ignore[arg-type]
    source["createdAt"] = "2026-07-10T14:05:00.0000001Z"

    with pytest.raises(ValidationError) as captured:
        validate_record(
            source,
            context=_context(
                vector,
                accepted_at=datetime(2026, 7, 10, 14, tzinfo=UTC),
            ),
        )
    assert captured.value.reason_code == "created_at_future"
    assert captured.value.path == ("createdAt",)


def test_source_received_and_signed_record_times_remain_distinct() -> None:
    vector = _vectors()["submit"]
    source = _json(vector["path"])  # type: ignore[arg-type]
    source["createdAt"] = "2026-07-10T10:01:00-04:00"
    delivery = IncomingDelivery(
        source="fixture",
        cursor="cursor-1",
        source_event_time=datetime(2026, 7, 10, 14, 2, tzinfo=UTC),
        received_at=datetime(2026, 7, 10, 14, 3, tzinfo=UTC),
        raw_envelope=source,
        trust_mode="test_fixture",
        verification_outcome="verified",
        verification_method="fixture",
        verifier_version="1",
    )
    validated = validate_record(
        source,
        context=_context(vector, accepted_at=delivery.received_at),
    ).record

    assert validated.created_at_raw == "2026-07-10T10:01:00-04:00"
    assert normalized_created_at(validated) == "2026-07-10T14:01:00Z"
    assert (
        validated.created_at,
        delivery.source_event_time,
        delivery.received_at,
    ) == (
        datetime(2026, 7, 10, 14, 1, tzinfo=UTC),
        datetime(2026, 7, 10, 14, 2, tzinfo=UTC),
        datetime(2026, 7, 10, 14, 3, tzinfo=UTC),
    )


def test_validation_context_rejects_non_datetime_accepted_time() -> None:
    vector = _vectors()["submit"]
    with pytest.raises(ValidationError) as captured:
        replace(
            _context(vector),
            first_accepted_at="2026-07-10T14:00:00Z",  # type: ignore[arg-type]
        )
    assert captured.value.reason_code == "datetime_invalid"


def test_reference_agreement_is_checked_separately_from_lexicon_shape() -> None:
    vectors = _vectors()
    submission = SubmissionRecord.from_record(
        _json(vectors["submit"]["path"])  # type: ignore[arg-type]
    )
    admission_source = _json(vectors["admission"]["path"])  # type: ignore[arg-type]
    admission_source["subject"] = {
        **admission_source["subject"],  # type: ignore[dict-item]
        "cid": "bafyreidfayvfuwqa7qlnopdjiqrxzs6blmoeu4rujcjtnci5beludirz2a",
    }
    admission = AdmissionRecord.from_record(admission_source)
    with pytest.raises(ValidationError, match="strong_ref_mismatch"):
        validate_admission_references(admission, submission)
