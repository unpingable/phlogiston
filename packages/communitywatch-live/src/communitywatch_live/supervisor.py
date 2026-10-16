"""One explicit poll -> qualify -> reconcile -> compile -> publish operation."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import urllib.parse
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from community_model import ValidationError, canonical_json_bytes
from community_space_artifact import DisclosureMode, DisclosurePolicy
from community_space_model import CommunityIdentity, SpaceIdentity
from communitywatch_space_publisher import (
    AtomicProjectionPublisher,
    AuthorityWriteReceipt,
    LiveProjectionCompiler,
    PublishedGeneration,
    QualifiedRepoHistory,
    QualifiedSnapshot,
    SourceUnavailableEvidence,
)
from communitywatch_spaces_alpha import (
    QualificationSourceContext,
    ReconciliationDisposition,
    extract_space_repo_evidence,
    identify_qualified_repo_state,
    qualify_empty_repo_state,
    qualify_repo_state,
    reconcile_qualified_states,
)
from communitywatch_spaces_alpha import (
    SpaceIdentity as AlphaSpaceIdentity,
)

from .identity import (
    PlcDirectoryIdentityQualifier,
    QualifiedRepoIdentity,
    QualifiedSpaceAuthority,
)

SUPERVISOR_VERSION = "juniper-live-supervisor/1"
_L8_FIELDS = frozenset(
    {
        "receiptId",
        "method",
        "requestId",
        "artifactKind",
        "space",
        "repoDid",
        "requestedUrl",
        "observedAt",
        "status",
        "contentType",
        "bodySha256",
        "bodyLength",
        "bodyFile",
        "delegationSha256",
        "credentialSha256",
        "dpopKeyThumbprint",
        "credentialExchangeProofSha256",
        "artifactProofSha256",
        "proofClaimsSelfVerified",
        "attempts",
        "automaticArtifactRetries",
        "redirectsFollowed",
        "verifiedClaims",
        "explicitNonClaims",
    }
)


class AcquisitionUnavailable(Exception):
    def __init__(self, repo_did: str, receipt_id: str, observed_at: datetime) -> None:
        super().__init__("bounded artifact acquisition unavailable")
        self.repo_did = repo_did
        self.receipt_id = receipt_id
        self.observed_at = observed_at


@dataclass(frozen=True, slots=True)
class SupervisorConfig:
    space: SpaceIdentity
    community_actor_did: str
    author_action_store: Path
    artifact_spool: Path
    authority_receipt_directory: Path
    evidence_directory: Path
    projection_directory: Path
    acquisition_command: tuple[str, ...]
    acquisition_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not isinstance(self.space, SpaceIdentity):
            raise ValueError("supervisor Space is required")
        CommunityIdentity(self.space, self.community_actor_did)
        if not self.acquisition_command or any(
            not item for item in self.acquisition_command
        ):
            raise ValueError("acquisition command is required")

    @property
    def community(self) -> CommunityIdentity:
        return CommunityIdentity(self.space, self.community_actor_did)


@dataclass(frozen=True, slots=True)
class LiveRunResult:
    run_receipt_id: str
    generation: PublishedGeneration | None
    discovered_authors: tuple[str, ...]
    qualified_repositories: tuple[str, ...]
    unavailable_authors: tuple[str, ...]
    published: bool
    explicit_non_claims: tuple[str, ...] = (
        "complete_history",
        "global_currentness",
        "community_standing",
        "governance_authority",
        "human_comprehension",
    )


class CommandArtifactAcquirer:
    """Invoke the L8 child once; stdin and output contain no credentials."""

    def __init__(self, config: SupervisorConfig) -> None:
        self.config = config

    def acquire(self, repo_did: str, *, observed_at: datetime) -> None:
        request_id = f"repo-{observed_at.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex}"
        payload = canonical_json_bytes(
            {"kind": "get_repo", "repoDid": repo_did, "requestId": request_id}
        )
        try:
            result = subprocess.run(
                self.config.acquisition_command,
                input=payload,
                capture_output=True,
                timeout=self.config.acquisition_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise self._failure(repo_did, request_id, observed_at) from exc
        if result.returncode != 0 or len(result.stdout) > 256 * 1024:
            raise self._failure(repo_did, request_id, observed_at)
        try:
            output = _strict_json(result.stdout)
        except ValidationError as exc:
            raise self._failure(repo_did, request_id, observed_at) from exc
        if (
            not isinstance(output, dict)
            or set(output) != {"receipt", "receiptFile", "bodyFile"}
            or not isinstance(output["receipt"], dict)
            or output["receipt"].get("requestId") != request_id
            or output["receipt"].get("repoDid") != repo_did
        ):
            raise self._failure(repo_did, request_id, observed_at)

    def _failure(
        self, repo_did: str, request_id: str, observed_at: datetime
    ) -> AcquisitionUnavailable:
        receipt = {
            "version": SUPERVISOR_VERSION,
            "classification": "acquisition_unavailable",
            "repoDid": repo_did,
            "requestId": request_id,
            "observedAt": observed_at.astimezone(UTC).isoformat(),
            "secretOutputRetained": False,
            "artifactQualified": False,
            "currentness": False,
            "governanceAuthority": False,
        }
        receipt_id = _retain_receipt(self.config.evidence_directory, receipt)
        return AcquisitionUnavailable(repo_did, receipt_id, observed_at)


class LiveSupervisor:
    def __init__(
        self,
        config: SupervisorConfig,
        identities: PlcDirectoryIdentityQualifier,
        acquirer: CommandArtifactAcquirer,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.config = config
        self.identities = identities
        self.acquirer = acquirer
        self.clock = clock

    def run_once(self) -> LiveRunResult:
        observed_at = _aware(self.clock())
        authors = _discover_authors(self.config.author_action_store)
        if not authors:
            return self._record_result(observed_at, (), (), (), None)
        repositories = (*authors, self.config.community_actor_did)
        unavailable: list[AcquisitionUnavailable] = []
        for repo_did in repositories:
            try:
                self.acquirer.acquire(repo_did, observed_at=observed_at)
            except AcquisitionUnavailable as exc:
                unavailable.append(exc)

        bindings = {
            did: self.identities.qualify(did, evaluated_at=observed_at)
            for did in repositories
        }
        authority = self.identities.qualify_space_authority(
            self.config.space.authority_did, evaluated_at=observed_at
        )
        histories = {
            did: _qualified_history(
                self.config,
                bindings[did],
                authority,
                expected_space=self.config.space,
            )
            for did in repositories
        }
        unavailable_ids = {item.repo_did for item in unavailable}
        if self.config.community_actor_did in unavailable_ids or (
            self.config.community_actor_did not in histories
        ):
            raise ValidationError(
                "live_community_observation_unavailable",
                "community repository cannot be republished without observation",
            )
        for did in repositories:
            if did not in histories:
                raise ValidationError(
                    "live_initial_observation_unavailable",
                    "repository has no qualified snapshot",
                )
        source_unavailable = tuple(
            SourceUnavailableEvidence(
                item.repo_did,
                item.receipt_id,
                item.receipt_id,
                item.observed_at,
            )
            for item in unavailable
            if item.repo_did in authors and item.repo_did in histories
        )
        authority = _authority_receipts(
            self.config.authority_receipt_directory, self.config.community
        )
        ordinary, audit = _policies()
        compiled = LiveProjectionCompiler(self.config.community).compile(
            authors=tuple(histories[item] for item in authors),
            community_history=histories[self.config.community_actor_did],
            authority_receipts=authority,
            ordinary_policy=ordinary,
            audit_policy=audit,
            published_at=observed_at.isoformat().replace("+00:00", "Z"),
            unavailable=source_unavailable,
        )
        generation = None
        if compiled.ordinary_feed is not None and compiled.audit_feed is not None:
            generation = AtomicProjectionPublisher().publish(
                self.config.projection_directory,
                compiled.ordinary_feed,
                compiled.audit_feed,
            )
        return self._record_result(
            observed_at,
            authors,
            tuple(histories),
            tuple(sorted(unavailable_ids & set(authors))),
            generation,
        )

    def run_forever(self, interval_seconds: float) -> None:
        if interval_seconds < 1:
            raise ValueError("poll interval must be at least one second")
        while True:
            self.run_once()
            time.sleep(interval_seconds)

    def _record_result(
        self,
        observed_at: datetime,
        authors: tuple[str, ...],
        qualified: tuple[str, ...],
        unavailable: tuple[str, ...],
        generation: PublishedGeneration | None,
    ) -> LiveRunResult:
        payload = {
            "version": SUPERVISOR_VERSION,
            "observedAt": observed_at.isoformat(),
            "discoveredAuthors": list(authors),
            "qualifiedRepositories": list(qualified),
            "unavailableAuthors": list(unavailable),
            "generationId": generation.generation_id if generation else None,
            "published": generation is not None,
            "completeHistory": False,
            "globalCurrentness": False,
            "governanceAuthority": False,
        }
        receipt_id = _retain_receipt(self.config.evidence_directory, payload)
        return LiveRunResult(
            receipt_id,
            generation,
            authors,
            qualified,
            unavailable,
            generation is not None,
        )


def _qualified_history(
    config: SupervisorConfig,
    identity: QualifiedRepoIdentity,
    authority: QualifiedSpaceAuthority,
    *,
    expected_space: SpaceIdentity,
) -> QualifiedRepoHistory:
    candidates: list[tuple[datetime, object, str]] = []
    for receipt_path in sorted(config.artifact_spool.glob("*.receipt.json")):
        receipt = _l8_receipt(receipt_path, config.artifact_spool)
        if receipt["artifactKind"] != "get_repo" or receipt["repoDid"] != identity.did:
            continue
        if receipt["space"] != expected_space.uri:
            raise ValidationError(
                "live_space_binding_mismatch",
                "artifact acquisition Space differs from supervisor Space",
            )
        requested_origin = _url_origin(str(receipt["requestedUrl"]))
        if requested_origin != identity.repo_host:
            raise ValidationError(
                "live_endpoint_binding_mismatch",
                "artifact origin differs from qualified DID service",
            )
        if _credential_exchange_origin(receipt) != authority.authority_host:
            raise ValidationError(
                "live_authority_endpoint_binding_mismatch",
                "credential exchange origin differs from qualified Space authority service",
            )
        body = (config.artifact_spool / str(receipt["bodyFile"])).read_bytes()
        observed = _aware(
            datetime.fromisoformat(str(receipt["observedAt"]).replace("Z", "+00:00"))
        )
        extraction = extract_space_repo_evidence(
            body, source_vector_identifier=str(receipt["receiptId"])
        )
        source = QualificationSourceContext(
            identity.repo_host,
            identity.key_binding_receipt_id,
            "sa9c:did:plc+sa9b:account-key",
            str(receipt["receiptId"]),
            "explicit-writer-claim-required-for-admission",
        )
        qualifier = (
            qualify_empty_repo_state
            if not extraction.evidence.record_blocks
            else qualify_repo_state
        )
        state = qualifier(
            extraction.evidence,
            expected_space=AlphaSpaceIdentity.parse(expected_space.uri),
            expected_author_did=identity.did,
            author_public_key=identity.public_key,
            signature_algorithm=identity.signature_algorithm,
            source=source,
            verified_at=observed,
        )
        candidates.append((observed, state, str(receipt["receiptId"])))
    if not candidates:
        raise ValidationError(
            "live_qualified_snapshot_missing", "repository has no qualified CAR"
        )
    snapshots: list[QualifiedSnapshot] = []
    previous = None
    for observed, state, custody in sorted(candidates, key=lambda item: item[0]):
        if previous is None:
            currentness = _state_relationship_receipt(
                config.evidence_directory, None, state, observed, "snapshot_seed"
            )
            snapshots.append(QualifiedSnapshot(state, custody, currentness, observed))
            previous = state
            continue
        reconciliation = reconcile_qualified_states(
            previous, state, reconciled_at=observed
        )
        currentness = _state_relationship_receipt(
            config.evidence_directory,
            previous,
            state,
            observed,
            reconciliation.disposition.value,
        )
        if reconciliation.disposition is ReconciliationDisposition.EQUAL_STATE:
            continue
        if (
            reconciliation.disposition
            is ReconciliationDisposition.INSUFFICIENT_EVIDENCE
        ):
            raise ValidationError(
                "live_reconciliation_conflict",
                "stale or conflicting qualified artifact cannot replace state",
            )
        snapshots.append(QualifiedSnapshot(state, custody, currentness, observed))
        previous = state
    return QualifiedRepoHistory(tuple(snapshots))


def _l8_receipt(path: Path, spool: Path) -> dict[str, object]:
    raw = path.read_bytes()
    value = _strict_json(raw)
    if not isinstance(value, dict) or set(value) != _L8_FIELDS:
        raise ValidationError(
            "live_acquisition_receipt_invalid", "receipt fields differ"
        )
    receipt_id = value.pop("receiptId")
    expected = "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    value["receiptId"] = receipt_id
    if receipt_id != expected or value["method"] != "juniper-communitywatch-alpha/1":
        raise ValidationError(
            "live_acquisition_receipt_invalid", "receipt binding differs"
        )
    if (
        value["automaticArtifactRetries"] != 0
        or value["redirectsFollowed"] != 0
        or value["status"] != 200
        or value["proofClaimsSelfVerified"] is not True
        or value["verifiedClaims"]
        != ["exact_http_response_bytes", "credential_bound_dpop_request"]
    ):
        raise ValidationError(
            "live_acquisition_receipt_invalid", "transport policy differs"
        )
    body_name = value["bodyFile"]
    if not isinstance(body_name, str) or Path(body_name).name != body_name:
        raise ValidationError(
            "live_acquisition_receipt_invalid", "body path escapes spool"
        )
    body_path = spool / body_name
    if body_path.is_symlink() or not body_path.is_file():
        raise ValidationError(
            "live_acquisition_body_mismatch", "spool body is not regular"
        )
    body = body_path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != value["bodySha256"]
        or len(body) != value["bodyLength"]
    ):
        raise ValidationError("live_acquisition_body_mismatch", "spool bytes differ")
    return value


def _authority_receipts(
    directory: Path, community: CommunityIdentity
) -> tuple[AuthorityWriteReceipt, ...]:
    if not directory.exists():
        return ()
    return tuple(
        AuthorityWriteReceipt.parse(path.read_bytes(), community=community)
        for path in sorted(directory.glob("*.json"))
    )


def _discover_authors(path: Path) -> tuple[str, ...]:
    try:
        value = _strict_json(path.read_bytes())
    except FileNotFoundError:
        return ()
    except ValidationError as exc:
        raise ValidationError(
            "live_discovery_invalid", "author discovery is invalid"
        ) from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "items"}
        or value["version"] != "juniper-author-actions/1"
        or not isinstance(value["items"], list)
    ):
        raise ValidationError(
            "live_discovery_invalid", "author discovery fields differ"
        )
    authors = set()
    for item in value["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("authorDid"), str):
            raise ValidationError(
                "live_discovery_invalid", "author discovery item differs"
            )
        authors.add(item["authorDid"])
    return tuple(sorted(authors))


def _policies() -> tuple[DisclosurePolicy, DisclosurePolicy]:
    policy = _static_id("scv0-d2-public-projection-policy/1")
    ordinary = _static_id("scv0-d2-publication-ordinary/1")
    audit = _static_id("scv0-d2-publication-audit/1")
    return (
        DisclosurePolicy(DisclosureMode.ORDINARY, policy, ordinary),
        DisclosurePolicy(DisclosureMode.TECHNICAL_AUDIT, policy, audit),
    )


def _state_relationship_receipt(
    directory: Path,
    previous: object | None,
    observed: object,
    when: datetime,
    classification: str,
) -> str:
    observed_identity = identify_qualified_repo_state(observed).to_provenance()  # type: ignore[arg-type]
    previous_identity = (
        identify_qualified_repo_state(previous).to_provenance()  # type: ignore[arg-type]
        if previous is not None
        else None
    )
    return _retain_receipt(
        directory,
        {
            "version": SUPERVISOR_VERSION,
            "classification": classification,
            "knownState": previous_identity,
            "observedState": observed_identity,
            "observedAt": when.isoformat(),
            "completeHistory": False,
            "currentness": False,
            "governanceAuthority": False,
        },
    )


def _retain_receipt(directory: Path, payload: Mapping[str, object]) -> str:
    receipt_id = _id(payload)
    output = dict(payload)
    output["receiptId"] = receipt_id
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    path = directory / f"{receipt_id.removeprefix('sha256:')}.json"
    data = canonical_json_bytes(output) + b"\n"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValidationError(
                "live_receipt_custody_conflict", "receipt bytes conflict"
            )
    return receipt_id


def _id(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _static_id(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _aware(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValidationError(
            "live_supervisor_time_invalid", "supervisor time must be aware"
        )
    return value.astimezone(UTC)


def _url_origin(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if not parsed.scheme or not parsed.netloc or parsed.username or parsed.password:
        raise ValidationError(
            "live_endpoint_binding_mismatch", "artifact URL is invalid"
        )
    return f"{parsed.scheme}://{parsed.netloc}"


def _strict_json(value: bytes) -> object:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = item
        return result

    try:
        return json.loads(value, object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValidationError(
            "live_json_invalid", "input is invalid or ambiguous JSON"
        ) from exc


def _credential_exchange_origin(receipt: Mapping[str, object]) -> str:
    attempts = receipt.get("attempts")
    if not isinstance(attempts, list):
        raise ValidationError(
            "live_acquisition_receipt_invalid", "transport attempts are invalid"
        )
    exchanges = []
    artifacts = []
    for ordinal, attempt in enumerate(attempts):
        if not isinstance(attempt, dict) or set(attempt) != {
            "ordinal",
            "method",
            "url",
            "status",
            "purpose",
        }:
            raise ValidationError(
                "live_acquisition_receipt_invalid", "transport attempt fields differ"
            )
        if attempt["ordinal"] != ordinal:
            raise ValidationError(
                "live_acquisition_receipt_invalid", "transport attempt order differs"
            )
        if attempt["purpose"] not in {
            "oauth-library",
            "credential-exchange",
            "artifact",
        }:
            raise ValidationError(
                "live_acquisition_receipt_invalid", "transport purpose is invalid"
            )
        if attempt["purpose"] == "credential-exchange":
            if attempt["method"] != "POST" or attempt["status"] != 200:
                raise ValidationError(
                    "live_acquisition_receipt_invalid",
                    "credential exchange attempt is not successful",
                )
            exchanges.append(_url_origin(str(attempt["url"])))
        elif attempt["purpose"] == "artifact":
            if (
                attempt["method"] != "GET"
                or attempt["status"] != 200
                or attempt["url"] != receipt.get("requestedUrl")
            ):
                raise ValidationError(
                    "live_acquisition_receipt_invalid",
                    "artifact attempt differs from receipt request",
                )
            artifacts.append(attempt["url"])
    if len(exchanges) != 1:
        raise ValidationError(
            "live_acquisition_receipt_invalid",
            "exactly one credential exchange attempt is required",
        )
    if len(artifacts) != 1:
        raise ValidationError(
            "live_acquisition_receipt_invalid",
            "exactly one artifact attempt is required",
        )
    return exchanges[0]
