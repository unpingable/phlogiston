from __future__ import annotations

from pathlib import Path

import pytest

from community_notify.config import ConfigError, NotifyConfig

VALID = """
projection_origin = "http://127.0.0.1:8080"
community_did = "did:plc:exampleparticipantabcdef"
community_name = "Test Community"
public_base_url = "https://community.example.test"
webhook_url = "https://room.example.test/api/webhooks/1/token"
webhook_payload_key = "content"
poll_interval_seconds = 30
cursor_path = "/var/lib/community-notify/cursor.json"
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "notify.toml"
    path.write_text(text)
    return path


def test_config_is_strict_and_carries_no_credentials(tmp_path: Path) -> None:
    config = NotifyConfig.load(write(tmp_path, VALID))
    assert config.webhook_payload_key == "content"
    assert config.cursor_path == Path("/var/lib/community-notify/cursor.json")
    assert config.poll_interval_seconds == 30.0
    for extra in ('credential = "x"', 'second_webhook_url = "https://b.test/x"'):
        with pytest.raises(ConfigError, match="fields differ"):
            NotifyConfig.load(write(tmp_path, VALID + extra + "\n"))


def test_both_payload_keys_are_accepted_and_nothing_else(tmp_path: Path) -> None:
    slack = VALID.replace('"content"', '"text"')
    assert NotifyConfig.load(write(tmp_path, slack)).webhook_payload_key == "text"
    with pytest.raises(ConfigError, match="webhook_payload_key"):
        NotifyConfig.load(write(tmp_path, VALID.replace('"content"', '"body"')))


@pytest.mark.parametrize(
    "webhook",
    [
        "http://room.example.test/api/webhooks/1/token",
        "ftp://room.example.test/hook",
        "https://user:secret@room.example.test/hook",
        "https:///no-host",
        "room.example.test/hook",
        "javascript:alert(1)",
    ],
)
def test_webhook_must_be_credential_free_https(tmp_path: Path, webhook: str) -> None:
    text = VALID.replace("https://room.example.test/api/webhooks/1/token", webhook)
    with pytest.raises(ConfigError, match="webhook_url") as caught:
        NotifyConfig.load(write(tmp_path, text))
    assert webhook not in str(caught.value)


@pytest.mark.parametrize(
    ("old", "new", "field"),
    [
        (
            '"https://community.example.test"',
            '"http://community.example.test"',
            "public_base_url",
        ),
        (
            '"https://community.example.test"',
            '"https://community.example.test/x"',
            "public_base_url",
        ),
        ('"http://127.0.0.1:8080"', '"http://127.0.0.1:8080/api"', "projection_origin"),
        ('"did:plc:exampleparticipantabcdef"', '"not-a-did"', "community_did"),
        ('"/var/lib/community-notify/cursor.json"', '"cursor.json"', "cursor_path"),
        ("poll_interval_seconds = 30", "poll_interval_seconds = 0", "poll_interval"),
        ("poll_interval_seconds = 30", "poll_interval_seconds = true", "poll_interval"),
        ('"Test Community"', '"line\\nbreak"', "community_name"),
    ],
)
def test_other_fields_are_validated(
    tmp_path: Path, old: str, new: str, field: str
) -> None:
    with pytest.raises(ConfigError, match=field):
        NotifyConfig.load(write(tmp_path, VALID.replace(old, new)))
