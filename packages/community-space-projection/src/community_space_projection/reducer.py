"""Pure SCV0-M2 projection lifecycle reduction.

The reducer consumes immutable SCV0-M1 values and explicit source-observation
receipts. It has no transport, persistence, credential, policy, writer, or
serving capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from community_model import ValidationError, canonical_json_bytes, sha256_digest
from community_model.canonical import validate_sha256
from community_model.identifiers import normalize_rfc3339, parse_rfc3339
from community_space_model import (
    AuthorWithdrawal,
    CommunityAdmission,
    CommunityIdentity,
    ExactSpaceRecordReference,
    ModeratorAuthorization,
    PostReference,
    ProjectionReference,
    RemovalRecord,
    RenderState,
    SourceRelationship,
    Submission,
)

REDUCER_VERSION: Final = "scv0-projection-reducer/1"


def _receipt(value: object, *, field: str) -> str:
    try:
        return validate_sha256(value)
    except ValidationError as exc:
        raise ValidationError(
            "receipt_reference_invalid", f"{field} must be a sha256 receipt ID"
        ) from exc


def _timestamp(value: object, *, field: str) -> str:
    try:
        return normalize_rfc3339(value)
    except ValidationError as exc:
        raise ValidationError(
            "datetime_invalid", f"{field} must be an RFC 3339 instant"
        ) from exc


def _identity(kind: str, fields: object) -> str:
    return sha256_digest(
        canonical_json_bytes(
            {"kind": kind, "reducerVersion": REDUCER_VERSION, "fields": fields}
        )
    )


class SourceObservationOutcome(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class SourceObservation:
    """One bounded source observation with explicit currentness provenance.

    ``predecessor_observation_id`` is an externally qualified relationship,
    not something inferred from ``observed_at`` or a revision label.
    """

    post: PostReference
    outcome: SourceObservationOutcome | str
    observed_record: ExactSpaceRecordReference | None
    evidence_receipt_id: str
    currentness_receipt_id: str
    observed_at: str
    predecessor_observation_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.post, PostReference):
            raise ValidationError(
                "source_reference_invalid", "qualified post reference is required"
            )
        try:
            outcome = SourceObservationOutcome(self.outcome)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "source_observation_invalid", "unsupported source outcome"
            ) from exc
        object.__setattr__(self, "outcome", outcome)
        _receipt(self.evidence_receipt_id, field="evidence_receipt_id")
        _receipt(self.currentness_receipt_id, field="currentness_receipt_id")
        if self.predecessor_observation_id is not None:
            _receipt(
                self.predecessor_observation_id,
                field="predecessor_observation_id",
            )
        object.__setattr__(
            self, "observed_at", _timestamp(self.observed_at, field="observed_at")
        )

        if outcome is SourceObservationOutcome.PRESENT:
            if not isinstance(self.observed_record, ExactSpaceRecordReference):
                raise ValidationError(
                    "source_observation_invalid",
                    "present observation requires an exact observed record",
                )
            if self.observed_record.uri != self.post.record.uri:
                raise ValidationError(
                    "source_binding_mismatch",
                    "observed record path does not match the admitted source path",
                )
        elif self.observed_record is not None:
            raise ValidationError(
                "source_observation_invalid",
                "absent/unavailable observation cannot contain a source record",
            )

    @property
    def observation_id(self) -> str:
        return _identity(
            "source-observation",
            [
                self.post.reference_id,
                self.outcome,
                (
                    None
                    if self.observed_record is None
                    else self.observed_record.exact_id
                ),
                self.evidence_receipt_id,
                self.currentness_receipt_id,
                self.observed_at,
                self.predecessor_observation_id,
            ],
        )


class LifecycleState(StrEnum):
    SUGGESTED = "suggested"
    ADDED = "added"
    CHANGED_AT_SOURCE = "changed_at_source"
    SOURCE_UNAVAILABLE = "source_unavailable"
    AUTHOR_WITHDRAWN = "author_withdrawn"
    REMOVED = "removed"


class TransitionKind(StrEnum):
    SUBMISSION_QUALIFIED = "submission_qualified"
    ADMISSION_QUALIFIED = "admission_qualified"
    SOURCE_OBSERVED = "source_observed"
    AUTHOR_WITHDREW = "author_withdrew"
    COMMUNITY_REMOVED = "community_removed"


def _projection_identity(community: CommunityIdentity, submission: Submission) -> str:
    return _identity(
        "projection-lifecycle",
        [community.identity_id, submission.submission_id],
    )


@dataclass(frozen=True, slots=True)
class ProjectionLifecycle:
    """One deterministic reader-facing state with its exact retained inputs."""

    projection_identity: str
    state: LifecycleState | str
    community: CommunityIdentity
    submission: Submission
    source_observation: SourceObservation
    transition: TransitionKind | str
    transition_input_ids: tuple[str, ...]
    prior_state_id: str | None = None
    admission: CommunityAdmission | None = None
    projection_reference: ProjectionReference | None = None
    author_withdrawal: AuthorWithdrawal | None = None
    removal: RemovalRecord | None = None
    terminal_source_divergence: bool = False
    reducer_version: str = REDUCER_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.community, CommunityIdentity):
            raise ValidationError(
                "community_binding_invalid", "community identity is required"
            )
        if not isinstance(self.submission, Submission):
            raise ValidationError(
                "submission_required", "projection requires a qualified submission"
            )
        if not isinstance(self.source_observation, SourceObservation):
            raise ValidationError(
                "source_observation_required",
                "projection requires an explicit source observation",
            )
        try:
            state = LifecycleState(self.state)
            transition = TransitionKind(self.transition)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "projection_state_invalid", "unsupported lifecycle state/transition"
            ) from exc
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "transition", transition)

        if self.reducer_version != REDUCER_VERSION:
            raise ValidationError(
                "reducer_version_unsupported", "unsupported projection reducer version"
            )
        expected_identity = _projection_identity(self.community, self.submission)
        _receipt(self.projection_identity, field="projection_identity")
        if self.projection_identity != expected_identity:
            raise ValidationError(
                "projection_identity_mismatch",
                "projection identity does not match community/submission",
            )
        if self.submission.community != self.community:
            raise ValidationError(
                "projection_community_mismatch",
                "submission belongs to another community",
            )
        if self.source_observation.post != self.submission.post:
            raise ValidationError(
                "source_binding_mismatch",
                "source observation does not match the submitted post",
            )
        if (
            not isinstance(self.transition_input_ids, tuple)
            or not self.transition_input_ids
        ):
            raise ValidationError(
                "transition_inputs_invalid",
                "transition input IDs must be a nonempty ordered tuple",
            )
        for input_id in self.transition_input_ids:
            _receipt(input_id, field="transition_input_ids")
        if len(self.transition_input_ids) != len(set(self.transition_input_ids)):
            raise ValidationError(
                "transition_inputs_invalid", "transition input IDs must be unique"
            )
        if self.prior_state_id is not None:
            _receipt(self.prior_state_id, field="prior_state_id")
        if not isinstance(self.terminal_source_divergence, bool):
            raise ValidationError(
                "projection_state_invalid", "terminal source flag must be boolean"
            )

        self._validate_shape()
        if self.transition_input_ids != self._expected_transition_inputs():
            raise ValidationError(
                "transition_inputs_invalid",
                "transition inputs do not match the exact lifecycle transition",
            )

    def _validate_shape(self) -> None:
        allowed_transitions = {
            LifecycleState.SUGGESTED: {TransitionKind.SUBMISSION_QUALIFIED},
            LifecycleState.ADDED: {
                TransitionKind.ADMISSION_QUALIFIED,
                TransitionKind.SOURCE_OBSERVED,
            },
            LifecycleState.CHANGED_AT_SOURCE: {TransitionKind.SOURCE_OBSERVED},
            LifecycleState.SOURCE_UNAVAILABLE: {TransitionKind.SOURCE_OBSERVED},
            LifecycleState.AUTHOR_WITHDRAWN: {
                TransitionKind.AUTHOR_WITHDREW,
                TransitionKind.SOURCE_OBSERVED,
            },
            LifecycleState.REMOVED: {
                TransitionKind.COMMUNITY_REMOVED,
                TransitionKind.SOURCE_OBSERVED,
            },
        }
        if self.transition not in allowed_transitions[self.state]:
            raise ValidationError(
                "invalid_lifecycle_transition",
                "transition kind cannot produce the declared lifecycle state",
            )
        if self.state is LifecycleState.SUGGESTED:
            if self.prior_state_id is not None:
                raise ValidationError(
                    "invalid_lifecycle_transition",
                    "suggested is the initial projection state",
                )
            if any(
                value is not None
                for value in (
                    self.admission,
                    self.projection_reference,
                    self.author_withdrawal,
                    self.removal,
                )
            ):
                raise ValidationError(
                    "admission_without_decision",
                    "suggested state cannot contain admission/removal records",
                )
            if (
                self.source_observation.outcome is not SourceObservationOutcome.PRESENT
                or self.source_observation.observed_record
                != self.submission.post.record
            ):
                raise ValidationError(
                    "source_observation_required",
                    "suggested requires the exact qualified submitted source",
                )
            if self.terminal_source_divergence:
                raise ValidationError(
                    "projection_state_invalid",
                    "initial suggestion cannot be source-terminal",
                )
            return

        if self.prior_state_id is None:
            raise ValidationError(
                "prior_state_required",
                "noninitial projection state requires its exact prior state",
            )
        if self.prior_state_id not in self.transition_input_ids:
            raise ValidationError(
                "transition_inputs_invalid",
                "transition inputs must retain the exact prior state",
            )

        if not isinstance(self.admission, CommunityAdmission):
            raise ValidationError(
                "admission_required", "non-suggested state requires an admission"
            )
        if self.admission.community != self.community:
            raise ValidationError(
                "projection_community_mismatch",
                "admission belongs to another community",
            )
        if self.admission.submission != self.submission:
            raise ValidationError(
                "submission_binding_mismatch",
                "admission does not reference this exact submission",
            )
        if self.admission.post != self.submission.post:
            raise ValidationError(
                "source_binding_mismatch",
                "admission does not reference this exact post",
            )
        if not isinstance(self.projection_reference, ProjectionReference):
            raise ValidationError(
                "projection_reference_required",
                "admitted lifecycle requires a projection reference",
            )
        if self.projection_reference.admission != self.admission:
            raise ValidationError(
                "projection_admission_mismatch",
                "projection reference belongs to another admission",
            )

        if self.state is LifecycleState.REMOVED:
            if not isinstance(self.removal, RemovalRecord):
                raise ValidationError(
                    "removal_required", "removed state requires a removal record"
                )
            if self.removal.admission != self.admission:
                raise ValidationError(
                    "removal_admission_mismatch",
                    "removal does not target this exact admission",
                )
            if self.author_withdrawal is not None:
                self._validate_withdrawal()
            return

        if self.removal is not None:
            raise ValidationError(
                "source_mutation_refused",
                "active source states cannot contain a community removal",
            )
        if self.state is LifecycleState.AUTHOR_WITHDRAWN:
            self._validate_withdrawal()
        elif self.author_withdrawal is not None:
            raise ValidationError(
                "withdrawal_state_invalid",
                "only author-withdrawn/removed states may retain withdrawal",
            )
        if (
            self.projection_reference.source_qualification_receipt_id
            != self.source_observation.evidence_receipt_id
            or self.projection_reference.last_qualification_check
            != self.source_observation.observed_at
        ):
            raise ValidationError(
                "source_observation_mismatch",
                "projection reference must bind the exact source observation",
            )

        if self.state is LifecycleState.ADDED:
            observed = self.source_observation.observed_record
            if (
                self.source_observation.outcome is not SourceObservationOutcome.PRESENT
                or observed is None
                or observed.cid != self.admission.post.record.cid
                or self.terminal_source_divergence
                or self.projection_reference.render_state is not RenderState.INCLUDED
            ):
                raise ValidationError(
                    "added_without_exact_source",
                    "added requires a nonterminal exact source observation",
                )
        elif self.state is LifecycleState.CHANGED_AT_SOURCE:
            if (
                self.source_observation.outcome is not SourceObservationOutcome.PRESENT
                or not self.terminal_source_divergence
                or self.projection_reference.render_state
                is not RenderState.HIDDEN_CHANGED
            ):
                raise ValidationError(
                    "changed_source_invalid",
                    "changed state requires present terminal source divergence",
                )
        elif self.state is LifecycleState.SOURCE_UNAVAILABLE:
            if self.source_observation.outcome not in {
                SourceObservationOutcome.ABSENT,
                SourceObservationOutcome.UNAVAILABLE,
            }:
                raise ValidationError(
                    "source_unavailable_invalid",
                    "unavailable state requires absent/unavailable observation",
                )
            if self.source_observation.outcome is SourceObservationOutcome.ABSENT:
                if (
                    self.projection_reference.render_state
                    is not RenderState.HIDDEN_DELETED
                    or self.projection_reference.current_source_relationship
                    is not SourceRelationship.DELETED
                    or not self.terminal_source_divergence
                ):
                    raise ValidationError(
                        "source_unavailable_invalid",
                        "qualified absence requires deleted/terminal projection state",
                    )
            elif (
                self.projection_reference.render_state
                is not RenderState.HIDDEN_UNAVAILABLE
                or self.projection_reference.current_source_relationship
                is not SourceRelationship.UNAVAILABLE
            ):
                raise ValidationError(
                    "source_unavailable_invalid",
                    "unavailable observation requires unavailable projection state",
                )

    def _validate_withdrawal(self) -> None:
        if not isinstance(self.author_withdrawal, AuthorWithdrawal):
            raise ValidationError(
                "author_withdrawal_required",
                "author-withdrawn state requires an exact withdrawal",
            )
        assert self.admission is not None
        if self.author_withdrawal.admission != self.admission:
            raise ValidationError(
                "withdrawal_occurrence_mismatch",
                "withdrawal does not target this exact admission",
            )
        if self.author_withdrawal.submission != self.submission:
            raise ValidationError(
                "withdrawal_occurrence_mismatch",
                "withdrawal does not target this exact submission",
            )
        if self.state is not LifecycleState.AUTHOR_WITHDRAWN:
            return
        assert self.projection_reference is not None
        observation = self.source_observation
        if observation.outcome is SourceObservationOutcome.PRESENT:
            assert observation.observed_record is not None
            changed = (
                self.terminal_source_divergence
                or observation.observed_record.cid != self.admission.post.record.cid
            )
            expected = (
                (RenderState.HIDDEN_CHANGED, SourceRelationship.CHANGED)
                if changed
                else (RenderState.INCLUDED, SourceRelationship.EXACT)
            )
        elif observation.outcome is SourceObservationOutcome.ABSENT:
            expected = (RenderState.HIDDEN_DELETED, SourceRelationship.DELETED)
        else:
            expected = (RenderState.HIDDEN_UNAVAILABLE, SourceRelationship.UNAVAILABLE)
        if (
            self.projection_reference.render_state,
            self.projection_reference.current_source_relationship,
        ) != expected:
            raise ValidationError(
                "withdrawal_source_state_invalid",
                "withdrawal retained source state does not match its observation",
            )

    def _expected_transition_inputs(self) -> tuple[str, ...]:
        if self.transition is TransitionKind.SUBMISSION_QUALIFIED:
            return (
                self.submission.post.reference_id,
                self.submission.submission_id,
                self.source_observation.observation_id,
            )
        assert self.prior_state_id is not None
        if self.transition is TransitionKind.ADMISSION_QUALIFIED:
            assert self.admission is not None
            assert self.projection_reference is not None
            return (
                self.prior_state_id,
                self.admission.authorization.authorization_id,
                self.admission.admission_id,
                self.source_observation.observation_id,
                self.projection_reference.projection_id,
            )
        if self.transition is TransitionKind.COMMUNITY_REMOVED:
            assert self.removal is not None
            return (self.prior_state_id, self.removal.removal_id)
        if self.transition is TransitionKind.AUTHOR_WITHDREW:
            assert self.author_withdrawal is not None
            return (self.prior_state_id, self.author_withdrawal.withdrawal_id)
        if self.state is LifecycleState.REMOVED:
            return (self.prior_state_id, self.source_observation.observation_id)
        assert self.projection_reference is not None
        return (
            self.prior_state_id,
            self.source_observation.observation_id,
            self.projection_reference.projection_id,
        )

    @property
    def state_id(self) -> str:
        return _identity(
            "projection-state",
            [
                self.projection_identity,
                self.state,
                self.submission.submission_id,
                None if self.admission is None else self.admission.admission_id,
                self.source_observation.observation_id,
                (
                    None
                    if self.projection_reference is None
                    else self.projection_reference.projection_id
                ),
                (
                    None
                    if self.author_withdrawal is None
                    else self.author_withdrawal.withdrawal_id
                ),
                None if self.removal is None else self.removal.removal_id,
                self.prior_state_id,
                self.transition,
                self.transition_input_ids,
                self.terminal_source_divergence,
            ],
        )


@dataclass(frozen=True, slots=True)
class ProjectionReducer:
    """Stateless deterministic transition functions for one community."""

    community: CommunityIdentity
    version: str = REDUCER_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.community, CommunityIdentity):
            raise ValidationError(
                "community_binding_invalid", "community identity is required"
            )
        if self.version != REDUCER_VERSION:
            raise ValidationError(
                "reducer_version_unsupported", "unsupported projection reducer version"
            )

    def suggest(
        self, submission: Submission, observation: SourceObservation
    ) -> ProjectionLifecycle:
        if not isinstance(submission, Submission):
            raise ValidationError(
                "submission_required", "suggestion requires a qualified submission"
            )
        if submission.community != self.community:
            raise ValidationError(
                "projection_community_mismatch",
                "submission belongs to another community",
            )
        if not isinstance(observation, SourceObservation):
            raise ValidationError(
                "source_observation_required", "source observation is required"
            )
        if observation.predecessor_observation_id is not None:
            raise ValidationError(
                "source_observation_stale",
                "initial suggestion requires an unchained source observation",
            )
        return ProjectionLifecycle(
            projection_identity=_projection_identity(self.community, submission),
            state=LifecycleState.SUGGESTED,
            community=self.community,
            submission=submission,
            source_observation=observation,
            transition=TransitionKind.SUBMISSION_QUALIFIED,
            transition_input_ids=(
                submission.post.reference_id,
                submission.submission_id,
                observation.observation_id,
            ),
        )

    def admit(
        self,
        prior: ProjectionLifecycle,
        authorization: ModeratorAuthorization,
        admission: CommunityAdmission,
        observation: SourceObservation,
    ) -> ProjectionLifecycle:
        self._require_prior(prior)
        if not isinstance(admission, CommunityAdmission):
            raise ValidationError(
                "admission_required", "added state requires an admission"
            )
        if prior.state is not LifecycleState.SUGGESTED:
            if prior.admission is not None:
                if prior.admission.admission_id == admission.admission_id:
                    raise ValidationError(
                        "duplicate_admission", "exact admission already reduced"
                    )
                if prior.admission.submission == admission.submission:
                    raise ValidationError(
                        "conflicting_admission",
                        "another admission already occupies this lifecycle",
                    )
            raise ValidationError(
                "invalid_lifecycle_transition",
                "admission can follow only suggested state",
            )
        if not isinstance(authorization, ModeratorAuthorization):
            raise ValidationError(
                "authorization_required", "admission authorization is required"
            )
        if admission.authorization != authorization:
            raise ValidationError(
                "authorization_occurrence_mismatch",
                "supplied authorization is not the admission authorization",
            )
        if admission.community != self.community:
            raise ValidationError(
                "projection_community_mismatch",
                "admission belongs to another community",
            )
        if admission.submission != prior.submission:
            raise ValidationError(
                "submission_binding_mismatch",
                "admission does not target the suggested submission",
            )
        self._require_successor_observation(prior, observation)
        observed = observation.observed_record
        if (
            observation.outcome is not SourceObservationOutcome.PRESENT
            or observed is None
            or observed.cid != admission.post.record.cid
        ):
            raise ValidationError(
                "source_change_before_admission",
                "admission requires a current exact-source observation",
            )
        projection = ProjectionReference(
            admission=admission,
            render_state=RenderState.INCLUDED,
            current_source_relationship=SourceRelationship.EXACT,
            source_qualification_receipt_id=observation.evidence_receipt_id,
            last_qualification_check=observation.observed_at,
        )
        return ProjectionLifecycle(
            projection_identity=prior.projection_identity,
            state=LifecycleState.ADDED,
            community=self.community,
            submission=prior.submission,
            admission=admission,
            projection_reference=projection,
            source_observation=observation,
            prior_state_id=prior.state_id,
            transition=TransitionKind.ADMISSION_QUALIFIED,
            transition_input_ids=(
                prior.state_id,
                authorization.authorization_id,
                admission.admission_id,
                observation.observation_id,
                projection.projection_id,
            ),
        )

    def observe(
        self, prior: ProjectionLifecycle, observation: SourceObservation
    ) -> ProjectionLifecycle:
        self._require_prior(prior)
        if prior.state is LifecycleState.SUGGESTED:
            raise ValidationError(
                "source_change_before_admission",
                "source lifecycle changes require a prior admission",
            )
        self._require_successor_observation(prior, observation)
        assert prior.admission is not None
        assert prior.projection_reference is not None

        if prior.state is LifecycleState.REMOVED:
            return ProjectionLifecycle(
                projection_identity=prior.projection_identity,
                state=LifecycleState.REMOVED,
                community=self.community,
                submission=prior.submission,
                admission=prior.admission,
                projection_reference=prior.projection_reference,
                author_withdrawal=prior.author_withdrawal,
                removal=prior.removal,
                source_observation=observation,
                prior_state_id=prior.state_id,
                transition=TransitionKind.SOURCE_OBSERVED,
                transition_input_ids=(prior.state_id, observation.observation_id),
                terminal_source_divergence=prior.terminal_source_divergence,
            )

        if prior.state is LifecycleState.AUTHOR_WITHDRAWN:
            state, render_state, relationship, terminal = self._source_projection(
                prior, observation
            )
            projection = ProjectionReference(
                admission=prior.admission,
                render_state=render_state,
                current_source_relationship=relationship,
                source_qualification_receipt_id=observation.evidence_receipt_id,
                last_qualification_check=observation.observed_at,
            )
            return ProjectionLifecycle(
                projection_identity=prior.projection_identity,
                state=LifecycleState.AUTHOR_WITHDRAWN,
                community=self.community,
                submission=prior.submission,
                admission=prior.admission,
                projection_reference=projection,
                author_withdrawal=prior.author_withdrawal,
                source_observation=observation,
                prior_state_id=prior.state_id,
                transition=TransitionKind.SOURCE_OBSERVED,
                transition_input_ids=(
                    prior.state_id,
                    observation.observation_id,
                    projection.projection_id,
                ),
                terminal_source_divergence=terminal,
            )

        state, render_state, relationship, terminal = self._source_projection(
            prior, observation
        )
        projection = ProjectionReference(
            admission=prior.admission,
            render_state=render_state,
            current_source_relationship=relationship,
            source_qualification_receipt_id=observation.evidence_receipt_id,
            last_qualification_check=observation.observed_at,
        )
        return ProjectionLifecycle(
            projection_identity=prior.projection_identity,
            state=state,
            community=self.community,
            submission=prior.submission,
            admission=prior.admission,
            projection_reference=projection,
            source_observation=observation,
            prior_state_id=prior.state_id,
            transition=TransitionKind.SOURCE_OBSERVED,
            transition_input_ids=(
                prior.state_id,
                observation.observation_id,
                projection.projection_id,
            ),
            terminal_source_divergence=terminal,
        )

    def withdraw(
        self, prior: ProjectionLifecycle, withdrawal: AuthorWithdrawal
    ) -> ProjectionLifecycle:
        self._require_prior(prior)
        if prior.state is LifecycleState.SUGGESTED:
            raise ValidationError(
                "invalid_lifecycle_transition",
                "withdrawal cannot target a submission before admission",
            )
        if not isinstance(withdrawal, AuthorWithdrawal):
            raise ValidationError(
                "author_withdrawal_required", "author withdrawal is required"
            )
        if prior.state is LifecycleState.REMOVED:
            raise ValidationError(
                "invalid_lifecycle_transition",
                "withdrawal cannot replace a community removal",
            )
        if prior.state is LifecycleState.AUTHOR_WITHDRAWN:
            if prior.author_withdrawal == withdrawal:
                raise ValidationError(
                    "duplicate_withdrawal", "exact withdrawal already reduced"
                )
            raise ValidationError(
                "conflicting_withdrawal",
                "another withdrawal already occupies this lifecycle",
            )
        assert prior.admission is not None
        assert prior.projection_reference is not None
        if withdrawal.admission != prior.admission:
            raise ValidationError(
                "withdrawal_occurrence_mismatch",
                "withdrawal does not target the lifecycle's exact admission",
            )
        return ProjectionLifecycle(
            projection_identity=prior.projection_identity,
            state=LifecycleState.AUTHOR_WITHDRAWN,
            community=self.community,
            submission=prior.submission,
            admission=prior.admission,
            projection_reference=prior.projection_reference,
            author_withdrawal=withdrawal,
            source_observation=prior.source_observation,
            prior_state_id=prior.state_id,
            transition=TransitionKind.AUTHOR_WITHDREW,
            transition_input_ids=(prior.state_id, withdrawal.withdrawal_id),
            terminal_source_divergence=prior.terminal_source_divergence,
        )

    def remove(
        self, prior: ProjectionLifecycle, removal: RemovalRecord
    ) -> ProjectionLifecycle:
        self._require_prior(prior)
        if prior.state is LifecycleState.SUGGESTED:
            raise ValidationError(
                "invalid_lifecycle_transition",
                "removal cannot occur before admission",
            )
        if not isinstance(removal, RemovalRecord):
            raise ValidationError("removal_required", "removal record is required")
        if prior.state is LifecycleState.REMOVED:
            if prior.removal == removal:
                raise ValidationError(
                    "duplicate_removal", "exact removal already reduced"
                )
            raise ValidationError(
                "conflicting_removal", "another removal already occupies lifecycle"
            )
        assert prior.admission is not None
        assert prior.projection_reference is not None
        if removal.admission != prior.admission:
            raise ValidationError(
                "removal_admission_mismatch",
                "removal does not target the lifecycle's exact admission",
            )
        return ProjectionLifecycle(
            projection_identity=prior.projection_identity,
            state=LifecycleState.REMOVED,
            community=self.community,
            submission=prior.submission,
            admission=prior.admission,
            projection_reference=prior.projection_reference,
            author_withdrawal=prior.author_withdrawal,
            removal=removal,
            source_observation=prior.source_observation,
            prior_state_id=prior.state_id,
            transition=TransitionKind.COMMUNITY_REMOVED,
            transition_input_ids=(prior.state_id, removal.removal_id),
            terminal_source_divergence=prior.terminal_source_divergence,
        )

    def _require_prior(self, prior: ProjectionLifecycle) -> None:
        if not isinstance(prior, ProjectionLifecycle):
            raise ValidationError(
                "projection_state_required", "prior projection state is required"
            )
        if prior.community != self.community:
            raise ValidationError(
                "projection_community_mismatch",
                "prior projection belongs to another community",
            )

    @staticmethod
    def _require_successor_observation(
        prior: ProjectionLifecycle, observation: SourceObservation
    ) -> None:
        if not isinstance(observation, SourceObservation):
            raise ValidationError(
                "source_observation_required", "source observation is required"
            )
        if observation.post != prior.submission.post:
            raise ValidationError(
                "source_binding_mismatch",
                "source observation belongs to another post",
            )
        if (
            observation.predecessor_observation_id
            != prior.source_observation.observation_id
        ):
            raise ValidationError(
                "source_observation_stale",
                "source observation does not advance the current observation",
            )
        if parse_rfc3339(observation.observed_at) < parse_rfc3339(
            prior.source_observation.observed_at
        ):
            raise ValidationError(
                "source_observation_order_invalid",
                "successor observation timestamp predates its predecessor",
            )

    @staticmethod
    def _source_projection(
        prior: ProjectionLifecycle, observation: SourceObservation
    ) -> tuple[LifecycleState, RenderState, SourceRelationship, bool]:
        if observation.outcome is SourceObservationOutcome.PRESENT:
            assert observation.observed_record is not None
            changed = (
                prior.terminal_source_divergence
                or observation.observed_record.cid != prior.submission.post.record.cid
            )
            if changed:
                return (
                    LifecycleState.CHANGED_AT_SOURCE,
                    RenderState.HIDDEN_CHANGED,
                    SourceRelationship.CHANGED,
                    True,
                )
            return (
                LifecycleState.ADDED,
                RenderState.INCLUDED,
                SourceRelationship.EXACT,
                False,
            )
        if observation.outcome is SourceObservationOutcome.ABSENT:
            return (
                LifecycleState.SOURCE_UNAVAILABLE,
                RenderState.HIDDEN_DELETED,
                SourceRelationship.DELETED,
                True,
            )
        return (
            LifecycleState.SOURCE_UNAVAILABLE,
            RenderState.HIDDEN_UNAVAILABLE,
            SourceRelationship.UNAVAILABLE,
            prior.terminal_source_divergence,
        )


def refuse_projection_claim_upgrade(labels: object) -> None:
    """Projection results have no caller-extensible claim or ranking fields."""

    if not isinstance(labels, dict) or any(not isinstance(key, str) for key in labels):
        raise ValidationError("claim_labels_invalid", "claim labels must be a mapping")
    if labels:
        raise ValidationError(
            "projection_claim_upgrade_refused",
            "caller labels cannot add ranking, authority, or source-mutation claims",
        )
