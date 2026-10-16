"""``community-submit`` — suggest one of your own Bluesky posts to a community.

The participant sees ordinary language. NSIDs, CIDs, MSTs, CARs, repository
proofs and governance vocabulary stay behind ``--verbose``.

The one distinction this tool always makes plainly is **submitted is not
added**: writing a submission records your intent in your own repository; a
moderator still has to add it before it appears in the community.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from community_model import ValidationError

from .submit import SubmitOutcome, parse_post_reference, submit
from .transport import (
    AuthorizationFailed,
    Credential,
    HttpPds,
    Pds,
    ReadUnavailable,
    SubmitError,
    WriteAmbiguous,
)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 3
EXIT_VALIDATION = 4
EXIT_CONFLICT = 5
EXIT_READ_UNAVAILABLE = 6
EXIT_CREDENTIAL_UNAVAILABLE = 7
EXIT_WRITE_FAILED = 8

_EXIT_FOR_CODE = {
    "malformed_link": EXIT_USAGE,
    "not_a_post": EXIT_USAGE,
    "not_your_post": EXIT_REFUSED,
    "record_invalid": EXIT_VALIDATION,
    "rkey_conflict": EXIT_CONFLICT,
    "post_missing": EXIT_READ_UNAVAILABLE,
    "read_failed": EXIT_READ_UNAVAILABLE,
    "transport_failed": EXIT_READ_UNAVAILABLE,
    "authorization_failed": EXIT_CREDENTIAL_UNAVAILABLE,
    "write_unsettled": EXIT_WRITE_FAILED,
    "write_failed": EXIT_WRITE_FAILED,
}

_CREDENTIAL_KEYS = frozenset({"identifier", "app_password"})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="community-submit",
        description="Suggest one of your own Bluesky posts to a community.",
    )
    parser.add_argument(
        "post", help="link to your Bluesky post (bsky.app URL or at:// URI)"
    )
    parser.add_argument(
        "--community", required=True, help="the community's DID (did:plc:... )"
    )
    parser.add_argument(
        "--pds",
        required=True,
        help="your PDS base URL, for example https://bsky.social",
    )
    parser.add_argument(
        "--credential",
        required=True,
        help=(
            "env:VARNAME naming an environment variable that holds the path of "
            'a JSON file {"identifier": ..., "app_password": ...}'
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="also print the exact record coordinates",
    )
    return parser


def load_credential(reference: str) -> Credential:
    """Resolve ``env:VARNAME`` to a credential file kept outside the repo.

    No failure message repeats the variable's value or any file content.
    """

    if not reference.startswith("env:"):
        raise AuthorizationFailed(
            "authorization_failed", "--credential must be an env:VARNAME reference"
        )
    variable = reference[len("env:") :]
    path_value = os.environ.get(variable)
    if not path_value:
        raise AuthorizationFailed(
            "authorization_failed",
            f"the environment variable {variable} is not set",
        )
    try:
        raw = Path(path_value).read_bytes()
    except OSError:
        raise AuthorizationFailed(
            "authorization_failed", "the credential file could not be read"
        ) from None
    try:
        document = json.loads(raw)
    except ValueError:
        raise AuthorizationFailed(
            "authorization_failed", "the credential file is not valid JSON"
        ) from None
    if not isinstance(document, dict) or set(document) != _CREDENTIAL_KEYS:
        raise AuthorizationFailed(
            "authorization_failed",
            "the credential file must contain exactly identifier and app_password",
        )
    identifier = document["identifier"]
    app_password = document["app_password"]
    if (
        not isinstance(identifier, str)
        or not identifier
        or not isinstance(app_password, str)
        or not app_password
    ):
        raise AuthorizationFailed(
            "authorization_failed",
            "identifier and app_password must both be non-empty",
        )
    return Credential(identifier=identifier, app_password=app_password)


def render(outcome: SubmitOutcome, *, verbose: bool) -> str:
    """Ordinary-language result; the submitted/added distinction is explicit."""

    if outcome.result == "already_submitted":
        headline = f"You had already submitted this post to {outcome.community_did}."
    else:
        headline = f"Submitted to {outcome.community_did} for review."
    lines = [
        headline,
        "This does not add it to the community yet — a moderator still has to "
        "add it before it appears.",
    ]
    if verbose:
        lines.extend(
            [
                "",
                f"post      {outcome.subject.uri}",
                f"exact version  {outcome.subject.cid}",
                f"submission  {outcome.submission_uri}",
                f"submission version  {outcome.submission_cid or '(unreported)'}",
            ]
        )
    return "\n".join(lines)


def run(
    argv: Sequence[str] | None = None,
    *,
    pds_factory=None,
    credential_loader=load_credential,
) -> tuple[int, str, str]:
    """Return ``(exit_code, stdout_text, stderr_text)`` for one invocation."""

    parser = _parser()
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as exc:  # argparse already wrote its own message
        return int(exc.code or EXIT_USAGE), "", ""

    try:
        post = parse_post_reference(arguments.post)
        credential = credential_loader(arguments.credential)
        factory = pds_factory or (lambda url: HttpPds(url))
        pds: Pds = factory(arguments.pds)
        outcome = submit(
            pds,
            credential,
            community_did=arguments.community,
            post=post,
        )
    except ValidationError as exc:
        return EXIT_USAGE, "", f"community-submit: {exc.issue.message}\n"
    except (AuthorizationFailed, ReadUnavailable, WriteAmbiguous, SubmitError) as exc:
        code = _EXIT_FOR_CODE.get(exc.code, EXIT_WRITE_FAILED)
        return code, "", f"community-submit: {exc.message}\n"
    return EXIT_OK, render(outcome, verbose=arguments.verbose) + "\n", ""


def main(argv: Sequence[str] | None = None) -> int:
    code, out, err = run(argv)
    if out:
        sys.stdout.write(out)
    if err:
        sys.stderr.write(err)
    return code


__all__ = [
    "EXIT_CONFLICT",
    "EXIT_CREDENTIAL_UNAVAILABLE",
    "EXIT_OK",
    "EXIT_READ_UNAVAILABLE",
    "EXIT_REFUSED",
    "EXIT_USAGE",
    "EXIT_VALIDATION",
    "EXIT_WRITE_FAILED",
    "load_credential",
    "main",
    "render",
    "run",
]
