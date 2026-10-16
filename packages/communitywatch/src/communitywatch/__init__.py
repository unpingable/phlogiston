"""Detect-only observer contracts for portable ATProto communities."""

from .config import ConfigError, ObserverConfig, load_config, parse_config
from .discussion import (
    DiscussionDetail,
    DiscussionPage,
    DiscussionQuery,
    ModerationQueue,
    ParticipantActivity,
    ProjectionSnapshot,
    ReplyCandidates,
)
from .fakes import FakeEventSource, FakeSubjectResolver
from .jetstream import JetstreamEventSource
from .ports import CommunityQuery, EventSource, SubjectResolver
from .query import (
    EntryDetail,
    ProjectionQuery,
    ProjectionStatus,
    ProjectionUnavailableError,
    SourceFreshness,
    UnknownCommunityError,
    UnknownEntryError,
)
from .render import (
    STYLE_SHA256,
    describe_reason,
    describe_state,
    render_audit_page,
    render_community_page,
    render_error_page,
    render_item_page,
)
from .runner import ObserverRunner
from .storage import IngestResult, ObserverStore, ReadOnlyStoreError
from .syncclient import DidResolver, PdsClient, UrllibHttpGetter
from .verifying import VerifiedSubjectResolver, VerifyingEventSource

__all__ = [
    "STYLE_SHA256",
    "CommunityQuery",
    "ConfigError",
    "DidResolver",
    "DiscussionDetail",
    "DiscussionPage",
    "DiscussionQuery",
    "EntryDetail",
    "EventSource",
    "FakeEventSource",
    "FakeSubjectResolver",
    "IngestResult",
    "JetstreamEventSource",
    "ObserverConfig",
    "ObserverRunner",
    "ObserverStore",
    "ModerationQueue",
    "ParticipantActivity",
    "ProjectionSnapshot",
    "ReplyCandidates",
    "PdsClient",
    "ProjectionQuery",
    "ProjectionStatus",
    "ProjectionUnavailableError",
    "ReadOnlyStoreError",
    "SourceFreshness",
    "SubjectResolver",
    "UnknownCommunityError",
    "UnknownEntryError",
    "UrllibHttpGetter",
    "VerifiedSubjectResolver",
    "VerifyingEventSource",
    "describe_reason",
    "describe_state",
    "load_config",
    "parse_config",
    "render_audit_page",
    "render_community_page",
    "render_error_page",
    "render_item_page",
]
__version__ = "0.1.0"
