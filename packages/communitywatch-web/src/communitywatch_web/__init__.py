"""Read-only web surfaces for ATProto community observer evidence.

Detect-only: this package serves GET/HEAD over the committed observer SQLite
projection through stdlib HTTP.  It carries no writer, credential, signing,
transport-client, or archive dependency. The historical demo is explicitly
separate from the canonical current AppView.
"""

from .app import (
    HTML_CONTENT_TYPE,
    JSON_CONTENT_TYPE,
    SECURITY_HEADERS,
    Response,
    WebApp,
)
from .cli import main, scrub_environment
from .history import HISTORY_DEMO_VERSION, HistoricalEvidenceDemo, sha256_file
from .server import make_server

__all__ = [
    "HTML_CONTENT_TYPE",
    "HISTORY_DEMO_VERSION",
    "JSON_CONTENT_TYPE",
    "SECURITY_HEADERS",
    "Response",
    "HistoricalEvidenceDemo",
    "WebApp",
    "main",
    "make_server",
    "scrub_environment",
    "sha256_file",
]
__version__ = "0.1.0"
