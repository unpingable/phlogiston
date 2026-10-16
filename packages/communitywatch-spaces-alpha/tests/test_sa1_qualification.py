from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from community_model import ValidationError
from communitywatch_spaces_alpha import (
    ALPHA_LABEL,
    BULLETIN_COMMIT,
    PROPOSAL_COMMIT,
    REFERENCE_COMMIT,
    RepoSnapshot,
    SpaceObserver,
    VerifiedSpaceClaim,
    WriterSetClaim,
    qualify_repo_state,
)
from communitywatch_spaces_alpha.crypto import (
    blake3_xof_one_chunk,
    lthash_add,
    lthash_digest,
)
from spaces_support import (
    FakeDirectSpaceSource,
    access,
    binding,
    sa1_algorithm,
    sa1_author,
    sa1_evidence,
    sa1_public_key,
    sa1_source,
    sa1_space,
    timestamp,
)


def _qualify(document: dict[str, object], name: str = "initial"):
    return qualify_repo_state(
        sa1_evidence(document, name),
        expected_space=sa1_space(document),
        expected_author_did=sa1_author(document),
        author_public_key=sa1_public_key(document),
        signature_algorithm=sa1_algorithm(document),
        source=sa1_source(document),
        verified_at=timestamp("2026-08-20T14:00:02Z"),
    )


def _flatten_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {str(key).lower() for key in value} | set().union(
            *(_flatten_keys(item) for item in value.values()), set()
        )
    if isinstance(value, list | tuple):
        return set().union(*(_flatten_keys(item) for item in value), set())
    return set()


def test_sa1_vectors_pin_current_alpha_sources(
    sa1_vectors: dict[str, object],
) -> None:
    assert sa1_vectors["format"] == "spaces-alpha-sa1-vector-v1"
    assert sa1_vectors["compatibility"] == {
        "proposalCommit": PROPOSAL_COMMIT,
        "referenceCommit": REFERENCE_COMMIT,
        "bulletinCommit": BULLETIN_COMMIT,
    }
    assert not (
        _flatten_keys(sa1_vectors)
        & {
            "private_key",
            "oauth_token",
            "space_credential",
            "delegation_token",
            "dpop_private_key",
            "authorization_header",
            "cookie",
        }
    )


def test_blake3_and_lthash_match_pinned_reference_vectors() -> None:
    assert blake3_xof_one_chunk(b"", 32).hex() == (
        "af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262"
    )
    state = lthash_add(bytes(2048), "one")
    state = lthash_add(state, "two")
    assert lthash_digest(state).hex() == (
        "ae05cb6d224379d9710c290c8529945c5b0e0fde9ead30b9699057ce701c63e7"
    )


def test_valid_commit_record_and_lthash_produce_bounded_receipt(
    sa1_vectors: dict[str, object],
) -> None:
    qualified = _qualify(sa1_vectors)

    assert qualified.commit.version == 1
    assert qualified.commit.rev == "3mtaaaabbbbbc"
    assert qualified.commit.state_hash == lthash_digest(qualified.lthash_state)
    assert len(qualified.records) == len(qualified.receipts) == 1
    record = qualified.records[0]
    receipt = qualified.receipts[0]
    assert receipt.space_identity == sa1_space(sa1_vectors)
    assert receipt.record_identity == record.identity
    assert receipt.record_identity.uri == (
        "at://did:web:spaces.test.invalid/space/invalid.test.communityspace/"
        "alpha-board/did:plc:fixtureauthor/invalid.test.spacepost/first"
    )
    assert receipt.record_cid == record.cid
    assert receipt.protocol_assumption == ALPHA_LABEL
    assert receipt.governance_authority is False
    assert receipt.verified_claims == {
        VerifiedSpaceClaim.COMMIT_STRUCTURE,
        VerifiedSpaceClaim.COMMIT_CONTEXT,
        VerifiedSpaceClaim.AUTHOR_SIGNATURE,
        VerifiedSpaceClaim.COMMIT_MAC,
        VerifiedSpaceClaim.LTHASH_REPOSITORY_STATE,
        VerifiedSpaceClaim.RECORD_CID,
        VerifiedSpaceClaim.RECORD_DAG_CBOR,
        VerifiedSpaceClaim.RECORD_PATH,
        VerifiedSpaceClaim.AUTHOR_BINDING,
        VerifiedSpaceClaim.SPACE_BINDING,
    }
    assert receipt.cryptographic_inputs["recordBlockCid"] == record.cid
    assert receipt.cryptographic_inputs["commitContextSha256"] == (
        "13c6df01d6ac1a12e0cb4f112e88999bd16068cde47d7262a0d7b32def697e00"
    )
    assert receipt.cryptographic_inputs["lthashStateSha256"] == (
        "6bb296f54e86eb8115f142af3289e726f90161f38659219d556c328d3d636274"
    )
    assert receipt.receipt_id == (
        "sha256:c7584ad43983317c1a251aef0b9ee4801669579898a84ca3528c18e8e868abf0"
    )
    # The verifier checked the signature against this supplied key.  How that
    # key was bound to the DID remains clearly caller/upstream context.
    assert receipt.unverified_context == {
        "repoHost": "https://repo-host.test.invalid",
        "authorKeyRef": "fixture:did:plc:fixtureauthor#atproto",
        "authorKeyBindingMethod": "fixture-supplied-did-document",
        "evidenceRef": "fixture:spaces-alpha:sa1",
        "writerDiscoveryRef": "fixture:listRepos:initial",
    }
    assert not (
        _flatten_keys(receipt.to_provenance())
        & {
            "private_key",
            "oauth_token",
            "space_credential",
            "delegation_token",
            "dpop_private_key",
        }
    )


def test_valid_advanced_vector_qualifies_supplied_state_transition(
    sa1_vectors: dict[str, object],
) -> None:
    qualified = _qualify(sa1_vectors, "advanced")

    assert len(qualified.records) == len(qualified.receipts) == 2
    assert qualified.commit.rev == "3mtaaaabbbbbe"
    assert all(
        VerifiedSpaceClaim.STATE_TRANSITION in receipt.verified_claims
        for receipt in qualified.receipts
    )


def test_qualified_state_cannot_be_relabelled_with_other_source_context(
    sa1_vectors: dict[str, object],
) -> None:
    qualified = _qualify(sa1_vectors)
    substituted = replace(
        sa1_source(sa1_vectors), evidence_ref="caller:unverified:replacement"
    )

    with pytest.raises(ValidationError) as caught:
        qualified.repo_verification(
            source=substituted,
            verified_at=timestamp("2026-08-20T14:00:02Z"),
        )

    assert caught.value.reason_code == "spaces_qualification_invalid"


def test_qualified_receipt_drives_existing_observation_admission_seam(
    sa1_vectors: dict[str, object], campaign: dict[str, object]
) -> None:
    checked_at = timestamp("2026-08-20T14:00:02Z")
    qualified = _qualify(sa1_vectors)
    source_context = sa1_source(sa1_vectors)
    verification = qualified.repo_verification(
        source=source_context, verified_at=checked_at
    )
    snapshot = RepoSnapshot(
        space=qualified.space,
        author_did=qualified.author_did,
        repo_host=source_context.repo_host,
        rev=qualified.commit.rev,
        commit_hash=qualified.commit.state_hash.hex(),
        acquired_at=checked_at,
        access=access(campaign),
        verification=verification,
        records=qualified.records,
        qualification_receipts=qualified.receipts,
    )
    raw_space = campaign["space"]
    assert isinstance(raw_space, dict)
    discovery = WriterSetClaim(
        space=qualified.space,
        space_host=str(raw_space["spaceHost"]),
        repo_did=qualified.author_did,
        rev=qualified.commit.rev,
        commit_hash=qualified.commit.state_hash.hex(),
        discovered_at=datetime(2026, 8, 20, 14, 0, 1, tzinfo=UTC),
    )
    direct_source = FakeDirectSpaceSource(
        claims=(discovery,),
        repo_binding=binding(campaign),
        repo_snapshot=snapshot,
    )
    observer = SpaceObserver(
        space=qualified.space,
        space_host=str(raw_space["spaceHost"]),
        source=direct_source,
        admitted_collections=frozenset({"invalid.test.spacepost"}),
        access=access(campaign),
    )

    result = observer.reconcile()[0]

    assert result.refusals == ()
    assert len(result.observations) == len(result.admissions) == 1
    provenance = result.observations[0].provenance()
    qualification = provenance["cryptographicQualification"]
    assert isinstance(qualification, list) and len(qualification) == 1
    assert qualification[0]["governanceAuthority"] is False
    assert provenance["governanceAuthority"] is False
