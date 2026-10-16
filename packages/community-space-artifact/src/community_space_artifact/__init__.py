"""Pure synthetic SCV0 projection-artifact compiler."""

from .artifact import (
    COMPILER_VERSION,
    PRESENTATION_PROFILE,
    ArtifactReceiptReferences,
    BoundedSourcePresentation,
    DisclosureMode,
    DisclosurePolicy,
    NonPublishedCandidate,
    ProjectionArtifact,
    ProjectionArtifactCompiler,
    ProjectionArtifactEntry,
    ProjectionCompilation,
    ProjectionDisclosureInput,
    refuse_artifact_claim_upgrade,
)

__all__ = [
    "COMPILER_VERSION",
    "PRESENTATION_PROFILE",
    "ArtifactReceiptReferences",
    "BoundedSourcePresentation",
    "DisclosureMode",
    "DisclosurePolicy",
    "NonPublishedCandidate",
    "ProjectionArtifact",
    "ProjectionArtifactCompiler",
    "ProjectionArtifactEntry",
    "ProjectionCompilation",
    "ProjectionDisclosureInput",
    "refuse_artifact_claim_upgrade",
]

__version__ = "0.1.0"
