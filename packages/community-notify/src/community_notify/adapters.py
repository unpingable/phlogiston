from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from collections.abc import Mapping

_MAX_PROJECTION_BYTES = 8 * 1024 * 1024
_TIMEOUT_SECONDS = 10.0
_USER_AGENT = "community-notify/0.1"


class HttpProjectionSource:
    """Reads the loopback read-only projection API. GET only."""

    def __init__(self, origin: str, timeout: float = _TIMEOUT_SECONDS) -> None:
        self.origin = origin.rstrip("/")
        self.timeout = timeout

    def get(self, path: str) -> Mapping[str, object]:
        request = urllib.request.Request(
            self.origin + path, headers={"User-Agent": _USER_AGENT}, method="GET"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read(_MAX_PROJECTION_BYTES + 1)
        except (OSError, urllib.error.URLError) as exc:
            raise OSError("projection acquisition failed") from exc
        if len(body) > _MAX_PROJECTION_BYTES:
            raise OSError("projection response exceeds the byte ceiling")
        document = json.loads(body)
        if not isinstance(document, dict):
            raise ValueError("projection response is not an object")
        return document


class WebhookError(OSError):
    """Delivery failed. The message never contains the webhook URL."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class HttpsWebhookSender:
    """POSTs one JSON object to the single configured room webhook.

    Redirects are not followed, and errors are reported without the URL,
    which for common incoming webhooks is itself a bearer capability.
    """

    def __init__(self, url: str, timeout: float = _TIMEOUT_SECONDS) -> None:
        if not url.startswith("https://"):
            raise ValueError("webhook URL must use https")
        self._url = url
        self.timeout = timeout
        self._opener = urllib.request.build_opener(_NoRedirect)

    def send(self, payload: Mapping[str, str]) -> None:
        request = urllib.request.Request(
            self._url,
            data=json.dumps(dict(payload), separators=(",", ":")).encode(),
            headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT},
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                status = response.status
                response.read(64 * 1024)
        except urllib.error.HTTPError as exc:
            raise WebhookError(f"webhook answered HTTP {exc.code}") from None
        except (OSError, urllib.error.URLError) as exc:
            raise WebhookError(f"webhook unreachable ({type(exc).__name__})") from None
        except http.client.HTTPException as exc:
            # The POST may have been accepted, but an unreadable or truncated
            # answer is not a confirmation; the caller retries.
            raise WebhookError(
                f"webhook answer unreadable ({type(exc).__name__})"
            ) from None
        if not 200 <= status < 300:
            raise WebhookError(f"webhook answered HTTP {status}")

    def __repr__(self) -> str:
        return "HttpsWebhookSender(<redacted>)"
