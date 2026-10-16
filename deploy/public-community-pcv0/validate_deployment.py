#!/usr/bin/env python3
"""Offline validation and receipt scaffolding for the PCV0 deployment.

This program performs no DNS, HTTP, OAuth, PDS, or systemd operation.  It
validates committed examples or operator-supplied, secret-free campaign and
receipt JSON.  The ``host-preflight`` command additionally reads installed
unit files and the passwd database, and nothing else.  Credential files are
deliberately outside its interface.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlsplit

from community_model.identifiers import parse_at_uri, parse_rfc3339, validate_cid
from community_notify.config import NotifyConfig
from community_policy.config import PolicyConfig
from communityd.config import load_config as load_daemon_config
from communitywatch.config import load_config as load_observer_config

COMMUNITY_DID = "did:plc:exampleparticipantabcdef"
COMMUNITY_HANDLE = "participant.example.com"
COMMUNITY_PDS = "https://phellinus.us-west.host.bsky.network"
P0_COMMUNITY_DID = "did:plc:yrdhg6whfezek67fchtrmqgu"
P0_COMMUNITY_HANDLE = "curator-20261011.phlogiston.social"
P0_HOSTED_PDS = "https://phlogiston.social"
PUBLIC_ORIGIN = "https://phlogiston.app"
LEXICON_DNS_NAME = "_lexicon.community.phlogiston.app"
CAMPAIGN_SCHEMA = "pcv0-integration-campaign-v1"
RECEIPT_SCHEMA = "pcv0-integration-receipt-v1"
P0_CAMPAIGN_SCHEMA = "phlogiston-p0-campaign-v1"
P0_RECEIPT_SCHEMA = "phlogiston-p0-receipt-v1"
P0_CHECK_IDS = (
    "publication",
    "bluesky-oauth",
    "authorized-submit-write",
    "unknown-did-actual-stream",
    "bounded-fair-intake",
    "admit-decline-render",
    "identity-custody-scopes",
    "duplicate-and-uncertain-writes",
    "observer-recovery",
    "pause-readonly-and-removal",
    "notifier-absent",
    "host-loss-and-rollback",
)
P0_WEB_KEYS = frozenset(
    {
        "COMMUNITY_PROFILE",
        "COMMUNITY_SITE_PAUSE_PATH",
        "COMMUNITY_ADMISSION_PAUSE_PATH",
        "COMMUNITY_P0_HOSTED_PDS_ORIGIN",
        "COMMUNITY_P0_ALLOW_BLUESKY",
    }
)
P0_DISABLED_UNITS = frozenset({"community-policy.service", "community-notify.service"})
P0_LEXICON_SHA256 = {
    "app.phlogiston.community.admission": "fe9b1a8bdf4b60e7b7cb588b862c624e7ee71f70bb77c1a4a723d8a3d8baedd9",
    "app.phlogiston.community.memberAction": "549ef10d92c04dbf5b020003bcbd62c8edc9e2eb0397268cbf85e23898038fe1",
    "app.phlogiston.community.modAction": "e7879aed2706e35a65ebf97cd5c94fdd3c8e4f54cb84e00a5d821c704f94915f",
    "app.phlogiston.community.profile": "e1c9a1e30aefab5f579bef2cc2caa069fe1c102a2692776b47f96db32b537d3a",
    "app.phlogiston.community.replyAction": "0353e6f3c8af0c7760952009eff377966009600ea32bbd147fea2e5b69070bdb",
    "app.phlogiston.community.replyAdmission": "4f8e4cd50d9f39768a04ec281d26cc02bfceb5796d7752e0f8f4a27606aef6e1",
    "app.phlogiston.community.replyPolicy": "5f8b5a724339d0893b6612bb0ac656e305eb117b390459c6773f09215b8c7332",
    "app.phlogiston.community.submit": "0d1cb4ed8b80a77332904f24ed701d8731950f491999dbbf46ff7c604b6d3c96",
}

CAMPAIGN_KEYS = frozenset(
    {
        "schema",
        "campaignId",
        "publicOrigin",
        "communityActor",
        "schemaAuthority",
        "servicePrincipals",
        "integrationIdentities",
        "publicationEvidence",
        "humanDogfood",
    }
)
RECEIPT_KEYS = frozenset(
    {
        "schema",
        "campaignId",
        "status",
        "completedAt",
        "communityDid",
        "schemaAuthorityDid",
        "participants",
        "serviceVersions",
        "checks",
        "publicRecords",
        "humanDogfood",
        "nonClaims",
    }
)
CHECK_IDS = (
    "publication",
    "oauth-cross-pds",
    "root-post-and-admission",
    "automatic-reply-admission",
    "fresh-session-unread",
    "reply-remove-source-unchanged",
    "reply-restore",
    "participant-unknown-write-recovery",
    "authority-unknown-write-recovery",
    "full-service-restart",
)
WEB_ENV_KEYS = frozenset(
    {
        "COMMUNITY_PUBLIC_URL",
        "COMMUNITY_DID",
        "COMMUNITY_NAME",
        "COMMUNITY_PURPOSE",
        "COMMUNITY_MODERATOR_DID",
        "COMMUNITY_RUNTIME_DIR",
        "COMMUNITY_OBSERVER_URL",
        "COMMUNITY_AUTHORITY_SOCKET",
        "COMMUNITY_SNAPSHOT_SECRET",
        "PORT",
    }
)
# Campaign-only post-commit crash hooks.  Both processes treat their absence as
# hooks disabled; community-live accepts no explicit "disabled" value.
WEB_FAULT_KEYS = frozenset(
    {"COMMUNITY_INTEGRATION_FAULTS", "COMMUNITY_INTEGRATION_FAULT_DIR"}
)
WEB_FAULT_DIRECTORY = "/var/lib/community-web/integration-faults"
# community-live runs the installed tsx binary directly.  corepack keeps its
# cache in the user's home and may fetch pnpm, neither of which the unit's
# ProtectSystem=strict/ProtectHome=true sandbox permits.
LIVE_WORKING_DIRECTORY = "/opt/atproto-community/apps/community-live"
LIVE_EXEC_START = f"{LIVE_WORKING_DIRECTORY}/node_modules/.bin/tsx src/server.ts"
# Campaign servicePrincipals key -> the unit files that must run as that UID.
PRINCIPAL_UNITS: Mapping[str, tuple[str, ...]] = {
    "communityWebUid": ("community-live.service",),
    "communityPolicyUid": ("community-policy.service",),
    "communitydUid": ("communityd.service",),
    "communitywatchUid": (
        "communitywatch-index.service",
        "communitywatch-web.service",
    ),
    "communityNotifyUid": ("community-notify.service",),
}
PRINCIPAL_KEYS = frozenset(PRINCIPAL_UNITS)
P0_PRINCIPAL_KEYS = PRINCIPAL_KEYS - {"communityPolicyUid", "communityNotifyUid"}
# systemd unit load path, highest precedence first, relative to the host root.
UNIT_DIRECTORIES = (
    "etc/systemd/system",
    "run/systemd/system",
    "usr/local/lib/systemd/system",
    "usr/lib/systemd/system",
    "lib/systemd/system",
)
REQUIRED_UNIT_DIRECTORIES = frozenset({"etc/systemd/system", "usr/lib/systemd/system"})
AUTHORITY_UNIT = "communityd.service"
# Any of these in an ExecStart= marks a unit as a community writer: the
# console script, or the module it wraps started through the interpreter
# (``python -m communityd.serve_cli``, ``-c "... communityd.serve_cli ..."``).
AUTHORITY_COMMAND = "communityd-serve"
AUTHORITY_COMMAND_MARKERS = (AUTHORITY_COMMAND, "communityd.serve_cli")
# Units of the phlogiston kit that were withdrawn for Phase 2 because they
# would run a second community writer beside PCV0's communityd.service.
WITHDRAWN_UNITS = ("phlogiston-communityd.service",)
AUTHORITY_FAULT_DIRECTORY = "/var/lib/communityd/integration-faults"
SECRET_KEY_PARTS = (
    "authorization",
    "cookie",
    "password",
    "privatekey",
    "refreshtoken",
    "secret",
    "session",
    "token",
)
PLACEHOLDER_MARKERS = ("replace-with", "replacewith", ".invalid")
_DID = re.compile(r"^did:(?:plc|web):[^\s/]+$")


class ValidationFailure(ValueError):
    """One deployment artifact failed closed validation."""


def fail(message: str) -> NoReturn:
    raise ValidationFailure(message)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except OSError as exc:
        fail(f"cannot read {path}: {exc.strerror or exc}")
    except (UnicodeError, json.JSONDecodeError) as exc:
        fail(f"invalid UTF-8 JSON in {path}: {exc}")


def _object(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        fail(f"{where} must be an object")
    return value


def _exact(value: Mapping[str, object], keys: frozenset[str], where: str) -> None:
    actual = set(value)
    if actual != keys:
        fail(
            f"{where} fields differ: missing={sorted(keys - actual)!r} unknown={sorted(actual - keys)!r}"
        )


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{where} must be a nonempty string")
    return value


def _did(value: object, where: str) -> str:
    result = _text(value, where)
    if _DID.fullmatch(result) is None:
        fail(f"{where} must be a did:plc or did:web DID")
    return result


def _origin(value: object, where: str) -> str:
    result = _text(value, where)
    parsed = urlsplit(result)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        fail(f"{where} must be a bare HTTPS origin")
    return result.rstrip("/")


def _absolute(value: object, where: str) -> str:
    result = _text(value, where)
    if not Path(result).is_absolute():
        fail(f"{where} must be an absolute path")
    return result


def _contains_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def _reject_placeholders(value: object, where: str = "campaign") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_placeholders(child, f"{where}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_placeholders(child, f"{where}[{index}]")
    elif isinstance(value, str) and _contains_placeholder(value):
        fail(f"{where} is unresolved")


def _bluesky_pds(value: object, where: str) -> str:
    origin = _origin(value, where)
    parsed = urlsplit(origin)
    if not parsed.hostname.endswith(".host.bsky.network") or parsed.port not in (
        None,
        443,
    ):
        fail(f"{where} must be a Bluesky-operated PDS; no alternate hosting fallback")
    return origin


def _publication_digest(value: object) -> str:
    # The publisher's stable JSON for these frozen ASCII-keyed documents.
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_p0_publication_evidence(
    evidence: Mapping[str, object], authority_did: str
) -> None:
    """Bind the three local publication artifacts; provider readback is separate."""
    manifest = _object(
        load_json(Path(str(evidence["manifestPath"]))), "publication manifest"
    )
    _exact(
        manifest,
        frozenset(
            {
                "contract",
                "namespaceAuthority",
                "dnsName",
                "dnsTxt",
                "authorityDid",
                "collection",
                "documents",
            }
        ),
        "publication manifest",
    )
    if (
        manifest["contract"],
        manifest["namespaceAuthority"],
        manifest["dnsName"],
        manifest["dnsTxt"],
        manifest["authorityDid"],
        manifest["collection"],
    ) != (
        "pcv0-lexicon-publication-manifest/1",
        "community.phlogiston.app",
        LEXICON_DNS_NAME,
        f"did={authority_did}",
        authority_did,
        "com.atproto.lexicon.schema",
    ):
        fail("P0 publication manifest authority or namespace differs")
    documents = manifest["documents"]
    if not isinstance(documents, list) or len(documents) != len(P0_LEXICON_SHA256):
        fail("P0 publication manifest must contain eight frozen Lexicons")
    seen: set[str] = set()
    for item in documents:
        entry = _object(item, "publication document")
        _exact(
            entry,
            frozenset(
                {"nsid", "rkey", "documentSha256", "recordSha256", "uri", "document"}
            ),
            "publication document",
        )
        nsid = _text(entry["nsid"], "publication document NSID")
        if nsid not in P0_LEXICON_SHA256 or nsid in seen:
            fail("P0 publication manifest has unknown or duplicate Lexicon")
        seen.add(nsid)
        document = _object(entry["document"], "publication Lexicon")
        _exact(document, frozenset({"defs", "id", "lexicon"}), "publication Lexicon")
        if (
            document["id"] != nsid
            or document["lexicon"] != 1
            or not isinstance(document["defs"], dict)
        ):
            fail("P0 publication Lexicon envelope differs")
        uri = f"at://{authority_did}/com.atproto.lexicon.schema/{nsid}"
        if (
            entry["rkey"],
            entry["uri"],
            entry["documentSha256"],
            entry["recordSha256"],
        ) != (
            nsid,
            uri,
            f"sha256:{P0_LEXICON_SHA256[nsid]}",
            _publication_digest({"$type": "com.atproto.lexicon.schema", **document}),
        ) or _publication_digest(document) != entry["documentSha256"]:
            fail("P0 publication document differs from the frozen source or URI")
    digest = _publication_digest(manifest)
    acceptance = _object(
        load_json(Path(str(evidence["acceptancePath"]))), "publication acceptance"
    )
    _exact(
        acceptance,
        frozenset(
            {"contract", "manifestSha256", "authorityDid", "acceptedBy", "acceptedAt"}
        ),
        "publication acceptance",
    )
    if (
        acceptance["contract"],
        acceptance["manifestSha256"],
        acceptance["authorityDid"],
    ) != ("pcv0-lexicon-publication-acceptance/1", digest, authority_did):
        fail("P0 publication acceptance does not bind the manifest")
    _text(acceptance["acceptedBy"], "publication acceptor")
    parse_rfc3339(acceptance["acceptedAt"], path=("acceptedAt",))
    receipt = _object(
        load_json(Path(str(evidence["receiptPath"]))), "publication receipt"
    )
    _exact(
        receipt,
        frozenset(
            {
                "contract",
                "manifestSha256",
                "authorityDid",
                "namespaceAuthority",
                "dns",
                "records",
                "completedAt",
                "explicitNonClaims",
            }
        ),
        "publication receipt",
    )
    if (
        receipt["contract"],
        receipt["manifestSha256"],
        receipt["authorityDid"],
        receipt["namespaceAuthority"],
    ) != (
        "pcv0-lexicon-publication-receipt/1",
        digest,
        authority_did,
        "community.phlogiston.app",
    ):
        fail("P0 publication receipt does not bind the accepted manifest")
    dns = _object(receipt["dns"], "publication DNS receipt")
    _exact(
        dns,
        frozenset({"name", "expected", "answers", "verified"}),
        "publication DNS receipt",
    )
    if (
        (dns["name"], dns["expected"], dns["verified"])
        != (LEXICON_DNS_NAME, f"did={authority_did}", True)
        or not isinstance(dns["answers"], list)
        or dns["answers"].count(f"did={authority_did}") != 1
    ):
        fail("P0 publication DNS receipt does not bind the namespace")
    records = receipt["records"]
    if not isinstance(records, list) or len(records) != len(documents):
        fail("P0 publication receipt lacks eight record readbacks")
    for item, record in zip(documents, records, strict=True):
        row = _object(record, "publication record receipt")
        _exact(
            row,
            frozenset({"nsid", "documentSha256", "uri", "cid", "disposition"}),
            "publication record receipt",
        )
        if (row["nsid"], row["documentSha256"], row["uri"]) != (
            item["nsid"],
            item["documentSha256"],
            item["uri"],
        ):
            fail("P0 publication record readback differs from the manifest")
        validate_cid(row["cid"], require_dag_cbor=True, path=("publication", "cid"))
        if row["disposition"] not in {"created", "read_back"}:
            fail("P0 publication record disposition is invalid")
    parse_rfc3339(receipt["completedAt"], path=("completedAt",))
    if (
        not isinstance(receipt["explicitNonClaims"], list)
        or not receipt["explicitNonClaims"]
    ):
        fail("P0 publication receipt lacks explicit non-claims")


def validate_campaign(value: object, *, ready: bool = False) -> dict[str, object]:
    campaign = _object(value, "campaign")
    _exact(campaign, CAMPAIGN_KEYS, "campaign")
    p0 = campaign["schema"] == P0_CAMPAIGN_SCHEMA
    if campaign["schema"] not in {CAMPAIGN_SCHEMA, P0_CAMPAIGN_SCHEMA}:
        fail("campaign.schema is unsupported")
    _text(campaign["campaignId"], "campaign.campaignId")
    if _origin(campaign["publicOrigin"], "campaign.publicOrigin") != PUBLIC_ORIGIN:
        fail("campaign.publicOrigin must be the PCV0 origin")

    actor = _object(campaign["communityActor"], "campaign.communityActor")
    _exact(actor, frozenset({"did", "handle", "pdsOrigin"}), "campaign.communityActor")
    expected_actor = {
        "did": P0_COMMUNITY_DID if p0 else COMMUNITY_DID,
        "handle": P0_COMMUNITY_HANDLE if p0 else COMMUNITY_HANDLE,
        "pdsOrigin": P0_HOSTED_PDS if p0 else COMMUNITY_PDS,
    }
    if actor != expected_actor:
        fail("campaign.communityActor differs from the selected actor for this profile")

    authority = _object(campaign["schemaAuthority"], "campaign.schemaAuthority")
    _exact(
        authority,
        frozenset({"did", "handle", "dnsName", "expectedTxt"})
        | ({"pdsOrigin"} if p0 else set()),
        "campaign.schemaAuthority",
    )
    authority_did = _did(authority["did"], "campaign.schemaAuthority.did")
    if p0:
        if authority["handle"] != "lexicon.phlogiston.app":
            fail("P0 requires the approved dedicated publisher handle")
        if authority["pdsOrigin"] != P0_HOSTED_PDS:
            fail("P0 publisher must use the exact hosted Phlogiston PDS")
    _text(authority["handle"], "campaign.schemaAuthority.handle")
    if authority["dnsName"] != LEXICON_DNS_NAME:
        fail("campaign.schemaAuthority.dnsName is not the selected namespace")
    if authority["expectedTxt"] != f"did={authority_did}":
        fail("campaign.schemaAuthority.expectedTxt does not bind its DID")
    if authority_did == actor["did"]:
        fail("schema authority and community actor must be distinct")

    principals = _object(campaign["servicePrincipals"], "campaign.servicePrincipals")
    _exact(
        principals,
        P0_PRINCIPAL_KEYS if p0 else PRINCIPAL_KEYS,
        "campaign.servicePrincipals",
    )
    uids = list(principals.values())
    if any(
        isinstance(uid, bool) or not isinstance(uid, int) or uid < 0 for uid in uids
    ):
        fail("campaign service UIDs must be nonnegative integers")
    if len(set(uids)) != len(uids):
        fail("campaign service UIDs must be pairwise distinct")

    identities = campaign["integrationIdentities"]
    if not isinstance(identities, list) or len(identities) != 2:
        fail("campaign.integrationIdentities must contain exactly two identities")
    seen_roles: set[str] = set()
    seen_dids: set[str] = set()
    seen_origins: set[str] = set()
    for index, raw_identity in enumerate(identities):
        identity = _object(raw_identity, f"campaign.integrationIdentities[{index}]")
        _exact(
            identity,
            frozenset({"role", "did", "handle", "pdsOrigin", "controller"}),
            f"campaign.integrationIdentities[{index}]",
        )
        role = _text(identity["role"], f"campaign.integrationIdentities[{index}].role")
        if role not in {"moderator", "participant"} or role in seen_roles:
            fail("campaign identities require one moderator and one participant")
        seen_roles.add(role)
        identity_did = _did(
            identity["did"], f"campaign.integrationIdentities[{index}].did"
        )
        origin = _origin(
            identity["pdsOrigin"], f"campaign.integrationIdentities[{index}].pdsOrigin"
        )
        if p0 and role == "moderator":
            if (identity_did, identity["handle"], origin) != (
                P0_COMMUNITY_DID,
                P0_COMMUNITY_HANDLE,
                P0_HOSTED_PDS,
            ):
                fail("P0 moderator must be the selected community actor")
        elif p0:
            _bluesky_pds(origin, f"campaign.integrationIdentities[{index}].pdsOrigin")
            if (identity_did, identity["handle"], origin) != (
                COMMUNITY_DID,
                COMMUNITY_HANDLE,
                COMMUNITY_PDS,
            ):
                fail("P0 participant must be the selected participant Bluesky identity")
        _text(identity["handle"], f"campaign.integrationIdentities[{index}].handle")
        _text(
            identity["controller"],
            f"campaign.integrationIdentities[{index}].controller",
        )
        if identity_did in seen_dids or origin in seen_origins:
            fail("campaign identities require distinct DIDs and PDS origins")
        if identity_did == authority_did or (not p0 and identity_did == COMMUNITY_DID):
            fail(
                "campaign participant identities must be separate from authority identities"
            )
        seen_dids.add(identity_did)
        seen_origins.add(origin)
    if seen_roles != {"moderator", "participant"}:
        fail("campaign identities require one moderator and one participant")

    evidence = _object(campaign["publicationEvidence"], "campaign.publicationEvidence")
    _exact(
        evidence,
        frozenset({"manifestPath", "acceptancePath", "receiptPath"}),
        "campaign.publicationEvidence",
    )
    for key, path in evidence.items():
        _absolute(path, f"campaign.publicationEvidence.{key}")
    if len(set(evidence.values())) != 3:
        fail("publication evidence paths must be distinct")

    dogfood = _object(campaign["humanDogfood"], "campaign.humanDogfood")
    _exact(
        dogfood,
        frozenset({"status", "maintainers", "topic", "activity"}),
        "campaign.humanDogfood",
    )
    maintainers = dogfood["maintainers"]
    if not isinstance(maintainers, list):
        fail("campaign.humanDogfood.maintainers must be a list")
    if dogfood["status"] == "BLOCKED_MISSING_PARTICIPANTS":
        if (
            maintainers
            or dogfood["topic"] is not None
            or dogfood["activity"] is not None
        ):
            fail("blocked human dogfood must not fabricate participants or activity")
    elif dogfood["status"] == "ready":
        if len(maintainers) != 2 or len(set(maintainers)) != 2:
            fail("ready human dogfood requires two distinct named maintainers")
        _text(dogfood["topic"], "campaign.humanDogfood.topic")
        _text(dogfood["activity"], "campaign.humanDogfood.activity")
    else:
        fail("campaign.humanDogfood.status is unsupported")

    if p0 and dogfood["status"] != "BLOCKED_MISSING_PARTICIPANTS":
        fail("P0 does not promote the historical human dogfood claim")
    if ready:
        _reject_placeholders(campaign)
        if p0:
            validate_p0_publication_evidence(evidence, authority_did)
    return campaign


def _reject_secrets(value: object, where: str = "receipt") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z]", "", key.lower())
            if any(part in normalized for part in SECRET_KEY_PARTS):
                fail(f"{where}.{key} is a forbidden secret-bearing field")
            _reject_secrets(child, f"{where}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secrets(child, f"{where}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if (
            lowered.startswith(("bearer ", "basic ", "sk-"))
            or "authorization_code=" in lowered
        ):
            fail(f"{where} appears to contain secret material")


def validate_receipt(value: object, *, complete: bool = False) -> dict[str, object]:
    receipt = _object(value, "receipt")
    _exact(receipt, RECEIPT_KEYS, "receipt")
    _reject_secrets(receipt)
    p0 = receipt["schema"] == P0_RECEIPT_SCHEMA
    check_ids = P0_CHECK_IDS if p0 else CHECK_IDS
    if receipt["schema"] not in {RECEIPT_SCHEMA, P0_RECEIPT_SCHEMA}:
        fail("receipt.schema is unsupported")
    _text(receipt["campaignId"], "receipt.campaignId")
    if receipt["communityDid"] != (P0_COMMUNITY_DID if p0 else COMMUNITY_DID):
        fail("receipt.communityDid is not the selected community actor")
    _did(receipt["schemaAuthorityDid"], "receipt.schemaAuthorityDid")
    if receipt["status"] not in {"pending", "pass", "fail", "blocked"}:
        fail("receipt.status is unsupported")
    if receipt["completedAt"] is not None:
        parse_rfc3339(receipt["completedAt"], path=("completedAt",))

    participants = receipt["participants"]
    if not isinstance(participants, list) or len(participants) != 2:
        fail("receipt.participants must contain exactly two identities")
    roles: list[str] = []
    dids: list[str] = []
    origins: list[str] = []
    for index, raw in enumerate(participants):
        participant = _object(raw, f"receipt.participants[{index}]")
        _exact(
            participant,
            frozenset({"role", "did", "pdsOrigin"}),
            f"receipt.participants[{index}]",
        )
        roles.append(_text(participant["role"], f"receipt.participants[{index}].role"))
        dids.append(_did(participant["did"], f"receipt.participants[{index}].did"))
        origins.append(
            _origin(
                participant["pdsOrigin"], f"receipt.participants[{index}].pdsOrigin"
            )
        )
    if (
        set(roles) != {"moderator", "participant"}
        or len(set(dids)) != 2
        or len(set(origins)) != 2
    ):
        fail(
            "receipt participants must be distinct cross-PDS moderator/participant identities"
        )

    if p0:
        by_role = dict(zip(roles, zip(dids, origins), strict=True))
        if by_role["moderator"] != (P0_COMMUNITY_DID, P0_HOSTED_PDS):
            fail("P0 receipt moderator must be the selected hosted actor")
        if by_role["participant"] != (COMMUNITY_DID, COMMUNITY_PDS):
            fail("P0 receipt participant must be the selected participant Bluesky identity")
    versions = _object(receipt["serviceVersions"], "receipt.serviceVersions")
    for component, version in versions.items():
        _text(component, "receipt.serviceVersions key")
        _text(version, f"receipt.serviceVersions.{component}")

    checks = receipt["checks"]
    if not isinstance(checks, list) or len(checks) != len(check_ids):
        fail("receipt.checks must contain the complete fixed journey")
    observed_ids: list[str] = []
    check_statuses: list[str] = []
    for index, raw in enumerate(checks):
        check = _object(raw, f"receipt.checks[{index}]")
        _exact(
            check, frozenset({"id", "status", "evidence"}), f"receipt.checks[{index}]"
        )
        observed_ids.append(_text(check["id"], f"receipt.checks[{index}].id"))
        status = _text(check["status"], f"receipt.checks[{index}].status")
        if status not in {"pending", "pass", "fail"}:
            fail(f"receipt.checks[{index}].status is unsupported")
        check_statuses.append(status)
        evidence = check["evidence"]
        if not isinstance(evidence, list) or any(
            not isinstance(item, str) or not item for item in evidence
        ):
            fail(f"receipt.checks[{index}].evidence must be a string list")
        if p0 and status == "pass" and not evidence:
            fail(f"receipt.checks[{index}] passing P0 check requires evidence")
    if tuple(observed_ids) != check_ids:
        fail("receipt checks are missing, reordered, or substituted")

    records = receipt["publicRecords"]
    if not isinstance(records, list):
        fail("receipt.publicRecords must be a list")
    for index, raw in enumerate(records):
        record = _object(raw, f"receipt.publicRecords[{index}]")
        _exact(
            record, frozenset({"role", "uri", "cid"}), f"receipt.publicRecords[{index}]"
        )
        _text(record["role"], f"receipt.publicRecords[{index}].role")
        parse_at_uri(record["uri"], path=("publicRecords", index, "uri"))
        validate_cid(
            record["cid"],
            require_dag_cbor=True,
            path=("publicRecords", index, "cid"),
        )

    dogfood = _object(receipt["humanDogfood"], "receipt.humanDogfood")
    _exact(dogfood, frozenset({"status", "receipt"}), "receipt.humanDogfood")
    if (
        dogfood["status"] != "BLOCKED_MISSING_PARTICIPANTS"
        or dogfood["receipt"] is not None
    ):
        fail("integration receipt must keep the separate human campaign blocked")
    non_claims = receipt["nonClaims"]
    if not isinstance(non_claims, list) or len(non_claims) < 3:
        fail("receipt.nonClaims must retain the bounded campaign non-claims")
    for index, claim in enumerate(non_claims):
        _text(claim, f"receipt.nonClaims[{index}]")

    if complete:
        if receipt["status"] != "pass" or receipt["completedAt"] is None:
            fail("complete receipt requires pass status and completedAt")
        if any(status != "pass" for status in check_statuses):
            fail("complete receipt requires every integration check to pass")
        if not versions or not records:
            fail(
                "complete receipt requires service versions and public record references"
            )
        _reject_placeholders(receipt)
    return receipt


def validate_receipt_binding(
    receipt: Mapping[str, object], campaign: Mapping[str, object]
) -> None:
    expected_schema = (
        P0_RECEIPT_SCHEMA
        if campaign["schema"] == P0_CAMPAIGN_SCHEMA
        else RECEIPT_SCHEMA
    )
    if receipt["schema"] != expected_schema:
        fail("receipt profile does not match the campaign")
    if receipt["campaignId"] != campaign["campaignId"]:
        fail("receipt campaign ID does not match the campaign")
    if receipt["communityDid"] != campaign["communityActor"]["did"]:
        fail("receipt community DID does not match the campaign")
    if receipt["schemaAuthorityDid"] != campaign["schemaAuthority"]["did"]:
        fail("receipt schema authority DID does not match the campaign")
    expected = [
        {
            "role": identity["role"],
            "did": identity["did"],
            "pdsOrigin": identity["pdsOrigin"],
        }
        for identity in campaign["integrationIdentities"]
    ]
    if receipt["participants"] != expected:
        fail("receipt participants do not match the campaign")


def _load_env_example(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            fail(f"{path}:{number} is not KEY=VALUE")
        key, value = line.split("=", 1)
        if not key or key in result:
            fail(f"{path}:{number} has an empty or duplicate key")
        result[key] = value
    return result


def validate_committed_bundle(root: Path) -> str:
    """Validate the bundle and return its fault mode: campaign or normal."""
    deployment = root / "deploy" / "public-community-pcv0"
    campaign = validate_campaign(load_json(deployment / "campaign.example.json"))
    validate_receipt(load_json(deployment / "integration-receipt.example.json"))

    daemon = load_daemon_config(deployment / "communityd.toml")
    observer = load_observer_config(deployment / "communitywatch.toml")
    policy = PolicyConfig.load(deployment / "community-policy.toml")
    web = _load_env_example(deployment / "community-web.env.example")
    if not WEB_ENV_KEYS <= set(web) <= WEB_ENV_KEYS | WEB_FAULT_KEYS:
        fail("community-web.env.example fields differ from the strict set")

    if {
        daemon.community_did,
        observer.community_did,
        policy.community_did,
        web["COMMUNITY_DID"],
    } != {COMMUNITY_DID}:
        fail("deployment components disagree about the community DID")
    if daemon.community_pds_url != COMMUNITY_PDS:
        fail("communityd does not target the selected community actor PDS")
    if web["COMMUNITY_PUBLIC_URL"] != PUBLIC_ORIGIN:
        fail("community-live does not use the selected public origin")
    moderator = next(
        identity
        for identity in campaign["integrationIdentities"]
        if identity["role"] == "moderator"
    )
    if {
        daemon.administrator_did,
        observer.administrator_did,
        web["COMMUNITY_MODERATOR_DID"],
    } != {moderator["did"]}:
        fail("deployment components disagree about the moderator DID")
    principals = campaign["servicePrincipals"]
    if daemon.allowed_uid != principals["communitydUid"]:
        fail("communityd local authorizer UID must equal the authority process UID")
    if (
        daemon.web_peer_uid != principals["communityWebUid"]
        or daemon.policy_peer_uid != principals["communityPolicyUid"]
    ):
        fail("communityd peer UIDs disagree with the campaign")
    if observer.bind not in {"127.0.0.1", "::1", "localhost"}:
        fail("observer API must bind to loopback")
    if policy.observer_origin != web["COMMUNITY_OBSERVER_URL"]:
        fail("policy and browser must use the same loopback observer origin")
    if (
        str(policy.authority_socket) != web["COMMUNITY_AUTHORITY_SOCKET"]
        or daemon.authority_socket_path != web["COMMUNITY_AUTHORITY_SOCKET"]
    ):
        fail("requesters and communityd disagree about the authority socket")
    mode = fault_mode(web, daemon.integration_fault_directory)
    _validate_live_unit(deployment)
    _validate_notifier(deployment, web)
    caddy = (deployment / "Caddyfile.fragment").read_text(encoding="utf-8")
    if not caddy.startswith(f"{PUBLIC_ORIGIN.removeprefix('https://')} {{\n"):
        fail("Caddyfile does not expose the exact selected hostname")
    return mode


def validate_p0_bundle(root: Path) -> str:
    """Validate the inert public profile; no notifier, policy worker or test seams."""
    deployment = root / "deploy" / "public-community-pcv0" / "p0"
    campaign = validate_campaign(load_json(deployment / "campaign.example.json"))
    if campaign["schema"] != P0_CAMPAIGN_SCHEMA:
        fail("P0 bundle requires its own campaign schema")
    receipt = validate_receipt(
        load_json(deployment / "integration-receipt.example.json")
    )
    validate_receipt_binding(receipt, campaign)
    for name in (
        "community-notify.service",
        "community-notify.toml",
        "community-policy.service",
        "community-policy.toml",
    ):
        if (deployment / name).exists():
            fail("P0 notifier and policy files must be absent")
    web = _load_env_example(deployment / "community-web.env.example")
    if set(web) != WEB_ENV_KEYS | P0_WEB_KEYS:
        fail("P0 browser configuration differs from the strict set")
    if web["COMMUNITY_PROFILE"] != "p0":
        fail("P0 browser profile must be explicit")
    if (web["COMMUNITY_P0_HOSTED_PDS_ORIGIN"], web["COMMUNITY_P0_ALLOW_BLUESKY"]) != (
        P0_HOSTED_PDS,
        "true",
    ):
        fail(
            "P0 browser must explicitly select hosted Phlogiston and Bluesky interoperation"
        )
    if web["COMMUNITY_PUBLIC_URL"] != PUBLIC_ORIGIN:
        fail("P0 must use the selected participant origin")
    if web["COMMUNITY_SITE_PAUSE_PATH"] != "/etc/atproto-community/p0-site-state":
        fail("P0 site pause path must be operator-controlled")
    if (
        web["COMMUNITY_ADMISSION_PAUSE_PATH"]
        != "/etc/atproto-community/p0-admission-state"
    ):
        fail("P0 admission pause must match the authority control")
    daemon = load_daemon_config(deployment / "communityd.toml")
    observer = load_observer_config(deployment / "communitywatch.toml")
    moderator = next(
        item
        for item in campaign["integrationIdentities"]
        if item["role"] == "moderator"
    )
    if {daemon.community_did, observer.community_did, web["COMMUNITY_DID"]} != {
        P0_COMMUNITY_DID
    }:
        fail("P0 components disagree about the community DID")
    if {
        daemon.administrator_did,
        observer.administrator_did,
        web["COMMUNITY_MODERATOR_DID"],
    } != {moderator["did"]}:
        fail("P0 components disagree about the moderator DID")
    if daemon.community_pds_url != P0_HOSTED_PDS:
        fail("P0 writer must use the selected community actor PDS")
    if (
        daemon.p0_profile != "root_only"
        or daemon.p0_admission_pause_path != "/etc/atproto-community/p0-admission-state"
    ):
        fail("P0 authority needs the root-only profile and operator pause")
    if getattr(daemon, "p0_hosted_pds_origin", None) != P0_HOSTED_PDS or not getattr(
        daemon, "p0_allow_bluesky", False
    ):
        fail(
            "P0 authority must explicitly select hosted Phlogiston and Bluesky interoperation"
        )
    if daemon.allow_loopback_public_endpoints or getattr(
        daemon, "p0_test_pds_origin", None
    ):
        fail("P0 public profile must not enable isolated test providers")
    if (
        observer.p0_bluesky_only
        or getattr(observer, "p0_hosted_pds_origin", None) != P0_HOSTED_PDS
        or not getattr(observer, "p0_allow_bluesky", False)
        or getattr(observer, "p0_test_pds_origin", None)
        or getattr(observer, "p0_isolated_test", False)
    ):
        fail(
            "P0 public observer must use hosted Phlogiston and Bluesky without test overrides"
        )
    if observer.event_source_url != "wss://jetstream.us-east.bsky.network":
        fail("P0 observer requires the current Jetstream v2 base origin")
    if (
        observer.resolver_url != "https://plc.directory"
        or daemon.plc_directory_url != "https://plc.directory"
    ):
        fail("P0 must use the public DID directory")
    if (
        observer.bind != "127.0.0.1"
        or web["COMMUNITY_OBSERVER_URL"] != f"http://127.0.0.1:{observer.port}"
    ):
        fail("P0 observer must bind to the exact browser loopback origin")
    principals = campaign["servicePrincipals"]
    if (
        daemon.allowed_uid != principals["communitydUid"]
        or daemon.web_peer_uid != principals["communityWebUid"]
        or daemon.policy_peer_uid is not None
    ):
        fail("P0 authority peer principals differ or retain a policy peer")
    if daemon.authority_socket_path != web["COMMUNITY_AUTHORITY_SOCKET"]:
        fail("P0 browser and authority sockets differ")
    if fault_mode(web, daemon.integration_fault_directory) != "normal":
        fail("P0 must disable qualification fault injection")
    _validate_live_unit(deployment)
    for name in ("p0-site-state", "p0-admission-state"):
        path = deployment / name
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_mode & 0o022
            or path.read_bytes() != b"paused\n"
        ):
            fail("P0 shipped pause controls must be regular non-writable paused files")
    caddy = (deployment / "Caddyfile.fragment").read_text()
    if not caddy.startswith("phlogiston.app {\n") or "phlogiston.social" in caddy:
        fail("P0 Caddy scope must be the selected participant origin only")
    for name in (
        "community-live.service",
        "communityd.service",
        "communitywatch-index.service",
        "communitywatch-web.service",
    ):
        lines = _unit_lines(deployment / name)
        if any(
            "community-policy" in line or "community-notify" in line for line in lines
        ):
            fail("P0 service startup must not require notifier or reply policy")
    return "p0"


def fault_mode(web: Mapping[str, str], authority_directory: str | None) -> str:
    """Classify the integration fault hooks as exactly campaign or normal.

    Campaign mode arms both post-commit hooks at their fixed directories.
    Normal mode leaves every hook setting absent on both sides.  Any other
    combination is a hybrid that proves neither shape and is refused.
    """
    web_keys = WEB_FAULT_KEYS & set(web)
    if not web_keys and authority_directory is None:
        return "normal"
    if not web_keys:
        fail(
            "communityd names an integration_fault_directory but the browser"
            " fault settings are absent; arm both sides or neither"
        )
    if web_keys != WEB_FAULT_KEYS:
        fail(
            "browser integration fault settings must be both present or both absent;"
            f" found only {sorted(web_keys)!r}"
        )
    if (
        web["COMMUNITY_INTEGRATION_FAULTS"] != "enabled"
        or web["COMMUNITY_INTEGRATION_FAULT_DIR"] != WEB_FAULT_DIRECTORY
    ):
        fail("browser integration fault boundary is not explicitly configured")
    if authority_directory is None:
        fail(
            "browser integration faults are enabled but communityd has no"
            " integration_fault_directory; arm both sides or neither"
        )
    if authority_directory != AUTHORITY_FAULT_DIRECTORY:
        fail("authority integration fault boundary is not explicitly configured")
    return "campaign"


def _unit_lines(unit_path: Path) -> list[str]:
    try:
        text = unit_path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read {unit_path}: {exc.strerror or exc}")
    return [line.strip() for line in text.splitlines()]


def _validate_live_unit(deployment: Path) -> None:
    lines = _unit_lines(deployment / "community-live.service")
    exec_starts = [line for line in lines if line.startswith("ExecStart=")]
    if exec_starts != [f"ExecStart={LIVE_EXEC_START}"]:
        fail(
            "community-live start path must run the installed tsx binary"
            f" directly: expected ExecStart={LIVE_EXEC_START}"
        )
    if f"WorkingDirectory={LIVE_WORKING_DIRECTORY}" not in lines:
        fail("community-live must start from its own application directory")
    if any("corepack" in line or "pnpm" in line for line in lines):
        fail("community-live unit must not depend on corepack or pnpm at start")


def _validate_notifier(deployment: Path, web: Mapping[str, str]) -> None:
    notify = NotifyConfig.load(deployment / "community-notify.toml")
    if notify.community_did != COMMUNITY_DID:
        fail("community-notify disagrees about the community DID")
    if notify.community_name != web["COMMUNITY_NAME"]:
        fail("community-notify and the browser disagree about the community name")
    if notify.public_base_url != PUBLIC_ORIGIN:
        fail("community-notify permalinks must use the selected public origin")
    if notify.projection_origin != web["COMMUNITY_OBSERVER_URL"]:
        fail("community-notify must read the same loopback observer origin")
    if notify.cursor_path.parent != Path("/var/lib/community-notify"):
        fail("community-notify cursor must live in its own state directory")
    unit = (deployment / "community-notify.service").read_text(encoding="utf-8")
    lines = {line.strip() for line in unit.splitlines()}
    if (
        "User=community-notify" not in lines
        or "Group=community-notify" not in lines
        or "ReadWritePaths=/var/lib/community-notify" not in lines
        or "community-authority" in unit
        or "EnvironmentFile" in unit
    ):
        fail("community-notify must run as its own principal without authority access")


def installed_units(root: Path) -> dict[str, Path | None]:
    """Map each installed ``.service`` name to its effective unit file.

    A masked unit maps to ``None``.  Higher-precedence directories shadow
    lower ones exactly as systemd loads them.  Any unit directory that
    exists but cannot be read, or a required one that is missing, fails
    closed: an unreadable load path cannot prove a single writer.
    """
    units: dict[str, Path | None] = {}
    for relative in UNIT_DIRECTORIES:
        directory = root / relative
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except FileNotFoundError:
            if relative in REQUIRED_UNIT_DIRECTORIES:
                fail(f"unit directory {directory} is missing")
            continue
        except OSError as exc:
            fail(f"cannot read unit directory {directory}: {exc.strerror or exc}")
        for entry in entries:
            if not entry.name.endswith(".service") or entry.name in units:
                continue
            if entry.is_symlink() and os.readlink(entry.path) == "/dev/null":
                units[entry.name] = None
            else:
                units[entry.name] = Path(entry.path)
    return units


def _unit_and_dropin_lines(root: Path, name: str, unit_path: Path) -> list[str]:
    lines = _unit_lines(unit_path)
    for relative in UNIT_DIRECTORIES:
        dropins = root / relative / f"{name}.d"
        try:
            entries = sorted(os.scandir(dropins), key=lambda entry: entry.name)
        except FileNotFoundError:
            continue
        except OSError as exc:
            fail(f"cannot read drop-in directory {dropins}: {exc.strerror or exc}")
        for entry in entries:
            if entry.name.endswith(".conf"):
                lines.extend(_unit_lines(Path(entry.path)))
    return lines


def _directive(lines: Sequence[str], key: str) -> list[str]:
    return [
        line[len(key) + 1 :].strip() for line in lines if line.startswith(f"{key}=")
    ]


def validate_host_units(root: Path) -> dict[str, list[str]]:
    """Refuse unless PCV0's communityd.service is the only community writer.

    Returns the effective directive lines of every installed, unmasked unit
    so callers can inspect ``User=`` without a second scan.
    """
    units = installed_units(root)
    lines_by_unit: dict[str, list[str]] = {}
    writers: list[str] = []
    for name, unit_path in units.items():
        if unit_path is None:
            continue
        lines = _unit_and_dropin_lines(root, name, unit_path)
        lines_by_unit[name] = lines
        if any(
            marker in command
            for command in _directive(lines, "ExecStart")
            for marker in AUTHORITY_COMMAND_MARKERS
        ):
            writers.append(name)
    if writers != [AUTHORITY_UNIT]:
        fail(
            f"exactly one installed unit may start {AUTHORITY_COMMAND} (or"
            f" communityd.serve_cli) and it must be {AUTHORITY_UNIT};"
            f" found {writers!r}"
        )
    for withdrawn in WITHDRAWN_UNITS:
        if withdrawn in units and units[withdrawn] is not None:
            fail(
                f"{withdrawn} is installed and not masked; the phlogiston kit's"
                " community units are withdrawn and must never run beside"
                f" {AUTHORITY_UNIT}"
            )
    return lines_by_unit


def _passwd_uid(name: str) -> int:
    return pwd.getpwnam(name).pw_uid


def validate_host_principals(
    campaign: Mapping[str, object],
    lines_by_unit: Mapping[str, Sequence[str]],
    lookup: Callable[[str], int] | None = None,
) -> None:
    """Require every installed PCV0 unit's ``User=`` to resolve to its UID."""
    resolve = lookup or _passwd_uid
    principals = campaign["servicePrincipals"]
    if campaign["schema"] == P0_CAMPAIGN_SCHEMA:
        if P0_DISABLED_UNITS & set(lines_by_unit):
            fail("P0 notifier and reply policy services must be absent or masked")
    for key, unit_names in PRINCIPAL_UNITS.items():
        if key not in principals:
            continue
        expected = principals[key]
        for name in unit_names:
            lines = lines_by_unit.get(name)
            if lines is None:
                continue
            users = _directive(lines, "User")
            if len(users) != 1:
                fail(f"{name} must name exactly one User=")
            try:
                actual = resolve(users[0])
            except KeyError:
                fail(f"{name} User={users[0]} is not a provisioned account")
            if actual != expected:
                fail(
                    f"{name} User={users[0]} is UID {actual}, but the campaign"
                    f" {key} is {expected}"
                )


def host_preflight(
    root: Path,
    campaign: Mapping[str, object],
    lookup: Callable[[str], int] | None = None,
) -> None:
    validate_host_principals(campaign, validate_host_units(root), lookup)


def build_receipt(campaign: Mapping[str, object]) -> dict[str, object]:
    identities = campaign["integrationIdentities"]
    p0 = campaign["schema"] == P0_CAMPAIGN_SCHEMA
    return {
        "schema": P0_RECEIPT_SCHEMA if p0 else RECEIPT_SCHEMA,
        "campaignId": campaign["campaignId"],
        "status": "pending",
        "completedAt": None,
        "communityDid": campaign["communityActor"]["did"],
        "schemaAuthorityDid": campaign["schemaAuthority"]["did"],
        "participants": [
            {"role": item["role"], "did": item["did"], "pdsOrigin": item["pdsOrigin"]}
            for item in identities
        ],
        "serviceVersions": {},
        "checks": [
            {
                "id": check_id,
                "status": "pending",
                "evidence": [],
            }
            for check_id in (P0_CHECK_IDS if p0 else CHECK_IDS)
        ],
        "publicRecords": [],
        "humanDogfood": {"status": "BLOCKED_MISSING_PARTICIPANTS", "receipt": None},
        "nonClaims": [
            "This internal campaign does not establish an external pilot.",
            "This internal campaign does not establish production readiness.",
            "Test identities controlled by one person do not satisfy the two-maintainer dogfood requirement.",
        ],
    }


def write_new(path: Path, value: object) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=False)
            stream.write("\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    bundle = subparsers.add_parser("validate-bundle")
    bundle.add_argument("--repository-root", type=Path, required=True)
    bundle.add_argument("--profile", choices=("legacy", "p0"), default="legacy")
    campaign_parser = subparsers.add_parser("validate-campaign")
    campaign_parser.add_argument("path", type=Path)
    campaign_parser.add_argument("--ready", action="store_true")
    receipt_parser = subparsers.add_parser("validate-receipt")
    receipt_parser.add_argument("path", type=Path)
    receipt_parser.add_argument("--complete", action="store_true")
    receipt_parser.add_argument("--campaign", type=Path)
    new_parser = subparsers.add_parser("new-receipt")
    new_parser.add_argument("campaign", type=Path)
    new_parser.add_argument("output", type=Path)
    preflight_parser = subparsers.add_parser("host-preflight")
    preflight_parser.add_argument("--campaign", type=Path, required=True)
    preflight_parser.add_argument("--unit-root", type=Path, default=Path("/"))
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "validate-bundle":
            if arguments.profile == "p0":
                validate_p0_bundle(arguments.repository_root.resolve())
            else:
                validate_committed_bundle(arguments.repository_root.resolve())
        elif arguments.command == "validate-campaign":
            validate_campaign(load_json(arguments.path), ready=arguments.ready)
        elif arguments.command == "validate-receipt":
            receipt = validate_receipt(
                load_json(arguments.path), complete=arguments.complete
            )
            if arguments.complete and arguments.campaign is None:
                fail("complete receipt validation requires --campaign")
            if arguments.campaign is not None:
                campaign = validate_campaign(
                    load_json(arguments.campaign), ready=arguments.complete
                )
                validate_receipt_binding(receipt, campaign)
        elif arguments.command == "host-preflight":
            campaign = validate_campaign(load_json(arguments.campaign), ready=True)
            host_preflight(arguments.unit_root, campaign)
        else:
            campaign = validate_campaign(load_json(arguments.campaign), ready=True)
            receipt = build_receipt(campaign)
            validate_receipt(receipt)
            write_new(arguments.output, receipt)
    except (ValidationFailure, OSError, ValueError) as exc:
        print(f"pcv0_deployment_refused:{exc}", file=sys.stderr)
        return 1
    print("pcv0_deployment_valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
