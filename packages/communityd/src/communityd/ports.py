"""Create-only authority ports owned exclusively by ``communityd``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol, runtime_checkable

from community_model import (
    AuthoritySubjectState,
    AuthorizedAdmin,
    CurrentRecordResult,
    ImmutableCreateOutcome,
    RecordRef,
    ResolveResult,
)


@runtime_checkable
class RecordReader(Protocol):
    """Read referenced records without leaking credentials into shared code."""

    def get_exact(self, ref: RecordRef) -> ResolveResult: ...

    def get_current(self, uri: str) -> CurrentRecordResult: ...


@runtime_checkable
class AuthorityLedgerReader(Protocol):
    """Read the community actor ledger directly, never observer artifacts."""

    def find_subject_lifecycle(
        self, community_did: str, subject: RecordRef
    ) -> AuthoritySubjectState: ...


@runtime_checkable
class AdminAuthorizer(Protocol):
    """Derive the configured administrator from the local principal."""

    def require(
        self, action: Literal["admit", "remove", "membership"]
    ) -> AuthorizedAdmin: ...


@runtime_checkable
class CredentialProvider(Protocol):
    """Resolve an external credential reference without storing its value."""

    def require(self, reference: str) -> str: ...


@runtime_checkable
class AuthorityWriter(Protocol):
    """Expose immutable creation only; update and delete are intentionally absent."""

    def create_immutable(
        self,
        repo_did: str,
        collection: str,
        semantic_operation_id: str,
        record: Mapping[str, object],
    ) -> ImmutableCreateOutcome: ...
