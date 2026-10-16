# SCV0-L5 — Spaces authority occurrence construction

Status: fixture-qualified 2026-08-24; transport integration pending.

## Boundary

`communityd` now owns the only code that can construct experimental Juniper
admission and removal records. It consumes an exact submission/source or
admission/source pair, a bounded source-observation reference, and one local
per-occurrence moderator authorization. It then presents exactly one immutable
authority record to an isolated Spaces writer port.

The local operating-system principal is checked before credential access. The
configured administrator DID cannot be supplied by the caller. The resulting
`ModeratorAuthorization` binds action, community, exact M1 occurrence,
authorization basis, provenance, and a short validity interval. Its identity
is the deterministic record key.

An authorization occurrence is consumed before the one writer attempt.
Reusing it, even for the identical request, refuses. A transport must settle
an ambiguous attempt through exact readback; callers may not blindly retry.

## Claims and non-claims

The module establishes deterministic authority-record construction under the
existing local `communityd` authorization boundary. A supplied observation
receipt remains an evidence reference; `communityd` does not read an observer
database or derive authority from it. The record must return through normal
Space observation and qualification before public projection changes.

An admission is not source ownership, membership, standing, truth, or reader
authorization. A removal changes only Juniper's projection decision and has no
source update/delete operation.

## Witnesses

Fixtures cover exact admission construction, actor-only writing,
authorization replay refusal before a second write, cross-author and stale
authorization refusal, and removal targeting the exact admission while leaving
the author source outside the writer call.
