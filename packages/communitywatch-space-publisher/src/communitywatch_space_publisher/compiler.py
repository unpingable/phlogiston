"""Compose qualified Spaces records into the frozen SCV0 projection model.

This module has no acquisition, credential, signing, writer, or serving path.
It accepts only SA1-qualified repository states plus the bounded public output
of communityd.  It does not reinterpret either as source currentness,
moderator standing, reader authorization, or governance authority.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from community_model import ValidationError, canonical_json_bytes, sha256_digest
from community_model.canonical import validate_sha256
from community_model.identifiers import parse_rfc3339, validate_cid, validate_did
from community_space_artifact import (
    BoundedSourcePresentation,
    DisclosurePolicy,
    ProjectionArtifactCompiler,
    ProjectionDisclosureInput,
)
from community_space_feed import (
    FeedPublicationRequest,
    LocalProjectionFeedBoundary,
    PublicProjectionChannel,
    PublishedProjectionFeed,
)
from community_space_model import (
    AuthorizedAction,
    CommunityAdmission,
    CommunityIdentity,
    ExactSpaceRecordReference,
    ModeratorAuthorization,
    RemovalRecord,
    SpaceIdentity,
)
from community_space_projection import (
    LifecycleState,
    ProjectionLifecycle,
    ProjectionReducer,
    SourceObservation,
    SourceObservationOutcome,
)
from community_space_wire import (
    ADMISSION_COLLECTION,
    REMOVAL_COLLECTION,
    SUBMISSION_COLLECTION,
    WITHDRAWAL_COLLECTION,
    AdaptedLiveSubmission,
    adapt_live_admission,
    adapt_live_post,
    adapt_live_removal,
    adapt_live_submission,
    adapt_live_withdrawal,
)
from communitywatch_spaces_alpha import (
    QualifiedRepoState,
    ReconciliationDisposition,
    RepoRecord,
    SpaceObservationReceipt,
    reconcile_qualified_states,
)

COMPILER_VERSION: Final = "scv0-live-projection-composer/1"
_AUTHORITY_OUTPUT_FIELDS: Final = frozenset({"record", "authorization"})
_AUTHORIZATION_FIELDS: Final = frozenset(
    {
        "authorizationId",
        "communityIdentityId",
        "decisionId",
        "moderatorDid",
        "action",
        "targetOccurrenceId",
        "authorizationBasisReceiptId",
        "authorizedAt",
        "expiresAt",
        "provenanceReceiptId",
    }
)


def _fail(reason: str, message: str) -> None:
    raise ValidationError(reason, message)


def _aware(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        _fail("live_projection_time_invalid", f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail("live_projection_input_invalid", f"{field} must be bounded text")
    return value


def _object(value: object, *, field: str, keys: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict) or frozenset(value) != keys:
        _fail("live_projection_input_invalid", f"{field} fields differ")
    return value


def _model_space(value: object) -> SpaceIdentity:
    if not hasattr(value, "authority_did"):
        _fail("live_projection_space_mismatch", "qualified Space is invalid")
    return SpaceIdentity(value.authority_did, value.space_type, value.skey)


def _exact(record: RepoRecord) -> ExactSpaceRecordReference:
    return ExactSpaceRecordReference(
        _model_space(record.identity.space),
        record.identity.author_did,
        record.identity.collection,
        record.identity.rkey,
        record.cid,
    )


@dataclass(frozen=True, slots=True)
class QualifiedSnapshot:
    """One SA1-qualified state with separately supplied custody/currentness IDs."""

    state: QualifiedRepoState
    custody_receipt_id: str
    currentness_receipt_id: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.state, QualifiedRepoState):
            _fail("live_projection_qualification_required", "SA1 state is required")
        validate_sha256(self.custody_receipt_id)
        validate_sha256(self.currentness_receipt_id)
        checked = _aware(self.observed_at, field="observed_at")
        object.__setattr__(self, "observed_at", checked)
        if len(self.state.records) != len(self.state.receipts):
            _fail("live_projection_receipt_mismatch", "record receipts are incomplete")
        for record in self.state.records:
            self.receipt_for(record)

    def receipt_for(self, record: RepoRecord) -> SpaceObservationReceipt:
        matches = tuple(
            receipt
            for receipt in self.state.receipts
            if receipt.record_identity == record.identity
            and receipt.record_cid == record.cid
        )
        if len(matches) != 1:
            _fail(
                "live_projection_receipt_mismatch",
                "qualified record must have exactly one SA1 receipt in its state",
            )
        return matches[0]


@dataclass(frozen=True, slots=True)
class QualifiedRepoHistory:
    """Ordered qualified snapshots; no claim that unseen history is complete."""

    snapshots: tuple[QualifiedSnapshot, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.snapshots, tuple) or not self.snapshots:
            _fail("live_projection_history_invalid", "repo history cannot be empty")
        if any(not isinstance(item, QualifiedSnapshot) for item in self.snapshots):
            _fail("live_projection_history_invalid", "history items must be qualified")
        first = self.snapshots[0]
        for previous, current in zip(self.snapshots, self.snapshots[1:], strict=False):
            if current.observed_at < previous.observed_at:
                _fail(
                    "live_projection_history_invalid", "snapshot custody is reordered"
                )
            result = reconcile_qualified_states(
                previous.state, current.state, reconciled_at=current.observed_at
            )
            if result.disposition is ReconciliationDisposition.INSUFFICIENT_EVIDENCE:
                _fail(
                    "live_projection_history_insufficient",
                    "stale, conflicting, or cross-repo snapshot cannot replace the head",
                )
        if any(
            item.state.space != first.state.space
            or item.state.author_did != first.state.author_did
            for item in self.snapshots
        ):
            _fail("live_projection_history_invalid", "history changes Space or author")

    @property
    def latest(self) -> QualifiedSnapshot:
        return self.snapshots[-1]

    def occurrences(
        self, uri: str, cid: str | None = None
    ) -> tuple[tuple[RepoRecord, SpaceObservationReceipt, QualifiedSnapshot], ...]:
        result: list[tuple[RepoRecord, SpaceObservationReceipt, QualifiedSnapshot]] = []
        seen: set[str] = set()
        for snapshot in self.snapshots:
            for record in snapshot.state.records:
                if record.identity.uri != uri or (
                    cid is not None and record.cid != cid
                ):
                    continue
                receipt = snapshot.receipt_for(record)
                if receipt.receipt_id in seen:
                    continue
                seen.add(receipt.receipt_id)
                result.append((record, receipt, snapshot))
        return tuple(result)


@dataclass(frozen=True, slots=True)
class SourceUnavailableEvidence:
    author_did: str
    acquisition_receipt_id: str
    currentness_receipt_id: str
    observed_at: datetime

    def __post_init__(self) -> None:
        validate_did(self.author_did)
        validate_sha256(self.acquisition_receipt_id)
        validate_sha256(self.currentness_receipt_id)
        object.__setattr__(
            self, "observed_at", _aware(self.observed_at, field="observed_at")
        )


@dataclass(frozen=True, slots=True)
class AuthorityWriteReceipt:
    record: ExactSpaceRecordReference
    authorization: ModeratorAuthorization
    output_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.record, ExactSpaceRecordReference) or not isinstance(
            self.authorization, ModeratorAuthorization
        ):
            _fail(
                "live_authority_receipt_invalid", "typed authority receipt is required"
            )
        validate_sha256(self.output_sha256)
        expected_collection = (
            ADMISSION_COLLECTION
            if self.authorization.action is AuthorizedAction.ADMIT
            else REMOVAL_COLLECTION
        )
        if (
            self.record.space != self.authorization.community.space
            or self.record.author_did
            != self.authorization.community.community_actor_did
            or self.record.collection != expected_collection
            or self.record.rkey
            != self.authorization.authorization_id.removeprefix("sha256:")
        ):
            _fail("live_authority_receipt_invalid", "authority record binding differs")

    @classmethod
    def parse(
        cls, payload: bytes, *, community: CommunityIdentity
    ) -> AuthorityWriteReceipt:
        if not isinstance(payload, bytes) or not payload:
            _fail(
                "live_authority_receipt_invalid", "authority output bytes are required"
            )
        try:
            raw = json.loads(payload)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValidationError(
                "live_authority_receipt_invalid", "authority output is not JSON"
            ) from exc
        root = _object(raw, field="authority output", keys=_AUTHORITY_OUTPUT_FIELDS)
        record_raw = _object(
            root["record"], field="authority record", keys=frozenset({"uri", "cid"})
        )
        auth_raw = _object(
            root["authorization"], field="authorization", keys=_AUTHORIZATION_FIELDS
        )
        if auth_raw["communityIdentityId"] != community.identity_id:
            _fail(
                "live_authority_receipt_invalid", "community identity was substituted"
            )
        authorization = ModeratorAuthorization(
            community=community,
            decision_id=_text(auth_raw["decisionId"], field="decisionId"),
            moderator_did=_text(auth_raw["moderatorDid"], field="moderatorDid"),
            action=_text(auth_raw["action"], field="action"),
            target_occurrence_id=_text(
                auth_raw["targetOccurrenceId"], field="targetOccurrenceId"
            ),
            authorization_basis_receipt_id=_text(
                auth_raw["authorizationBasisReceiptId"],
                field="authorizationBasisReceiptId",
            ),
            authorized_at=_text(auth_raw["authorizedAt"], field="authorizedAt"),
            expires_at=_text(auth_raw["expiresAt"], field="expiresAt"),
            provenance_receipt_id=_text(
                auth_raw["provenanceReceiptId"], field="provenanceReceiptId"
            ),
        )
        if auth_raw["authorizationId"] != authorization.authorization_id:
            _fail("live_authority_receipt_invalid", "authorization identity mismatch")
        collection = (
            ADMISSION_COLLECTION
            if authorization.action is AuthorizedAction.ADMIT
            else REMOVAL_COLLECTION
        )
        record = ExactSpaceRecordReference(
            community.space,
            community.community_actor_did,
            collection,
            authorization.authorization_id.removeprefix("sha256:"),
            validate_cid(record_raw["cid"], require_dag_cbor=True),
        )
        if record_raw["uri"] != record.uri:
            _fail("live_authority_receipt_invalid", "authority record URI mismatch")
        canonical = canonical_json_bytes(raw)
        if canonical != payload:
            _fail(
                "live_authority_receipt_invalid",
                "authority output is not canonical JSON",
            )
        return cls(record, authorization, sha256_digest(canonical))

    @property
    def receipt_id(self) -> str:
        return self.output_sha256


@dataclass(frozen=True, slots=True)
class CompiledLiveProjection:
    lifecycles: tuple[ProjectionLifecycle, ...]
    ordinary_feed: PublishedProjectionFeed | None
    audit_feed: PublishedProjectionFeed | None
    non_published_candidate_ids: tuple[str, ...]
    compiler_version: str = COMPILER_VERSION

    def __post_init__(self) -> None:
        if self.compiler_version != COMPILER_VERSION:
            _fail("live_projection_version_invalid", "unsupported compiler version")
        if (self.ordinary_feed is None) != (self.audit_feed is None):
            _fail("live_projection_disclosure_mismatch", "publication channels differ")


class LiveProjectionCompiler:
    """Reduce exact qualified occurrences; never decide admission or authority."""

    def __init__(self, community: CommunityIdentity) -> None:
        if not isinstance(community, CommunityIdentity):
            _fail("live_projection_community_invalid", "community is required")
        self.community = community
        self.reducer = ProjectionReducer(community)

    def compile(
        self,
        *,
        authors: tuple[QualifiedRepoHistory, ...],
        community_history: QualifiedRepoHistory,
        authority_receipts: tuple[AuthorityWriteReceipt, ...],
        ordinary_policy: DisclosurePolicy,
        audit_policy: DisclosurePolicy,
        published_at: str,
        unavailable: tuple[SourceUnavailableEvidence, ...] = (),
    ) -> CompiledLiveProjection:
        self._validate_inputs(
            authors, community_history, authority_receipts, unavailable
        )
        histories = {item.latest.state.author_did: item for item in authors}
        records = self._record_index((*authors, community_history))
        authority = {
            item.authorization.authorization_id: item for item in authority_receipts
        }
        submissions = self._submissions(authors, records, authority)
        admissions = self._admissions(
            community_history, records, submissions, authority
        )
        removals = self._removals(community_history, records, admissions, authority)
        withdrawals = self._withdrawals(authors, records, admissions)
        unavailable_by_author = {item.author_did: item for item in unavailable}

        lifecycles: list[ProjectionLifecycle] = []
        presentations: dict[str, BoundedSourcePresentation] = {}
        for submission in submissions.values():
            history = histories[submission.submission.post.record.author_did]
            admission = admissions.get(
                (submission.submission.record.uri, submission.submission.record.cid)
            )
            lifecycle = self._suggest(submission, history)
            if admission is None:
                lifecycles.append(lifecycle)
                continue
            lifecycle = self._admit(lifecycle, admission, history)
            lifecycle = self._observe_current(
                lifecycle,
                history,
                unavailable_by_author.get(history.latest.state.author_did),
            )
            events: list[tuple[datetime, str, object]] = []
            withdrawal = withdrawals.get(admission.admission_id)
            removal = removals.get(admission.admission_id)
            if withdrawal is not None:
                events.append(
                    (parse_rfc3339(withdrawal.withdrawn_at), "withdraw", withdrawal)
                )
            if removal is not None:
                events.append((parse_rfc3339(removal.removed_at), "remove", removal))
            for _, action, value in sorted(events, key=lambda item: (item[0], item[1])):
                lifecycle = (
                    self.reducer.withdraw(lifecycle, value)
                    if action == "withdraw"
                    else self.reducer.remove(lifecycle, value)
                )
            lifecycles.append(lifecycle)
            disclosed = submission.presentation
            presentations[lifecycle.projection_identity] = BoundedSourcePresentation(
                source_reference_id=submission.submission.post.reference_id,
                source_uri=submission.submission.post.record.uri,
                source_cid=submission.submission.post.record.cid,
                title=disclosed.title,
                body=disclosed.body,
                author_display_reference=disclosed.author_display_reference,
            )

        inputs = tuple(
            ProjectionDisclosureInput(
                projection=item,
                declared_community_identity_id=self.community.identity_id,
                declared_lifecycle_state=item.state,
                presentation=(
                    presentations[item.projection_identity]
                    if item.state is LifecycleState.ADDED
                    else None
                ),
                include_exact_occurrence_references=True,
            )
            for item in lifecycles
        )
        artifact_compiler = ProjectionArtifactCompiler(self.community)
        ordinary = artifact_compiler.compile(inputs, ordinary_policy)
        audit = artifact_compiler.compile(inputs, audit_policy)
        ordinary_feed = self._publish(ordinary.artifact, ordinary_policy, published_at)
        audit_feed = self._publish(audit.artifact, audit_policy, published_at)
        candidates = tuple(
            item.candidate_id for item in ordinary.non_published_candidates
        )
        return CompiledLiveProjection(
            tuple(lifecycles), ordinary_feed, audit_feed, candidates
        )

    def _validate_inputs(
        self,
        authors: tuple[QualifiedRepoHistory, ...],
        community: QualifiedRepoHistory,
        authority: tuple[AuthorityWriteReceipt, ...],
        unavailable: tuple[SourceUnavailableEvidence, ...],
    ) -> None:
        if not authors or any(
            not isinstance(item, QualifiedRepoHistory) for item in authors
        ):
            _fail(
                "live_projection_input_invalid",
                "qualified author histories are required",
            )
        author_ids = tuple(item.latest.state.author_did for item in authors)
        if (
            len(set(author_ids)) != len(author_ids)
            or self.community.community_actor_did in author_ids
        ):
            _fail(
                "live_projection_custody_mismatch", "author/community custody differs"
            )
        if (
            community.latest.state.author_did != self.community.community_actor_did
            or _model_space(community.latest.state.space) != self.community.space
        ):
            _fail("live_projection_community_mismatch", "community repo differs")
        if any(
            _model_space(item.latest.state.space) != self.community.space
            for item in authors
        ):
            _fail("live_projection_space_mismatch", "author repo uses another Space")
        if len({item.authorization.authorization_id for item in authority}) != len(
            authority
        ):
            _fail("live_authority_receipt_conflict", "duplicate authority receipt")
        if any(item.authorization.community != self.community for item in authority):
            _fail(
                "live_authority_receipt_invalid", "authority receipt community differs"
            )
        if len({item.author_did for item in unavailable}) != len(unavailable):
            _fail(
                "live_projection_unavailable_conflict", "duplicate unavailable evidence"
            )

    @staticmethod
    def _record_index(histories: tuple[QualifiedRepoHistory, ...]):
        index: dict[
            tuple[str, str],
            list[tuple[RepoRecord, SpaceObservationReceipt, QualifiedSnapshot]],
        ] = {}
        for history in histories:
            for snapshot in history.snapshots:
                for record in snapshot.state.records:
                    receipt = snapshot.receipt_for(record)
                    index.setdefault((record.identity.uri, record.cid), []).append(
                        (record, receipt, snapshot)
                    )
        return index

    def _submissions(self, histories, records, authority):
        result: dict[tuple[str, str], AdaptedLiveSubmission] = {}
        target_ids = {
            item.authorization.target_occurrence_id
            for item in authority.values()
            if item.authorization.action is AuthorizedAction.ADMIT
        }
        for history in histories:
            for record in history.latest.state.records:
                if record.identity.collection != SUBMISSION_COLLECTION:
                    continue
                raw_subject = record.record.get("subject")
                if not isinstance(raw_subject, Mapping):
                    _fail(
                        "live_projection_submission_invalid",
                        "submission subject is invalid",
                    )
                key = (
                    _text(raw_subject.get("uri"), field="subject.uri"),
                    _text(raw_subject.get("cid"), field="subject.cid"),
                )
                post_occurrences = records.get(key, ())
                submission_occurrences = records.get(
                    (record.identity.uri, record.cid), ()
                )
                matches: list[AdaptedLiveSubmission] = []
                for post_record, post_receipt, _ in post_occurrences:
                    post = adapt_live_post(
                        post_record.record,
                        record=_exact(post_record),
                        qualification_receipt_id=post_receipt.receipt_id,
                        expected_author_did=record.identity.author_did,
                    )
                    for _, submission_receipt, _ in submission_occurrences:
                        candidate = adapt_live_submission(
                            record.record,
                            record=_exact(record),
                            post=post.post,
                            qualification_receipt_id=submission_receipt.receipt_id,
                            expected_community=self.community,
                        )
                        matches.append(candidate)
                unique = {item.submission.submission_id: item for item in matches}
                targeted = {
                    identifier: item
                    for identifier, item in unique.items()
                    if identifier in target_ids
                }
                if len(targeted) > 1 or (not targeted and not unique):
                    _fail(
                        "live_projection_submission_ambiguous",
                        "submission evidence does not select one exact occurrence",
                    )
                result[(record.identity.uri, record.cid)] = (
                    next(iter(targeted.values()))
                    if targeted
                    else next(reversed(unique.values()))
                )
        return result

    def _admissions(self, history, records, submissions, authority):
        result: dict[tuple[str, str], CommunityAdmission] = {}
        for record in history.latest.state.records:
            if record.identity.collection != ADMISSION_COLLECTION:
                continue
            raw = record.record
            auth_id = _text(
                raw.get("authorizationOccurrence"), field="authorizationOccurrence"
            )
            authority_receipt = authority.get(auth_id)
            if authority_receipt is None or authority_receipt.record != _exact(record):
                _fail(
                    "live_authority_receipt_missing",
                    "admission authority receipt is absent",
                )
            submission_ref = raw.get("submission")
            if not isinstance(submission_ref, Mapping):
                _fail(
                    "live_projection_admission_invalid",
                    "admission submission is invalid",
                )
            key = (
                _text(submission_ref.get("uri"), field="submission.uri"),
                _text(submission_ref.get("cid"), field="submission.cid"),
            )
            submission = submissions.get(key)
            if submission is None:
                _fail(
                    "live_projection_admission_invalid",
                    "admission submission is unavailable",
                )
            admission = adapt_live_admission(
                raw,
                record=_exact(record),
                post=submission.submission.post,
                submission=submission.submission,
                authorization=authority_receipt.authorization,
                community=self.community,
            )
            occurrence = (
                submission.submission.record.uri,
                submission.submission.record.cid,
            )
            if occurrence in result:
                _fail(
                    "live_projection_admission_conflict",
                    "submission has multiple admissions",
                )
            result[occurrence] = admission
        return result

    def _removals(self, history, records, admissions, authority):
        by_record = {
            (item.record.uri, item.record.cid): item for item in admissions.values()
        }
        result: dict[str, RemovalRecord] = {}
        for record in history.latest.state.records:
            if record.identity.collection != REMOVAL_COLLECTION:
                continue
            raw = record.record
            auth_id = _text(
                raw.get("authorizationOccurrence"), field="authorizationOccurrence"
            )
            receipt = authority.get(auth_id)
            if receipt is None or receipt.record != _exact(record):
                _fail(
                    "live_authority_receipt_missing",
                    "removal authority receipt is absent",
                )
            ref = raw.get("admission")
            if not isinstance(ref, Mapping):
                _fail("live_projection_removal_invalid", "removal admission is invalid")
            admission = by_record.get(
                (
                    _text(ref.get("uri"), field="admission.uri"),
                    _text(ref.get("cid"), field="admission.cid"),
                )
            )
            if admission is None:
                _fail(
                    "live_projection_removal_invalid",
                    "removal admission is unavailable",
                )
            removal = adapt_live_removal(
                raw,
                record=_exact(record),
                admission=admission,
                authorization=receipt.authorization,
            )
            if admission.admission_id in result:
                _fail(
                    "live_projection_removal_conflict",
                    "admission has multiple removals",
                )
            result[admission.admission_id] = removal
        return result

    def _withdrawals(self, histories, records, admissions):
        by_record = {
            (item.record.uri, item.record.cid): item for item in admissions.values()
        }
        result = {}
        for history in histories:
            for record in history.latest.state.records:
                if record.identity.collection != WITHDRAWAL_COLLECTION:
                    continue
                raw = record.record
                ref = raw.get("admission")
                if not isinstance(ref, Mapping):
                    _fail(
                        "live_projection_withdrawal_invalid",
                        "withdrawal admission is invalid",
                    )
                admission = by_record.get(
                    (
                        _text(ref.get("uri"), field="admission.uri"),
                        _text(ref.get("cid"), field="admission.cid"),
                    )
                )
                if admission is None:
                    _fail(
                        "live_projection_withdrawal_invalid",
                        "withdrawal admission is unavailable",
                    )
                occurrences = records.get((record.identity.uri, record.cid), ())
                if not occurrences:
                    _fail(
                        "live_projection_withdrawal_invalid",
                        "withdrawal receipt is absent",
                    )
                _, receipt, _ = occurrences[-1]
                withdrawal = adapt_live_withdrawal(
                    raw,
                    record=_exact(record),
                    admission=admission,
                    qualification_receipt_id=receipt.receipt_id,
                )
                if admission.admission_id in result:
                    _fail(
                        "live_projection_withdrawal_conflict",
                        "admission has multiple withdrawals",
                    )
                result[admission.admission_id] = withdrawal
        return result

    def _suggest(
        self, submission: AdaptedLiveSubmission, history: QualifiedRepoHistory
    ) -> ProjectionLifecycle:
        post = submission.submission.post
        occurrences = history.occurrences(post.record.uri, post.record.cid)
        selected = next(
            (
                item
                for item in occurrences
                if item[1].receipt_id == post.source_qualification_receipt_id
            ),
            None,
        )
        if selected is None:
            _fail(
                "live_projection_source_evidence_missing",
                "submitted source receipt is absent",
            )
        _, receipt, snapshot = selected
        observation = SourceObservation(
            post,
            SourceObservationOutcome.PRESENT,
            post.record,
            receipt.receipt_id,
            snapshot.currentness_receipt_id,
            receipt.verified_at.isoformat(),
        )
        return self.reducer.suggest(submission.submission, observation)

    def _admit(
        self,
        prior: ProjectionLifecycle,
        admission: CommunityAdmission,
        history: QualifiedRepoHistory,
    ) -> ProjectionLifecycle:
        occurrences = history.occurrences(
            admission.post.record.uri, admission.post.record.cid
        )
        selected = next(
            (
                item
                for item in occurrences
                if item[1].receipt_id == admission.source_observation_receipt_id
            ),
            None,
        )
        if selected is None:
            _fail(
                "live_projection_source_evidence_missing",
                "admission source receipt is absent",
            )
        _, receipt, snapshot = selected
        observed = max(receipt.verified_at, parse_rfc3339(admission.admitted_at))
        observation = SourceObservation(
            admission.post,
            SourceObservationOutcome.PRESENT,
            admission.post.record,
            receipt.receipt_id,
            snapshot.currentness_receipt_id,
            observed.isoformat(),
            prior.source_observation.observation_id,
        )
        return self.reducer.admit(
            prior, admission.authorization, admission, observation
        )

    def _observe_current(self, prior, history, unavailable):
        latest = history.latest
        if unavailable is not None and unavailable.observed_at >= latest.observed_at:
            observation = SourceObservation(
                prior.submission.post,
                SourceObservationOutcome.UNAVAILABLE,
                None,
                unavailable.acquisition_receipt_id,
                unavailable.currentness_receipt_id,
                unavailable.observed_at.isoformat(),
                prior.source_observation.observation_id,
            )
            return self.reducer.observe(prior, observation)
        current = next(
            (
                record
                for record in latest.state.records
                if record.identity.uri == prior.submission.post.record.uri
            ),
            None,
        )
        if current is None:
            outcome = SourceObservationOutcome.ABSENT
            observed_record = None
            evidence = latest.custody_receipt_id
        else:
            outcome = SourceObservationOutcome.PRESENT
            observed_record = _exact(current)
            evidence = latest.receipt_for(current).receipt_id
        if latest.observed_at < parse_rfc3339(prior.source_observation.observed_at):
            if (
                observed_record == prior.submission.post.record
                and evidence == prior.source_observation.evidence_receipt_id
            ):
                # The admission already bound this same qualified observation at
                # its later decision time.  An older custody timestamp for the
                # identical snapshot is not a newer observation and must not
                # roll the lifecycle backward.
                return prior
            _fail(
                "live_projection_history_insufficient",
                "current snapshot predates admission evidence",
            )
        observation = SourceObservation(
            prior.submission.post,
            outcome,
            observed_record,
            evidence,
            latest.currentness_receipt_id,
            latest.observed_at.isoformat(),
            prior.source_observation.observation_id,
        )
        return self.reducer.observe(prior, observation)

    @staticmethod
    def _publish(artifact, policy, published_at):
        if artifact is None:
            return None
        channel = (
            PublicProjectionChannel.TECHNICAL_AUDIT
            if policy.include_technical_receipts
            else PublicProjectionChannel.ORDINARY
        )
        return LocalProjectionFeedBoundary().publish(
            FeedPublicationRequest(
                artifact,
                artifact.artifact_id,
                artifact.community_identity_id,
                artifact.publication_reference_id,
                channel,
                published_at,
            )
        )


__all__ = [
    "AuthorityWriteReceipt",
    "CompiledLiveProjection",
    "LiveProjectionCompiler",
    "QualifiedRepoHistory",
    "QualifiedSnapshot",
    "SourceUnavailableEvidence",
]
