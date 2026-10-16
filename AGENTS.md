# Agent instructions

Read `BUILD.md`, `DOCTRINE.md`, and `IDEAS.md` before modifying code or design
documents. `BUILD.md` authorizes work and bounds V0; `DOCTRINE.md` is normative
for architecture; `IDEAS.md` is context and does not expand scope. `ROADMAP.md`
names candidate slices above V0 and is non-authorizing; a slice becomes work
only through a `BUILD.md` amendment naming its ID.

## Non-negotiable invariants

1. Do not modify or fork PDS behavior.
2. Posts remain in the author's repository.
3. Submission and admission subjects use both AT URI and exact CID.
4. Labels may provide presentation hints only. They may not represent
   admission, membership, roles, or moderation authority.
5. `communitywatch` is detect-only and read-only with respect to ATProto. It
   must have no writer credentials, signing dependency, or code path capable
   of emitting authority records.
6. `communityd` is the sole authority-bearing writer. It must use separate
   configuration, credentials, process boundaries, and package dependencies.
7. Removing a post from a community changes the assembled view. It must not
   delete or mutate the underlying user record.
8. Ranking is view policy. V0 uses reverse chronological order only.
9. Do not implement anything listed as out of scope in `BUILD.md`.
10. Never read, create, copy, log, or commit production credentials.

## Package and dependency boundary

- Shared code is limited to inert schemas, value types, validation, and
  deterministic projection rules. It must not contain transport clients,
  credentials, or signing behavior.
- `communitywatch` may depend on the shared package. It must not depend on or
  import `communityd` or any ATProto write adapter.
- `communityd` may depend on the shared package and its own writer interface.
- Observer and emitter configuration must remain disjoint, even when both are
  developed in this repository.
- SQLite, future Parquet artifacts, DuckDB queries, manifests, and observer
  receipts are observation infrastructure only. They never confer community
  authority, and `communityd` must not read or depend on them.

## Donor repository

`../labelwatch` is read-only reference material.
`../driftwatch` is also read-only and may be consulted only for the explicitly
documented DuckDB/Parquet storage seam. Do not modify either sibling.

Before copying code, record in `docs/REUSE-MATRIX.md`:

- original module and function;
- why it is reusable;
- changes made;
- applicable license; and
- whether observer-only assumptions remain safe or become unsafe.

Do not modify donor/reference repositories. Any copied Driftwatch code has the
same provenance, boundary-review, and license requirements as Labelwatch code.
Do not inherit Labelwatch identity,
terminology, DIDs, keys, configuration, or implied neutrality.

## Work discipline

- Make one bounded milestone per commit.
- Add tests before or alongside implementation.
- Run the complete check suite before reporting completion.
- Do not silently resolve protocol or governance ambiguities.
- Record genuinely blocking decisions in `docs/OPEN-QUESTIONS.md`.
- Prefer a small vertical slice over generalized abstractions.
- Phase 0 is documentary only. Begin a named implementation milestone only on
  an explicit implementation task; that changes no architectural invariant.
