"""Closed V0 vocabularies shared by the inert model contracts."""

from __future__ import annotations

from enum import StrEnum

PROFILE_COLLECTION = "app.phlogiston.community.profile"
SUBMISSION_COLLECTION = "app.phlogiston.community.submit"
ADMISSION_COLLECTION = "app.phlogiston.community.admission"
MOD_ACTION_COLLECTION = "app.phlogiston.community.modAction"
MEMBER_ACTION_COLLECTION = "app.phlogiston.community.memberAction"
REPLY_POLICY_COLLECTION = "app.phlogiston.community.replyPolicy"
REPLY_ADMISSION_COLLECTION = "app.phlogiston.community.replyAdmission"
REPLY_ACTION_COLLECTION = "app.phlogiston.community.replyAction"
POST_COLLECTION = "app.bsky.feed.post"

COMMUNITY_COLLECTIONS = (
    PROFILE_COLLECTION,
    SUBMISSION_COLLECTION,
    ADMISSION_COLLECTION,
    MOD_ACTION_COLLECTION,
    MEMBER_ACTION_COLLECTION,
    REPLY_POLICY_COLLECTION,
    REPLY_ADMISSION_COLLECTION,
    REPLY_ACTION_COLLECTION,
)


class RepositoryOperation(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class PayloadHashScope(StrEnum):
    DAG_CBOR = "dag_cbor"
    OBSERVER_JSON_V0 = "observer_json_v0"
    DELETE_ENVELOPE_V0 = "delete_envelope_v0"


class DeliveryTrustMode(StrEnum):
    VERIFY_REPO = "verify_repo"
    TRUST_RELAY = "trust_relay"
    TEST_FIXTURE = "test_fixture"


class ResolverTrustMode(StrEnum):
    VERIFY_REPO = "verify_repo"
    TRUST_PDS = "trust_pds"
    TEST_FIXTURE = "test_fixture"


class VerificationOutcome(StrEnum):
    VERIFIED = "verified"
    ATTESTED = "attested"
    UNVERIFIED = "unverified"
    FAILED = "failed"


class ResolutionStatus(StrEnum):
    EXACT = "exact"
    MISMATCH = "mismatch"
    MISSING = "missing"
    ERROR = "error"


class CurrentRecordStatus(StrEnum):
    PRESENT = "present"
    MISSING = "missing"
    ERROR = "error"


class ProjectionState(StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    VISIBLE = "visible"
    INVALID = "invalid"
    UNAUTHORIZED = "unauthorized"
    STALE_CID = "stale_cid"
    SUBJECT_DELETED = "subject_deleted"
    SUBJECT_UNAVAILABLE = "subject_unavailable"
    REMOVED = "removed"
    CONFLICT = "conflict"


class AuditOutcome(StrEnum):
    VALID = "valid"
    PENDING = "pending"
    INVALID = "invalid"
    UNAUTHORIZED = "unauthorized"
    IGNORED = "ignored"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"


REASON_CODES = frozenset(
    {
        "schema_invalid",
        "unsupported_record_type",
        "did_invalid",
        "at_uri_invalid",
        "cid_invalid",
        "datetime_invalid",
        "commit_revision_invalid",
        "payload_evidence_invalid",
        "created_at_future",
        "community_mismatch",
        "repo_mismatch",
        "subject_collection_invalid",
        "strong_ref_mismatch",
        "reference_pending",
        "reference_missing",
        "subject_cid_mismatch",
        "subject_deleted",
        "resolver_error",
        "authenticity_unverified",
        "authenticity_failed",
        "authority_repo_mismatch",
        "actor_unauthorized",
        "authority_record_mutated",
        "semantic_event_conflict",
        "duplicate_semantic_record",
        "unsupported_readmission",
        "unsupported_action",
        "reply_policy_mismatch",
        "reply_ancestry_invalid",
        "moderation_key_mismatch",
        "action_chain_invalid",
        "profile_unavailable",
        "projection_missing",
        "projection_incomplete",
        "projection_stale",
        "schema_incompatible",
        "ingest_stale",
        "resolve_stale",
    }
)
