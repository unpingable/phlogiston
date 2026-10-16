"""Manual local administrative CLI for the sole authority writer.

Success writes one JSON object to stdout and nothing else; failure leaves
stdout empty and writes one redacted ``{"error", "message"}`` object to
stderr.  Stable exits: 0 success/help, 2 usage/configuration, 3 local
authorization, 4 record/reference validation, 5 immutable conflict or
unsupported readmission, 6 read/resolution unavailable, 7 credential
unavailable, 8 write failed or ambiguous.  No actor override flag exists.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TextIO

from community_model import (
    AuthorizationError,
    CredentialUnavailableError,
    ImmutableConflictError,
    PortError,
    PortUnavailableError,
    RecordRef,
    UnsupportedReadmissionError,
    ValidationError,
    WriteFailedError,
)

from .config import ConfigError, DaemonConfig, load_config
from .fakes import (
    FakeAdminAuthorizer,
    FakeAuthorityLedgerReader,
    FakeAuthorityWriter,
    FakeCredentialProvider,
    FakeRecordReader,
    FakeRepoState,
)
from .faults import PostCommitFaultAuthorityWriter
from .identity import AuthorityDidResolver
from .journal import JournalConflictError, SQLiteOperationJournal
from .operations import (
    DaemonPorts,
    LocalAdminAuthorizer,
    OperationOutcome,
    admit,
    remove,
)
from .pds import (
    EnvFileCredentialProvider,
    PdsAuthorityLedgerReader,
    PdsAuthorityWriter,
    PdsRecordReader,
    PdsSession,
    PdsTransport,
    ResolvingPdsRecordReader,
)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_AUTHORIZATION = 3
EXIT_VALIDATION = 4
EXIT_CONFLICT = 5
EXIT_READ_UNAVAILABLE = 6
EXIT_CREDENTIAL_UNAVAILABLE = 7
EXIT_WRITE_FAILED = 8


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="communityd",
        description="Manual administrative writer for one community actor.",
    )
    parser.add_argument("--config", required=True, help="daemon TOML path")
    subcommands = parser.add_subparsers(dest="command", required=True)

    admit_parser = subcommands.add_parser(
        "admit", help="admit one exact submission into the community"
    )
    admit_parser.add_argument("--submission-uri", required=True)
    admit_parser.add_argument("--submission-cid", required=True)

    remove_parser = subcommands.add_parser(
        "remove", help="remove one exact admission's subject from the view"
    )
    remove_parser.add_argument("--admission-uri", required=True)
    remove_parser.add_argument("--admission-cid", required=True)
    remove_parser.add_argument("--reason", default=None)
    return parser


def build_runtime(config: DaemonConfig) -> DaemonPorts:
    """Construct the adapter runtime named by the configuration."""

    journal = (
        SQLiteOperationJournal(config.operation_journal_path)
        if config.operation_journal_path is not None
        else None
    )

    if (
        config.reader_adapter == "fake"
        and config.ledger_adapter == "fake"
        and config.writer_adapter == "fake"
        and config.credential_provider == "fake"
    ):
        state = FakeRepoState()
        return DaemonPorts(
            reader=FakeRecordReader(state),
            ledger=FakeAuthorityLedgerReader(state),
            authorizer=FakeAdminAuthorizer(
                administrator_did=config.administrator_did,
                allowed_uid=config.allowed_uid,
                effective_uid=config.allowed_uid,
            ),
            writer=FakeAuthorityWriter(state),
            credentials=FakeCredentialProvider({config.credential_ref: "fake-handle"}),
            operation_journal=journal,
        )

    # Any real adapter runs under the ratified OQ-4/A local model: the OS
    # effective UID is checked against allowed_uid before any network,
    # credential, reader, or writer call.
    authorizer = LocalAdminAuthorizer(
        administrator_did=config.administrator_did,
        allowed_uid=config.allowed_uid,
    )
    transport = PdsTransport(
        base_url=config.community_pds_url.rstrip("/"),
        timeout_seconds=config.request_timeout_ms / 1000,
        max_retries=config.max_retries,
    )
    authority_reader = PdsRecordReader(transport)
    provider: EnvFileCredentialProvider | FakeCredentialProvider
    if config.credential_provider == "env_file":
        provider = EnvFileCredentialProvider()
    else:
        provider = FakeCredentialProvider({config.credential_ref: "fake-handle"})

    state = FakeRepoState()
    reader = (
        FakeRecordReader(state)
        if config.reader_adapter == "fake"
        else PdsRecordReader(transport)
        if config.reader_adapter == "pds_fixed"
        else ResolvingPdsRecordReader(
            AuthorityDidResolver(
                plc_directory_url=config.plc_directory_url,
                timeout_seconds=config.request_timeout_ms / 1000,
                cache_size=config.did_cache_size,
                allow_loopback=config.allow_loopback_public_endpoints,
                bluesky_only=config.p0_profile == "root_only",
                p0_test_pds_origin=config.p0_test_pds_origin,
                p0_hosted_pds_origin=config.p0_hosted_pds_origin,
                p0_allow_bluesky=config.p0_allow_bluesky,
            ),
            timeout_seconds=config.request_timeout_ms / 1000,
            max_retries=config.max_retries,
            cache_size=config.did_cache_size,
        )
    )
    ledger = (
        FakeAuthorityLedgerReader(state)
        if config.ledger_adapter == "fake"
        else PdsAuthorityLedgerReader(transport)
    )
    writer: FakeAuthorityWriter | PdsAuthorityWriter | PostCommitFaultAuthorityWriter
    if config.writer_adapter == "fake":
        writer = FakeAuthorityWriter(state)
    else:
        # parse_config guarantees env_file when the pds writer is selected.
        assert isinstance(provider, EnvFileCredentialProvider)
        session = PdsSession(
            transport,
            lambda: provider.load(config.credential_ref),
            expected_did=config.community_did,
        )
        writer = PdsAuthorityWriter(transport, session)
        if config.integration_fault_directory is not None:
            writer = PostCommitFaultAuthorityWriter(
                writer, config.integration_fault_directory
            )
    return DaemonPorts(
        reader=reader,
        ledger=ledger,
        authorizer=authorizer,
        writer=writer,
        credentials=provider,
        operation_journal=journal,
        authority_reader=(
            authority_reader if config.writer_adapter == "pds" else reader
        ),
    )


def _emit_error(stream: TextIO, code: str, message: str) -> None:
    stream.write(json.dumps({"error": code, "message": message}) + "\n")


def _reference(uri: str, cid: str) -> RecordRef:
    return RecordRef(uri=uri, cid=cid)


def _run(
    arguments: argparse.Namespace,
    *,
    runtime: DaemonPorts | None,
) -> tuple[int, OperationOutcome | None, str, str]:
    """Execute one parsed invocation, returning exit/outcome/error details."""

    try:
        config = load_config(arguments.config)
    except ConfigError as exc:
        return EXIT_USAGE, None, "config_invalid", str(exc)
    if config.p0_profile == "root_only":
        return (
            EXIT_USAGE,
            None,
            "p0_socket_required",
            "P0 authority actions require the supervised socket boundary",
        )
    ports = runtime if runtime is not None else build_runtime(config)
    try:
        if arguments.command == "admit":
            reference = _reference(arguments.submission_uri, arguments.submission_cid)
            outcome = admit(ports, config, reference, now=datetime.now(UTC))
        else:
            reference = _reference(arguments.admission_uri, arguments.admission_cid)
            outcome = remove(
                ports, config, reference, arguments.reason, now=datetime.now(UTC)
            )
    except AuthorizationError:
        return (
            EXIT_AUTHORIZATION,
            None,
            "unauthorized",
            "local principal is not authorized",
        )
    except ValidationError as exc:
        return EXIT_VALIDATION, None, exc.reason_code, "reference validation failed"
    except UnsupportedReadmissionError:
        return (
            EXIT_CONFLICT,
            None,
            "unsupported_readmission",
            "a valid removal terminalizes this exact subject",
        )
    except (ImmutableConflictError, JournalConflictError):
        return (
            EXIT_CONFLICT,
            None,
            "immutable_conflict",
            "deterministic authority rkey holds incompatible content",
        )
    except CredentialUnavailableError:
        return (
            EXIT_CREDENTIAL_UNAVAILABLE,
            None,
            "credential_unavailable",
            "the configured credential reference is unavailable",
        )
    except WriteFailedError:
        return (
            EXIT_WRITE_FAILED,
            None,
            "write_failed",
            "authority write failed or remained ambiguous",
        )
    except PortUnavailableError:
        return (
            EXIT_READ_UNAVAILABLE,
            None,
            "read_unavailable",
            "record read or resolution is unavailable",
        )
    except PortError:
        return EXIT_WRITE_FAILED, None, "write_failed", "authority operation failed"
    return EXIT_OK, outcome, "", ""


def main(
    argv: Sequence[str] | None = None,
    *,
    runtime: DaemonPorts | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    try:
        arguments = _parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    code, outcome, error, message = _run(arguments, runtime=runtime)
    if outcome is not None:
        out.write(
            json.dumps(
                {
                    "operation": outcome.operation,
                    "uri": outcome.record.uri,
                    "cid": outcome.record.cid,
                }
            )
            + "\n"
        )
    else:
        _emit_error(err, error, message)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
