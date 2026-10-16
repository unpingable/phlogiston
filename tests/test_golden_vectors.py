from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from community_model import (
    RecordRef,
    RepoEvent,
    ValidationError,
    decode_dag_cbor,
    deep_freeze,
)
from community_model.canonical import (
    admission_rkey,
    canonical_json_bytes,
    cid_for_dag_cbor,
    event_variant_key,
    payload_hash,
    quarantine_audit_key,
    removal_rkey,
    semantic_event_key,
)

FIXTURES = Path(__file__).parent / "fixtures" / "v0"


def _load_json(relative_path: str) -> object:
    with (FIXTURES / relative_path).open(encoding="utf-8") as handle:
        return json.load(handle)


def _sha256_prefixed(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _decode_fixture_dag_cbor(data: bytes) -> object:
    """Decode the JSON-shaped DAG-CBOR subset used by the frozen fixtures."""

    def read_length(additional: int, cursor: int) -> tuple[int, int]:
        if additional < 24:
            return additional, cursor
        widths = {24: 1, 25: 2, 26: 4, 27: 8}
        width = widths.get(additional)
        if width is None or cursor + width > len(data):
            raise AssertionError("unsupported or truncated fixture CBOR length")
        return int.from_bytes(data[cursor : cursor + width], "big"), cursor + width

    def decode(cursor: int) -> tuple[object, int]:
        if cursor >= len(data):
            raise AssertionError("truncated fixture CBOR")
        initial = data[cursor]
        cursor += 1
        major = initial >> 5
        additional = initial & 0x1F
        if major in {0, 1}:
            value, cursor = read_length(additional, cursor)
            return (value if major == 0 else -1 - value), cursor
        if major in {2, 3}:
            length, cursor = read_length(additional, cursor)
            end = cursor + length
            assert end <= len(data)
            raw = data[cursor:end]
            return (raw if major == 2 else raw.decode("utf-8")), end
        if major == 4:
            length, cursor = read_length(additional, cursor)
            values: list[object] = []
            for _ in range(length):
                item, cursor = decode(cursor)
                values.append(item)
            return values, cursor
        if major == 5:
            length, cursor = read_length(additional, cursor)
            mapping: dict[str, object] = {}
            for _ in range(length):
                key, cursor = decode(cursor)
                assert isinstance(key, str) and key not in mapping
                mapping[key], cursor = decode(cursor)
            return mapping, cursor
        if major == 7 and additional in {20, 21, 22}:
            return {20: False, 21: True, 22: None}[additional], cursor
        raise AssertionError(
            f"unsupported fixture CBOR major/additional: {major}/{additional}"
        )

    decoded, final_cursor = decode(0)
    assert final_cursor == len(data)
    return decoded


def test_canonical_json_has_exact_ordering_and_unicode_bytes() -> None:
    vectors = _load_json("golden-vectors.json")
    assert isinstance(vectors, dict)
    vector = vectors["canonicalJson"]

    expected = bytes.fromhex(vector["utf8Hex"])
    assert canonical_json_bytes(vector["value"]) == expected
    assert payload_hash("observer_json_v0", vector["value"]) == vector["sha256"]
    assert _sha256_prefixed(expected) == vector["sha256"]
    assert "é☃".encode() in expected

    reversed_mapping = {
        "a": vector["value"]["a"],
        "z": vector["value"]["z"],
    }
    assert canonical_json_bytes(reversed_mapping) == expected


def test_canonical_json_rejects_unordered_set_carriers() -> None:
    for carrier in ({"value": {1, 2}}, deep_freeze({"value": {1, 2}})):
        with pytest.raises(ValidationError) as captured:
            canonical_json_bytes(carrier)
        assert captured.value.reason_code == "payload_evidence_invalid"
        assert captured.value.path == ("value",)


def test_canonical_json_is_stable_in_a_fresh_supported_runtime_process() -> None:
    vectors = _load_json("golden-vectors.json")
    assert isinstance(vectors, dict)
    vector = vectors["canonicalJson"]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(
        FIXTURES.parents[2] / "packages/community-model/src"
    )
    program = (
        "from community_model import canonical_json_bytes; "
        f"print(canonical_json_bytes({vector['value']!r}).hex())"
    )
    results = [
        subprocess.run(
            [sys.executable, "-c", program],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout.strip()
        for _ in range(2)
    ]
    assert results == [vector["utf8Hex"], vector["utf8Hex"]]


@pytest.mark.parametrize("bad_number", [float("nan"), float("inf"), -float("inf")])
def test_canonical_json_rejects_non_finite_numbers(bad_number: float) -> None:
    with pytest.raises((TypeError, ValueError)):
        canonical_json_bytes({"value": bad_number})


def test_record_fixtures_pin_observer_json_and_dag_cbor_evidence() -> None:
    manifest = _load_json("record-vectors.json")
    assert isinstance(manifest, dict)

    for vector in manifest["records"]:
        record = _load_json(vector["path"])
        assert isinstance(record, dict)
        assert record["$type"] == vector["collection"]

        canonical = canonical_json_bytes(record)
        assert len(canonical) == vector["observerJson"]["bytes"]
        assert _sha256_prefixed(canonical) == vector["observerJson"]["sha256"]
        assert (
            payload_hash("observer_json_v0", record) == vector["observerJson"]["sha256"]
        )

        dag_cbor = bytes.fromhex(vector["dagCbor"]["hex"])
        assert len(dag_cbor) == vector["dagCbor"]["bytes"]
        assert _decode_fixture_dag_cbor(dag_cbor) == record
        assert decode_dag_cbor(dag_cbor) == record
        assert payload_hash("dag_cbor", dag_cbor) == vector["dagCbor"]["sha256"]
        assert cid_for_dag_cbor(dag_cbor) == vector["dagCbor"]["cid"]


def test_repo_event_binds_dag_cbor_bytes_cid_and_decoded_record() -> None:
    manifest = _load_json("record-vectors.json")
    assert isinstance(manifest, dict)
    vector = next(item for item in manifest["records"] if item["name"] == "submit")
    record = _load_json(vector["path"])
    assert isinstance(record, dict)
    encoded = bytes.fromhex(vector["dagCbor"]["hex"])
    commit_revision = "3jzfcijpj2z2c"
    semantic_key = semantic_event_key(
        repo_did=vector["repoDid"],
        commit_identity=f"rev:{commit_revision}",
        collection=vector["collection"],
        rkey=vector["rkey"],
        operation="create",
    )
    digest = payload_hash("dag_cbor", encoded)
    variant_key = event_variant_key(
        semantic_event_key=semantic_key,
        record_cid=vector["dagCbor"]["cid"],
        payload_hash_scope="dag_cbor",
        payload_hash=digest,
    )
    event = RepoEvent(
        semantic_event_key=semantic_key,
        event_variant_key=variant_key,
        commit_identity=f"rev:{commit_revision}",
        repo_order=commit_revision,
        repo_did=vector["repoDid"],
        operation="create",
        collection=vector["collection"],
        rkey=vector["rkey"],
        record_uri=(
            f"at://{vector['repoDid']}/{vector['collection']}/{vector['rkey']}"
        ),
        record_cid=vector["dagCbor"]["cid"],
        commit_rev=commit_revision,
        commit_cid=None,
        record=record,
        record_bytes=encoded,
        payload_hash=digest,
        payload_hash_scope="dag_cbor",
    )
    assert event.record_cid == vector["dagCbor"]["cid"]

    forged_record = dict(record, createdAt="2026-07-10T14:01:01Z")
    with pytest.raises(ValidationError, match="do not encode the supplied record"):
        replace(event, record=forged_record)

    numeric_bytes = bytes.fromhex("a1617801")
    numeric_cid = cid_for_dag_cbor(numeric_bytes)
    numeric_digest = payload_hash("dag_cbor", numeric_bytes)
    numeric_variant = event_variant_key(
        semantic_event_key=semantic_key,
        record_cid=numeric_cid,
        payload_hash_scope="dag_cbor",
        payload_hash=numeric_digest,
    )
    with pytest.raises(ValidationError, match="do not encode the supplied record"):
        replace(
            event,
            event_variant_key=numeric_variant,
            record_cid=numeric_cid,
            record={"x": True},
            record_bytes=numeric_bytes,
            payload_hash=numeric_digest,
        )


@pytest.mark.parametrize(
    "encoded",
    [
        bytes.fromhex("1b8000000000000000"),
        bytes.fromhex("3b8000000000000000"),
        bytes.fromhex("a2626262f66161f6"),
        b"\x81" * 129 + b"\xf6",
    ],
    ids=("positive-overflow", "negative-overflow", "map-order", "nesting"),
)
def test_dag_cbor_decoder_rejects_noncanonical_or_unsafe_evidence(
    encoded: bytes,
) -> None:
    with pytest.raises(ValidationError) as captured:
        decode_dag_cbor(encoded)
    assert captured.value.reason_code == "payload_evidence_invalid"


def test_fixture_schema_versions_and_record_inventory_are_frozen() -> None:
    records = _load_json("record-vectors.json")
    golden = _load_json("golden-vectors.json")
    assert isinstance(records, dict)
    assert isinstance(golden, dict)

    assert records["schema"] == "v0-record-fixtures-1"
    assert [vector["name"] for vector in records["records"]] == [
        "profile",
        "post",
        "submit",
        "admission",
        "mod_action",
    ]
    assert golden["schema"] == "v0-golden-vectors-1"


def test_fixture_lifecycle_references_exact_record_cids() -> None:
    manifest = _load_json("record-vectors.json")
    assert isinstance(manifest, dict)
    by_name = {item["name"]: item for item in manifest["records"]}

    submit = _load_json(by_name["submit"]["path"])
    admission = _load_json(by_name["admission"]["path"])
    action = _load_json(by_name["mod_action"]["path"])
    assert isinstance(submit, dict)
    assert isinstance(admission, dict)
    assert isinstance(action, dict)

    post_uri = (
        f"at://{by_name['post']['repoDid']}/{by_name['post']['collection']}"
        f"/{by_name['post']['rkey']}"
    )
    assert submit["subject"] == {
        "uri": post_uri,
        "cid": by_name["post"]["dagCbor"]["cid"],
    }
    assert admission["subject"] == submit["subject"]

    submit_uri = (
        f"at://{by_name['submit']['repoDid']}/{by_name['submit']['collection']}"
        f"/{by_name['submit']['rkey']}"
    )
    submission_ref = RecordRef(
        uri=submit_uri,
        cid=by_name["submit"]["dagCbor"]["cid"],
    )
    assert admission["submission"] == {
        "uri": submission_ref.uri,
        "cid": submission_ref.cid,
    }
    assert admission_rkey(submission_ref) == by_name["admission"]["rkey"]

    admission_uri = (
        f"at://{by_name['admission']['repoDid']}/"
        f"{by_name['admission']['collection']}/{by_name['admission']['rkey']}"
    )
    admission_ref = RecordRef(
        uri=admission_uri,
        cid=by_name["admission"]["dagCbor"]["cid"],
    )
    assert action["admission"] == {
        "uri": admission_ref.uri,
        "cid": admission_ref.cid,
    }
    assert action["subject"] == admission["subject"]
    assert removal_rkey(admission_ref) == by_name["mod_action"]["rkey"]


def test_semantic_event_key_exact_bytes() -> None:
    vectors = _load_json("golden-vectors.json")
    assert isinstance(vectors, dict)
    vector = vectors["semanticEvent"]

    assert _sha256_prefixed(bytes.fromhex(vector["inputUtf8Hex"])) == vector["output"]
    assert (
        semantic_event_key(
            repo_did=vector["repoDid"],
            commit_identity=vector["commitIdentity"],
            collection=vector["collection"],
            rkey=vector["rkey"],
            operation=vector["operation"],
        )
        == vector["output"]
    )


def test_event_variant_keys_keep_representation_testimony_distinct() -> None:
    vectors = _load_json("golden-vectors.json")
    assert isinstance(vectors, dict)
    semantic_key = vectors["semanticEvent"]["output"]
    outputs: set[str] = set()

    for vector in vectors["eventVariants"]:
        assert (
            _sha256_prefixed(bytes.fromhex(vector["inputUtf8Hex"])) == vector["output"]
        )
        actual = event_variant_key(
            semantic_event_key=semantic_key,
            record_cid=vector["recordCid"],
            payload_hash_scope=vector["payloadHashScope"],
            payload_hash=vector["payloadHash"],
        )
        assert actual == vector["output"]
        outputs.add(actual)

    assert len(outputs) == len(vectors["eventVariants"])


def test_delete_envelope_payload_hash_uses_canonical_json() -> None:
    vectors = _load_json("golden-vectors.json")
    assert isinstance(vectors, dict)
    vector = vectors["deleteEnvelope"]

    expected = bytes.fromhex(vector["canonicalUtf8Hex"])
    assert canonical_json_bytes(vector["value"]) == expected
    assert payload_hash("delete_envelope_v0", vector["value"]) == vector["payloadHash"]
    assert _sha256_prefixed(expected) == vector["payloadHash"]


def test_delete_event_variant_uses_literal_dash_for_absent_cid() -> None:
    vectors = _load_json("golden-vectors.json")
    assert isinstance(vectors, dict)
    vector = vectors["deleteEvent"]

    assert (
        _sha256_prefixed(bytes.fromhex(vector["semanticInputUtf8Hex"]))
        == vector["semanticEventKey"]
    )
    semantic_key = semantic_event_key(
        repo_did=vector["repoDid"],
        commit_identity=vector["commitIdentity"],
        collection=vector["collection"],
        rkey=vector["rkey"],
        operation=vector["operation"],
    )
    assert semantic_key == vector["semanticEventKey"]

    variant_material = bytes.fromhex(vector["variantInputUtf8Hex"])
    assert b"\x00-\x00delete_envelope_v0\x00" in variant_material
    assert _sha256_prefixed(variant_material) == vector["eventVariantKey"]
    assert (
        event_variant_key(
            semantic_event_key=semantic_key,
            record_cid=vector["recordCid"],
            payload_hash_scope=vector["payloadHashScope"],
            payload_hash=vector["payloadHash"],
        )
        == vector["eventVariantKey"]
    )


def test_documented_and_fixture_authority_rkeys() -> None:
    vectors = _load_json("golden-vectors.json")
    assert isinstance(vectors, dict)

    for vector in vectors["authorityRkeys"]:
        ref = RecordRef(**vector["ref"])
        if "inputUtf8Hex" in vector:
            assert (
                hashlib.sha256(bytes.fromhex(vector["inputUtf8Hex"])).hexdigest()
                in vector["output"]
            )

        if vector["kind"] == "admission":
            assert admission_rkey(ref) == vector["output"]
        else:
            assert vector["kind"] == "removal"
            assert removal_rkey(ref) == vector["output"]


def test_quarantine_audit_key_exact_bytes() -> None:
    vectors = _load_json("golden-vectors.json")
    assert isinstance(vectors, dict)
    vector = vectors["quarantine"]

    assert (
        payload_hash("observer_json_v0", vector["rawEnvelope"])
        == vector["rawEnvelopeHash"]
    )
    assert (
        f"quarantine:{hashlib.sha256(bytes.fromhex(vector['inputUtf8Hex'])).hexdigest()}"
        == vector["output"]
    )
    assert (
        quarantine_audit_key(
            source=vector["source"],
            cursor=vector["cursor"],
            raw_envelope_hash=vector["rawEnvelopeHash"],
        )
        == vector["output"]
    )
