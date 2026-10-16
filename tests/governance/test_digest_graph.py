"""Acyclic digest-order checks over the committed bootstrap artifacts.

The contract's binding order is: BUILD.md pins the contract (via the
single-use authorization block before acceptance, via the consumption
record after it); the (external, controller-held) controller-entry packet
pins that exact BUILD.md; no antecedent embeds a descendant digest. The
entry packet and receipts live outside the repository, so these tests
validate the structure of the committed antecedents: the BUILD.md
authorization state, the frozen change sets, and the contract.
"""

from __future__ import annotations

import hashlib

import validate_roadmap
import verify_frozen_changeset as vfc


def _authorization_state(repo_root):
    build = (repo_root / "BUILD.md").read_text(encoding="utf-8")
    blocks, problems = validate_roadmap.parse_build_block(build)
    consumed, consumed_problems = validate_roadmap.parse_consumed_block(build)
    assert not problems
    assert not consumed_problems
    # Pre-acceptance: one live block. Post-acceptance: one consumption
    # record. Never both, never neither.
    assert len(blocks) + len(consumed) == 1
    return blocks[0] if blocks else consumed[0]


def test_build_block_pins_exact_contract_digest(repo_root):
    state = _authorization_state(repo_root)
    contract_digest = hashlib.sha256(
        (repo_root / "docs" / "GOVERNED-LOOP.md").read_bytes()
    ).hexdigest()
    assert state["contract_sha256"] == f"sha256:{contract_digest}"


def test_build_block_embeds_no_descendant_digests(repo_root):
    state = _authorization_state(repo_root)
    digest_keys = [k for k in state if k.endswith("_sha256")]
    # Only the contract (an antecedent document) may be pinned here; a
    # packet or receipt digest in this record would close a hash cycle.
    assert digest_keys == ["contract_sha256"]


def test_change_sets_embed_ids_but_no_packet_or_receipt_digests(repo_root):
    for answer in "ABC":
        path = repo_root / "docs" / f"OQ-7-CHANGESET-{answer}.patch"
        scalars, targets, _ = vfc.parse_header(path.read_text(encoding="utf-8"))
        assert scalars["receipt_id"].startswith("OQDR-OQ-7-2026-07-27-")
        keys = list(scalars) + [
            f"target.{i}.{k}" for i, t in enumerate(targets, start=1) for k in t
        ]
        digest_keys = [k for k in keys if k.endswith("_sha256")]
        assert set(digest_keys) <= {
            f"target.{i}.{f}"
            for i in range(1, len(targets) + 1)
            for f in ("base_sha256", "result_sha256")
        }


def test_change_set_result_feeds_forward_only(repo_root):
    # The applied change set records only the stable receipt ID in
    # docs/OPEN-QUESTIONS.md; no receipt digest appears in the register.
    register = (repo_root / "docs" / "OPEN-QUESTIONS.md").read_text(encoding="utf-8")
    assert "OQDR-OQ-7-2026-07-27-A-02" in register
    assert "receipt_sha256" not in register
