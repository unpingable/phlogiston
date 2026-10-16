from __future__ import annotations

import json
import os
import socket

import pytest

from community_model import ValidationError
from communityd.config import DaemonConfig
from communityd.fakepds import FakePds
from communityd.identity import (
    AuthorityDidResolver,
    did_web_document_url,
    extract_pds_origin,
    validate_bluesky_pds_origin,
    validate_public_url,
)
from communityd.operations import DaemonPorts, LocalAdminAuthorizer, admit
from communityd.pds import (
    EnvFileCredentialProvider,
    PdsAuthorityLedgerReader,
    PdsAuthorityWriter,
    PdsSession,
    PdsTransport,
    ResolvingPdsRecordReader,
)
from fakes_support import (
    ADMIN_DID,
    BASE_TIME,
    COMMUNITY_DID,
    POST_COLLECTION,
    SUBMISSION_COLLECTION,
    make_post,
    make_submission,
)

ALICE = "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa"
BOB = "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb"


@pytest.mark.parametrize(
    "origin",
    [
        "https://host.bsky.network",
        "https://phellinus.us-west.host.bsky.network.evil.example",
        "https://phellinus.us-west.host.bsky.network:8443",
        "https://user@phellinus.us-west.host.bsky.network",
        "http://phellinus.us-west.host.bsky.network",
        "https://phellinus..host.bsky.network",
        "https://juche.social",
    ],
)
def test_p0_bluesky_origin_refuses_nonmatching_hosts(origin) -> None:
    with pytest.raises(ValidationError, match="Bluesky|port"):
        validate_bluesky_pds_origin(origin)


def test_p0_resolver_rejects_unsupported_pds_before_repository_transport(
    monkeypatch,
) -> None:
    resolver = AuthorityDidResolver(
        plc_directory_url="https://plc.directory",
        timeout_seconds=1,
        cache_size=1,
        bluesky_only=True,
        address_resolver=lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    monkeypatch.setattr(
        resolver,
        "_get_document",
        lambda _: {
            "id": ALICE,
            "service": [
                {
                    "id": "#atproto_pds",
                    "type": "AtprotoPersonalDataServer",
                    "serviceEndpoint": "https://juche.social",
                }
            ],
        },
    )
    with pytest.raises(ValidationError, match="Bluesky"):
        resolver.pds_origin(ALICE)
    with pytest.raises(ValidationError, match="PLC"):
        resolver.pds_origin("did:web:juche.social")
    assert resolver._cache == {}
    assert validate_bluesky_pds_origin("https://phellinus.us-west.host.bsky.network")
    assert validate_bluesky_pds_origin(
        "https://phellinus.us-west.host.bsky.network:443"
    )


def test_p0_exact_juche_test_origin_requires_isolation(monkeypatch) -> None:
    with pytest.raises(ValueError, match="isolated"):
        AuthorityDidResolver(
            plc_directory_url="https://plc.directory",
            timeout_seconds=1,
            cache_size=1,
            bluesky_only=True,
            p0_test_pds_origin="https://juche.social",
        )
    resolver = AuthorityDidResolver(
        plc_directory_url="https://plc.directory",
        timeout_seconds=1,
        cache_size=1,
        bluesky_only=True,
        allow_loopback=True,
        p0_test_pds_origin="https://juche.social",
        address_resolver=lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    monkeypatch.setattr(
        resolver,
        "_get_document",
        lambda _: {
            "id": ALICE,
            "service": [
                {
                    "id": "#atproto_pds",
                    "type": "AtprotoPersonalDataServer",
                    "serviceEndpoint": "https://juche.social",
                }
            ],
        },
    )
    assert resolver.pds_origin(ALICE) == "https://juche.social"
    assert resolver.pds_origin(ALICE) == "https://juche.social"  # cached exact origin


class StaticResolver:
    def __init__(self, origins):
        self.origins = origins

    def pds_origin(self, did):
        return self.origins[did]


class DocumentResolver(AuthorityDidResolver):
    def __init__(self, documents):
        self.documents = documents
        self.fetches = []

        def public(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

        super().__init__(
            plc_directory_url="https://plc.directory",
            timeout_seconds=1,
            cache_size=1,
            address_resolver=public,
        )

    def _get_document(self, url):
        self.fetches.append(url)
        return self.documents[url]


def _seed(server: FakePds, did: str, suffix: str):
    post = server.seed(did, POST_COLLECTION, f"3jzfcijpj2z{suffix}a", make_post())
    return server.seed(
        did,
        SUBMISSION_COLLECTION,
        f"3jzfcijpj2z{suffix}b",
        make_submission(post),
    )


def test_authority_reads_two_foreign_repositories_at_their_own_pds(
    tmp_path, monkeypatch
) -> None:
    with (
        FakePds(session_did=COMMUNITY_DID) as community,
        FakePds(session_did=ALICE) as alice_pds,
        FakePds(session_did=BOB) as bob_pds,
    ):
        alice_submission = _seed(alice_pds, ALICE, "3")
        bob_submission = _seed(bob_pds, BOB, "4")
        credential = tmp_path / "credential.json"
        credential.write_text(
            json.dumps(
                {
                    "identifier": community.identifier,
                    "app_password": community.app_password,
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("COMMUNITYD_MULTI_PDS_CREDENTIAL", str(credential))
        config = DaemonConfig(
            community_did=COMMUNITY_DID,
            administrator_did=ADMIN_DID,
            community_pds_url=community.url,
            allowed_uid=os.geteuid(),
            reader_adapter="pds",
            ledger_adapter="pds",
            writer_adapter="pds",
            credential_provider="env_file",
            credential_ref="env:COMMUNITYD_MULTI_PDS_CREDENTIAL",
        )
        community_transport = PdsTransport(community.url, 2, 0)
        provider = EnvFileCredentialProvider()
        resolver = StaticResolver({ALICE: alice_pds.url, BOB: bob_pds.url})
        reader = ResolvingPdsRecordReader(
            resolver,  # type: ignore[arg-type]
            timeout_seconds=2,
            max_retries=0,
            cache_size=4,
        )
        ports = DaemonPorts(
            reader=reader,
            ledger=PdsAuthorityLedgerReader(community_transport),
            authorizer=LocalAdminAuthorizer(
                administrator_did=ADMIN_DID,
                allowed_uid=os.geteuid(),
            ),
            writer=PdsAuthorityWriter(
                community_transport,
                PdsSession(
                    community_transport,
                    lambda: provider.load(config.credential_ref),
                    expected_did=COMMUNITY_DID,
                ),
            ),
            credentials=provider,
            authority_reader=None,
        )
        admit(ports, config, alice_submission, now=BASE_TIME)
        admit(ports, config, bob_submission, now=BASE_TIME)

        assert sum("getRecord" in request for request in alice_pds.requests) == 2
        assert sum("getRecord" in request for request in bob_pds.requests) == 2
        assert not any(
            ALICE in request or BOB in request for request in community.requests
        )
        assert len(community.created) == 2


def test_did_web_mapping_and_pds_service_selection() -> None:
    assert did_web_document_url("did:web:example.com") == (
        "https://example.com/.well-known/did.json"
    )
    assert did_web_document_url("did:web:example.com:users:alice") == (
        "https://example.com/users/alice/did.json"
    )
    origin = extract_pds_origin(
        {
            "service": [
                {
                    "id": "#atproto_pds",
                    "type": "AtprotoPersonalDataServer",
                    "serviceEndpoint": "https://pds.example.com",
                }
            ]
        },
        allow_loopback=False,
    )
    assert origin == "https://pds.example.com"


def test_plc_resolution_checks_document_identity_and_uses_bounded_cache() -> None:
    url = f"https://plc.directory/{ALICE}"
    resolver = DocumentResolver(
        {
            url: {
                "id": ALICE,
                "service": [
                    {
                        "id": "#atproto_pds",
                        "type": "AtprotoPersonalDataServer",
                        "serviceEndpoint": "https://alice-pds.example.com",
                    }
                ],
            }
        }
    )
    assert resolver.pds_origin(ALICE) == "https://alice-pds.example.com"
    assert resolver.pds_origin(ALICE) == "https://alice-pds.example.com"
    assert resolver.fetches == [url]


def test_ssrf_addresses_and_redirectable_origin_shapes_refuse() -> None:
    def private(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))]

    with pytest.raises(ValidationError, match="private"):
        validate_public_url(
            "https://pds.example.com/xrpc",
            allow_loopback=False,
            address_resolver=private,
        )
    with pytest.raises(ValidationError):
        extract_pds_origin(
            {
                "service": [
                    {
                        "id": "#atproto_pds",
                        "serviceEndpoint": "https://user@pds.example.com",
                    }
                ]
            },
            allow_loopback=False,
        )


def test_controlled_hosted_routing_refuses_external_provider(monkeypatch):
    resolver = AuthorityDidResolver(
        plc_directory_url="https://plc.directory",
        timeout_seconds=1,
        cache_size=1,
        bluesky_only=True,
        p0_hosted_pds_origin="https://phlogiston.social",
        address_resolver=lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )

    def document(origin):
        return {
            "id": ALICE,
            "service": [
                {
                    "id": "#atproto_pds",
                    "type": "AtprotoPersonalDataServer",
                    "serviceEndpoint": origin,
                }
            ],
        }

    monkeypatch.setattr(
        resolver, "_get_document", lambda _: document("https://phlogiston.social")
    )
    assert resolver.pds_origin(ALICE) == "https://phlogiston.social"
    resolver._cache.clear()
    monkeypatch.setattr(
        resolver,
        "_get_document",
        lambda _: document("https://phellinus.us-west.host.bsky.network"),
    )
    with pytest.raises(ValidationError, match="configured Phlogiston"):
        resolver.pds_origin(ALICE)
    assert resolver._cache == {}


def test_mixed_hosted_resolver_permits_only_explicit_bluesky_reads(monkeypatch):
    resolver = AuthorityDidResolver(
        plc_directory_url="https://plc.directory",
        timeout_seconds=1,
        cache_size=1,
        bluesky_only=True,
        p0_hosted_pds_origin="https://phlogiston.social",
        p0_allow_bluesky=True,
        address_resolver=lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    for origin in [
        "https://phlogiston.social",
        "https://phellinus.us-west.host.bsky.network",
    ]:
        monkeypatch.setattr(
            resolver,
            "_get_document",
            lambda _, origin=origin: {
                "id": ALICE,
                "service": [
                    {
                        "id": "#atproto_pds",
                        "type": "AtprotoPersonalDataServer",
                        "serviceEndpoint": origin,
                    }
                ],
            },
        )
        resolver._cache.clear()
        assert resolver.pds_origin(ALICE) == origin
    for origin in [
        "https://juche.social",
        "https://phellinus.us-west.host.bsky.network.other",
    ]:
        monkeypatch.setattr(
            resolver,
            "_get_document",
            lambda _, origin=origin: {
                "id": ALICE,
                "service": [
                    {
                        "id": "#atproto_pds",
                        "type": "AtprotoPersonalDataServer",
                        "serviceEndpoint": origin,
                    }
                ],
            },
        )
        resolver._cache.clear()
        with pytest.raises(ValidationError):
            resolver.pds_origin(ALICE)
        assert not resolver._cache
    with pytest.raises(ValueError):
        AuthorityDidResolver(
            plc_directory_url="https://plc.directory",
            timeout_seconds=1,
            cache_size=1,
            p0_allow_bluesky=True,
        )
