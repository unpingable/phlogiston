from pathlib import Path

import pytest

from community_model import ValidationError
from community_policy.config import PolicyConfig


def test_config_is_strict_and_contains_no_credentials(tmp_path: Path) -> None:
    path = tmp_path / "policy.toml"
    path.write_text("""
community_did = "did:web:community.invalid"
observer_origin = "http://127.0.0.1:8042"
authority_socket = "/run/communityd/authority.sock"
state_path = "/var/lib/community-policy/state.sqlite3"
poll_interval_seconds = 5
request_timeout_seconds = 10
""")
    config = PolicyConfig.load(path)
    assert config.authority_socket == Path("/run/communityd/authority.sock")
    assert not hasattr(config, "credential")
    path.write_text(path.read_text() + 'credential = "forbidden"\n')
    with pytest.raises(ValidationError, match="fields differ"):
        PolicyConfig.load(path)


@pytest.mark.parametrize(
    "origin",
    ["http://user:password@observer.invalid", "http://observer.invalid/not-an-origin"],
)
def test_observer_origin_rejects_credentials_and_paths(origin: str) -> None:
    with pytest.raises(ValidationError, match=r"HTTP\(S\) origin"):
        PolicyConfig(
            community_did="did:web:community.invalid",
            observer_origin=origin,
            authority_socket=Path("/run/communityd/authority.sock"),
            state_path=Path("/var/lib/community-policy/state.sqlite3"),
        )
