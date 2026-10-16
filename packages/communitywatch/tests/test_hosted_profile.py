"""Controlled hosted-origin qualification; local proof fixtures, no provider IO."""

import sys
from pathlib import Path

import pytest

from community_model import SUBMISSION_COLLECTION
from communitywatch.config import ConfigError, parse_config
from communitywatch.syncclient import FetchError, UrllibHttpGetter
from communitywatch.verifying import _Claim, _ProofFetcher

HOSTED = "https://phlogiston.social"


def document():
    return {
        "community_did": "did:plc:community",
        "administrator_did": "did:plc:admin",
        "community_slug": "hosted",
        "sqlite_path": "local.sqlite3",
        "event_source_url": "wss://jetstream.us-west.bsky.network",
        "resolver_url": "https://plc.directory",
        "p0_hosted_pds_origin": HOSTED,
    }


def test_hosted_config_is_explicit_exact_and_separate():
    assert parse_config(document()).p0_hosted_pds_origin == HOSTED
    for change in (
        {"p0_hosted_pds_origin": "https://phlogiston.social:443"},
        {"p0_hosted_pds_origin": "https://other.social"},
        {"p0_test_pds_origin": "https://juche.social"},
        {"p0_bluesky_only": True},
    ):
        with pytest.raises(ConfigError):
            parse_config({**document(), **change})


@pytest.mark.parametrize("allow_bluesky", [False, True])
def test_hosted_proof_guard_permits_exact_origin_and_refuses_bluesky(allow_bluesky):
    sys.path.insert(
        0, str(Path(__file__).resolve().parents[3] / "tests" / "acceptance")
    )
    from ingest_fixtures import FixtureRepo

    repo = FixtureRepo("did:plc:hostedfixture", 0x1234)
    rkey = "3jzfcijpj2z2a"
    repo.put(SUBMISSION_COLLECTION, rkey, {"local": "proof"})
    origin = HOSTED
    calls = []

    class Did:
        def resolve(self, did):
            return repo.did_document(origin)

    class Pds:
        def get_record_car(self, url, *, repo: str, collection, rkey):
            calls.append(url)
            return fixture.record_car(collection, rkey)

    fixture = repo
    claim = _Claim(
        repo.did,
        repo.current_rev,
        "create",
        SUBMISSION_COLLECTION,
        rkey,
        repo.record_cid(SUBMISSION_COLLECTION, rkey),
    )
    fetcher = _ProofFetcher(
        Did(), Pds(), p0_hosted_pds_origin=HOSTED, p0_allow_bluesky=allow_bluesky
    )
    proof, _, digest, failure = fetcher.fetch(claim)
    assert proof is not None and digest is not None and failure is None
    assert calls == [HOSTED]
    for origin in (
        "https://phellinus.us-west.host.bsky.network",
        "https://juche.social",
        "https://phlogiston.social.other",
    ):
        if allow_bluesky and origin == "https://phellinus.us-west.host.bsky.network":
            assert fetcher.fetch(claim)[3] is None
            continue
        assert fetcher.fetch(claim) == (
            None,
            "p0:unsupported-pds-host",
            None,
            "unverified",
        )
    assert calls == (
        [HOSTED, "https://phellinus.us-west.host.bsky.network"]
        if allow_bluesky
        else [HOSTED]
    )


def test_hosted_http_guard_refuses_other_provider_before_transport():
    getter = UrllibHttpGetter(p0_hosted_pds_origin=HOSTED)
    for url in (
        "https://juche.social/xrpc/test",
        "https://phellinus.us-west.host.bsky.network/xrpc/test",
    ):
        with pytest.raises(FetchError, match="unsupported"):
            getter.get(url)


def test_mixed_config_requires_explicit_hosted_profile():
    assert parse_config({**document(), "p0_allow_bluesky": True}).p0_allow_bluesky
    assert not parse_config(document()).p0_allow_bluesky
    for changes in [
        {"p0_hosted_pds_origin": None, "p0_allow_bluesky": True},
        {"p0_allow_bluesky": "true"},
        {"p0_allow_bluesky": 1},
        {"p0_allow_bluesky": True, "p0_test_pds_origin": "https://juche.social"},
    ]:
        with pytest.raises(ConfigError):
            parse_config({**document(), **changes})


def test_mixed_http_accepts_bluesky_but_refuses_other_origins(monkeypatch):
    import urllib.request

    calls = []

    class Response:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            return b"{}"

    class Opener:
        def open(self, request, **kwargs):
            calls.append(request.full_url)
            return Response()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener())
    getter = UrllibHttpGetter(p0_hosted_pds_origin=HOSTED, p0_allow_bluesky=True)
    url = "https://phellinus.us-west.host.bsky.network/xrpc/test"
    assert getter.get(url).status == 200
    for origin in [
        "https://juche.social",
        "https://phlogiston.social.other",
        "https://phellinus.us-west.host.bsky.network.other",
    ]:
        with pytest.raises(FetchError):
            getter.get(origin + "/xrpc/test")
    assert calls == [url]


def test_mixed_flag_is_wired_into_both_proof_paths(tmp_path):
    from communitywatch.builder import build_runner
    from communitywatch.storage import ObserverStore

    config = parse_config({**document(), "p0_allow_bluesky": True})
    store = ObserverStore(
        tmp_path / "observer.sqlite3",
        community_did=config.community_did,
        administrator_did=config.administrator_did,
    )
    runner = build_runner(config, store)
    assert runner.event_source.p0_allow_bluesky
    assert runner.resolver.p0_allow_bluesky
    assert runner.event_source.pds_client.http.p0_allow_bluesky


def test_direct_http_constructor_refuses_unpaired_mixed_flag():
    with pytest.raises(ValueError):
        UrllibHttpGetter(p0_allow_bluesky=True)
    with pytest.raises(ValueError):
        UrllibHttpGetter(
            p0_hosted_pds_origin=HOSTED,
            p0_allow_bluesky=True,
            p0_test_pds_origin="https://juche.social",
        )


@pytest.mark.parametrize(
    "origin",
    [
        "https://.host.bsky.network",
        "https://-bad.host.bsky.network",
        "https://one..host.bsky.network",
        "https://bad-.host.bsky.network",
        "https://" + "a" * 64 + ".host.bsky.network",
    ],
)
def test_mixed_observer_rejects_invalid_bluesky_dns_labels(origin):
    from communitywatch.verifying import supported_bluesky_pds

    assert not supported_bluesky_pds(origin)
    with pytest.raises(FetchError):
        UrllibHttpGetter(p0_hosted_pds_origin=HOSTED, p0_allow_bluesky=True).get(
            origin + "/xrpc/test"
        )
