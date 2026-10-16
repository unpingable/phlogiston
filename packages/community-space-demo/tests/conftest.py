from __future__ import annotations

import json
from pathlib import Path

import pytest

from community_space_demo import (
    StaticDemoCompiler,
    build_showcase_bundle,
    build_showcase_corpus,
    build_synthetic_demo_sites,
)

ROOT = Path(__file__).resolve().parents[3]
M7A_VECTOR = ROOT / "tests" / "fixtures" / "space-community" / "scv0-m7a.json"
M7C_VECTOR = ROOT / "tests" / "fixtures" / "space-community" / "scv0-m7c.json"


@pytest.fixture
def m7a() -> dict[str, object]:
    sites = build_synthetic_demo_sites()
    bundle = StaticDemoCompiler().compile(sites)
    return {
        "sites": sites,
        "bundle": bundle,
        "vector": json.loads(M7A_VECTOR.read_text(encoding="utf-8")),
    }


@pytest.fixture
def m7c() -> dict[str, object]:
    return {
        "corpus": build_showcase_corpus(),
        "bundle": build_showcase_bundle(),
        "vector": json.loads(M7C_VECTOR.read_text(encoding="utf-8")),
    }
