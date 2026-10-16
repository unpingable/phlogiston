"""Single compatibility boundary for the 2026-08-20 Spaces alpha.

Nothing outside this module should spell alpha endpoint names, URI markers,
commit formats, or the verification claims expected from a direct repo fetch.
These constants are observations of volatile upstream inputs, not a stable
protocol specification.
"""

from __future__ import annotations

from types import MappingProxyType

ALPHA_LABEL = "atproto-spaces-alpha-2026-08-20"
ALPHA_DATE = "2026-08-20"

ANNOUNCEMENT_URL = "https://atproto.com/blog/atproto-spaces-alpha"
PROPOSAL_URL = (
    "https://github.com/bluesky-social/proposals/tree/main/0016-permissioned-data"
)
PROPOSAL_COMMIT = "54c9cf5153d668c4f4fb4438529967412e861775"
REFERENCE_URL = "https://github.com/bluesky-social/atproto/pull/5187"
REFERENCE_COMMIT = "89deb9faca20e56fa2a262fe9746ed52bc1095ba"
BULLETIN_URL = "https://github.com/bluesky-social/bulletin"
BULLETIN_COMMIT = "ccca73d212167e20da56db4691ba7c94e9ad5ccc"
BULLETIN_ALPHA_PACKAGE_COMMIT = "2f77206ff8010710db5733c454abff9eb5ebb96b"

SPACE_URI_MARKER = "space"
COMMIT_FORMAT = 1
COMMIT_CONTEXT_TAG = "atproto-space-v1"
SOURCE_VECTOR_FORMAT = "spaces-alpha-sa1-vector-v1"
SA2_SOURCE_VECTOR_FORMAT = "spaces-alpha-sa2-car-vector-v1"
SA3_REFERENCE_VECTOR_FORMAT = "spaces-alpha-sa3-reference-vector-v1"
PERMISSIONED_REPO_PROOF_KIND = "permissioned-repo-v1"
PUBLIC_REPO_PROOF_KIND = "public-mst-car"
SA1_VERIFICATION_METHOD = "spaces-alpha-v1-dag-cbor+lthash+context-mac+es256k"
SA1_VERIFIER_VERSION = "sa1-v1"
# SA2 deliberately remains pinned to the reference commit used to construct
# the SA1 vectors.  The volatile PR branch stopped containing the Spaces code
# after this commit on 2026-08-20, so a moving branch head is not a usable pin.
SA2_REFERENCE_COMMIT = REFERENCE_COMMIT
SA2_CAR_ADAPTER_VERSION = "sa2-car-v1"
SA2_CAR_METHOD = "carv1+two-ordered-dag-cbor-sha256-roots"
SA3_REFERENCE_IMPLEMENTATION = "@atproto/space.serializeRepo"
SA3_REFERENCE_PACKAGE_VERSION = "0.0.1"
SA3_REFERENCE_COMMIT = REFERENCE_COMMIT
SA3_REFERENCE_ARTIFACT_SHA256 = (
    "2ac249edc712c796211250bd7084850fc3d2cb576a575fa4c6c93da92115dd23"
)
SA3_QUALIFICATION_RECEIPT_IDS = (
    "sha256:c7584ad43983317c1a251aef0b9ee4801669579898a84ca3528c18e8e868abf0",
)
SA3_SOURCE_VECTOR_IDENTIFIER = "sa1:valid-initial:89deb9f"
SA3_INTEROP_METHOD = "reference-car-byte+root+block+sa1-input-parity"
SA3_INTEROP_VERSION = "sa3-v1"
SA4_SOURCE_VECTOR_FORMAT = "spaces-alpha-sa4-source-vector-v1"
SA4_REFERENCE_VECTOR_FORMAT = "spaces-alpha-sa4-reference-transition-vector-v1"
SA4_REFERENCE_IMPLEMENTATION = "@atproto/space.RepoCommit.applyOps+serializeRepo"
SA4_REFERENCE_PACKAGE_VERSION = "0.0.1"
SA4_REFERENCE_COMMIT = REFERENCE_COMMIT
SA4_REFERENCE_DRIVER_SHA256 = (
    "fc0132528f7f880b33cced1401c25c1862a7c22c3f1ed5452169d02b9056aeef"
)
SA4_REFERENCE_SOURCE_SHA256 = (
    "554e2b6bdda9258235c8dab5f2371aea505d4e1ed1593ed90a189d13324041a9"
)
SA4_REFERENCE_MANIFEST_SHA256 = (
    "e9a7725c0242cae1955f32f3b34ab9a7b7f39a80d12d1bc35691c08823c28f43"
)
SA4_REFERENCE_ARTIFACT_SHA256 = MappingProxyType(
    {
        "n": "c564c3ff8a4663014e6100d26a78ce4ba5f60da01799c2b09a307e8febd1ac9e",
        "n1": "aec612cf702f6cd39cf84b635017772d57cbca08ad132107664d40b92d9711dd",
        "n2": "28b912b64e1b9c98b78d06ac04c60517cc28c9de0d44a9f64214632a78a4fb73",
    }
)
SA4_REFERENCE_OPERATION_SHA256 = MappingProxyType(
    {
        "n-to-n1": "a027289630c37737eacb3b81b83b2806d5a83d410032a571ef070f1fd96f43c9",
        "n1-to-n2": "9b128157d538a6103b04ac3304b5772d2cefce13c89b5086ce325807cc928fc7",
    }
)
SA4_TRANSITION_RECEIPT_IDS = MappingProxyType(
    {
        "n-to-n1": "sha256:55a0adf0522c47333b174c0071f8dc7a99f5239182c5ccbdc810760a7c92337f",
        "n1-to-n2": "sha256:6bd6827ac83a780f0ea852ba08da80e5a293a381366a56d362eca8d1f952e526",
    }
)
SA4_TRANSITION_METHOD = "qualified-source+ordered-ops+qualified-target"
SA4_TRANSITION_VERSION = "sa4-v1"
SA5_SOURCE_VECTOR_FORMAT = "spaces-alpha-sa5-list-repo-ops-vector-v1"
SA5_ACQUISITION_METHOD = "listRepoOps-json+observed-cursor-chain"
SA5_ADAPTER_VERSION = "sa5-v1"
SA6_RECONCILIATION_METHOD = "qualified-state-relation+optional-sa4-transition"
SA6_RECONCILER_VERSION = "sa6-v1"
SA6_SOURCE_VECTOR_FORMAT = "spaces-alpha-sa6-reconciliation-vector-v1"
SA7_TRANSPORT_BOUNDARY_VERSION = "sa7-v1"
SA8_SOURCE_VECTOR_FORMAT = "spaces-alpha-sa8-recovery-vector-v1"
SA8_RECOVERY_METHOD = "sa5-path-selection+sa4-or-sa2-sa1-sa6"
SA8_RECOVERY_VERSION = "sa8-v1"
SA8_RECOVERY_DOCTRINE = (
    "Recovery can restore observability. It cannot manufacture missing provenance."
)
SA9A_HTTP_METHOD = "stdlib-urllib-get+bounded-body+same-origin-redirects"
SA9A_HTTP_VERSION = "sa9a-v1"
SA9A_HTTP_DOCTRINE = "Transport success is acquisition evidence, not source authority."
SA9A_SOURCE_VECTOR_FORMAT = "spaces-alpha-sa9a-http-vector-v1"
SA9B_DID_SPEC_URL = "https://atproto.com/specs/did"
SA9B_DID_SPEC_OBSERVED_DATE = "2026-08-21"
SA9B_BINDING_METHOD = "bounded-did-json+ordered-atproto-spaces-selection"
SA9B_BINDING_VERSION = "sa9b-v1"
SA9B_BINDING_DOCTRINE = "Service binding interprets identity evidence; it does not create identity evidence."
SA9B_SOURCE_VECTOR_FORMAT = "spaces-alpha-sa9b-did-binding-vector-v1"
SA9C_DID_SPEC_URL = SA9B_DID_SPEC_URL
SA9C_DID_SPEC_OBSERVED_DATE = "2026-08-21"
SA9C_WEB_SPEC_URL = "https://w3c-ccg.github.io/did-method-web/"
SA9C_WEB_SPEC_OBSERVED_DATE = "2026-08-21"
SA9C_PLC_SPEC_URL = (
    "https://github.com/did-method-plc/did-method-plc/blob/"
    "2ed82a5ccf1b424aa5e2f6c5b461dc0ee133278b/website/spec/v0.1/did-plc.md"
)
SA9C_PLC_REFERENCE_URL = "https://github.com/did-method-plc/did-method-plc"
SA9C_PLC_REFERENCE_COMMIT = "2ed82a5ccf1b424aa5e2f6c5b461dc0ee133278b"
SA9C_PLC_REFERENCE_FIXTURE_SHA256 = (
    "8a45e23e5c59164d1b84f78ec6c3dfecb38e4bb2a4ff0927d1b8aa4ef280a32a"
)
SA9C_PLC_REFERENCE_DRIVER_SHA256 = (
    "1b44dbaa61415cd66f83e0f4c35517a16f698adc9242fc4327562a4672707ebc"
)
SA9C_PLC_SPEC_VERSION = "v0.3.0"
SA9C_RESOLUTION_DOCTRINE = (
    "DID methods establish provenance differently; common output must not erase "
    "those differences."
)
SA9C_AUTHORITY_DOCTRINE = "Resolution provenance is not governance authority."
SA9C_WEB_METHOD = "did:web-hostname+bounded-https-webpki+exact-json"
SA9C_WEB_VERSION = "sa9c-web-v1"
SA9C_PLC_METHOD = "did:plc-v0.3.0-operation-cids+rotation-signatures+recovery"
SA9C_PLC_VERSION = "sa9c-plc-v1"
SA9C_SOURCE_VECTOR_FORMAT = "spaces-alpha-sa9c-did-resolution-vector-v1"
SA9D_OAUTH_SPEC_URL = "https://atproto.com/specs/oauth"
SA9D_OAUTH_SPEC_OBSERVED_DATE = "2026-08-21"
SA9D_DPOP_SPEC_URL = "https://www.rfc-editor.org/rfc/rfc9449.html"
SA9D_DPOP_SPEC_VERSION = "RFC9449"
SA9D_SPACES_PROPOSAL_COMMIT = PROPOSAL_COMMIT
SA9D_OAUTH_PROFILE = "atproto-oauth-observed-2026-08-21+spaces-alpha-54c9cf5"
SA9D_DPOP_METHOD = "fixture-es256+rfc9449-protected-resource-binding"
SA9D_DPOP_VERSION = "sa9d-a-v1"
SA9D_SOURCE_VECTOR_FORMAT = "spaces-alpha-sa9d-a-oauth-dpop-vector-v1"
SA9D_FIXTURE_SHA256 = "38c9c204e01948852831e78b448985f5495624eee8e6893e5cf6b85646aef4c8"
SA9D_AUTH_DOCTRINE = (
    "Authentication binds a credential to a request. It does not bind that "
    "request to governance authority."
)
SA9DB_DELEGATION_TOKEN_TYP = "atproto-space-delegation+jwt"
SA9DB_DELEGATION_KEY_ID = "#atproto"
SA9DB_DELEGATION_LIFETIME_SECONDS = 60
SA9DB_DELEGATION_METHOD = "compact-jwt+account-key+oauth-read+dpop-request-binding"
SA9DB_DELEGATION_VERSION = "sa9d-b-v1"
SA9DB_SOURCE_VECTOR_FORMAT = "spaces-alpha-sa9d-b-delegation-vector-v1"
SA9DB_FIXTURE_SHA256 = (
    "ac1db8730abf43c4b91e3d03e01ee34f51cb710cb24a5002b7515a202c595be0"
)
SA9DB_DELEGATION_DOCTRINE = (
    "Delegation proves only that the user's PDS delegated this application to "
    "request access to this exact Space. It is not a Space authority admission "
    "decision."
)
SA9DC_CREDENTIAL_TYP = "atproto-space-credential+jwt"
SA9DC_CREDENTIAL_LIFETIME_SECONDS = 7200
SA9DC_CREDENTIAL_METHOD = "compact-jwt+space-authority-key+cnf-jkt+delegation-context"
SA9DC_CREDENTIAL_VERSION = "sa9d-c-v1"
SA9DC_SOURCE_VECTOR_FORMAT = "spaces-alpha-sa9d-c-credential-vector-v1"
SA9DC_FIXTURE_SHA256 = (
    "af024a97b619bc4ec2dee72ac2e085b7bd4086dfcb1db447dd4420bc86e8c8ba"
)
SA9DC_CREDENTIAL_DOCTRINE = (
    "A qualified Space credential is protocol access evidence, not community "
    "standing or governance authority."
)
SA9DD_AUTHENTICATED_ACQUISITION_METHOD = (
    "credential-dpop-get+explicit-nonce-attempt+bounded-stdlib-http"
)
SA9DD_AUTHENTICATED_ACQUISITION_VERSION = "sa9d-d-v1"
SA9DD_AUTHENTICATED_ACQUISITION_DOCTRINE = (
    "Authenticated transport changes acquisition provenance, not artifact meaning."
)
SA9DD_SOURCE_VECTOR_FORMAT = "spaces-alpha-sa9d-d-authenticated-acquisition-v1"
SA9DD_FIXTURE_SHA256 = (
    "4d4081034b4ee71c5cfc289d7deed4dc9e2776e09c2aa0e23200e285314609a0"
)
SA10A_EMPTY_STATE_METHOD = "sa1-qualified-empty-index+state-level-receipt"
SA10A_EMPTY_STATE_VERSION = "sa10a-v1"
SA10B_SYNC_STORE_VERSION = "sa10b-v1"
SA10B_SYNC_STORE_DOCTRINE = (
    "Persistence records evidence; restart and retry do not manufacture confidence."
)
SA10C_HOST_MIGRATION_VERSION = "sa10c-v1"
SA10C_HOST_MIGRATION_METHOD = "ordered-sa9c-provenance+sa9b-service-binding-epochs"
SA10D_OBSERVER_VERSION = "sa10d-v1"
SA10D_OBSERVER_METHOD = (
    "sa9c-sa9b-identity+sa9dd-acquisition+sa2-sa8-qualification+sa10b-custody"
)
SA10D_OBSERVER_DOCTRINE = (
    "Composition preserves claim boundaries; it does not amplify them."
)
ATPROTO_PDS_FRAGMENT = "atproto_pds"
ATPROTO_PDS_SERVICE_TYPE = "AtprotoPersonalDataServer"
ATPROTO_ACCOUNT_KEY_FRAGMENT = "atproto"
ATPROTO_SPACE_HOST_FRAGMENT = "atproto_space_host"
ATPROTO_SPACE_KEY_FRAGMENT = "atproto_space"
XRPC_PATH_PREFIX = "/xrpc/"
CAR_VERSION = 1
CAR_ROOT_COUNT = 2
CAR_DAG_CBOR_CODEC = 0x71
CAR_SHA256_MULTIHASH = 0x12
CAR_SHA256_DIGEST_BYTES = 32
LTHASH_STATE_BYTES = 2048
SUPPORTED_SIGNATURE_ALGORITHMS = frozenset({"ES256K"})
WRITER_SET_ENDPOINT = "com.atproto.space.listRepos"
FULL_REPO_ENDPOINT = "com.atproto.space.getRepo"
INCREMENTAL_ENDPOINT = "com.atproto.space.listRepoOps"
LATEST_COMMIT_ENDPOINT = "com.atproto.space.getLatestCommit"
NOTIFICATION_ENDPOINT = "com.atproto.space.notifyWrite"
DELEGATION_TOKEN_ENDPOINT = "com.atproto.space.getDelegationToken"

ENDPOINTS = MappingProxyType(
    {
        "writer_set": WRITER_SET_ENDPOINT,
        "full_repo": FULL_REPO_ENDPOINT,
        "incremental": INCREMENTAL_ENDPOINT,
        "latest_commit": LATEST_COMMIT_ENDPOINT,
        "notification": NOTIFICATION_ENDPOINT,
        "delegation_token": DELEGATION_TOKEN_ENDPOINT,
    }
)

# A verifier adapter must make every one of these narrow claims before this
# package admits a record as Space evidence.  In particular there is no MST
# claim: permissioned repos use an LtHash set digest and a deniable commit.
REQUIRED_REPO_VERIFICATION_CLAIMS = frozenset(
    {
        "author_signature_context",
        "commit_mac",
        "lthash_record_set",
        "record_cids",
        "space_context",
    }
)

# The proposal explicitly says omitted OAuth collections are dynamically
# resolved from the current Space type declaration.  This is recorded here so
# governed code can freeze the effective set instead of inheriting mutation.
BARE_SCOPE_COLLECTIONS_ARE_DYNAMIC = True

__all__ = [
    "ALPHA_DATE",
    "ALPHA_LABEL",
    "ANNOUNCEMENT_URL",
    "ATPROTO_ACCOUNT_KEY_FRAGMENT",
    "ATPROTO_PDS_FRAGMENT",
    "ATPROTO_PDS_SERVICE_TYPE",
    "ATPROTO_SPACE_HOST_FRAGMENT",
    "ATPROTO_SPACE_KEY_FRAGMENT",
    "BARE_SCOPE_COLLECTIONS_ARE_DYNAMIC",
    "BULLETIN_ALPHA_PACKAGE_COMMIT",
    "BULLETIN_COMMIT",
    "BULLETIN_URL",
    "CAR_DAG_CBOR_CODEC",
    "CAR_ROOT_COUNT",
    "CAR_SHA256_DIGEST_BYTES",
    "CAR_SHA256_MULTIHASH",
    "CAR_VERSION",
    "COMMIT_CONTEXT_TAG",
    "COMMIT_FORMAT",
    "DELEGATION_TOKEN_ENDPOINT",
    "ENDPOINTS",
    "FULL_REPO_ENDPOINT",
    "INCREMENTAL_ENDPOINT",
    "LATEST_COMMIT_ENDPOINT",
    "NOTIFICATION_ENDPOINT",
    "LTHASH_STATE_BYTES",
    "PERMISSIONED_REPO_PROOF_KIND",
    "PROPOSAL_COMMIT",
    "PROPOSAL_URL",
    "REFERENCE_COMMIT",
    "REFERENCE_URL",
    "REQUIRED_REPO_VERIFICATION_CLAIMS",
    "PUBLIC_REPO_PROOF_KIND",
    "SA1_VERIFICATION_METHOD",
    "SA1_VERIFIER_VERSION",
    "SA2_CAR_ADAPTER_VERSION",
    "SA2_CAR_METHOD",
    "SA2_REFERENCE_COMMIT",
    "SA2_SOURCE_VECTOR_FORMAT",
    "SA3_INTEROP_METHOD",
    "SA3_INTEROP_VERSION",
    "SA3_QUALIFICATION_RECEIPT_IDS",
    "SA3_REFERENCE_ARTIFACT_SHA256",
    "SA3_REFERENCE_COMMIT",
    "SA3_REFERENCE_IMPLEMENTATION",
    "SA3_REFERENCE_PACKAGE_VERSION",
    "SA3_REFERENCE_VECTOR_FORMAT",
    "SA3_SOURCE_VECTOR_IDENTIFIER",
    "SA4_REFERENCE_COMMIT",
    "SA4_REFERENCE_ARTIFACT_SHA256",
    "SA4_REFERENCE_DRIVER_SHA256",
    "SA4_REFERENCE_IMPLEMENTATION",
    "SA4_REFERENCE_MANIFEST_SHA256",
    "SA4_REFERENCE_OPERATION_SHA256",
    "SA4_REFERENCE_PACKAGE_VERSION",
    "SA4_REFERENCE_SOURCE_SHA256",
    "SA4_REFERENCE_VECTOR_FORMAT",
    "SA4_SOURCE_VECTOR_FORMAT",
    "SA4_TRANSITION_METHOD",
    "SA4_TRANSITION_RECEIPT_IDS",
    "SA4_TRANSITION_VERSION",
    "SA5_ACQUISITION_METHOD",
    "SA5_ADAPTER_VERSION",
    "SA5_SOURCE_VECTOR_FORMAT",
    "SA6_RECONCILIATION_METHOD",
    "SA6_RECONCILER_VERSION",
    "SA6_SOURCE_VECTOR_FORMAT",
    "SA7_TRANSPORT_BOUNDARY_VERSION",
    "SA8_RECOVERY_DOCTRINE",
    "SA8_RECOVERY_METHOD",
    "SA8_RECOVERY_VERSION",
    "SA8_SOURCE_VECTOR_FORMAT",
    "SA9A_HTTP_DOCTRINE",
    "SA9A_HTTP_METHOD",
    "SA9A_HTTP_VERSION",
    "SA9A_SOURCE_VECTOR_FORMAT",
    "SA9B_BINDING_DOCTRINE",
    "SA9B_BINDING_METHOD",
    "SA9B_BINDING_VERSION",
    "SA9B_DID_SPEC_OBSERVED_DATE",
    "SA9B_DID_SPEC_URL",
    "SA9B_SOURCE_VECTOR_FORMAT",
    "SA9C_AUTHORITY_DOCTRINE",
    "SA9C_DID_SPEC_OBSERVED_DATE",
    "SA9C_DID_SPEC_URL",
    "SA9C_PLC_METHOD",
    "SA9C_PLC_REFERENCE_COMMIT",
    "SA9C_PLC_REFERENCE_DRIVER_SHA256",
    "SA9C_PLC_REFERENCE_FIXTURE_SHA256",
    "SA9C_PLC_REFERENCE_URL",
    "SA9C_PLC_SPEC_URL",
    "SA9C_PLC_SPEC_VERSION",
    "SA9C_PLC_VERSION",
    "SA9C_RESOLUTION_DOCTRINE",
    "SA9C_SOURCE_VECTOR_FORMAT",
    "SA9C_WEB_METHOD",
    "SA9C_WEB_SPEC_OBSERVED_DATE",
    "SA9C_WEB_SPEC_URL",
    "SA9C_WEB_VERSION",
    "SA9D_AUTH_DOCTRINE",
    "SA9D_DPOP_METHOD",
    "SA9D_DPOP_SPEC_URL",
    "SA9D_DPOP_SPEC_VERSION",
    "SA9D_DPOP_VERSION",
    "SA9D_FIXTURE_SHA256",
    "SA9D_OAUTH_PROFILE",
    "SA9D_OAUTH_SPEC_OBSERVED_DATE",
    "SA9D_OAUTH_SPEC_URL",
    "SA9D_SOURCE_VECTOR_FORMAT",
    "SA9D_SPACES_PROPOSAL_COMMIT",
    "SA9DB_DELEGATION_DOCTRINE",
    "SA9DB_DELEGATION_KEY_ID",
    "SA9DB_DELEGATION_LIFETIME_SECONDS",
    "SA9DB_DELEGATION_METHOD",
    "SA9DB_DELEGATION_TOKEN_TYP",
    "SA9DB_DELEGATION_VERSION",
    "SA9DB_FIXTURE_SHA256",
    "SA9DB_SOURCE_VECTOR_FORMAT",
    "SA9DC_CREDENTIAL_DOCTRINE",
    "SA9DC_CREDENTIAL_LIFETIME_SECONDS",
    "SA9DC_CREDENTIAL_METHOD",
    "SA9DC_CREDENTIAL_TYP",
    "SA9DC_CREDENTIAL_VERSION",
    "SA9DC_FIXTURE_SHA256",
    "SA9DC_SOURCE_VECTOR_FORMAT",
    "SOURCE_VECTOR_FORMAT",
    "SPACE_URI_MARKER",
    "SUPPORTED_SIGNATURE_ALGORITHMS",
    "WRITER_SET_ENDPOINT",
    "XRPC_PATH_PREFIX",
]
