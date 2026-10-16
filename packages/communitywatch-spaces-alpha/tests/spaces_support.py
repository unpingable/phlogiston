from __future__ import annotations

import base64
import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from community_model import cid_for_dag_cbor, encode_dag_cbor
from communitywatch_spaces_alpha import (
    AccessContext,
    QualificationSourceContext,
    ReferenceBlockExpectation,
    ReferenceCarExpectation,
    RepoBinding,
    RepoOperation,
    RepoRecord,
    RepoSnapshot,
    RepoTransition,
    RepoVerification,
    SpaceIdentity,
    SpaceNotification,
    SpaceRecordBlock,
    SpaceRecordIdentity,
    SpaceRepoEvidence,
    WriterSetClaim,
    extract_space_repo_evidence,
    parse_list_repo_ops_page,
    qualify_repo_state,
    qualify_repo_transition,
)

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "spaces-alpha"
    / "campaign.json"
)
SA1_FIXTURE = FIXTURE.with_name("sa1-qualification.json")
SA2_FIXTURE = FIXTURE.with_name("sa2-car.json")
SA3_FIXTURE = FIXTURE.with_name("sa3-reference.json")
SA3_CAR = FIXTURE.parent / "reference" / "sa3-golden.car"
SA4_SOURCE_FIXTURE = FIXTURE.with_name("sa4-source.json")
SA4_FIXTURE = FIXTURE.with_name("sa4-transition.json")
SA5_FIXTURE = FIXTURE.with_name("sa5-list-repo-ops.json")
SA6_FIXTURE = FIXTURE.with_name("sa6-reconciliation.json")
SA8_FIXTURE = FIXTURE.with_name("sa8-recovery.json")
SA9A_FIXTURE = FIXTURE.with_name("sa9a-http.json")
SA9B_FIXTURE = FIXTURE.with_name("sa9b-did-binding.json")
SA4_REFERENCE_DIR = FIXTURE.parent / "reference"


def load_campaign() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def load_sa1() -> dict[str, object]:
    return json.loads(SA1_FIXTURE.read_text(encoding="utf-8"))


def load_sa2() -> dict[str, object]:
    return json.loads(SA2_FIXTURE.read_text(encoding="utf-8"))


def load_sa3() -> dict[str, object]:
    return json.loads(SA3_FIXTURE.read_text(encoding="utf-8"))


def load_sa4_source() -> dict[str, object]:
    return json.loads(SA4_SOURCE_FIXTURE.read_text(encoding="utf-8"))


def load_sa4() -> dict[str, object]:
    return json.loads(SA4_FIXTURE.read_text(encoding="utf-8"))


def load_sa5() -> dict[str, object]:
    return json.loads(SA5_FIXTURE.read_text(encoding="utf-8"))


def load_sa6() -> dict[str, object]:
    return json.loads(SA6_FIXTURE.read_text(encoding="utf-8"))


def load_sa8() -> dict[str, object]:
    return json.loads(SA8_FIXTURE.read_text(encoding="utf-8"))


def load_sa9a() -> dict[str, object]:
    return json.loads(SA9A_FIXTURE.read_text(encoding="utf-8"))


def load_sa9b() -> dict[str, object]:
    return json.loads(SA9B_FIXTURE.read_text(encoding="utf-8"))


def sa9b_document_bytes(document: dict[str, object], name: str) -> bytes:
    documents = document["documents"]
    assert isinstance(documents, dict)
    value = documents[name]
    assert isinstance(value, dict)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()


def sa5_case(document: dict[str, object], name: str) -> dict[str, object]:
    case = document[name]
    assert isinstance(case, dict)
    return case


def sa5_pages(document: dict[str, object], name: str):
    case = sa5_case(document, name)
    pages = case["pages"]
    assert isinstance(pages, list)
    result = []
    for ordinal, raw_page in enumerate(pages):
        assert isinstance(raw_page, dict)
        response = raw_page["response"]
        assert isinstance(response, dict)
        result.append(
            parse_list_repo_ops_page(
                response,
                ordinal=ordinal,
                request_since=str(raw_page["requestSince"]),
                request_cursor=(
                    str(raw_page["requestCursor"])
                    if raw_page["requestCursor"] is not None
                    else None
                ),
                received_at=timestamp(str(raw_page["receivedAt"])),
            )
        )
    return tuple(result)


def sa5_responses(
    document: dict[str, object], name: str
) -> tuple[dict[str, object], ...]:
    """Return detached wire-shaped responses without applying SA5 semantics."""

    case = sa5_case(document, name)
    pages = case["pages"]
    assert isinstance(pages, list)
    responses = []
    for raw_page in pages:
        assert isinstance(raw_page, dict)
        response = raw_page["response"]
        assert isinstance(response, dict)
        responses.append(deepcopy(response))
    return tuple(responses)


def _b64(value: object) -> bytes:
    assert isinstance(value, str)
    return base64.b64decode(value, validate=True)


def sa2_car(document: dict[str, object], name: str = "car1") -> bytes:
    section = document["valid"]
    assert isinstance(section, dict)
    raw = section[name]
    assert isinstance(raw, dict)
    return _b64(raw["carB64"])


def sa2_hostile_car(document: dict[str, object], name: str) -> bytes:
    section = document["hostile"]
    assert isinstance(section, dict)
    return _b64(section[name])


def sa3_car(document: dict[str, object]) -> bytes:
    artifact = document["artifact"]
    assert isinstance(artifact, dict)
    raw = SA3_CAR.read_bytes()
    assert raw == _b64(artifact["carB64"])
    return raw


def sa3_expectation(document: dict[str, object]) -> ReferenceCarExpectation:
    artifact = document["artifact"]
    generator = document["generator"]
    interpretation = document["referenceInterpretation"]
    local = document["localExpectation"]
    assert isinstance(artifact, dict)
    assert isinstance(generator, dict)
    assert isinstance(interpretation, dict)
    assert isinstance(local, dict)
    raw_blocks = interpretation["blocks"]
    raw_roots = interpretation["roots"]
    raw_receipts = local["sa1QualificationReceiptIds"]
    assert isinstance(raw_blocks, list)
    assert isinstance(raw_roots, list)
    assert isinstance(raw_receipts, list)
    return ReferenceCarExpectation(
        format=str(document["format"]),
        generator_implementation=str(generator["implementation"]),
        generator_package_version=str(generator["packageVersion"]),
        generator_commit=str(generator["commit"]),
        local_adapter_version=str(local["adapterVersion"]),
        local_interop_version=str(local["interoperabilityVersion"]),
        raw_car_sha256=str(artifact["rawSha256"]),
        roots=tuple(str(root) for root in raw_roots),
        blocks=tuple(
            ReferenceBlockExpectation(
                ordinal=int(block["ordinal"]),
                cid=str(block["cid"]),
                codec=int(block["codec"]),
                multihash_code=int(block["multihashCode"]),
                block_bytes=_b64(block["bytesB64"]),
            )
            for block in raw_blocks
            if isinstance(block, dict)
        ),
        source_vector_identifier=str(local["sourceVectorIdentifier"]),
        qualification_receipt_ids=tuple(str(item) for item in raw_receipts),
    )


def _sa4_named(items: object, name: str) -> dict[str, object]:
    assert isinstance(items, list)
    for item in items:
        if isinstance(item, dict) and item.get("name") == name:
            return item
    raise AssertionError(f"missing SA4 item {name}")


def sa4_state_source(document: dict[str, object], name: str) -> dict[str, object]:
    return _sa4_named(document["states"], name)


def sa4_transition_source(document: dict[str, object], name: str) -> dict[str, object]:
    return _sa4_named(document["transitions"], name)


def sa4_manifest_state(document: dict[str, object], name: str) -> dict[str, object]:
    states = document["states"]
    assert isinstance(states, dict)
    state = states[name]
    assert isinstance(state, dict)
    return state


def sa4_car(document: dict[str, object], name: str) -> bytes:
    state = sa4_manifest_state(document, name)
    return (SA4_REFERENCE_DIR / str(state["artifact"])).read_bytes()


def sa4_space(document: dict[str, object]) -> SpaceIdentity:
    expected = document["expected"]
    assert isinstance(expected, dict)
    raw = expected["space"]
    assert isinstance(raw, dict)
    return SpaceIdentity(
        authority_did=str(raw["authorityDid"]),
        space_type=str(raw["spaceType"]),
        skey=str(raw["skey"]),
    )


def sa4_author(document: dict[str, object]) -> str:
    expected = document["expected"]
    assert isinstance(expected, dict)
    return str(expected["authorDid"])


def sa4_public_key(document: dict[str, object]) -> bytes:
    expected = document["expected"]
    assert isinstance(expected, dict)
    return _b64(expected["authorPublicKeyB64"])


def sa4_algorithm(document: dict[str, object]) -> str:
    expected = document["expected"]
    assert isinstance(expected, dict)
    return str(expected["signatureAlgorithm"])


def sa4_source_context(document: dict[str, object]) -> QualificationSourceContext:
    raw = document["sourceContext"]
    assert isinstance(raw, dict)
    return QualificationSourceContext(
        repo_host=str(raw["repoHost"]),
        author_key_ref=str(raw["authorKeyRef"]),
        author_key_binding_method=str(raw["authorKeyBindingMethod"]),
        evidence_ref=str(raw["evidenceRef"]),
        writer_discovery_ref=str(raw["writerDiscoveryRef"]),
    )


def sa4_evidence(
    source_document: dict[str, object],
    manifest: dict[str, object],
    state_name: str,
    *,
    transition_name: str | None = None,
) -> SpaceRepoEvidence:
    state = sa4_manifest_state(manifest, state_name)
    extraction = extract_space_repo_evidence(
        sa4_car(manifest, state_name),
        source_vector_identifier=str(state["sourceVectorIdentifier"]),
    )
    if transition_name is None:
        return extraction.evidence
    raw_transition = sa4_transition_source(source_document, transition_name)
    source_name = str(raw_transition["source"])
    target_name = str(raw_transition["target"])
    assert target_name == state_name
    prior = sa4_state_source(source_document, source_name)
    raw_operations = raw_transition["operations"]
    raw_index = prior["index"]
    assert isinstance(raw_operations, list) and isinstance(raw_index, dict)
    transition = RepoTransition(
        prior_rev=str(prior["rev"]),
        prior_state=_b64(prior["lthashStateB64"]),
        prior_index={str(path): str(cid) for path, cid in raw_index.items()},
        operations=tuple(
            RepoOperation(
                rev=str(operation["rev"]),
                collection=str(operation["collection"]),
                rkey=str(operation["rkey"]),
                cid=str(operation["cid"]) if operation["cid"] is not None else None,
                prev=(
                    str(operation["prev"]) if operation["prev"] is not None else None
                ),
            )
            for operation in raw_operations
            if isinstance(operation, dict)
        ),
    )
    return SpaceRepoEvidence(
        source_vector_identifier=extraction.evidence.source_vector_identifier,
        proof_kind=extraction.evidence.proof_kind,
        protocol_assumption=extraction.evidence.protocol_assumption,
        commit_bytes=extraction.evidence.commit_bytes,
        index_bytes=extraction.evidence.index_bytes,
        record_blocks=extraction.evidence.record_blocks,
        transition=transition,
    )


def _uvarint(value: int) -> bytes:
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _cid_bytes(cid: str) -> bytes:
    encoded = cid[1:].upper()
    return base64.b32decode(encoded + "=" * ((8 - len(encoded) % 8) % 8))


def space_car_from_evidence(evidence: SpaceRepoEvidence) -> bytes:
    """Build deterministic CARv1 fixture bytes from pre-separated SA1 evidence."""

    commit_cid = cid_for_dag_cbor(evidence.commit_bytes)
    index_cid = cid_for_dag_cbor(evidence.index_bytes)
    header = encode_dag_cbor(
        {
            "roots": ({"$link": commit_cid}, {"$link": index_cid}),
            "version": 1,
        }
    )
    result = bytearray(_uvarint(len(header)) + header)
    blocks = (
        (commit_cid, evidence.commit_bytes),
        (index_cid, evidence.index_bytes),
        *((record.cid, record.record_bytes) for record in evidence.record_blocks),
    )
    for cid, block_bytes in blocks:
        section = _cid_bytes(cid) + block_bytes
        result.extend(_uvarint(len(section)))
        result.extend(section)
    return bytes(result)


def qualified_sa4_snapshot(
    source_document: dict[str, object],
    manifest: dict[str, object],
    state_name: str,
    verified_at: str,
):
    return qualify_repo_state(
        sa4_evidence(source_document, manifest, state_name),
        expected_space=sa4_space(source_document),
        expected_author_did=sa4_author(source_document),
        author_public_key=sa4_public_key(source_document),
        signature_algorithm=sa4_algorithm(source_document),
        source=sa4_source_context(source_document),
        verified_at=timestamp(verified_at),
    )


def qualified_sa4_transition(
    source_state,
    source_document: dict[str, object],
    manifest: dict[str, object],
    target_name: str,
    transition_name: str,
    verified_at: str,
):
    return qualify_repo_transition(
        source_state,
        sa4_evidence(
            source_document,
            manifest,
            target_name,
            transition_name=transition_name,
        ),
        expected_space=sa4_space(source_document),
        expected_author_did=sa4_author(source_document),
        author_public_key=sa4_public_key(source_document),
        signature_algorithm=sa4_algorithm(source_document),
        source=sa4_source_context(source_document),
        verified_at=timestamp(verified_at),
    )


def sa1_space(document: dict[str, object], *, hostile: bool = False) -> SpaceIdentity:
    expected = document["expected"]
    assert isinstance(expected, dict)
    if hostile:
        hostile_values = document["hostile"]
        assert isinstance(hostile_values, dict)
        raw = hostile_values["c4WrongSpace"]
    else:
        raw = expected["space"]
    assert isinstance(raw, dict)
    return SpaceIdentity(
        authority_did=str(raw["authorityDid"]),
        space_type=str(raw["spaceType"]),
        skey=str(raw["skey"]),
    )


def sa1_author(document: dict[str, object]) -> str:
    expected = document["expected"]
    assert isinstance(expected, dict)
    return str(expected["authorDid"])


def sa1_public_key(document: dict[str, object]) -> bytes:
    expected = document["expected"]
    assert isinstance(expected, dict)
    return _b64(expected["authorPublicKeyB64"])


def sa1_algorithm(document: dict[str, object]) -> str:
    expected = document["expected"]
    assert isinstance(expected, dict)
    return str(expected["signatureAlgorithm"])


def sa1_source(document: dict[str, object]) -> QualificationSourceContext:
    raw = document["sourceContext"]
    assert isinstance(raw, dict)
    return QualificationSourceContext(
        repo_host=str(raw["repoHost"]),
        author_key_ref=str(raw["authorKeyRef"]),
        author_key_binding_method=str(raw["authorKeyBindingMethod"]),
        evidence_ref=str(raw["evidenceRef"]),
        writer_discovery_ref=str(raw["writerDiscoveryRef"]),
    )


def _sa1_raw_vector(
    document: dict[str, object], name: str, *, hostile: bool = False
) -> dict[str, object]:
    section = document["hostile" if hostile else "valid"]
    assert isinstance(section, dict)
    raw = section[name]
    assert isinstance(raw, dict)
    return raw


def sa1_evidence(
    document: dict[str, object], name: str, *, hostile: bool = False
) -> SpaceRepoEvidence:
    raw = _sa1_raw_vector(document, name, hostile=hostile)
    blocks: list[SpaceRecordBlock] = []
    for item in raw.get("recordBlocks", []):
        assert isinstance(item, dict)
        blocks.append(
            SpaceRecordBlock(
                collection=str(item["collection"]),
                rkey=str(item["rkey"]),
                cid=str(item["cid"]),
                record_bytes=_b64(item["bytesB64"]),
            )
        )
    transition = None
    raw_transition = raw.get("transition")
    if raw_transition is not None:
        assert isinstance(raw_transition, dict)
        raw_operations = raw_transition["operations"]
        raw_index = raw_transition["priorIndex"]
        assert isinstance(raw_operations, list) and isinstance(raw_index, dict)
        transition = RepoTransition(
            prior_rev=str(raw_transition["priorRev"]),
            prior_state=_b64(raw_transition["priorStateB64"]),
            prior_index={str(key): str(value) for key, value in raw_index.items()},
            operations=tuple(
                RepoOperation(
                    rev=str(item["rev"]),
                    collection=str(item["collection"]),
                    rkey=str(item["rkey"]),
                    cid=str(item["cid"]) if item["cid"] is not None else None,
                    prev=str(item["prev"]) if item["prev"] is not None else None,
                )
                for item in raw_operations
                if isinstance(item, dict)
            ),
        )
    return SpaceRepoEvidence(
        source_vector_identifier=str(raw["sourceVectorIdentifier"]),
        proof_kind=str(raw["proofKind"]),
        protocol_assumption=str(raw["protocolAssumption"]),
        commit_bytes=_b64(raw["commitB64"]) if "commitB64" in raw else b"",
        index_bytes=_b64(raw["indexB64"]) if "indexB64" in raw else b"",
        record_blocks=tuple(blocks),
        transition=transition,
    )


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def space(document: dict[str, object]) -> SpaceIdentity:
    raw = document["space"]
    assert isinstance(raw, dict)
    return SpaceIdentity(
        authority_did=str(raw["authorityDid"]),
        space_type=str(raw["spaceType"]),
        skey=str(raw["skey"]),
    )


def other_space(document: dict[str, object]) -> SpaceIdentity:
    hostile = document["hostile"]
    assert isinstance(hostile, dict)
    raw = hostile["wrongSpace"]
    assert isinstance(raw, dict)
    return SpaceIdentity(
        authority_did=str(raw["authorityDid"]),
        space_type=str(raw["spaceType"]),
        skey=str(raw["skey"]),
    )


def access(document: dict[str, object]) -> AccessContext:
    raw = document["access"]
    assert isinstance(raw, dict)
    return AccessContext(
        space=space(document),
        issuer_did=str(raw["issuerDid"]),
        user_did=str(raw["userDid"]),
        client_id=str(raw["clientId"]),
        issued_at=timestamp(str(raw["issuedAt"])),
        expires_at=timestamp(str(raw["expiresAt"])),
        verified_at=timestamp(str(raw["verifiedAt"])),
    )


def _repo(document: dict[str, object]) -> dict[str, object]:
    raw = document["repo"]
    assert isinstance(raw, dict)
    return raw


def _state(document: dict[str, object], name: str) -> dict[str, object]:
    states = document["states"]
    assert isinstance(states, dict)
    raw = states[name]
    assert isinstance(raw, dict)
    return raw


def claim(
    document: dict[str, object],
    state_name: str,
    *,
    target_space: SpaceIdentity | None = None,
    commit_hash: str | None = None,
) -> WriterSetClaim:
    raw_space = document["space"]
    assert isinstance(raw_space, dict)
    raw_state = _state(document, state_name)
    raw_repo = _repo(document)
    return WriterSetClaim(
        space=target_space or space(document),
        space_host=str(raw_space["spaceHost"]),
        repo_did=str(raw_repo["authorDid"]),
        rev=str(raw_state["rev"]),
        commit_hash=commit_hash or str(raw_state["hash"]),
        discovered_at=timestamp(str(raw_state["discoveredAt"])),
    )


def binding(
    document: dict[str, object],
    *,
    target_space: SpaceIdentity | None = None,
    repo_did: str | None = None,
    repo_host: str | None = None,
) -> RepoBinding:
    raw = _repo(document)
    return RepoBinding(
        space=target_space or space(document),
        repo_did=repo_did or str(raw["authorDid"]),
        repo_host=repo_host or str(raw["repoHost"]),
        resolved_at=timestamp("2026-08-20T14:00:01Z"),
        resolution_method=str(raw["bindingMethod"]),
        evidence_ref=str(raw["bindingEvidence"]),
    )


def snapshot(
    document: dict[str, object],
    state_name: str,
    *,
    target_space: SpaceIdentity | None = None,
    snapshot_author: str | None = None,
    record_author: str | None = None,
    repo_host: str | None = None,
    verification_claims: frozenset[str] | None = None,
    access_context: AccessContext | None = None,
) -> RepoSnapshot:
    target = target_space or space(document)
    raw_state = _state(document, state_name)
    raw_repo = _repo(document)
    raw_verification = document["verification"]
    assert isinstance(raw_verification, dict)
    author = snapshot_author or str(raw_repo["authorDid"])
    source_host = repo_host or str(raw_repo["repoHost"])
    records: list[RepoRecord] = []
    raw_records = raw_state["records"]
    assert isinstance(raw_records, list)
    for raw_record in raw_records:
        assert isinstance(raw_record, dict)
        value = deepcopy(raw_record["value"])
        assert isinstance(value, dict)
        records.append(
            RepoRecord(
                identity=SpaceRecordIdentity(
                    space=target,
                    author_did=record_author or author,
                    collection=str(raw_record["collection"]),
                    rkey=str(raw_record["rkey"]),
                ),
                cid=str(raw_record["cid"]),
                record=value,
                record_bytes=encode_dag_cbor(value),
            )
        )
    claims = verification_claims
    if claims is None:
        claims = frozenset(str(item) for item in raw_verification["claims"])
    verification = RepoVerification(
        mode=str(raw_verification["mode"]),
        space=target,
        author_did=author,
        repo_host=source_host,
        rev=str(raw_state["rev"]),
        commit_hash=str(raw_state["hash"]),
        verified_at=timestamp(str(raw_state["acquiredAt"])),
        method=str(raw_verification["method"]),
        verifier_version=str(raw_verification["version"]),
        author_key_ref=str(raw_verification["authorKeyRef"]),
        evidence_ref=f"fixture:spaces-alpha:{state_name}:repo",
        claims=claims,
    )
    return RepoSnapshot(
        space=target,
        author_did=author,
        repo_host=source_host,
        rev=str(raw_state["rev"]),
        commit_hash=str(raw_state["hash"]),
        acquired_at=timestamp(str(raw_state["acquiredAt"])),
        access=access_context or access(document),
        verification=verification,
        records=tuple(records),
    )


def notification(document: dict[str, object]) -> SpaceNotification:
    raw = document["notification"]
    raw_space = document["space"]
    raw_repo = _repo(document)
    assert isinstance(raw, dict) and isinstance(raw_space, dict)
    return SpaceNotification(
        space=space(document),
        space_host=str(raw_space["spaceHost"]),
        repo_did=str(raw_repo["authorDid"]),
        rev=str(raw["rev"]),
        commit_hash=str(raw["hash"]),
        received_at=timestamp(str(raw["receivedAt"])),
    )


@dataclass(slots=True)
class FakeDirectSpaceSource:
    claims: tuple[WriterSetClaim, ...]
    repo_binding: RepoBinding
    repo_snapshot: RepoSnapshot
    calls: list[tuple[str, str]] = field(default_factory=list)

    def list_writer_claims(
        self, requested_space: SpaceIdentity, requested_access: AccessContext
    ) -> tuple[WriterSetClaim, ...]:
        self.calls.append(("listRepos", requested_space.uri))
        assert requested_access.space == requested_space
        return self.claims

    def bind_repo(
        self,
        requested_space: SpaceIdentity,
        repo_did: str,
        requested_access: AccessContext,
    ) -> RepoBinding:
        self.calls.append(("bindRepo", repo_did))
        assert requested_access.space == requested_space
        return self.repo_binding

    def fetch_repo(
        self,
        requested_space: SpaceIdentity,
        repo_did: str,
        requested_access: AccessContext,
    ) -> RepoSnapshot:
        self.calls.append(("getRepo", repo_did))
        assert requested_access.space == requested_space
        return self.repo_snapshot


def fixture_source(
    document: dict[str, object], state_name: str = "initial"
) -> FakeDirectSpaceSource:
    return FakeDirectSpaceSource(
        claims=(claim(document, state_name),),
        repo_binding=binding(document),
        repo_snapshot=snapshot(document, state_name),
    )
