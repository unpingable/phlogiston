from __future__ import annotations

import inspect

from communityd import (
    AdminAuthorizer,
    AuthorityLedgerReader,
    AuthorityWriter,
    RecordReader,
)


def _public_callables(protocol: type[object]) -> set[str]:
    return {
        name
        for name, value in vars(protocol).items()
        if not name.startswith("_") and callable(value)
    }


def test_writer_port_is_create_only_and_reader_is_daemon_owned() -> None:
    assert _public_callables(AuthorityWriter) == {"create_immutable"}
    assert _public_callables(AuthorityLedgerReader) == {"find_subject_lifecycle"}
    assert _public_callables(RecordReader) == {"get_exact", "get_current"}
    assert _public_callables(AdminAuthorizer) == {"require"}

    parameters = inspect.signature(AuthorityWriter.create_immutable).parameters
    assert tuple(parameters) == (
        "self",
        "repo_did",
        "collection",
        "semantic_operation_id",
        "record",
    )
    assert tuple(inspect.signature(RecordReader.get_exact).parameters) == (
        "self",
        "ref",
    )
    assert tuple(inspect.signature(RecordReader.get_current).parameters) == (
        "self",
        "uri",
    )
    assert tuple(
        inspect.signature(AuthorityLedgerReader.find_subject_lifecycle).parameters
    ) == ("self", "community_did", "subject")
    assert tuple(inspect.signature(AdminAuthorizer.require).parameters) == (
        "self",
        "action",
    )
