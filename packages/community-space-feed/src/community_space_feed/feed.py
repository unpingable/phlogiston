"""Deterministic local publication envelope for M5A artifacts.

This module performs no I/O. It preserves exact artifact bytes and bounded
publication context; it does not authenticate a publisher or a reader.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable

from community_space_artifact import DisclosureMode, ProjectionArtifact

FEED_VERSION: Final = "scv0-public-projection-feed/1"

_SHA256_RE: Final = re.compile(r"sha256:[0-9a-f]{64}")

_CLAIMS: Final = (
    "artifact_integrity_checked",
    "channel_matches_disclosure_mode",
    "exact_artifact_embedded",
)

_NON_CLAIMS: Final = (
    "publisher_authority",
    "reader_authentication",
    "reader_authorization",
    "membership",
    "moderator_authority",
    "source_truth",
    "source_ownership",
    "repository_currentness",
    "governance_authority",
)


def _sha(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a sha256 identifier")
    return value


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _time(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("published_at must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("published_at must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("published_at must include an offset")
    normalized = parsed.astimezone(UTC).isoformat(timespec="seconds")
    return normalized.replace("+00:00", "Z")


class PublicProjectionChannel(StrEnum):
    ORDINARY = "public_ordinary"
    TECHNICAL_AUDIT = "public_technical_audit"


_CHANNEL_MODE: Final = {
    PublicProjectionChannel.ORDINARY: DisclosureMode.ORDINARY,
    PublicProjectionChannel.TECHNICAL_AUDIT: DisclosureMode.TECHNICAL_AUDIT,
}


@dataclass(frozen=True, slots=True)
class FeedPublicationRequest:
    artifact: ProjectionArtifact | object
    expected_artifact_id: str
    expected_community_identity_id: str
    expected_publication_reference_id: str
    channel: PublicProjectionChannel | str
    published_at: str

    def __post_init__(self) -> None:
        _sha(self.expected_artifact_id, field="expected_artifact_id")
        _sha(
            self.expected_community_identity_id,
            field="expected_community_identity_id",
        )
        _sha(
            self.expected_publication_reference_id,
            field="expected_publication_reference_id",
        )
        try:
            channel = PublicProjectionChannel(self.channel)
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported public projection channel") from exc
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "published_at", _time(self.published_at))


@dataclass(frozen=True, slots=True)
class PublishedProjectionFeed:
    artifact: ProjectionArtifact
    artifact_id: str
    artifact_bytes_sha256: str
    community_identity_id: str
    publication_reference_id: str
    channel: PublicProjectionChannel
    disclosure_mode: str
    published_at: str
    verified_claims: tuple[str, ...] = _CLAIMS
    explicit_non_claims: tuple[str, ...] = _NON_CLAIMS
    feed_version: str = FEED_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.artifact, ProjectionArtifact):
            raise TypeError("published feed requires a typed ProjectionArtifact")
        if self.feed_version != FEED_VERSION:
            raise ValueError("unsupported feed version")
        _sha(self.artifact_id, field="artifact_id")
        _sha(self.artifact_bytes_sha256, field="artifact_bytes_sha256")
        _sha(self.community_identity_id, field="community_identity_id")
        _sha(self.publication_reference_id, field="publication_reference_id")
        try:
            channel = PublicProjectionChannel(self.channel)
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported public projection channel") from exc
        object.__setattr__(self, "channel", channel)
        if self.verified_claims != _CLAIMS or self.explicit_non_claims != _NON_CLAIMS:
            raise ValueError("feed claims and non-claims are fixed")
        object.__setattr__(self, "published_at", _time(self.published_at))
        self._validate_binding()

    @property
    def artifact_bytes(self) -> bytes:
        return _canonical_bytes(self.artifact.to_payload())

    @property
    def entries(self):
        return self.artifact.entries

    @property
    def feed_id(self) -> str:
        return _digest(self.to_bytes())

    def _validate_binding(self) -> None:
        self.artifact.validate_integrity()
        if self.artifact.artifact_id != self.artifact_id:
            raise ValueError("published artifact identity mismatch")
        if _digest(self.artifact_bytes) != self.artifact_bytes_sha256:
            raise ValueError("published artifact bytes mismatch")
        if self.artifact.community_identity_id != self.community_identity_id:
            raise ValueError("published artifact community mismatch")
        if self.artifact.publication_reference_id != self.publication_reference_id:
            raise ValueError("published artifact publication reference mismatch")
        if _CHANNEL_MODE[self.channel] != self.artifact.disclosure_mode:
            raise ValueError("public channel and artifact disclosure mode mismatch")
        if self.disclosure_mode != str(self.artifact.disclosure_mode):
            raise ValueError("published disclosure mode mismatch")

    def validate_integrity(self) -> str:
        self.__post_init__()
        return self.feed_id

    def to_payload(self) -> dict[str, object]:
        return {
            "feedVersion": self.feed_version,
            "artifactId": self.artifact_id,
            "artifactBytesSha256": self.artifact_bytes_sha256,
            "communityIdentityId": self.community_identity_id,
            "publicationReferenceId": self.publication_reference_id,
            "channel": self.channel,
            "disclosureMode": self.disclosure_mode,
            "publishedAt": self.published_at,
            "artifact": self.artifact.to_payload(),
            "verifiedClaims": self.verified_claims,
            "explicitNonClaims": self.explicit_non_claims,
        }

    def to_bytes(self) -> bytes:
        return _canonical_bytes(self.to_payload())


@runtime_checkable
class ProjectionFeedPublisher(Protocol):
    def publish(self, request: FeedPublicationRequest) -> PublishedProjectionFeed: ...


class LocalProjectionFeedBoundary:
    """Pure fixture publisher; deliberately has no source or network method."""

    def publish(self, request: FeedPublicationRequest) -> PublishedProjectionFeed:
        if not isinstance(request, FeedPublicationRequest):
            raise TypeError("feed boundary requires a typed publication request")
        request.__post_init__()
        artifact = request.artifact
        if not isinstance(artifact, ProjectionArtifact):
            raise TypeError("feed boundary accepts only a ProjectionArtifact")
        artifact.validate_integrity()
        if artifact.artifact_id != request.expected_artifact_id:
            raise ValueError("publication request artifact identity mismatch")
        if artifact.community_identity_id != request.expected_community_identity_id:
            raise ValueError("publication request community mismatch")
        if (
            artifact.publication_reference_id
            != request.expected_publication_reference_id
        ):
            raise ValueError("publication request reference mismatch")
        if _CHANNEL_MODE[request.channel] != artifact.disclosure_mode:
            raise ValueError("public channel and artifact disclosure mode mismatch")
        artifact_bytes = _canonical_bytes(artifact.to_payload())
        return PublishedProjectionFeed(
            artifact=artifact,
            artifact_id=artifact.artifact_id,
            artifact_bytes_sha256=_digest(artifact_bytes),
            community_identity_id=artifact.community_identity_id,
            publication_reference_id=artifact.publication_reference_id,
            channel=request.channel,
            disclosure_mode=str(artifact.disclosure_mode),
            published_at=request.published_at,
        )


def refuse_feed_claim_upgrade(labels: object) -> None:
    """Public disclosure cannot become authentication or authority."""

    if not isinstance(labels, dict) or any(not isinstance(key, str) for key in labels):
        raise TypeError("feed claim labels must be an object with string keys")
    if labels:
        raise ValueError(
            "feed publication cannot add authorization or authority claims"
        )
