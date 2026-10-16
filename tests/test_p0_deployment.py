from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
DEPLOY = ROOT / "deploy/public-community-pcv0"
SPEC = importlib.util.spec_from_file_location(
    "p0_validator", DEPLOY / "validate_deployment.py"
)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def campaign():
    return json.loads((DEPLOY / "p0/campaign.example.json").read_text())


def copy_bundle(tmp_path):
    target = tmp_path / "deploy/public-community-pcv0"
    shutil.copytree(DEPLOY, target)
    return target / "p0"


def test_p0_without_notifier_or_policy_is_valid_but_not_ready():
    assert validator.validate_p0_bundle(ROOT) == "p0"
    with pytest.raises(validator.ValidationFailure, match="unresolved"):
        validator.validate_campaign(campaign(), ready=True)


def test_p0_communityd_credential_example_names_a_protected_file():
    lines = (DEPLOY / "p0/communityd.env.example").read_text().splitlines()
    assignments = [line for line in lines if line and not line.startswith("#")]
    assert len(assignments) == 1
    name, value = assignments[0].split("=", 1)
    assert name == "COMMUNITYD_APP_PASSWORD"
    assert Path(value).is_absolute()
    assert Path(value).suffix == ".json"
    assert "REPLACE" not in value


@pytest.mark.parametrize(
    "origin",
    [
        "https://juche.social",
        "https://bsky.social",
        "https://one.host.bsky.network.example.net",
        "https://one.host.bsky.network:444",
        "https://user@one.host.bsky.network",
        "http://one.host.bsky.network",
    ],
)
def test_public_p0_refuses_alternate_hosting_and_lookalikes(origin):
    value = campaign()
    value["integrationIdentities"][0]["pdsOrigin"] = origin
    with pytest.raises(validator.ValidationFailure):
        validator.validate_campaign(value)


def test_one_controller_for_two_technical_identities_is_not_human_dogfood():
    value = campaign()
    for item in value["integrationIdentities"]:
        item["controller"] = "same-operator"
    validator.validate_campaign(value)
    value["humanDogfood"] = {
        "status": "ready",
        "maintainers": ["a", "b"],
        "topic": "test",
        "activity": "test",
    }
    with pytest.raises(validator.ValidationFailure, match="historical"):
        validator.validate_campaign(value)


def test_p0_exact_selected_roles_and_hosting():
    value = campaign()
    validator.validate_campaign(value)
    for role, field, wrong in [
        ("moderator", "did", validator.COMMUNITY_DID),
        ("moderator", "handle", "other.phlogiston.social"),
        ("participant", "did", validator.P0_COMMUNITY_DID),
        ("participant", "pdsOrigin", validator.P0_HOSTED_PDS),
    ]:
        changed = campaign()
        next(item for item in changed["integrationIdentities"] if item["role"] == role)[
            field
        ] = wrong
        with pytest.raises(validator.ValidationFailure):
            validator.validate_campaign(changed)
    changed = campaign()
    changed["schemaAuthority"]["pdsOrigin"] = validator.COMMUNITY_PDS
    with pytest.raises(validator.ValidationFailure, match="publisher"):
        validator.validate_campaign(changed)


def _publication_files(tmp_path):
    value = campaign()
    publisher_did = "did:plc:publishedschemaauthority"
    value["campaignId"] = "P0-20261012-01"
    value["schemaAuthority"].update(
        {"did": publisher_did, "expectedTxt": f"did={publisher_did}"}
    )
    lexicons = ROOT / "packages/community-lexicon-publisher/lexicons"
    documents = []
    for nsid in sorted(validator.P0_LEXICON_SHA256):
        document = json.loads((lexicons / f"{nsid}.json").read_text())
        documents.append(
            {
                "nsid": nsid,
                "rkey": nsid,
                "documentSha256": validator._publication_digest(document),
                "recordSha256": validator._publication_digest(
                    {"$type": "com.atproto.lexicon.schema", **document}
                ),
                "uri": f"at://{publisher_did}/com.atproto.lexicon.schema/{nsid}",
                "document": document,
            }
        )
    manifest = {
        "contract": "pcv0-lexicon-publication-manifest/1",
        "namespaceAuthority": "community.phlogiston.app",
        "dnsName": validator.LEXICON_DNS_NAME,
        "dnsTxt": f"did={publisher_did}",
        "authorityDid": publisher_did,
        "collection": "com.atproto.lexicon.schema",
        "documents": documents,
    }
    digest = validator._publication_digest(manifest)
    acceptance = {
        "contract": "pcv0-lexicon-publication-acceptance/1",
        "manifestSha256": digest,
        "authorityDid": publisher_did,
        "acceptedBy": "qualification fixture",
        "acceptedAt": "2026-10-12T00:00:00Z",
    }
    receipt = {
        "contract": "pcv0-lexicon-publication-receipt/1",
        "manifestSha256": digest,
        "authorityDid": publisher_did,
        "namespaceAuthority": "community.phlogiston.app",
        "dns": {
            "name": validator.LEXICON_DNS_NAME,
            "expected": f"did={publisher_did}",
            "answers": [f"did={publisher_did}"],
            "verified": True,
        },
        "records": [
            {
                "nsid": item["nsid"],
                "documentSha256": item["documentSha256"],
                "uri": item["uri"],
                "cid": "bafyreicl6ujc6ncfktctxxroxognfn7d2fqavvrryoc2lv6m4i6hpbkfti",
                "disposition": "read_back",
            }
            for item in documents
        ],
        "completedAt": "2026-10-12T00:00:00Z",
        "explicitNonClaims": ["production_readiness"],
    }
    for name, data in [
        ("manifest", manifest),
        ("acceptance", acceptance),
        ("receipt", receipt),
    ]:
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(data))
        value["publicationEvidence"][f"{name}Path"] = str(path)
    return value, manifest, receipt


def test_ready_p0_binds_exact_publication_artifacts(tmp_path):
    value, manifest, receipt = _publication_files(tmp_path)
    validator.validate_campaign(value, ready=True)
    manifest["documents"][0]["document"]["defs"] = {}
    Path(value["publicationEvidence"]["manifestPath"]).write_text(json.dumps(manifest))
    with pytest.raises(validator.ValidationFailure, match="document differs"):
        validator.validate_campaign(value, ready=True)
    value, manifest, receipt = _publication_files(tmp_path)
    receipt["records"][0]["uri"] += "-other"
    Path(value["publicationEvidence"]["receiptPath"]).write_text(json.dumps(receipt))
    with pytest.raises(validator.ValidationFailure, match="record readback"):
        validator.validate_campaign(value, ready=True)


@pytest.mark.parametrize(
    "file",
    [
        "community-notify.service",
        "community-notify.toml",
        "community-policy.service",
        "community-policy.toml",
    ],
)
def test_disabled_services_are_absent_not_dummy_destinations(tmp_path, file):
    target = copy_bundle(tmp_path)
    (target / file).write_text("disabled=true\n")
    with pytest.raises(validator.ValidationFailure, match="must be absent"):
        validator.validate_p0_bundle(tmp_path)


@pytest.mark.parametrize(
    "change",
    [
        "origin",
        "faults",
        "test-provider",
        "unpaused",
        "policy-peer",
        "stream-path",
        "observer-test",
        "missing-mixed-flag",
        "observer-bluesky-only",
        "wrong-hosted-origin",
    ],
)
def test_p0_refuses_mixed_or_unsafe_profile(tmp_path, change):
    target = copy_bundle(tmp_path)
    if change == "origin":
        file = target / "community-web.env.example"
        file.write_text(
            file.read_text().replace(
                "https://phlogiston.app", "https://community.phlogiston.app"
            )
        )
    elif change == "faults":
        file = target / "community-web.env.example"
        file.write_text(file.read_text() + "COMMUNITY_INTEGRATION_FAULTS=enabled\n")
    elif change == "test-provider":
        file = target / "community-web.env.example"
        file.write_text(
            file.read_text() + "COMMUNITY_P0_TEST_PDS_ORIGIN=https://juche.social\n"
        )
    elif change == "unpaused":
        (target / "p0-site-state").write_text("open\n")
    elif change == "policy-peer":
        file = target / "communityd.toml"
        file.write_text(file.read_text() + "policy_peer_uid = 42002\n")
    elif change == "observer-test":
        file = target / "communitywatch.toml"
        file.write_text(
            file.read_text()
            + 'p0_isolated_test = true\np0_test_pds_origin = "https://juche.social"\n'
        )
    elif change == "missing-mixed-flag":
        file = target / "community-web.env.example"
        file.write_text(
            file.read_text().replace("COMMUNITY_P0_ALLOW_BLUESKY=true\n", "")
        )
    elif change == "observer-bluesky-only":
        file = target / "communitywatch.toml"
        file.write_text(file.read_text() + "p0_bluesky_only = true\n")
    elif change == "wrong-hosted-origin":
        file = target / "communityd.toml"
        file.write_text(
            file.read_text().replace(
                'p0_hosted_pds_origin = "https://phlogiston.social"',
                'p0_hosted_pds_origin = "https://other.social"',
            )
        )
    else:
        file = target / "communitywatch.toml"
        file.write_text(
            file.read_text().replace(
                "wss://jetstream.us-east.bsky.network",
                "wss://jetstream2.us-east.bsky.network/subscribe",
            )
        )
    with pytest.raises(ValueError):
        validator.validate_p0_bundle(tmp_path)


def test_receipt_profiles_cannot_be_substituted():
    value = campaign()
    receipt = validator.build_receipt(value)
    validator.validate_receipt(receipt)
    validator.validate_receipt_binding(receipt, value)
    with pytest.raises(validator.ValidationFailure, match="pass status"):
        validator.validate_receipt(receipt, complete=True)
    receipt["schema"] = validator.RECEIPT_SCHEMA
    with pytest.raises(validator.ValidationFailure, match="profile"):
        validator.validate_receipt_binding(receipt, value)


def test_public_p0_host_preflight_refuses_unmasked_optional_workers():
    value = campaign()
    for unit in validator.P0_DISABLED_UNITS:
        with pytest.raises(validator.ValidationFailure, match="absent or masked"):
            validator.validate_host_principals(value, {unit: ["User=unused"]})


def test_p0_pause_template_must_be_regular(tmp_path):
    target = copy_bundle(tmp_path)
    path = target / "p0-site-state"
    path.unlink()
    path.mkdir()
    with pytest.raises(validator.ValidationFailure, match="regular"):
        validator.validate_p0_bundle(tmp_path)


def test_p0_pass_status_requires_named_evidence():
    receipt = validator.build_receipt(campaign())
    receipt["checks"][0]["status"] = "pass"
    with pytest.raises(validator.ValidationFailure, match="requires evidence"):
        validator.validate_receipt(receipt)
