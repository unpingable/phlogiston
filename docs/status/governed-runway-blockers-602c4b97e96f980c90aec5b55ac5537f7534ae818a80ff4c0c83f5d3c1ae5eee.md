# Governed V0 runway blocker report

**Schema:** factual-governed-runway-status-v1

**Authority effect:** none

**Source commit:** `f2d784236eda75bb350b51bed503ec1aa51c7b7e` (base for the
V0-M5 working tree described below)

**Observed at:** `2026-08-14T15:59Z`

**Scope:** committed artifacts at the source commit, the V0-M5 working-tree
change executed on top of it, and executable gates in the current checkout

**Rulings made:** none

This note does not select an operator answer, ratify a contract, accept a
digest, create a receipt, or change `BUILD.md`. It records task execution
under an existing controller-entry packet; the controller retains all
commit, receipt, and gate authority.

## Governed task execution record (2026-08-14)

Under controller-entry packet `CEP-V0-M4-M5-2026-08-14-01`:

| Task | State | Evidence |
|---|---|---|
| `V0-M4` | completed as a governed task | commit `f2d7842`; `./scripts/v0-gate V0-M4` PASS; evidence bundle retained by the controller |
| `V0-M5` | implemented in the current working tree under the same packet; pending controller commit and gate run | `packages/communitywatch-web` (read-only canonical AppView subprocess), `communitywatch` read-only store / projection-state / audit-operation / audit-renderer extensions, boundary and acceptance tests |

`V0-M1`, `V0-M2`, and `V0-M2A` remain implementation-complete but
pre-governance, as recorded in the prior runway reports; `V0-M3` likewise
remains implementation-complete-but-pre-governance (its committed artifacts
predate the governed-loop runway). No earlier task state is altered by this
note.

## V0-M5 content summary

- New distribution `communitywatch-web`: stdlib-only HTTP surface serving
  `GET`/`HEAD` for `/c/{slug}`, `/c/{slug}/audit`,
  `/api/v0/communities/{did}/posts`, `/api/v0/communities/{did}/audit`, and
  `/health`, with the plan's exact wire shapes, error vocabulary, and
  security headers; dependency closure is `communitywatch` +
  `community-model` only.
- The web process opens the observer SQLite database URI `mode=ro` with
  `PRAGMA query_only=ON`, performs no migration, no write, and no network
  resolution in a request, and drops every environment variable outside a
  small allow-list at entry.
- `communitywatch` gained a read-only store mode (all write paths refuse),
  committed projection-state introspection for health/freshness, the audit
  row `operation` field required by the plan's wire shape, and an escaped
  HTML audit-log renderer.
- Boundary tests now cover the web distribution's import graph and prove
  the web layer cannot mutate SQLite; acceptance tests cover the lifecycle
  over HTTP, the subprocess boundary with daemon variables present, and
  concurrent WAL ingest versus web reads.

## Validator execution

| Command | Classification | Exact result |
|---|---|---|
| `./scripts/check` | repository formatting, test, and package-boundary check; not a roadmap/governance validator | 431 tests passed; Ruff check and format check passed |
| `./scripts/v0-gate V0-M5` | governed task gate | run by the controller after commit; not executed as part of this note |
