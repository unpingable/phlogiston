from __future__ import annotations

import pytest

from communitywatch_spaces_alpha import SpaceObserver
from spaces_http_support import http_fixture_factory as http_fixture_factory
from spaces_support import (
    access,
    fixture_source,
    load_campaign,
    load_sa1,
    load_sa2,
    load_sa3,
    load_sa4,
    load_sa4_source,
    load_sa5,
    load_sa6,
    load_sa8,
    load_sa9a,
    load_sa9b,
    space,
)


@pytest.fixture
def campaign() -> dict[str, object]:
    return load_campaign()


@pytest.fixture
def sa1_vectors() -> dict[str, object]:
    return load_sa1()


@pytest.fixture
def sa2_vectors() -> dict[str, object]:
    return load_sa2()


@pytest.fixture
def sa3_vectors() -> dict[str, object]:
    return load_sa3()


@pytest.fixture
def sa4_source_vectors() -> dict[str, object]:
    return load_sa4_source()


@pytest.fixture
def sa4_vectors() -> dict[str, object]:
    return load_sa4()


@pytest.fixture
def sa5_vectors() -> dict[str, object]:
    return load_sa5()


@pytest.fixture
def sa6_vectors() -> dict[str, object]:
    return load_sa6()


@pytest.fixture
def sa8_vectors() -> dict[str, object]:
    return load_sa8()


@pytest.fixture
def sa9a_vectors() -> dict[str, object]:
    return load_sa9a()


@pytest.fixture
def sa9b_vectors() -> dict[str, object]:
    return load_sa9b()


@pytest.fixture
def observer(campaign: dict[str, object]) -> SpaceObserver:
    raw_space = campaign["space"]
    assert isinstance(raw_space, dict)
    return SpaceObserver(
        space=space(campaign),
        space_host=str(raw_space["spaceHost"]),
        source=fixture_source(campaign),
        admitted_collections=frozenset({"invalid.test.spacepost"}),
        access=access(campaign),
        accepted_verification_modes=frozenset({"fixture"}),
    )
