from __future__ import annotations

from dataclasses import replace

from communitywatch_spaces_alpha import (
    FrozenEffectAuthorization,
    SpaceObserver,
    assess_effect_preconditions,
)
from spaces_support import (
    FakeDirectSpaceSource,
    access,
    binding,
    claim,
    fixture_source,
    notification,
    other_space,
    snapshot,
    space,
    timestamp,
)


def _observer(
    campaign: dict[str, object], source: FakeDirectSpaceSource
) -> SpaceObserver:
    raw_space = campaign["space"]
    assert isinstance(raw_space, dict)
    return SpaceObserver(
        space=space(campaign),
        space_host=str(raw_space["spaceHost"]),
        source=source,
        admitted_collections=frozenset({"invalid.test.spacepost"}),
        access=access(campaign),
        accepted_verification_modes=frozenset({"fixture"}),
    )


def _hostile(campaign: dict[str, object]) -> dict[str, object]:
    hostile = campaign["hostile"]
    assert isinstance(hostile, dict)
    return hostile


def test_h1_writer_set_state_substitution_is_not_admitted(
    campaign: dict[str, object],
) -> None:
    hostile_hash = str(_hostile(campaign)["writerSetSubstitutionHash"])
    source = FakeDirectSpaceSource(
        claims=(claim(campaign, "initial", commit_hash=hostile_hash),),
        repo_binding=binding(campaign),
        repo_snapshot=snapshot(campaign, "initial"),
    )

    result = _observer(campaign, source).reconcile()[0]

    assert result.observations == result.admissions == ()
    assert result.refusals == ("writer_set_state_conflict",)
    assert [item[0] for item in source.calls] == ["listRepos", "bindRepo", "getRepo"]


def test_h2_notification_only_never_becomes_evidence(
    campaign: dict[str, object],
) -> None:
    observer = _observer(campaign, fixture_source(campaign))

    result = observer.record_notification(notification(campaign))

    assert result.observations == result.admissions == ()
    assert observer.observations == observer.admissions == ()
    assert len(observer.pending_notifications) == 1


def test_h3_same_record_coordinates_in_another_space_are_refused(
    campaign: dict[str, object],
) -> None:
    source = FakeDirectSpaceSource(
        claims=(claim(campaign, "initial"),),
        repo_binding=binding(campaign),
        repo_snapshot=snapshot(campaign, "initial", target_space=other_space(campaign)),
    )

    result = _observer(campaign, source).reconcile()[0]

    assert result.admissions == ()
    assert "wrong_space" in result.refusals
    assert "record_wrong_space" in result.refusals


def test_h4_record_author_must_match_source_bound_repo(
    campaign: dict[str, object],
) -> None:
    wrong_author = str(_hostile(campaign)["wrongAuthorDid"])
    source = FakeDirectSpaceSource(
        claims=(claim(campaign, "initial"),),
        repo_binding=binding(campaign),
        repo_snapshot=snapshot(campaign, "initial", record_author=wrong_author),
    )

    result = _observer(campaign, source).reconcile()[0]

    assert result.observations == result.admissions == ()
    assert result.refusals == ("record_author_mismatch",)


def test_h5_unbound_repo_host_cannot_inherit_expected_source_provenance(
    campaign: dict[str, object],
) -> None:
    substitute = str(_hostile(campaign)["substituteRepoHost"])
    source = FakeDirectSpaceSource(
        claims=(claim(campaign, "initial"),),
        repo_binding=binding(campaign),
        repo_snapshot=snapshot(campaign, "initial", repo_host=substitute),
    )

    result = _observer(campaign, source).reconcile()[0]

    assert result.observations == result.admissions == ()
    assert result.refusals == ("repo_host_substitution",)


def test_h6_older_repo_state_cannot_replace_an_established_head(
    campaign: dict[str, object],
) -> None:
    source = fixture_source(campaign)
    observer = _observer(campaign, source)
    initial_admission = observer.reconcile()[0].admissions[0]
    source.claims = (claim(campaign, "advanced"),)
    source.repo_snapshot = snapshot(campaign, "advanced")
    advanced = observer.reconcile()[0]
    assert len(advanced.admissions) == 2
    assert not observer.is_current(initial_admission.observation)

    source.repo_snapshot = snapshot(campaign, "initial")
    stale = observer.sync_discovered_repo("did:plc:fixtureauthor")

    assert stale.admissions == ()
    assert stale.refusals == ("repo_behind_writer_discovery",)
    assert {
        item.observation.repo_snapshot.rev for item in observer.current_admissions()
    } == {"3mtaaaabbbbbe"}


def test_h7_lost_or_expired_access_does_not_rewrite_history_or_standing(
    campaign: dict[str, object],
) -> None:
    source = fixture_source(campaign)
    observer = _observer(campaign, source)
    admitted = observer.reconcile()[0].admissions[0]
    history = admitted.observation.provenance()

    observer.replace_access(None)
    refused = observer.reconcile()[0]

    assert refused.refusals == ("access_unavailable",)
    assert admitted.observation.provenance() == history
    assert observer.current_admissions() == (admitted,)

    renewed = replace(access(campaign), verified_at=timestamp("2026-08-20T14:06:00Z"))
    observer.replace_access(renewed)
    source.claims = (claim(campaign, "advanced"),)
    source.repo_snapshot = snapshot(campaign, "advanced", access_context=renewed)
    assert len(observer.reconcile()[0].admissions) == 2
    # Renewed read access still supplies neither community standing nor an
    # occurrence authorization.
    gated = assess_effect_preconditions(
        observer.current_admissions()[0],
        evidence_is_current=True,
        standing_ref=None,
        occurrence_authorization_ref=None,
        collection_authorization=None,
        effect_collection="invalid.test.spacepost",
    )
    assert not gated.preconditions_met
    assert not gated.authority_conferred
    assert set(gated.reasons) >= {
        "community_standing_required",
        "occurrence_authorization_required",
    }


def test_h8_dynamic_space_type_widening_does_not_expand_frozen_authority(
    campaign: dict[str, object], observer: SpaceObserver
) -> None:
    admission = observer.reconcile()[0].admissions[0]
    declarations = _hostile(campaign)["spaceTypeDeclarations"]
    assert isinstance(declarations, dict)
    at_t0 = frozenset(str(item) for item in declarations["t0"])
    at_t1 = frozenset(str(item) for item in declarations["t1"])
    frozen = FrozenEffectAuthorization(
        authorization_id="fixture-effect-authorization-t0",
        space=space(campaign),
        effective_collections=at_t0,
        authorized_at=timestamp("2026-08-20T14:01:00Z"),
        scope="space:invalid.test.communityspace",
        declaration_evidence_ref="fixture:space-type:t0",
        resolved_from_dynamic_default=True,
    )

    assert "invalid.test.spaceeffect" in at_t1
    assert not frozen.permits("invalid.test.spaceeffect")
    decision = assess_effect_preconditions(
        admission,
        evidence_is_current=True,
        standing_ref="fixture:standing:member",
        occurrence_authorization_ref="fixture:occurrence:1",
        collection_authorization=frozen,
        effect_collection="invalid.test.spaceeffect",
    )
    assert not decision.preconditions_met
    assert not decision.authority_conferred
    assert decision.reasons == ("collection_not_authorized_at_boundary",)


def test_h9_valid_access_and_admitted_evidence_are_not_standing(
    campaign: dict[str, object], observer: SpaceObserver
) -> None:
    admission = observer.reconcile()[0].admissions[0]
    frozen = FrozenEffectAuthorization(
        authorization_id="fixture-effect-authorization-t0",
        space=space(campaign),
        effective_collections=frozenset({"invalid.test.spacepost"}),
        authorized_at=timestamp("2026-08-20T14:01:00Z"),
        scope="space:invalid.test.communityspace",
        declaration_evidence_ref="fixture:space-type:t0",
        resolved_from_dynamic_default=True,
    )

    decision = assess_effect_preconditions(
        admission,
        evidence_is_current=True,
        standing_ref=None,
        occurrence_authorization_ref="fixture:occurrence:1",
        collection_authorization=frozen,
        effect_collection="invalid.test.spacepost",
    )

    assert not decision.preconditions_met
    assert not decision.authority_conferred
    assert decision.reasons == ("community_standing_required",)


def test_h10_standing_is_not_per_occurrence_effect_authorization(
    campaign: dict[str, object], observer: SpaceObserver
) -> None:
    admission = observer.reconcile()[0].admissions[0]
    frozen = FrozenEffectAuthorization(
        authorization_id="fixture-effect-authorization-t0",
        space=space(campaign),
        effective_collections=frozenset({"invalid.test.spacepost"}),
        authorized_at=timestamp("2026-08-20T14:01:00Z"),
        scope="space:invalid.test.communityspace",
        declaration_evidence_ref="fixture:space-type:t0",
        resolved_from_dynamic_default=False,
    )

    decision = assess_effect_preconditions(
        admission,
        evidence_is_current=True,
        standing_ref="fixture:standing:member",
        occurrence_authorization_ref=None,
        collection_authorization=frozen,
        effect_collection="invalid.test.spacepost",
    )

    assert not decision.preconditions_met
    assert not decision.authority_conferred
    assert decision.reasons == ("occurrence_authorization_required",)


def test_incomplete_spaces_verification_is_refused_without_public_mst_fallback(
    campaign: dict[str, object],
) -> None:
    source = FakeDirectSpaceSource(
        claims=(claim(campaign, "initial"),),
        repo_binding=binding(campaign),
        repo_snapshot=snapshot(
            campaign,
            "initial",
            verification_claims=frozenset({"record_cids"}),
        ),
    )

    result = _observer(campaign, source).reconcile()[0]

    assert result.observations == result.admissions == ()
    assert result.refusals == ("verification_incomplete",)
