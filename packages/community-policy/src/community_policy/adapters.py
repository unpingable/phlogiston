from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping

from community_model import RecordRef, ValidationError

from .worker import ReplyCandidate

_MAX_FRAME = 64 * 1024


class HttpCandidateSource:
    def __init__(self, origin: str, timeout: float) -> None:
        self.origin = origin.rstrip("/")
        self.timeout = timeout

    def fetch(self, community_did: str) -> tuple[ReplyCandidate, ...]:
        encoded_did = urllib.parse.quote(community_did, safe=":")
        url = f"{self.origin}/api/v0/communities/{encoded_did}/reply-candidates"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                document = json.loads(response.read(_MAX_FRAME + 1))
        except (OSError, ValueError, urllib.error.URLError) as exc:
            raise OSError("observer candidate acquisition failed") from exc
        if not isinstance(document, dict) or set(document) != {
            "communityDid",
            "candidates",
            "snapshot",
        }:
            raise ValidationError(
                "schema_invalid", "candidate response shape is invalid"
            )
        if document["communityDid"] != community_did or not isinstance(
            document["snapshot"], dict
        ):
            raise ValidationError(
                "schema_invalid", "candidate response context is invalid"
            )
        raw_candidates = document["candidates"]
        if not isinstance(raw_candidates, list):
            raise ValidationError("schema_invalid", "candidates must be an array")
        return tuple(self._candidate(value) for value in raw_candidates)

    @staticmethod
    def _candidate(value: object) -> ReplyCandidate:
        if not isinstance(value, dict) or set(value) != {
            "submission",
            "subject",
            "rootAdmission",
            "replyPolicy",
        }:
            raise ValidationError("schema_invalid", "reply candidate shape is invalid")
        return ReplyCandidate(
            submission=RecordRef.from_mapping(
                value["submission"], path=("submission",)
            ),
            subject=RecordRef.from_mapping(value["subject"], path=("subject",)),
            root_admission=RecordRef.from_mapping(
                value["rootAdmission"], path=("rootAdmission",)
            ),
            reply_policy=RecordRef.from_mapping(
                value["replyPolicy"], path=("replyPolicy",)
            ),
        )


class UnixAuthorityClient:
    def __init__(self, path: str, timeout: float) -> None:
        self.path = path
        self.timeout = timeout

    def send(self, request: Mapping[str, object]) -> Mapping[str, object]:
        allowed = {"operationId", "action", "target", "rootAdmission", "replyPolicy"}
        if set(request) != allowed or request.get("action") != "reply_admit":
            raise ValidationError(
                "request_invalid", "policy client only sends reply_admit"
            )
        frame = (
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )
        if len(frame) > _MAX_FRAME:
            raise ValidationError("request_invalid", "authority request is too large")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(self.timeout)
            connection.connect(self.path)
            connection.sendall(frame)
            chunks = bytearray()
            while b"\n" not in chunks and len(chunks) <= _MAX_FRAME:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                chunks.extend(chunk)
        if b"\n" not in chunks or len(chunks) > _MAX_FRAME:
            raise OSError("authority response frame is incomplete")
        raw, remainder = bytes(chunks).split(b"\n", 1)
        if remainder:
            raise OSError("authority returned multiple frames")
        try:
            response = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OSError("authority response is invalid") from exc
        if not isinstance(response, dict) or set(response) - {"ok", "result", "error"}:
            raise OSError("authority response shape is invalid")
        return response
