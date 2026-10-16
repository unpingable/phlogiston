"""Minimal authenticated XRPC transport for one participant's own repository.

This is participant-side custody, deliberately separate from ``communityd``:
the credential here belongs to the person submitting their own post, never to
a community actor.  Nothing in this distribution can write an admission or a
moderation record — it knows only the participant's submission collection.

The retry policy matches the rest of the project: idempotent reads may be
retried, writes never are.  A dropped write is resolved by reading back the
deterministic rkey, because a blind retry could fork a repository history.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

_CREATE_SESSION = "com.atproto.server.createSession"
_GET_RECORD = "com.atproto.repo.getRecord"
_CREATE_RECORD = "com.atproto.repo.createRecord"

_MAX_BODY_BYTES = 1 << 20


class SubmitError(Exception):
    """A submission could not complete; ``code`` is a stable wire token."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AuthorizationFailed(SubmitError):
    """The PDS rejected the participant credential."""


class ReadUnavailable(SubmitError):
    """A required read did not complete or the record is absent."""


class WriteAmbiguous(SubmitError):
    """A write may or may not have landed and readback could not settle it."""


@dataclass(frozen=True, slots=True)
class Credential:
    """An app-password credential held in memory only; repr is redacted."""

    identifier: str
    app_password: str

    def __repr__(self) -> str:
        return f"Credential(identifier={self.identifier!r}, app_password=<redacted>)"


@dataclass(frozen=True, slots=True)
class Session:
    """One authenticated participant session; the token never leaves memory."""

    did: str
    token: str

    def __repr__(self) -> str:
        return f"Session(did={self.did!r}, token=<redacted>)"


class Pds(Protocol):
    """The three XRPC calls a self-submission needs, and nothing more."""

    def create_session(self, credential: Credential) -> Session: ...

    def get_record(
        self, repo: str, collection: str, rkey: str, token: str | None = None
    ) -> Mapping[str, object] | None: ...

    def create_record(
        self,
        repo: str,
        collection: str,
        rkey: str,
        record: Mapping[str, object],
        token: str,
    ) -> Mapping[str, object]: ...


@dataclass(slots=True)
class HttpPds:
    """Real XRPC client over one PDS origin."""

    base_url: str
    timeout_seconds: float = 10.0

    def _request(
        self,
        path: str,
        *,
        method: str,
        body: Mapping[str, object] | None,
        token: str | None,
        query: Mapping[str, str] | None = None,
    ) -> tuple[int, object]:
        url = f"{self.base_url.rstrip('/')}/xrpc/{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(  # noqa: S310 - https origin from config
            url, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(  # noqa: S310
                request, timeout=self.timeout_seconds
            ) as response:
                raw = response.read(_MAX_BODY_BYTES)
                status = response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read(_MAX_BODY_BYTES)
            status = exc.code
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ReadUnavailable(
                "transport_failed", "the request to your PDS did not complete"
            ) from exc
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = None
        return status, payload

    def create_session(self, credential: Credential) -> Session:
        status, payload = self._request(
            _CREATE_SESSION,
            method="POST",
            body={
                "identifier": credential.identifier,
                "password": credential.app_password,
            },
            token=None,
        )
        if status != 200 or not isinstance(payload, Mapping):
            raise AuthorizationFailed(
                "authorization_failed", "your PDS rejected that identifier or password"
            )
        did = payload.get("did")
        access = payload.get("accessJwt")
        if (
            not isinstance(did, str)
            or not did
            or not isinstance(access, str)
            or not access
        ):
            raise AuthorizationFailed(
                "authorization_failed", "your PDS returned an unusable session"
            )
        return Session(did=did, token=access)

    def get_record(
        self, repo: str, collection: str, rkey: str, token: str | None = None
    ) -> Mapping[str, object] | None:
        status, payload = self._request(
            _GET_RECORD,
            method="GET",
            body=None,
            token=token,
            query={"repo": repo, "collection": collection, "rkey": rkey},
        )
        if status == 400:
            # The lexicon reports a missing record as a 400 error body.
            return None
        if status != 200:
            raise ReadUnavailable(
                "read_failed", "the post could not be read from its repository"
            )
        if not isinstance(payload, Mapping):
            raise ReadUnavailable(
                "read_failed", "the repository returned an unreadable response"
            )
        return payload

    def create_record(
        self,
        repo: str,
        collection: str,
        rkey: str,
        record: Mapping[str, object],
        token: str,
    ) -> Mapping[str, object]:
        # Writes are never retried: a dropped response may still have
        # committed, and the caller resolves that by readback.
        status, payload = self._request(
            _CREATE_RECORD,
            method="POST",
            body={
                "repo": repo,
                "collection": collection,
                "rkey": rkey,
                "record": dict(record),
            },
            token=token,
        )
        if status == 401:
            raise AuthorizationFailed(
                "authorization_failed", "your session was rejected while writing"
            )
        if status != 200 or not isinstance(payload, Mapping):
            raise WriteAmbiguous(
                "write_unsettled", "the write did not confirm and must be checked"
            )
        return payload


__all__ = [
    "AuthorizationFailed",
    "Credential",
    "HttpPds",
    "Pds",
    "ReadUnavailable",
    "Session",
    "SubmitError",
    "WriteAmbiguous",
]
