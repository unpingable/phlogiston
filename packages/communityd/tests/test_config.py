from __future__ import annotations

import pytest

from communityd.config import ConfigError, load_config, parse_config
from fakes_support import ADMIN_DID, ALLOWED_UID, COMMUNITY_DID, ROOT, write_config


def _document() -> dict[str, object]:
    return {
        "community_did": COMMUNITY_DID,
        "administrator_did": ADMIN_DID,
        "community_pds_url": "https://pds.invalid",
        "allowed_uid": ALLOWED_UID,
        "reader_adapter": "fake",
        "ledger_adapter": "fake",
        "writer_adapter": "fake",
        "credential_provider": "fake",
        "credential_ref": "fake://communityd-admin",
    }


def test_repository_example_config_parses() -> None:
    config = load_config(ROOT / "config" / "communityd.example.toml")
    assert config.community_did == COMMUNITY_DID
    assert config.administrator_did == ADMIN_DID
    assert config.writer_adapter == "fake"


def test_valid_document_uses_bounded_defaults(tmp_path) -> None:
    path = write_config(tmp_path)
    config = load_config(path)
    assert config.request_timeout_ms == 5000
    assert config.max_retries == 2
    assert config.operation_journal_path is None


def test_private_operation_journal_requires_absolute_path(tmp_path) -> None:
    document = _document()
    document["operation_journal_path"] = str(tmp_path / "authority.sqlite3")
    assert (
        parse_config(document).operation_journal_path
        == document["operation_journal_path"]
    )
    document["operation_journal_path"] = "relative.sqlite3"
    with pytest.raises(ConfigError):
        parse_config(document)


def test_p0_requires_durable_journal_and_explicit_pause_file(tmp_path) -> None:
    document = _document()
    document["p0_profile"] = "root_only"
    with pytest.raises(ConfigError, match="durable operation journal"):
        parse_config(document)
    document["operation_journal_path"] = str(tmp_path / "journal.sqlite3")
    with pytest.raises(ConfigError, match="admission pause path"):
        parse_config(document)
    document["p0_admission_pause_path"] = str(tmp_path / "admission.state")
    assert parse_config(document).p0_profile == "root_only"
    document["p0_profile"] = "other"
    with pytest.raises(ConfigError, match="p0_profile"):
        parse_config(document)
    document["p0_profile"] = "root_only"
    document["writer_adapter"] = "pds"
    document["reader_adapter"] = "pds"
    document["ledger_adapter"] = "pds"
    document["credential_provider"] = "env_file"
    document["credential_ref"] = "env:COMMUNITYD_CREDENTIAL_FILE"
    with pytest.raises(ConfigError, match="actor PDS is unsupported"):
        parse_config(document)
    document["p0_test_pds_origin"] = "https://juche.social"
    with pytest.raises(ConfigError, match="isolated test mode"):
        parse_config(document)
    document["allow_loopback_public_endpoints"] = True
    document["community_pds_url"] = "https://juche.social"
    assert parse_config(document).p0_test_pds_origin == "https://juche.social"
    document["p0_test_pds_origin"] = "https://other.example"
    with pytest.raises(ConfigError, match="exact Juche"):
        parse_config(document)


def test_integration_fault_directory_requires_real_writer_and_journal(tmp_path) -> None:
    document = _document()
    document["integration_fault_directory"] = str(tmp_path / "faults")
    with pytest.raises(ConfigError, match="PDS writer"):
        parse_config(document)
    document.update(
        {
            "reader_adapter": "pds",
            "ledger_adapter": "pds",
            "writer_adapter": "pds",
            "credential_provider": "env_file",
            "credential_ref": "env:COMMUNITYD_CREDENTIAL_FILE",
            "operation_journal_path": str(tmp_path / "journal.sqlite3"),
        }
    )
    assert parse_config(document).integration_fault_directory == str(
        tmp_path / "faults"
    )


def test_authority_server_paths_and_peer_uids_are_strict(tmp_path) -> None:
    document = _document()
    document.update(
        {
            "authority_socket_path": str(tmp_path / "authority.sock"),
            "web_peer_uid": 1001,
            "policy_peer_uid": 1002,
        }
    )
    config = parse_config(document)
    assert config.web_peer_uid == 1001
    document["policy_peer_uid"] = 1001
    with pytest.raises(ConfigError):
        parse_config(document)
    document["policy_peer_uid"] = 1002
    document["authority_socket_path"] = "authority.sock"
    with pytest.raises(ConfigError):
        parse_config(document)


def test_public_resolver_configuration_is_bounded_and_https() -> None:
    document = _document()
    document["did_cache_size"] = 0
    with pytest.raises(ConfigError):
        parse_config(document)
    document["did_cache_size"] = 64
    document["plc_directory_url"] = "http://plc.example.com"
    with pytest.raises(ConfigError):
        parse_config(document)
    document["plc_directory_url"] = "http://127.0.0.1:2584"
    document["allow_loopback_public_endpoints"] = True
    assert parse_config(document).did_cache_size == 64


def test_fixed_pds_reader_is_loopback_test_only() -> None:
    document = _document()
    document["reader_adapter"] = "pds_fixed"
    with pytest.raises(ConfigError, match="loopback tests"):
        parse_config(document)


def test_unknown_keys_are_rejected() -> None:
    for key in ("sqlite_path", "artifact_root", "observer_path", "extra"):
        document = _document()
        document[key] = "value"
        with pytest.raises(ConfigError):
            parse_config(document)


def test_secret_bearing_keys_are_rejected() -> None:
    for key in ("token", "admin_password", "signing_private_key"):
        document = _document()
        document[key] = "value"
        with pytest.raises(ConfigError):
            parse_config(document)


def test_raw_secret_in_credential_ref_is_rejected() -> None:
    document = _document()
    document["credential_ref"] = "hunter2-plaintext-secret"
    with pytest.raises(ConfigError):
        parse_config(document)


def test_missing_allowed_uid_is_rejected() -> None:
    document = _document()
    del document["allowed_uid"]
    with pytest.raises(ConfigError):
        parse_config(document)


def test_unavailable_adapter_selection_is_rejected() -> None:
    document = _document()
    document["writer_adapter"] = "atproto"
    with pytest.raises(ConfigError):
        parse_config(document)


def test_pds_adapters_with_env_file_credentials_are_accepted() -> None:
    document = _document()
    document.update(
        {
            "reader_adapter": "pds",
            "ledger_adapter": "pds",
            "writer_adapter": "pds",
            "credential_provider": "env_file",
            "credential_ref": "env:COMMUNITYD_CREDENTIAL_FILE",
        }
    )
    config = parse_config(document)
    assert config.writer_adapter == "pds"
    assert config.credential_provider == "env_file"


def test_env_file_provider_requires_env_reference() -> None:
    document = _document()
    document.update(
        {
            "writer_adapter": "pds",
            "credential_provider": "env_file",
            "credential_ref": "fake://communityd-admin",
        }
    )
    with pytest.raises(ConfigError):
        parse_config(document)


def test_pds_writer_requires_env_file_provider() -> None:
    document = _document()
    document["writer_adapter"] = "pds"
    with pytest.raises(ConfigError):
        parse_config(document)


def test_non_loopback_http_pds_url_is_rejected() -> None:
    document = _document()
    document["community_pds_url"] = "http://pds.example.com"
    with pytest.raises(ConfigError):
        parse_config(document)


def test_loopback_http_pds_url_is_accepted() -> None:
    document = _document()
    document["community_pds_url"] = "http://127.0.0.1:2583"
    config = parse_config(document)
    assert config.community_pds_url == "http://127.0.0.1:2583"


def test_pds_url_with_userinfo_or_path_is_rejected() -> None:
    for url in (
        "https://user:pw@pds.example.com",
        "https://pds.example.com/xrpc",
        "https://pds.example.com?query=1",
    ):
        document = _document()
        document["community_pds_url"] = url
        with pytest.raises(ConfigError):
            parse_config(document)


def test_invalid_did_is_rejected() -> None:
    document = _document()
    document["administrator_did"] = "not a did"
    with pytest.raises(ConfigError):
        parse_config(document)


def test_controlled_hosted_profile_is_exact_and_separate(tmp_path):
    document = {
        **_document(),
        "p0_profile": "root_only",
        "operation_journal_path": str(tmp_path / "journal.sqlite3"),
        "p0_admission_pause_path": str(tmp_path / "pause"),
        "p0_hosted_pds_origin": "https://phlogiston.social",
    }
    assert parse_config(document).p0_hosted_pds_origin == "https://phlogiston.social"
    for change in (
        {"p0_profile": None},
        {"p0_hosted_pds_origin": "https://other.social"},
        {"p0_test_pds_origin": "https://juche.social"},
    ):
        with pytest.raises(ConfigError):
            parse_config({**document, **change})


def test_hosted_decision_custody_cannot_be_reused_by_another_profile(tmp_path):
    from communityd.p0_decisions import P0DecisionStore

    path = tmp_path / "hosted.sqlite3"
    mode = "controlled-hosted:https://phlogiston.social"
    P0DecisionStore(path, test_origin=mode)
    P0DecisionStore(path, test_origin=mode)
    for other in (None, "https://juche.social"):
        with pytest.raises(ValueError, match="another provider mode"):
            P0DecisionStore(path, test_origin=other)


def test_mixed_profile_keeps_community_writer_pinned(tmp_path):
    document = {
        **_document(),
        "p0_profile": "root_only",
        "p0_hosted_pds_origin": "https://phlogiston.social",
        "p0_allow_bluesky": True,
        "operation_journal_path": str(tmp_path / "journal.sqlite3"),
        "p0_admission_pause_path": str(tmp_path / "pause"),
        "community_pds_url": "https://phlogiston.social",
        "reader_adapter": "pds",
        "ledger_adapter": "pds",
        "writer_adapter": "pds",
        "credential_provider": "env_file",
        "credential_ref": "env:LOCAL_FIXTURE",
    }
    assert parse_config(document).p0_allow_bluesky
    for changes in [
        {"p0_hosted_pds_origin": None},
        {"p0_allow_bluesky": "true"},
        {"p0_allow_bluesky": 1},
        {"p0_test_pds_origin": "https://juche.social"},
        {"community_pds_url": "https://phellinus.us-west.host.bsky.network"},
    ]:
        with pytest.raises(ConfigError):
            parse_config({**document, **changes})
