"""Strict fixture-only SCV0 wire translation into immutable M1 values.

This module parses one explicitly noncanonical JSON profile. It does not
qualify ATProto state, resolve identities, authorize a writer, or admit an
item. Expected Space, author, community, and source values are supplied by a
separate boundary and must match exactly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from community_model import ValidationError, canonical_json_bytes, sha256_digest
from community_model.canonical import validate_sha256
from community_model.identifiers import (
    normalize_rfc3339,
    validate_cid,
    validate_did,
    validate_nsid,
    validate_rkey,
)
from community_space_model import (
    CommunityAdmission,
    CommunityIdentity,
    ExactSpaceRecordReference,
    ModeratorAuthorization,
    PostReference,
    SpaceIdentity,
    Submission,
)

WIRE_PROFILE: Final = "scv0-m3-test-wire/1"
NAMESPACE_STATUS: Final = "synthetic-noncanonical-invalid.test"
_TEST_NSID_PREFIX: Final = "test.invalid."
_TEST_DID_SUFFIX: Final = ".invalid.test"
_TEST_SPACE_TYPE: Final = "test.invalid.community"
_TEST_COLLECTIONS: Final = {
    "source_post": "test.invalid.community.post",
    "submission": "test.invalid.community.submit",
    "admission_input": "test.invalid.community.admission",
}


class WireRecordKind(StrEnum):
    SOURCE_POST = "source_post"
    SUBMISSION = "submission"
    ADMISSION_INPUT = "admission_input"


_NON_CLAIMS: Final = (
    "live_atproto_validity",
    "did_resolution",
    "writer_authorization",
    "community_admission_policy",
    "reader_visibility",
    "governance_authority",
)

_VERIFIED_CLAIMS: Final = {
    WireRecordKind.SOURCE_POST: (
        "canonical_fixture_shape",
        "noncanonical_namespace_enforced",
        "space_context_matched",
        "author_context_matched",
        "exact_record_reference_constructed",
    ),
    WireRecordKind.SUBMISSION: (
        "canonical_fixture_shape",
        "noncanonical_namespace_enforced",
        "source_reference_matched",
        "community_context_matched",
        "submission_occurrence_matched",
        "submission_constructed",
    ),
    WireRecordKind.ADMISSION_INPUT: (
        "canonical_fixture_shape",
        "noncanonical_namespace_enforced",
        "admission_context_matched",
        "existing_authorization_composed",
        "admission_value_constructed",
    ),
}


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValidationError(
            "wire_field_invalid", f"{field} must be a nonempty NUL-free string"
        )
    return value


def _object(
    value: object,
    *,
    field: str,
    exact_fields: frozenset[str],
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValidationError("wire_shape_invalid", f"{field} must be an object")
    keys = frozenset(value)
    if keys != exact_fields:
        missing = sorted(exact_fields - keys)
        unknown = sorted(keys - exact_fields)
        raise ValidationError(
            "wire_fields_invalid",
            f"{field} fields differ; missing={missing!r}, unknown={unknown!r}",
        )
    return value


def _test_did(value: object, *, field: str) -> str:
    did = validate_did(value)
    if not did.endswith(_TEST_DID_SUFFIX):
        raise ValidationError(
            "wire_live_identity_refused",
            f"{field} must use the synthetic invalid.test fixture namespace",
        )
    return did


def _test_nsid(value: object, *, field: str) -> str:
    nsid = validate_nsid(value)
    if not nsid.startswith(_TEST_NSID_PREFIX):
        raise ValidationError(
            "wire_canonical_namespace_refused",
            f"{field} must use the noncanonical test.invalid fixture namespace",
        )
    return nsid


def _receipt(value: object, *, field: str) -> str:
    try:
        return validate_sha256(value)
    except ValidationError as exc:
        raise ValidationError(
            "wire_receipt_invalid", f"{field} must be a sha256 receipt ID"
        ) from exc


def _require_collection(
    record: ExactSpaceRecordReference, kind: WireRecordKind
) -> None:
    expected = _TEST_COLLECTIONS[kind]
    if record.collection != expected:
        raise ValidationError(
            "wire_record_role_mismatch",
            f"{kind.value} requires the frozen fixture collection {expected!r}",
        )


def _reject_constant(value: str) -> None:
    raise ValidationError("wire_json_invalid", f"invalid JSON constant {value!r}")


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(
                "wire_duplicate_key", f"duplicate JSON object key {key!r}"
            )
        result[key] = value
    return result


def _decode(payload: bytes) -> dict[str, object]:
    if not isinstance(payload, bytes) or not payload:
        raise ValidationError("wire_json_invalid", "wire payload must be bytes")
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except ValidationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "wire_json_invalid", "wire payload is not strict JSON"
        ) from exc
    if not isinstance(value, dict):
        raise ValidationError("wire_shape_invalid", "wire payload must be an object")
    if canonical_json_bytes(value) != payload:
        raise ValidationError(
            "wire_noncanonical",
            "wire fixture must use the frozen canonical JSON encoding",
        )
    return value


def _profile(root: dict[str, object], *, kind: WireRecordKind) -> None:
    if root["profile"] != WIRE_PROFILE:
        raise ValidationError("wire_profile_unsupported", "unsupported wire profile")
    if root["namespaceStatus"] != NAMESPACE_STATUS:
        raise ValidationError(
            "wire_namespace_status_invalid",
            "wire fixture must declare its namespace noncanonical",
        )
    if root["kind"] != kind:
        raise ValidationError("wire_kind_mismatch", f"expected {kind.value!r}")


@dataclass(frozen=True, slots=True)
class WireSpaceInput:
    authority_did: str
    space_type: str
    skey: str
    uri: str

    @classmethod
    def parse(cls, value: object) -> WireSpaceInput:
        raw = _object(
            value,
            field="space",
            exact_fields=frozenset({"authorityDid", "spaceType", "skey", "uri"}),
        )
        item = cls(
            authority_did=_test_did(raw["authorityDid"], field="authorityDid"),
            space_type=_test_nsid(raw["spaceType"], field="spaceType"),
            skey=validate_rkey(raw["skey"]),
            uri=_text(raw["uri"], field="space.uri"),
        )
        if item.to_model().uri != item.uri:
            raise ValidationError(
                "wire_space_uri_mismatch",
                "supplied Space URI does not match its exact identity fields",
            )
        if item.space_type != _TEST_SPACE_TYPE:
            raise ValidationError(
                "wire_space_type_mismatch",
                "wire fixture must use the frozen noncanonical Space type",
            )
        return item

    def to_model(self) -> SpaceIdentity:
        return SpaceIdentity(
            authority_did=self.authority_did,
            space_type=self.space_type,
            skey=self.skey,
        )


@dataclass(frozen=True, slots=True)
class WireRecordInput:
    space: WireSpaceInput
    author_did: str
    collection: str
    rkey: str
    cid: str
    uri: str

    @classmethod
    def parse(cls, value: object) -> WireRecordInput:
        raw = _object(
            value,
            field="record",
            exact_fields=frozenset(
                {"space", "authorDid", "collection", "rkey", "cid", "uri"}
            ),
        )
        item = cls(
            space=WireSpaceInput.parse(raw["space"]),
            author_did=_test_did(raw["authorDid"], field="record.authorDid"),
            collection=_test_nsid(raw["collection"], field="record.collection"),
            rkey=validate_rkey(raw["rkey"]),
            cid=validate_cid(raw["cid"], require_dag_cbor=True),
            uri=_text(raw["uri"], field="record.uri"),
        )
        if item.to_model().uri != item.uri:
            raise ValidationError(
                "wire_record_uri_mismatch",
                "supplied record URI does not match its exact identity fields",
            )
        return item

    def to_model(self) -> ExactSpaceRecordReference:
        return ExactSpaceRecordReference(
            space=self.space.to_model(),
            author_did=self.author_did,
            collection=self.collection,
            rkey=self.rkey,
            cid=self.cid,
        )


@dataclass(frozen=True, slots=True)
class WireTranslationReceipt:
    record_kind: WireRecordKind
    exact_wire_sha256: str
    domain_value_id: str
    verified_claims: tuple[str, ...]
    explicit_non_claims: tuple[str, ...] = _NON_CLAIMS
    profile: str = WIRE_PROFILE

    def __post_init__(self) -> None:
        kind = WireRecordKind(self.record_kind)
        object.__setattr__(self, "record_kind", kind)
        validate_sha256(self.exact_wire_sha256)
        validate_sha256(self.domain_value_id)
        if self.profile != WIRE_PROFILE:
            raise ValidationError(
                "wire_profile_unsupported", "unsupported wire profile"
            )
        if self.explicit_non_claims != _NON_CLAIMS:
            raise ValidationError(
                "wire_claim_upgrade_refused",
                "translation non-claims are fixed by the compatibility profile",
            )
        if self.verified_claims != _VERIFIED_CLAIMS[kind]:
            raise ValidationError(
                "wire_claim_upgrade_refused",
                "translation claims are fixed by record kind",
            )

    @property
    def receipt_id(self) -> str:
        return sha256_digest(
            canonical_json_bytes(
                {
                    "profile": self.profile,
                    "kind": self.record_kind,
                    "wireSha256": self.exact_wire_sha256,
                    "domainValueId": self.domain_value_id,
                    "verifiedClaims": self.verified_claims,
                    "explicitNonClaims": self.explicit_non_claims,
                }
            )
        )


@dataclass(frozen=True, slots=True)
class AdaptedPost:
    post: PostReference
    receipt: WireTranslationReceipt


@dataclass(frozen=True, slots=True)
class AdaptedSubmission:
    submission: Submission
    receipt: WireTranslationReceipt


@dataclass(frozen=True, slots=True)
class AdaptedAdmissionInput:
    admission: CommunityAdmission
    receipt: WireTranslationReceipt


def _translation(
    *, payload: bytes, kind: WireRecordKind, value_id: str
) -> WireTranslationReceipt:
    return WireTranslationReceipt(
        record_kind=kind,
        exact_wire_sha256=sha256_digest(payload),
        domain_value_id=value_id,
        verified_claims=_VERIFIED_CLAIMS[kind],
    )


def adapt_source_post(
    payload: bytes,
    *,
    expected_space: SpaceIdentity,
    expected_author_did: str,
) -> AdaptedPost:
    """Translate one exact synthetic post record into an M1 PostReference."""

    root = _object(
        _decode(payload),
        field="source_post",
        exact_fields=frozenset(
            {
                "profile",
                "namespaceStatus",
                "kind",
                "record",
                "sourceQualificationReceiptId",
            }
        ),
    )
    _profile(root, kind=WireRecordKind.SOURCE_POST)
    wire_record = WireRecordInput.parse(root["record"])
    record = wire_record.to_model()
    _require_collection(record, WireRecordKind.SOURCE_POST)
    if record.space != expected_space:
        raise ValidationError(
            "wire_space_context_mismatch",
            "source record does not match the separately expected Space",
        )
    validate_did(expected_author_did)
    if record.author_did != expected_author_did:
        raise ValidationError(
            "wire_author_context_mismatch",
            "source record does not match the separately expected author",
        )
    post = PostReference(
        record=record,
        source_qualification_receipt_id=_receipt(
            root["sourceQualificationReceiptId"],
            field="sourceQualificationReceiptId",
        ),
    )
    return AdaptedPost(
        post=post,
        receipt=_translation(
            payload=payload,
            kind=WireRecordKind.SOURCE_POST,
            value_id=post.reference_id,
        ),
    )


def adapt_submission(
    payload: bytes,
    *,
    post: PostReference,
    expected_community: CommunityIdentity,
) -> AdaptedSubmission:
    """Translate one synthetic submission bound to an existing M1 post."""

    root = _object(
        _decode(payload),
        field="submission",
        exact_fields=frozenset(
            {
                "profile",
                "namespaceStatus",
                "kind",
                "record",
                "source",
                "targetCommunity",
                "submittingActorDid",
                "submittedAt",
                "submissionEvidenceReceiptId",
                "occurrenceId",
            }
        ),
    )
    _profile(root, kind=WireRecordKind.SUBMISSION)
    source = _object(
        root["source"],
        field="source",
        exact_fields=frozenset({"referenceId", "uri", "cid"}),
    )
    if (
        _receipt(source["referenceId"], field="source.referenceId") != post.reference_id
        or source["uri"] != post.record.uri
        or source["cid"] != post.record.cid
    ):
        raise ValidationError(
            "wire_source_reference_mismatch",
            "submission source does not match the supplied qualified post",
        )
    target = _object(
        root["targetCommunity"],
        field="targetCommunity",
        exact_fields=frozenset({"identityId", "actorDid"}),
    )
    if (
        _receipt(target["identityId"], field="targetCommunity.identityId")
        != expected_community.identity_id
        or target["actorDid"] != expected_community.community_actor_did
    ):
        raise ValidationError(
            "wire_community_context_mismatch",
            "submission target does not match the separately expected community",
        )
    record = WireRecordInput.parse(root["record"]).to_model()
    _require_collection(record, WireRecordKind.SUBMISSION)
    submission = Submission(
        record=record,
        post=post,
        submitting_actor_did=_test_did(
            root["submittingActorDid"], field="submittingActorDid"
        ),
        community=expected_community,
        submitted_at=normalize_rfc3339(root["submittedAt"]),
        submission_evidence_receipt_id=_receipt(
            root["submissionEvidenceReceiptId"],
            field="submissionEvidenceReceiptId",
        ),
    )
    if _receipt(root["occurrenceId"], field="occurrenceId") != submission.submission_id:
        raise ValidationError(
            "wire_occurrence_mismatch",
            "submission occurrence does not match the constructed M1 value",
        )
    return AdaptedSubmission(
        submission=submission,
        receipt=_translation(
            payload=payload,
            kind=WireRecordKind.SUBMISSION,
            value_id=submission.submission_id,
        ),
    )


def adapt_admission_input(
    payload: bytes,
    *,
    community: CommunityIdentity,
    post: PostReference,
    submission: Submission,
    authorization: ModeratorAuthorization,
) -> AdaptedAdmissionInput:
    """Translate a fixture placeholder using an independently supplied authorization."""

    root = _object(
        _decode(payload),
        field="admission_input",
        exact_fields=frozenset(
            {
                "profile",
                "namespaceStatus",
                "kind",
                "record",
                "communityIdentityId",
                "postReferenceId",
                "submissionId",
                "sourceObservationReceiptId",
                "admittedAt",
            }
        ),
    )
    _profile(root, kind=WireRecordKind.ADMISSION_INPUT)
    if (
        _receipt(root["communityIdentityId"], field="communityIdentityId")
        != community.identity_id
        or _receipt(root["postReferenceId"], field="postReferenceId")
        != post.reference_id
        or _receipt(root["submissionId"], field="submissionId")
        != submission.submission_id
    ):
        raise ValidationError(
            "wire_admission_context_mismatch",
            "admission placeholder does not match its supplied M1 context",
        )
    record = WireRecordInput.parse(root["record"]).to_model()
    _require_collection(record, WireRecordKind.ADMISSION_INPUT)
    admission = CommunityAdmission(
        record=record,
        community=community,
        post=post,
        submission=submission,
        authorization=authorization,
        source_observation_receipt_id=_receipt(
            root["sourceObservationReceiptId"],
            field="sourceObservationReceiptId",
        ),
        admitted_at=normalize_rfc3339(root["admittedAt"]),
    )
    return AdaptedAdmissionInput(
        admission=admission,
        receipt=_translation(
            payload=payload,
            kind=WireRecordKind.ADMISSION_INPUT,
            value_id=admission.admission_id,
        ),
    )


def refuse_wire_claim_upgrade(labels: dict[str, object]) -> None:
    """No caller or UI label can add semantics to a translation receipt."""

    if not isinstance(labels, dict):
        raise ValidationError("wire_claim_upgrade_refused", "labels must be an object")
    if labels:
        raise ValidationError(
            "wire_claim_upgrade_refused",
            "wire translation cannot add approval, visibility, or authority claims",
        )
