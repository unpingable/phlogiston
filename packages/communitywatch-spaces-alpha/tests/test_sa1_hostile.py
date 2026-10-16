from __future__ import annotations

import base64
from dataclasses import replace

import pytest

from community_model import ValidationError, decode_dag_cbor, encode_dag_cbor
from communitywatch_spaces_alpha import (
    RepoTransition,
    SpaceObserver,
    SpaceRepoEvidence,
    VerificationMode,
    qualify_repo_state,
)
from spaces_support import (
    FakeDirectSpaceSource,
    access,
    binding,
    claim,
    sa1_algorithm,
    sa1_author,
    sa1_evidence,
    sa1_public_key,
    sa1_source,
    sa1_space,
    snapshot,
    timestamp,
)


def _raw_hostile(document: dict[str, object], name: str) -> object:
    hostile = document["hostile"]
    assert isinstance(hostile, dict)
    return hostile[name]


def _qualify(
    document: dict[str, object],
    evidence: SpaceRepoEvidence,
    *,
    space=None,
    author: str | None = None,
    public_key: bytes | None = None,
) -> None:
    qualify_repo_state(
        evidence,
        expected_space=space or sa1_space(document),
        expected_author_did=author or sa1_author(document),
        author_public_key=public_key or sa1_public_key(document),
        signature_algorithm=sa1_algorithm(document),
        source=sa1_source(document),
        verified_at=timestamp("2026-08-20T14:00:02Z"),
    )


def _assert_refusal(reason: str, operation) -> None:
    with pytest.raises(ValidationError) as caught:
        operation()
    assert caught.value.reason_code == reason


def test_c1_cid_substitution_same_metadata_altered_bytes_is_refused(
    sa1_vectors: dict[str, object],
) -> None:
    evidence = sa1_evidence(sa1_vectors, "initial")
    altered = base64.b64decode(
        str(_raw_hostile(sa1_vectors, "c1AlteredRecordBytesB64")), validate=True
    )
    block = replace(evidence.record_blocks[0], record_bytes=altered)

    _assert_refusal(
        "spaces_record_cid_invalid",
        lambda: _qualify(sa1_vectors, replace(evidence, record_blocks=(block,))),
    )


def test_c2_cid_valid_but_malformed_dag_cbor_is_refused(
    sa1_vectors: dict[str, object],
) -> None:
    evidence = sa1_evidence(sa1_vectors, "c2MalformedDagCbor", hostile=True)

    _assert_refusal(
        "spaces_record_content_invalid", lambda: _qualify(sa1_vectors, evidence)
    )


def test_c3_index_change_without_lthash_accumulator_change_is_refused(
    sa1_vectors: dict[str, object],
) -> None:
    evidence = sa1_evidence(sa1_vectors, "initial")
    index = decode_dag_cbor(evidence.index_bytes)
    extra = _raw_hostile(sa1_vectors, "c3AdditionalIndexEntry")
    assert isinstance(index, dict) and isinstance(extra, dict)
    index[str(extra["path"])] = {"$link": str(extra["cid"])}

    _assert_refusal(
        "spaces_lthash_invalid",
        lambda: _qualify(
            sa1_vectors, replace(evidence, index_bytes=encode_dag_cbor(index))
        ),
    )


def test_c4_valid_commit_does_not_bind_to_another_space(
    sa1_vectors: dict[str, object],
) -> None:
    _assert_refusal(
        "spaces_mac_invalid",
        lambda: _qualify(
            sa1_vectors,
            sa1_evidence(sa1_vectors, "initial"),
            space=sa1_space(sa1_vectors, hostile=True),
        ),
    )


def test_c5_valid_commit_does_not_bind_to_another_author(
    sa1_vectors: dict[str, object],
) -> None:
    wrong_author = str(_raw_hostile(sa1_vectors, "c5WrongAuthorDid"))

    _assert_refusal(
        "spaces_mac_invalid",
        lambda: _qualify(
            sa1_vectors,
            sa1_evidence(sa1_vectors, "initial"),
            author=wrong_author,
        ),
    )


def test_c6_supplied_parent_state_mismatch_is_refused(
    sa1_vectors: dict[str, object],
) -> None:
    evidence = sa1_evidence(sa1_vectors, "advanced")
    transition = evidence.transition
    assert isinstance(transition, RepoTransition)
    wrong_state = base64.b64decode(
        str(_raw_hostile(sa1_vectors, "c6PriorStateB64")), validate=True
    )

    _assert_refusal(
        "spaces_transition_invalid",
        lambda: _qualify(
            sa1_vectors,
            replace(
                evidence,
                transition=replace(transition, prior_state=wrong_state),
            ),
        ),
    )


def test_c7_unsupported_alpha_commit_version_is_explicitly_refused(
    sa1_vectors: dict[str, object],
) -> None:
    evidence = sa1_evidence(sa1_vectors, "initial")
    future_commit = base64.b64decode(
        str(_raw_hostile(sa1_vectors, "c7UnsupportedCommitB64")), validate=True
    )

    _assert_refusal(
        "spaces_alpha_compatibility_failure",
        lambda: _qualify(sa1_vectors, replace(evidence, commit_bytes=future_commit)),
    )


def test_c8_public_car_mst_material_cannot_upgrade_to_spaces_observation(
    sa1_vectors: dict[str, object],
) -> None:
    evidence = sa1_evidence(sa1_vectors, "c8PublicProofOnly", hostile=True)

    _assert_refusal(
        "spaces_public_proof_refused", lambda: _qualify(sa1_vectors, evidence)
    )


def test_supplied_author_key_substitution_is_refused_not_relabelled(
    sa1_vectors: dict[str, object],
) -> None:
    wrong_key = bytes([2]) + bytes(32)

    _assert_refusal(
        "spaces_signature_invalid",
        lambda: _qualify(
            sa1_vectors,
            sa1_evidence(sa1_vectors, "initial"),
            public_key=wrong_key,
        ),
    )


def test_caller_claim_labels_without_receipts_cannot_become_verified(
    sa1_vectors: dict[str, object], campaign: dict[str, object]
) -> None:
    fixture_snapshot = snapshot(campaign, "initial")
    labelled_verification = replace(
        fixture_snapshot.verification,
        mode=VerificationMode.VERIFIED,
    )
    labelled_snapshot = replace(
        fixture_snapshot,
        verification=labelled_verification,
    )
    source = FakeDirectSpaceSource(
        claims=(claim(campaign, "initial"),),
        repo_binding=binding(campaign),
        repo_snapshot=labelled_snapshot,
    )
    raw_space = campaign["space"]
    assert isinstance(raw_space, dict)
    observer = SpaceObserver(
        space=sa1_space(sa1_vectors),
        space_host=str(raw_space["spaceHost"]),
        source=source,
        admitted_collections=frozenset({"invalid.test.spacepost"}),
        access=access(campaign),
    )

    result = observer.reconcile()[0]

    assert result.observations == result.admissions == ()
    assert result.refusals == ("cryptographic_qualification_missing",)
