"""Pure SCV0 projection lifecycle reduction."""

from .reducer import (
    REDUCER_VERSION,
    LifecycleState,
    ProjectionLifecycle,
    ProjectionReducer,
    SourceObservation,
    SourceObservationOutcome,
    TransitionKind,
    refuse_projection_claim_upgrade,
)

__all__ = [
    "REDUCER_VERSION",
    "LifecycleState",
    "ProjectionLifecycle",
    "ProjectionReducer",
    "SourceObservation",
    "SourceObservationOutcome",
    "TransitionKind",
    "refuse_projection_claim_upgrade",
]

__version__ = "0.1.0"
