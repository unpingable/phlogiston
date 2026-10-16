"""Pure SCV0-M5A projection-artifact compilation.

The compiler consumes already-validated M2 lifecycle values. It does not
fetch sources, inspect credentials, authorize readers, or decide admission.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from community_model import ValidationError, canonical_json_bytes, sha256_digest
from community_model.canonical import validate_sha256
from community_model.identifiers import normalize_rfc3339, validate_cid, validate_did
from community_space_model import CommunityIdentity, SourceRelationship
from community_space_projection import (
    REDUCER_VERSION,
    LifecycleState,
    ProjectionLifecycle,
)

COMPILER_VERSION: Final = "scv0-projection-artifact-compiler/1"
PRESENTATION_PROFILE: Final = "scv0-test-presentation/1"

_NON_CLAIMS: Final = (
    "reader_authorization",
    "membership",
    "community_legitimacy",
    "moderator_authority",
    "source_truth",
    "source_ownership",
    "repository_currentness",
    "governance_authority",
)

_SECRET_PATTERN: Final = re.compile(
    r"(?i)(?:"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\bAuthorization\s*:\s*(?:Bearer|DPoP)\s+|"
    r"\b(?:access[_ -]?token|refresh[_ -]?token|space[_ -]?credential|"
    r"dpop[_ -]?private[_ -]?key|moderator[_ -]?private[_ -]?key)\b|"
    r"\bCookie\s*:|\bSet-Cookie\s*:"
    r")"
)


def _receipt(value: object, *, field: str) -> str:
    try:
        return validate_sha256(value)
    except ValidationError as exc:
        raise ValidationError(
            "artifact_reference_invalid", f"{field} must be a sha256 identifier"
        ) from exc


def _text(value: object, *, field: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value) or "\x00" in value:
        raise ValidationError(
            "artifact_field_invalid", f"{field} must be a NUL-free string"
        )
    if _SECRET_PATTERN.search(value):
        raise ValidationError(
            "artifact_secret_material_refused",
            f"{field} contains credential/private-authority shaped material",
        )
    return value


def _contains_secret(value: object) -> bool:
    if isinstance(value, str):
        return bool(_SECRET_PATTERN.search(value))
    if isinstance(value, dict):
        return any(
            _contains_secret(key) or _contains_secret(item)
            for key, item in value.items()
        )
    if isinstance(value, list | tuple):
        return any(_contains_secret(item) for item in value)
    return False


class DisclosureMode(StrEnum):
    ORDINARY = "ordinary_reader"
    TECHNICAL_AUDIT = "technical_audit"


@dataclass(frozen=True, slots=True)
class DisclosurePolicy:
    """One fixed disclosure profile; booleans are derived, not caller switches."""

    mode: DisclosureMode | str
    policy_reference_id: str
    publication_reference_id: str

    def __post_init__(self) -> None:
        try:
            mode = DisclosureMode(self.mode)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "disclosure_policy_invalid", "unsupported disclosure policy"
            ) from exc
        object.__setattr__(self, "mode", mode)
        _receipt(self.policy_reference_id, field="policy_reference_id")
        _receipt(self.publication_reference_id, field="publication_reference_id")

    @property
    def include_presentation(self) -> bool:
        return True

    @property
    def include_technical_receipts(self) -> bool:
        return self.mode is DisclosureMode.TECHNICAL_AUDIT

    @property
    def include_available_lifecycle_links(self) -> bool:
        return self.mode is DisclosureMode.TECHNICAL_AUDIT

    @property
    def policy_id(self) -> str:
        return sha256_digest(
            canonical_json_bytes(
                {
                    "compilerVersion": COMPILER_VERSION,
                    "mode": self.mode,
                    "policyReferenceId": self.policy_reference_id,
                    "publicationReferenceId": self.publication_reference_id,
                    "includePresentation": self.include_presentation,
                    "includeTechnicalReceipts": self.include_technical_receipts,
                    "includeAvailableLifecycleLinks": self.include_available_lifecycle_links,
                }
            )
        )


@dataclass(frozen=True, slots=True)
class BoundedSourcePresentation:
    """Caller-supplied disclosed presentation, never the source record itself."""

    source_reference_id: str
    source_uri: str
    source_cid: str
    title: str
    body: str
    author_display_reference: str
    profile: str = PRESENTATION_PROFILE

    def __post_init__(self) -> None:
        _receipt(self.source_reference_id, field="source_reference_id")
        _text(self.source_uri, field="source_uri")
        validate_cid(self.source_cid, require_dag_cbor=True)
        object.__setattr__(self, "title", _text(self.title, field="title"))
        object.__setattr__(
            self, "body", _text(self.body, field="body", allow_empty=True)
        )
        object.__setattr__(
            self,
            "author_display_reference",
            _text(self.author_display_reference, field="author_display_reference"),
        )
        if self.profile != PRESENTATION_PROFILE:
            raise ValidationError(
                "presentation_profile_unsupported", "unsupported presentation profile"
            )

    @property
    def presentation_id(self) -> str:
        return sha256_digest(canonical_json_bytes(self.to_payload()))

    def to_payload(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "sourceReferenceId": self.source_reference_id,
            "sourceUri": self.source_uri,
            "sourceCid": self.source_cid,
            "title": self.title,
            "body": self.body,
            "authorDisplayReference": self.author_display_reference,
        }


@dataclass(frozen=True, slots=True)
class ArtifactReceiptReferences:
    """Disclosed identifiers only; no receipt body or authority upgrade."""

    source_qualification_receipt_id: str
    source_observation_receipt_id: str
    source_currentness_receipt_id: str
    submission_evidence_receipt_id: str
    moderator_authorization_id: str
    admission_id: str
    projection_reference_id: str
    removal_id: str | None
    withdrawal_id: str | None = None
    admission_record_uri: str | None = None
    admission_record_cid: str | None = None

    def __post_init__(self) -> None:
        for field in (
            "source_qualification_receipt_id",
            "source_observation_receipt_id",
            "source_currentness_receipt_id",
            "submission_evidence_receipt_id",
            "moderator_authorization_id",
            "admission_id",
            "projection_reference_id",
        ):
            _receipt(getattr(self, field), field=field)
        if self.removal_id is not None:
            _receipt(self.removal_id, field="removal_id")
        if self.withdrawal_id is not None:
            _receipt(self.withdrawal_id, field="withdrawal_id")
        if (self.admission_record_uri is None) != (self.admission_record_cid is None):
            raise ValidationError(
                "artifact_receipts_invalid",
                "admission record URI and CID must be disclosed together",
            )
        if self.admission_record_uri is not None:
            _text(self.admission_record_uri, field="admission_record_uri")
            validate_cid(self.admission_record_cid, require_dag_cbor=True)

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "sourceQualificationReceiptId": self.source_qualification_receipt_id,
            "sourceObservationReceiptId": self.source_observation_receipt_id,
            "sourceCurrentnessReceiptId": self.source_currentness_receipt_id,
            "submissionEvidenceReceiptId": self.submission_evidence_receipt_id,
            "moderatorAuthorizationId": self.moderator_authorization_id,
            "admissionId": self.admission_id,
            "projectionReferenceId": self.projection_reference_id,
            "removalId": self.removal_id,
        }
        if self.withdrawal_id is not None:
            payload["withdrawalId"] = self.withdrawal_id
        if self.admission_record_uri is not None:
            payload["admissionRecordUri"] = self.admission_record_uri
            payload["admissionRecordCid"] = self.admission_record_cid
        return payload


@dataclass(frozen=True, slots=True)
class ProjectionArtifactEntry:
    projection_identity: str
    projection_state_id: str
    lifecycle_state: LifecycleState | str
    community_identity_id: str
    post_reference_id: str
    source_uri: str
    admitted_source_cid: str
    author_did: str
    admission_id: str
    admitted_at: str
    source_observation_id: str
    source_relationship: str
    presentation: BoundedSourcePresentation | None
    technical_receipts: ArtifactReceiptReferences | None
    available_lifecycle_links: tuple[str, ...]
    removal_id: str | None
    withdrawal_id: str | None = None
    explicit_non_claims: tuple[str, ...] = _NON_CLAIMS

    def __post_init__(self) -> None:
        for field in (
            "projection_identity",
            "projection_state_id",
            "community_identity_id",
            "post_reference_id",
            "admission_id",
            "source_observation_id",
        ):
            _receipt(getattr(self, field), field=field)
        if self.removal_id is not None:
            _receipt(self.removal_id, field="removal_id")
        if self.withdrawal_id is not None:
            _receipt(self.withdrawal_id, field="withdrawal_id")
        try:
            state = LifecycleState(self.lifecycle_state)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "artifact_lifecycle_invalid", "unsupported lifecycle state"
            ) from exc
        if state is LifecycleState.SUGGESTED:
            raise ValidationError(
                "suggested_publication_refused",
                "suggested state cannot enter a reader artifact",
            )
        object.__setattr__(self, "lifecycle_state", state)
        validate_did(self.author_did)
        validate_cid(self.admitted_source_cid, require_dag_cbor=True)
        _text(self.source_uri, field="source_uri")
        object.__setattr__(self, "admitted_at", normalize_rfc3339(self.admitted_at))
        try:
            relationship = SourceRelationship(self.source_relationship)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "artifact_source_relationship_invalid",
                "unsupported source relationship",
            ) from exc
        object.__setattr__(self, "source_relationship", relationship)
        allowed_relationships = {
            LifecycleState.ADDED: (SourceRelationship.EXACT,),
            LifecycleState.CHANGED_AT_SOURCE: (SourceRelationship.CHANGED,),
            LifecycleState.SOURCE_UNAVAILABLE: (
                SourceRelationship.DELETED,
                SourceRelationship.UNAVAILABLE,
            ),
            LifecycleState.AUTHOR_WITHDRAWN: tuple(SourceRelationship),
            LifecycleState.REMOVED: tuple(SourceRelationship),
        }
        if relationship not in allowed_relationships[state]:
            raise ValidationError(
                "artifact_source_relationship_invalid",
                "source relationship is incompatible with lifecycle state",
            )
        if not isinstance(self.available_lifecycle_links, tuple):
            raise ValidationError(
                "artifact_lifecycle_invalid", "lifecycle links must be a tuple"
            )
        for item in self.available_lifecycle_links:
            _receipt(item, field="available_lifecycle_links")
        if len(self.available_lifecycle_links) != len(
            set(self.available_lifecycle_links)
        ):
            raise ValidationError(
                "artifact_lifecycle_invalid", "lifecycle links must be unique"
            )
        if self.explicit_non_claims != _NON_CLAIMS:
            raise ValidationError(
                "artifact_claim_upgrade_refused", "artifact non-claims are fixed"
            )
        if self.presentation is not None and not isinstance(
            self.presentation, BoundedSourcePresentation
        ):
            raise ValidationError(
                "artifact_presentation_invalid",
                "artifact presentation must be a bounded typed value",
            )
        if self.presentation is not None:
            self.presentation.__post_init__()
            if (
                self.presentation.source_reference_id != self.post_reference_id
                or self.presentation.source_uri != self.source_uri
                or self.presentation.source_cid != self.admitted_source_cid
            ):
                raise ValidationError(
                    "presentation_source_mismatch",
                    "artifact presentation does not bind its admitted source",
                )
        if self.technical_receipts is not None and not isinstance(
            self.technical_receipts, ArtifactReceiptReferences
        ):
            raise ValidationError(
                "artifact_receipts_invalid",
                "technical receipts must be a bounded typed value",
            )
        if self.technical_receipts is not None:
            self.technical_receipts.__post_init__()
            if (
                self.technical_receipts.admission_id != self.admission_id
                or self.technical_receipts.removal_id != self.removal_id
                or self.technical_receipts.withdrawal_id != self.withdrawal_id
            ):
                raise ValidationError(
                    "artifact_receipts_invalid",
                    "technical receipts do not bind the entry occurrence",
                )
        if state is not LifecycleState.ADDED and self.presentation is not None:
            raise ValidationError(
                "implicit_source_replacement_refused",
                "only exact Added state may disclose source presentation",
            )
        if state is LifecycleState.REMOVED and self.removal_id is None:
            raise ValidationError(
                "artifact_removal_invalid", "removed artifact requires removal identity"
            )
        if state is not LifecycleState.REMOVED and self.removal_id is not None:
            raise ValidationError(
                "artifact_removal_invalid", "active artifact cannot contain removal"
            )
        if state is LifecycleState.AUTHOR_WITHDRAWN and self.withdrawal_id is None:
            raise ValidationError(
                "artifact_withdrawal_invalid",
                "author-withdrawn artifact requires withdrawal identity",
            )
        if state not in {LifecycleState.AUTHOR_WITHDRAWN, LifecycleState.REMOVED}:
            if self.withdrawal_id is not None:
                raise ValidationError(
                    "artifact_withdrawal_invalid",
                    "non-withdrawn artifact cannot contain withdrawal identity",
                )

    @property
    def entry_id(self) -> str:
        return sha256_digest(canonical_json_bytes(self.to_payload()))

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "projectionIdentity": self.projection_identity,
            "projectionStateId": self.projection_state_id,
            "lifecycleState": self.lifecycle_state,
            "communityIdentityId": self.community_identity_id,
            "postReferenceId": self.post_reference_id,
            "sourceUri": self.source_uri,
            "admittedSourceCid": self.admitted_source_cid,
            "authorDid": self.author_did,
            "admissionId": self.admission_id,
            "admittedAt": self.admitted_at,
            "sourceObservationId": self.source_observation_id,
            "sourceRelationship": self.source_relationship,
            "presentation": None
            if self.presentation is None
            else self.presentation.to_payload(),
            "technicalReceipts": None
            if self.technical_receipts is None
            else self.technical_receipts.to_payload(),
            "availableLifecycleLinks": self.available_lifecycle_links,
            "removalId": self.removal_id,
            "explicitNonClaims": self.explicit_non_claims,
        }
        if self.withdrawal_id is not None:
            payload["withdrawalId"] = self.withdrawal_id
        return payload


@dataclass(frozen=True, slots=True)
class NonPublishedCandidate:
    projection_identity: str
    projection_state_id: str
    community_identity_id: str
    disclosure_policy_id: str
    reason: str = "suggested_not_reader_published"

    def __post_init__(self) -> None:
        for field in (
            "projection_identity",
            "projection_state_id",
            "community_identity_id",
            "disclosure_policy_id",
        ):
            _receipt(getattr(self, field), field=field)
        if self.reason != "suggested_not_reader_published":
            raise ValidationError(
                "suggested_publication_refused", "candidate reason is fixed"
            )

    @property
    def candidate_id(self) -> str:
        return sha256_digest(
            canonical_json_bytes(
                {
                    "compilerVersion": COMPILER_VERSION,
                    "projectionIdentity": self.projection_identity,
                    "projectionStateId": self.projection_state_id,
                    "communityIdentityId": self.community_identity_id,
                    "disclosurePolicyId": self.disclosure_policy_id,
                    "reason": self.reason,
                }
            )
        )


@dataclass(frozen=True, slots=True)
class ProjectionArtifact:
    community_identity_id: str
    community_actor_did: str
    space_identity_id: str
    projection_version: str
    disclosure_mode: DisclosureMode | str
    disclosure_policy_id: str
    disclosure_policy_reference_id: str
    publication_reference_id: str
    entries: tuple[ProjectionArtifactEntry, ...]
    compiler_version: str = COMPILER_VERSION
    explicit_non_claims: tuple[str, ...] = _NON_CLAIMS

    def __post_init__(self) -> None:
        for field in (
            "community_identity_id",
            "space_identity_id",
            "disclosure_policy_id",
            "disclosure_policy_reference_id",
            "publication_reference_id",
        ):
            _receipt(getattr(self, field), field=field)
        validate_did(self.community_actor_did)
        if self.projection_version != REDUCER_VERSION:
            raise ValidationError(
                "artifact_projection_version_invalid", "unsupported reducer version"
            )
        if self.compiler_version != COMPILER_VERSION:
            raise ValidationError(
                "artifact_compiler_version_invalid", "unsupported compiler version"
            )
        try:
            mode = DisclosureMode(self.disclosure_mode)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "disclosure_policy_invalid", "unsupported disclosure mode"
            ) from exc
        object.__setattr__(self, "disclosure_mode", mode)
        if not isinstance(self.entries, tuple) or not self.entries:
            raise ValidationError(
                "artifact_entries_invalid", "published artifact requires entries"
            )
        if len({entry.projection_identity for entry in self.entries}) != len(
            self.entries
        ):
            raise ValidationError(
                "artifact_entries_invalid",
                "artifact projection identities must be unique",
            )
        for entry in self.entries:
            if not isinstance(entry, ProjectionArtifactEntry):
                raise ValidationError(
                    "artifact_entries_invalid", "artifact entries must be typed values"
                )
            entry.__post_init__()
            if entry.community_identity_id != self.community_identity_id:
                raise ValidationError(
                    "artifact_community_mismatch", "entry belongs to another community"
                )
            if mode is DisclosureMode.ORDINARY and (
                entry.technical_receipts is not None or entry.available_lifecycle_links
            ):
                raise ValidationError(
                    "ordinary_disclosure_leak_refused",
                    "ordinary artifact cannot contain technical disclosure",
                )
            if mode is DisclosureMode.TECHNICAL_AUDIT and (
                entry.technical_receipts is None or not entry.available_lifecycle_links
            ):
                raise ValidationError(
                    "audit_disclosure_incomplete",
                    "audit artifact requires technical receipts and lifecycle links",
                )
        if self.explicit_non_claims != _NON_CLAIMS:
            raise ValidationError(
                "artifact_claim_upgrade_refused", "artifact non-claims are fixed"
            )

    @property
    def artifact_id(self) -> str:
        return sha256_digest(canonical_json_bytes(self.to_payload()))

    def to_payload(self) -> dict[str, object]:
        return {
            "compilerVersion": self.compiler_version,
            "communityIdentityId": self.community_identity_id,
            "communityActorDid": self.community_actor_did,
            "spaceIdentityId": self.space_identity_id,
            "projectionVersion": self.projection_version,
            "disclosureMode": self.disclosure_mode,
            "disclosurePolicyId": self.disclosure_policy_id,
            "disclosurePolicyReferenceId": self.disclosure_policy_reference_id,
            "publicationReferenceId": self.publication_reference_id,
            "entries": tuple(entry.to_payload() for entry in self.entries),
            "explicitNonClaims": self.explicit_non_claims,
        }

    def validate_integrity(self) -> str:
        """Re-run structural validation and return the deterministic identity."""

        self.__post_init__()
        return self.artifact_id


@dataclass(frozen=True, slots=True)
class ProjectionDisclosureInput:
    projection: ProjectionLifecycle
    declared_community_identity_id: str
    declared_lifecycle_state: LifecycleState | str
    presentation: BoundedSourcePresentation | object | None = None
    include_exact_occurrence_references: bool = False


@dataclass(frozen=True, slots=True)
class ProjectionCompilation:
    artifact: ProjectionArtifact | None
    non_published_candidates: tuple[NonPublishedCandidate, ...]
    compiler_version: str = COMPILER_VERSION

    def __post_init__(self) -> None:
        if self.compiler_version != COMPILER_VERSION:
            raise ValidationError(
                "artifact_compiler_version_invalid", "unsupported compiler version"
            )
        if self.artifact is None and not self.non_published_candidates:
            raise ValidationError(
                "artifact_compilation_empty", "compilation produced no bounded result"
            )
        if self.artifact is not None and not isinstance(
            self.artifact, ProjectionArtifact
        ):
            raise ValidationError(
                "artifact_invalid", "compilation artifact must be a typed value"
            )
        if not isinstance(self.non_published_candidates, tuple) or any(
            not isinstance(item, NonPublishedCandidate)
            for item in self.non_published_candidates
        ):
            raise ValidationError(
                "artifact_candidate_invalid", "candidate results must be typed values"
            )


class ProjectionArtifactCompiler:
    """Compile exact M2 lifecycles under one explicit disclosure profile."""

    def __init__(self, community: CommunityIdentity) -> None:
        if not isinstance(community, CommunityIdentity):
            raise ValidationError(
                "artifact_community_invalid", "compiler requires a community identity"
            )
        self._community = community

    def compile(
        self,
        inputs: tuple[ProjectionDisclosureInput, ...],
        policy: DisclosurePolicy,
    ) -> ProjectionCompilation:
        if not isinstance(inputs, tuple) or not inputs:
            raise ValidationError(
                "artifact_input_invalid", "compiler inputs must be a nonempty tuple"
            )
        if not isinstance(policy, DisclosurePolicy):
            raise ValidationError(
                "disclosure_policy_invalid", "typed disclosure policy is required"
            )
        entries: list[ProjectionArtifactEntry] = []
        candidates: list[NonPublishedCandidate] = []
        seen: set[str] = set()
        for item in inputs:
            if not isinstance(item, ProjectionDisclosureInput):
                if _contains_secret(item):
                    raise ValidationError(
                        "artifact_secret_material_refused",
                        "compiler input contains credential/private-authority material",
                    )
                raise ValidationError(
                    "artifact_input_invalid", "typed disclosure input is required"
                )
            if not isinstance(item.include_exact_occurrence_references, bool):
                raise ValidationError(
                    "artifact_input_invalid",
                    "exact occurrence disclosure flag must be boolean",
                )
            projection = item.projection
            if not isinstance(projection, ProjectionLifecycle):
                if _contains_secret(item.presentation):
                    raise ValidationError(
                        "artifact_secret_material_refused",
                        "presentation contains credential/private-authority material",
                    )
                raise ValidationError(
                    "projection_state_required", "valid M2 projection state is required"
                )
            projection.__post_init__()
            if projection.community != self._community:
                raise ValidationError(
                    "artifact_community_mismatch",
                    "projection belongs to another community",
                )
            if item.declared_community_identity_id != self._community.identity_id:
                raise ValidationError(
                    "artifact_community_mismatch",
                    "declared community identity was substituted",
                )
            try:
                declared_state = LifecycleState(item.declared_lifecycle_state)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    "artifact_lifecycle_invalid", "unsupported declared lifecycle state"
                ) from exc
            if declared_state is not projection.state:
                raise ValidationError(
                    "artifact_lifecycle_upgrade_refused",
                    "declared lifecycle differs from the qualified M2 state",
                )
            if projection.projection_identity in seen:
                raise ValidationError(
                    "artifact_projection_conflict",
                    "multiple current states were supplied for one projection",
                )
            seen.add(projection.projection_identity)

            if projection.state is LifecycleState.SUGGESTED:
                if item.presentation is not None:
                    raise ValidationError(
                        "suggested_publication_refused",
                        "suggested candidate cannot carry reader presentation",
                    )
                candidates.append(
                    NonPublishedCandidate(
                        projection_identity=projection.projection_identity,
                        projection_state_id=projection.state_id,
                        community_identity_id=self._community.identity_id,
                        disclosure_policy_id=policy.policy_id,
                    )
                )
                continue
            entries.append(
                self._entry(
                    projection,
                    item.presentation,
                    policy,
                    include_exact_occurrence_references=item.include_exact_occurrence_references,
                )
            )

        entries.sort(
            key=lambda value: (value.admitted_at, value.admission_id), reverse=True
        )
        artifact = None
        if entries:
            artifact = ProjectionArtifact(
                community_identity_id=self._community.identity_id,
                community_actor_did=self._community.community_actor_did,
                space_identity_id=self._community.space.identity_id,
                projection_version=REDUCER_VERSION,
                disclosure_mode=policy.mode,
                disclosure_policy_id=policy.policy_id,
                disclosure_policy_reference_id=policy.policy_reference_id,
                publication_reference_id=policy.publication_reference_id,
                entries=tuple(entries),
            )
        return ProjectionCompilation(
            artifact=artifact,
            non_published_candidates=tuple(candidates),
        )

    def _entry(
        self,
        projection: ProjectionLifecycle,
        presentation: object | None,
        policy: DisclosurePolicy,
        *,
        include_exact_occurrence_references: bool,
    ) -> ProjectionArtifactEntry:
        assert projection.admission is not None
        assert projection.projection_reference is not None
        if _contains_secret(presentation):
            raise ValidationError(
                "artifact_secret_material_refused",
                "presentation contains credential/private-authority material",
            )
        if projection.state is LifecycleState.ADDED:
            if not isinstance(presentation, BoundedSourcePresentation):
                raise ValidationError(
                    "presentation_required",
                    "ordinary/audit Added artifact requires bounded presentation",
                )
            post = projection.submission.post
            if (
                presentation.source_reference_id != post.reference_id
                or presentation.source_uri != post.record.uri
                or presentation.source_cid != post.record.cid
            ):
                raise ValidationError(
                    "presentation_source_mismatch",
                    "presentation does not bind the exact admitted source",
                )
            disclosed_presentation: BoundedSourcePresentation | None = presentation
        else:
            if presentation is not None:
                raise ValidationError(
                    "implicit_source_replacement_refused",
                    "changed/unavailable/removed state cannot disclose source presentation",
                )
            disclosed_presentation = None

        receipts = None
        links: tuple[str, ...] = ()
        if policy.include_technical_receipts:
            receipts = ArtifactReceiptReferences(
                source_qualification_receipt_id=projection.submission.post.source_qualification_receipt_id,
                source_observation_receipt_id=projection.source_observation.evidence_receipt_id,
                source_currentness_receipt_id=projection.source_observation.currentness_receipt_id,
                submission_evidence_receipt_id=projection.submission.submission_evidence_receipt_id,
                moderator_authorization_id=projection.admission.authorization.authorization_id,
                admission_id=projection.admission.admission_id,
                projection_reference_id=projection.projection_reference.projection_id,
                removal_id=None
                if projection.removal is None
                else projection.removal.removal_id,
                withdrawal_id=None
                if projection.author_withdrawal is None
                else projection.author_withdrawal.withdrawal_id,
                admission_record_uri=(
                    projection.admission.record.uri
                    if include_exact_occurrence_references
                    else None
                ),
                admission_record_cid=(
                    projection.admission.record.cid
                    if include_exact_occurrence_references
                    else None
                ),
            )
            links = tuple(
                value
                for value in (projection.prior_state_id, projection.state_id)
                if value is not None
            )

        return ProjectionArtifactEntry(
            projection_identity=projection.projection_identity,
            projection_state_id=projection.state_id,
            lifecycle_state=projection.state,
            community_identity_id=self._community.identity_id,
            post_reference_id=projection.submission.post.reference_id,
            source_uri=projection.submission.post.record.uri,
            admitted_source_cid=projection.submission.post.record.cid,
            author_did=projection.submission.post.record.author_did,
            admission_id=projection.admission.admission_id,
            admitted_at=projection.admission.admitted_at,
            source_observation_id=projection.source_observation.observation_id,
            source_relationship=projection.projection_reference.current_source_relationship,
            presentation=disclosed_presentation,
            technical_receipts=receipts,
            available_lifecycle_links=links,
            removal_id=None
            if projection.removal is None
            else projection.removal.removal_id,
            withdrawal_id=None
            if projection.author_withdrawal is None
            else projection.author_withdrawal.withdrawal_id,
        )


def refuse_artifact_claim_upgrade(labels: object) -> None:
    """Receipt references and artifacts cannot acquire caller claims."""

    if not isinstance(labels, dict) or any(not isinstance(key, str) for key in labels):
        raise ValidationError(
            "artifact_claim_labels_invalid", "labels must be an object"
        )
    if labels:
        raise ValidationError(
            "artifact_claim_upgrade_refused",
            "reader artifact cannot add authorization, authority, or truth claims",
        )
