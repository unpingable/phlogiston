"""Inert exact-reference records for the SCV0 Space community product slice."""

from .model import (
    COMPATIBILITY_PROFILE,
    AdmissionDisposition,
    AuthorizedAction,
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
    SpaceIdentity,
    Submission,
    classify_admission_candidate,
    refuse_claim_upgrade,
)

__all__ = [
    "COMPATIBILITY_PROFILE",
    "AdmissionDisposition",
    "AuthorWithdrawal",
    "AuthorizedAction",
    "CommunityAdmission",
    "CommunityIdentity",
    "ExactSpaceRecordReference",
    "ModeratorAuthorization",
    "PostReference",
    "ProjectionReference",
    "RemovalRecord",
    "RenderState",
    "SourceRelationship",
    "SpaceIdentity",
    "Submission",
    "classify_admission_candidate",
    "refuse_claim_upgrade",
]

__version__ = "0.1.0"
