"""Narrow Unix-socket request boundary for community authority effects.

Peer credentials attest which trusted local component connected.  They do not
identify a human.  Human moderator identity is supplied only by the trusted
``community-web`` broker after it validates its server-side OAuth session;
communityd still pins that DID to its configuration and validates every exact
target again in its action handler.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import stat
import struct
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from community_model import (
    SUBMISSION_COLLECTION,
    AuthorizationError,
    PortError,
    RecordRef,
    SubmissionRecord,
    UnsupportedReadmissionError,
    ValidationContext,
    ValidationError,
    validate_record,
)
from community_model.identifiers import validate_did

from .config import DaemonConfig
from .journal import JournalConflictError
from .operations import (
    DaemonPorts,
    _reconcile_journaled_write,
    admit,
    change_membership,
    remove,
)
from .p0_decisions import P0DecisionStore, SubjectDecision, admission_open
from .reply_operations import (
    ReplyAuthorityLedgerReader,
    admit_reply,
    create_reply_policy,
    moderate_reply,
)

PeerRole = Literal["community-web", "community-policy"]
AuthorityAction = Literal[
    "root_admit",
    "root_remove",
    "reply_admit",
    "reply_remove",
    "reply_restore",
    "member_add",
    "member_remove",
    "root_decline",
    "root_status",
]

_WEB_ACTIONS = frozenset(
    {
        "root_admit",
        "root_remove",
        "reply_remove",
        "reply_restore",
        "member_add",
        "member_remove",
        "root_decline",
        "root_status",
    }
)
_POLICY_ACTIONS = frozenset({"reply_admit"})
_MAX_REQUEST_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class PeerIdentity:
    pid: int
    uid: int
    gid: int
    role: PeerRole


@dataclass(frozen=True, slots=True)
class AuthorityRequest:
    operation_id: str
    action: AuthorityAction
    authenticated_did: str | None
    target: RecordRef | None = None
    subject_did: str | None = None
    root_admission: RecordRef | None = None
    reply_policy: RecordRef | None = None
    controlling_action: RecordRef | None = None
    reason: str | None = None


class BoundaryActionHandler(Protocol):
    """Communityd-owned semantic validator and writer.

    Implementations must resolve the supplied exact records directly, check
    the root's currently bound immutable reply policy and lifecycle at the
    write boundary, then use the durable operation journal before writing.
    Observer-derived verdicts are never valid inputs to this interface.
    """

    def execute(
        self, request: AuthorityRequest, peer: PeerIdentity
    ) -> Mapping[str, object]: ...


class CommunityAuthorityHandler:
    """Concrete write-boundary handler used by the supervised socket server."""

    def __init__(
        self,
        *,
        ports: DaemonPorts,
        reply_ledger: ReplyAuthorityLedgerReader,
        config: DaemonConfig,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.ports = ports
        self.reply_ledger = reply_ledger
        self.config = config
        self.clock = clock
        self.p0 = (
            P0DecisionStore(
                config.operation_journal_path,
                test_origin=("controlled-hosted:" + config.p0_hosted_pds_origin)
                if config.p0_hosted_pds_origin
                else config.p0_test_pds_origin,
            )
            if config.p0_profile == "root_only"
            and config.operation_journal_path is not None
            else None
        )

    def _submission_subject(self, submission: RecordRef) -> RecordRef:
        if submission.collection != SUBMISSION_COLLECTION:
            raise ValidationError(
                "request_invalid", "P0 decision requires a submission"
            )
        result = self.ports.reader.get_exact(submission)
        if result.status.value == "error":
            raise ValidationError(
                "source_unavailable", "submission resolution unavailable"
            )
        if result.status.value != "exact" or result.record is None:
            raise ValidationError(
                "reference_missing", "exact submission is unavailable"
            )
        validated = validate_record(
            result.record,
            context=ValidationContext(
                community_did=self.config.community_did,
                repo_did=submission.repo_did,
                collection=SUBMISSION_COLLECTION,
                rkey=submission.rkey,
                operation="create",
                record_cid=submission.cid,
                administrator_did=self.config.administrator_did,
            ),
        )
        if not isinstance(validated.record, SubmissionRecord):
            raise ValidationError("request_invalid", "target is not a submission")
        return validated.record.subject

    def _p0_decision(self, submission: RecordRef) -> SubjectDecision | None:
        assert self.p0 is not None
        direct = self.p0.find_submission(self.config.community_did, submission)
        if direct is not None:
            return direct
        subject = self._submission_subject(submission)
        return self.p0.find(self.config.community_did, submission.repo_did, subject)

    def _p0_status(self, submission: RecordRef) -> dict[str, object]:
        assert self.p0 is not None
        # The private exact-submission decision is authoritative even if the
        # author's source record has since disappeared. Without one, resolve
        # the source exactly once before looking up a subject-level decision.
        decision = self.p0.find_submission(self.config.community_did, submission)
        if decision is None:
            try:
                subject = self._submission_subject(submission)
            except ValidationError as exc:
                if exc.reason_code != "reference_missing":
                    raise
                return {
                    "decision": "submission_unavailable",
                    "submission": submission.as_dict(),
                    "subject": None,
                    "admission": None,
                    "reason": "Exact submission is no longer current or available",
                    "operationId": None,
                    "actorDid": None,
                    "decidedAt": None,
                }
            decision = self.p0.find(
                self.config.community_did, submission.repo_did, subject
            )
            if decision is None:
                return {
                    "decision": "none",
                    "submission": submission.as_dict(),
                    "subject": subject.as_dict(),
                    "admission": None,
                    "reason": None,
                    "operationId": None,
                    "actorDid": None,
                    "decidedAt": None,
                }
        if decision.state == "admit_pending":
            journal = self.ports.operation_journal
            if journal is None:
                raise ValidationError(
                    "source_unavailable", "admission journal unavailable"
                )
            entry = journal.get(decision.operation_id + ":admission")
            if entry is not None:
                result = _reconcile_journaled_write(self.ports, journal, entry)
                if result is not None:
                    decision = self.p0.committed(decision, result.record)
        return decision.response(submission)

    def _release_unattempted(self, decision: SubjectDecision) -> None:
        """Release only a P0 reservation with no provider attempt."""
        assert self.p0 is not None
        journal = self.ports.operation_journal
        if journal is None:
            return
        operation_id = decision.operation_id + ":admission"
        entry = journal.get(operation_id)
        if entry is None or journal.discard_prepared(operation_id):
            self.p0.release_unattempted(decision)

    def execute(
        self, request: AuthorityRequest, peer: PeerIdentity
    ) -> Mapping[str, object]:
        now = self.clock()
        if self.p0 is not None:
            if request.action == "root_status":
                assert request.target is not None
                return self._p0_status(request.target)
            if request.action == "root_decline":
                assert request.target is not None
                if not request.reason:
                    raise ValidationError(
                        "request_invalid", "decline requires a reason"
                    )
                subject = self._submission_subject(request.target)
                lifecycle = self.ports.ledger.find_subject_lifecycle(
                    self.config.community_did, subject
                )
                if lifecycle.valid_admissions or lifecycle.valid_removals:
                    raise ValidationError(
                        "already_decided",
                        "subject already has public authority history",
                    )
                pending = self.p0.find(
                    self.config.community_did, request.target.repo_did, subject
                )
                if pending is not None and pending.state == "admit_pending":
                    self._release_unattempted(pending)
                decision = self.p0.reserve(
                    community_did=self.config.community_did,
                    author_did=request.target.repo_did,
                    actor_did=self.config.administrator_did,
                    subject=subject,
                    submission=request.target,
                    operation_id=request.operation_id,
                    state="declined",
                    reason=request.reason,
                    decided_at=now.isoformat(),
                )
                return decision.response(request.target)
            if request.action not in {"root_admit", "root_remove"}:
                raise ValidationError(
                    "p0_action_disabled", "action is outside the P0 profile"
                )
            if request.action == "root_admit":
                assert request.target is not None
                # A pending admission may be read back while paused, but pause
                # never permits a fresh provider dispatch.
                if not admission_open(self.config.p0_admission_pause_path or ""):
                    status = self._p0_status(request.target)
                    if status["decision"] == "admitted":
                        return {"admission": status["admission"]}
                    raise ValidationError(
                        "admission_paused", "new admissions are paused"
                    )
                prior = self._p0_decision(request.target)
                if prior is not None and prior.state == "admitted":
                    return {
                        "admission": prior.admission.as_dict()
                        if prior.admission
                        else None
                    }
                subject = (
                    prior.subject
                    if prior is not None
                    else self._submission_subject(request.target)
                )
                if prior is None:
                    lifecycle = self.ports.ledger.find_subject_lifecycle(
                        self.config.community_did, subject
                    )
                    if lifecycle.valid_admissions or lifecycle.valid_removals:
                        raise ValidationError(
                            "already_decided",
                            "subject already has public authority history",
                        )
                decision = self.p0.reserve(
                    community_did=self.config.community_did,
                    author_did=request.target.repo_did,
                    actor_did=self.config.administrator_did,
                    subject=subject,
                    submission=request.target,
                    operation_id=request.operation_id,
                    state="admit_pending",
                    decided_at=now.isoformat(),
                )
                if decision.state == "admitted":
                    return {
                        "admission": decision.admission.as_dict()
                        if decision.admission
                        else None
                    }
                if decision.submission != request.target:
                    raise JournalConflictError(
                        "another submission reserved this exact subject"
                    )
                journal = self.ports.operation_journal
                if journal is not None:
                    entry = journal.get(decision.operation_id + ":admission")
                    if entry is not None:
                        result = _reconcile_journaled_write(self.ports, journal, entry)
                        if result is not None:
                            return {
                                "admission": self.p0.committed(
                                    decision, result.record
                                ).admission.as_dict()
                            }

                def require_open_at_dispatch() -> None:
                    if not admission_open(self.config.p0_admission_pause_path or ""):
                        raise ValidationError(
                            "admission_paused", "new admissions are paused"
                        )

                try:
                    admission = admit(
                        self.ports,
                        self.config,
                        request.target,
                        now=now,
                        operation_id=request.operation_id + ":admission",
                        before_dispatch=require_open_at_dispatch,
                        retain_attempt_marker=True,
                    )
                except (ValidationError, UnsupportedReadmissionError):
                    # Prepared means no provider attempt in P0. Keep an
                    # attempted-unknown reservation until exact readback.
                    self._release_unattempted(decision)
                    raise
                return {
                    "admission": self.p0.committed(
                        decision, admission.record
                    ).admission.as_dict()
                }
        elif request.action in {"root_decline", "root_status"}:
            raise ValidationError("p0_action_disabled", "P0 action requires P0 profile")
        if request.action in {"member_add", "member_remove"}:
            assert request.subject_did is not None
            outcome = change_membership(
                self.ports,
                self.config,
                request.subject_did,
                "add" if request.action == "member_add" else "remove",
                request.reason,
                now=now,
                operation_id=request.operation_id,
            )
            return {
                "operation": outcome.operation,
                "membership": outcome.record.as_dict(),
            }
        if request.action == "root_admit":
            assert request.target is not None
            admission = admit(
                self.ports,
                self.config,
                request.target,
                now=now,
                operation_id=request.operation_id + ":admission",
            )
            policy = create_reply_policy(
                self.ports,
                self.config,
                admission.record,
                now=now,
                operation_id=request.operation_id + ":policy",
            )
            return {
                "admission": admission.record.as_dict(),
                "replyPolicy": policy.record.as_dict(),
            }
        if request.action == "root_remove":
            assert request.target is not None
            outcome = remove(
                self.ports,
                self.config,
                request.target,
                request.reason,
                now=now,
                operation_id=request.operation_id,
            )
        elif request.action == "reply_admit":
            assert request.target is not None
            assert request.root_admission is not None
            assert request.reply_policy is not None
            outcome = admit_reply(
                self.ports,
                self.reply_ledger,
                self.config,
                request.target,
                request.root_admission,
                request.reply_policy,
                now=now,
                operation_id=request.operation_id,
            )
        else:
            assert request.target is not None
            outcome = moderate_reply(
                self.ports,
                self.reply_ledger,
                self.config,
                request.target,
                "remove" if request.action == "reply_remove" else "restore",
                request.reason,
                controlling_action=request.controlling_action,
                now=now,
                operation_id=request.operation_id,
            )
        return {
            "operation": outcome.operation,
            "record": outcome.record.as_dict(),
        }


class UnixPeerRolePolicy:
    """Map configured OS UIDs to one non-overlapping trusted component role."""

    def __init__(self, *, web_uid: int, policy_uid: int | None) -> None:
        if web_uid < 0 or (policy_uid is not None and policy_uid < 0):
            raise ValueError("peer UIDs must be nonnegative")
        if policy_uid is not None and web_uid == policy_uid:
            raise ValueError("web and policy peers require distinct OS UIDs")
        self._roles = {web_uid: "community-web"}
        if policy_uid is not None:
            self._roles[policy_uid] = "community-policy"

    def identify(self, connection: socket.socket) -> PeerIdentity:
        if not hasattr(socket, "SO_PEERCRED"):
            raise AuthorizationError("Unix peer credentials are unavailable")
        raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        pid, uid, gid = struct.unpack("3i", raw)
        role = self._roles.get(uid)
        if role is None:
            raise AuthorizationError("local peer UID is not authorized")
        return PeerIdentity(pid=pid, uid=uid, gid=gid, role=role)  # type: ignore[arg-type]


class AuthorityRequestBoundary:
    """Authorize and parse one framed request before semantic execution."""

    def __init__(
        self,
        *,
        administrator_did: str,
        handler: BoundaryActionHandler,
        peer_identifier: Callable[[socket.socket], PeerIdentity],
    ) -> None:
        self.administrator_did = administrator_did
        self.handler = handler
        self.peer_identifier = peer_identifier

    def handle(self, connection: socket.socket) -> None:
        try:
            peer = self.peer_identifier(connection)
            request = _parse_request(_read_frame(connection))
            _authorize_request(peer, request, self.administrator_did)
            result = self.handler.execute(request, peer)
            response: Mapping[str, object] = {"ok": True, "result": dict(result)}
        except (
            AuthorizationError,
            JournalConflictError,
            PortError,
            ValidationError,
            ValueError,
            KeyError,
            sqlite3.Error,
            OSError,
        ) as exc:
            response = {"ok": False, "error": _safe_error_code(exc)}
        connection.sendall(_encode_frame(response))


class UnixAuthorityServer:
    """Small synchronous server; supervision owns restart and concurrency policy."""

    def __init__(
        self,
        path: str,
        boundary: AuthorityRequestBoundary,
        *,
        backlog: int = 16,
    ) -> None:
        self.path = path
        self.boundary = boundary
        self.backlog = backlog

    def serve_forever(self) -> None:  # pragma: no cover - exercised by deployment
        path = Path(self.path)
        # Group traversal is required for the two distinct, group-authorized
        # peer UIDs; SO_PEERCRED still decides which verb each UID may request.
        path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        path.parent.chmod(0o750)
        _remove_stale_socket(path)
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(self.path)
                os.chmod(self.path, 0o660)
                listener.listen(self.backlog)
                while True:
                    connection, _ = listener.accept()
                    with connection:
                        self.boundary.handle(connection)
        finally:
            if path.exists() and stat.S_ISSOCK(path.lstat().st_mode):
                path.unlink()


def _remove_stale_socket(path: Path) -> None:
    if not path.exists():
        return
    if not stat.S_ISSOCK(path.lstat().st_mode):
        raise RuntimeError("authority socket path exists and is not a socket")
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.connect(str(path))
    except ConnectionRefusedError:
        path.unlink()
    else:
        raise RuntimeError("authority server is already running")
    finally:
        probe.close()


def _authorize_request(
    peer: PeerIdentity, request: AuthorityRequest, administrator_did: str
) -> None:
    allowed = _WEB_ACTIONS if peer.role == "community-web" else _POLICY_ACTIONS
    if request.action not in allowed:
        raise AuthorizationError("peer role is not authorized for this action")
    if peer.role == "community-web":
        if request.action == "root_status":
            assert request.target is not None
            if request.authenticated_did not in {
                administrator_did,
                request.target.repo_did,
            }:
                raise AuthorizationError("status requires the author or moderator")
        elif request.authenticated_did != administrator_did:
            raise AuthorizationError("broker did not attest the configured moderator")
    elif request.authenticated_did is not None:
        raise AuthorizationError("policy worker cannot attest a human moderator")


def _parse_request(value: object) -> AuthorityRequest:
    if not isinstance(value, dict) or set(value) - {
        "operationId",
        "action",
        "authenticatedDid",
        "target",
        "subjectDid",
        "rootAdmission",
        "replyPolicy",
        "controllingAction",
        "reason",
    }:
        raise ValidationError("request_invalid", "invalid authority request keys")
    operation_id = value.get("operationId")
    action = value.get("action")
    if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 200:
        raise ValidationError("request_invalid", "operationId is invalid")
    if action not in _WEB_ACTIONS | _POLICY_ACTIONS:
        raise ValidationError("request_invalid", "action is invalid")
    authenticated = value.get("authenticatedDid")
    if authenticated is not None and not isinstance(authenticated, str):
        raise ValidationError("request_invalid", "authenticatedDid is invalid")
    reason = value.get("reason")
    if reason is not None and (not isinstance(reason, str) or len(reason) > 2000):
        raise ValidationError("request_invalid", "reason is invalid")
    request = AuthorityRequest(
        operation_id=operation_id,
        action=action,  # type: ignore[arg-type]
        authenticated_did=authenticated,
        target=_optional_ref(value.get("target"), "target"),
        subject_did=(
            None
            if value.get("subjectDid") is None
            else validate_did(value.get("subjectDid"))
        ),
        root_admission=_optional_ref(value.get("rootAdmission"), "rootAdmission"),
        reply_policy=_optional_ref(value.get("replyPolicy"), "replyPolicy"),
        controlling_action=_optional_ref(
            value.get("controllingAction"), "controllingAction"
        ),
        reason=reason,
    )
    if request.action == "reply_admit" and (
        request.target is None
        or request.root_admission is None
        or request.reply_policy is None
    ):
        raise ValidationError(
            "request_invalid", "reply admission requires exact root and policy refs"
        )
    if request.action == "reply_restore" and request.controlling_action is None:
        raise ValidationError(
            "request_invalid", "reply restoration requires the controlling action"
        )
    if request.action in {"member_add", "member_remove"}:
        if request.subject_did is None or request.target is not None:
            raise ValidationError(
                "request_invalid", "membership action requires only subjectDid"
            )
    elif request.target is None or request.subject_did is not None:
        raise ValidationError(
            "request_invalid", "record action requires only an exact target"
        )
    return request


def _ref(value: object, field: str) -> RecordRef:
    if not isinstance(value, dict) or set(value) != {"uri", "cid"}:
        raise ValidationError("request_invalid", f"{field} must be an exact reference")
    uri, cid = value.get("uri"), value.get("cid")
    if not isinstance(uri, str) or not isinstance(cid, str):
        raise ValidationError("request_invalid", f"{field} must be an exact reference")
    return RecordRef(uri=uri, cid=cid)


def _optional_ref(value: object, field: str) -> RecordRef | None:
    return None if value is None else _ref(value, field)


def _read_frame(connection: socket.socket) -> object:
    chunks = bytearray()
    while len(chunks) <= _MAX_REQUEST_BYTES:
        chunk = connection.recv(min(4096, _MAX_REQUEST_BYTES + 1 - len(chunks)))
        if not chunk:
            break
        chunks.extend(chunk)
        if b"\n" in chunk:
            break
    if len(chunks) > _MAX_REQUEST_BYTES or b"\n" not in chunks:
        raise ValidationError("request_invalid", "authority request frame is invalid")
    frame, remainder = bytes(chunks).split(b"\n", 1)
    if remainder:
        raise ValidationError("request_invalid", "only one request is allowed")
    try:
        return json.loads(frame)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "request_invalid", "authority request is not JSON"
        ) from exc


def _encode_frame(value: Mapping[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _safe_error_code(exc: Exception) -> str:
    if isinstance(exc, AuthorizationError):
        return "unauthorized"
    if isinstance(exc, ValidationError):
        return exc.reason_code
    if isinstance(exc, JournalConflictError):
        return "immutable_conflict"
    if isinstance(exc, PortError):
        return "authority_unavailable"
    if isinstance(exc, sqlite3.Error | OSError):
        return "authority_unavailable"
    return "authority_request_refused"


__all__ = [
    "AuthorityRequest",
    "AuthorityRequestBoundary",
    "BoundaryActionHandler",
    "CommunityAuthorityHandler",
    "PeerIdentity",
    "UnixAuthorityServer",
    "UnixPeerRolePolicy",
]
