"""In-memory authority-side fakes with an exact call log.

These adapters implement the daemon ports over a shared ``FakeRepoState`` so
tests can compose the daemon and observer halves without any network,
credential, or signing material.  Every port invocation is recorded; the
vertical acceptance test asserts from these logs that no user repository was
ever written and that no update or delete operation exists to call.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from community_model import (
    ADMISSION_COLLECTION,
    MOD_ACTION_COLLECTION,
    REPLY_ACTION_COLLECTION,
    REPLY_ADMISSION_COLLECTION,
    AdmissionRecord,
    AuthoritySubjectState,
    AuthorizationError,
    AuthorizedAdmin,
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
    apply_reply_action,
    canonical_json_bytes,
    cid_for_dag_cbor,
    deep_freeze,
)
from community_model.identifiers import parse_at_uri, validate_did

_TID_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"
_AUTHORITY_DEFINING_IGNORED = frozenset({"createdAt"})


def _mint_tid(sequence: int) -> str:
    """Render a small monotone counter as a valid, increasing TID."""

    if sequence < 0:
        raise ValueError("revision sequence must be nonnegative")
    digits = ""
    value = sequence
    while True:
        digits = _TID_ALPHABET[value % 32] + digits
        value //= 32
        if not value:
            break
    return digits.rjust(13, "2")


def _record_uri(repo_did: str, collection: str, rkey: str) -> str:
    return f"at://{repo_did}/{collection}/{rkey}"


@dataclass(frozen=True, slots=True)
class FakeRepoRecord:
    """One immutable record version inside the fake repository state."""

    record: Mapping[str, object]
    cid: str
    rev: str


@dataclass(slots=True)
class FakeRepoState:
    """Shared in-memory repositories plus the repo events the writer emitted."""

    records: dict[tuple[str, str, str], FakeRepoRecord] = field(default_factory=dict)
    rev_counters: dict[str, int] = field(default_factory=dict)
    emitted: list[dict[str, object]] = field(default_factory=list)

    def seed(
        self,
        repo_did: str,
        collection: str,
        rkey: str,
        record: Mapping[str, object],
        *,
        cid: str | None = None,
    ) -> RecordRef:
        """Place a record as pre-existing repository content and emit nothing."""

        minted = cid or cid_for_dag_cbor(canonical_json_bytes(record))
        self.records[(repo_did, collection, rkey)] = FakeRepoRecord(
            record=deep_freeze(record),
            cid=minted,
            rev=self.next_rev(repo_did),
        )
        return RecordRef(uri=_record_uri(repo_did, collection, rkey), cid=minted)

    def move(self, repo_did: str, collection: str, rkey: str, cid: str) -> None:
        """Point an existing record at a new CID, simulating an author edit."""

        key = (repo_did, collection, rkey)
        existing = self.records.get(key)
        if existing is None:
            raise ValidationError("reference_missing", "fake repo has no such record")
        self.records[key] = FakeRepoRecord(
            record=existing.record, cid=cid, rev=self.next_rev(repo_did)
        )

    def drop(self, repo_did: str, collection: str, rkey: str) -> None:
        """Remove a record entirely, simulating an author-side deletion."""

        self.records.pop((repo_did, collection, rkey), None)
        self.next_rev(repo_did)

    def next_rev(self, repo_did: str) -> str:
        sequence = self.rev_counters.get(repo_did, 0) + 1
        self.rev_counters[repo_did] = sequence
        return _mint_tid(sequence)


@dataclass(slots=True)
class FakeRecordReader:
    """Resolve exact/current references against the shared fake state."""

    state: FakeRepoState
    unavailable: bool = False
    calls: list[tuple[str, str]] = field(default_factory=list)

    def get_exact(self, ref: RecordRef) -> ResolveResult:
        self.calls.append(("get_exact", ref.uri))
        if self.unavailable:
            raise PortUnavailableError("fake record reader is unavailable")
        stored = self.state.records.get((ref.repo_did, ref.collection, ref.rkey))
        if stored is None:
            status, current_cid, record = "missing", None, None
        elif stored.cid != ref.cid:
            status, current_cid, record = "mismatch", stored.cid, None
        else:
            status, current_cid, record = "exact", ref.cid, stored.record
        return ResolveResult(
            status=status,
            requested=ref,
            current_cid=current_cid,
            record=record,
            checked_at=datetime.now(UTC),
            trust_mode="test_fixture",
            verification_outcome="verified",
            resolution_method="fake",
            resolver_version="1",
        )

    def get_current(self, uri: str) -> CurrentRecordResult:
        self.calls.append(("get_current", uri))
        if self.unavailable:
            raise PortUnavailableError("fake record reader is unavailable")
        parsed = parse_at_uri(uri)
        stored = self.state.records.get(
            (parsed.authority, parsed.collection, parsed.rkey)
        )
        if stored is None:
            status, current_cid, record = "missing", None, None
        else:
            status, current_cid, record = "present", stored.cid, stored.record
        return CurrentRecordResult(
            status=status,
            uri=uri,
            current_cid=current_cid,
            record=record,
            checked_at=datetime.now(UTC),
            trust_mode="test_fixture",
            verification_outcome="verified",
            resolution_method="fake",
            resolver_version="1",
        )


@dataclass(slots=True)
class FakeAuthorityLedgerReader:
    """Scan the fake community repo for admissions/removals of one subject."""

    state: FakeRepoState
    unavailable: bool = False
    calls: list[tuple[str, str]] = field(default_factory=list)

    def find_subject_lifecycle(
        self, community_did: str, subject: RecordRef
    ) -> AuthoritySubjectState:
        self.calls.append(("find_subject_lifecycle", subject.uri))
        if self.unavailable:
            raise PortUnavailableError("fake authority ledger reader is unavailable")
        admissions: list[RecordRef] = []
        removals: list[RecordRef] = []
        for (repo, collection, rkey), stored in self.state.records.items():
            if repo != community_did:
                continue
            ref = RecordRef(
                uri=_record_uri(repo, collection, rkey),
                cid=stored.cid,
            )
            try:
                if collection == ADMISSION_COLLECTION:
                    parsed = AdmissionRecord.from_record(dict(stored.record))
                    if parsed.subject == subject:
                        admissions.append(ref)
                elif collection == MOD_ACTION_COLLECTION:
                    parsed_action = ModActionRecord.from_record(dict(stored.record))
                    if parsed_action.subject == subject:
                        removals.append(ref)
            except ValidationError:
                continue
        high_water = self.state.rev_counters.get(community_did, 0)
        return AuthoritySubjectState(
            subject=subject,
            valid_admissions=tuple(admissions),
            valid_removals=tuple(removals),
            community_repo_high_water=_mint_tid(high_water),
        )

    def eligible_reply_uris(
        self, community_did: str, discussion: RecordRef
    ) -> frozenset[str]:
        return frozenset(
            parsed.subject.uri
            for (repo, collection, _), stored in self.state.records.items()
            if repo == community_did and collection == REPLY_ADMISSION_COLLECTION
            for parsed in (ReplyAdmissionRecord.from_record(dict(stored.record)),)
            if parsed.discussion == discussion
        )

    def moderation_state(
        self, community_did: str, moderation_key: str
    ) -> ReplyModerationState | None:
        admissions: dict[str, tuple[RecordRef, ReplyAdmissionRecord]] = {}
        actions: list[tuple[RecordRef, ReplyActionRecord]] = []
        for (repo, collection, rkey), stored in self.state.records.items():
            if repo != community_did:
                continue
            ref = RecordRef(uri=_record_uri(repo, collection, rkey), cid=stored.cid)
            if collection == REPLY_ADMISSION_COLLECTION:
                admission = ReplyAdmissionRecord.from_record(dict(stored.record))
                admissions[ref.uri] = (ref, admission)
            elif collection == REPLY_ACTION_COLLECTION:
                action = ReplyActionRecord.from_record(dict(stored.record))
                if action.moderation_key == moderation_key:
                    actions.append((ref, action))
        state: ReplyModerationState | None = None
        while actions:
            candidates = [
                pair
                for pair in actions
                if pair[1].previous_action
                == (None if state is None else state.last_action)
            ]
            if len(candidates) != 1:
                raise PortUnavailableError("fake reply action chain is invalid")
            action_ref, action = candidates[0]
            admission_ref, admission = admissions[action.admission.uri]
            state = apply_reply_action(
                state,
                action,
                action_ref=action_ref,
                admission=admission,
                admission_ref=admission_ref,
                community_did=community_did,
            )
            actions.remove(candidates[0])
        return state


@dataclass(slots=True)
class FakeAdminAuthorizer:
    """Compare an injected effective UID with the configured boundary."""

    administrator_did: str
    allowed_uid: int
    effective_uid: int
    calls: list[str] = field(default_factory=list)

    def require(self, action: Literal["admit", "remove"]) -> AuthorizedAdmin:
        self.calls.append(action)
        if self.effective_uid != self.allowed_uid:
            raise AuthorizationError("effective UID is not the configured principal")
        return AuthorizedAdmin(
            did=self.administrator_did, effective_uid=self.effective_uid
        )


@dataclass(slots=True)
class FakeCredentialProvider:
    """Resolve configured external references to inert fake handles."""

    handles: Mapping[str, str]
    calls: list[str] = field(default_factory=list)

    def require(self, reference: str) -> str:
        self.calls.append(reference)
        handle = self.handles.get(reference)
        if handle is None:
            raise CredentialUnavailableError(
                "the configured credential reference is unavailable"
            )
        return handle


@dataclass(slots=True)
class FakeAuthorityWriter:
    """Create-only fake community writer; update/delete do not exist."""

    state: FakeRepoState
    unavailable: bool = False
    calls: list[tuple[str, str, str]] = field(default_factory=list)

    def create_immutable(
        self,
        repo_did: str,
        collection: str,
        semantic_operation_id: str,
        record: Mapping[str, object],
    ) -> ImmutableCreateOutcome:
        self.calls.append(("create_immutable", repo_did, collection))
        if self.unavailable:
            raise PortUnavailableError("fake authority writer is unavailable")
        validate_did(repo_did)
        frozen = deep_freeze(record)
        key = (repo_did, collection, semantic_operation_id)
        existing = self.state.records.get(key)
        if existing is not None:
            if _authority_compatible(existing.record, frozen):
                return ImmutableCreateOutcome(
                    RecordRef(uri=_record_uri(*key), cid=existing.cid), created=False
                )
            raise ImmutableConflictError(
                "deterministic authority rkey holds incompatible content"
            )
        cid = cid_for_dag_cbor(canonical_json_bytes(record))
        rev = self.state.next_rev(repo_did)
        self.state.records[key] = FakeRepoRecord(record=frozen, cid=cid, rev=rev)
        self.state.emitted.append(
            {
                "repo": repo_did,
                "rev": rev,
                "operation": "create",
                "collection": collection,
                "rkey": semantic_operation_id,
                "cid": cid,
                "record": dict(record),
            }
        )
        return ImmutableCreateOutcome(
            RecordRef(uri=_record_uri(*key), cid=cid), created=True
        )


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
