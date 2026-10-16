"""Assemble the live observer pipeline from the strict configuration.

Wiring: Jetstream v2 source -> verify-at-ingest wrapper -> observer store,
with the verified subject resolver feeding the resolve stage.  Every network
client built here is a public unauthenticated reader; the observer
configuration carries no credential fields by construction.
"""

from __future__ import annotations

from .config import ConfigError, ObserverConfig
from .jetstream import JetstreamEventSource
from .runner import ObserverRunner
from .storage import ObserverStore
from .syncclient import DidResolver, PdsClient, UrllibHttpGetter
from .verifying import VerifiedSubjectResolver, VerifyingEventSource

SOURCE_NAME = "jetstream"


def build_runner(config: ObserverConfig, store: ObserverStore) -> ObserverRunner:
    """Connect source, verifier, resolver, and store for one observer."""

    if config.administrator_did is None:
        raise ConfigError("administrator_did is required for the index pipeline")
    if store.administrator_did != config.administrator_did:
        raise ConfigError("observer store and configuration administrators differ")
    if config.p0_test_pds_origin is not None and (
        config.p0_test_pds_origin != "https://juche.social"
        or not config.p0_isolated_test
        or not config.p0_bluesky_only
        or config.bind not in {"127.0.0.1", "::1"}
    ):
        raise ConfigError("test PDS override requires isolated loopback P0")
    if config.p0_hosted_pds_origin is not None and (
        config.p0_hosted_pds_origin != "https://phlogiston.social"
        or config.p0_test_pds_origin is not None
        or config.p0_bluesky_only
    ):
        raise ConfigError(
            "controlled hosted P0 requires separate exact Phlogiston origin"
        )
    if (
        config.p0_allow_bluesky
        and config.p0_hosted_pds_origin != "https://phlogiston.social"
    ):
        raise ConfigError("p0_allow_bluesky requires exact hosted P0 origin")
    http = UrllibHttpGetter(
        p0_bluesky_only=config.p0_bluesky_only,
        p0_test_pds_origin=config.p0_test_pds_origin,
        p0_hosted_pds_origin=config.p0_hosted_pds_origin,
        p0_allow_bluesky=config.p0_allow_bluesky,
    )
    did_resolver = DidResolver(http, plc_url=config.resolver_url)
    pds_client = PdsClient(http)
    source = JetstreamEventSource(
        config.event_source_url,
        # Submission authors are not known a priori: the subscription pins
        # the four community collections and cannot pin repository DIDs.
        wanted_dids=(),
        source_name=SOURCE_NAME,
    )
    verifying = VerifyingEventSource(
        source,
        did_resolver,
        pds_client,
        p0_bluesky_only=config.p0_bluesky_only,
        p0_test_pds_origin=config.p0_test_pds_origin,
        p0_hosted_pds_origin=config.p0_hosted_pds_origin,
        p0_allow_bluesky=config.p0_allow_bluesky,
    )
    resolver = VerifiedSubjectResolver(
        did_resolver,
        pds_client,
        p0_bluesky_only=config.p0_bluesky_only,
        p0_test_pds_origin=config.p0_test_pds_origin,
        p0_hosted_pds_origin=config.p0_hosted_pds_origin,
        p0_allow_bluesky=config.p0_allow_bluesky,
    )
    return ObserverRunner(
        store=store,
        event_source=verifying,
        source_name=SOURCE_NAME,
        resolver=resolver,
        subject_refresh_seconds=config.subject_refresh_seconds,
    )


__all__ = ["SOURCE_NAME", "build_runner"]
