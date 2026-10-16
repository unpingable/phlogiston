"""Local, explicitly configured crash injection for supervised PCV0 recovery.

This wrapper does not alter or broaden an authority write.  It consumes one
host-local trigger only after the delegated immutable create has returned, then
terminates before the operation journal can record the successful response.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path

from community_model import ImmutableCreateOutcome

from .ports import AuthorityWriter


class PostCommitFaultAuthorityWriter:
    def __init__(
        self,
        delegate: AuthorityWriter,
        directory: str | Path,
        *,
        terminate: Callable[[], None] = lambda: os._exit(86),
    ) -> None:
        self.delegate = delegate
        self.directory = Path(directory)
        self.terminate = terminate

    def create_immutable(
        self,
        repo_did: str,
        collection: str,
        semantic_operation_id: str,
        record: Mapping[str, object],
    ) -> ImmutableCreateOutcome:
        outcome = self.delegate.create_immutable(
            repo_did, collection, semantic_operation_id, record
        )
        trigger = self.directory / "authority.once"
        try:
            trigger.replace(self.directory / "authority.consumed")
        except FileNotFoundError:
            return outcome
        self.terminate()
        raise RuntimeError("integration fault termination returned unexpectedly")


__all__ = ["PostCommitFaultAuthorityWriter"]
