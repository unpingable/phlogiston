"""One self-submission: resolve a post URL, prove ownership, write the record.

Semantics are exactly V0's and nothing here relaxes them:

* the record written is ``community_model.SubmissionRecord``, unchanged;
* self-submission is enforced before any write — the authenticated
  participant's DID must be the authority of the post's AT URI, which is the
  same rule ``community-model`` applies at ingest (``records.py`` rejects a
  mismatch with ``repo_mismatch``);
* the exact subject CID comes from the repository's own ``getRecord``
  response, never from the URL or from user input;
* the submission rkey is a TID derived from the community and the exact
  subject, so re-running is idempotent at the same key rather than piling up
  duplicate intent records; and
* a write is attempted once. If its response is lost, the deterministic rkey
  is read back to settle what happened; the write is never blindly retried.

Submitting is not admission. This tool cannot admit anything: it holds no
community credential and knows no admission collection.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from community_model import (
    POST_COLLECTION,
    SUBMISSION_COLLECTION,
    RecordRef,
    SubmissionRecord,
    ValidationError,
)
from community_model.identifiers import (
    format_rfc3339,
    parse_rfc3339,
    validate_did,
)

from .transport import (
    Credential,
    Pds,
    ReadUnavailable,
    SubmitError,
    WriteAmbiguous,
)

_TID_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"

_BSKY_POST_URL = re.compile(
    r"^https?://[^/]+/profile/(?P<authority>[^/]+)/post/(?P<rkey>[^/?#]+)/?$"
)
_AT_POST_URI = re.compile(
    r"^at://(?P<authority>[^/]+)/(?P<collection>[^/]+)/(?P<rkey>[^/?#]+)$"
)


@dataclass(frozen=True, slots=True)
class PostLocator:
    """Where a post lives, as named by the participant."""

    authority: str
    rkey: str


@dataclass(frozen=True, slots=True)
class SubmitOutcome:
    """What happened, in terms the caller can render for a human."""

    result: str
    community_did: str
    subject: RecordRef
    submission_uri: str
    submission_cid: str | None


def parse_post_reference(value: str) -> PostLocator:
    """Accept a bsky.app post URL or an ``at://`` post URI."""

    text = value.strip()
    match = _BSKY_POST_URL.match(text)
    if match:
        return PostLocator(match.group("authority"), match.group("rkey"))
    match = _AT_POST_URI.match(text)
    if match:
        if match.group("collection") != POST_COLLECTION:
            raise SubmitError(
                "not_a_post",
                "that link points at something other than a Bluesky post",
            )
        return PostLocator(match.group("authority"), match.group("rkey"))
    raise SubmitError(
        "malformed_link",
        "that does not look like a Bluesky post link",
    )


def submission_rkey(community_did: str, subject: RecordRef) -> str:
    """A TID-shaped, content-derived rkey so re-running is idempotent.

    V0 requires submission rkeys to be TIDs, so a content hash cannot be used
    directly; this folds the digest into the TID alphabet the same way the
    live exercise harness does.
    """

    digest = hashlib.sha256(
        f"community-submit\n{community_did}\n{subject.uri}\n{subject.cid}".encode()
    ).digest()
    value = int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF
    return "".join(_TID_ALPHABET[(value >> shift) & 31] for shift in range(60, -1, -5))


def _authority_of(uri: str) -> str:
    match = _AT_POST_URI.match(uri)
    if match is None:
        raise ReadUnavailable(
            "read_failed", "the repository returned an unrecognisable record URI"
        )
    return match.group("authority")


def _defining_fields(record: Mapping[str, object]) -> tuple[object, object]:
    """The parts of a submission that make it the same intent, sans time."""

    return record.get("community"), record.get("subject")


def submit(
    pds: Pds,
    credential: Credential,
    *,
    community_did: str,
    post: PostLocator,
    now: datetime | None = None,
) -> SubmitOutcome:
    """Perform one self-submission and report exactly what happened."""

    validate_did(community_did)
    session = pds.create_session(credential)

    found = pds.get_record(post.authority, POST_COLLECTION, post.rkey, session.token)
    if found is None:
        raise ReadUnavailable(
            "post_missing", "that post is not in its author's repository"
        )
    uri = found.get("uri")
    cid = found.get("cid")
    if not isinstance(uri, str) or not isinstance(cid, str) or not cid:
        raise ReadUnavailable(
            "read_failed", "the repository did not return an exact post version"
        )

    # Self-submission, enforced before anything is written.
    if _authority_of(uri) != session.did:
        raise SubmitError(
            "not_your_post",
            "that post belongs to someone else; this community only accepts "
            "posts submitted by their own author",
        )

    try:
        subject = RecordRef(uri=uri, cid=cid)
        # One instant, formatted once: the signed raw value and the parsed
        # datetime must agree exactly or community-model rejects the record.
        created_at_raw = format_rfc3339(now if now is not None else datetime.now(UTC))
        record = SubmissionRecord(
            community=community_did,
            subject=subject,
            created_at=parse_rfc3339(created_at_raw),
            created_at_raw=created_at_raw,
        ).to_record()
    except ValidationError as exc:
        raise SubmitError(
            "record_invalid", f"the submission record is not valid: {exc.issue.message}"
        ) from exc

    rkey = submission_rkey(community_did, subject)
    existing = pds.get_record(session.did, SUBMISSION_COLLECTION, rkey, session.token)
    if existing is not None:
        return _settle_existing(existing, record, community_did, subject)

    try:
        created = pds.create_record(
            session.did, SUBMISSION_COLLECTION, rkey, record, session.token
        )
    except WriteAmbiguous:
        # The commit may have landed. Read back the deterministic rkey rather
        # than retrying, which could fork this repository's history.
        try:
            readback = pds.get_record(
                session.did, SUBMISSION_COLLECTION, rkey, session.token
            )
        except SubmitError as exc:
            raise WriteAmbiguous(
                "write_unsettled",
                "the submission may or may not have been written; check your "
                "repository before trying again",
            ) from exc
        if readback is None:
            raise WriteAmbiguous(
                "write_failed",
                "the submission was not written; nothing was recorded",
            ) from None
        return _settle_existing(readback, record, community_did, subject)

    created_cid = created.get("cid")
    return SubmitOutcome(
        result="submitted",
        community_did=community_did,
        subject=subject,
        submission_uri=str(created.get("uri", "")),
        submission_cid=created_cid if isinstance(created_cid, str) else None,
    )


def _settle_existing(
    existing: Mapping[str, object],
    intended: Mapping[str, object],
    community_did: str,
    subject: RecordRef,
) -> SubmitOutcome:
    """Decide whether an occupant at our rkey is our own prior submission."""

    value = existing.get("value")
    occupant = value if isinstance(value, Mapping) else {}
    if _defining_fields(occupant) != _defining_fields(intended):
        raise SubmitError(
            "rkey_conflict",
            "a different record already occupies this submission's key; "
            "inspect your repository before retrying",
        )
    cid = existing.get("cid")
    return SubmitOutcome(
        result="already_submitted",
        community_did=community_did,
        subject=subject,
        submission_uri=str(existing.get("uri", "")),
        submission_cid=cid if isinstance(cid, str) else None,
    )


__all__ = [
    "PostLocator",
    "SubmitOutcome",
    "parse_post_reference",
    "submission_rkey",
    "submit",
]
