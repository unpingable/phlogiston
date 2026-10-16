from __future__ import annotations

from dataclasses import replace

import pytest

from community_model import ValidationError
from community_space_artifact import (
    BoundedSourcePresentation,
    DisclosureMode,
    ProjectionArtifact,
    ProjectionArtifactCompiler,
    ProjectionArtifactEntry,
    ProjectionDisclosureInput,
    refuse_artifact_claim_upgrade,
)
from community_space_model import CommunityIdentity, SourceRelationship
from community_space_projection import LifecycleState


def _reason(expected: str):
    return pytest.raises(ValidationError, match=rf"^{expected} at")


def _input(
    m5a: dict[str, object],
    name: str,
    *,
    presentation: object | None = None,
    community_id: str | None = None,
    state: object | None = None,
) -> ProjectionDisclosureInput:
    projection = m5a[name]
    return ProjectionDisclosureInput(
        projection=projection,
        declared_community_identity_id=(
            community_id if community_id is not None else m5a["community"].identity_id
        ),
        declared_lifecycle_state=projection.state if state is None else state,
        presentation=presentation,
    )


def test_m5a_h1_suggested_cannot_be_published(m5a: dict[str, object]) -> None:
    compiler = ProjectionArtifactCompiler(m5a["community"])
    with _reason("suggested_publication_refused"):
        compiler.compile(
            (_input(m5a, "suggested", presentation=m5a["presentation"]),),
            m5a["ordinary"],
        )
    added = compiler.compile(
        (_input(m5a, "added", presentation=m5a["presentation"]),),
        m5a["ordinary"],
    ).artifact
    assert added is not None
    with _reason("suggested_publication_refused"):
        replace(added.entries[0], lifecycle_state=LifecycleState.SUGGESTED)


def test_m5a_h2_oauth_or_token_material_refuses(m5a: dict[str, object]) -> None:
    with _reason("artifact_secret_material_refused"):
        BoundedSourcePresentation(
            source_reference_id=m5a["post"].reference_id,
            source_uri=m5a["post"].record.uri,
            source_cid=m5a["post"].record.cid,
            title="Authorization: Bearer synthetic-secret",
            body="no",
            author_display_reference=m5a["post"].record.author_did,
        )
    with _reason("artifact_secret_material_refused"):
        ProjectionArtifactCompiler(m5a["community"]).compile(
            (_input(m5a, "added", presentation={"access_token": "secret"}),),
            m5a["ordinary"],
        )


def test_m5a_h3_private_moderator_authority_refuses(
    m5a: dict[str, object],
) -> None:
    with _reason("artifact_secret_material_refused"):
        ProjectionArtifactCompiler(m5a["community"]).compile(
            (
                _input(
                    m5a,
                    "added",
                    presentation={"moderator_private_key": "synthetic-secret"},
                ),
            ),
            m5a["ordinary"],
        )


def test_m5a_h4_invalid_projection_state_refuses(m5a: dict[str, object]) -> None:
    candidate = ProjectionDisclosureInput(
        projection=object(),
        declared_community_identity_id=m5a["community"].identity_id,
        declared_lifecycle_state=LifecycleState.ADDED,
    )
    with _reason("projection_state_required"):
        ProjectionArtifactCompiler(m5a["community"]).compile(
            (candidate,), m5a["ordinary"]
        )


def test_m5a_h5_community_identity_substitution_refuses(
    m5a: dict[str, object],
) -> None:
    with _reason("artifact_community_mismatch"):
        ProjectionArtifactCompiler(m5a["community"]).compile(
            (
                _input(
                    m5a,
                    "added",
                    presentation=m5a["presentation"],
                    community_id="sha256:" + "f" * 64,
                ),
            ),
            m5a["ordinary"],
        )
    other = CommunityIdentity(
        space=m5a["community"].space,
        community_actor_did="did:web:other-community.invalid.test",
    )
    with _reason("artifact_community_mismatch"):
        ProjectionArtifactCompiler(other).compile(
            (_input(m5a, "added", presentation=m5a["presentation"]),),
            m5a["ordinary"],
        )


def test_m5a_h6_lifecycle_upgrade_refuses(m5a: dict[str, object]) -> None:
    with _reason("artifact_lifecycle_upgrade_refused"):
        ProjectionArtifactCompiler(m5a["community"]).compile(
            (_input(m5a, "unavailable", state=LifecycleState.ADDED),),
            m5a["ordinary"],
        )
    with _reason("implicit_source_replacement_refused"):
        ProjectionArtifactCompiler(m5a["community"]).compile(
            (
                _input(
                    m5a,
                    "unavailable",
                    presentation=m5a["presentation"],
                ),
            ),
            m5a["ordinary"],
        )


def test_m5a_h7_receipt_reference_cannot_become_authorization() -> None:
    with _reason("artifact_claim_upgrade_refused"):
        refuse_artifact_claim_upgrade(
            {"receiptAuthorizesReader": True, "governanceAuthority": True}
        )


def test_m5a_h8_audit_fields_cannot_leak_into_ordinary_artifact(
    m5a: dict[str, object],
) -> None:
    compiler = ProjectionArtifactCompiler(m5a["community"])
    ordinary = compiler.compile(
        (_input(m5a, "added", presentation=m5a["presentation"]),),
        m5a["ordinary"],
    ).artifact
    audit = compiler.compile(
        (_input(m5a, "added", presentation=m5a["presentation"]),),
        m5a["audit"],
    ).artifact
    assert ordinary is not None and audit is not None
    with _reason("ordinary_disclosure_leak_refused"):
        replace(ordinary, entries=audit.entries)


def test_added_presentation_must_match_exact_admitted_source(
    m5a: dict[str, object],
) -> None:
    substituted = replace(
        m5a["presentation"],
        source_cid=m5a["changed"].source_observation.observed_record.cid,
    )
    with _reason("presentation_source_mismatch"):
        ProjectionArtifactCompiler(m5a["community"]).compile(
            (_input(m5a, "added", presentation=substituted),), m5a["ordinary"]
        )


def test_duplicate_current_projection_refuses(m5a: dict[str, object]) -> None:
    item = _input(m5a, "added", presentation=m5a["presentation"])
    with _reason("artifact_projection_conflict"):
        ProjectionArtifactCompiler(m5a["community"]).compile(
            (item, item), m5a["ordinary"]
        )


def test_artifact_values_are_immutable_and_integrity_checked(
    m5a: dict[str, object],
) -> None:
    artifact = (
        ProjectionArtifactCompiler(m5a["community"])
        .compile(
            (_input(m5a, "added", presentation=m5a["presentation"]),),
            m5a["ordinary"],
        )
        .artifact
    )
    assert isinstance(artifact, ProjectionArtifact)
    with pytest.raises((AttributeError, TypeError)):
        artifact.entries = ()  # type: ignore[misc]


def test_direct_entry_cannot_smuggle_untyped_presentation(
    m5a: dict[str, object],
) -> None:
    artifact = (
        ProjectionArtifactCompiler(m5a["community"])
        .compile(
            (_input(m5a, "added", presentation=m5a["presentation"]),),
            m5a["ordinary"],
        )
        .artifact
    )
    assert artifact is not None
    entry = artifact.entries[0]
    assert isinstance(entry, ProjectionArtifactEntry)
    with _reason("artifact_presentation_invalid"):
        replace(entry, presentation={"title": "untyped"})


def test_direct_artifact_cannot_change_disclosure_mode(
    m5a: dict[str, object],
) -> None:
    artifact = (
        ProjectionArtifactCompiler(m5a["community"])
        .compile(
            (_input(m5a, "added", presentation=m5a["presentation"]),),
            m5a["ordinary"],
        )
        .artifact
    )
    assert artifact is not None
    with _reason("audit_disclosure_incomplete"):
        replace(artifact, disclosure_mode=DisclosureMode.TECHNICAL_AUDIT)


def test_direct_entry_cannot_relabel_source_relationship(
    m5a: dict[str, object],
) -> None:
    artifact = (
        ProjectionArtifactCompiler(m5a["community"])
        .compile(
            (_input(m5a, "added", presentation=m5a["presentation"]),),
            m5a["ordinary"],
        )
        .artifact
    )
    assert artifact is not None
    with _reason("artifact_source_relationship_invalid"):
        replace(
            artifact.entries[0],
            source_relationship=SourceRelationship.UNAVAILABLE,
        )


def test_nested_values_are_revalidated_after_object_tampering(
    m5a: dict[str, object],
) -> None:
    artifact = (
        ProjectionArtifactCompiler(m5a["community"])
        .compile(
            (_input(m5a, "added", presentation=m5a["presentation"]),),
            m5a["ordinary"],
        )
        .artifact
    )
    assert artifact is not None
    presentation = artifact.entries[0].presentation
    assert isinstance(presentation, BoundedSourcePresentation)
    object.__setattr__(presentation, "title", "Authorization: Bearer changed-secret")
    with _reason("artifact_secret_material_refused"):
        artifact.validate_integrity()


def test_author_withdrawal_cannot_republish_or_drop_its_occurrence(
    m5a: dict[str, object],
) -> None:
    compiler = ProjectionArtifactCompiler(m5a["community"])
    with _reason("implicit_source_replacement_refused"):
        compiler.compile(
            (_input(m5a, "withdrawn", presentation=m5a["presentation"]),),
            m5a["ordinary"],
        )
    artifact = compiler.compile((_input(m5a, "withdrawn"),), m5a["ordinary"]).artifact
    assert artifact is not None
    with _reason("artifact_withdrawal_invalid"):
        replace(artifact.entries[0], withdrawal_id=None)
