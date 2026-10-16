"""Read-only historical evidence demo over one byte-pinned observer store.

This is deliberately not the canonical current AppView. It exposes a retained
non-production V0 lifecycle as captured history and preserves every underlying
verification outcome. A real observation may be old; serving it later cannot
make it current.
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from html import escape
from pathlib import Path

from community_model import canonical_json_bytes
from community_model.immutable import deep_thaw
from communitywatch import ProjectionQuery

from .app import HTML_CONTENT_TYPE, JSON_CONTENT_TYPE, Response

HISTORY_DEMO_VERSION = "scv0-retained-v0-evidence-demo/1"
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}")
_CLAIMS = (
    "observer_store_digest_matches",
    "retained_projection_is_complete_and_compatible",
    "exact_submission_admission_source_and_removal_references_retained",
    "per_event_verification_outcomes_preserved",
)
_NON_CLAIMS = (
    "live_observation",
    "repository_currentness",
    "complete_history",
    "community_legitimacy",
    "membership",
    "governance_authority",
    "public_verification_of_operator_authorization",
    "production_readiness",
)


def sha256_file(path: Path) -> str:
    """Hash one file without reading it into an unbounded buffer."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


@dataclass(frozen=True, slots=True)
class HistoricalEvidenceDemo:
    """Serve one exact removed lifecycle as historical, never current, state."""

    query: ProjectionQuery
    community_did: str
    slug: str
    admission_rkey: str
    captured_at: str
    expected_store_sha256: str
    source_label: str

    def __post_init__(self) -> None:
        if _SHA256_RE.fullmatch(self.expected_store_sha256) is None:
            raise ValueError("historical store digest must be sha256")
        if not self.query.store.read_only:
            raise ValueError("historical evidence demo requires a read-only store")
        if self.store_sha256 != self.expected_store_sha256:
            raise ValueError("historical observer store digest mismatch")
        if not self.admission_rkey or "/" in self.admission_rkey:
            raise ValueError("historical admission key must be one path segment")
        if not self.captured_at.endswith("Z"):
            raise ValueError("historical capture time must be UTC wire time")
        if not self.source_label:
            raise ValueError("historical source label is required")

    @property
    def store_sha256(self) -> str:
        """Digest the exact database file this query opens read-only."""

        return sha256_file(self.query.store.path)

    @property
    def security_headers(self) -> tuple[tuple[str, str], ...]:
        """Admit only this app's exact inline stylesheet; never scripts."""

        return HISTORY_SECURITY_HEADERS

    def document(self) -> dict[str, object]:
        """Return the canonical historical receipt document."""

        detail = self.query.entry_detail(self.community_did, self.admission_rkey)
        audit = self.query.list_audit(self.community_did, 100, None)
        state = self.query.projection_state()
        if state.status != "complete" or not state.compatible:
            raise ValueError("retained projection is not complete and compatible")
        entry = deep_thaw(detail.entry)
        events = tuple(deep_thaw(item) for item in audit.items)
        receipt: dict[str, object] = {
            "profile": HISTORY_DEMO_VERSION,
            "historicalSnapshot": True,
            "capturedAt": self.captured_at,
            "sourceLabel": self.source_label,
            "storeSha256": self.store_sha256,
            "community": deep_thaw(self.query.community_identity(self.community_did)),
            "projection": {
                "generation": state.generation,
                "status": state.status,
                "compatible": state.compatible,
                "highWaterMatchesAtCapture": state.high_water_matches,
                "lastIngestAt": state.last_ingest_at,
                "lastResolveAt": state.last_resolve_at,
            },
            "item": {"statusAtCapture": detail.status, **entry},
            "events": events,
            "verifiedClaims": _CLAIMS,
            "explicitNonClaims": _NON_CLAIMS,
        }
        receipt["receiptId"] = (
            "sha256:" + hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
        )
        return receipt

    def handle(self, method: str, target: str) -> Response:
        """Serve GET/HEAD/OPTIONS only; every document is immutable history."""

        method = method.upper()
        if method == "OPTIONS":
            return Response(
                204,
                JSON_CONTENT_TYPE,
                b"",
                (
                    ("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS"),
                    ("Access-Control-Max-Age", "86400"),
                ),
            )
        if method not in {"GET", "HEAD"}:
            return self._json(
                405,
                {"error": "method_not_allowed", "message": "read-only demo"},
                (("Allow", "GET, HEAD, OPTIONS"),),
            )
        path = target.partition("?")[0]
        if path == "/":
            return Response(200, HTML_CONTENT_TYPE, self.render_html().encode())
        if path == "/api/v0/history":
            return self._json(200, self.document())
        if path == "/health":
            document = self.document()
            return self._json(
                200,
                {
                    "status": "historical_snapshot",
                    "profile": HISTORY_DEMO_VERSION,
                    "receiptId": document["receiptId"],
                    "storeSha256": self.store_sha256,
                    "currentnessClaim": False,
                },
            )
        return self._json(404, {"error": "not_found", "message": "unknown route"})

    def _json(
        self,
        status: int,
        document: dict[str, object],
        extra: tuple[tuple[str, str], ...] = (),
    ) -> Response:
        return Response(
            status, JSON_CONTENT_TYPE, canonical_json_bytes(document), extra
        )

    def render_html(self) -> str:
        """Render a human explanation over the exact retained receipt."""

        document = self.document()
        item = document["item"]
        assert isinstance(item, dict)
        post = item.get("post")
        post = post if isinstance(post, dict) else {}
        subject = item.get("subject")
        subject = subject if isinstance(subject, dict) else {}
        admission = item.get("admission")
        admission = admission if isinstance(admission, dict) else {}
        events = document["events"]
        assert isinstance(events, tuple)
        accepted = [
            event
            for event in events
            if isinstance(event, dict)
            and event.get("outcome") == "valid"
            and "verified" in event.get("verificationOutcomes", ())
        ]
        discovery_only = [
            event
            for event in events
            if isinstance(event, dict) and event.get("outcome") != "valid"
        ]
        timeline = "".join(self._event_card(event) for event in reversed(accepted))
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>A real ATProto community lifecycle — captured evidence</title>
<style>{_STYLE}</style></head><body><main class="shell">
<p class="eyebrow">Captured V0 evidence · not a current feed</p>
<h1>This one actually touched ATProto.</h1>
<p class="lead">A disposable account submitted a real author-owned post, the
community actor admitted it, and later removed it from the community view.
The PDS signed those repository records; the observer independently verified
the repository proofs before projecting them.</p>
<div class="warning"><strong>Historical snapshot.</strong> Captured
{escape(self.captured_at)}. Serving it today does not prove that no newer
repository state exists.</div>
<section class="source"><span>Author-owned source at capture</span>
<blockquote>{escape(str(post.get("text", "")))}</blockquote>
<code>{escape(str(subject.get("uri", "")))}</code><br>
<code>{escape(str(subject.get("cid", "")))}</code></section>
<section><p class="eyebrow">What happened</p><h2>The retained lifecycle</h2>
<div class="timeline">{timeline}</div></section>
<section class="why"><p class="eyebrow">Why trust the admission?</p>
<h2>A bounded answer, not a magic badge.</h2>
<p>The admitted occurrence is the exact URI/CID pair below. The accepted
admission event carries a verified repository-proof outcome for the community
actor. That establishes the observed signed record—not community legitimacy,
membership, or a universal right to moderate.</p>
<code>{escape(str(admission.get("uri", "")))}</code><br>
<code>{escape(str(admission.get("cid", "")))}</code>
<p class="small">The observer also retained {len(discovery_only)} transport-only
delivery result(s) that did not qualify as authority. They remain visible in
the JSON instead of being rewritten as success.</p></section>
<section class="split"><div><h3>What is real here</h3><ul>
<li>public non-production ATProto records</li><li>PDS-signed repository commits</li>
<li>independent DID/signature/MST proof verification</li><li>the retained removal</li>
</ul></div><div><h3>What is not claimed</h3><ul>
<li>current repository state</li><li>complete history</li><li>membership or standing</li>
<li>governance legitimacy</li><li>production readiness</li></ul></div></section>
<p class="links"><a href="/api/v0/history">Inspect the exact JSON receipt</a>
<a href="/health">Check the deliberately historical health status</a></p>
<footer>Store <code>{escape(self.store_sha256)}</code><br>
Receipt <code>{escape(str(document["receiptId"]))}</code></footer>
</main></body></html>"""

    @staticmethod
    def _event_card(event: dict[str, object]) -> str:
        labels = {
            "submission": (
                "Suggested",
                "The author submitted an exact post URI and CID.",
            ),
            "admission": (
                "Added",
                "The community actor signed an admission for that occurrence.",
            ),
            "subject_observation": (
                "Source checked",
                "The observer verified the exact source record.",
            ),
            "removal": (
                "Removed",
                "The community stopped projecting it; the source was not deleted.",
            ),
        }
        kind = str(event.get("kind", "observation"))
        title, description = labels.get(
            kind, (kind.replace("_", " ").title(), "Retained evidence event.")
        )
        when = event.get("createdAt") or event.get("firstReceivedAt") or ""
        return (
            '<article><span class="pill">verified</span>'
            f"<h3>{escape(title)}</h3><p>{escape(description)}</p>"
            f"<time>{escape(str(when))}</time></article>"
        )


_STYLE = """
:root{--ink:#19251f;--muted:#657169;--paper:#f7f3e8;--card:#fffdf8;--green:#1d5b43;--line:#d8d2c4;--gold:#e9ad3f}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 8% 0,#f0c76a44,transparent 32rem),var(--paper);color:var(--ink);font:16px/1.6 system-ui,sans-serif}.shell{width:min(920px,calc(100% - 32px));margin:auto;padding:70px 0}.eyebrow{color:var(--green);font-size:.78rem;font-weight:850;letter-spacing:.12em;text-transform:uppercase}h1,h2{font-family:Georgia,serif;letter-spacing:-.04em}h1{max-width:13ch;margin:.2rem 0 1.5rem;font-size:clamp(3rem,8vw,5.8rem);line-height:.95}h2{font-size:2.3rem}.lead{max-width:65ch;font-size:1.2rem;color:#3d4c44}.warning,.source,.why,.split,article{border:1px solid var(--line);border-radius:20px;background:var(--card);box-shadow:0 12px 35px #26372e0d}.warning{margin:30px 0;padding:18px 22px;border-left:5px solid var(--gold)}section{margin-top:65px}.source,.why{padding:28px}.source span{color:var(--muted);font-size:.85rem}.source blockquote{margin:18px 0;font:1.5rem/1.4 Georgia,serif}.timeline{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}article{padding:20px}article h3{margin:.8rem 0 .4rem}article p{color:var(--muted)}time,code{overflow-wrap:anywhere;font:12px ui-monospace,monospace;color:var(--muted)}.pill{border-radius:99px;padding:4px 8px;background:#dcebdc;color:var(--green);font-size:11px;font-weight:800}.split{display:grid;grid-template-columns:1fr 1fr;padding:16px 28px;gap:28px}.small{color:var(--muted);font-size:.9rem}.links{display:flex;gap:20px;flex-wrap:wrap;margin-top:40px}.links a{color:var(--green);font-weight:750}footer{margin-top:50px;padding-top:20px;border-top:1px solid var(--line);color:var(--muted)}@media(max-width:720px){.timeline,.split{grid-template-columns:1fr}.shell{padding-top:40px}}
"""

_STYLE_SHA256 = "sha256-" + base64.b64encode(
    hashlib.sha256(_STYLE.encode()).digest()
).decode("ascii")
HISTORY_SECURITY_HEADERS = (
    (
        "Content-Security-Policy",
        "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
        f"style-src '{_STYLE_SHA256}'",
    ),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
)


__all__ = ["HISTORY_DEMO_VERSION", "HistoricalEvidenceDemo", "sha256_file"]
