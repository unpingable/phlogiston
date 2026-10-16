"""Verify-at-ingest and verified subject resolution (OQ-2, answer A).

A Jetstream delivery is transport/discovery evidence only.  This module
fetches independent repository proof (``com.atproto.sync.getRecord`` for
present records, ``getRepo`` to prove absence for deletes) from the
DID-resolved PDS and verifies the commit signature against the current DID
document key, MST membership or non-membership, and the record block hash
against the claimed CID.  Revision and order always come from the verified
signed commit, never from the stream envelope.

Operator qualification on later revisions, implemented explicitly:

- proof rev == claimed event rev: the proof authenticates that historical
  event; one ``verified`` delivery results.
- proof rev later than the claimed event rev: the historical event is
  ingested as ``unverified`` (fail closed; the reducer records the existing
  ``authenticity_unverified`` finding) and a separate ``repo-resync-v1``
  delivery carries the verified current repository state at the signed
  commit's own revision.  The later proof is never represented as
  cryptographic authentication of the historical event.
- proof rev earlier than the claimed event rev: the proof covers neither
  the event nor current state; the delivery stays ``unverified``.
- malformed proof material (bad signature, hash mismatch, broken MST) or a
  proof that contradicts the claim at its own revision: ``failed``.
- transport/DID-resolution failures: ``unverified`` with no evidence.

Resync events never fabricate authority history: verified current state is
represented as a presence fact (``create``) or absence fact (``delete``) at
the signed commit's own revision, under the explicit ``repo-resync-v1``
method label.  A state proof can never authenticate a claimed *operation*,
so claimed updates/deletes that cannot be corroborated stay unverified
rather than becoming verified mutations; CID-difference against the
observed original is what convicts real mutations through the existing
create-only fail-closed rule.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

from community_model import (
    EventBatch,
    IncomingDelivery,
    RecordRef,
    ResolveResult,
    ValidationError,
    decode_dag_cbor,
    sha256_digest,
)
from community_model.identifiers import tid_sort_key, validate_tid

from .jetstream import RESYNC_CURSOR_MARK, TRANSPORT_METHOD
from .ports import EventSource
from .repoproof import (
    ProofError,
    RecordProof,
    extract_pds_endpoint,
    extract_verification_key,
    verify_record_proof,
)
from .syncclient import (
    DidResolver,
    FetchError,
    PdsClient,
    RecordNotFoundError,
)

METHOD_REPO_PROOF = "repo-proof-v1"
METHOD_REPO_RESYNC = "repo-resync-v1"
VERIFIER_VERSION = "1"


def supported_bluesky_pds(url: str) -> bool:
    """P0 supported hosting boundary; hostname is not identity evidence."""
    try:
        parts = urlsplit(url)
        suffix = ".host.bsky.network"
        prefix = (parts.hostname or "")[: -len(suffix)]
        return (
            parts.scheme == "https"
            and parts.hostname is not None
            and parts.hostname.endswith(suffix)
            and bool(prefix)
            and all(
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is not None
                for label in prefix.split(".")
            )
            and parts.port in (None, 443)
            and parts.username is None
            and parts.password is None
            and parts.path in ("", "/")
            and not parts.query
            and not parts.fragment
        )
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class _Claim:
    """One parsed in-scope commit claim from the transport source."""

    repo: str
    rev: str
    operation: str
    collection: str
    rkey: str
    cid: str | None


@dataclass(slots=True)
class _ProofFetcher:
    """DID resolution plus proof CAR download/verification for one claim."""

    did_resolver: DidResolver
    pds_client: PdsClient
    p0_bluesky_only: bool = False
    p0_test_pds_origin: str | None = None
    p0_hosted_pds_origin: str | None = None
    p0_allow_bluesky: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.p0_allow_bluesky, bool) or (
            self.p0_allow_bluesky
            and (
                self.p0_hosted_pds_origin != "https://phlogiston.social"
                or self.p0_test_pds_origin is not None
                or self.p0_bluesky_only
            )
        ):
            raise ValueError(
                "p0_allow_bluesky requires separate exact hosted P0 profile"
            )

    def fetch(
        self, claim: _Claim
    ) -> tuple[RecordProof | None, str | None, str | None, str | None]:
        """Return (proof, evidence_ref, evidence_hash, failure_kind).

        ``failure_kind`` is ``None`` on success, ``"unverified"`` for
        transport/identity problems, or ``"failed"`` for bad proof material.
        The evidence locator/hash are retained even for failed proofs.
        """

        try:
            document = self.did_resolver.resolve(claim.repo)
            public_key = extract_verification_key(document)
            pds_url = extract_pds_endpoint(document)
            if (
                self.p0_hosted_pds_origin is not None
                and pds_url != self.p0_hosted_pds_origin
                and not (self.p0_allow_bluesky and supported_bluesky_pds(pds_url))
            ):
                return None, "p0:unsupported-pds-host", None, "unverified"
            if self.p0_bluesky_only and not (
                supported_bluesky_pds(pds_url) or pds_url == self.p0_test_pds_origin
            ):
                return None, "p0:unsupported-pds-host", None, "unverified"
        except (ValidationError, ProofError, FetchError):
            return None, None, None, "unverified"
        evidence_ref: str | None = None
        car: bytes | None = None
        try:
            if claim.operation == "delete":
                evidence_ref, car = self._repo_car(pds_url, claim.repo)
            else:
                try:
                    evidence_ref, car = self._record_car(pds_url, claim)
                except RecordNotFoundError:
                    # The claimed create/update is absent at the current
                    # head; prove non-membership over the full repository.
                    evidence_ref, car = self._repo_car(pds_url, claim.repo)
        except FetchError:
            return None, evidence_ref, None, "unverified"
        evidence_hash = sha256_digest(car)
        try:
            proof = verify_record_proof(
                car,
                repo_did=claim.repo,
                collection=claim.collection,
                rkey=claim.rkey,
                public_key=public_key,
            )
        except ProofError:
            return None, evidence_ref, evidence_hash, "failed"
        return proof, evidence_ref, evidence_hash, None

    def _record_car(self, pds_url: str, claim: _Claim) -> tuple[str, bytes]:
        ref = (
            f"{pds_url}/xrpc/com.atproto.sync.getRecord"
            f"?did={claim.repo}&collection={claim.collection}&rkey={claim.rkey}"
        )
        return ref, self.pds_client.get_record_car(
            pds_url, repo=claim.repo, collection=claim.collection, rkey=claim.rkey
        )

    def _repo_car(self, pds_url: str, repo: str) -> tuple[str, bytes]:
        ref = f"{pds_url}/xrpc/com.atproto.sync.getRepo?did={repo}"
        return ref, self.pds_client.get_repo_car(pds_url, repo=repo)


def _parse_claim(delivery: IncomingDelivery) -> _Claim | None:
    envelope = delivery.raw_envelope
    if isinstance(envelope, bytes) or not isinstance(envelope, Mapping):
        return None
    try:
        repo = envelope["repo"]
        rev = validate_tid(envelope["rev"])
        operation = envelope["operation"]
        collection = envelope["collection"]
        rkey = envelope["rkey"]
    except (KeyError, ValidationError):
        return None
    if not all(
        isinstance(value, str) for value in (repo, operation, collection, rkey)
    ) or operation not in {"create", "update", "delete"}:
        return None
    cid = envelope.get("cid")
    assert isinstance(repo, str) and isinstance(operation, str)
    assert isinstance(collection, str) and isinstance(rkey, str)
    return _Claim(
        repo=repo,
        rev=rev,
        operation=operation,
        collection=collection,
        rkey=rkey,
        cid=cid if isinstance(cid, str) else None,
    )


def _decode_record(proof: RecordProof) -> Mapping[str, object]:
    if proof.record_bytes is None:
        raise ProofError("present proof without record bytes")
    try:
        decoded = decode_dag_cbor(proof.record_bytes)
    except ValidationError as exc:
        raise ProofError("proven record bytes do not decode") from exc
    if not isinstance(decoded, Mapping):
        raise ProofError("proven record is not a mapping")
    return decoded


@dataclass(slots=True)
class VerifyingEventSource:
    """Wrap a claim source with independent repository proof verification."""

    inner: EventSource
    did_resolver: DidResolver
    pds_client: PdsClient
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    p0_bluesky_only: bool = False
    p0_test_pds_origin: str | None = None
    p0_hosted_pds_origin: str | None = None
    p0_allow_bluesky: bool = False

    def read(self, after_cursor: str | None) -> EventBatch[IncomingDelivery]:
        batch = self.inner.read(after_cursor)
        verified: list[IncomingDelivery] = []
        for delivery in batch.items:
            verified.extend(self.verify_delivery(delivery))
        next_cursor = verified[-1].cursor if verified else batch.next_cursor
        return EventBatch(items=tuple(verified), next_cursor=next_cursor)

    def verify_delivery(
        self, delivery: IncomingDelivery
    ) -> tuple[IncomingDelivery, ...]:
        """Verify one claim delivery; returns the deliveries to ingest."""

        claim = _parse_claim(delivery)
        if claim is None:
            # Quarantine-bound or foreign input passes through untouched;
            # the store quarantines it with its cursor and reason codes.
            return (delivery,)
        fetcher = _ProofFetcher(
            self.did_resolver,
            self.pds_client,
            self.p0_bluesky_only,
            self.p0_test_pds_origin,
            self.p0_hosted_pds_origin,
            self.p0_allow_bluesky,
        )
        proof, evidence_ref, evidence_hash, failure = fetcher.fetch(claim)
        if failure is not None or proof is None:
            return (
                self._verdict(
                    delivery,
                    outcome="unverified" if failure != "failed" else "failed",
                    evidence_ref=evidence_ref,
                    evidence_hash=evidence_hash,
                ),
            )
        assert proof is not None
        claimed_order = tid_sort_key(claim.rev)
        proof_order = tid_sort_key(proof.commit.rev)
        if proof_order < claimed_order:
            # A stale proof covers neither the event nor current state.
            return (
                self._verdict(
                    delivery,
                    outcome="unverified",
                    evidence_ref=evidence_ref,
                    evidence_hash=evidence_hash,
                ),
            )
        exact_rev = proof_order == claimed_order
        try:
            record = _decode_record(proof) if proof.present else None
        except ProofError:
            return (
                self._verdict(
                    delivery,
                    outcome="failed",
                    evidence_ref=evidence_ref,
                    evidence_hash=evidence_hash,
                ),
            )
        cid_matches = (
            proof.present and claim.cid is not None and proof.record_cid == claim.cid
        )
        claims_present = claim.operation in {"create", "update"}
        consistent = proof.present and claims_present and cid_matches
        if claim.operation == "delete" and not proof.present and exact_rev:
            # Verified non-membership at the claimed revision authenticates
            # this exact historical delete.
            envelope = {
                "repo": claim.repo,
                "rev": proof.commit.rev,
                "operation": "delete",
                "collection": claim.collection,
                "rkey": claim.rkey,
                "commitCid": proof.commit.commit_cid,
            }
            return (
                self._verdict(
                    delivery,
                    outcome="verified",
                    evidence_ref=evidence_ref,
                    evidence_hash=evidence_hash,
                    envelope=envelope,
                ),
            )
        if consistent and exact_rev and claim.operation == "create":
            # The proof authenticates this exact historical create event.
            envelope = self._record_envelope(
                claim.repo,
                proof.commit.rev,
                "create",
                claim.collection,
                claim.rkey,
                proof,
                record,
            )
            return (
                self._verdict(
                    delivery,
                    outcome="verified",
                    evidence_ref=evidence_ref,
                    evidence_hash=evidence_hash,
                    envelope=envelope,
                ),
            )

        # Every remaining case: the historical event is not authenticated.
        # A repository state proof attests presence/absence at one signed
        # revision; it can never authenticate the claimed *operation*.  An
        # "update" claim therefore stays unverified even when the state
        # matches — otherwise a hostile relay could mint verified updates
        # (or fake deletes) for any record whose public CID it knows and
        # convict pristine create-only authority records of mutation.
        # Verified current state is always represented as presence
        # (resync "create") or absence (resync "delete") at the signed
        # commit's own revision; CID-difference against the observed
        # original is what convicts real mutations.
        contradicts = exact_rev and (
            (claims_present and not consistent)
            or (claim.operation == "delete" and proof.present)
        )
        historical = self._verdict(
            delivery,
            outcome="failed" if contradicts else "unverified",
            evidence_ref=evidence_ref,
            evidence_hash=evidence_hash,
        )
        resync = self._resync_delivery(
            delivery,
            claim,
            proof,
            record,
            evidence_ref=evidence_ref,
            evidence_hash=evidence_hash,
        )
        return historical, resync

    def _resync_delivery(
        self,
        delivery: IncomingDelivery,
        claim: _Claim,
        proof: RecordProof,
        record: Mapping[str, object] | None,
        *,
        evidence_ref: str | None,
        evidence_hash: str | None,
    ) -> IncomingDelivery:
        """One verified delivery carrying current state at the signed rev."""

        if proof.present:
            # A state proof attests presence, never the operation that
            # produced it; verified current state is represented as a
            # presence fact ("create") at the signed commit's own revision.
            envelope = self._record_envelope(
                claim.repo,
                proof.commit.rev,
                "create",
                claim.collection,
                claim.rkey,
                proof,
                record,
            )
        else:
            envelope = {
                "repo": claim.repo,
                "rev": proof.commit.rev,
                "operation": "delete",
                "collection": claim.collection,
                "rkey": claim.rkey,
                "commitCid": proof.commit.commit_cid,
            }
        cursor = f"{delivery.cursor}{RESYNC_CURSOR_MARK}{proof.commit.rev}"
        now = self.now()
        return IncomingDelivery(
            source=delivery.source,
            cursor=cursor,
            source_event_time=None,
            received_at=now,
            raw_envelope=envelope,
            trust_mode="verify_repo",
            verification_outcome="verified",
            verification_method=METHOD_REPO_RESYNC,
            verifier_version=VERIFIER_VERSION,
            evidence_ref=evidence_ref,
            evidence_hash=evidence_hash,
        )

    @staticmethod
    def _record_envelope(
        repo: str,
        rev: str,
        operation: str,
        collection: str,
        rkey: str,
        proof: RecordProof,
        record: Mapping[str, object] | None,
    ) -> dict[str, object]:
        assert proof.record_cid is not None and proof.record_bytes is not None
        assert record is not None
        return {
            "repo": repo,
            "rev": rev,
            "operation": operation,
            "collection": collection,
            "rkey": rkey,
            "cid": proof.record_cid,
            "record": dict(record),
            "recordBytesHex": proof.record_bytes.hex(),
            "commitCid": proof.commit.commit_cid,
        }

    @staticmethod
    def _verdict(
        delivery: IncomingDelivery,
        *,
        outcome: str,
        evidence_ref: str | None,
        evidence_hash: str | None,
        envelope: object | None = None,
    ) -> IncomingDelivery:
        return IncomingDelivery(
            source=delivery.source,
            cursor=delivery.cursor,
            source_event_time=delivery.source_event_time,
            received_at=delivery.received_at,
            raw_envelope=(
                delivery.raw_envelope if envelope is None else envelope  # type: ignore[arg-type]
            ),
            trust_mode="verify_repo",
            verification_outcome=outcome,
            verification_method=(
                TRANSPORT_METHOD
                if outcome == "unverified" and evidence_hash is None
                else METHOD_REPO_PROOF
            ),
            verifier_version=VERIFIER_VERSION,
            evidence_ref=evidence_ref,
            evidence_hash=evidence_hash,
        )


@dataclass(slots=True)
class VerifiedSubjectResolver:
    """Resolve exact URI+CID subjects through the same verified proof path."""

    did_resolver: DidResolver
    pds_client: PdsClient
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    p0_bluesky_only: bool = False
    p0_test_pds_origin: str | None = None
    p0_hosted_pds_origin: str | None = None
    p0_allow_bluesky: bool = False

    def resolve_exact(self, ref: RecordRef) -> ResolveResult:
        checked_at: datetime = self.now()
        claim = _Claim(
            repo=ref.repo_did,
            rev="2222222222222",  # unused for resolution; placeholder TID
            operation="create",
            collection=ref.collection,
            rkey=ref.rkey,
            cid=ref.cid,
        )
        fetcher = _ProofFetcher(
            self.did_resolver,
            self.pds_client,
            self.p0_bluesky_only,
            self.p0_test_pds_origin,
            self.p0_hosted_pds_origin,
            self.p0_allow_bluesky,
        )
        try:
            proof, evidence_ref, evidence_hash, failure = fetcher.fetch(claim)
        except Exception:
            proof, evidence_ref, evidence_hash, failure = (
                None,
                None,
                None,
                "unverified",
            )
        if failure is not None or proof is None:
            return self._result(
                ref,
                status="error",
                outcome="failed" if failure == "failed" else "unverified",
                current_cid=None,
                record=None,
                checked_at=checked_at,
                evidence_ref=evidence_ref,
                evidence_hash=evidence_hash,
            )
        assert proof is not None
        if not proof.present:
            return self._result(
                ref,
                status="missing",
                outcome="verified",
                current_cid=None,
                record=None,
                checked_at=checked_at,
                evidence_ref=evidence_ref,
                evidence_hash=evidence_hash,
            )
        try:
            record = _decode_record(proof)
        except ProofError:
            return self._result(
                ref,
                status="error",
                outcome="failed",
                current_cid=None,
                record=None,
                checked_at=checked_at,
                evidence_ref=evidence_ref,
                evidence_hash=evidence_hash,
            )
        if proof.record_cid == ref.cid:
            return self._result(
                ref,
                status="exact",
                outcome="verified",
                current_cid=proof.record_cid,
                record=record,
                checked_at=checked_at,
                evidence_ref=evidence_ref,
                evidence_hash=evidence_hash,
            )
        return self._result(
            ref,
            status="mismatch",
            outcome="verified",
            current_cid=proof.record_cid,
            record=record,
            checked_at=checked_at,
            evidence_ref=evidence_ref,
            evidence_hash=evidence_hash,
        )

    @staticmethod
    def _result(
        ref: RecordRef,
        *,
        status: str,
        outcome: str,
        current_cid: str | None,
        record: Mapping[str, object] | None,
        checked_at: datetime,
        evidence_ref: str | None,
        evidence_hash: str | None,
    ) -> ResolveResult:
        return ResolveResult(
            status=status,
            requested=ref,
            current_cid=current_cid,
            record=record,
            checked_at=checked_at,
            trust_mode="verify_repo",
            verification_outcome=outcome,
            resolution_method=METHOD_REPO_PROOF,
            resolver_version=VERIFIER_VERSION,
            evidence_ref=evidence_ref,
            evidence_hash=evidence_hash,
        )


__all__ = [
    "METHOD_REPO_PROOF",
    "METHOD_REPO_RESYNC",
    "VERIFIER_VERSION",
    "VerifiedSubjectResolver",
    "VerifyingEventSource",
]
