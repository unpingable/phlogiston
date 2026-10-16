"""SA10d bounded read-only composition through the admission boundary."""

from __future__ import annotations

import hashlib
import urllib.parse
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from community_model import ValidationError

from .artifact_source import (
    FullRepoArtifactRequest,
    ObservedCarArtifact,
    RepoOpsArtifactRequest,
)
from .authenticated_acquisition import AuthenticatedSpaceArtifactProvider
from .car import extract_space_repo_evidence
from .compat import (
    SA10D_OBSERVER_DOCTRINE,
    SA10D_OBSERVER_METHOD,
    SA10D_OBSERVER_VERSION,
)
from .credential import QualifiedSpaceCredential
from .credential_request import CredentialAuthenticatedRequest
from .did_binding import (
    DidBindingReceipt,
    DidInterpretationProfile,
    verification_key_bytes,
)
from .did_resolution import ResolvedDidDocument, require_resolved_document_binding
from .empty_state import QualifiedEmptyRepoState, qualify_empty_repo_state
from .host_migration import HostBindingEpoch
from .model import (
    AccessContext,
    EvidenceAdmission,
    RepoBinding,
    RepoSnapshot,
    SpaceIdentity,
    SpaceObservation,
    WriterSetClaim,
)
from .operations import (
    OperationAcquisitionResult,
    OperationSourceContext,
    acquire_repo_transition_candidate,
)
from .qualification import (
    QualificationSourceContext,
    QualifiedRepoState,
    qualify_repo_state,
)
from .reconciliation import ReconciliationResult, reconcile_qualified_states
from .recovery import (
    OperationUnavailableReason,
    RecoveryDecisionTrace,
    qualify_recovery_decision,
)
from .sync_state import DurableSyncStore
from .transition import identify_qualified_repo_state

_NON_CLAIMS = frozenset(
    {
        "complete_history",
        "global_currentness",
        "source_authority_beyond_supplied_identity_receipts",
        "space_membership",
        "community_standing",
        "authorization",
        "governance_authority",
        "effect_execution",
    }
)


def _fail(reason: str, message: str) -> None:
    raise ValidationError(reason, message)


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        _fail("spaces_read_only_sync_invalid", "time must be timezone-aware")
    return value.astimezone(UTC)


def _rid(parts: tuple[str, ...]) -> str:
    return "sha256:" + hashlib.sha256("\x00".join(parts).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ReadOnlySnapshotReceipt:
    receipt_id: str
    resolution_receipt_id: str
    repo_host_binding_receipt_id: str
    author_key_binding_receipt_id: str
    credential_receipt_id: str
    request_binding_receipt_id: str
    acquisition_receipt_id: str
    car_sha256: str
    state_receipt_ids: tuple[str, ...]
    durable_event_ids: tuple[str, ...]
    admission_subjects: tuple[tuple[str, str], ...]
    endpoint_binding_established: bool
    loopback_fixture_override: bool
    observed_at: datetime
    explicit_non_claims: frozenset[str] = field(default=_NON_CLAIMS)
    method: str = field(default=SA10D_OBSERVER_METHOD, init=False)
    version: str = field(default=SA10D_OBSERVER_VERSION, init=False)
    doctrine: str = field(default=SA10D_OBSERVER_DOCTRINE, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", _utc(self.observed_at))
        if (
            self.endpoint_binding_established == self.loopback_fixture_override
            or self.explicit_non_claims != _NON_CLAIMS
            or self.receipt_id
            != _rid(
                (
                    self.method,
                    self.version,
                    self.doctrine,
                    self.resolution_receipt_id,
                    self.repo_host_binding_receipt_id,
                    self.author_key_binding_receipt_id,
                    self.credential_receipt_id,
                    self.request_binding_receipt_id,
                    self.acquisition_receipt_id,
                    self.car_sha256,
                    *self.state_receipt_ids,
                    *self.durable_event_ids,
                    *(f"{uri}@{cid}" for uri, cid in self.admission_subjects),
                    str(self.endpoint_binding_established),
                    str(self.loopback_fixture_override),
                    _utc(self.observed_at).isoformat(),
                )
            )
        ):
            _fail("spaces_read_only_sync_receipt_invalid", "receipt is not bound")

    def to_provenance(self) -> dict[str, object]:
        return {
            "receiptId": self.receipt_id,
            "method": self.method,
            "version": self.version,
            "doctrine": self.doctrine,
            "resolutionReceiptId": self.resolution_receipt_id,
            "repoHostBindingReceiptId": self.repo_host_binding_receipt_id,
            "authorKeyBindingReceiptId": self.author_key_binding_receipt_id,
            "credentialReceiptId": self.credential_receipt_id,
            "requestBindingReceiptId": self.request_binding_receipt_id,
            "acquisitionReceiptId": self.acquisition_receipt_id,
            "carSha256": self.car_sha256,
            "stateReceiptIds": self.state_receipt_ids,
            "durableEventIds": self.durable_event_ids,
            "admissionSubjects": self.admission_subjects,
            "endpointBindingEstablished": self.endpoint_binding_established,
            "loopbackFixtureOverride": self.loopback_fixture_override,
            "observedAt": self.observed_at.isoformat(),
            "explicitNonClaims": sorted(self.explicit_non_claims),
        }


@dataclass(frozen=True, slots=True)
class ReadOnlySnapshotResult:
    artifact: ObservedCarArtifact
    state: QualifiedRepoState
    reconciliation: ReconciliationResult | None
    admissions: tuple[EvidenceAdmission, ...]
    receipt: ReadOnlySnapshotReceipt


@dataclass(slots=True)
class BoundedReadOnlySpacesObserver:
    """No scheduler: each call is one explicit, independently receipted attempt."""

    space: SpaceIdentity
    repo_did: str
    resolved_repo: ResolvedDidDocument
    repo_host_binding: DidBindingReceipt
    author_key_binding: DidBindingReceipt
    credential: QualifiedSpaceCredential
    store: DurableSyncStore
    allow_loopback_fixture_transport: bool = False

    def __post_init__(self) -> None:
        require_resolved_document_binding(
            self.resolved_repo, self.resolved_repo.document_bytes
        )
        if self.repo_did != self.resolved_repo.expected_did:
            _fail(
                "spaces_read_only_sync_identity_mismatch", "resolved repo DID differs"
            )
        for binding, profile in (
            (self.repo_host_binding, DidInterpretationProfile.ACCOUNT_REPO_HOST),
            (self.author_key_binding, DidInterpretationProfile.ACCOUNT_SIGNING_KEY),
        ):
            if (
                binding.profile is not profile
                or binding.expected_did != self.repo_did
                or binding.document_sha256 != self.resolved_repo.document_sha256
                or binding.document_provenance_ref
                != self.resolved_repo.method_receipt_id
            ):
                _fail(
                    "spaces_read_only_sync_identity_mismatch",
                    "service/key binding is not from the supplied resolution",
                )
        if self.credential.receipt.space != self.space:
            _fail(
                "spaces_read_only_sync_credential_mismatch", "credential Space differs"
            )
        HostBindingEpoch.from_receipts(self.resolved_repo, self.repo_host_binding)

    def _request_endpoint_match(self, request: CredentialAuthenticatedRequest) -> bool:
        if (
            request.credential.receipt.receipt_id != self.credential.receipt.receipt_id
            or request.receipt.credential_receipt_id
            != self.credential.receipt.receipt_id
        ):
            _fail(
                "spaces_read_only_sync_credential_mismatch",
                "authenticated request uses another credential",
            )
        parsed = urllib.parse.urlsplit(request.url)
        actual_origin = f"{parsed.scheme}://{parsed.netloc}"
        expected_origin = self.repo_host_binding.selected_origin
        if actual_origin == expected_origin:
            return True
        if not self.allow_loopback_fixture_transport or (
            parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
        ):
            _fail(
                "spaces_read_only_sync_endpoint_mismatch",
                "request target differs from the selected repo-host origin",
            )
        return False

    def _source(self, artifact: ObservedCarArtifact) -> QualificationSourceContext:
        if artifact.source.source_endpoint != self.repo_host_binding.selected_origin:
            _fail(
                "spaces_read_only_sync_source_mismatch",
                "artifact source differs from selected repo host",
            )
        return QualificationSourceContext(
            repo_host=artifact.source.source_endpoint,
            author_key_ref=self.author_key_binding.receipt_id,
            author_key_binding_method=(
                f"sa9c:{self.resolved_repo.method.value}+sa9b:account-key"
            ),
            evidence_ref=artifact.source.artifact_ref,
            writer_discovery_ref="explicit-writer-claim-required-for-admission",
        )

    def _algorithm(self) -> str:
        return (
            "ES256K"
            if self.author_key_binding.selected_key_curve == "k256"
            else "ES256"
        )

    def acquire_operations(
        self,
        provider: AuthenticatedSpaceArtifactProvider,
        requests: tuple[
            tuple[RepoOpsArtifactRequest, CredentialAuthenticatedRequest], ...
        ],
        *,
        known_state: QualifiedRepoState,
    ) -> OperationAcquisitionResult:
        if not requests:
            _fail("spaces_read_only_sync_invalid", "operation requests are required")
        if provider.source_endpoint != self.repo_host_binding.selected_origin:
            _fail("spaces_read_only_sync_source_mismatch", "provider source differs")
        pages = []
        refs = []
        observed = None
        for ordinal, (artifact_request, authenticated_request) in enumerate(requests):
            self._request_endpoint_match(authenticated_request)
            if artifact_request.identity.space != self.space or (
                artifact_request.identity.repo_did != self.repo_did
            ):
                _fail(
                    "spaces_read_only_sync_request_mismatch", "operation target differs"
                )
            artifact = provider.list_repo_ops(artifact_request, authenticated_request)
            if (
                artifact.source.source_endpoint
                != self.repo_host_binding.selected_origin
            ):
                _fail(
                    "spaces_read_only_sync_source_mismatch", "operation source differs"
                )
            for page in artifact.pages:
                pages.append(replace(page, ordinal=len(pages)))
            refs.append(artifact.source.artifact_ref)
            observed = artifact.source.observed_at
            acquisition = provider.receipt(artifact.source.artifact_ref)
            self.store.record_acquisition(
                acquisition.receipt_id,
                acquisition.to_provenance(),
                observed_at=acquisition.observed_at,
            )
        assert observed is not None
        context = OperationSourceContext(
            self.space,
            self.repo_did,
            self.repo_host_binding.selected_origin or "",
            "authenticated-pages:"
            + hashlib.sha256("\x00".join(refs).encode()).hexdigest(),
            observed,
        )
        return acquire_repo_transition_candidate(
            pages, source_state=known_state, context=context
        )

    def synchronize_snapshot(
        self,
        provider: AuthenticatedSpaceArtifactProvider,
        artifact_request: FullRepoArtifactRequest,
        authenticated_request: CredentialAuthenticatedRequest,
        *,
        known_state: QualifiedRepoState | None = None,
        writer_discovery: WriterSetClaim | None = None,
        access: AccessContext | None = None,
        admitted_collections: frozenset[str] = frozenset(),
    ) -> ReadOnlySnapshotResult:
        if artifact_request.identity.space != self.space or (
            artifact_request.identity.repo_did != self.repo_did
        ):
            _fail("spaces_read_only_sync_request_mismatch", "full-repo target differs")
        if provider.source_endpoint != self.repo_host_binding.selected_origin:
            _fail("spaces_read_only_sync_source_mismatch", "provider source differs")
        endpoint_match = self._request_endpoint_match(authenticated_request)
        artifact = provider.get_repo(artifact_request, authenticated_request)
        acquisition = provider.receipt(artifact.source.artifact_ref)
        acquisition_event = self.store.record_acquisition(
            acquisition.receipt_id,
            acquisition.to_provenance(),
            observed_at=acquisition.observed_at,
        )
        source = self._source(artifact)
        extraction = extract_space_repo_evidence(
            artifact.sa2_input(), source_vector_identifier=artifact.source.artifact_ref
        )
        qualifier = (
            qualify_empty_repo_state
            if not extraction.evidence.record_blocks
            else qualify_repo_state
        )
        state = qualifier(
            extraction.evidence,
            expected_space=self.space,
            expected_author_did=self.repo_did,
            author_public_key=verification_key_bytes(self.author_key_binding),
            signature_algorithm=self._algorithm(),
            source=source,
            verified_at=artifact.source.observed_at,
        )
        admissions = self._admit(
            state,
            source,
            artifact,
            writer_discovery=writer_discovery,
            access=access,
            admitted_collections=admitted_collections,
        )
        identity = identify_qualified_repo_state(state)
        reconciliation = None
        if known_state is None:
            state_event = self.store.seed_qualified_state(
                identity,
                custody_ref=artifact.source.artifact_ref,
                observed_at=artifact.source.observed_at,
            )
        else:
            reconciliation = reconcile_qualified_states(
                known_state,
                state,
                reconciled_at=artifact.source.observed_at,
            )
            state_event = self.store.record_reconciliation(reconciliation)
        state_receipts = (
            (state.empty_receipt.receipt_id,)
            if isinstance(state, QualifiedEmptyRepoState)
            else tuple(receipt.receipt_id for receipt in state.receipts)
        )
        fields = (
            self.resolved_repo.method_receipt_id,
            self.repo_host_binding.receipt_id,
            self.author_key_binding.receipt_id,
            self.credential.receipt.receipt_id,
            authenticated_request.receipt.receipt_id,
            acquisition.receipt_id,
            extraction.car.raw_sha256,
            *state_receipts,
            acquisition_event,
            state_event,
            *(
                f"{a.observation.record.identity.uri}@{a.observation.record.cid}"
                for a in admissions
            ),
            str(endpoint_match),
            str(self.allow_loopback_fixture_transport and not endpoint_match),
            artifact.source.observed_at.isoformat(),
        )
        receipt_id = _rid(
            (
                SA10D_OBSERVER_METHOD,
                SA10D_OBSERVER_VERSION,
                SA10D_OBSERVER_DOCTRINE,
                *fields,
            )
        )
        receipt = ReadOnlySnapshotReceipt(
            receipt_id,
            self.resolved_repo.method_receipt_id,
            self.repo_host_binding.receipt_id,
            self.author_key_binding.receipt_id,
            self.credential.receipt.receipt_id,
            authenticated_request.receipt.receipt_id,
            acquisition.receipt_id,
            extraction.car.raw_sha256,
            state_receipts,
            (acquisition_event, state_event),
            tuple(
                (a.observation.record.identity.uri, a.observation.record.cid)
                for a in admissions
            ),
            endpoint_match,
            self.allow_loopback_fixture_transport and not endpoint_match,
            artifact.source.observed_at,
        )
        return ReadOnlySnapshotResult(
            artifact, state, reconciliation, admissions, receipt
        )

    def _admit(
        self,
        state: QualifiedRepoState,
        source: QualificationSourceContext,
        artifact: ObservedCarArtifact,
        *,
        writer_discovery: WriterSetClaim | None,
        access: AccessContext | None,
        admitted_collections: frozenset[str],
    ) -> tuple[EvidenceAdmission, ...]:
        if writer_discovery is None and access is None and not admitted_collections:
            return ()
        if writer_discovery is None or access is None or not admitted_collections:
            _fail(
                "spaces_read_only_sync_admission_context_incomplete",
                "admission inputs are incomplete",
            )
        if (
            writer_discovery.space != self.space
            or writer_discovery.repo_did != self.repo_did
            or writer_discovery.rev != state.commit.rev
            or writer_discovery.commit_hash != state.commit.state_hash.hex()
            or access.space != self.space
            or access.issuer_did != self.credential.receipt.authority_did
            or access.user_did != self.credential.receipt.applicant_context_did
            or int(access.issued_at.timestamp()) != self.credential.receipt.issued_at
            or int(access.expires_at.timestamp()) != self.credential.receipt.expires_at
            or writer_discovery.space_host
            != self.credential.receipt.issuance_host_origin
        ):
            _fail(
                "spaces_read_only_sync_admission_context_mismatch",
                "admission context differs",
            )
        verification = state.repo_verification(
            source=source, verified_at=artifact.source.observed_at
        )
        snapshot = RepoSnapshot(
            self.space,
            self.repo_did,
            source.repo_host,
            state.commit.rev,
            state.commit.state_hash.hex(),
            artifact.source.observed_at,
            access,
            verification,
            state.records,
            state.receipts,
        )
        binding = RepoBinding(
            self.space,
            self.repo_did,
            source.repo_host,
            self.repo_host_binding.qualified_at,
            "sa9c-resolution+sa9b-account-repo-host",
            self.repo_host_binding.receipt_id,
        )
        return tuple(
            EvidenceAdmission(
                SpaceObservation(
                    record,
                    writer_discovery,
                    binding,
                    snapshot,
                    artifact.source.observed_at,
                ),
                artifact.source.observed_at,
                policy="spaces-alpha-sa10d-qualified-read-only-v1",
            )
            for record in state.records
            if record.identity.collection in admitted_collections
        )

    def record_recovery(
        self,
        known_state: QualifiedRepoState,
        operation_acquisition: OperationAcquisitionResult | None,
        full_repo_artifact: ObservedCarArtifact,
        *,
        unavailable_reason: OperationUnavailableReason | None,
        decided_at: datetime,
    ) -> RecoveryDecisionTrace:
        self.store.record_acquisition(
            full_repo_artifact.source.artifact_ref,
            full_repo_artifact.source.to_provenance(),
            observed_at=full_repo_artifact.source.observed_at,
        )
        source = self._source(full_repo_artifact)
        trace = qualify_recovery_decision(
            known_state,
            operation_acquisition=operation_acquisition,
            operation_unavailable_reason=unavailable_reason,
            full_repo_artifact=full_repo_artifact,
            author_public_key=verification_key_bytes(self.author_key_binding),
            signature_algorithm=self._algorithm(),
            qualification_source=source,
            qualified_at=full_repo_artifact.source.observed_at,
            decided_at=_utc(decided_at),
        )
        self.store.apply_qualified_recovery(trace)
        return trace


__all__ = [
    "BoundedReadOnlySpacesObserver",
    "ReadOnlySnapshotReceipt",
    "ReadOnlySnapshotResult",
]
