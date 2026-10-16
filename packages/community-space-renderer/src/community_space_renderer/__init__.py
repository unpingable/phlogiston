"""Replaceable local renderers for exact SCV0 projection artifacts."""

from .renderer import (
    RENDERER_VERSION,
    AccessibleFixtureRenderer,
    CompactFixtureRenderer,
    RenderedEntrySemantics,
    RenderedPage,
    RenderedProjectionSemantics,
    RendererStyle,
    refuse_renderer_claim_upgrade,
)

__all__ = [
    "RENDERER_VERSION",
    "AccessibleFixtureRenderer",
    "CompactFixtureRenderer",
    "RenderedEntrySemantics",
    "RenderedPage",
    "RenderedProjectionSemantics",
    "RendererStyle",
    "refuse_renderer_claim_upgrade",
]

__version__ = "0.1.0"
