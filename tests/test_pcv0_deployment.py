from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from community_notify.config import ConfigError

ROOT = Path(__file__).parents[1]
DEPLOYMENT = ROOT / "deploy" / "public-community-pcv0"
SPEC = importlib.util.spec_from_file_location(
    "pcv0_validate_deployment", DEPLOYMENT / "validate_deployment.py"
)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def campaign() -> dict[str, object]:
    return json.loads((DEPLOYMENT / "campaign.example.json").read_text())


def receipt() -> dict[str, object]:
    return json.loads((DEPLOYMENT / "integration-receipt.example.json").read_text())


def test_committed_bundle_is_strict_and_internally_consistent() -> None:
    validator.validate_committed_bundle(ROOT)


def test_template_is_valid_but_not_launch_ready() -> None:
    validator.validate_campaign(campaign())
    with pytest.raises(validator.ValidationFailure, match="unresolved"):
        validator.validate_campaign(campaign(), ready=True)


def test_cross_pds_identity_is_required() -> None:
    value = campaign()
    identities = value["integrationIdentities"]
    identities[1]["pdsOrigin"] = identities[0]["pdsOrigin"]
    with pytest.raises(
        validator.ValidationFailure, match="distinct DIDs and PDS origins"
    ):
        validator.validate_campaign(value)


def test_schema_authority_may_not_be_the_community_actor() -> None:
    value = campaign()
    authority = value["schemaAuthority"]
    authority["did"] = validator.COMMUNITY_DID
    authority["expectedTxt"] = f"did={validator.COMMUNITY_DID}"
    with pytest.raises(validator.ValidationFailure, match="must be distinct"):
        validator.validate_campaign(value)


def test_blocked_human_campaign_cannot_name_synthetic_completion() -> None:
    value = campaign()
    value["humanDogfood"]["maintainers"] = ["test-account-one", "test-account-two"]
    with pytest.raises(validator.ValidationFailure, match="must not fabricate"):
        validator.validate_campaign(value)


def test_receipt_has_fixed_ordered_journey_and_refuses_secret_fields() -> None:
    validator.validate_receipt(receipt())
    value = receipt()
    value["oauthToken"] = "secret"
    with pytest.raises(validator.ValidationFailure, match="fields differ"):
        validator.validate_receipt(value)

    value = receipt()
    value["checks"][0]["evidence"] = ["Bearer should-never-appear"]
    with pytest.raises(validator.ValidationFailure, match="secret material"):
        validator.validate_receipt(value)


def test_incomplete_receipt_cannot_be_reported_complete() -> None:
    with pytest.raises(validator.ValidationFailure, match="pass status"):
        validator.validate_receipt(receipt(), complete=True)


def ready_campaign() -> dict[str, object]:
    value = campaign()
    replacements = {
        "PCV0-INTERNAL-REPLACE-WITH-DATE-01": "PCV0-INTERNAL-2026-09-08-01",
        "did:plc:replacewithschemaauthority": "did:plc:schematestauthority",
        "replace-with-schema-authority-handle.invalid": "schema-authority.example.net",
        "did:plc:replacewithtestmoderator": "did:plc:testmoderatoraccount",
        "replace-with-moderator-handle.invalid": "moderator.example.net",
        "https://participant-one-pds.invalid": "https://pds-one.example.net",
        "did:plc:replacewithtestparticipant": "did:plc:testparticipantaccount",
        "replace-with-participant-handle.invalid": "participant.example.org",
        "https://participant-two-pds.invalid": "https://pds-two.example.org",
        "REPLACE_WITH_ACCOUNT_CONTROLLER": "integration-operator",
    }
    encoded = json.dumps(value)
    for old, new in replacements.items():
        encoded = encoded.replace(old, new)
    return json.loads(encoded)


def test_service_principals_require_a_distinct_notifier_uid() -> None:
    value = campaign()
    assert value["servicePrincipals"]["communityNotifyUid"] == 42005
    del value["servicePrincipals"]["communityNotifyUid"]
    with pytest.raises(validator.ValidationFailure, match="fields differ"):
        validator.validate_campaign(value)
    value = campaign()
    value["servicePrincipals"]["communityNotifyUid"] = 42004
    with pytest.raises(validator.ValidationFailure, match="pairwise distinct"):
        validator.validate_campaign(value)


def test_receipt_creation_is_exclusive_and_secret_free(tmp_path: Path) -> None:
    ready = ready_campaign()
    validator.validate_campaign(ready, ready=True)
    built = validator.build_receipt(ready)
    validator.validate_receipt(built)
    validator.validate_receipt_binding(built, ready)
    output = tmp_path / "receipt.json"
    validator.write_new(output, built)
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        validator.write_new(output, built)


@pytest.mark.parametrize(
    ("name", "old", "new", "message"),
    [
        (
            "community-notify.service",
            "Group=community-notify",
            "Group=community-authority",
            "own principal",
        ),
        (
            "community-notify.service",
            "ReadWritePaths=/var/lib/community-notify",
            "ReadWritePaths=/var/lib/community-notify /run/community-authority",
            "own principal",
        ),
        (
            "community-notify.toml",
            'public_base_url = "https://phlogiston.app"',
            'public_base_url = "https://elsewhere.example.net"',
            "public origin",
        ),
        (
            "community-notify.toml",
            'projection_origin = "http://127.0.0.1:8080"',
            'projection_origin = "http://127.0.0.1:9090"',
            "observer origin",
        ),
    ],
)
def test_notifier_is_bound_to_the_bundle_without_authority(
    tmp_path: Path, name: str, old: str, new: str, message: str
) -> None:
    copy = tmp_path / "deploy" / "public-community-pcv0"
    shutil.copytree(DEPLOYMENT, copy)
    target = copy / name
    text = target.read_text()
    assert old in text
    target.write_text(text.replace(old, new))
    with pytest.raises(validator.ValidationFailure, match=message):
        validator.validate_committed_bundle(tmp_path)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "ExecStart=/opt/atproto-community/apps/community-live/node_modules/.bin/tsx src/server.ts",
            "ExecStart=/usr/bin/corepack pnpm start",
            "installed tsx binary",
        ),
        (
            "ExecStart=/opt/atproto-community/apps/community-live/node_modules/.bin/tsx src/server.ts",
            "ExecStart=/opt/atproto-community/apps/community-live/node_modules/.bin/tsx src/server.ts\n"
            "ExecStartPre=/usr/bin/corepack pnpm install",
            "corepack or pnpm",
        ),
        (
            "WorkingDirectory=/opt/atproto-community/apps/community-live",
            "WorkingDirectory=/opt/atproto-community",
            "own application directory",
        ),
    ],
)
def test_live_unit_starts_the_installed_tsx_binary(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    root = _bundle_with(tmp_path, {"community-live.service": (old, new)})
    with pytest.raises(validator.ValidationFailure, match=message):
        validator.validate_committed_bundle(root)


def test_notifier_example_refuses_a_plain_http_webhook(tmp_path: Path) -> None:
    copy = tmp_path / "deploy" / "public-community-pcv0"
    shutil.copytree(DEPLOYMENT, copy)
    target = copy / "community-notify.toml"
    target.write_text(
        target.read_text().replace("https://room-webhook", "http://room-webhook")
    )
    with pytest.raises(ConfigError, match="https"):
        validator.validate_committed_bundle(tmp_path)


WEB_FAULTS = "COMMUNITY_INTEGRATION_FAULTS=enabled\n"
WEB_FAULT_DIR = (
    "COMMUNITY_INTEGRATION_FAULT_DIR=/var/lib/community-web/integration-faults\n"
)
AUTHORITY_FAULT_DIR = (
    'integration_fault_directory = "/var/lib/communityd/integration-faults"\n'
)


def _bundle_with(tmp_path: Path, edits: dict[str, tuple[str, str]]) -> Path:
    copy = tmp_path / "deploy" / "public-community-pcv0"
    shutil.copytree(DEPLOYMENT, copy)
    for name, (old, new) in edits.items():
        target = copy / name
        text = target.read_text()
        assert old in text
        target.write_text(text.replace(old, new))
    return tmp_path


def test_committed_example_is_campaign_mode() -> None:
    assert validator.validate_committed_bundle(ROOT) == "campaign"


@pytest.mark.parametrize(
    ("edits", "message"),
    [
        (
            {"community-web.env.example": (WEB_FAULTS, "")},
            "both present or both absent",
        ),
        (
            {"community-web.env.example": (WEB_FAULT_DIR, "")},
            "both present or both absent",
        ),
        (
            {
                "community-web.env.example": (
                    WEB_FAULTS,
                    "COMMUNITY_INTEGRATION_FAULTS=disabled\n",
                )
            },
            "browser integration fault boundary",
        ),
        (
            {"communityd.toml": (AUTHORITY_FAULT_DIR, "")},
            "communityd has no integration_fault_directory",
        ),
    ],
)
def test_campaign_mode_missing_one_control_is_refused(
    tmp_path: Path, edits: dict[str, tuple[str, str]], message: str
) -> None:
    root = _bundle_with(tmp_path, edits)
    with pytest.raises(validator.ValidationFailure, match=message):
        validator.validate_committed_bundle(root)


def test_normal_mode_with_hooks_absent_on_both_sides_is_accepted(
    tmp_path: Path,
) -> None:
    root = _bundle_with(
        tmp_path,
        {
            "community-web.env.example": (WEB_FAULTS + WEB_FAULT_DIR, ""),
            "communityd.toml": (AUTHORITY_FAULT_DIR, ""),
        },
    )
    assert validator.validate_committed_bundle(root) == "normal"


@pytest.mark.parametrize(
    ("edits", "message"),
    [
        (
            {"community-web.env.example": (WEB_FAULTS + WEB_FAULT_DIR, "")},
            "browser fault settings are absent",
        ),
        (
            {
                "community-web.env.example": (WEB_FAULTS, ""),
                "communityd.toml": (AUTHORITY_FAULT_DIR, ""),
            },
            "both present or both absent",
        ),
        (
            {
                "community-web.env.example": (
                    WEB_FAULT_DIR,
                    "COMMUNITY_INTEGRATION_FAULT_DIR=/var/lib/community-web\n",
                )
            },
            "browser integration fault boundary",
        ),
        (
            {
                "communityd.toml": (
                    AUTHORITY_FAULT_DIR,
                    'integration_fault_directory = "/var/lib/communityd/other"\n',
                )
            },
            "authority integration fault boundary",
        ),
        (
            {
                "community-web.env.example": (
                    WEB_FAULTS + WEB_FAULT_DIR,
                    "COMMUNITY_INTEGRATION_FAULTS_EXTRA=enabled\n",
                ),
                "communityd.toml": (AUTHORITY_FAULT_DIR, ""),
            },
            "fields differ from the strict set",
        ),
    ],
)
def test_hybrid_fault_configuration_is_refused(
    tmp_path: Path, edits: dict[str, tuple[str, str]], message: str
) -> None:
    root = _bundle_with(tmp_path, edits)
    with pytest.raises(validator.ValidationFailure, match=message):
        validator.validate_committed_bundle(root)


def test_normal_mode_keeps_every_other_invariant(tmp_path: Path) -> None:
    root = _bundle_with(
        tmp_path,
        {
            "community-web.env.example": (WEB_FAULTS + WEB_FAULT_DIR, ""),
            "communityd.toml": ("web_peer_uid = 42001", "web_peer_uid = 42009"),
        },
    )
    text = (root / "deploy/public-community-pcv0/communityd.toml").read_text()
    (root / "deploy/public-community-pcv0/communityd.toml").write_text(
        text.replace(AUTHORITY_FAULT_DIR, "")
    )
    with pytest.raises(validator.ValidationFailure, match="peer UIDs"):
        validator.validate_committed_bundle(root)


PCV0_UNITS = (
    "communityd.service",
    "communitywatch-index.service",
    "communitywatch-web.service",
    "community-policy.service",
    "community-live.service",
    "community-notify.service",
)
HOST_USERS = {
    "community-web": 42001,
    "community-policy": 42002,
    "communityd": 42003,
    "communitywatch": 42004,
    "community-notify": 42005,
}
PHLOGISTON_UNIT = (
    "[Service]\nUser=phlogiston\n"
    "ExecStart=/opt/phlogiston/.venv/bin/communityd-serve --config /etc/phlogiston/communityd.toml\n"
)


def _host(
    tmp_path: Path,
    units: dict[str, str | None] | None = None,
    *,
    vendor: dict[str, str] | None = None,
) -> Path:
    """Build a fake host root: PCV0 units in /etc, optional vendor units in /usr/lib.

    A ``None`` unit body installs a mask (symlink to /dev/null) in /etc.
    """
    root = tmp_path / "host"
    etc = root / "etc/systemd/system"
    lib = root / "usr/lib/systemd/system"
    etc.mkdir(parents=True)
    lib.mkdir(parents=True)
    for name in PCV0_UNITS:
        (etc / name).write_text((DEPLOYMENT / name).read_text())
    for name, body in (units or {}).items():
        if body is None:
            (etc / name).symlink_to("/dev/null")
        else:
            (etc / name).write_text(body)
    for name, body in (vendor or {}).items():
        (lib / name).write_text(body)
    return root


def _lookup(name: str) -> int:
    return HOST_USERS[name]


def _preflight(root: Path, lookup=_lookup) -> None:
    validator.host_preflight(root, ready_campaign(), lookup)


def test_host_preflight_accepts_the_single_pcv0_writer(tmp_path: Path) -> None:
    _preflight(_host(tmp_path))


def test_host_preflight_refuses_a_second_communityd_unit(tmp_path: Path) -> None:
    body = (DEPLOYMENT / "communityd.service").read_text()
    root = _host(tmp_path, {"communityd-second.service": body})
    with pytest.raises(validator.ValidationFailure, match="exactly one installed"):
        _preflight(root)


@pytest.mark.parametrize(
    "exec_start",
    [
        "/opt/other/.venv/bin/python -m communityd.serve_cli --config /etc/other/communityd.toml",
        '/usr/bin/python3 -c "import communityd.serve_cli; communityd.serve_cli.main()"',
    ],
)
def test_host_preflight_refuses_a_module_started_writer(
    tmp_path: Path, exec_start: str
) -> None:
    body = f"[Service]\nUser=other\nExecStart={exec_start}\n"
    root = _host(tmp_path, {"other-community.service": body})
    with pytest.raises(validator.ValidationFailure, match="exactly one installed"):
        _preflight(root)


def test_host_preflight_refuses_a_vendor_writer_shadowed_by_nothing(
    tmp_path: Path,
) -> None:
    root = _host(tmp_path, vendor={"other-communityd.service": PHLOGISTON_UNIT})
    with pytest.raises(validator.ValidationFailure, match="exactly one installed"):
        _preflight(root)


def test_host_preflight_refuses_a_dropin_that_adds_a_writer(tmp_path: Path) -> None:
    root = _host(tmp_path)
    dropin = root / "etc/systemd/system/community-policy.service.d"
    dropin.mkdir()
    (dropin / "override.conf").write_text(
        "[Service]\nExecStart=/opt/atproto-community/.venv/bin/communityd-serve\n"
    )
    with pytest.raises(validator.ValidationFailure, match="exactly one installed"):
        _preflight(root)


def test_host_preflight_refuses_an_unmasked_phlogiston_unit(tmp_path: Path) -> None:
    root = _host(tmp_path, {"phlogiston-communityd.service": PHLOGISTON_UNIT})
    with pytest.raises(validator.ValidationFailure, match="exactly one installed"):
        _preflight(root)
    inert = "[Service]\nUser=phlogiston\nExecStart=/bin/true\n"
    root = _host(tmp_path / "inert", {"phlogiston-communityd.service": inert})
    with pytest.raises(validator.ValidationFailure, match="withdrawn"):
        _preflight(root)
    root = _host(tmp_path / "vendor", vendor={"phlogiston-communityd.service": inert})
    with pytest.raises(validator.ValidationFailure, match="withdrawn"):
        _preflight(root)


def test_host_preflight_accepts_a_masked_phlogiston_unit(tmp_path: Path) -> None:
    root = _host(
        tmp_path,
        {"phlogiston-communityd.service": None},
        vendor={"phlogiston-communityd.service": PHLOGISTON_UNIT},
    )
    _preflight(root)


def test_host_preflight_fails_closed_without_the_unit_directories(
    tmp_path: Path,
) -> None:
    root = _host(tmp_path)
    shutil.rmtree(root / "usr/lib/systemd/system")
    with pytest.raises(validator.ValidationFailure, match="missing"):
        _preflight(root)
    root = _host(tmp_path / "unreadable")
    etc = root / "etc/systemd/system"
    etc.chmod(0)
    try:
        if not list(etc.iterdir()):
            pytest.skip("directory permissions are not enforced for this user")
    except PermissionError:
        pass
    try:
        with pytest.raises(validator.ValidationFailure, match="cannot read"):
            _preflight(root)
    finally:
        etc.chmod(0o755)


def test_host_preflight_binds_unit_users_to_campaign_uids(tmp_path: Path) -> None:
    root = _host(tmp_path)
    users = dict(HOST_USERS, **{"community-notify": 42004})
    with pytest.raises(validator.ValidationFailure, match="communityNotifyUid"):
        _preflight(root, users.__getitem__)
    users = dict(HOST_USERS)
    del users["community-notify"]
    with pytest.raises(validator.ValidationFailure, match="not a provisioned"):
        _preflight(root, users.__getitem__)


def test_host_preflight_command_uses_the_injected_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(validator, "_passwd_uid", _lookup)
    campaign_path = tmp_path / "campaign.json"
    campaign_path.write_text(json.dumps(ready_campaign()))
    root = _host(tmp_path)
    assert (
        validator.main(
            [
                "host-preflight",
                "--campaign",
                str(campaign_path),
                "--unit-root",
                str(root),
            ]
        )
        == 0
    )
    (root / "etc/systemd/system/phlogiston-communityd.service").write_text(
        PHLOGISTON_UNIT
    )
    assert (
        validator.main(
            [
                "host-preflight",
                "--campaign",
                str(campaign_path),
                "--unit-root",
                str(root),
            ]
        )
        == 1
    )
    assert "exactly one installed" in capsys.readouterr().err
