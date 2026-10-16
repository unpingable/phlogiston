"""Explicitly invoked offline maintenance CLI for sealed observer history.

Runs only with the live observer processes stopped.  It accepts no network,
credential, signing, authority-writer, or community-repository target
argument: the only inputs are the observer SQLite path, the artifact root,
generation identifiers, high-waters, and process bounds.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date, datetime

from community_model import ValidationError, canonical_json_bytes

from .cold import ColdReader
from .export import export_generation
from .lifecycle import accept_generation, prune_generation, recover


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="communitywatch-archive",
        description="Offline sealed-history maintenance for the observer.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    def common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--db", required=True, help="observer SQLite path")
        sub.add_argument("--artifacts", required=True, help="archive artifact root")

    export = subcommands.add_parser(
        "export", help="close a prefix, stage, validate, and seal a generation"
    )
    common(export)
    export.add_argument(
        "--high-water",
        action="append",
        default=[],
        metavar="SOURCE=CURSOR",
        help="explicit per-source high-water (defaults to committed cursors)",
    )

    for name, help_text in (
        ("recover", "quarantine abandoned staging and reconcile sealed state"),
        ("accept", "prove parity and switch the last-good pointer"),
        ("prune", "delete exactly covered SQLite rows after every gate passes"),
    ):
        sub = subcommands.add_parser(name, help=help_text)
        common(sub)
        if name in ("accept", "prune"):
            sub.add_argument("--generation", required=True)
        if name == "accept":
            sub.add_argument("--community-did", required=True)
            sub.add_argument("--administrator-did", required=True)

    query = subcommands.add_parser(
        "query", help="stream bounded rows from manifest-listed sealed partitions"
    )
    query.add_argument("--artifacts", required=True, help="archive artifact root")
    query.add_argument("--generation", required=True)
    query.add_argument(
        "--table",
        required=True,
        choices=(
            "receipts",
            "quarantine",
            "observations",
            "event_variants",
            "subject_variants",
        ),
    )
    query.add_argument("--from-seq", type=int, default=0)
    query.add_argument("--to-seq", type=int, default=2**63 - 1)
    query.add_argument("--limit", type=int, default=None)
    query.add_argument("--memory-limit", default="256MB")
    return parser


def _high_waters(values: list[str]) -> dict[str, str] | None:
    if not values:
        return None
    result: dict[str, str] = {}
    for value in values:
        source, separator, cursor = value.partition("=")
        if not separator or not source or not cursor:
            raise ValidationError(
                "schema_invalid", "--high-water must be SOURCE=CURSOR"
            )
        result[source] = cursor
    return result


def _json_safe(value: object) -> object:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _emit(value: object) -> None:
    sys.stdout.write(canonical_json_bytes(value).decode("utf-8") + "\n")
    sys.stdout.flush()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "export":
            result = export_generation(
                arguments.db,
                arguments.artifacts,
                high_waters=_high_waters(arguments.high_water),
            )
            _emit(
                {
                    "generation": result.generation_id,
                    "manifestIdentity": result.manifest["manifestIdentity"],
                    "sealed": str(result.sealed_dir),
                }
            )
        elif arguments.command == "recover":
            report = recover(arguments.db, arguments.artifacts)
            _emit(
                {
                    "quarantinedStaging": list(report.quarantined_staging),
                    "reconciledSealed": list(report.reconciled_sealed),
                    "reconciledAccepted": list(report.reconciled_accepted),
                    "disagreements": list(report.disagreements),
                }
            )
        elif arguments.command == "accept":
            result = accept_generation(
                arguments.db,
                arguments.artifacts,
                arguments.generation,
                community_did=arguments.community_did,
                administrator_did=arguments.administrator_did,
            )
            _emit(
                {
                    "generation": result.generation_id,
                    "receiptDigest": result.receipt_digest,
                    "pointerGeneration": result.pointer_generation,
                }
            )
        elif arguments.command == "prune":
            result = prune_generation(
                arguments.db, arguments.artifacts, arguments.generation
            )
            _emit(
                {
                    "generation": result.generation_id,
                    "prunedSequence": result.pruned_sequence,
                    "deletedRows": result.deleted_rows,
                    "alreadyPruned": result.already_pruned,
                }
            )
        elif arguments.command == "query":
            with ColdReader(
                arguments.artifacts, memory_limit=arguments.memory_limit
            ) as reader:
                for row in reader.scan(
                    arguments.generation,
                    arguments.table,
                    min_sequence=arguments.from_seq,
                    max_sequence=arguments.to_seq,
                    limit=arguments.limit,
                ):
                    _emit({key: _json_safe(value) for key, value in row.items()})
        else:  # pragma: no cover - argparse enforces a known command
            raise ValidationError("schema_invalid", "unknown command")
    except ValidationError as exc:
        sys.stderr.write(
            canonical_json_bytes(
                {"error": exc.reason_code, "message": str(exc)}
            ).decode("utf-8")
            + "\n"
        )
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
