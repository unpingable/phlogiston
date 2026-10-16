# SA10b — durable sync/reconciliation state

Status: deterministically qualified on 2026-08-21.

The observer-only SQLite store retains append-only, digest-bound acquisition,
cursor, reconciliation, recovery, and initial qualified-state events. A small
head projection changes only when an existing SA6 result is
`qualified_transition` or `snapshot_only`; `equal_state` needs no change and
`insufficient_evidence` never replaces it. Initial seeding is idempotent and a
different seed cannot overwrite an existing head. Closing/reopening and
replaying the same event preserve both event count and semantics.

Cursor values, acquisition timestamps, HTTP status, retries, and persistence
are observations only. They do not prove completeness, freshness, ancestry,
source authority, standing, authorization, or governance authority. Recovery
traces retain missing-provenance fields. Secret-bearing header/token/key/proof
fields are rejected from durable payloads.

This is a directly invoked evidence store, not a scheduler or synchronization
daemon. SQLite schema and projection logic are replaceable without changing
SA1–SA10a receipts or any governance boundary.
