"""Bounded Juniper Spaces-alpha authority operations.

This module owns community admission/removal construction.  It has no observer
store and accepts no credential value: the writer and credential provider stay
behind communityd ports.  Every local authorization occurrence is consumed
before its one exact writer attempt, so it cannot be replayed for another or
even an identical operation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from community_model import (
    AuthorizationError,
    ValidationError,
)
from community_model.canonical import validate_sha256
from community_model.identifiers import format_rfc3339
from community_space_model import (
    AuthorizedAction,
    CommunityIdentity,
    ExactSpaceRecordReference,
    ModeratorAuthorization,
    SpaceIdentity,
)
from community_space_wire import ADMISSION_COLLECTION, REMOVAL_COLLECTION

from .ports import AdminAuthorizer, CredentialProvider


@runtime_checkable
class SpacesAlphaAuthorityWriter(Protocol):
    def create_immutable(
        self,
        *,
        space_uri: str,
        repo_did: str,
        collection: str,
        rkey: str,
        record: Mapping[str, object],
    ) -> SpacesAlphaWriteOutcome: ...


@dataclass(frozen=True, slots=True)
class SpacesAlphaWriteOutcome:
    uri: str
    cid: str
    created: bool


@runtime_checkable
class AuthorizationOccurrenceStore(Protocol):
    def consume(self, authorization_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class SpacesAlphaPorts:
    authorizer: AdminAuthorizer
    credentials: CredentialProvider
    writer: SpacesAlphaAuthorityWriter
    occurrences: AuthorizationOccurrenceStore


@dataclass(frozen=True, slots=True)
class SpacesAlphaAuthorityConfig:
    space: SpaceIdentity
    community_actor_did: str
    administrator_did: str
    credential_ref: str

    @property
    def community(self) -> CommunityIdentity:
        return CommunityIdentity(self.space, self.community_actor_did)


@dataclass(frozen=True, slots=True)
class AdmitOccurrence:
    submission: ExactSpaceRecordReference
    subject: ExactSpaceRecordReference
    submission_occurrence_id: str
    source_observation_receipt_id: str
    decision_id: str
    authorization_basis_receipt_id: str
    authorization_provenance_receipt_id: str
    authorized_at: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class RemoveOccurrence:
    admission: ExactSpaceRecordReference
    subject: ExactSpaceRecordReference
    admission_occurrence_id: str
    reason: str
    decision_id: str
    authorization_basis_receipt_id: str
    authorization_provenance_receipt_id: str
    authorized_at: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class SpacesAlphaOutcome:
    record: ExactSpaceRecordReference
    authorization: ModeratorAuthorization


def admit_space(
    ports: SpacesAlphaPorts,
    config: SpacesAlphaAuthorityConfig,
    occurrence: AdmitOccurrence,
    *,
    now: datetime,
) -> SpacesAlphaOutcome:
    authorization = _authorize(
        ports,
        config,
        action=AuthorizedAction.ADMIT,
        occurrence_id=_receipt(
            occurrence.submission_occurrence_id, field="submission occurrence"
        ),
        decision_id=occurrence.decision_id,
        basis=occurrence.authorization_basis_receipt_id,
        provenance=occurrence.authorization_provenance_receipt_id,
        authorized_at=occurrence.authorized_at,
        expires_at=occurrence.expires_at,
        now=now,
    )
    _same_space_author(occurrence.submission, occurrence.subject)
    source_receipt = _receipt(
        occurrence.source_observation_receipt_id, field="source observation"
    )
    record = {
        "$type": ADMISSION_COLLECTION,
        "submission": _strong_ref(occurrence.submission),
        "subject": _strong_ref(occurrence.subject),
        "authorizationOccurrence": authorization.authorization_id,
        "sourceObservationReceipt": source_receipt,
        "createdAt": format_rfc3339(now),
    }
    return _write(
        ports,
        config,
        authorization,
        collection=ADMISSION_COLLECTION,
        record=record,
    )


def remove_space(
    ports: SpacesAlphaPorts,
    config: SpacesAlphaAuthorityConfig,
    occurrence: RemoveOccurrence,
    *,
    now: datetime,
) -> SpacesAlphaOutcome:
    authorization = _authorize(
        ports,
        config,
        action=AuthorizedAction.REMOVE,
        occurrence_id=_receipt(
            occurrence.admission_occurrence_id, field="admission occurrence"
        ),
        decision_id=occurrence.decision_id,
        basis=occurrence.authorization_basis_receipt_id,
        provenance=occurrence.authorization_provenance_receipt_id,
        authorized_at=occurrence.authorized_at,
        expires_at=occurrence.expires_at,
        now=now,
    )
    if (
        occurrence.admission.space != config.space
        or occurrence.subject.space != config.space
    ):
        raise ValidationError(
            "space_binding_mismatch", "removal references another Space"
        )
    reason = occurrence.reason.strip()
    if not reason or "\x00" in reason:
        raise ValidationError("removal_reason_invalid", "removal reason is required")
    record = {
        "$type": REMOVAL_COLLECTION,
        "admission": _strong_ref(occurrence.admission),
        "subject": _strong_ref(occurrence.subject),
        "authorizationOccurrence": authorization.authorization_id,
        "reason": reason,
        "createdAt": format_rfc3339(now),
    }
    return _write(
        ports,
        config,
        authorization,
        collection=REMOVAL_COLLECTION,
        record=record,
    )


def _authorize(
    ports: SpacesAlphaPorts,
    config: SpacesAlphaAuthorityConfig,
    *,
    action: AuthorizedAction,
    occurrence_id: str,
    decision_id: str,
    basis: str,
    provenance: str,
    authorized_at: str,
    expires_at: str,
    now: datetime,
) -> ModeratorAuthorization:
    admin = ports.authorizer.require(action.value)  # type: ignore[arg-type]
    if admin.did != config.administrator_did:
        raise AuthorizationError("authorizer returned another administrator")
    ports.credentials.require(config.credential_ref)
    authorization = ModeratorAuthorization(
        community=config.community,
        decision_id=decision_id,
        moderator_did=admin.did,
        action=action,
        target_occurrence_id=occurrence_id,
        authorization_basis_receipt_id=_receipt(basis, field="authorization basis"),
        authorized_at=authorized_at,
        expires_at=expires_at,
        provenance_receipt_id=_receipt(provenance, field="authorization provenance"),
    )
    authorization.require_for(
        community=config.community,
        action=action,
        occurrence_id=occurrence_id,
        occurred_at=format_rfc3339(now),
    )
    return authorization


def _write(
    ports: SpacesAlphaPorts,
    config: SpacesAlphaAuthorityConfig,
    authorization: ModeratorAuthorization,
    *,
    collection: str,
    record: Mapping[str, object],
) -> SpacesAlphaOutcome:
    ports.occurrences.consume(_consumption_id(authorization))
    rkey = authorization.authorization_id.removeprefix("sha256:")
    outcome = ports.writer.create_immutable(
        space_uri=config.space.uri,
        repo_did=config.community_actor_did,
        collection=collection,
        rkey=rkey,
        record=record,
    )
    reference = _exact_from_outcome(
        config.space, config.community_actor_did, collection, rkey, outcome
    )
    return SpacesAlphaOutcome(reference, authorization)


def _exact_from_outcome(
    space: SpaceIdentity,
    actor: str,
    collection: str,
    rkey: str,
    outcome: SpacesAlphaWriteOutcome,
) -> ExactSpaceRecordReference:
    expected = f"{space.uri}/{actor}/{collection}/{rkey}"
    if outcome.uri != expected:
        raise ValidationError(
            "authority_writer_mismatch", "writer returned another record"
        )
    return ExactSpaceRecordReference(space, actor, collection, rkey, outcome.cid)


def _same_space_author(
    submission: ExactSpaceRecordReference, subject: ExactSpaceRecordReference
) -> None:
    if submission.space != subject.space:
        raise ValidationError(
            "space_binding_mismatch", "submission and source Space differ"
        )
    if submission.author_did != subject.author_did:
        raise ValidationError(
            "author_binding_mismatch", "submission and source authors differ"
        )


def _strong_ref(reference: ExactSpaceRecordReference) -> dict[str, str]:
    return {"uri": reference.uri, "cid": reference.cid}


def _receipt(value: object, *, field: str) -> str:
    try:
        return validate_sha256(value)
    except ValidationError as exc:
        raise ValidationError(
            "live_authorization_invalid", f"{field} must be a receipt"
        ) from exc


def _consumption_id(authorization: ModeratorAuthorization) -> str:
    payload = json.dumps(
        {
            "community": authorization.community.identity_id,
            "action": authorization.action,
            "targetOccurrence": authorization.target_occurrence_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


__all__ = [
    "AdmitOccurrence",
    "AuthorizationOccurrenceStore",
    "RemoveOccurrence",
    "SpacesAlphaAuthorityConfig",
    "SpacesAlphaAuthorityWriter",
    "SpacesAlphaOutcome",
    "SpacesAlphaPorts",
    "SpacesAlphaWriteOutcome",
    "admit_space",
    "remove_space",
]
