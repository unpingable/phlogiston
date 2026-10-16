from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

from community_policy.adapters import UnixAuthorityClient


def test_unix_client_sends_one_exact_reply_admit_frame(tmp_path: Path) -> None:
    path = tmp_path / "authority.sock"
    received = []
    ready = threading.Event()

    def serve() -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(path))
            listener.listen(1)
            ready.set()
            connection, _ = listener.accept()
            with connection:
                frame = b""
                while b"\n" not in frame:
                    frame += connection.recv(4096)
                received.append(json.loads(frame))
                connection.sendall(b'{"ok":true,"result":{"operation":"created"}}\n')

    thread = threading.Thread(target=serve)
    thread.start()
    ready.wait(timeout=2)
    exact = {
        "uri": "at://did:web:alice.invalid/app.phlogiston.community.submit/3jzfcijpj2z2a",
        "cid": "bafyreidfayvfuwqa7qlnopdjiqrxzs6blmoeu4rujcjtnci5beludirz2a",
    }
    request = {
        "operationId": "policy-reply-admit-test",
        "action": "reply_admit",
        "target": exact,
        "rootAdmission": {
            "uri": "at://did:web:community.invalid/app.phlogiston.community.admission/admit-x",
            "cid": exact["cid"],
        },
        "replyPolicy": {
            "uri": "at://did:web:community.invalid/app.phlogiston.community.replyPolicy/policy-x",
            "cid": exact["cid"],
        },
    }
    response = UnixAuthorityClient(str(path), 2).send(request)
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert response["ok"] is True
    assert received == [request]
    assert "authenticatedDid" not in received[0]
