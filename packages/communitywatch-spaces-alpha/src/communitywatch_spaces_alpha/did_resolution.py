"""Method-preserving SA9c output boundary for exact DID-document bytes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from community_model import ValidationError
from community_model.identifiers import validate_did

from .compat import (
    SA9C_AUTHORITY_DOCTRINE,
    SA9C_RESOLUTION_DOCTRINE,
)
from .did_binding import DidDocumentInput, DidDocumentProvenanceKind


class DidResolutionMethod(StrEnum):
    WEB = "did:web"
    PLC = "did:plc"


class DidResolutionProvenance(StrEnum):
    WEBPKI_HTTPS = "webpki_https_acquisition"
    DEVELOPMENT_LOOPBACK = "development_loopback_acquisition"
    PLC_OPERATION_HISTORY = "plc_operation_history"


RESOLUTION_NON_CLAIMS = frozenset(
    {
        "governance_authority",
        "standing",
        "authorization",
        "artifact_validity",
        "perpetual_control",
        "globally_current_state",
    }
)


def _fail(reason: str, message: str) -> None:
    raise ValidationError(reason, message)


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        _fail("spaces_did_resolution_invalid", "resolution time must be aware")
    return value.astimezone(UTC)


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True, slots=True)
class ResolvedDidDocument:
    """Exact document bytes plus non-interchangeable method provenance."""

    expected_did: str
    document_bytes: bytes
    document_sha256: str
    method: DidResolutionMethod
    method_receipt_id: str
    provenance: DidResolutionProvenance
    verified_claims: frozenset[str]
    observed_at: datetime
    explicit_non_claims: frozenset[str] = field(default=RESOLUTION_NON_CLAIMS)
    doctrine: str = field(default=SA9C_RESOLUTION_DOCTRINE, init=False)
    authority_doctrine: str = field(default=SA9C_AUTHORITY_DOCTRINE, init=False)
    governance_authority: bool = False
    standing: bool = False
    authorization: bool = False
    globally_current: bool = False

    def __post_init__(self) -> None:
        validate_did(self.expected_did)
        expected_prefix = f"{self.method.value}:"
        if not self.expected_did.startswith(expected_prefix):
            _fail(
                "spaces_did_resolution_method_mismatch",
                "document DID and resolution method differ",
            )
        if not isinstance(self.document_bytes, bytes) or not self.document_bytes:
            _fail("spaces_did_resolution_invalid", "document bytes are required")
        if self.document_sha256 != _digest(self.document_bytes):
            _fail(
                "spaces_did_resolution_document_mismatch",
                "document digest does not bind the exact bytes",
            )
        if (
            not isinstance(self.method_receipt_id, str)
            or not self.method_receipt_id.startswith("sha256:")
            or len(self.method_receipt_id) != 71
        ):
            _fail("spaces_did_resolution_invalid", "method receipt id is invalid")
        allowed_provenance = {
            DidResolutionMethod.WEB: {
                DidResolutionProvenance.WEBPKI_HTTPS,
                DidResolutionProvenance.DEVELOPMENT_LOOPBACK,
            },
            DidResolutionMethod.PLC: {DidResolutionProvenance.PLC_OPERATION_HISTORY},
        }
        if self.provenance not in allowed_provenance[self.method]:
            _fail(
                "spaces_did_resolution_method_mismatch",
                "method-specific provenance cannot be interchanged",
            )
        if not isinstance(self.verified_claims, frozenset) or not all(
            isinstance(claim, str) and claim for claim in self.verified_claims
        ):
            _fail("spaces_did_resolution_invalid", "verified claims are invalid")
        if self.explicit_non_claims != RESOLUTION_NON_CLAIMS:
            _fail("spaces_did_resolution_invalid", "non-claims may not be relabeled")
        object.__setattr__(self, "observed_at", _utc(self.observed_at))
        if any(
            (
                self.governance_authority,
                self.standing,
                self.authorization,
                self.globally_current,
            )
        ):
            _fail(
                "spaces_did_resolution_invalid",
                "resolution provenance cannot confer authority or currentness",
            )

    def to_sa9b_input(self) -> DidDocumentInput:
        """Pass the exact bytes to SA9b while retaining this receipt identity."""

        return DidDocumentInput(
            expected_did=self.expected_did,
            document_bytes=self.document_bytes,
            provenance_kind=(DidDocumentProvenanceKind.FUTURE_VERIFIED_DID_RESOLUTION),
            provenance_ref=self.method_receipt_id,
            media_type="application/did+ld+json",
            allow_insecure_loopback_fixture=(
                self.provenance is DidResolutionProvenance.DEVELOPMENT_LOOPBACK
            ),
        )


def require_resolution_method(
    resolved: ResolvedDidDocument, method: DidResolutionMethod
) -> None:
    if resolved.method is not method:
        _fail(
            "spaces_did_resolution_method_mismatch",
            "resolution receipt uses a different DID method",
        )


def require_resolved_document_binding(
    resolved: ResolvedDidDocument, document_bytes: bytes
) -> None:
    if not isinstance(document_bytes, bytes) or _digest(document_bytes) != (
        resolved.document_sha256
    ):
        _fail(
            "spaces_did_resolution_document_mismatch",
            "document no longer matches the resolution receipt",
        )


__all__ = [
    "DidResolutionMethod",
    "DidResolutionProvenance",
    "RESOLUTION_NON_CLAIMS",
    "ResolvedDidDocument",
    "require_resolution_method",
    "require_resolved_document_binding",
]
