"""Minimal human-facing local prototype over public projection feeds."""

from .prototype import (
    PROTOTYPE_VERSION,
    LocalCommunityPrototype,
    PrototypeSite,
    refuse_prototype_claim_upgrade,
)

__all__ = [
    "PROTOTYPE_VERSION",
    "LocalCommunityPrototype",
    "PrototypeSite",
    "refuse_prototype_claim_upgrade",
]

__version__ = "0.1.0"
