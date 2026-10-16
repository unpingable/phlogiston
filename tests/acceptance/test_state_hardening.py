"""V0-M4 state-machine and invariant hardening tests (TEST-PLAN).

Each test drives the observer store through one hostile or out-of-order
scenario from the "State-machine and invariant tests" section of
``docs/TEST-PLAN.md`` and asserts the projected lifecycle, entry, findings,
and audit outcomes required by ``docs/V0-STATE-MACHINE.md``.  PCV0 supersedes the earlier OQ-5 rule for admitted roots: author context
withdrawal closes community discovery while preserving the admission history.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from community_model import (
    ADMISSION_COLLECTION,
    MOD_ACTION_COLLECTION,
    POST_COLLECTION,
    SUBMISSION_COLLECTION,
    IncomingDelivery,
    RecordRef,
    ResolveResult,
    admission_rkey,
    canonical_json_bytes,
    cid_for_dag_cbor,
    removal_rkey,
)
from communitywatch import ObserverStore, ProjectionQuery

COMMUNITY_DID = "did:web:community.invalid"
ADMIN_DID = "did:web:admin.invalid"
ALICE_DID = "did:web:alice.invalid"
POST_RKEY = "3jzfcijpj2z2a"
SUBMISSION_RKEY = "3jzfcijpj2z2k"
T0 = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)
SIGNED_PAST = "2026-08-14T11:00:00Z"
_TID_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"


def _tid(sequence: int) -> str:
    digits = ""
    value = sequence
    while True:
        digits = _TID_ALPHABET[value % 32] + digits
        value //= 32
        if not value:
            break
    return digits.rjust(13, "2")


def _cid(record: dict[str, object]) -> str:
    return cid_for_dag_cbor(canonical_json_bytes(record))


def _submission_record(subject: RecordRef, created_at: str) -> dict[str, object]:
    return {
        "$type": SUBMISSION_COLLECTION,
        "community": COMMUNITY_DID,
        "subject": subject.as_dict(),
        "createdAt": created_at,
    }


def _submission_ref(
    subject: RecordRef, rkey: str, created_at: str, author: str = ALICE_DID
) -> RecordRef:
    return RecordRef(
        uri=f"at://{author}/{SUBMISSION_COLLECTION}/{rkey}",
        cid=_cid(_submission_record(subject, created_at)),
    )


def _admission_record(
    submission: RecordRef,
    subject: RecordRef,
    created_at: str,
    actor: str = ADMIN_DID,
) -> dict[str, object]:
    return {
        "$type": ADMISSION_COLLECTION,
        "submission": submission.as_dict(),
        "subject": subject.as_dict(),
        "actor": actor,
        "createdAt": created_at,
    }


def _admission_ref(
    submission: RecordRef,
    subject: RecordRef,
    created_at: str,
    actor: str = ADMIN_DID,
    repo: str = COMMUNITY_DID,
) -> RecordRef:
    return RecordRef(
        uri=f"at://{repo}/{ADMISSION_COLLECTION}/{admission_rkey(submission)}",
        cid=_cid(_admission_record(submission, subject, created_at, actor)),
    )


class Rig:
    """Deterministic scenario driver over one temporary observer store."""

    def __init__(self, tmp_path: Path, **store_kwargs: object) -> None:
        self.store = ObserverStore(
            tmp_path / "observer.sqlite3",
            community_did=COMMUNITY_DID,
            administrator_did=ADMIN_DID,
            **store_kwargs,
        )
        self.query = ProjectionQuery(self.store, slug="test")
        self.cursors: dict[str, int] = {}
        self.revs: dict[str, int] = {}
        self.tick = 0
        self.post_records: dict[tuple[str, str], dict[str, object]] = {}

    def _time(self) -> datetime:
        self.tick += 1
        return T0 + timedelta(seconds=self.tick)

    def _next_cursor(self, source: str) -> str:
        self.cursors[source] = self.cursors.get(source, 0) + 1
        return str(self.cursors[source])

    def _next_rev(self, repo: str) -> str:
        self.revs[repo] = self.revs.get(repo, 0) + 1
        return _tid(self.revs[repo])

    def deliver(
        self,
        *,
        repo: str,
        collection: str,
        rkey: str,
        record: dict[str, object] | None,
        operation: str = "create",
        outcome: str = "verified",
        source: str = "relay-a",
        rev: str | None = None,
    ) -> str:
        """Ingest one raw envelope; return the derived event/quarantine key."""

        when = self._time()
        envelope: dict[str, object] = {
            "repo": repo,
            "rev": rev or self._next_rev(repo),
            "operation": operation,
            "collection": collection,
            "rkey": rkey,
        }
        if operation != "delete":
            assert record is not None
            envelope["cid"] = _cid(record)
            envelope["record"] = record
        return self.store.ingest(
            IncomingDelivery(
                source=source,
                cursor=self._next_cursor(source),
                source_event_time=when,
                received_at=when,
                raw_envelope=envelope,
                trust_mode="test_fixture",
                verification_outcome=outcome,
                verification_method="fixture",
                verifier_version="1",
            )
        ).key

    def post(
        self, *, author: str = ALICE_DID, rkey: str = POST_RKEY, text: str = "hello"
    ) -> RecordRef:
        record = {"$type": POST_COLLECTION, "text": text, "createdAt": SIGNED_PAST}
        ref = RecordRef(uri=f"at://{author}/{POST_COLLECTION}/{rkey}", cid=_cid(record))
        self.post_records[(author, rkey)] = record
        return ref

    def post_record(self, ref: RecordRef) -> dict[str, object]:
        return self.post_records[(ref.repo_did, ref.rkey)]

    def submit(
        self,
        subject: RecordRef,
        *,
        author: str = ALICE_DID,
        rkey: str = SUBMISSION_RKEY,
        community: str = COMMUNITY_DID,
        outcome: str = "verified",
        source: str = "relay-a",
        rev: str | None = None,
        created_at: str = SIGNED_PAST,
    ) -> RecordRef:
        record = _submission_record(subject, created_at)
        record["community"] = community
        self.deliver(
            repo=author,
            collection=SUBMISSION_COLLECTION,
            rkey=rkey,
            record=record,
            outcome=outcome,
            source=source,
            rev=rev,
        )
        return RecordRef(
            uri=f"at://{author}/{SUBMISSION_COLLECTION}/{rkey}", cid=_cid(record)
        )

    def mutate(self, ref: RecordRef, record: dict[str, object] | None) -> str:
        """Externally update/delete a record outside any authority flow."""

        operation = "delete" if record is None else "update"
        return self.deliver(
            repo=ref.repo_did,
            collection=ref.collection,
            rkey=ref.rkey,
            record=record,
            operation=operation,
        )

    def admit(
        self,
        submission: RecordRef,
        subject: RecordRef,
        *,
        actor: str = ADMIN_DID,
        repo: str = COMMUNITY_DID,
        outcome: str = "verified",
        created_at: str = SIGNED_PAST,
    ) -> tuple[RecordRef, str]:
        record = _admission_record(submission, subject, created_at, actor)
        key = self.deliver(
            repo=repo,
            collection=ADMISSION_COLLECTION,
            rkey=admission_rkey(submission),
            record=record,
            outcome=outcome,
        )
        ref = RecordRef(
            uri=f"at://{repo}/{ADMISSION_COLLECTION}/{admission_rkey(submission)}",
            cid=_cid(record),
        )
        return ref, key

    def remove(
        self,
        admission: RecordRef,
        subject: RecordRef,
        *,
        outcome: str = "verified",
        created_at: str = SIGNED_PAST,
    ) -> tuple[RecordRef, str]:
        record = {
            "$type": MOD_ACTION_COLLECTION,
            "action": "remove",
            "admission": admission.as_dict(),
            "subject": subject.as_dict(),
            "actor": ADMIN_DID,
            "createdAt": created_at,
        }
        key = self.deliver(
            repo=COMMUNITY_DID,
            collection=MOD_ACTION_COLLECTION,
            rkey=removal_rkey(admission),
            record=record,
            outcome=outcome,
        )
        ref = RecordRef(
            uri=(
                f"at://{COMMUNITY_DID}/{MOD_ACTION_COLLECTION}"
                f"/{removal_rkey(admission)}"
            ),
            cid=_cid(record),
        )
        return ref, key

    def observe(
        self,
        subject: RecordRef,
        status: str,
        *,
        outcome: str = "verified",
        triggering: str | None = None,
        trust_mode: str = "test_fixture",
        method: str = "fixture",
        version: str = "1",
    ) -> str:
        if status == "exact":
            current_cid: str | None = subject.cid
            record: dict[str, object] | None = self.post_record(subject)
        elif status == "mismatch":
            changed = dict(self.post_record(subject), text="edited")
            current_cid = _cid(changed)
            record = None
        else:
            current_cid = None
            record = None
        return self.store.record_subject_observation(
            ResolveResult(
                status=status,
                requested=subject,
                current_cid=current_cid,
                record=record,
                checked_at=self._time(),
                trust_mode=trust_mode,
                verification_outcome=outcome,
                resolution_method=method,
                resolver_version=version,
            ),
            triggering_event_variant_key=triggering,
        )

    def admit_and_observe(
        self, submission: RecordRef, subject: RecordRef, **kwargs: object
    ) -> RecordRef:
        admission, variant = self.admit(submission, subject, **kwargs)
        self.observe(subject, "exact", triggering=variant)
        return admission

    def snapshot(self) -> dict[str, object]:
        return self.store.projection_snapshot()

    def lifecycles(self) -> list[dict[str, object]]:
        rows = self.snapshot()["admission_lifecycles"]
        assert isinstance(rows, list)
        return rows

    def lifecycle_statuses(self) -> list[str]:
        return sorted(str(row["status"]) for row in self.lifecycles())

    def entries(self) -> list[dict[str, object]]:
        rows = self.snapshot()["community_entries"]
        assert isinstance(rows, list)
        return rows

    def findings(self, reason: str) -> list[dict[str, object]]:
        rows = self.snapshot()["projection_findings"]
        assert isinstance(rows, list)
        return [row for row in rows if row["reason_code"] == reason]

    def audit(self, kind: str) -> list[dict[str, object]]:
        rows = self.snapshot()["audit_index"]
        assert isinstance(rows, list)
        return [row for row in rows if row["kind"] == kind]

    def visible_count(self) -> int:
        return len(self.query.list_visible(COMMUNITY_DID, 100, None).items)


def _visible(rig: Rig, subject: RecordRef) -> tuple[RecordRef, RecordRef]:
    """Drive one plain submission/admission/exact-observation flow."""

    submission = rig.submit(subject)
    admission = rig.admit_and_observe(submission, subject)
    assert rig.visible_count() == 1
    return submission, admission


# --- PCV0: root submission mutation withdraws community context ---------------


def test_pcv0_submission_update_after_admission_withdraws_root(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    submission, _ = _visible(rig, subject)

    rig.mutate(submission, _submission_record(subject, "2026-08-14T11:00:01Z"))

    assert [row["status"] for row in rig.lifecycles()] == ["author_withdrawn"]
    assert [row["status"] for row in rig.entries()] == ["author_withdrawn"]
    assert rig.visible_count() == 0
    # The mutation stays audit-visible as its own valid event row.
    submissions = rig.audit("submission")
    assert len(submissions) == 2
    assert all(row["outcome"] == "valid" for row in submissions)
    assert rig.findings("projection_incomplete") == []
    before = rig.snapshot()
    rig.store.rebuild()
    assert rig.snapshot() == before


def test_pcv0_submission_delete_after_admission_withdraws_root(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    submission, _ = _visible(rig, subject)

    rig.mutate(submission, None)

    assert [row["status"] for row in rig.lifecycles()] == ["author_withdrawn"]
    assert rig.visible_count() == 0
    assert len(rig.audit("submission")) == 2


def test_oq5_post_mutation_still_hides_after_submission_mutation(
    tmp_path: Path,
) -> None:
    # Once author context is withdrawn, later post observations remain auditable
    # and may refine the lifecycle terminal state.
    rig = Rig(tmp_path)
    subject = rig.post()
    submission, _ = _visible(rig, subject)
    rig.mutate(submission, None)
    assert rig.visible_count() == 0

    rig.observe(subject, "mismatch")
    assert [row["status"] for row in rig.lifecycles()] == ["stale_cid"]
    assert rig.visible_count() == 0
    rig.observe(subject, "missing")
    assert [row["status"] for row in rig.lifecycles()] == ["subject_deleted"]


# --- dependency arrival order ------------------------------------------------


def test_admission_before_submission_stays_pending_until_exact_resolution(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    submission = _submission_ref(subject, SUBMISSION_RKEY, SIGNED_PAST)
    admission, _ = rig.admit(submission, subject)
    assert [row["status"] for row in rig.lifecycles()] == ["pending"]
    assert rig.findings("reference_pending")
    assert rig.visible_count() == 0

    rig.submit(subject)
    # The dependency arrived but the exact start check has not run yet.
    assert [row["status"] for row in rig.lifecycles()] == ["pending"]
    assert admission.cid == _admission_ref(submission, subject, SIGNED_PAST).cid


def test_admission_resolves_once_submission_and_check_arrive(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    submission = _submission_ref(subject, SUBMISSION_RKEY, SIGNED_PAST)
    _, variant = rig.admit(submission, subject)
    rig.submit(subject)
    rig.observe(subject, "exact", triggering=variant)
    assert [row["status"] for row in rig.lifecycles()] == ["visible"]
    assert rig.visible_count() == 1


def test_cross_repository_arrival_shuffle_preserves_reference_validity(
    tmp_path: Path,
) -> None:
    summaries = []
    for label, submission_first in (("in-order", True), ("shuffled", False)):
        rig = Rig(tmp_path / label)
        subject = rig.post()
        submission = _submission_ref(subject, SUBMISSION_RKEY, SIGNED_PAST)
        if submission_first:
            rig.submit(subject)
            _, variant = rig.admit(submission, subject)
        else:
            _, variant = rig.admit(submission, subject)
            rig.submit(subject)
        rig.observe(subject, "exact", triggering=variant)
        rows = rig.snapshot()["audit_index"]
        assert isinstance(rows, list)
        summaries.append(
            {
                "outcomes": sorted((row["kind"], row["outcome"]) for row in rows),
                "entries": [row["status"] for row in rig.entries()],
                "visible": rig.visible_count(),
            }
        )
    assert summaries[0] == summaries[1]
    assert summaries[0]["entries"] == ["visible"]


def test_removal_before_admission_masks_without_flashing_visible(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    submission = _submission_ref(subject, SUBMISSION_RKEY, SIGNED_PAST)
    admission = _admission_ref(submission, subject, SIGNED_PAST)
    rig.remove(admission, subject)
    assert rig.findings("reference_missing")
    assert rig.entries() == []

    rig.submit(subject)
    _, variant = rig.admit(submission, subject)
    rig.observe(subject, "exact", triggering=variant)
    assert [row["status"] for row in rig.lifecycles()] == ["removed"]
    assert [row["status"] for row in rig.entries()] == ["removed"]
    assert rig.visible_count() == 0


def test_removal_of_unknown_admission_is_a_finding_only(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    submission = _submission_ref(subject, SUBMISSION_RKEY, SIGNED_PAST)
    admission = _admission_ref(submission, subject, SIGNED_PAST)
    rig.remove(admission, subject)
    assert rig.lifecycles() == []
    assert rig.entries() == []
    findings = rig.findings("reference_missing")
    assert len(findings) == 1
    assert findings[0]["subject_uri"] == subject.uri


# --- authority and authenticity boundaries -----------------------------------


def test_unauthorized_actor_admission_has_no_authority_effect(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    submission = rig.submit(subject)
    rig.admit(submission, subject, actor="did:web:mallory.invalid")
    assert rig.lifecycles() == []
    assert rig.visible_count() == 0
    rows = rig.audit("admission")
    assert [row["outcome"] for row in rows] == ["unauthorized"]
    assert [row["reason_codes"] for row in rows] == [["actor_unauthorized"]]


def test_wrong_repo_admission_has_no_authority_effect(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    submission = rig.submit(subject)
    rig.admit(submission, subject, repo=ALICE_DID)
    assert rig.lifecycles() == []
    rows = rig.audit("admission")
    assert [row["outcome"] for row in rows] == ["unauthorized"]
    assert [row["reason_codes"] for row in rows] == [["authority_repo_mismatch"]]


def test_wrong_community_submission_is_invalid_and_inert(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    rig.submit(subject, community="did:web:other.invalid")
    assert rig.entries() == []
    rows = rig.audit("submission")
    assert [row["outcome"] for row in rows] == ["invalid"]
    assert [row["reason_codes"] for row in rows] == [["community_mismatch"]]


def test_unverified_envelopes_stay_audit_visible_without_effect(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    submission = rig.submit(subject, outcome="unverified")
    rig.admit(submission, subject, outcome="unverified")
    assert rig.lifecycles() == []
    assert rig.visible_count() == 0
    rows = rig.snapshot()["audit_index"]
    assert isinstance(rows, list)
    assert {row["outcome"] for row in rows} == {"unauthorized"}
    assert all(row["reason_codes"] == ["authenticity_unverified"] for row in rows)


def test_mismatched_admission_submission_subjects_are_invalid(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    other = rig.post(rkey="3jzfcijpj2z2b", text="other post")
    submission = rig.submit(subject)
    rig.admit(submission, other)
    assert [row["status"] for row in rig.lifecycles()] == ["invalid"]
    assert [row["reason_codes"] for row in rig.lifecycles()] == [
        ["strong_ref_mismatch"]
    ]
    assert rig.visible_count() == 0


# --- submission currency at first admission validation -----------------------


def test_admission_must_reference_the_current_submission_version(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    old = rig.submit(subject)
    # The author updates the submission before any admission is observed.
    updated = _submission_record(subject, "2026-08-14T11:00:01Z")
    rig.mutate(old, updated)
    current = RecordRef(uri=old.uri, cid=_cid(updated))

    # An external admission for the superseded version is rejected; an
    # admission for the exact current version is a valid new intent.
    rig.admit(old, subject)
    _, variant = rig.admit(current, subject)
    rig.observe(subject, "exact", triggering=variant)

    by_submission_cid = {row["submission_cid"]: row for row in rig.lifecycles()}
    assert by_submission_cid[old.cid]["status"] == "invalid"
    assert by_submission_cid[old.cid]["reason_codes"] == ["reference_missing"]
    assert by_submission_cid[current.cid]["status"] == "visible"
    assert rig.visible_count() == 1


def test_admission_referencing_deleted_submission_is_rejected(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    submission = rig.submit(subject)
    rig.mutate(submission, None)
    rig.admit(submission, subject)
    assert [row["status"] for row in rig.lifecycles()] == ["invalid"]
    assert [row["reason_codes"] for row in rig.lifecycles()] == [["reference_missing"]]
    assert rig.visible_count() == 0


# --- authority-record mutation (create-only invariant) -----------------------


def test_admission_update_after_admission_fails_closed(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    submission, admission = _visible(rig, subject)
    rig.mutate(
        admission,
        _admission_record(submission, subject, "2026-08-14T11:00:02Z"),
    )
    assert [row["status"] for row in rig.lifecycles()] == ["conflict"]
    assert [row["reason_codes"] for row in rig.lifecycles()] == [
        ["authority_record_mutated"]
    ]
    assert rig.visible_count() == 0
    rows = rig.audit("admission")
    assert any(
        row["outcome"] == "invalid"
        and row["reason_codes"] == ["authority_record_mutated"]
        for row in rows
    )


def test_admission_delete_after_admission_fails_closed(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    _, admission = _visible(rig, subject)
    rig.mutate(admission, None)
    assert [row["status"] for row in rig.lifecycles()] == ["conflict"]
    assert rig.visible_count() == 0
    rows = rig.audit("admission")
    assert any(
        row["outcome"] == "conflict"
        and row["reason_codes"] == ["authority_record_mutated"]
        for row in rows
    )


def test_occupied_admission_rkey_with_differing_content_fails_closed(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    submission = rig.submit(subject)
    rig.admit_and_observe(submission, subject)
    assert rig.visible_count() == 1

    # A second create occupies the deterministic rkey with differing content.
    rig.admit(submission, subject, created_at="2026-08-14T11:00:03Z")
    assert rig.lifecycle_statuses() == ["conflict", "conflict"]
    assert rig.visible_count() == 0


def test_removal_update_cannot_restore_content(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    _, admission = _visible(rig, subject)
    removal, _ = rig.remove(admission, subject)
    assert [row["status"] for row in rig.entries()] == ["removed"]

    rig.mutate(
        removal,
        {
            "$type": MOD_ACTION_COLLECTION,
            "action": "remove",
            "admission": admission.as_dict(),
            "subject": subject.as_dict(),
            "actor": ADMIN_DID,
            "reason": "rewritten",
            "createdAt": "2026-08-14T11:00:04Z",
        },
    )
    assert [row["status"] for row in rig.entries()] == ["removed"]
    assert rig.visible_count() == 0
    assert rig.findings("authority_record_mutated")
    rows = rig.audit("removal")
    assert any(row["outcome"] == "valid" for row in rows)


def test_removal_delete_cannot_restore_content(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    _, admission = _visible(rig, subject)
    removal, _ = rig.remove(admission, subject)
    rig.mutate(removal, None)
    assert [row["status"] for row in rig.entries()] == ["removed"]
    assert rig.visible_count() == 0
    rows = rig.audit("removal")
    assert any(
        row["outcome"] == "conflict"
        and row["reason_codes"] == ["authority_record_mutated"]
        for row in rows
    )


# --- removal, duplicates, and readmission ------------------------------------


def test_readmission_after_removal_stays_removed_with_finding(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    _, admission = _visible(rig, subject)
    rig.remove(admission, subject)
    assert [row["status"] for row in rig.entries()] == ["removed"]

    # An externally observed readmission of the exact subject after the
    # removal (community-repo commit order) is masked and flagged.
    submission2 = rig.submit(subject, rkey="3jzfcijpj2z2m")
    rig.admit_and_observe(submission2, subject)
    assert rig.lifecycle_statuses() == ["removed", "removed"]
    assert rig.visible_count() == 0
    findings = rig.findings("unsupported_readmission")
    assert len(findings) == 1
    assert findings[0]["subject_uri"] == subject.uri
    assert findings[0]["subject_cid"] == subject.cid


def test_removal_masks_duplicate_admissions_but_never_later_cid(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    subject_a = rig.post()
    submission1 = rig.submit(subject_a)
    submission2 = rig.submit(subject_a, rkey="3jzfcijpj2z2m")
    admission1 = rig.admit_and_observe(
        submission1, subject_a, created_at="2026-08-14T11:01:00Z"
    )
    rig.admit_and_observe(submission2, subject_a, created_at="2026-08-14T11:02:00Z")

    # Semantic duplicates collapse to one card at the earliest time; both
    # admissions remain in audit and cannot bump chronology.
    assert len(rig.entries()) == 1
    assert rig.entries()[0]["admitted_at"] == "2026-08-14T11:01:00Z"
    assert len(rig.audit("admission")) == 2
    assert rig.visible_count() == 1

    rig.remove(admission1, subject_a)
    assert rig.lifecycle_statuses() == ["removed", "removed"]
    assert [row["status"] for row in rig.entries()] == ["removed"]
    assert rig.visible_count() == 0

    # A later different CID is a different exact subject and is never masked.
    changed = dict(rig.post_record(subject_a), text="second version")
    subject_b = RecordRef(uri=subject_a.uri, cid=_cid(changed))
    rig.post_records[(subject_b.repo_did, subject_b.rkey)] = changed
    submission3 = rig.submit(subject_b, rkey="3jzfcijpj2z2n")
    rig.admit_and_observe(submission3, subject_b)
    by_cid = {row["subject_cid"]: row["status"] for row in rig.entries()}
    assert by_cid == {subject_a.cid: "removed", subject_b.cid: "visible"}
    assert rig.visible_count() == 1


# --- terminality, revert, and first-observed eligibility ---------------------


def test_revert_does_not_revive_terminal_lifecycle(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    submission = rig.submit(subject)
    admission = rig.admit_and_observe(submission, subject)

    rig.observe(subject, "mismatch")
    assert [row["status"] for row in rig.lifecycles()] == ["stale_cid"]

    # The post reverts to the admitted CID; a duplicate admission of the old
    # submission (same deterministic rkey, same content) cannot revive it.
    rig.admit(submission, subject)
    assert [row["status"] for row in rig.lifecycles()] == ["stale_cid"]
    assert rig.visible_count() == 0

    # A genuinely new submission plus admission, both first observed after the
    # terminal observation, seed a fresh visible lifecycle for the same CID.
    submission2 = rig.submit(subject, rkey="3jzfcijpj2z2m")
    rig.admit_and_observe(submission2, subject)
    by_admission = {row["admission_cid"]: row for row in rig.lifecycles()}
    assert by_admission[admission.cid]["status"] == "stale_cid"
    assert len(rig.lifecycles()) == 2
    assert [row["status"] for row in rig.entries()] == ["visible"]
    assert rig.visible_count() == 1
    # The terminal lifecycle stays in audit.
    assert len(rig.audit("admission")) == 3


def test_pre_terminal_equivalent_submission_is_ineligible(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    submission1 = rig.submit(subject)
    # S2 is equivalent intent observed before the terminal event.
    submission2 = rig.submit(subject, rkey="3jzfcijpj2z2m")
    rig.admit_and_observe(submission1, subject)
    rig.observe(subject, "mismatch")  # terminal for the exact subject

    # Admitting S2 after the post reverts cannot restore visibility: S2's
    # first observed sequence predates the terminal observation.
    rig.admit_and_observe(submission2, subject)
    assert rig.lifecycle_statuses() == ["stale_cid", "stale_cid"]
    assert rig.visible_count() == 0


def test_pending_pre_terminal_admission_cannot_be_held_for_restoration(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    submission1 = rig.submit(subject)
    submission2 = rig.submit(subject, rkey="3jzfcijpj2z2m")
    _, variant1 = rig.admit(submission1, subject)
    # A2 is observed (pending) before the terminal event.
    _, variant2 = rig.admit(submission2, subject)
    assert "pending" in rig.lifecycle_statuses()

    rig.observe(subject, "exact", triggering=variant1)
    rig.observe(subject, "mismatch")  # terminal
    # A2's start check happens only after the terminal observation.
    rig.observe(subject, "exact", triggering=variant2)
    assert rig.lifecycle_statuses() == ["stale_cid", "stale_cid"]
    assert rig.visible_count() == 0


def test_unverified_first_observation_anchors_lifecycle_eligibility(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    submission1 = rig.submit(subject)
    # S2 first observed unverified before the terminal event.
    submission2 = rig.submit(subject, rkey="3jzfcijpj2z2m", outcome="unverified")
    rig.admit_and_observe(submission1, subject)
    rig.observe(subject, "mismatch")  # terminal

    # Trusted corroboration arrives later from a second source: same revision
    # and payload, so the same event variant keeps its early sequence.
    rig.submit(
        subject,
        rkey="3jzfcijpj2z2m",
        source="relay-b",
        rev=_tid(2),
    )
    corroborated = rig.audit("submission")
    assert any(
        row["record_cid"] == submission2.cid and row["outcome"] == "valid"
        for row in corroborated
    )

    # Authentic but causally old: it still cannot seed a fresh lifecycle.
    rig.admit_and_observe(submission2, subject)
    assert rig.lifecycle_statuses() == ["stale_cid", "stale_cid"]
    assert rig.visible_count() == 0


# --- resolver trust and terminality ------------------------------------------


def test_transient_resolver_error_recovers_without_new_authority(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    _visible(rig, subject)
    rig.observe(subject, "error")
    assert [row["status"] for row in rig.lifecycles()] == ["subject_unavailable"]
    assert [row["reason_codes"] for row in rig.lifecycles()] == [["resolver_error"]]
    rig.observe(subject, "exact")
    assert [row["status"] for row in rig.lifecycles()] == ["visible"]
    assert rig.visible_count() == 1


def test_transport_error_cannot_demote_terminal_states(tmp_path: Path) -> None:
    rig = Rig(tmp_path / "stale")
    subject = rig.post()
    _visible(rig, subject)
    rig.observe(subject, "mismatch")
    rig.observe(subject, "error")
    assert [row["status"] for row in rig.lifecycles()] == ["stale_cid"]

    rig2 = Rig(tmp_path / "deleted")
    subject2 = rig2.post()
    _visible(rig2, subject2)
    rig2.observe(subject2, "missing")
    rig2.observe(subject2, "error")
    assert [row["status"] for row in rig2.lifecycles()] == ["subject_deleted"]


def test_unverified_or_failed_absence_cannot_terminalize(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    _visible(rig, subject)
    rig.observe(subject, "missing", outcome="failed")
    assert [row["status"] for row in rig.lifecycles()] == ["subject_unavailable"]
    observations = rig.audit("subject_observation")
    assert observations[-1]["outcome"] == "invalid"
    assert observations[-1]["reason_codes"] == ["authenticity_failed"]

    # Accepted resolver testimony may terminalize.
    rig.observe(subject, "missing")
    assert [row["status"] for row in rig.lifecycles()] == ["subject_deleted"]
    assert rig.visible_count() == 0


def test_adverse_start_initializes_terminal_without_flashing_visible(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path / "mismatch")
    subject = rig.post()
    submission = rig.submit(subject)
    _, variant = rig.admit(submission, subject)
    rig.observe(subject, "mismatch", triggering=variant)
    (lifecycle,) = rig.lifecycles()
    assert lifecycle["status"] == "stale_cid"
    assert lifecycle["start_observation_key"] is not None
    assert rig.visible_count() == 0

    rig2 = Rig(tmp_path / "deleted")
    subject2 = rig2.post()
    submission2 = rig2.submit(subject2)
    _, variant2 = rig2.admit(submission2, subject2)
    rig2.observe(subject2, "missing", triggering=variant2)
    assert [row["status"] for row in rig2.lifecycles()] == ["subject_deleted"]
    assert rig2.visible_count() == 0


def test_future_dated_removal_still_masks_and_keeps_finding(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    subject = rig.post()
    _, admission = _visible(rig, subject)
    future = (T0 + timedelta(days=1)).isoformat().replace("+00:00", "Z")
    rig.remove(admission, subject, created_at=future)
    assert [row["status"] for row in rig.entries()] == ["removed"]
    assert rig.visible_count() == 0
    rows = rig.audit("removal")
    assert [row["outcome"] for row in rows] == ["valid"]
    assert [row["reason_codes"] for row in rows] == [["created_at_future"]]
