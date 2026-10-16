"""SA7 interface-only seam for future Spaces artifact providers.

No transport implementation, authentication, credential, or network trust is
provided here. The artifacts only carry bytes/pages plus caller-supplied source
context to the existing SA2 and SA5 boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Protocol

from community_model import ValidationError
from community_model.identifiers import validate_did, validate_tid

from .compat import (
    FULL_REPO_ENDPOINT,
    INCREMENTAL_ENDPOINT,
    SA7_TRANSPORT_BOUNDARY_VERSION,
)
from .model import SpaceIdentity
from .operations import ListRepoOpsPage


def _fail(message: str) -> None:
    raise ValidationError("spaces_transport_boundary_invalid", message)


def _nonempty(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or any(ch.isspace() for ch in value):
        _fail(f"{field_name} must be nonempty")
    return value


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        _fail("artifact observation time must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ArtifactRequestIdentity:
    request_id: str
    space: SpaceIdentity
    repo_did: str

    def __post_init__(self) -> None:
        _nonempty(self.request_id, field_name="request id")
        if not isinstance(self.space, SpaceIdentity):
            _fail("request Space identity is required")
        validate_did(self.repo_did)


@dataclass(frozen=True, slots=True)
class FullRepoArtifactRequest:
    identity: ArtifactRequestIdentity
    endpoint: str = field(default=FULL_REPO_ENDPOINT, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ArtifactRequestIdentity):
            _fail("full-repo request identity is invalid")


@dataclass(frozen=True, slots=True)
class RepoOpsArtifactRequest:
    identity: ArtifactRequestIdentity
    since: str
    cursor: str | None = None
    limit: int = 100
    exclude_values: bool = True
    endpoint: str = field(default=INCREMENTAL_ENDPOINT, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ArtifactRequestIdentity):
            _fail("operation request identity is invalid")
        validate_tid(self.since)
        if self.cursor is not None:
            _nonempty(self.cursor, field_name="cursor")
        if (
            isinstance(self.limit, bool)
            or not isinstance(self.limit, int)
            or not 1 <= self.limit <= 1000
        ):
            _fail("operation request limit is outside the pinned alpha bounds")
        if not isinstance(self.exclude_values, bool):
            _fail("exclude_values must be boolean")


@dataclass(frozen=True, slots=True)
class TransportSourceContext:
    transport_name: str
    source_endpoint: str
    artifact_ref: str
    observed_at: datetime
    asserted_transport_security: str | None = None
    asserted_service_identity: str | None = None
    trust_classification: str = field(
        default="caller_supplied_unverified_transport_context", init=False
    )
    boundary_version: str = field(default=SA7_TRANSPORT_BOUNDARY_VERSION, init=False)
    credential_material_present: bool = False
    service_authenticated: bool = False
    authority_conferred: bool = False

    def __post_init__(self) -> None:
        _nonempty(self.transport_name, field_name="transport name")
        if (
            not isinstance(self.source_endpoint, str)
            or not self.source_endpoint.startswith("https://")
            or any(ch.isspace() for ch in self.source_endpoint)
        ):
            _fail("source endpoint must be an HTTPS URL")
        object.__setattr__(self, "source_endpoint", self.source_endpoint.rstrip("/"))
        _nonempty(self.artifact_ref, field_name="artifact reference")
        object.__setattr__(self, "observed_at", _utc(self.observed_at))
        for field_name in (
            "asserted_transport_security",
            "asserted_service_identity",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _nonempty(value, field_name=field_name)
        if any(
            (
                self.credential_material_present,
                self.service_authenticated,
                self.authority_conferred,
            )
        ):
            _fail("SA7 source context cannot claim credentials, trust, or authority")

    def to_provenance(self) -> MappingProxyType[str, object]:
        return MappingProxyType(
            {
                "transportName": self.transport_name,
                "sourceEndpoint": self.source_endpoint,
                "artifactRef": self.artifact_ref,
                "observedAt": self.observed_at.isoformat(),
                "assertedTransportSecurity": self.asserted_transport_security,
                "assertedServiceIdentity": self.asserted_service_identity,
                "trustClassification": self.trust_classification,
                "boundaryVersion": self.boundary_version,
                "credentialMaterialPresent": False,
                "serviceAuthenticated": False,
                "authorityConferred": False,
            }
        )


@dataclass(frozen=True, slots=True)
class ObservedCarArtifact:
    request: FullRepoArtifactRequest
    source: TransportSourceContext
    car_bytes: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.request, FullRepoArtifactRequest) or not isinstance(
            self.source, TransportSourceContext
        ):
            _fail("CAR artifact request or source is invalid")
        if not isinstance(self.car_bytes, bytes) or not self.car_bytes:
            _fail("CAR artifact bytes are required")

    def sa2_input(self) -> bytes:
        """Return exact bytes; this method establishes no CAR or trust claim."""

        return self.car_bytes


@dataclass(frozen=True, slots=True)
class ObservedRepoOpsArtifact:
    request: RepoOpsArtifactRequest
    source: TransportSourceContext
    pages: tuple[ListRepoOpsPage, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.request, RepoOpsArtifactRequest) or not isinstance(
            self.source, TransportSourceContext
        ):
            _fail("operation artifact request or source is invalid")
        if (
            not isinstance(self.pages, tuple)
            or not self.pages
            or any(not isinstance(page, ListRepoOpsPage) for page in self.pages)
        ):
            _fail("operation artifact pages are invalid")
        first = self.pages[0]
        if first.request_since != self.request.since or (
            first.request_cursor != self.request.cursor
        ):
            _fail("artifact pages do not match the explicit operation request")

    def sa5_input(self) -> tuple[ListRepoOpsPage, ...]:
        """Return exact pages; this method establishes no response trust claim."""

        return self.pages


class SpaceArtifactTransport(Protocol):
    """Future provider contract. SA7 supplies deliberately no implementation."""

    def get_repo(self, request: FullRepoArtifactRequest) -> ObservedCarArtifact: ...

    def list_repo_ops(
        self, request: RepoOpsArtifactRequest
    ) -> ObservedRepoOpsArtifact: ...


__all__ = [
    "ArtifactRequestIdentity",
    "FullRepoArtifactRequest",
    "ObservedCarArtifact",
    "ObservedRepoOpsArtifact",
    "RepoOpsArtifactRequest",
    "SpaceArtifactTransport",
    "TransportSourceContext",
]
