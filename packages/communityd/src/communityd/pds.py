"""Authenticated PDS adapters for the sole authority writer.

These adapters implement the communityd ports against a real PDS using only
the Python standard library.  They realize OQ-3/A: communityd holds an
*authenticated capability* (an app-password session; the PDS signs and
commits) and never takes key custody.  Secret values transit exactly three
places: the external credential file read into memory, the in-memory
``SessionCredential``/session token, and the ``createSession`` request body
over the configured (HTTPS or loopback) origin.  They are never logged,
never rendered into error payloads, and never written anywhere.

Reads use the public ``com.atproto.repo`` procedures, so they carry
``trust_pds``/``unverified`` provenance.  Writes use a single
``createRecord`` attempt at the deterministic rkey; an ambiguous failure is
never blind-retried but resolved by readback (see ``PdsAuthorityWriter``).
"""

from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from community_model import (
    ADMISSION_COLLECTION,
    MOD_ACTION_COLLECTION,
    REPLY_ACTION_COLLECTION,
    REPLY_ADMISSION_COLLECTION,
    AdmissionRecord,
    AuthoritySubjectState,
    CredentialUnavailableError,
    CurrentRecordResult,
    ImmutableConflictError,
    ImmutableCreateOutcome,
    ModActionRecord,
    PortUnavailableError,
    RecordRef,
    ReplyActionRecord,
    ReplyAdmissionRecord,
    ReplyModerationState,
    ResolveResult,
    ValidationError,
    WriteFailedError,
    apply_reply_action,
    canonical_json_bytes,
    deep_freeze,
    deep_thaw,
)
from community_model.identifiers import parse_at_uri, validate_did, validate_nsid

from .identity import AuthorityDidResolver

MAX_RESPONSE_BYTES = 8 << 20
_LIST_PAGE_LIMIT = 100
_TID_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"
_AUTHORITY_DEFINING_IGNORED = frozenset({"createdAt"})
_CREDENTIAL_FILE_KEYS = frozenset({"identifier", "app_password"})


class _TransportError(PortUnavailableError):
    """An XRPC request could not complete or be understood."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


@dataclass(frozen=True, slots=True)
class SessionCredential:
    """An app-password credential held in memory only; repr is redacted."""

    identifier: str
    app_password: str

    def __repr__(self) -> str:
        return f"SessionCredential(identifier={self.identifier!r}, app_password=<redacted>)"


class EnvFileCredentialProvider:
    """Resolve ``env:VARNAME`` references to credential files outside the repo.

    The environment variable's value is the path of a JSON document
    ``{"identifier": ..., "app_password": ...}``.  Every failure mode raises
    ``CredentialUnavailableError`` with a message that contains neither the
    path value nor any file content.
    """

    def require(self, reference: str) -> str:
        return self.load(reference).identifier

    def load(self, reference: str) -> SessionCredential:
        if not reference.startswith("env:"):
            raise CredentialUnavailableError(
                "the env_file provider requires an env:VARNAME reference"
            )
        variable = reference[len("env:") :]
        path_value = os.environ.get(variable)
        if not path_value:
            raise CredentialUnavailableError(
                f"credential environment variable {variable} is unset"
            )
        try:
            raw = Path(path_value).read_bytes()
        except OSError:
            raise CredentialUnavailableError(
                "the referenced credential file is unreadable"
            ) from None
        try:
            document = json.loads(raw)
        except ValueError:
            raise CredentialUnavailableError(
                "the referenced credential file is not valid JSON"
            ) from None
        if not isinstance(document, dict) or set(document) != _CREDENTIAL_FILE_KEYS:
            raise CredentialUnavailableError(
                "the credential file must contain exactly identifier and app_password"
            )
        identifier = document["identifier"]
        app_password = document["app_password"]
        if (
            not isinstance(identifier, str)
            or not identifier
            or not isinstance(app_password, str)
            or not app_password
        ):
            raise CredentialUnavailableError(
                "credential identifier and app_password must be nonempty strings"
            )
        assert isinstance(identifier, str) and isinstance(app_password, str)
        return SessionCredential(identifier=identifier, app_password=app_password)


@dataclass(slots=True)
class PdsTransport:
    """Bounded JSON XRPC transport; idempotent requests retry, writes do not."""

    base_url: str
    timeout_seconds: float
    max_retries: int

    def get_json(self, procedure: str, params: Mapping[str, str]) -> tuple[int, object]:
        query = urllib.parse.urlencode(params)
        url = f"{self.base_url}/xrpc/{procedure}?{query}"
        return self._request(
            "GET", url, None, token=None, attempts=1 + self.max_retries
        )

    def post_json(
        self,
        procedure: str,
        body: Mapping[str, object],
        *,
        token: str | None,
        retry: bool,
    ) -> tuple[int, object]:
        url = f"{self.base_url}/xrpc/{procedure}"
        payload = json.dumps(body).encode("utf-8")
        attempts = 1 + self.max_retries if retry else 1
        return self._request("POST", url, payload, token=token, attempts=attempts)

    def _request(
        self,
        method: str,
        url: str,
        payload: bytes | None,
        *,
        token: str | None,
        attempts: int,
    ) -> tuple[int, object]:
        last_error: _TransportError | None = None
        for _ in range(max(1, attempts)):
            try:
                status, raw = self._once(method, url, payload, token)
            except _TransportError as exc:
                last_error = exc
                continue
            if status >= 500:
                last_error = _TransportError(f"XRPC returned HTTP {status}")
                continue
            try:
                return status, json.loads(raw)
            except ValueError as exc:
                raise _TransportError("XRPC response is not valid JSON") from exc
        assert last_error is not None
        raise last_error

    def _once(
        self, method: str, url: str, payload: bytes | None, token: str | None
    ) -> tuple[int, bytes]:
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            url, data=payload, headers=headers, method=method
        )
        try:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}), _NoRedirect()
            )
            with opener.open(request, timeout=self.timeout_seconds) as reply:
                body = reply.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise _TransportError("XRPC response exceeds the size bound")
                return reply.status, body
        except urllib.error.HTTPError as exc:
            body = exc.read(MAX_RESPONSE_BYTES + 1) if exc.fp is not None else b""
            return exc.code, body
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            raise _TransportError(f"XRPC request failed: {type(exc).__name__}") from exc


class PdsSession:
    """A lazily created app-password session; the token lives in memory only."""

    def __init__(
        self,
        transport: PdsTransport,
        credential_loader: Callable[[], SessionCredential],
        *,
        expected_did: str,
    ) -> None:
        self._transport = transport
        self._credential_loader = credential_loader
        self._expected_did = expected_did
        self._token: str | None = None

    def __repr__(self) -> str:
        return f"PdsSession(expected_did={self._expected_did!r}, token=<redacted>)"

    def token(self) -> str:
        """Authenticate once, then reuse the in-memory bearer token."""

        if self._token is not None:
            return self._token
        credential = self._credential_loader()
        status, payload = self._transport.post_json(
            "com.atproto.server.createSession",
            {
                "identifier": credential.identifier,
                "password": credential.app_password,
            },
            token=None,
            retry=True,
        )
        if status != 200 or not isinstance(payload, Mapping):
            raise CredentialUnavailableError(
                "the community credential was rejected by the PDS"
            )
        access = payload.get("accessJwt")
        if (
            payload.get("did") != self._expected_did
            or not isinstance(access, str)
            or not access
        ):
            raise CredentialUnavailableError(
                "the community session does not match the configured actor"
            )
        self._token = access
        return access


def _get_record(
    transport: PdsTransport, repo_did: str, collection: str, rkey: str
) -> tuple[str, Mapping[str, object]] | None:
    """Fetch one current record; ``None`` when the PDS reports it absent."""

    status, payload = transport.get_json(
        "com.atproto.repo.getRecord",
        {"repo": repo_did, "collection": collection, "rkey": rkey},
    )
    if status in (400, 404):
        return None
    if status != 200:
        raise PortUnavailableError("getRecord did not succeed")
    if not isinstance(payload, Mapping):
        raise PortUnavailableError("getRecord returned a malformed payload")
    uri = payload.get("uri")
    cid = payload.get("cid")
    value = payload.get("value")
    if (
        not isinstance(uri, str)
        or not isinstance(cid, str)
        or not isinstance(value, Mapping)
    ):
        raise PortUnavailableError("getRecord returned a malformed record view")
    try:
        parsed = parse_at_uri(uri)
    except ValidationError as exc:
        raise PortUnavailableError("getRecord returned a malformed record URI") from exc
    if (
        parsed.authority != repo_did
        or parsed.collection != collection
        or parsed.rkey != rkey
    ):
        raise PortUnavailableError("getRecord answered for the wrong record key")
    return cid, value


def _result_metadata() -> dict[str, object]:
    return {
        "checked_at": datetime.now(UTC),
        "trust_mode": "trust_pds",
        "verification_outcome": "unverified",
        "resolution_method": "pds_xrpc",
        "resolver_version": "1",
    }


@dataclass(slots=True)
class PdsRecordReader:
    """Resolve exact/current references through public PDS reads."""

    transport: PdsTransport

    def get_exact(self, ref: RecordRef) -> ResolveResult:
        found = _get_record(self.transport, ref.repo_did, ref.collection, ref.rkey)
        if found is None:
            return ResolveResult(
                status="missing",
                requested=ref,
                current_cid=None,
                record=None,
                **_result_metadata(),  # type: ignore[arg-type]
            )
        current_cid, record = found
        if current_cid != ref.cid:
            return ResolveResult(
                status="mismatch",
                requested=ref,
                current_cid=current_cid,
                record=None,
                **_result_metadata(),  # type: ignore[arg-type]
            )
        return ResolveResult(
            status="exact",
            requested=ref,
            current_cid=current_cid,
            record=record,
            **_result_metadata(),  # type: ignore[arg-type]
        )

    def get_current(self, uri: str) -> CurrentRecordResult:
        parsed = parse_at_uri(uri)
        found = _get_record(
            self.transport, parsed.authority, parsed.collection, parsed.rkey
        )
        if found is None:
            return CurrentRecordResult(
                status="missing",
                uri=uri,
                current_cid=None,
                record=None,
                **_result_metadata(),  # type: ignore[arg-type]
            )
        current_cid, record = found
        return CurrentRecordResult(
            status="present",
            uri=uri,
            current_cid=current_cid,
            record=record,
            **_result_metadata(),  # type: ignore[arg-type]
        )


@dataclass(slots=True)
class ResolvingPdsRecordReader:
    """Route each public repository read through its DID-bound PDS origin."""

    resolver: AuthorityDidResolver
    timeout_seconds: float
    max_retries: int
    cache_size: int
    _transports: dict[str, PdsTransport] | None = None

    def __post_init__(self) -> None:
        if self._transports is None:
            self._transports = {}

    def _reader(self, did: str) -> PdsRecordReader:
        origin = self.resolver.pds_origin(did)
        assert self._transports is not None
        transport = self._transports.get(origin)
        if transport is None:
            if len(self._transports) >= self.cache_size:
                self._transports.pop(next(iter(self._transports)))
            transport = PdsTransport(origin, self.timeout_seconds, self.max_retries)
            self._transports[origin] = transport
        return PdsRecordReader(transport)

    def get_exact(self, ref: RecordRef) -> ResolveResult:
        return self._reader(ref.repo_did).get_exact(ref)

    def get_current(self, uri: str) -> CurrentRecordResult:
        return self._reader(parse_at_uri(uri).authority).get_current(uri)


def _mint_tid() -> str:
    """Render the current time as a valid, roughly monotone TID."""

    value = (int(time.time() * 1_000_000) << 10) & 0xFFFFFFFFFFFFFFFF
    return "".join(_TID_ALPHABET[(value >> shift) & 31] for shift in range(60, -1, -5))


@dataclass(slots=True)
class PdsAuthorityLedgerReader:
    """Paginate the community repo's authority collections; never observer data."""

    transport: PdsTransport
    page_limit: int = _LIST_PAGE_LIMIT

    def find_subject_lifecycle(
        self, community_did: str, subject: RecordRef
    ) -> AuthoritySubjectState:
        admissions: list[RecordRef] = []
        removals: list[RecordRef] = []
        for collection, parser in (
            (ADMISSION_COLLECTION, AdmissionRecord.from_record),
            (MOD_ACTION_COLLECTION, ModActionRecord.from_record),
        ):
            for uri, cid, value in self._list_all(community_did, collection):
                try:
                    parsed = parser(dict(value))
                except ValidationError:
                    continue
                if parsed.subject == subject:
                    reference = RecordRef(uri=uri, cid=cid)
                    if collection == ADMISSION_COLLECTION:
                        admissions.append(reference)
                    else:
                        removals.append(reference)
        return AuthoritySubjectState(
            subject=subject,
            valid_admissions=tuple(admissions),
            valid_removals=tuple(removals),
            community_repo_high_water=_mint_tid(),
        )

    def eligible_reply_uris(
        self, community_did: str, discussion: RecordRef
    ) -> frozenset[str]:
        eligible: set[str] = set()
        for _, _, value in self._list_all(community_did, REPLY_ADMISSION_COLLECTION):
            try:
                admission = ReplyAdmissionRecord.from_record(dict(value))
            except ValidationError:
                continue
            if admission.discussion == discussion:
                eligible.add(admission.subject.uri)
        return frozenset(eligible)

    def moderation_state(
        self, community_did: str, moderation_key: str
    ) -> ReplyModerationState | None:
        admissions: dict[str, tuple[RecordRef, ReplyAdmissionRecord]] = {}
        for uri, cid, value in self._list_all(
            community_did, REPLY_ADMISSION_COLLECTION
        ):
            try:
                parsed = ReplyAdmissionRecord.from_record(dict(value))
            except ValidationError:
                continue
            admissions[uri] = (RecordRef(uri=uri, cid=cid), parsed)

        pending: list[tuple[RecordRef, ReplyActionRecord]] = []
        for uri, cid, value in self._list_all(community_did, REPLY_ACTION_COLLECTION):
            try:
                action = ReplyActionRecord.from_record(dict(value))
            except ValidationError:
                continue
            if action.moderation_key == moderation_key:
                pending.append((RecordRef(uri=uri, cid=cid), action))

        state: ReplyModerationState | None = None
        while pending:
            candidates = [
                pair
                for pair in pending
                if pair[1].previous_action
                == (None if state is None else state.last_action)
            ]
            if len(candidates) != 1:
                raise PortUnavailableError(
                    "reply action chain is incomplete or branched"
                )
            action_ref, action = candidates[0]
            admitted = admissions.get(action.admission.uri)
            if admitted is None or admitted[0] != action.admission:
                raise PortUnavailableError("reply action admission is unavailable")
            admission_ref, admission = admitted
            try:
                state = apply_reply_action(
                    state,
                    action,
                    action_ref=action_ref,
                    admission=admission,
                    admission_ref=admission_ref,
                    community_did=community_did,
                )
            except ValidationError as exc:
                raise PortUnavailableError("reply action chain is invalid") from exc
            pending.remove(candidates[0])
        return state

    def _list_all(
        self, community_did: str, collection: str
    ) -> Iterator[tuple[str, str, Mapping[str, object]]]:
        cursor: str | None = None
        while True:
            params = {
                "repo": community_did,
                "collection": collection,
                "limit": str(self.page_limit),
            }
            if cursor is not None:
                params["cursor"] = cursor
            status, payload = self.transport.get_json(
                "com.atproto.repo.listRecords", params
            )
            if status != 200 or not isinstance(payload, Mapping):
                raise PortUnavailableError("listRecords did not succeed")
            records = payload.get("records")
            if not isinstance(records, list):
                raise PortUnavailableError("listRecords returned a malformed page")
            for entry in records:
                if not isinstance(entry, Mapping):
                    raise PortUnavailableError("listRecords returned a malformed entry")
                uri = entry.get("uri")
                cid = entry.get("cid")
                value = entry.get("value")
                if (
                    not isinstance(uri, str)
                    or not isinstance(cid, str)
                    or not isinstance(value, Mapping)
                ):
                    raise PortUnavailableError("listRecords returned a malformed entry")
                try:
                    parsed = parse_at_uri(uri)
                except ValidationError as exc:
                    raise PortUnavailableError(
                        "listRecords returned a malformed record URI"
                    ) from exc
                if parsed.authority != community_did or parsed.collection != collection:
                    raise PortUnavailableError(
                        "listRecords answered outside the community ledger"
                    )
                yield uri, cid, value
            next_cursor = payload.get("cursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                return
            cursor = next_cursor


def _authority_compatible(
    existing: Mapping[str, object], new: Mapping[str, object]
) -> bool:
    """Compare authority-defining fields; generated createdAt is excluded."""

    def defining(record: Mapping[str, object]) -> bytes:
        return canonical_json_bytes(
            {
                key: value
                for key, value in record.items()
                if key not in _AUTHORITY_DEFINING_IGNORED
            }
        )

    return defining(existing) == defining(new)


@dataclass(slots=True)
class PdsAuthorityWriter:
    """Create-only writer: one attempt, then readback to resolve ambiguity."""

    transport: PdsTransport
    session: PdsSession

    def create_immutable(
        self,
        repo_did: str,
        collection: str,
        semantic_operation_id: str,
        record: Mapping[str, object],
    ) -> ImmutableCreateOutcome:
        validate_did(repo_did)
        validate_nsid(collection)
        rkey = semantic_operation_id
        uri = f"at://{repo_did}/{collection}/{rkey}"
        frozen = deep_freeze(record)
        # The single existence check for one deterministic create: callers
        # rely on this read instead of pre-reading the same record themselves.
        prior = _get_record(self.transport, repo_did, collection, rkey)
        if prior is not None:
            cid, existing = prior
            if _authority_compatible(existing, frozen):
                return ImmutableCreateOutcome(
                    RecordRef(uri=uri, cid=cid), created=False
                )
            raise ImmutableConflictError(
                "deterministic authority rkey holds incompatible content"
            )

        token = self.session.token()
        body = {
            "repo": repo_did,
            "collection": collection,
            "rkey": rkey,
            "record": deep_thaw(frozen),
        }
        try:
            status, payload = self.transport.post_json(
                "com.atproto.repo.createRecord", body, token=token, retry=False
            )
        except _TransportError as exc:
            return self._resolve_ambiguous(uri, repo_did, collection, rkey, frozen, exc)
        if status == 200:
            if _create_response_matches(payload, uri):
                assert isinstance(payload, Mapping)
                return ImmutableCreateOutcome(
                    RecordRef(uri=uri, cid=payload["cid"]),  # type: ignore[arg-type]
                    created=True,
                )
            return self._resolve_ambiguous(
                uri, repo_did, collection, rkey, frozen, None
            )
        if status >= 500:
            return self._resolve_ambiguous(
                uri, repo_did, collection, rkey, frozen, None
            )
        if status == 401:
            raise CredentialUnavailableError(
                "the community session was rejected by the PDS"
            )
        raise WriteFailedError("the PDS rejected the authority record")

    def _resolve_ambiguous(
        self,
        uri: str,
        repo_did: str,
        collection: str,
        rkey: str,
        frozen: Mapping[str, object],
        cause: _TransportError | None,
    ) -> ImmutableCreateOutcome:
        """After a timeout/5xx/dropped response, resolve by rkey readback.

        The commit may have landed, so a blind retry could fork authority
        history.  Readback at the deterministic rkey settles it: a compatible
        occupant is the same operation; an incompatible one is a hard
        conflict; absence or a failed readback means the write failed or
        remains ambiguous (exit 8 through the caller).
        """

        try:
            prior = _get_record(self.transport, repo_did, collection, rkey)
        except PortUnavailableError as exc:
            raise PortUnavailableError(
                "authority write outcome is ambiguous and readback failed"
            ) from exc
        if prior is None:
            raise PortUnavailableError(
                "authority write failed; readback found no record at the rkey"
            ) from cause
        cid, existing = prior
        if _authority_compatible(existing, frozen):
            # This path is reached only when the pre-create existence check
            # found the rkey absent, so a compatible occupant after our
            # attempt is our own dropped commit: the operation created it.
            return ImmutableCreateOutcome(RecordRef(uri=uri, cid=cid), created=True)
        raise ImmutableConflictError(
            "deterministic authority rkey holds incompatible content"
        ) from cause


def _create_response_matches(payload: object, uri: str) -> bool:
    return (
        isinstance(payload, Mapping)
        and payload.get("uri") == uri
        and isinstance(payload.get("cid"), str)
    )


__all__ = [
    "EnvFileCredentialProvider",
    "PdsAuthorityLedgerReader",
    "PdsAuthorityWriter",
    "PdsRecordReader",
    "PdsSession",
    "PdsTransport",
    "SessionCredential",
]
