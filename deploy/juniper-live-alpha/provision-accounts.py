#!/usr/bin/env python3
"""Provision three disposable Juniper roles without emitting their secrets."""

from __future__ import annotations

import base64
import json
import os
import secrets
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import NoReturn

ROOT = Path("/home/jbeck/juniper-alpha-pds")
ENVIRONMENT = ROOT / "pds.env"
SECRET_OUTPUT = ROOT / "account-credentials.json"
PUBLIC_OUTPUT = ROOT / "account-identities.json"
ORIGIN = "http://127.0.0.1:3001"
ROLES = ("authority", "author", "moderator")


def refuse(reason: str) -> NoReturn:
    print(f"juniper_account_provision_refused:{reason}", file=sys.stderr)
    raise SystemExit(1)


def load_admin_password() -> str:
    mode = stat.S_IMODE(ENVIRONMENT.stat().st_mode)
    if mode != 0o600:
        refuse("unsafe_environment_mode")
    prefix = "PDS_ADMIN_PASSWORD="
    for line in ENVIRONMENT.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            value = line.removeprefix(prefix)
            if value:
                return value
    refuse("missing_admin_password")


def request_json(
    method: str,
    path: str,
    body: dict[str, object],
    authorization: str | None = None,
) -> dict[str, object]:
    headers = {"content-type": "application/json"}
    if authorization is not None:
        headers["authorization"] = authorization
    request = urllib.request.Request(
        f"{ORIGIN}{path}",
        method=method,
        headers=headers,
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status != 200:
                refuse(f"http_status_{response.status}")
            value = json.loads(response.read())
    except urllib.error.HTTPError as error:
        refuse(f"http_status_{error.code}")
    except (OSError, ValueError):
        refuse("request_failed")
    if not isinstance(value, dict):
        refuse("invalid_response")
    return value


def write_private_json(path: Path, value: object) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main() -> None:
    os.umask(0o077)
    if SECRET_OUTPUT.exists() or PUBLIC_OUTPUT.exists():
        refuse("output_already_exists")

    admin_password = load_admin_password()
    basic = base64.b64encode(f"admin:{admin_password}".encode()).decode()
    invite_response = request_json(
        "POST",
        "/xrpc/com.atproto.server.createInviteCode",
        {"useCount": len(ROLES)},
        f"Basic {basic}",
    )
    invite_code = invite_response.get("code")
    if not isinstance(invite_code, str) or not invite_code:
        refuse("missing_invite_code")

    credentials: dict[str, dict[str, str]] = {}
    identities: dict[str, dict[str, str]] = {}
    for role in ROLES:
        handle = f"{role}.juniper-pds.sp00ky.net"
        password = secrets.token_urlsafe(32)
        account = request_json(
            "POST",
            "/xrpc/com.atproto.server.createAccount",
            {
                "email": f"{role}@juniper.invalid.test",
                "handle": handle,
                "password": password,
                "inviteCode": invite_code,
            },
        )
        did = account.get("did")
        returned_handle = account.get("handle")
        if not isinstance(did, str) or returned_handle != handle:
            refuse(f"invalid_{role}_identity")
        credentials[role] = {"handle": handle, "password": password}
        identities[role] = {"did": did, "handle": handle}

    write_private_json(SECRET_OUTPUT, credentials)
    write_private_json(PUBLIC_OUTPUT, identities)
    print(json.dumps(identities, sort_keys=True))


if __name__ == "__main__":
    main()
