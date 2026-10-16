from __future__ import annotations

from pathlib import Path

import pytest

from communitywatch_space_publisher import AtomicProjectionPublisher


def test_atomic_publisher_refuses_untyped_values(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        AtomicProjectionPublisher().publish(tmp_path, {}, {})  # type: ignore[arg-type]
