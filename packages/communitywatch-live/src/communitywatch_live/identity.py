"""Bounded PLC-directory acquisition followed by unchanged SA9c/SA9b."""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from community_model import ValidationError, canonical_json_bytes
from community_model.dag_cbor import encode_dag_cbor
from community_model.identifiers import validate_did
from communitywatch_spaces_alpha import (
    DidInterpretationProfile,
    PlcAuditEntry,
    PlcHistoryEvidence,
    qualify_did_document,
    qualify_plc_history,
    verification_key_bytes,
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


@dataclass(frozen=True, slots=True)
class QualifiedRepoIdentity:
    did: str
    repo_host: str
    public_key: bytes
    signature_algorithm: str
    resolution_receipt_id: str
    host_binding_receipt_id: str
    key_binding_receipt_id: str
    acquisition_receipt_id: str

    def __post_init__(self) -> None:
        validate_did(self.did)
        if not self.repo_host.startswith(("https://", "http://127.0.0.1:")):
            raise ValidationError("live_identity_invalid", "repo host is invalid")
        if self.signature_algorithm not in {"ES256", "ES256K"}:
            raise ValidationError("live_identity_invalid", "key algorithm is invalid")
        if not self.public_key:
            raise ValidationError("live_identity_invalid", "public key is missing")
        for value in (
            self.resolution_receipt_id,
            self.host_binding_receipt_id,
            self.key_binding_receipt_id,
            self.acquisition_receipt_id,
        ):
            if not _digest(value):
                raise ValidationError("live_identity_invalid", "receipt ID is invalid")


@dataclass(frozen=True, slots=True)
class QualifiedSpaceAuthority:
    did: str
    authority_host: str
    resolution_receipt_id: str
    host_binding_receipt_id: str
    acquisition_receipt_id: str

    def __post_init__(self) -> None:
        validate_did(self.did)
        if not self.authority_host.startswith(("https://", "http://127.0.0.1:")):
            raise ValidationError("live_identity_invalid", "authority host is invalid")
        for value in (
            self.resolution_receipt_id,
            self.host_binding_receipt_id,
            self.acquisition_receipt_id,
        ):
            if not _digest(value):
                raise ValidationError("live_identity_invalid", "receipt ID is invalid")


class PlcDirectoryIdentityQualifier:
    """Acquire exact audit bytes; never trust directory current-document JSON."""

    def __init__(
        self,
        evidence_directory: str | Path,
        *,
        directory_origin: str = "https://plc.directory",
        timeout_seconds: float = 10.0,
        maximum_bytes: int = 1 << 20,
        allow_loopback_fixture: bool = False,
    ) -> None:
        self.evidence_directory = Path(evidence_directory)
        self.directory_origin = _origin(
            directory_origin, allow_loopback=allow_loopback_fixture
        )
        self.timeout_seconds = timeout_seconds
        self.maximum_bytes = maximum_bytes

    def qualify(self, did: str, *, evaluated_at: datetime) -> QualifiedRepoIdentity:
        expected, checked, plc, acquisition_id = self._resolve(
            did, evaluated_at=evaluated_at
        )
        assert plc.resolved_document is not None
        host = qualify_did_document(
            plc.resolved_document.to_sa9b_input(),
            profile=DidInterpretationProfile.ACCOUNT_REPO_HOST,
            qualified_at=checked,
        )
        key = qualify_did_document(
            plc.resolved_document.to_sa9b_input(),
            profile=DidInterpretationProfile.ACCOUNT_SIGNING_KEY,
            qualified_at=checked,
        )
        if host.selected_origin is None or key.selected_key_curve is None:
            raise ValidationError("live_identity_invalid", "PLC binding is incomplete")
        return QualifiedRepoIdentity(
            expected,
            host.selected_origin,
            verification_key_bytes(key),
            "ES256K" if key.selected_key_curve == "k256" else "ES256",
            plc.receipt.receipt_id,
            host.receipt_id,
            key.receipt_id,
            acquisition_id,
        )

    def qualify_space_authority(
        self, did: str, *, evaluated_at: datetime
    ) -> QualifiedSpaceAuthority:
        expected, checked, plc, acquisition_id = self._resolve(
            did, evaluated_at=evaluated_at
        )
        assert plc.resolved_document is not None
        host = qualify_did_document(
            plc.resolved_document.to_sa9b_input(),
            profile=DidInterpretationProfile.SPACE_AUTHORITY_HOST,
            qualified_at=checked,
        )
        if host.selected_origin is None:
            raise ValidationError(
                "live_identity_invalid", "Space authority binding is incomplete"
            )
        return QualifiedSpaceAuthority(
            expected,
            host.selected_origin,
            plc.receipt.receipt_id,
            host.receipt_id,
            acquisition_id,
        )

    def _resolve(self, did: str, *, evaluated_at: datetime):
        expected = validate_did(did)
        if not expected.startswith("did:plc:"):
            raise ValidationError(
                "live_identity_method_unsupported", "live alpha requires did:plc"
            )
        checked = _aware(evaluated_at)
        url = f"{self.directory_origin}/{expected}/log/audit"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"Accept": "application/json", "Accept-Encoding": "identity"},
        )
        try:
            response = urllib.request.build_opener(
                urllib.request.ProxyHandler({}), _NoRedirect()
            ).open(request, timeout=self.timeout_seconds)
            status = response.status
            body = response.read(self.maximum_bytes + 1)
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                raise ValidationError(
                    "live_identity_redirect_refused", "PLC directory redirect refused"
                ) from exc
            raise ValidationError(
                "live_identity_acquisition_failed", "PLC audit acquisition failed"
            ) from exc
        except Exception as exc:
            raise ValidationError(
                "live_identity_acquisition_failed", "PLC audit acquisition failed"
            ) from exc
        if status != 200 or not body or len(body) > self.maximum_bytes:
            raise ValidationError(
                "live_identity_acquisition_failed", "PLC audit response refused"
            )
        acquisition = {
            "version": "juniper-plc-audit-acquisition/1",
            "did": expected,
            "url": url,
            "status": status,
            "bodySha256": hashlib.sha256(body).hexdigest(),
            "bodyLength": len(body),
            "observedAt": checked.isoformat(),
            "redirectsFollowed": 0,
            "automaticRetries": 0,
            "verifiedClaims": ["exact_http_response_bytes"],
            "explicitNonClaims": [
                "directory_honesty",
                "globally_current",
                "governance_authority",
            ],
        }
        acquisition_id = _id(acquisition)
        acquisition["receiptId"] = acquisition_id
        _write_once(self.evidence_directory, acquisition_id, body, acquisition)

        raw = _json(body)
        if not isinstance(raw, list) or not raw:
            raise ValidationError("live_identity_invalid", "PLC audit is not a list")
        entries = tuple(_entry(item, expected) for item in raw)
        plc = qualify_plc_history(
            PlcHistoryEvidence(expected, entries, acquisition_id),
            evaluated_at=checked,
        )
        if plc.resolved_document is None:
            raise ValidationError(
                "live_identity_deactivated", "PLC identity is deactivated"
            )
        return expected, checked, plc, acquisition_id


def _entry(value: object, expected_did: str) -> PlcAuditEntry:
    if not isinstance(value, dict) or set(value) != {
        "did",
        "operation",
        "cid",
        "nullified",
        "createdAt",
    }:
        raise ValidationError("live_identity_invalid", "PLC audit entry fields differ")
    if (
        value["did"] != expected_did
        or not isinstance(value["operation"], dict)
        or not isinstance(value["nullified"], bool)
    ):
        raise ValidationError("live_identity_invalid", "PLC audit entry differs")
    try:
        created_at = _aware(
            datetime.fromisoformat(str(value["createdAt"]).replace("Z", "+00:00"))
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "live_identity_invalid", "PLC audit timestamp is invalid"
        ) from exc
    return PlcAuditEntry(
        encode_dag_cbor(value["operation"]),
        str(value["cid"]),
        created_at,
        value["nullified"],
    )


def _json(body: bytes) -> object:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        return json.loads(body, object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValidationError(
            "live_identity_invalid", "PLC audit JSON is invalid"
        ) from exc


def _write_once(directory: Path, receipt_id: str, body: bytes, receipt: object) -> None:
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    stem = receipt_id.removeprefix("sha256:")
    for path, value in (
        (directory / f"{stem}.audit.json", body),
        (directory / f"{stem}.receipt.json", canonical_json_bytes(receipt) + b"\n"),
    ):
        try:
            with path.open("xb") as handle:
                handle.write(value)
        except FileExistsError:
            if path.read_bytes() != value:
                raise ValidationError(
                    "live_identity_custody_conflict", "identity evidence conflicts"
                )


def _id(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(item in "0123456789abcdef" for item in value[7:])
    )


def _aware(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValidationError(
            "live_identity_time_invalid", "identity time must be aware"
        )
    return value.astimezone(UTC)


def _origin(value: str, *, allow_loopback: bool) -> str:
    parsed = urllib.parse.urlsplit(value)
    loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or (
            parsed.scheme != "https"
            and not (allow_loopback and loopback and parsed.scheme == "http")
        )
    ):
        raise ValueError("PLC directory origin is invalid")
    return value.rstrip("/")
