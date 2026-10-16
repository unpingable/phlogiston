"""Authority-writer contracts isolated from observer infrastructure."""

from .authority_server import (
    AuthorityRequest,
    AuthorityRequestBoundary,
    CommunityAuthorityHandler,
    PeerIdentity,
    UnixAuthorityServer,
    UnixPeerRolePolicy,
)
from .config import ConfigError, DaemonConfig, load_config, parse_config
from .journal import (
    JournalConflictError,
    JournalEntry,
    SQLiteOperationJournal,
)
from .operations import (
    DaemonPorts,
    LocalAdminAuthorizer,
    OperationOutcome,
    admit,
    remove,
)
from .ports import (
    AdminAuthorizer,
    AuthorityLedgerReader,
    AuthorityWriter,
    CredentialProvider,
    RecordReader,
)
from .reply_operations import (
    ReplyAuthorityLedgerReader,
    admit_reply,
    create_reply_policy,
    moderate_reply,
)

__all__ = [
    "AdminAuthorizer",
    "AuthorityLedgerReader",
    "AuthorityRequest",
    "AuthorityRequestBoundary",
    "AuthorityWriter",
    "CommunityAuthorityHandler",
    "ConfigError",
    "CredentialProvider",
    "DaemonConfig",
    "DaemonPorts",
    "JournalConflictError",
    "JournalEntry",
    "LocalAdminAuthorizer",
    "OperationOutcome",
    "PeerIdentity",
    "RecordReader",
    "ReplyAuthorityLedgerReader",
    "SQLiteOperationJournal",
    "UnixAuthorityServer",
    "UnixPeerRolePolicy",
    "admit",
    "admit_reply",
    "create_reply_policy",
    "load_config",
    "moderate_reply",
    "parse_config",
    "remove",
]
__version__ = "0.1.0"
