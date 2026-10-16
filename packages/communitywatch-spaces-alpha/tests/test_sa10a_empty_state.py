from __future__ import annotations

import hashlib
from dataclasses import replace

from community_model import cid_for_dag_cbor, encode_dag_cbor
from communitywatch_spaces_alpha import (
    ALPHA_LABEL,
    PERMISSIONED_REPO_PROOF_KIND,
    QualificationSourceContext,
    RepoOperation,
    RepoTransition,
    SpaceIdentity,
    SpaceRecordBlock,
    SpaceRepoEvidence,
    encode_commit_context,
    qualify_empty_repo_state,
    qualify_repo_transition,
    reconcile_qualified_states,
)
from communitywatch_spaces_alpha.crypto import (
    _SECP_GENERATOR,
    _SECP_ORDER,
    _point_multiply,
    commit_mac,
    lthash_add,
    lthash_digest,
)
from spaces_support import timestamp

SPACE = SpaceIdentity(
    "did:plc:sa10aauthority", "invalid.test.communityspace", "empty-life"
)
AUTHOR = "did:plc:sa10aauthor"
SCALAR = 0x123456789ABCDEF
SOURCE = QualificationSourceContext(
    "https://repo.empty.invalid",
    f"{AUTHOR}#atproto",
    "fixture-public-key",
    "fixture:sa10a",
)


def _sign(message: bytes) -> bytes:
    z = int.from_bytes(hashlib.sha256(message).digest(), "big")
    k = (
        int.from_bytes(hashlib.sha256(b"sa10a-k" + message).digest(), "big")
        % (_SECP_ORDER - 1)
        + 1
    )
    point = _point_multiply(k, _SECP_GENERATOR)
    assert point is not None
    r = point[0] % _SECP_ORDER
    s = (pow(k, -1, _SECP_ORDER) * (z + r * SCALAR)) % _SECP_ORDER
    s = min(s, _SECP_ORDER - s)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def _public() -> bytes:
    point = _point_multiply(SCALAR, _SECP_GENERATOR)
    assert point is not None
    return bytes([2 | (point[1] & 1)]) + point[0].to_bytes(32, "big")


def _evidence(
    rev: str,
    index: dict[str, str],
    blocks: tuple[SpaceRecordBlock, ...],
    transition=None,
) -> SpaceRepoEvidence:
    state = bytes(2048)
    for path, cid in index.items():
        state = lthash_add(state, f"{path}/{cid}")
    ikm = hashlib.sha256(f"sa10a:{rev}".encode()).digest()
    context = encode_commit_context(SPACE, AUTHOR, rev, ikm)
    digest = lthash_digest(state)
    commit = encode_dag_cbor(
        {
            "ver": 1,
            "hash": digest,
            "mac": commit_mac(ikm, context, digest),
            "ikm": ikm,
            "sig": _sign(context),
            "rev": rev,
        }
    )
    index_bytes = encode_dag_cbor({path: {"$link": cid} for path, cid in index.items()})
    return SpaceRepoEvidence(
        f"sa10a:{rev}",
        PERMISSIONED_REPO_PROOF_KIND,
        ALPHA_LABEL,
        commit,
        index_bytes,
        blocks,
        transition,
    )


def test_empty_state_has_state_receipt_not_fake_record_receipt_and_add_transition() -> (
    None
):
    empty_evidence = _evidence("3mtzzzzaaaaaa", {}, ())
    empty = qualify_empty_repo_state(
        empty_evidence,
        expected_space=SPACE,
        expected_author_did=AUTHOR,
        author_public_key=_public(),
        signature_algorithm="ES256K",
        source=SOURCE,
        verified_at=timestamp("2026-08-21T22:00:00Z"),
    )
    assert empty.records == () and empty.receipts == ()
    assert "record_existence" in empty.empty_receipt.explicit_non_claims
    record_bytes = encode_dag_cbor({"$type": "invalid.test.spacepost", "text": "first"})
    cid = cid_for_dag_cbor(record_bytes)
    path = "invalid.test.spacepost/first"
    operation = RepoOperation(
        "3mtzzzzaaaaab", "invalid.test.spacepost", "first", cid, None
    )
    transition = RepoTransition(empty.commit.rev, empty.lthash_state, {}, (operation,))
    target = _evidence(
        "3mtzzzzaaaaab",
        {path: cid},
        (SpaceRecordBlock("invalid.test.spacepost", "first", cid, record_bytes),),
        transition,
    )
    qualified = qualify_repo_transition(
        empty,
        target,
        expected_space=SPACE,
        expected_author_did=AUTHOR,
        author_public_key=_public(),
        signature_algorithm="ES256K",
        source=SOURCE,
        verified_at=timestamp("2026-08-21T22:00:01Z"),
    )
    assert qualified.receipt.source_state.record_count == 0
    assert qualified.receipt.target_state.record_count == 1
    assert qualified.receipt.effects[0].kind.value == "add"
    assert (
        not qualified.receipt.complete_history and not qualified.receipt.authorization
    )
    reconciled = reconcile_qualified_states(
        empty,
        qualified.target,
        transition=qualified,
        reconciled_at=timestamp("2026-08-21T22:00:02Z"),
    )
    assert reconciled.disposition.value == "qualified_transition"


def test_empty_state_hostile_nonempty_and_receipt_relabel_refuse() -> None:
    record_bytes = encode_dag_cbor(
        {"$type": "invalid.test.spacepost", "text": "not empty"}
    )
    cid = cid_for_dag_cbor(record_bytes)
    evidence = _evidence(
        "3mtzzzzaaaaac",
        {"invalid.test.spacepost/x": cid},
        (SpaceRecordBlock("invalid.test.spacepost", "x", cid, record_bytes),),
    )
    import pytest

    from community_model import ValidationError

    with pytest.raises(ValidationError):
        qualify_empty_repo_state(
            evidence,
            expected_space=SPACE,
            expected_author_did=AUTHOR,
            author_public_key=_public(),
            signature_algorithm="ES256K",
            source=SOURCE,
            verified_at=timestamp("2026-08-21T22:00:02Z"),
        )
    empty = qualify_empty_repo_state(
        _evidence("3mtzzzzaaaaad", {}, ()),
        expected_space=SPACE,
        expected_author_did=AUTHOR,
        author_public_key=_public(),
        signature_algorithm="ES256K",
        source=SOURCE,
        verified_at=timestamp("2026-08-21T22:00:03Z"),
    )
    with pytest.raises(ValidationError):
        replace(empty.empty_receipt, explicit_non_claims=frozenset())
