"""Participant-side self-submission for ATProto communities.

This distribution writes exactly one kind of record — the V0
``app.phlogiston.community.submit`` intent — into the authenticated
participant's own repository.  It holds no community credential, knows no
admission or moderation collection, and can neither grant nor imply
admission.
"""

from .submit import (
    PostLocator,
    SubmitOutcome,
    parse_post_reference,
    submission_rkey,
    submit,
)
from .transport import (
    AuthorizationFailed,
    Credential,
    HttpPds,
    Pds,
    ReadUnavailable,
    Session,
    SubmitError,
    WriteAmbiguous,
)

__all__ = [
    "AuthorizationFailed",
    "Credential",
    "HttpPds",
    "Pds",
    "PostLocator",
    "ReadUnavailable",
    "Session",
    "SubmitError",
    "SubmitOutcome",
    "WriteAmbiguous",
    "parse_post_reference",
    "submission_rkey",
    "submit",
]
__version__ = "0.1.0"
