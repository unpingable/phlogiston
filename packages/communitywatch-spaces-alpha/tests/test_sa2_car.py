from __future__ import annotations

from communitywatch_spaces_alpha import (
    ALPHA_LABEL,
    SA2_CAR_ADAPTER_VERSION,
    SA2_CAR_METHOD,
    SA2_REFERENCE_COMMIT,
    SA2_SOURCE_VECTOR_FORMAT,
    CarContainerClaim,
    SpaceRepoEvidence,
    extract_space_repo_evidence,
    parse_space_car,
    qualify_repo_state,
)
from spaces_support import (
    sa1_algorithm,
    sa1_author,
    sa1_evidence,
    sa1_public_key,
    sa1_source,
    sa1_space,
    sa2_car,
    timestamp,
)


def _raw_valid(document: dict[str, object]) -> dict[str, object]:
    valid = document["valid"]
    assert isinstance(valid, dict)
    raw = valid["car1"]
    assert isinstance(raw, dict)
    return raw


def _flatten_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {str(key).lower() for key in value} | set().union(
            *(_flatten_keys(item) for item in value.values()), set()
        )
    if isinstance(value, list | tuple):
        return set().union(*(_flatten_keys(item) for item in value), set())
    return set()


def _qualify(evidence: SpaceRepoEvidence, sa1_vectors: dict[str, object]):
    return qualify_repo_state(
        evidence,
        expected_space=sa1_space(sa1_vectors),
        expected_author_did=sa1_author(sa1_vectors),
        author_public_key=sa1_public_key(sa1_vectors),
        signature_algorithm=sa1_algorithm(sa1_vectors),
        source=sa1_source(sa1_vectors),
        verified_at=timestamp("2026-08-20T14:00:02Z"),
    )


def test_sa2_fixture_pins_transport_compatibility_only(
    sa2_vectors: dict[str, object],
) -> None:
    assert sa2_vectors["format"] == SA2_SOURCE_VECTOR_FORMAT
    assert sa2_vectors["compatibility"] == {
        "carVersion": 1,
        "rootOrder": ["commit", "index"],
        "cidCodec": "dag-cbor",
        "multihash": "sha2-256",
        "referenceCommit": SA2_REFERENCE_COMMIT,
        "observedPrHeadAtCampaignStart": ("f2c33aa4a72c95762c2708cf02acbfab7ddd2b5a"),
    }
    assert not (
        _flatten_keys(sa2_vectors)
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


def test_car1_parses_roots_blocks_and_container_provenance(
    sa2_vectors: dict[str, object],
) -> None:
    raw = _raw_valid(sa2_vectors)
    parsed = parse_space_car(
        sa2_car(sa2_vectors),
        source_vector_identifier=str(raw["sourceVectorIdentifier"]),
    )

    assert parsed.version == 1
    assert parsed.roots == tuple(raw["roots"])
    assert tuple(block.cid for block in parsed.blocks) == tuple(raw["blockCids"])
    assert tuple(parsed.block_index) == tuple(raw["blockCids"])
    assert parsed.raw_sha256 == raw["rawSha256"]
    assert parsed.container_claims == frozenset(CarContainerClaim)
    provenance = parsed.to_provenance()
    assert provenance["claimScope"] == "spaces_car_container_only"
    assert provenance["adapterMethod"] == SA2_CAR_METHOD
    assert provenance["adapterVersion"] == SA2_CAR_ADAPTER_VERSION
    assert provenance["semanticObservationClaims"] == ()
    assert provenance["governanceAuthority"] is False
    assert provenance["unverifiedContext"] == {
        "protocolAssumption": ALPHA_LABEL,
        "sourceVectorIdentifier": raw["sourceVectorIdentifier"],
    }
    assert not hasattr(parsed, "receipts")


def test_car1_handoff_is_exact_existing_sa1_input(
    sa1_vectors: dict[str, object], sa2_vectors: dict[str, object]
) -> None:
    raw = _raw_valid(sa2_vectors)
    extraction = extract_space_repo_evidence(
        sa2_car(sa2_vectors),
        source_vector_identifier=str(raw["sourceVectorIdentifier"]),
    )

    assert isinstance(extraction.evidence, SpaceRepoEvidence)
    assert extraction.evidence == sa1_evidence(sa1_vectors, "initial")


def test_car1_sa1_qualification_matches_preseparated_sa1_vector(
    sa1_vectors: dict[str, object], sa2_vectors: dict[str, object]
) -> None:
    raw = _raw_valid(sa2_vectors)
    extraction = extract_space_repo_evidence(
        sa2_car(sa2_vectors),
        source_vector_identifier=str(raw["sourceVectorIdentifier"]),
    )

    from_car = _qualify(extraction.evidence, sa1_vectors)
    pre_separated = _qualify(sa1_evidence(sa1_vectors, "initial"), sa1_vectors)

    assert from_car == pre_separated
    assert len(from_car.receipts) == 1
    assert from_car.receipts[0].governance_authority is False
