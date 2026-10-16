"""Shared fixtures and path setup for the governance test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "governance" / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# Commit at which every frozen OQ-7 change set's declared base digests hold.
OQ7_BASE_COMMIT = "4c42541f5ccfa396ead7114d84cef419fba07593"
# Commit at which change set A's declared result digests hold.
OQ7_APPLIED_COMMIT = "e81e499f5d0f9caa6a3a420eeb6e811abbd1ac47"


@pytest.fixture()
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture()
def fixtures_dir() -> Path:
    return FIXTURES_DIR
