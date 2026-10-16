"""SA5 adapter from pinned listRepoOps responses to an SA4 candidate.

This module validates only the supplied JSON shape and the observed pagination
chain. It does not authenticate a response, verify its terminal commit, prove
history completeness, or qualify a repository transition.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType

from community_model import ValidationError
from community_model.identifiers import validate_did, validate_tid

from .compat import (
    ALPHA_LABEL,
    INCREMENTAL_ENDPOINT,
    SA5_ACQUISITION_METHOD,
    SA5_ADAPTER_VERSION,
)
from .model import SpaceIdentity
from .qualification import QualifiedRepoState, RepoOperation, RepoTransition


def _fail(reason: str, message: str) -> None:
    raise ValidationError(reason, message)


def _nonempty(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or any(ch.isspace() for ch in value):
        _fail("spaces_operation_response_invalid", f"{field} must be nonempty")
    return value


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        _fail(
            "spaces_operation_response_invalid",
            "response acquisition time must be timezone-aware",
        )
    return value.astimezone(UTC)


def _json_sha256(value: object, *, field: str) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "spaces_operation_response_invalid",
            f"{field} must be deterministic JSON data",
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


class OperationAcquisitionStatus(StrEnum):
    TRANSITION_CANDIDATE = "transition_candidate"
    EMPTY_TERMINAL_PAGE = "empty_terminal_page"
    PARTIAL_RETRIEVAL = "partial_retrieval"


class ObservedOperationClaim(StrEnum):
    RESPONSE_SHAPE = "pinned_listRepoOps_response_shape"
    PAGE_ORDER = "supplied_page_order_preserved"
    CURSOR_CHAIN = "observed_cursor_chain"
    OPERATION_ORDER = "supplied_operation_order_preserved"
    CANDIDATE_CONSTRUCTION = "sa4_transition_candidate_constructed"


@dataclass(frozen=True, slots=True)
class OperationSourceContext:
    space: SpaceIdentity
    repo_did: str
    repo_host: str
    source_ref: str
    acquired_at: datetime
    endpoint: str = field(default=INCREMENTAL_ENDPOINT, init=False)
    trust_classification: str = field(
        default="caller_supplied_unverified_context", init=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.space, SpaceIdentity):
            _fail("spaces_operation_response_invalid", "Space identity is required")
        validate_did(self.repo_did)
        if (
            not isinstance(self.repo_host, str)
            or not self.repo_host.startswith("https://")
            or any(ch.isspace() for ch in self.repo_host)
        ):
            _fail(
                "spaces_operation_response_invalid",
                "repo host must be an HTTPS URL",
            )
        object.__setattr__(self, "repo_host", self.repo_host.rstrip("/"))
        _nonempty(self.source_ref, field="source reference")
        object.__setattr__(self, "acquired_at", _utc(self.acquired_at))

    def to_provenance(self) -> MappingProxyType[str, object]:
        return MappingProxyType(
            {
                "space": self.space.uri,
                "repoDid": self.repo_did,
                "repoHost": self.repo_host,
                "endpoint": self.endpoint,
                "sourceRef": self.source_ref,
                "acquiredAt": self.acquired_at.isoformat(),
                "trustClassification": self.trust_classification,
                "sourceAuthenticated": False,
                "authorityConferred": False,
            }
        )


@dataclass(frozen=True, slots=True)
class ListRepoOpsPage:
    ordinal: int
    request_since: str
    request_cursor: str | None
    response_cursor: str | None
    operations: tuple[RepoOperation, ...]
    value_presence: tuple[bool, ...]
    terminal_commit_sha256: str | None
    received_at: datetime

    def __post_init__(self) -> None:
        if (
            isinstance(self.ordinal, bool)
            or not isinstance(self.ordinal, int)
            or self.ordinal < 0
        ):
            _fail("spaces_operation_response_invalid", "page ordinal is invalid")
        validate_tid(self.request_since)
        for name, value in (
            ("request cursor", self.request_cursor),
            ("response cursor", self.response_cursor),
        ):
            if value is not None:
                _nonempty(value, field=name)
        if not isinstance(self.operations, tuple) or any(
            not isinstance(operation, RepoOperation) for operation in self.operations
        ):
            _fail(
                "spaces_operation_response_invalid",
                "page operations have an invalid shape",
            )
        if (
            not isinstance(self.value_presence, tuple)
            or len(self.value_presence) != len(self.operations)
            or any(not isinstance(item, bool) for item in self.value_presence)
        ):
            _fail(
                "spaces_operation_response_invalid",
                "operation value-presence metadata is invalid",
            )
        if self.terminal_commit_sha256 is not None and (
            len(self.terminal_commit_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in self.terminal_commit_sha256)
        ):
            _fail(
                "spaces_operation_response_invalid",
                "terminal response commit digest is invalid",
            )
        if self.response_cursor is not None and self.terminal_commit_sha256 is not None:
            _fail(
                "spaces_operation_response_invalid",
                "a page cannot be both paginated and terminal",
            )
        if self.response_cursor is None and self.terminal_commit_sha256 is None:
            _fail(
                "spaces_operation_response_invalid",
                "a terminal page must carry the pinned response commit",
            )
        if not self.operations and self.response_cursor is not None:
            _fail(
                "spaces_operation_response_invalid",
                "an empty page cannot advance a cursor",
            )
        object.__setattr__(self, "received_at", _utc(self.received_at))


def parse_list_repo_ops_page(
    response: Mapping[str, object],
    *,
    ordinal: int,
    request_since: str,
    request_cursor: str | None,
    received_at: datetime,
) -> ListRepoOpsPage:
    """Parse one exact pinned-alpha response without trusting its contents."""

    if (
        not isinstance(response, Mapping)
        or not set(response).issubset({"ops", "commit", "cursor"})
        or "ops" not in response
    ):
        _fail(
            "spaces_operation_response_invalid",
            "listRepoOps response fields do not match the pinned alpha",
        )
    raw_ops = response["ops"]
    if not isinstance(raw_ops, Sequence) or isinstance(raw_ops, str | bytes):
        _fail("spaces_operation_response_invalid", "ops must be an array")
    operations: list[RepoOperation] = []
    value_presence: list[bool] = []
    for raw in raw_ops:
        if (
            not isinstance(raw, Mapping)
            or not {"rev", "collection", "rkey", "cid", "prev"}.issubset(raw)
            or not set(raw).issubset(
                {"rev", "collection", "rkey", "cid", "prev", "value"}
            )
        ):
            _fail(
                "spaces_operation_response_invalid",
                "operation fields do not match the pinned alpha",
            )
        cid = raw["cid"]
        prev = raw["prev"]
        if cid is not None and not isinstance(cid, str):
            _fail("spaces_operation_response_invalid", "operation cid is invalid")
        if prev is not None and not isinstance(prev, str):
            _fail("spaces_operation_response_invalid", "operation prev is invalid")
        try:
            operation = RepoOperation(
                rev=str(raw["rev"]),
                collection=str(raw["collection"]),
                rkey=str(raw["rkey"]),
                cid=cid,
                prev=prev,
            )
        except ValidationError as exc:
            raise ValidationError(
                "spaces_operation_response_invalid",
                "operation identifiers are invalid",
            ) from exc
        operations.append(operation)
        value_presence.append("value" in raw)
    cursor = response.get("cursor")
    if cursor is not None and not isinstance(cursor, str):
        _fail("spaces_operation_response_invalid", "response cursor is invalid")
    commit = response.get("commit")
    if commit is not None and not isinstance(commit, Mapping):
        _fail(
            "spaces_operation_response_invalid",
            "terminal response commit must be a JSON object",
        )
    return ListRepoOpsPage(
        ordinal=ordinal,
        request_since=request_since,
        request_cursor=request_cursor,
        response_cursor=cursor,
        operations=tuple(operations),
        value_presence=tuple(value_presence),
        terminal_commit_sha256=(
            _json_sha256(commit, field="terminal response commit")
            if commit is not None
            else None
        ),
        received_at=received_at,
    )


@dataclass(frozen=True, slots=True)
class OperationAcquisitionResult:
    context: OperationSourceContext
    pages: tuple[ListRepoOpsPage, ...]
    status: OperationAcquisitionStatus
    transition: RepoTransition | None
    ordered_operation_sha256: str | None
    verified_claims: frozenset[ObservedOperationClaim]
    protocol_assumption: str = field(default=ALPHA_LABEL, init=False)
    adapter_method: str = field(default=SA5_ACQUISITION_METHOD, init=False)
    adapter_version: str = field(default=SA5_ADAPTER_VERSION, init=False)
    pagination_chain_closed: bool = False
    complete_history: bool = False
    authenticated_history: bool = False
    source_authority: bool = False
    authorization: bool = False
    governance_authority: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.context, OperationSourceContext) or not self.pages:
            _fail(
                "spaces_operation_acquisition_invalid", "source and pages are required"
            )
        if self.status is OperationAcquisitionStatus.TRANSITION_CANDIDATE:
            if self.transition is None or not self.pagination_chain_closed:
                _fail(
                    "spaces_operation_acquisition_invalid",
                    "candidate status requires a closed chain and transition",
                )
            if (
                ObservedOperationClaim.CANDIDATE_CONSTRUCTION
                not in self.verified_claims
            ):
                _fail(
                    "spaces_operation_acquisition_invalid",
                    "candidate claim is missing",
                )
        elif self.transition is not None:
            _fail(
                "spaces_operation_acquisition_invalid",
                "non-candidate acquisition cannot carry a transition",
            )
        if any(
            (
                self.complete_history,
                self.authenticated_history,
                self.source_authority,
                self.authorization,
                self.governance_authority,
            )
        ):
            _fail(
                "spaces_operation_acquisition_invalid",
                "operation acquisition cannot confer history or authority",
            )

    def to_provenance(self) -> MappingProxyType[str, object]:
        return MappingProxyType(
            {
                "status": self.status.value,
                "protocolAssumption": self.protocol_assumption,
                "adapterMethod": self.adapter_method,
                "adapterVersion": self.adapter_version,
                "source": self.context.to_provenance(),
                "pageCount": len(self.pages),
                "operationCount": sum(len(page.operations) for page in self.pages),
                "pageOrder": tuple(page.ordinal for page in self.pages),
                "orderedOperationSha256": self.ordered_operation_sha256,
                "terminalCommitSha256": self.pages[-1].terminal_commit_sha256,
                "paginationChainClosed": self.pagination_chain_closed,
                "verifiedClaims": tuple(
                    sorted(claim.value for claim in self.verified_claims)
                ),
                "completeHistory": False,
                "authenticatedHistory": False,
                "sourceAuthority": False,
                "authorization": False,
                "governanceAuthority": False,
            }
        )


def _operation_digest(operations: tuple[RepoOperation, ...]) -> str:
    fields = [
        "\x00".join(
            (
                str(ordinal),
                operation.rev,
                operation.collection,
                operation.rkey,
                operation.cid or "-",
                operation.prev or "-",
            )
        )
        for ordinal, operation in enumerate(operations)
    ]
    return hashlib.sha256("\x00".join(fields).encode("utf-8")).hexdigest()


def acquire_repo_transition_candidate(
    pages: Sequence[ListRepoOpsPage],
    *,
    source_state: QualifiedRepoState,
    context: OperationSourceContext,
) -> OperationAcquisitionResult:
    """Construct an SA4 candidate from one observed, ordered page sequence."""

    if not isinstance(source_state, QualifiedRepoState):
        _fail(
            "spaces_operation_acquisition_invalid",
            "an SA1-qualified source state is required",
        )
    if not isinstance(context, OperationSourceContext):
        _fail("spaces_operation_acquisition_invalid", "source context is required")
    if (
        source_state.space != context.space
        or source_state.author_did != context.repo_did
    ):
        _fail(
            "spaces_operation_source_mismatch",
            "operation context does not match the qualified source state",
        )
    if not isinstance(pages, Sequence) or isinstance(pages, str | bytes) or not pages:
        _fail("spaces_operation_acquisition_invalid", "at least one page is required")
    supplied = tuple(pages)
    if any(not isinstance(page, ListRepoOpsPage) for page in supplied):
        _fail("spaces_operation_acquisition_invalid", "page shape is invalid")
    if tuple(page.ordinal for page in supplied) != tuple(range(len(supplied))):
        _fail(
            "spaces_operation_page_order_invalid",
            "pages must remain in supplied contiguous order",
        )
    if supplied[0].request_cursor is not None:
        _fail(
            "spaces_operation_cursor_mismatch",
            "the first observed page must begin without a pagination cursor",
        )
    if any(page.request_since != source_state.commit.rev for page in supplied):
        _fail(
            "spaces_operation_source_mismatch",
            "every page must retain the qualified source revision as since",
        )
    for previous, current in zip(supplied, supplied[1:], strict=False):
        if previous.response_cursor is None or (
            current.request_cursor != previous.response_cursor
        ):
            _fail(
                "spaces_operation_cursor_mismatch",
                "observed page requests do not follow response cursors",
            )
    operations = tuple(operation for page in supplied for operation in page.operations)
    identities = [
        (
            operation.rev,
            operation.collection,
            operation.rkey,
            operation.cid,
            operation.prev,
        )
        for operation in operations
    ]
    if len(identities) != len(set(identities)):
        _fail(
            "spaces_operation_duplicate",
            "duplicate operation identity is ambiguous and is not deduplicated",
        )

    closed = supplied[-1].response_cursor is None
    base_claims = frozenset(
        {
            ObservedOperationClaim.RESPONSE_SHAPE,
            ObservedOperationClaim.PAGE_ORDER,
            ObservedOperationClaim.OPERATION_ORDER,
        }
    )
    if not closed:
        return OperationAcquisitionResult(
            context=context,
            pages=supplied,
            status=OperationAcquisitionStatus.PARTIAL_RETRIEVAL,
            transition=None,
            ordered_operation_sha256=(
                _operation_digest(operations) if operations else None
            ),
            verified_claims=base_claims,
            pagination_chain_closed=False,
        )
    closed_claims = base_claims | {ObservedOperationClaim.CURSOR_CHAIN}
    if not operations:
        return OperationAcquisitionResult(
            context=context,
            pages=supplied,
            status=OperationAcquisitionStatus.EMPTY_TERMINAL_PAGE,
            transition=None,
            ordered_operation_sha256=None,
            verified_claims=closed_claims,
            pagination_chain_closed=True,
        )
    prior_index = {
        f"{record.identity.collection}/{record.identity.rkey}": record.cid
        for record in source_state.records
    }
    transition = RepoTransition(
        prior_rev=source_state.commit.rev,
        prior_state=source_state.lthash_state,
        prior_index=prior_index,
        operations=operations,
    )
    return OperationAcquisitionResult(
        context=context,
        pages=supplied,
        status=OperationAcquisitionStatus.TRANSITION_CANDIDATE,
        transition=transition,
        ordered_operation_sha256=_operation_digest(operations),
        verified_claims=closed_claims | {ObservedOperationClaim.CANDIDATE_CONSTRUCTION},
        pagination_chain_closed=True,
    )


__all__ = [
    "ListRepoOpsPage",
    "ObservedOperationClaim",
    "OperationAcquisitionResult",
    "OperationAcquisitionStatus",
    "OperationSourceContext",
    "acquire_repo_transition_candidate",
    "parse_list_repo_ops_page",
]
