"""Observer-only Juniper projection compilation and atomic publication."""

from .compiler import (
    AuthorityWriteReceipt,
    CompiledLiveProjection,
    LiveProjectionCompiler,
    QualifiedRepoHistory,
    QualifiedSnapshot,
    SourceUnavailableEvidence,
)
from .publisher import AtomicProjectionPublisher, PublishedGeneration

__all__ = [
    "AtomicProjectionPublisher",
    "AuthorityWriteReceipt",
    "CompiledLiveProjection",
    "LiveProjectionCompiler",
    "PublishedGeneration",
    "QualifiedRepoHistory",
    "QualifiedSnapshot",
    "SourceUnavailableEvidence",
]

__version__ = "0.1.0"
