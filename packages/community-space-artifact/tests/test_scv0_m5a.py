from __future__ import annotations

import hashlib
from pathlib import Path

from community_space_artifact import (
    COMPILER_VERSION,
    DisclosureMode,
    ProjectionArtifactCompiler,
    ProjectionDisclosureInput,
)
from community_space_projection import LifecycleState


def _input(m5a: dict[str, object], name: str, *, presentation: bool = False):
    state = m5a[name]
    return ProjectionDisclosureInput(
        projection=state,
        declared_community_identity_id=m5a["community"].identity_id,
        declared_lifecycle_state=state.state,
        presentation=m5a["presentation"] if presentation else None,
    )


def test_m5a_p1_added_ordinary_discloses_only_bounded_fields(
    m5a: dict[str, object],
) -> None:
    result = ProjectionArtifactCompiler(m5a["community"]).compile(
        (_input(m5a, "added", presentation=True),), m5a["ordinary"]
    )
    assert result.artifact is not None
    artifact = result.artifact
    assert artifact.disclosure_mode is DisclosureMode.ORDINARY
    assert artifact.compiler_version == COMPILER_VERSION
    assert (
        artifact.disclosure_policy_reference_id == m5a["ordinary"].policy_reference_id
    )
    assert artifact.validate_integrity() == artifact.artifact_id
    assert len(artifact.entries) == 1
    entry = artifact.entries[0]
    assert entry.lifecycle_state is LifecycleState.ADDED
    assert entry.presentation == m5a["presentation"]
    assert entry.technical_receipts is None
    assert entry.available_lifecycle_links == ()
    assert result.non_published_candidates == ()


def test_m5a_p2_technical_audit_discloses_receipt_references(
    m5a: dict[str, object],
) -> None:
    result = ProjectionArtifactCompiler(m5a["community"]).compile(
        (_input(m5a, "added", presentation=True),), m5a["audit"]
    )
    assert result.artifact is not None
    entry = result.artifact.entries[0]
    assert entry.technical_receipts is not None
    assert entry.technical_receipts.admission_id == m5a["added"].admission.admission_id
    assert entry.available_lifecycle_links == (
        m5a["added"].prior_state_id,
        m5a["added"].state_id,
    )


def test_m5a_p3_suggested_is_nonpublished(m5a: dict[str, object]) -> None:
    result = ProjectionArtifactCompiler(m5a["community"]).compile(
        (_input(m5a, "suggested"),), m5a["ordinary"]
    )
    assert result.artifact is None
    assert len(result.non_published_candidates) == 1
    assert result.non_published_candidates[0].reason == "suggested_not_reader_published"


def test_m5a_p4_changed_source_is_lifecycle_only(m5a: dict[str, object]) -> None:
    result = ProjectionArtifactCompiler(m5a["community"]).compile(
        (_input(m5a, "changed"),), m5a["ordinary"]
    )
    assert result.artifact is not None
    entry = result.artifact.entries[0]
    assert entry.lifecycle_state is LifecycleState.CHANGED_AT_SOURCE
    assert entry.presentation is None
    assert entry.admitted_source_cid == m5a["post"].record.cid
    assert (
        entry.source_observation_id == m5a["changed"].source_observation.observation_id
    )


def test_m5a_p5_removed_is_nonrepublishing_tombstone(
    m5a: dict[str, object],
) -> None:
    result = ProjectionArtifactCompiler(m5a["community"]).compile(
        (_input(m5a, "removed"),), m5a["audit"]
    )
    assert result.artifact is not None
    entry = result.artifact.entries[0]
    assert entry.lifecycle_state is LifecycleState.REMOVED
    assert entry.presentation is None
    assert entry.removal_id == m5a["removed"].removal.removal_id
    assert entry.admission_id == m5a["removed"].admission.admission_id
    assert entry.available_lifecycle_links[-1] == m5a["removed"].state_id


def test_author_withdrawal_suppresses_presentation_but_retains_audit_receipt(
    m5a: dict[str, object],
) -> None:
    compiler = ProjectionArtifactCompiler(m5a["community"])
    ordinary = compiler.compile((_input(m5a, "withdrawn"),), m5a["ordinary"]).artifact
    audit = compiler.compile((_input(m5a, "withdrawn"),), m5a["audit"]).artifact
    assert ordinary is not None and audit is not None
    ordinary_entry = ordinary.entries[0]
    audit_entry = audit.entries[0]
    assert ordinary_entry.lifecycle_state is LifecycleState.AUTHOR_WITHDRAWN
    assert ordinary_entry.presentation is None
    assert ordinary_entry.withdrawal_id == m5a["withdrawal"].withdrawal_id
    assert ordinary_entry.technical_receipts is None
    assert audit_entry.technical_receipts is not None
    assert (
        audit_entry.technical_receipts.withdrawal_id == m5a["withdrawal"].withdrawal_id
    )


def test_removal_after_withdrawal_retains_both_historical_occurrences(
    m5a: dict[str, object],
) -> None:
    artifact = (
        ProjectionArtifactCompiler(m5a["community"])
        .compile((_input(m5a, "removed_after_withdrawal"),), m5a["audit"])
        .artifact
    )
    assert artifact is not None
    entry = artifact.entries[0]
    assert entry.lifecycle_state is LifecycleState.REMOVED
    assert entry.withdrawal_id == m5a["withdrawal"].withdrawal_id
    assert entry.removal_id == m5a["removed_after_withdrawal"].removal.removal_id
    assert entry.presentation is None


def test_compilation_is_deterministic_and_fixture_is_nonsecret(
    m5a: dict[str, object],
) -> None:
    compiler = ProjectionArtifactCompiler(m5a["community"])
    first = compiler.compile(
        (_input(m5a, "added", presentation=True),), m5a["ordinary"]
    )
    second = compiler.compile(
        (_input(m5a, "added", presentation=True),), m5a["ordinary"]
    )
    assert first.artifact is not None and second.artifact is not None
    assert first.artifact.artifact_id == second.artifact.artifact_id
    vector = m5a["vector"]
    assert vector["secretMaterialPresent"] is False
    fixture = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "space-community"
        / "scv0-m5a.json"
    )
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == (
        "c4ac94b267b238bd8df657d4f909d073973c8dae327ae4a9a89a1d892af7b8e3"
    )
