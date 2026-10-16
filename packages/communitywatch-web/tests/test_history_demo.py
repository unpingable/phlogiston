from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from community_model import canonical_json_bytes
from communitywatch import ObserverStore, ProjectionQuery
from communitywatch_web.history import HistoricalEvidenceDemo, sha256_file
from tests.web_support import COMMUNITY_DID, SLUG


def _demo(seeded_db: Path, refs: dict[str, object]) -> HistoricalEvidenceDemo:
    store = ObserverStore(seeded_db, community_did=COMMUNITY_DID, read_only=True)
    query = ProjectionQuery(store, slug=SLUG)
    admission = refs["removed_admission"]
    rkey = admission.uri.rsplit("/", 1)[-1]
    return HistoricalEvidenceDemo(
        query=query,
        community_did=COMMUNITY_DID,
        slug=SLUG,
        admission_rkey=rkey,
        captured_at="2026-08-14T12:00:00Z",
        expected_store_sha256=sha256_file(seeded_db),
        source_label="fixture V0 lifecycle",
    )


def test_history_document_preserves_bounded_real_claim_shape(
    seeded_db: Path, refs: dict[str, object]
) -> None:
    document = _demo(seeded_db, refs).document()
    assert document["historicalSnapshot"] is True
    assert document["storeSha256"] == sha256_file(seeded_db)
    assert document["item"]["statusAtCapture"] == "removed"
    assert document["projection"]["highWaterMatchesAtCapture"] is True
    assert "repository_currentness" in document["explicitNonClaims"]
    assert "governance_authority" in document["explicitNonClaims"]
    outcomes = {
        outcome
        for event in document["events"]
        for outcome in event["verificationOutcomes"]
    }
    assert "verified" in outcomes


def test_history_page_is_plain_language_escaped_and_explicitly_not_current(
    seeded_db: Path, refs: dict[str, object]
) -> None:
    page = _demo(seeded_db, refs).render_html()
    assert "This one actually touched ATProto." in page
    assert "Historical snapshot." in page
    assert "Serving it today does not prove" in page
    assert "Why trust the admission?" in page
    assert "off-topic noise" in page
    assert "<script>" not in page


def test_history_http_contract_is_read_only_and_calls_itself_historical(
    seeded_db: Path, refs: dict[str, object]
) -> None:
    demo = _demo(seeded_db, refs)
    root = demo.handle("GET", "/")
    api = demo.handle("GET", "/api/v0/history")
    health = demo.handle("GET", "/health")
    assert root.status == 200
    assert (
        "style-src 'sha256-" in dict(demo.security_headers)["Content-Security-Policy"]
    )
    assert json.loads(api.body)["historicalSnapshot"] is True
    assert json.loads(health.body) == {
        "currentnessClaim": False,
        "profile": "scv0-retained-v0-evidence-demo/1",
        "receiptId": demo.document()["receiptId"],
        "status": "historical_snapshot",
        "storeSha256": sha256_file(seeded_db),
    }
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = demo.handle(method, "/")
        assert response.status == 405
        assert json.loads(response.body)["message"] == "read-only demo"


def test_history_requires_read_only_exact_store_binding(
    seeded_db: Path, refs: dict[str, object], tmp_path: Path
) -> None:
    demo = _demo(seeded_db, refs)
    with pytest.raises(ValueError, match="digest mismatch"):
        replace(demo, expected_store_sha256="sha256:" + "0" * 64)

    writable_path = tmp_path / "writable.sqlite3"
    writable = ObserverStore(
        writable_path,
        community_did=COMMUNITY_DID,
        administrator_did="did:web:admin.invalid",
    )
    with pytest.raises(ValueError, match="read-only store"):
        replace(
            demo,
            query=ProjectionQuery(writable, slug=SLUG),
            expected_store_sha256=sha256_file(writable_path),
        )


def test_history_receipt_relabeling_changes_identity_and_cannot_remove_nonclaims(
    seeded_db: Path, refs: dict[str, object]
) -> None:
    document = _demo(seeded_db, refs).document()
    receipt_id = document.pop("receiptId")
    document["governanceAuthority"] = True
    relabeled = "sha256:" + hashlib.sha256(canonical_json_bytes(document)).hexdigest()
    assert relabeled != receipt_id
    assert "governance_authority" in document["explicitNonClaims"]
