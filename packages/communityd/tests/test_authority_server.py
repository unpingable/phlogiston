from __future__ import annotations

import json
import socket

from communityd.authority_server import (
    AuthorityRequestBoundary,
    PeerIdentity,
)

CID = "bafyreicl6ujc6ncfktctxxroxognfn7d2fqavvrryoc2lv6m4i6hpbkfti"
ADMIN = "did:web:admin.invalid"


class Handler:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, request, peer):
        self.calls.append((request, peer))
        return {"state": "committed", "operationId": request.operation_id}


def _exchange(role, payload):
    handler = Handler()
    boundary = AuthorityRequestBoundary(
        administrator_did=ADMIN,
        handler=handler,
        peer_identifier=lambda _: PeerIdentity(123, 1001, 1001, role),
    )
    client, server = socket.socketpair()
    try:
        client.sendall(json.dumps(payload).encode() + b"\n")
        boundary.handle(server)
        response = json.loads(client.recv(65536))
    finally:
        client.close()
        server.close()
    return response, handler


def _ref(collection="app.phlogiston.community.submit"):
    return {
        "uri": f"at://did:web:alice.invalid/{collection}/record",
        "cid": CID,
    }


def test_web_peer_requires_broker_attested_configured_moderator() -> None:
    request = {
        "operationId": "web-1",
        "action": "root_admit",
        "authenticatedDid": ADMIN,
        "target": _ref(),
    }
    response, handler = _exchange("community-web", request)
    assert response["ok"] is True
    assert handler.calls[0][0].target.uri == request["target"]["uri"]

    request["authenticatedDid"] = "did:web:mallory.invalid"
    response, handler = _exchange("community-web", request)
    assert response == {"error": "unauthorized", "ok": False}
    assert handler.calls == []


def test_web_peer_membership_request_has_no_fabricated_record_target() -> None:
    request = {
        "operationId": "web-member-1",
        "action": "member_add",
        "authenticatedDid": ADMIN,
        "subjectDid": "did:web:member.invalid",
    }
    response, handler = _exchange("community-web", request)
    assert response["ok"] is True
    parsed = handler.calls[0][0]
    assert parsed.target is None
    assert parsed.subject_did == "did:web:member.invalid"

    response, handler = _exchange(
        "community-web", {**request, "operationId": "web-member-2", "target": _ref()}
    )
    assert response == {"error": "request_invalid", "ok": False}
    assert handler.calls == []


def test_policy_peer_can_only_request_exact_policy_bound_reply_admission() -> None:
    request = {
        "operationId": "policy-1",
        "action": "reply_admit",
        "target": _ref(),
        "rootAdmission": _ref("app.phlogiston.community.admission"),
        "replyPolicy": _ref("app.phlogiston.community.replyPolicy"),
    }
    response, handler = _exchange("community-policy", request)
    assert response["ok"] is True
    parsed = handler.calls[0][0]
    assert parsed.root_admission is not None
    assert parsed.reply_policy is not None

    request["action"] = "root_remove"
    response, handler = _exchange("community-policy", request)
    assert response == {"error": "unauthorized", "ok": False}
    assert handler.calls == []


def test_web_cannot_auto_admit_and_restore_requires_controlling_action() -> None:
    request = {
        "operationId": "web-2",
        "action": "reply_admit",
        "authenticatedDid": ADMIN,
        "target": _ref(),
        "rootAdmission": _ref("app.phlogiston.community.admission"),
        "replyPolicy": _ref("app.phlogiston.community.replyPolicy"),
    }
    response, _ = _exchange("community-web", request)
    assert response == {"error": "unauthorized", "ok": False}

    request = {
        "operationId": "web-3",
        "action": "reply_restore",
        "authenticatedDid": ADMIN,
        "target": _ref("app.phlogiston.community.replyAdmission"),
    }
    response, _ = _exchange("community-web", request)
    assert response == {"error": "request_invalid", "ok": False}


def test_unknown_fields_and_non_exact_targets_refuse_before_handler() -> None:
    request = {
        "operationId": "web-4",
        "action": "root_remove",
        "authenticatedDid": ADMIN,
        "target": {"uri": _ref()["uri"]},
        "observerVerdict": "active",
    }
    response, handler = _exchange("community-web", request)
    assert response == {"error": "request_invalid", "ok": False}
    assert handler.calls == []
