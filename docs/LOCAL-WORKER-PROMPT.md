# Local-worker prompt (atproto-community)

Status: repo-local specialization of the standing local-worker policy. This
document is **not** a new authority mechanism. It creates no new admissibility
campaign, no new record type, no new governance surface, and no new trust
vocabulary. It describes how a local (Ollama) implementation worker may be used
inside boundaries this repository already defines.

Purpose: use local inference as an implementation worker, and reserve frontier
inference for architecture, review, and acceptance. Candidate work is cheap.
Acceptance is expensive.

## 0. Precedence

For a local-worker pass, the following hard rules are in force:

* **NO COMMITS**
* **NOTHING STAGED**
* **NO PUSHES**
* **NO DEPLOYMENT**

These **override** the normal `AGENTS.md` work discipline requiring one bounded
milestone per commit. That discipline is not repealed; it is deferred. The
later frontier audit/acceptance pass owns committing accepted work, and it
commits under the ordinary `AGENTS.md` rule.

Every other repository instruction remains fully in force: `BUILD.md`,
`DOCTRINE.md`, `AGENTS.md` invariants, the package and dependency boundary, the
donor-repository rules, and the credential prohibition.

Additional standing prohibitions for a local-worker pass:

* Do not modify remotes, branch history, release state, or production services.
* Do not weaken tests or acceptance criteria to make local-model output pass.
* Do not opportunistically refactor unrelated code.
* Do not let the local model choose architecture for security-sensitive,
  concurrency-sensitive, protocol-semantic, or persistent-state boundaries.
* Never read, create, copy, log, or commit production credentials.

## 1. Authority model: reuse the repository's existing split

Do not invent a parallel candidate/admission mechanism. The local-worker rule
maps directly onto structure this repository already has:

* local-model output is **submitted candidate work**;
* frontier review/acceptance is the **admission boundary**;
* `communitywatch` remains detect-only and carries no writer or signing
  authority;
* `communityd` remains the sole authority-bearing writer;
* SQLite, Parquet, DuckDB, receipts, caches, indexes, and other observational
  or derived state never acquire authority merely because they contain derived
  information.

The governing rule:

> **Local models may produce candidate artifacts. They may not independently
> cause admission or otherwise advance authority-bearing/canonical state.**

Local inference **may**:

* write candidate source;
* write tests;
* generate fixtures;
* propose documentation;
* perform repository archaeology;
* suggest cleanup.

Local inference **may not** independently:

* commit, merge, publish, or deploy;
* alter canonical data;
* emit or shape an authority-bearing record;
* declare qualification;
* weaken an acceptance boundary;
* decide that an architectural contradiction is harmless.

## 2. Invariants a local worker must not reinterpret

These are existing repository invariants, restated here because they are the
specific things a local model gets wrong. They are protected, not re-derived.

1. Submission and admission subjects retain **both** AT URI and **exact CID**.
2. Labels are presentation/observation hints only. They never define
   membership, admission, authority, or roles.
3. `communitywatch` is detect-only and read-only with respect to ATProto: no
   writer credentials, no signing dependency, no code path capable of emitting
   authority records.
4. `communityd` is the sole authority-bearing writer, with separate
   configuration, credentials, process boundaries, and package dependencies.
5. Removal changes the admitted/projected view. It does not delete or mutate
   the underlying ATProto record.
6. SQLite, Parquet, DuckDB, receipts, and other derived stores do not confer
   authority, and `communityd` must not read or depend on them.
7. PDS behavior is not modified or forked; posts remain in the author's
   repository.
8. Ranking is view policy. V0 is reverse chronological only.

If a task appears to require weakening or reinterpreting any of these, do not
delegate it and do not resolve it locally. Classify it **FRONTIER-ONLY /
DEFER** and report it.

## 3. `BUILD.md` remains the authorization gate

`ROADMAP.md`, `ROADMAP2.md`, `IDEAS.md`, `PRODUCT-DIRECTION.md`, backlog
material, TODOs, and **this document** do not authorize implementation scope.
Existing `BUILD.md` authorization remains controlling; a slice becomes work
only through a `BUILD.md` amendment naming its ID.

If a local-worker pass identifies useful work outside currently authorized
`BUILD.md` scope, then it:

* **may** produce a bounded candidate/prototype where that is useful;
* **must** label the result `UNAUTHORIZED_PENDING_BUILD_AMENDMENT`;
* **must not** describe the work as implemented or accepted scope;
* **must not** cross any authority-bearing boundary.

Product bias (§7) means avoiding unnecessary formal machinery *inside*
authorized work. It does not override scope authorization.

## 4. Baseline and diff custody

Before touching anything:

* record HEAD, branch, worktree status, and untracked files;
* capture the complete current diff if the tree is already dirty;
* save the baseline under `/tmp/atproto-community-local-worker-baseline-*`;
* distinguish pre-existing work from anything produced during this task.

At the end, report a **task-specific diff against that baseline**, not merely
`git diff HEAD`.

Session scratch space (for example
`/tmp/claude-1000/-data-git-atproto-nutrition/...`) may be used for ephemeral
intermediate files. Authoritative task baselines and the final task-specific
diff record must use the explicitly named
`/tmp/atproto-community-local-worker-baseline-*` artifacts, so that a later
audit does not depend on Claude-session scratch layout.

## 5. Classify before delegating

Read the relevant code, tests, docs, and existing abstractions first. Then
classify:

**A. Safe to delegate substantially to the local model**

Boilerplate; straightforward handlers/endpoints; UI wiring; schema
propagation; repetitive transformations; fixtures; test expansion from an
already-defined invariant; documentation; migration of call sites to an
already-established interface; mechanical refactors with strong tests.

**B. Local model may draft; frontier must personally redesign/review**

Persistence; asynchronous/concurrent behavior; retry/idempotency semantics;
cache invalidation; API compatibility; authorization boundaries;
moderation/label presentation semantics; projection and graph algorithms whose
meaning affects user-visible behavior.

**C. Do not delegate architecture**

AT Protocol semantic interpretation; trust/admissibility/authority rules;
security boundaries; irreversible state changes; protocol compatibility
decisions; anything whose correctness depends on subtle distributed-system
assumptions; anything touching §2.

State the classification briefly, then proceed without waiting unless an
ambiguity is discovered that materially changes the task.

## 6. Ollama as the implementation worker

Default implementation worker for ordinary Category-A work:

```
qwen3.5:27b
```

Do not silently switch among installed models. A different local model may be
used only when Claude states, before delegation, which model and why. Do not
use the prover models (`Kimina-Prover`, `BFS-Prover`, `Leanabell-Prover`) or
`orion-marginalia` as general coding workers.

For each delegated task, give the local model:

* the exact files involved;
* the existing interface/contract;
* explicit acceptance criteria;
* the relevant tests;
* constraints against unrelated refactoring.

Keep its context narrow. Do not dump the repository into it merely because
context is cheap. Prefer several small bounded tasks over one "fix the repo"
request. Record which files, functions, and tests were substantially produced
by local inference.

## 7. Frontier review is mandatory

After every local-model tranche, personally review the diff. Inspect for:

* invented APIs or fields;
* duplicated existing abstractions;
* hidden compatibility changes;
* incorrect ATProto assumptions;
* accidental network calls;
* swallowed errors and broad exception handling;
* state mutations outside the requested scope;
* concurrency and race problems;
* stale-read/write hazards;
* security and privacy leaks;
* tests that merely restate the implementation;
* gratuitous abstraction;
* suspiciously verbose "AI-shaped" code;
* any drift against §2.

Correct or replace local-model code as necessary. **Compilation and passing
tests are necessary, not sufficient.**

## 8. Product bias

Prefer shipping a bounded useful product capability over inventing new
governance or formal machinery. If a feature can be implemented with existing
trust/admissibility/provenance mechanisms, reuse them. Do not turn an ordinary
feature into a new admissibility campaign without an actual
correctness/security reason.

If a deeper architectural issue appears, capture it as a successor note and
continue the bounded product work when safe. Subject always to §3: product bias
does not authorize unauthorized scope.

## 9. Tests

The local model may generate first-pass tests. Review whether they test the
intended behavior rather than the implementation.

* Run focused tests first, then the relevant broader suite.
* Run the lint/format/type checks the repository already uses.
* Do not silently accept pre-existing failures; identify them.
* Any **new** failure is a stop until understood.

Where practical, include negative/adversarial tests for malformed ATProto data;
missing records; stale or cached state; pagination and boundary conditions;
duplicate events; unexpected labels or actors; and unavailable upstream
services.

## 10. No cosmetic rewrite pass

Do not rewrite otherwise-good local-model code merely to make it sound like
Claude. Review for correctness, maintainability, consistency with existing
repository conventions, and unnecessary complexity. Small, boring code that
satisfies the contract beats an elegant new framework.

## 11. Final report

Return:

### RESULT

`READY_FOR_FRONTIER_AUDIT`, `PARTIAL`, or `BLOCKED`
(plus `UNAUTHORIZED_PENDING_BUILD_AMENDMENT` on any out-of-scope candidate)

### IMPLEMENTED

What user/product behavior now exists.

### LOCAL-MODEL CONTRIBUTION

Exact files, functions, and tests substantially drafted by the local model, and
which model produced them.

### FRONTIER REVIEW

What was personally inspected, corrected, or rejected.

### TESTS

Commands and results.

### TASK-SPECIFIC DIFF

Changes relative to the captured baseline, not merely `git diff HEAD` if
pre-existing work existed.

### SUCCESSOR NOTES

Architectural observations deliberately **not** implemented during this task,
including anything classified FRONTIER-ONLY / DEFER.

### WORKTREE

Current branch/HEAD, modified and untracked files, staged state.

Explicitly confirm:

* **NO COMMITS**
* **NOTHING STAGED**
* **NO PUSH**
* **NO DEPLOYMENT**
* **LOCAL-MODEL OUTPUT HAS NOT BEEN DECLARED CANONICAL OR QUALIFIED**

A later Kimi/Codex pass independently audits the candidate diff before anything
becomes canonical.

---

The goal is to finish this feature, not discover reasons we are philosophically unprepared to implement software.
