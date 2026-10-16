"""Deterministic static publication bundle for the synthetic SCV0 demo."""

from .demo import (
    DEMO_VERSION,
    DemoFile,
    StaticDemoBundle,
    StaticDemoCompiler,
    build_synthetic_demo_sites,
)
from .showcase import (
    COMMUNITY_NAME,
    SHOWCASE_VERSION,
    HumanShowcaseCompiler,
    ShowcaseBundle,
    ShowcaseCorpus,
    build_showcase_bundle,
    build_showcase_corpus,
    refuse_showcase_claim_upgrade,
)

__all__ = [
    "DEMO_VERSION",
    "DemoFile",
    "StaticDemoBundle",
    "StaticDemoCompiler",
    "build_synthetic_demo_sites",
    "COMMUNITY_NAME",
    "SHOWCASE_VERSION",
    "HumanShowcaseCompiler",
    "ShowcaseBundle",
    "ShowcaseCorpus",
    "build_showcase_bundle",
    "build_showcase_corpus",
    "refuse_showcase_claim_upgrade",
]

__version__ = "0.1.0"
