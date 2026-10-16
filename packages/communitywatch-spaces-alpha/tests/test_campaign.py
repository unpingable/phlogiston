from __future__ import annotations

from communitywatch_spaces_alpha import (
    ALPHA_LABEL,
    BULLETIN_COMMIT,
    PROPOSAL_COMMIT,
    REFERENCE_COMMIT,
    SpaceObserver,
)
from spaces_support import (
    FakeDirectSpaceSource,
    claim,
    fixture_source,
    notification,
    snapshot,
)


def _flatten_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {str(key).lower() for key in value} | set().union(
            *(_flatten_keys(item) for item in value.values()), set()
        )
    if isinstance(value, list | tuple):
        return set().union(*(_flatten_keys(item) for item in value), set())
    return set()


def test_fixture_pins_exact_alpha_inputs(campaign: dict[str, object]) -> None:
    compatibility = campaign["compatibility"]
    assert isinstance(compatibility, dict)
    assert compatibility == {
        "label": ALPHA_LABEL,
        "proposalCommit": PROPOSAL_COMMIT,
        "referenceCommit": REFERENCE_COMMIT,
        "bulletinCommit": BULLETIN_COMMIT,
    }
    assert not (
        _flatten_keys(campaign)
        & {
            "token",
            "oauth_token",
            "delegation_token",
            "space_credential",
            "dpop_private_key",
            "private_key",
            "authorization_header",
            "cookie",
        }
    )


def test_initial_discovery_fetch_and_admission_have_complete_provenance(
    observer: SpaceObserver,
) -> None:
    source = observer.source
    assert isinstance(source, FakeDirectSpaceSource)

    results = observer.reconcile()

    assert len(results) == 1
    result = results[0]
    assert result.trigger == "reconcile"
    assert result.refusals == ()
    assert len(result.observations) == len(result.admissions) == 1
    assert [call[0] for call in source.calls] == ["listRepos", "bindRepo", "getRepo"]

    provenance = result.observations[0].provenance()
    assert provenance["claimScope"] == "space-record-observation"
    assert provenance["governanceAuthority"] is False
    assert provenance["space"] == {
        "authorityDid": "did:web:spaces.test.invalid",
        "spaceType": "invalid.test.communityspace",
        "skey": "alpha-board",
    }
    record = provenance["record"]
    assert isinstance(record, dict)
    assert record["authorDid"] == "did:plc:fixtureauthor"
    acquisition = provenance["acquisition"]
    assert isinstance(acquisition, dict)
    assert acquisition["spaceHost"] == "https://space-host.test.invalid"
    assert acquisition["repoHost"] == "https://repo-host.test.invalid"
    assert acquisition["writerSetRev"] == "3mtaaaabbbbbc"
    assert acquisition["repoRev"] == "3mtaaaabbbbbc"
    verification = provenance["verification"]
    assert isinstance(verification, dict)
    assert verification["mode"] == "fixture"
    assert verification["protocolAssumption"] == ALPHA_LABEL
    assert set(verification["claims"]) == {
        "author_signature_context",
        "commit_mac",
        "lthash_record_set",
        "record_cids",
        "space_context",
    }
    forbidden = {
        "token",
        "oauth_token",
        "delegation_token",
        "space_credential",
        "dpop_private_key",
        "private_key",
        "authorization",
    }
    assert not (_flatten_keys(provenance) & forbidden)


def test_notification_is_only_a_hint_then_direct_source_is_refetched(
    campaign: dict[str, object], observer: SpaceObserver
) -> None:
    initial = observer.reconcile()[0]
    assert len(initial.admissions) == 1
    source = observer.source
    assert isinstance(source, FakeDirectSpaceSource)
    source.repo_snapshot = snapshot(campaign, "advanced")

    before = (len(observer.observations), len(observer.admissions))
    hinted = observer.record_notification(notification(campaign))

    assert hinted.observations == hinted.admissions == ()
    assert before == (len(observer.observations), len(observer.admissions))
    assert len(observer.pending_notifications) == 1

    synchronized = observer.synchronize_notifications()

    assert len(synchronized) == 1
    assert synchronized[0].trigger == "notification-refetch"
    assert len(synchronized[0].admissions) == 2
    assert source.calls[-2:][0][0] == "bindRepo"
    assert source.calls[-1][0] == "getRepo"
    assert observer.pending_notifications == ()
    assert {
        item.observation.repo_snapshot.rev for item in observer.current_admissions()
    } == {"3mtaaaabbbbbe"}


def test_dropped_notification_recovers_by_periodic_writer_reconciliation(
    campaign: dict[str, object], observer: SpaceObserver
) -> None:
    observer.reconcile()
    source = observer.source
    assert isinstance(source, FakeDirectSpaceSource)
    source.claims = (claim(campaign, "advanced"),)
    source.repo_snapshot = snapshot(campaign, "advanced")

    results = observer.reconcile()

    assert observer.pending_notifications == ()
    assert len(results) == 1
    assert len(results[0].admissions) == 2
    assert {
        item.observation.repo_snapshot.rev for item in observer.current_admissions()
    } == {"3mtaaaabbbbbe"}


def test_source_fixture_is_deterministic_across_fresh_observers(
    campaign: dict[str, object], observer: SpaceObserver
) -> None:
    first = observer.reconcile()[0].observations[0].provenance()
    raw_space = campaign["space"]
    assert isinstance(raw_space, dict)
    second_observer = SpaceObserver(
        space=observer.space,
        space_host=str(raw_space["spaceHost"]),
        source=fixture_source(campaign),
        admitted_collections=observer.admitted_collections,
        access=observer.access,
        accepted_verification_modes=frozenset({"fixture"}),
    )
    second = second_observer.reconcile()[0].observations[0].provenance()
    assert first == second
