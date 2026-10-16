from __future__ import annotations

import inspect
from dataclasses import fields, replace

import pytest

from community_model import ValidationError
from communitywatch_spaces_alpha import (
    AccessContext,
    DirectSpaceSource,
    FrozenEffectAuthorization,
    SpaceIdentity,
    SpaceObserver,
    SpaceRecordIdentity,
    assess_effect_preconditions,
)
from spaces_support import access, fixture_source, snapshot, space, timestamp


def test_alpha_space_uri_shape_is_distinct_from_public_record_uris(
    campaign: dict[str, object],
) -> None:
    target = space(campaign)
    record = SpaceRecordIdentity(
        space=target,
        author_did="did:plc:fixtureauthor",
        collection="invalid.test.spacepost",
        rkey="first",
    )

    assert target.uri == (
        "at://did:web:spaces.test.invalid/space/invalid.test.communityspace/alpha-board"
    )
    assert SpaceIdentity.parse(target.uri) == target
    assert record.uri == (
        "at://did:web:spaces.test.invalid/space/"
        "invalid.test.communityspace/alpha-board/"
        "did:plc:fixtureauthor/invalid.test.spacepost/first"
    )
    assert SpaceRecordIdentity.parse(record.uri) == record


def test_fixture_verification_requires_explicit_test_policy(
    campaign: dict[str, object],
) -> None:
    raw_space = campaign["space"]
    assert isinstance(raw_space, dict)
    observer = SpaceObserver(
        space=space(campaign),
        space_host=str(raw_space["spaceHost"]),
        source=fixture_source(campaign),
        admitted_collections=frozenset({"invalid.test.spacepost"}),
        access=access(campaign),
    )

    result = observer.reconcile()[0]

    assert result.observations == result.admissions == ()
    assert result.refusals == ("verification_mode_refused",)


def test_expired_access_context_cannot_provenance_a_new_fetch(
    campaign: dict[str, object],
) -> None:
    state = snapshot(campaign, "initial")

    with pytest.raises(ValidationError, match="while the recorded access was valid"):
        replace(state, acquired_at=timestamp("2026-08-20T16:00:00Z"))


def test_access_context_has_no_secret_bearing_field() -> None:
    assert {item.name for item in fields(AccessContext)} == {
        "space",
        "issuer_did",
        "user_did",
        "client_id",
        "issued_at",
        "expires_at",
        "verified_at",
        "access_method",
    }


def test_direct_source_port_is_read_only_and_snapshot_shaped() -> None:
    methods = {
        name
        for name, value in vars(DirectSpaceSource).items()
        if not name.startswith("_") and callable(value)
    }
    assert methods == {"list_writer_claims", "bind_repo", "fetch_repo"}
    assert tuple(inspect.signature(DirectSpaceSource.fetch_repo).parameters) == (
        "self",
        "space",
        "repo_did",
        "access",
    )


def test_complete_preconditions_still_cannot_confer_effect_authority(
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
        standing_ref="fixture:standing:member",
        occurrence_authorization_ref="fixture:occurrence:1",
        collection_authorization=frozen,
        effect_collection="invalid.test.spacepost",
    )

    assert decision.preconditions_met
    assert not decision.authority_conferred
    assert decision.reasons == ()
