from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from community_model import RecordRef, canonical_json_bytes, cid_for_dag_cbor
from communityd.config import DaemonConfig
from communityd.fakes import (
    FakeAdminAuthorizer,
    FakeAuthorityLedgerReader,
    FakeAuthorityWriter,
    FakeCredentialProvider,
    FakeRecordReader,
    FakeRepoState,
)
from communityd.operations import DaemonPorts

ROOT = Path(__file__).resolve().parents[3]
COMMUNITY_DID = "did:web:community.invalid"
ADMIN_DID = "did:web:admin.invalid"
ALICE_DID = "did:web:alice.invalid"
POST_RKEY = "3jzfcijpj2z2a"
SUBMISSION_RKEY = "3jzfcijpj2z2b"
ALLOWED_UID = 4242
CREDENTIAL_REF = "fake://communityd-admin"
BASE_TIME = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)

POST_COLLECTION = "app.bsky.feed.post"
SUBMISSION_COLLECTION = "app.phlogiston.community.submit"


def mint_cid(record: dict[str, object]) -> str:
    return cid_for_dag_cbor(canonical_json_bytes(record))


def make_post(text: str = "Tiny computers, loud fans.") -> dict[str, object]:
    return {
        "$type": POST_COLLECTION,
        "text": text,
        "createdAt": "2026-08-13T11:59:00Z",
    }


def make_submission(subject: RecordRef) -> dict[str, object]:
    return {
        "$type": SUBMISSION_COLLECTION,
        "community": COMMUNITY_DID,
        "subject": subject.as_dict(),
        "createdAt": "2026-08-13T11:59:30Z",
    }


def make_config() -> DaemonConfig:
    return DaemonConfig(
        community_did=COMMUNITY_DID,
        administrator_did=ADMIN_DID,
        community_pds_url="https://pds.invalid",
        allowed_uid=ALLOWED_UID,
        reader_adapter="fake",
        ledger_adapter="fake",
        writer_adapter="fake",
        credential_provider="fake",
        credential_ref=CREDENTIAL_REF,
    )


def make_ports(
    state: FakeRepoState,
    *,
    effective_uid: int = ALLOWED_UID,
    credentials: dict[str, str] | None = None,
) -> DaemonPorts:
    return DaemonPorts(
        reader=FakeRecordReader(state),
        ledger=FakeAuthorityLedgerReader(state),
        authorizer=FakeAdminAuthorizer(
            administrator_did=ADMIN_DID,
            allowed_uid=ALLOWED_UID,
            effective_uid=effective_uid,
        ),
        writer=FakeAuthorityWriter(state),
        credentials=FakeCredentialProvider(
            {CREDENTIAL_REF: "fake-handle"} if credentials is None else credentials
        ),
    )


def seed_author_repo(
    state: FakeRepoState, *, text: str = "Tiny computers, loud fans."
) -> tuple[RecordRef, RecordRef]:
    """Seed Alice's post and exact self-submission; return both references."""

    post = make_post(text)
    post_ref = state.seed(ALICE_DID, POST_COLLECTION, POST_RKEY, post)
    submission = make_submission(post_ref)
    submission_ref = state.seed(
        ALICE_DID, SUBMISSION_COLLECTION, SUBMISSION_RKEY, submission
    )
    return post_ref, submission_ref


def write_config(tmp_path: Path, body: str | None = None) -> Path:
    if body is None:
        body = (
            f'community_did = "{COMMUNITY_DID}"\n'
            f'administrator_did = "{ADMIN_DID}"\n'
            'community_pds_url = "https://pds.invalid"\n'
            f"allowed_uid = {ALLOWED_UID}\n"
            'reader_adapter = "fake"\n'
            'ledger_adapter = "fake"\n'
            'writer_adapter = "fake"\n'
            'credential_provider = "fake"\n'
            f'credential_ref = "{CREDENTIAL_REF}"\n'
        )
    path = tmp_path / "communityd.toml"
    path.write_text(body, encoding="utf-8")
    return path
