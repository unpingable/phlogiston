from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from community_model import ValidationError
from communitywatch_spaces_alpha import (
    DidInterpretationProfile,
    DidResolutionMethod,
    DidResolutionProvenance,
    HostBindingEpoch,
    ResolvedDidDocument,
    qualify_did_document,
    qualify_host_migration,
)
from spaces_support import timestamp

DID = "did:web:migration.invalid.test"


def _epoch(origin: str, second: int) -> HostBindingEpoch:
    document = json.dumps(
        {
            "id": DID,
            "service": [
                {
                    "id": "#atproto_pds",
                    "type": "AtprotoPersonalDataServer",
                    "serviceEndpoint": origin,
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    resolved = ResolvedDidDocument(
        expected_did=DID,
        document_bytes=document,
        document_sha256=hashlib.sha256(document).hexdigest(),
        method=DidResolutionMethod.WEB,
        method_receipt_id="sha256:" + str(second) * 64,
        provenance=DidResolutionProvenance.WEBPKI_HTTPS,
        verified_claims=frozenset({"bounded_https_fixture"}),
        observed_at=timestamp(f"2026-08-21T23:10:0{second}Z"),
    )
    binding = qualify_did_document(
        resolved.to_sa9b_input(),
        profile=DidInterpretationProfile.ACCOUNT_REPO_HOST,
        qualified_at=timestamp(f"2026-08-21T23:10:0{second}Z"),
    )
    return HostBindingEpoch.from_receipts(resolved, binding)


def test_fresh_host_rebinding_preserves_historical_source() -> None:
    old, new = _epoch("https://a.invalid.test", 1), _epoch("https://b.invalid.test", 2)
    receipt = qualify_host_migration(
        old,
        new,
        historical_artifact_refs=("sha256:" + "a" * 64,),
        evaluated_at=timestamp("2026-08-21T23:10:03Z"),
    )
    provenance = receipt.to_provenance()
    assert provenance["historicalArtifactsRemainAt"] == old.origin
    assert provenance["futureAcquisitionOrigin"] == new.origin
    assert not receipt.historical_reattribution


def test_stale_substitution_rollback_and_relabel_refuse() -> None:
    old, new = _epoch("https://a.invalid.test", 1), _epoch("https://b.invalid.test", 2)
    with pytest.raises(ValidationError):
        qualify_host_migration(
            new,
            old,
            historical_artifact_refs=(),
            evaluated_at=timestamp("2026-08-21T23:10:03Z"),
        )
    with pytest.raises(ValidationError):
        qualify_host_migration(
            old,
            replace(new, did="did:web:other.invalid.test"),
            historical_artifact_refs=(),
            evaluated_at=timestamp("2026-08-21T23:10:03Z"),
        )
    good = qualify_host_migration(
        old,
        new,
        historical_artifact_refs=(),
        evaluated_at=timestamp("2026-08-21T23:10:03Z"),
    )
    with pytest.raises(ValidationError):
        replace(good, historical_reattribution=True)


def test_same_origin_and_reused_resolution_do_not_mint_migration() -> None:
    old = _epoch("https://a.invalid.test", 1)
    with pytest.raises(ValidationError):
        qualify_host_migration(
            old,
            replace(old, qualified_at=timestamp("2026-08-21T23:10:02Z")),
            historical_artifact_refs=(),
            evaluated_at=timestamp("2026-08-21T23:10:03Z"),
        )
