"""SSH/local CLI for the disposable Juniper Spaces authority writer."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from community_model import AuthorizationError, ValidationError, WriteFailedError
from community_model.identifiers import format_rfc3339, validate_did
from community_space_model import ExactSpaceRecordReference, SpaceIdentity
from community_space_wire import (
    ADMISSION_COLLECTION,
    POST_COLLECTION,
    SUBMISSION_COLLECTION,
)

from .operations import LocalAdminAuthorizer
from .spaces_alpha import (
    AdmitOccurrence,
    RemoveOccurrence,
    SpacesAlphaAuthorityConfig,
    SpacesAlphaPorts,
    admit_space,
    remove_space,
)
from .spaces_alpha_transport import (
    CommandSpacesAlphaWriter,
    FileAuthorizationOccurrenceStore,
    RuntimeCredentialReference,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="communityd-spaces-alpha")
    parser.add_argument("--config", required=True)
    parser.add_argument("--request", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        config, ports = _runtime(Path(arguments.config))
        request = _json(Path(arguments.request))
        now = datetime.now(UTC).replace(microsecond=0)
        common = {
            "decision_id": _text(request, "decisionId"),
            "authorization_basis_receipt_id": _text(
                request, "authorizationBasisReceiptId"
            ),
            "authorization_provenance_receipt_id": _text(
                request, "authorizationProvenanceReceiptId"
            ),
            "authorized_at": format_rfc3339(now - timedelta(seconds=1)),
            "expires_at": format_rfc3339(now + timedelta(minutes=5)),
        }
        action = request.get("action")
        if action == "admit":
            outcome = admit_space(
                ports,
                config,
                AdmitOccurrence(
                    submission=_reference(
                        config.space,
                        request.get("submission"),
                        SUBMISSION_COLLECTION,
                    ),
                    subject=_reference(
                        config.space, request.get("subject"), POST_COLLECTION
                    ),
                    submission_occurrence_id=_text(request, "submissionOccurrenceId"),
                    source_observation_receipt_id=_text(
                        request, "sourceObservationReceiptId"
                    ),
                    **common,
                ),
                now=now,
            )
        elif action == "remove":
            outcome = remove_space(
                ports,
                config,
                RemoveOccurrence(
                    admission=_reference(
                        config.space,
                        request.get("admission"),
                        ADMISSION_COLLECTION,
                    ),
                    subject=_reference(
                        config.space, request.get("subject"), POST_COLLECTION
                    ),
                    admission_occurrence_id=_text(request, "admissionOccurrenceId"),
                    reason=_text(request, "reason"),
                    **common,
                ),
                now=now,
            )
        else:
            raise ValidationError("action_invalid", "unsupported authority action")
        sys.stdout.write(
            json.dumps(
                {
                    "record": {
                        "uri": outcome.record.uri,
                        "cid": outcome.record.cid,
                    },
                    "authorization": {
                        "authorizationId": outcome.authorization.authorization_id,
                        "communityIdentityId": outcome.authorization.community.identity_id,
                        "decisionId": outcome.authorization.decision_id,
                        "moderatorDid": outcome.authorization.moderator_did,
                        "action": outcome.authorization.action.value,
                        "targetOccurrenceId": outcome.authorization.target_occurrence_id,
                        "authorizationBasisReceiptId": outcome.authorization.authorization_basis_receipt_id,
                        "authorizedAt": outcome.authorization.authorized_at,
                        "expiresAt": outcome.authorization.expires_at,
                        "provenanceReceiptId": outcome.authorization.provenance_receipt_id,
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        return 0
    except (AuthorizationError, ValidationError, WriteFailedError, ValueError, OSError):
        sys.stderr.write('{"error":"communityd_spaces_alpha_refused"}\n')
        return 1


def _runtime(path: Path) -> tuple[SpacesAlphaAuthorityConfig, SpacesAlphaPorts]:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    expected = {
        "space_authority_did",
        "space_type",
        "space_skey",
        "community_actor_did",
        "administrator_did",
        "allowed_uid",
        "credential_ref",
        "writer_command",
        "occurrence_store",
        "request_timeout_ms",
    }
    if set(raw) != expected:
        raise ValueError("communityd Spaces config fields differ")
    space = SpaceIdentity(
        validate_did(raw["space_authority_did"]),
        str(raw["space_type"]),
        str(raw["space_skey"]),
    )
    actor = validate_did(raw["community_actor_did"])
    admin = validate_did(raw["administrator_did"])
    uid = raw["allowed_uid"]
    command = raw["writer_command"]
    timeout_ms = raw["request_timeout_ms"]
    if (
        isinstance(uid, bool)
        or not isinstance(uid, int)
        or uid < 0
        or not isinstance(command, list)
        or not command
        or any(not isinstance(item, str) or not item for item in command)
        or isinstance(timeout_ms, bool)
        or not isinstance(timeout_ms, int)
        or not 1 <= timeout_ms <= 60_000
    ):
        raise ValueError("communityd Spaces config is invalid")
    credential_ref = str(raw["credential_ref"])
    authority = SpacesAlphaAuthorityConfig(space, actor, admin, credential_ref)
    return authority, SpacesAlphaPorts(
        authorizer=LocalAdminAuthorizer(administrator_did=admin, allowed_uid=uid),
        credentials=RuntimeCredentialReference(
            expected_reference=credential_ref,
            environment_key="JUNIPER_COMMUNITYD_RUNTIME_DIR",
        ),
        writer=CommandSpacesAlphaWriter(command, timeout_seconds=timeout_ms / 1000),
        occurrences=FileAuthorizationOccurrenceStore(str(raw["occurrence_store"])),
    )


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf8"))
    if not isinstance(value, dict):
        raise ValueError("authority request must be an object")
    return value


def _text(value: dict[str, object], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result or "\x00" in result:
        raise ValueError("authority request text is invalid")
    return result


def _reference(
    space: SpaceIdentity, value: object, expected_collection: str
) -> ExactSpaceRecordReference:
    if not isinstance(value, dict) or set(value) != {
        "authorDid",
        "collection",
        "rkey",
        "cid",
    }:
        raise ValueError("authority exact reference shape differs")
    if value["collection"] != expected_collection:
        raise ValueError("authority exact reference collection differs")
    return ExactSpaceRecordReference(
        space,
        str(value["authorDid"]),
        str(value["collection"]),
        str(value["rkey"]),
        str(value["cid"]),
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
