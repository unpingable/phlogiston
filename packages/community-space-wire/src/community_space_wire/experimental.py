"""Strict additive adapter for the disposable Juniper Spaces-alpha records.

Inputs have already crossed the SA1 record-content boundary. This module only
checks the frozen experimental record shape and composes existing M1 values;
it performs no acquisition, cryptography, authorization, or write.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from types import MappingProxyType
from typing import Final

from community_model import ValidationError, canonical_json_bytes, sha256_digest
from community_model.canonical import validate_sha256
from community_model.identifiers import normalize_rfc3339, validate_did
from community_space_model import (
    AuthorWithdrawal,
    CommunityAdmission,
    CommunityIdentity,
    ExactSpaceRecordReference,
    ModeratorAuthorization,
    PostReference,
    RemovalRecord,
    Submission,
)

EXPERIMENTAL_PREFIX: Final = "net.sp00ky.juniper-pds.authority"
SPACE_TYPE: Final = f"{EXPERIMENTAL_PREFIX}.juniperCommunity"
PERMISSION_SET: Final = f"{EXPERIMENTAL_PREFIX}.juniperPermissions"
POST_COLLECTION: Final = f"{EXPERIMENTAL_PREFIX}.juniperPost"
SUBMISSION_COLLECTION: Final = f"{EXPERIMENTAL_PREFIX}.juniperSubmission"
ADMISSION_COLLECTION: Final = f"{EXPERIMENTAL_PREFIX}.juniperAdmission"
REMOVAL_COLLECTION: Final = f"{EXPERIMENTAL_PREFIX}.juniperRemoval"
WITHDRAWAL_COLLECTION: Final = f"{EXPERIMENTAL_PREFIX}.juniperWithdrawal"
CONSENT_PROFILE: Final = "scv0-exact-public-presentation-consent/1"
EXPERIMENTAL_LEXICONS: Final = (
    SPACE_TYPE,
    PERMISSION_SET,
    POST_COLLECTION,
    SUBMISSION_COLLECTION,
    ADMISSION_COLLECTION,
    REMOVAL_COLLECTION,
    WITHDRAWAL_COLLECTION,
)


def load_experimental_lexicon(nsid: str) -> Mapping[str, object]:
    """Load one pinned schema without implying that it is published upstream."""

    if nsid not in EXPERIMENTAL_LEXICONS:
        raise ValidationError(
            "experimental_lexicon_unsupported", "unsupported Juniper alpha Lexicon"
        )
    path = resources.files("community_space_wire").joinpath("lexicons", f"{nsid}.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "experimental_lexicon_invalid", "could not load Juniper alpha Lexicon"
        ) from exc
    if (
        not isinstance(value, dict)
        or value.get("lexicon") != 1
        or value.get("id") != nsid
    ):
        raise ValidationError(
            "experimental_lexicon_invalid", "Juniper alpha Lexicon identity mismatch"
        )
    return MappingProxyType(value)


def _object(
    value: object, *, field: str, exact_fields: frozenset[str]
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValidationError("live_record_shape_invalid", f"{field} must be an object")
    keys = frozenset(value)
    if keys != exact_fields:
        raise ValidationError(
            "live_record_fields_invalid",
            f"{field} fields differ; missing={sorted(exact_fields - keys)!r}, "
            f"unknown={sorted(keys - exact_fields)!r}",
        )
    return value


def _text(value: object, *, field: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or "\x00" in value or (not value and not allow_empty):
        raise ValidationError(
            "live_record_field_invalid", f"{field} must be NUL-free text"
        )
    return value


def _typed(value: object, *, nsid: str, fields: frozenset[str]) -> Mapping[str, object]:
    raw = _object(value, field=nsid, exact_fields=fields | {"$type"})
    if raw["$type"] != nsid:
        raise ValidationError(
            "live_record_type_mismatch", "record $type does not match collection"
        )
    return raw


def _receipt(value: object, *, field: str) -> str:
    try:
        return validate_sha256(value)
    except ValidationError as exc:
        raise ValidationError(
            "live_record_receipt_invalid", f"{field} must be a sha256 receipt ID"
        ) from exc


def _strong_ref(value: object, *, field: str) -> tuple[str, str]:
    raw = _object(value, field=field, exact_fields=frozenset({"uri", "cid"}))
    return _text(raw["uri"], field=f"{field}.uri"), _text(
        raw["cid"], field=f"{field}.cid"
    )


def _require_record_role(
    record: ExactSpaceRecordReference, *, collection: str, author_did: str
) -> None:
    if not isinstance(record, ExactSpaceRecordReference):
        raise ValidationError(
            "live_record_reference_invalid", "exact record is required"
        )
    if record.collection != collection:
        raise ValidationError(
            "live_record_collection_mismatch", "record uses another collection"
        )
    if record.author_did != author_did:
        raise ValidationError("author_binding_mismatch", "record author differs")
    if record.space.space_type != SPACE_TYPE:
        raise ValidationError(
            "space_binding_mismatch", "record uses another Space type"
        )


@dataclass(frozen=True, slots=True)
class DisclosedPostFields:
    title: str
    body: str
    author_display_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", _text(self.title, field="title"))
        object.__setattr__(
            self, "body", _text(self.body, field="body", allow_empty=True)
        )
        object.__setattr__(
            self,
            "author_display_reference",
            _text(self.author_display_reference, field="authorDisplayReference"),
        )

    @property
    def presentation_id(self) -> str:
        return sha256_digest(
            canonical_json_bytes(
                {
                    "title": self.title,
                    "body": self.body,
                    "authorDisplayReference": self.author_display_reference,
                }
            )
        )


@dataclass(frozen=True, slots=True)
class AdaptedLivePost:
    post: PostReference
    content: DisclosedPostFields
    created_at: str


@dataclass(frozen=True, slots=True)
class AdaptedLiveSubmission:
    submission: Submission
    presentation: DisclosedPostFields
    consent_profile: str


def adapt_live_post(
    value: object,
    *,
    record: ExactSpaceRecordReference,
    qualification_receipt_id: str,
    expected_author_did: str,
) -> AdaptedLivePost:
    raw = _typed(
        value,
        nsid=POST_COLLECTION,
        fields=frozenset({"title", "body", "createdAt"}),
    )
    validate_did(expected_author_did)
    _require_record_role(
        record, collection=POST_COLLECTION, author_did=expected_author_did
    )
    receipt = _receipt(qualification_receipt_id, field="qualificationReceiptId")
    created_at = normalize_rfc3339(raw["createdAt"])
    content = DisclosedPostFields(
        title=_text(raw["title"], field="title"),
        body=_text(raw["body"], field="body", allow_empty=True),
        author_display_reference=expected_author_did,
    )
    return AdaptedLivePost(
        post=PostReference(record, receipt), content=content, created_at=created_at
    )


def adapt_live_submission(
    value: object,
    *,
    record: ExactSpaceRecordReference,
    post: PostReference,
    qualification_receipt_id: str,
    expected_community: CommunityIdentity,
) -> AdaptedLiveSubmission:
    raw = _typed(
        value,
        nsid=SUBMISSION_COLLECTION,
        fields=frozenset(
            {"subject", "communityActor", "consentProfile", "presentation", "createdAt"}
        ),
    )
    author_did = post.record.author_did
    _require_record_role(
        record, collection=SUBMISSION_COLLECTION, author_did=author_did
    )
    if record.space != post.record.space or expected_community.space != record.space:
        raise ValidationError("space_binding_mismatch", "submission Space differs")
    if raw["communityActor"] != expected_community.community_actor_did:
        raise ValidationError(
            "community_binding_mismatch", "submission names another community actor"
        )
    if raw["consentProfile"] != CONSENT_PROFILE:
        raise ValidationError("consent_profile_invalid", "unsupported consent profile")
    if _strong_ref(raw["subject"], field="subject") != (
        post.record.uri,
        post.record.cid,
    ):
        raise ValidationError(
            "source_reference_mismatch", "submission does not bind the exact post"
        )
    presentation = _object(
        raw["presentation"],
        field="presentation",
        exact_fields=frozenset({"title", "body", "authorDisplayReference"}),
    )
    disclosed = DisclosedPostFields(
        title=_text(presentation["title"], field="presentation.title"),
        body=_text(presentation["body"], field="presentation.body", allow_empty=True),
        author_display_reference=_text(
            presentation["authorDisplayReference"],
            field="presentation.authorDisplayReference",
        ),
    )
    submission = Submission(
        record=record,
        post=post,
        submitting_actor_did=author_did,
        community=expected_community,
        submitted_at=normalize_rfc3339(raw["createdAt"]),
        submission_evidence_receipt_id=_receipt(
            qualification_receipt_id, field="qualificationReceiptId"
        ),
    )
    return AdaptedLiveSubmission(submission, disclosed, CONSENT_PROFILE)


def adapt_live_admission(
    value: object,
    *,
    record: ExactSpaceRecordReference,
    post: PostReference,
    submission: Submission,
    authorization: ModeratorAuthorization,
    community: CommunityIdentity,
) -> CommunityAdmission:
    raw = _typed(
        value,
        nsid=ADMISSION_COLLECTION,
        fields=frozenset(
            {
                "submission",
                "subject",
                "authorizationOccurrence",
                "sourceObservationReceipt",
                "createdAt",
            }
        ),
    )
    _require_record_role(
        record,
        collection=ADMISSION_COLLECTION,
        author_did=community.community_actor_did,
    )
    if _strong_ref(raw["submission"], field="submission") != (
        submission.record.uri,
        submission.record.cid,
    ):
        raise ValidationError(
            "submission_reference_mismatch", "admission targets another submission"
        )
    if _strong_ref(raw["subject"], field="subject") != (
        post.record.uri,
        post.record.cid,
    ):
        raise ValidationError(
            "source_reference_mismatch", "admission targets another post"
        )
    if raw["authorizationOccurrence"] != authorization.authorization_id:
        raise ValidationError(
            "authorization_occurrence_mismatch", "admission relabels authorization"
        )
    source_receipt = _receipt(
        raw["sourceObservationReceipt"], field="sourceObservationReceipt"
    )
    return CommunityAdmission(
        record=record,
        community=community,
        post=post,
        submission=submission,
        authorization=authorization,
        source_observation_receipt_id=source_receipt,
        admitted_at=normalize_rfc3339(raw["createdAt"]),
    )


def adapt_live_removal(
    value: object,
    *,
    record: ExactSpaceRecordReference,
    admission: CommunityAdmission,
    authorization: ModeratorAuthorization,
) -> RemovalRecord:
    raw = _typed(
        value,
        nsid=REMOVAL_COLLECTION,
        fields=frozenset(
            {
                "admission",
                "subject",
                "authorizationOccurrence",
                "reasonCategory",
                "createdAt",
            }
        ),
    )
    community = admission.community
    _require_record_role(
        record,
        collection=REMOVAL_COLLECTION,
        author_did=community.community_actor_did,
    )
    if _strong_ref(raw["admission"], field="admission") != (
        admission.record.uri,
        admission.record.cid,
    ):
        raise ValidationError(
            "removal_admission_mismatch", "removal targets another admission"
        )
    if _strong_ref(raw["subject"], field="subject") != (
        admission.post.record.uri,
        admission.post.record.cid,
    ):
        raise ValidationError(
            "source_reference_mismatch", "removal targets another post"
        )
    if raw["authorizationOccurrence"] != authorization.authorization_id:
        raise ValidationError(
            "authorization_occurrence_mismatch", "removal relabels authorization"
        )
    return RemovalRecord(
        record=record,
        admission=admission,
        authorization=authorization,
        reason_category=_text(raw["reasonCategory"], field="reasonCategory"),
        removed_at=normalize_rfc3339(raw["createdAt"]),
    )


def adapt_live_withdrawal(
    value: object,
    *,
    record: ExactSpaceRecordReference,
    admission: CommunityAdmission,
    qualification_receipt_id: str,
) -> AuthorWithdrawal:
    raw = _typed(
        value,
        nsid=WITHDRAWAL_COLLECTION,
        fields=frozenset(
            {"submission", "admission", "subject", "communityActor", "createdAt"}
        ),
    )
    submission = admission.submission
    author_did = admission.post.record.author_did
    _require_record_role(
        record, collection=WITHDRAWAL_COLLECTION, author_did=author_did
    )
    expected = {
        "submission": (submission.record.uri, submission.record.cid),
        "admission": (admission.record.uri, admission.record.cid),
        "subject": (admission.post.record.uri, admission.post.record.cid),
    }
    for field, strong_ref in expected.items():
        if _strong_ref(raw[field], field=field) != strong_ref:
            raise ValidationError(
                "withdrawal_occurrence_mismatch",
                f"withdrawal {field} targets another occurrence",
            )
    if raw["communityActor"] != admission.community.community_actor_did:
        raise ValidationError(
            "community_binding_mismatch", "withdrawal names another community"
        )
    return AuthorWithdrawal(
        record=record,
        admission=admission,
        submission=submission,
        withdrawal_evidence_receipt_id=_receipt(
            qualification_receipt_id, field="qualificationReceiptId"
        ),
        withdrawn_at=normalize_rfc3339(raw["createdAt"]),
    )
