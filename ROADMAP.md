# Roadmap — candidate slice ladder (non-binding)

**Status:** candidate, non-binding, deliberately over-named. Captured 2026-07-14.
This document names slices above V0 under the "name early, ratify lazily"
discipline. A slice appearing here reserves an ID, a vocabulary, and a seam
obligation for review. It authorizes nothing.

Governed execution, including the V0 runway that precedes these slices, is
specified in `docs/GOVERNED-LOOP.md`. That contract is non-authorizing and
remains proposed until OQ-7 selects A or B and its required governance changes
are human-applied.

---

## Status and authorization boundary

- `BUILD.md` is the sole authorizing document. `DOCTRINE.md` remains
  architectural law over every slice named here. `AGENTS.md` invariants bind
  every task. Nothing in this document relaxes a `BUILD.md` non-goal; a slice
  entry is the review packet that could.
- **A slice's status may move to `ratified` only by an amendment to `BUILD.md`
  that names the slice ID. Agents and automation MUST treat a roadmap-only
  status change as invalid and MUST NOT begin implementation from this
  document alone.** "Next authorized work" is always the intersection of slice
  IDs named in `BUILD.md` and the task ladders below — never this document by
  itself.
- If this document and `BUILD.md` disagree, this document is wrong.
- Slices may be merged, split, reordered, or withdrawn at ratification time.
  IDs are never renumbered; a withdrawn slice keeps its ID with a tombstone
  note. The ladder records current best guess, not law.
- This ladder supersedes the `IDEAS.md` V0–V3 compatibility ladder for
  ordering purposes (`BUILD.md` already inverted it by making the web AppView
  canonical). `IDEAS.md` remains non-authorizing context.

## Thesis and organizing principle

The elevator line is "subreddits as an overlay to app-layer Bluesky." The
actual spine is:

> Restore **adjacency as a first-class social primitive** instead of a side
> effect of engagement ranking. Algorithms maximize salience; communities
> depend on things that are initially low-salience and become meaningful
> through recurrence.

The ladder is therefore organized by **what makes a place** — persistence,
recognition, conversation, shared stewardship, memory, portability — not by
Reddit feature parity.

Anti-goal, stated once and binding on every future edit of this file: "reach
Reddit parity" is not a rung and never becomes one. Parity features enter the
ladder only when they serve a place-property, and each entry says which one
honestly (a slice that serves none says `parity — thesis-neutral`).

Standing invariant, binding on every slice: **no regularity or recurrence
projection may authorize, deny, weight, or prioritize an action.** Recurrence
is testimony forever. If a future policy wants membership as an input, it
mints explicit records under S14's gates — a projection never launders into
standing. Social status is very talented at becoming authority through vibes;
this line exists so it would have to do it in writing.

## How to read a slice (automation contract)

This project is a dogfood substrate for governor-loop / constellation
automation, per the `DOCTRINE.md` build condition ("automation-first, not
hands-on"). Every slice entry uses the identical field labels in identical
order so a loop can parse the ladder without human interpretation.

Field grammar:

- **ID / Status:** `S<N>`, stable forever; status is one of
  `parked | candidate | ratified | done`.
  - `parked` — entry evidence not yet observed; do not prepare a packet.
  - `candidate` — forcing case observed or plausible; agents MAY prepare the
    slice-ratification packet.
  - `ratified` — a human has authenticated the slice-ratification decision and
    amended `BUILD.md` naming the slice ID; the slice is in scope and eligible.
    A controller-entry packet is still required for any run. There is no
    separate in-progress state: `ratified` covers active execution.
  - `done` — set by a human at exit review only.
  - Status, entry gates, and `BUILD.md` are human-writable only. Agents never
    self-promote status.
  - IDs are identity, not priority: **ladder order is document order.** A
    slice named late keeps its late number even when it sits early on the
    ladder (S18 sits in Tier 2).
- **Type:** `testimony` (observer/view only — adds no authority record kinds,
  no signers, no key custody; the conjunction of guarantee seams does not
  grow) or `guarantee` (expands what the community actor's signature promises
  — heavier gates, solo slice-ratification packets, emit-mode graduation) or
  `mixed` (edge noted inline). A `thesis-experiment` flag marks slices judged by
  the thesis, not by parity.
- **Thesis line:** how the slice serves recurrence/place/memory, or an honest
  `parity — thesis-neutral`.
- **Adds:** / **Still excludes:** scope and the slice's own non-goals.
- **Entry gate (HUMAN):** one batched slice-ratification packet — forcing-case
  evidence, promoted operator-question packets and their human
  operator-decision receipts, plus exact proposed `BUILD.md` and roadmap change
  sets. One sitting; agents pre-draft every non-ruling field and patch.
- **Blocking OQs:** references into `docs/OPEN-QUESTIONS.md` (OQ-N) and the
  candidate register below (OQ-R\*).
  `none registered` means only that no handle exists yet. Every unresolved
  human policy or shape choice encountered during eligible packet preparation
  MUST be promoted to a numbered OQ and receive an operator-question packet;
  the slice-ratification packet cannot carry an unreceipted free-form ruling.
- **Donor assets:** pinned modules per `docs/REUSE-MATRIX.md` (labelwatch
  `7f04bdd4`, driftwatch `6227bd81`). Every borrow lands in the matrix first.
- **Replay seam obligation:** what the slice must preserve so fork/replay
  (S13) stays possible. A candidate slice that cannot fill this field is
  misdesigned; redesign before ratification.
- **Deliverables:** named artifacts.
- **Task ladder (MACHINE):** commit-sized tasks in the style of
  `docs/IMPLEMENTATION-PLAN.md` milestones. Each done-condition is the exit
  code of a named command — pass/fail is never decided by eyeballing output.
  Command names are indicative until the slice-ratification packet's exact
  task-manifest/governance changes are human-applied.
- **Exit review (HUMAN):** the acceptance question, answered against a
  prepared execution-evidence bundle (rendered pages, receipts, audit exports,
  test transcripts) so the human gate is cheap. Verdict recorded in the exit
  field and a slice-exit human-acceptance receipt.
- **Evidence log:** content-addressed pointers to externally retained receipts,
  test output, and screenshots. Implementation tasks cannot modify this
  protected file. A pointer is appended only by a separately authorized
  evidence-index task or by the human exit review; no other slice field is
  agent-writable.
- `Authorized: no` — a literal line in every entry. It flips only alongside
  the `BUILD.md` amendment, in the same commit.

These artifact names follow `docs/GOVERNED-LOOP.md`: the
slice-ratification packet is the human governance bundle; an
operator-question packet is an unsigned proposal inside it; a
controller-entry packet separately bounds execution; and an
execution-evidence bundle records what ran. None substitutes for another.

Slice lifecycle: **(a)** human slice ratification → **(b)** autonomous execution
under machine gates only → **(c)** human exit review.

Standing machine gates for every slice, in addition to its own ladder: the
full test suite; the boundary/isolation suite (observer cannot reach writer
code paths, `communityd` cannot reach observer storage); and the
rebuild-parity test (projections rebuilt from immutable observations
byte-compare equal). Guarantee-typed slices that touch `communityd` emission
additionally graduate each new capability through driftwatch-style emit modes:
detect-only → quarantine → emit, with emit refused absent an explicit confirm
environment variable, each step its own commit with its own gate.

The canonical selection and stop rules are in
`docs/GOVERNED-LOOP.md`. In summary, the loop must finish the V0 runway before
it examines this slice ladder. Inside the slice lane, the next task is the first
failing side-effect-free done-condition in the earliest slice for which all of
these independently agree: canonical status `ratified`; literal
`Authorized: yes`; positive `BUILD.md` authorization naming the exact ID; a
valid slice-ratification receipt; completed dependencies; and resolved
blockers. It may not skip a blocked slice, infer authorization from a mention
in prose, or advance past machine-complete work awaiting human exit review.

If no slice is executable, a controller-entry packet may separately authorize
preparation of the earliest candidate slice-ratification packet whose
prerequisites exist. Packet preparation then stops for human review and cannot
change a status, `Authorized` line, or entry gate.

This contract is prose until it is enforced. `V0-G0` in
`docs/GOVERNED-LOOP.md` creates the strict task manifest, operator-question and
operator-decision-receipt validators, execution-evidence validator, and
mechanical **roadmap linter**. The linter must parse this file into a canonical
AST and reject missing, duplicate, or unknown fields; unknown status or base
type values; overview-table/section mismatches; incomplete dependency metadata;
and any disagreement among status, `Authorized`, `BUILD.md`, operator-question
packets, operator-decision receipts, slice-ratification receipt, blockers, or
dependencies. It uses valid and invalid golden fixtures and returns its verdict
by exit code. A loop must never infer authority from permissive Markdown parsing.

The current candidate inventory contains descriptive status/type qualifiers
and prose-only dependencies that are not yet canonical linter input. `V0-G0`
must report those mismatches and prepare a human-reviewed normalization patch;
it must not silently reinterpret or rewrite slice classifications.

**V0 runway (historically called the S0 reference row; not a slice):** the
current tree contains Phase 0 documents and no implementation milestone may be
presumed complete. Governed execution therefore starts with `V0-G0`, freezes
the M1 contracts and golden fixtures in `V0-D1`, then runs `V0-M1` through
`V0-M8` in the order defined by
`docs/GOVERNED-LOOP.md` and `docs/IMPLEMENTATION-PLAN.md`. After G0/D1 review,
M1–M3 are offline and have no further human blocker when donor code is
inaccessible; M4 requires OQ-5; M6 requires OQ-2; M7 requires
OQ-1/OQ-3/OQ-4; OQ-6 applies only if donor source will be copied; and M8 stops
for the human trial and verdict. **The entire slice ladder gates on that V0
verdict:** "feels like a real place" → the S1 packet may be considered; "feed
wearing a trench coat" → halt the ladder.

### Slice-lane normalization backlog

These are known review debts, not agent-editable slice decisions. They do not
block the V0 runway. They do make the post-V0 lane `CONTRACT_INVALID` until a
human-approved governance patch resolves them:

- normalize descriptive status/type spellings to a strict base enum without
  changing their intended meaning, and define an explicit tombstone state for
  withdrawn IDs;
- add canonical dependency, authority-delta, execution-class, stable task-ID,
  exact verification-command, operator-question-packet,
  operator-decision-receipt, required-change-set,
  slice-ratification-receipt-ID, and
  slice-exit-human-acceptance-receipt-ID fields before any candidate becomes
  ratified; applied roadmap bytes record only each predeclared stable receipt
  ID, while a later controller-entry packet pins the receipt digest;
- define a human-approved and human-applied positive-authorization table in
  `BUILD.md` so a linter cannot mistake an ID mentioned in a non-goal or
  historical note for scope;
- review S2's `testimony` classification because its generator record and
  `communityd` emission path add an authority-bearing write;
- split or reorder S8's thread-lock work, which currently requires S10 even
  though S8 precedes S10 and its entry gate names only S6/S7;
- distinguish OQ-1's pre-V0-M7 permanent namespace decision from S1's later
  production publication/deployment step; and
- define S1's production network, credential, deployment, and exercise modes
  explicitly rather than extending or relabeling a V0 non-production mode.

`V0-G0` may lint and report this backlog. It may not resolve classifications,
dependencies, or governance semantics on a slice's behalf.

## Ladder overview

| ID | Name | Tier | Type | Status | Blocking |
|----|------|------|------|--------|----------|
| S1 | Production community actor & deployment | 1 | guarantee | candidate | OQ-1, OQ-6, OQ-R1 |
| S2 | Feed-generator door | 1 | testimony | parked | OQ-R2 |
| S3 | Regulars: recurrence made visible | 2 | testimony · thesis-experiment | parked | OQ-R4 |
| S4 | Community memory | 2 | testimony · thesis-experiment | parked | — |
| S18 | Conversation surface: reply-tree projection | 2 | testimony · thesis-experiment | parked | — |
| S5 | Restore / readmission | 3 | guarantee | parked | OQ-R5 |
| S6 | Roles & delegated moderation | 3 | guarantee (heavy) | parked | OQ-R6, OQ-R7 |
| S7 | Rules & community self-description | 3 | mixed (light guarantee) | parked | — |
| S8 | Bans & locks | 3 | guarantee (heavy) | parked | OQ-R8 |
| S9 | Multiple communities & discovery | 4 | mixed | parked | OQ-R9, OQ-R14 |
| S10 | Comment moderation & inclusion policy | 4 | guarantee | parked | OQ-R10 |
| S11 | Votes & community-scoped ranking | 4 | mixed | parked | OQ-R11 |
| S12 | Managed cold-path operation | 4 | testimony | parked | — |
| S13 | Fork / import / replay | 5 | guarantee (heaviest) | parked | OQ-R12 |
| S14 | Explicit membership records | 6 | guarantee | parked | OQ-R3 |
| S15 | Community-aware client | 6 | testimony-flavored | parked | — |
| S16 | Private communities | 6 | guarantee (maximal) | parked | upstream protocol gap |
| S17 | Reports & T&S infrastructure | 6 | guarantee-adjacent | parked | — |

---

## Tier 1 — Prove and harden

### S1 — Production community actor & deployment

- **ID / Status:** S1 — candidate
- **Type:** guarantee (first production keys; first permanent namespace)
- **Thesis line:** a place must have a stable address before anything can
  recur at it. Every thesis claim below is longitudinal; S1 exists to let time
  pass in one place.
- **Adds:** permanent lexicon NSIDs published (retiring `invalid.community.*`
  wholesale, per OQ-1); a production community DID with real key custody;
  hardened deployment of `communitywatch-web` and `communityd` under separate
  OS principals (systemd); backup/restore of observer state; health and
  staleness surfaces; emit-mode graduation of `communityd` from lab to live.
- **Still excludes:** any new record kinds; any second operator; feedgen;
  multi-community; everything else on this ladder.
- **Entry gate (HUMAN):** one packet: V0 exit verdict recorded as "feels
  real"; OQ-1 namespace decision; OQ-R1 key custody and rotation policy;
  OQ-6 license closure before further donor copies; production go/no-go.
  Plus one unbatchable ceremony: production key generation and custody
  handoff — never delegated to automation.
- **Blocking OQs:** OQ-1, OQ-6, OQ-R1
- **Donor assets:** labelwatch `server.py` (`_TokenBucket`, `_DiskCache`,
  kill switch, read-only connections) and `deploy/*.service` hardening with
  split principals; driftwatch `emit_mode.py` (three-mode gate),
  `facts_export` atomic snapshot (`VACUUM INTO` + rename) for backups;
  driftwatch golden-fixture harness as the release regression gate.
- **Replay seam obligation:** published NSIDs are permanent protocol surface —
  frozen forever. Key rotation is recorded as events so historical signatures
  remain verifiable after rotation. Deterministic rkeys and strongRef
  discipline carry over unchanged.
- **Deliverables:** `lexicons/<ns>/*.json` (four, published); credential
  provider adapter and custody doc; systemd units + hardening assertions;
  backup/restore scripts; emit-mode harness; staging deployment; ops runbook
  stub.
- **Task ladder (MACHINE):**
  1. NSID migration in one atomic commit — done when a grep gate finds zero
     draft NSIDs outside history docs and the full suite exits 0.
  2. Credential provider adapter + custody doc — done when the boundary suite
     (`pytest -m boundary`) still proves the observer cannot import it.
  3. Systemd units with split principals — done when a scripted assertion of
     no shared principal / no cross-writable path exits 0.
  4. Backup round-trip — done when snapshot → restore → rebuild byte-compares
     the projection (script exits 0).
  5. Emit-mode harness — done when emit is refused without the confirm env in
     `pytest tests/daemon/test_emit_mode.py`.
  6. Staging deploy + health smoke — done when the smoke script exits 0.
- **Exit review (HUMAN):** *Can a stranger arrive at the same address a week
  later and find the same place, with its memory intact — and can the operator
  sleep?* Evidence: uptime receipts, health output, backup-drill transcript,
  an outsider walkthrough.
- **Evidence log:** (empty)

Authorized: no

### S2 — Feed-generator door

- **ID / Status:** S2 — parked
- **Type:** testimony (read-only projection of the admitted set)
- **Thesis line:** a feed is a slit in the wall; a community is a room. This
  slice is reach, not adjacency — it exists to recruit the repeat visitors the
  thesis experiments need, and it is reversible.
- **Adds:** an `app.bsky.feed.generator` surface over the committed observer
  projection, reverse-chronological by admission time only, every item linking
  back to the AppView permalink. The generator record itself must be emitted
  by `communityd` (the observer cannot publish records — OQ-R2 settles where
  the feedgen's serving identity lives; likely a third small process that is
  neither observer nor authority).
- **Still excludes:** any ranking; feed-only features; the feed never becomes
  the canonical surface — the AppView remains the room.
- **Entry gate (HUMAN):** packet: `BUILD.md`'s own condition (canonical
  AppView proof works live) plus trial evidence that people will not visit a
  standalone page; OQ-R2 decision; ratify the "feed stays lossy" non-goals.
- **Blocking OQs:** OQ-R2
- **Donor assets:** labelwatch `server.py` rate-limit/cache/kill-switch
  patterns.
- **Replay seam obligation:** none new — a pure view over replayable
  admissions.
- **Deliverables:** feedgen skeleton service + DID doc; contract tests against
  the feedgen spec; generator-record emission path through `communityd`
  (dry-run → emit).
- **Task ladder (MACHINE):**
  1. Skeleton endpoint + DID doc — done when the feedgen contract suite
     exits 0.
  2. Admitted-set parity — done when feed output equals the AppView JSON for
     the same generation (`pytest tests/feedgen/test_parity.py`).
  3. Pagination/cursor semantics — done when the cursor suite exits 0.
  4. No-ranking gate — done when output order equals admission order in
     `pytest tests/feedgen/test_order.py`.
- **Exit review (HUMAN):** *Does the feed act as a door into the room, or has
  it quietly become the place?* Evidence: referral flow from feed to page,
  side-by-side screenshots. An honest "the feed became the place" is a thesis
  failure signal and grounds for reversal.
- **Evidence log:** (empty)

Authorized: no

## Tier 2 — Thesis experiments

Deliberately ahead of governance depth: observer-only, guarantee-free, cheap —
and they test the actual thesis. Recognition (S3), memory (S4), and the
conversation surface (S18) — because adjacency forms in the talk, and without
it S3 would only recognize recurring submitters and S4 would remember exhibits
in a gallery; the V0 acceptance question would be structurally prevented from
passing. If these land flat, that is decision-grade evidence before any
authority expansion is paid for.

### S3 — Regulars: recurrence made visible

- **ID / Status:** S3 — parked
- **Type:** testimony · thesis-experiment
- **Thesis line:** a regular is someone the place recognizes; today only
  engagement ranking recognizes anyone. This is the core experiment —
  adjacency through recurrence made legible without a scoreboard.
- **Adds:** observer-side identity continuity (DID-stable across handle
  churn); a regulars projection derived from the admission ledger (tenure,
  streaks, first-seen/last-seen); AppView affordances — "regular since March,"
  first-admitted date, quiet presence markers on post cards. Deliberately NO
  join records and NO membership authority: the slice tests whether
  recognition can be built from observation alone before any authority is
  minted (this is the experiment that informs OQ-R3 / S14). Once S18 renders
  threads, whether reply participation counts toward recurrence is an OQ-R4
  packet decision — the aim is recognizing inhabitants, not just submitters.
- **Still excludes:** membership records, badges-as-authority, karma,
  leaderboards, any recurrence rendered as a rankable number — a score
  reintroduces salience through the side door.
- **Entry gate (HUMAN):** packet: forcing-case evidence (audit log shows the
  same DIDs recurring across ≥ N distinct weeks — the loop can detect this and
  prepare the packet); OQ-R4 decisions (recurrence predicate with exact
  numbers, display-consent stance, anti-leaderboard rule).
- **Blocking OQs:** OQ-R4 (OQ-R3 is informed by this slice, not blocking it)
- **Donor assets:** driftwatch `resolver.py` + `identity.py` (async DID
  resolver, fieldwise identity reducer); labelwatch `derive.py` organization
  (pure classifiers, frozen values, no moral vocabulary).
- **Replay seam obligation:** the recurrence policy is versioned view policy
  (doctrine clause 6), declared non-portable; regulars derive only from
  admission events, so a fork recomputes its own regulars for free. Machine
  test: recompute from the event log alone, compare to the projection.
- **Deliverables:** pure recurrence reducer in `community_model`;
  generation-scoped regulars tables; regulars page + JSON endpoint;
  identity-resolver adapter with offline fake; golden fixtures (synthetic
  multi-month admission histories); recurrence-policy version note.
- **Task ladder (MACHINE):**
  1. Pure recurrence reducer — done when
     `pytest tests/model/test_recurrence.py` (including determinism under
     replay) exits 0.
  2. Derived tables + rebuild parity — done when the rebuild byte-compare
     exits 0.
  3. Identity continuity across handle churn — done when
     `pytest tests/watch/test_identity_resolver.py` exits 0 on churn fixtures.
  4. Web surfaces, escaped and cached — done when API contract + escaping
     suites exit 0.
  5. Golden end-to-end — done when fixture history → expected regulars
     JSON/HTML byte-compare exits 0.
- **Exit review (HUMAN):** *Can you recognize faces? Do returning contributors
  become recognizable to each other without a scoreboard — does coming back
  feel noticed?* Evidence: rendered regulars page, post-card markers, cohort
  distribution, the policy note. The answer feeds OQ-R3.
- **Evidence log:** (empty)

Authorized: no

### S4 — Community memory: low-salience resurfacing

- **ID / Status:** S4 — parked
- **Type:** testimony · thesis-experiment
- **Thesis line:** a place remembers; a feed only refreshes. This is doctrine
  clause 6 used *for* the thesis — ranking-as-view-policy pointed away from
  engagement: resurface by age, recurrence, and anniversary, never by
  interaction velocity.
- **Adds:** archive/timeline view over the full admission ledger; "on this
  date / N months ago in this community" resurfacing, with windows that grow
  as the ledger ages (anniversaries arrive when a year of history exists —
  the affordance must not outrun the clock); a deterministic, seeded,
  receipted resurfacing slot on the main page (selection inputs published so
  the choice is reconstructible by anyone); the modlog reframed as readable
  community history rather than compliance exhaust; durable permalinks that
  render admission context.
- **Still excludes:** notifications and push (memory is ambient, not
  interruptive — an explicit anti-salience stance); personalization; any
  engagement-derived input; any new records.
- **Entry gate (HUMAN):** packet: enough calendar history that things worth
  remembering have scrolled away (≥ ~90 days live); memory-view policy
  ratification (which views, selection seed rule).
- **Blocking OQs:** none registered — eligible packet preparation must promote
  the memory-view choices to numbered OQs. Long-window queries may couple to
  V0-M2A's sealed history if the hot store strains; that coupling is noted,
  not assumed. Managed operation beyond the explicit V0 CLI remains S12.
- **Donor assets:** labelwatch `receipts.py` / `utils.py` (`stable_json`,
  `hash_sha256`) for selection receipts; driftwatch golden-fixture harness
  (deterministic selection is golden-testable).
- **Replay seam obligation:** memory views are recomputable projections over
  the event ledger; selection policies are versioned with published inputs. A
  fork inherits its memories.
- **Deliverables:** deterministic selection function (seeded by date +
  generation); timeline query layer; anniversary surface; selection receipts;
  golden fixtures.
- **Task ladder (MACHINE):**
  1. Selection function — done when the reproducibility test (same seed +
     inputs → identical selection) exits 0.
  2. Timeline queries + pagination — done when the suite exits 0.
  3. Anniversary surface — done when fixture snapshot compare exits 0.
  4. Selection receipts — done when receipt emission/verification tests
     exit 0.
- **Exit review (HUMAN):** *Does the place remember things its members had
  forgotten — and does an old post resurfacing feel like an anniversary
  rather than spam?* Evidence: rendered memory panel, selection receipts,
  timeline screenshots.
- **Evidence log:** (empty)

Authorized: no

### S18 — Conversation surface: reply-tree projection

- **ID / Status:** S18 — parked
- **Type:** testimony · thesis-experiment
- **Thesis line:** adjacency actually forms in the talk, not the posts; a
  place without conversation is a gallery. Split from S10 so the thesis can be
  tested where adjacency happens without minting any authority.
- **Adds:** read-only ingestion and rendering of `app.bsky.feed.post` reply
  trees under admitted posts, under one fixed v0 inclusion rule: all public
  replies beneath an admitted root render; removal of the root hides the
  thread. The projection reflects existing post-level outcomes only. Threads
  refuse to render incomplete rather than misleading. This is the first real
  ingestion-load test.
- **Still excludes:** reply-specific authority of any kind — no per-reply
  remove/restore, no inclusion-policy records, no locks (those are S10 and
  S8); votes; notifications; native comment records.
- **Entry gate (HUMAN):** packet: trial evidence that conversations about
  admitted posts are happening in bare Bluesky replies, invisible from inside
  the room; a bounded ingestion-scope decision (the blast radius of watching
  reply graphs); ratify the fixed v0 inclusion rule.
- **Blocking OQs:** none registered — eligible packet preparation must promote
  the ingestion-scope and inclusion-rule choices to numbered OQs.
- **Donor assets:** driftwatch `consumer.py` (batched writes, cursor
  persistence, backpressure, disk brake — reply volume is the first real
  backpressure test); driftwatch admissibility protocol
  (refuse-to-render-incomplete).
- **Replay seam obligation:** pure projection over replayable admissions and
  public replies; the fixed inclusion rule is versioned in a policy note so a
  fork can reproduce thread visibility. When S10 mints the inclusion-policy
  record, that record supersedes the note.
- **Deliverables:** reply-tree collection filter; thread projection reducer
  (render/hide with root state, exact-CID discipline per observed reply);
  thread view; golden thread fixture.
- **Task ladder (MACHINE):**
  1. Reply ingestion filter — done when the load-fixture suite exits 0.
  2. Thread projection reducer — done when render/hide fixtures exit 0.
  3. Thread rendering — done when escaping/pagination suite exits 0.
  4. Golden thread end-to-end — done when byte-compare exits 0.
- **Exit review (HUMAN):** *Does a thread read as a conversation happening in
  the room, not quoted in from the street?* Evidence: rendered threads beside
  their bare-Bluesky rendering.
- **Evidence log:** (empty)

Authorized: no

## Tier 3 — Governance depth

Guarantee-typed, demand-driven, bought smallest-authority-first:
restore < roles < bans. Each opens on a real operational forcing case, never
speculatively; each ships behind emit-mode graduation; none is batched with
another guarantee slice.

### S5 — Restore / readmission

- **ID / Status:** S5 — parked
- **Type:** guarantee (smallest possible authority extension)
- **Thesis line:** a place that can only exile, never forgive, is a tribunal.
  Recurrence includes coming back.
- **Adds:** a restore event as a new append-only authority record with a
  deterministic rkey (`restore-<sha256>` over the same subject-identity
  scheme); reducer states and precedence for remove → restore cycles; audit
  surface. Precedence respects V0's ratified law: an exact-CID-mismatch
  terminalization is never revived by restore.
- **Still excludes:** author-initiated withdrawal records (OQ-5's current
  recommended stance); appeals workflow; bulk operations.
- **Entry gate (HUMAN):** packet: the first regretted or wrongful removal in
  live operation (this will happen fast); OQ-R5 decision.
- **Blocking OQs:** OQ-R5
- **Donor assets:** existing V0 reducer/state-machine machinery; labelwatch
  receipts pattern for decision provenance.
- **Replay seam obligation:** restore never mutates the remove — corrections
  are new events; precedence is order-insensitive under the state machine's
  existing replay/duplicate rules, so total order is deterministic.
- **Deliverables:** restore lexicon; reducer extension + exhaustive transition
  fixtures; `communityd` CLI verb; audit rendering.
- **Task ladder (MACHINE):**
  1. Lexicon + validation — done when schema suite exits 0.
  2. Reducer precedence — done when exhaustive transition fixtures (including
     restore-after-stale-cid rejected) exit 0.
  3. Daemon verb + idempotent write — done when the idempotency suite exits 0.
  4. Audit surface — done when rendering tests exit 0.
- **Exit review (HUMAN):** *When the community un-removes something, does the
  audit trail read as a change of mind rather than an erasure?* Evidence: a
  full remove → restore cycle's audit export.
- **Evidence log:** (empty)

Authorized: no

### S6 — Roles & delegated moderation

- **ID / Status:** S6 — parked
- **Type:** guarantee — HEAVY. First slice where authority validity depends on
  projected state ("was the actor a mod at signing time?"). The largest
  expansion of the guarantee conjunction on the ladder.
- **Thesis line:** a place one person can silently lose is not yet an
  institution; regulars can become stewards.
- **Adds:** role grant/revoke authority events; authority validation as-of
  event time computed **only from ledger-visible facts** — never a mutable
  roles table as source of truth; real delegated admin authentication (OQ-4's
  proposed local-OS model explicitly does not extend here and dies at this
  slice); attribution checked against role validity in every modAction;
  modlog showing actor roles.
- **Still excludes:** role hierarchies beyond one mod tier; elections;
  per-rule permissions; bans (S8); votes on mod actions.
- **Entry gate (HUMAN):** solo packet (never batched): forcing-case evidence
  that the single admin is a latency/availability bottleneck (submission-queue
  age; the constitutional crisis at 2:13 AM); OQ-R6 and OQ-R7 decisions; a
  mandatory firewall re-review — this is the slice most likely to quietly
  become a moderation actor wearing an auditor's jacket.
- **Blocking OQs:** OQ-R6, OQ-R7
- **Donor assets:** driftwatch `label_decisions` receipted-decision ledger;
  labelwatch receipts; driftwatch `emit_mode.py` for each new capability.
- **Replay seam obligation:** grants and revocations are replayable interval
  events; any third party must be able to recompute "was this action
  authorized when signed" with no out-of-band state. A named precondition for
  S13.
- **Deliverables:** role lexicons; authority-interval reducer; delegated
  request-authn adapter behind an interface with an offline fake; boundary
  suite extension; modlog surfaces.
- **Task ladder (MACHINE):**
  1. Role lexicons — done when validation suite exits 0.
  2. Authority-interval reducer — done when property tests over
     grant/revoke/regrant orderings and out-of-order observation exit 0.
  3. ModAction authorization check — done when exhaustive unauthorized-actor
     fixtures exit 0.
  4. Delegated authn adapter + fake — done when contract tests exit 0.
  5. Boundary extension — done when `pytest -m boundary` proves the observer
     still reaches none of it.
  6. Modlog surfaces — done when rendering suite exits 0.
- **Exit review (HUMAN):** *Can a second person act for the place, be seen to
  have acted legitimately, and be revoked — with the whole story readable in
  the modlog?* Evidence: a grant → act → revoke cycle's receipts and modlog.
- **Evidence log:** (empty)

Authorized: no

### S7 — Rules & community self-description

- **ID / Status:** S7 — parked
- **Type:** mixed — rules/about are community-signed records (light guarantee:
  new record kinds, same single signer); flair is presentation only, never
  authority (`AGENTS.md` invariant 4 territory).
- **Thesis line:** bounded places post their rules at the door; boundaries you
  can read are part of what makes a room a room.
- **Adds:** a versioned, append-only rules record (strongRef-able); an
  about/self-description surface; admissions and removals gain an optional
  strongRef to the rules version in force — the constitutional-provenance seam
  fork/replay needs; removal reasons may cite rule IDs; post flair as
  presentation metadata.
- **Still excludes:** user-editable wiki; flair-as-permission; enforcement
  semantics — rules are description, not machinery.
- **Entry gate (HUMAN):** packet: forcing case (first real removal with no
  rule to point at; trial participants asking "what is this place for?");
  rules-record shape and supersession semantics decided in the packet.
- **Blocking OQs:** none registered — eligible packet preparation must promote
  the rules-shape and supersession choices to numbered OQs.
- **Donor assets:** labelwatch `stable_json` / `hash_sha256` for rules-version
  hashing.
- **Replay seam obligation:** rules changes are new records, never mutations;
  every authority record that cites rules does so by strongRef, so replay
  evaluates each decision under the constitution that made it.
- **Deliverables:** rules/about lexicons; citation field on modAction with
  reducer validation; rules page, flair chips, reason-with-rule modlog
  rendering; mid-ledger rules-change fixture.
- **Task ladder (MACHINE):**
  1. Lexicons + versioning — done when validation suite exits 0.
  2. Citation validation (cited version must exist and precede the action) —
     done when fixture suite exits 0.
  3. Rendering + escaping — done when the web suite exits 0.
  4. Mid-ledger rules-change golden — done when byte-compare exits 0.
- **Exit review (HUMAN):** *Can a newcomer tell what the room is for, and what
  gets removed, without asking anyone?* Evidence: rendered rules page and a
  rule-cited removal in the modlog.
- **Evidence log:** (empty)

Authorized: no

### S8 — Bans & locks

- **ID / Status:** S8 — parked
- **Type:** guarantee — HEAVY. Negative authority against persons, not posts;
  first mandatory T&S review.
- **Thesis line:** parity — thesis-neutral. Boundaries are part of what makes
  a bounded place bounded; the law of this slice is the clause-3/4 analog:
  **a ban is exclusion from context, not deletion of a person.**
- **Adds:** ban events (subject = DID, duration/expiry semantics, scoped
  strictly to this community's view: submissions from banned DIDs project to a
  visible non-admitted state, never silently dropped); thread-lock events
  (freeze reply inclusion — requires S18's thread projection and S10's
  reply-scoped authority plumbing); expiry and appeal as new events,
  never mutation; audit-visible throughout — shadow anything contradicts the
  receipts doctrine.
- **Still excludes:** network-level blocks; cross-community ban sharing;
  automated bans; effect on the banned party's previously admitted history
  (recommended: none, per clause 4).
- **Entry gate (HUMAN):** solo packet: forcing-case evidence — a real,
  sustained abuse incident that per-post removal demonstrably cannot keep up
  with (never build ahead of this); OQ-R8 decision; proportional abuse-posture
  review. Requires S6 (bans by delegated mods need role validity) and S7
  (bans cite rules).
- **Blocking OQs:** OQ-R8
- **Donor assets:** emit-mode graduation; receipts/ledger patterns. Nothing
  labeler-domain — `docs/REUSE-MATRIX.md` already rejects the moral-vocabulary
  modules.
- **Replay seam obligation:** bans are interval events like roles; a fork may
  drop the old regime's ban list — that is the point of clause 5 — so bans
  must be cleanly separable in export and the fork must be able to prove what
  it dropped.
- **Deliverables:** ban/lock lexicons; reducer states (banned-author
  submission path, expiry, lock precedence); daemon verbs; locked-thread and
  ban-audit surfaces.
- **Task ladder (MACHINE):**
  1. Lexicons — done when validation suite exits 0.
  2. Reducer states — done when exhaustive fixtures (ban, expiry, lock
     precedence, banned-author submission) exit 0.
  3. Daemon verbs + idempotency — done when the suite exits 0.
  4. Surfaces — done when rendering tests exit 0.
- **Exit review (HUMAN):** *Is exclusion legible — can an observer verify who
  was excluded, by whom, under which rule, for how long — a receipted boundary
  decision rather than a disappearance?* Evidence: ban lifecycle audit export.
- **Evidence log:** (empty)

Authorized: no

## Tier 4 — Scale-out

### S9 — Multiple communities & discovery

- **ID / Status:** S9 — parked
- **Type:** mixed — discovery is testimony; N actors mean N key custodies with
  strict per-actor isolation in `communityd` (guarantee-adjacent operationally,
  no new record kinds).
- **Thesis line:** neighborhoods, plural — adjacency between places, not just
  within one ("also a regular at…").
- **Adds:** community-DID scoping audited through observer schema and config
  (community identity is the community DID everywhere, never a
  deployment-local ID); disjoint credentials per actor; a directory view;
  cross-community author context on the regulars substrate.
- **Still excludes:** cross-community authority of any kind (shared bans,
  federated mod teams); global search (`BUILD.md` non-goal stands);
  self-service community creation; engagement-ranked discovery (OQ-R14 —
  directory and webring shapes, not trending).
- **Entry gate (HUMAN):** packet: a second real community wants to exist on
  this deployment; OQ-R9 and OQ-R14 decisions. S18 lands first — prove one
  room can hold talk before opening a hotel.
- **Blocking OQs:** OQ-R9, OQ-R14
- **Donor assets:** driftwatch consumer multi-source cursor handling;
  labelwatch discovery patterns as patterns only (registry modules are
  rejected in the reuse matrix).
- **Replay seam obligation:** per-community event streams independently
  exportable — a fork takes one community, not the deployment.
- **Deliverables:** schema scoping migration; credential-separation tests;
  directory + per-community routing; cross-community regulars projection.
- **Task ladder (MACHINE):**
  1. Schema scoping — done when rebuild parity per community exits 0.
  2. Credential separation — done when the test proving community A's writer
     cannot touch B exits 0.
  3. Directory + routing — done when the web suite exits 0.
  4. Cross-community context — done when projection tests exit 0.
- **Exit review (HUMAN):** *Are these distinguishable places with their own
  regulars, or one database wearing several nametags?* Evidence: two rendered
  communities side by side, per-community regulars.
- **Evidence log:** (empty)

Authorized: no

### S10 — Comment moderation & inclusion policy

- **ID / Status:** S10 — parked
- **Type:** guarantee — small (same modAction kinds over a new subject class,
  plus one policy record kind), but authority nonetheless. The authority half
  of conversation, split from S18 so smallest-authority-first holds.
- **Thesis line:** conversation the place can tend — moderation at reply
  granularity, with the same receipts discipline as posts.
- **Adds:** a signed, versioned inclusion-policy record replacing S18's fixed
  rule (default-visible-until-removed vs admission-required is a community
  policy record, not hardcode); per-reply remove/restore; orphan semantics
  when a parent reply is removed; the reply-scoped authority plumbing S8's
  locks consume. A native comment record remains a separate, later decision
  that opens only if the projection fails criteria pre-registered in OQ-R10.
- **Still excludes:** a native comment lexicon (unless OQ-R10's criteria
  fire); locks themselves (S8); votes; notification machinery.
- **Entry gate (HUMAN):** packet: S18 exit answered "reads as conversation"
  plus real moderation need at reply granularity; OQ-R10 criteria registered;
  inclusion-policy default chosen — that default is itself the decision.
  Requires S18 and S5 (removal hygiene before reply-scoped removal).
- **Blocking OQs:** OQ-R10 (native-record branch only)
- **Donor assets:** existing V0 modAction machinery; labelwatch receipts;
  emit-mode graduation for the new subject class.
- **Replay seam obligation:** reply removals/restores use the same event
  grammar (strongRef subjects, deterministic rkeys); the inclusion policy in
  force is a signed, versioned record so a fork replays reply visibility, not
  just post visibility; thread projection stays derived, never stored as
  truth.
- **Deliverables:** inclusion-policy lexicon; per-reply daemon path; thread
  reducer authority states (removal, restore, orphaning); post-removal thread
  rendering.
- **Task ladder (MACHINE):**
  1. Inclusion-policy lexicon + supersession of S18's fixed rule — done when
     validation suite exits 0.
  2. Thread reducer authority states — done when exhaustive fixtures exit 0.
  3. Per-reply removal path — done when daemon idempotency suite exits 0.
  4. Post-removal rendering — done when the thread suite exits 0.
- **Exit review (HUMAN):** *Does removing one reply leave an honest,
  non-gaslighting thread?* Evidence: rendered threads before/after a reply
  removal, audit trail.
- **Evidence log:** (empty)

Authorized: no

### S11 — Votes & community-scoped ranking

- **ID / Status:** S11 — parked
- **Type:** mixed, split by design — the most thesis-dangerous slice on the
  ladder. Vote records are user-repo testimony; ranking is versioned view
  policy (clause 6). **Votes as input to any authority outcome
  (membership-gated voting, vote-weighted moderation) are guarantee-typed and
  deliberately NOT on this ladder.**
- **Thesis line:** handled wrong, this re-imports the salience machine the
  thesis exists to escape. Null hypothesis, stated as part of the slice: a
  place that never needs votes is a thesis success, not a missing feature.
- **Adds:** a community-scoped vote lexicon living in the voter's repo
  (strongRef subject); vote ingestion with dedup/revocation semantics; one or
  more named, versioned, signed view policies with published inputs so any
  AppView can reconstruct or challenge the ranking; a clearly labeled ranked
  lens ("top this week") — the default surface stays recency + recurrence.
- **Still excludes:** global karma; contributor scoring; engagement-optimized
  defaults; downvote-driven hiding; membership-gated voting (couples to S14);
  any engagement-velocity input.
- **Entry gate (HUMAN):** packet: hard evidence that chronological + memory
  views fail legibility at real volume; OQ-R11 decisions; an explicit thesis
  review — does this community even want ranking?
- **Blocking OQs:** OQ-R11
- **Donor assets:** driftwatch consumer for volume; labelwatch receipts for
  ranking manifests; `derive.py` pure-scoring organization.
- **Replay seam obligation:** votes are replayable user events; ranking
  manifests (algorithm version + input hashes) make every ranked view
  reproducible — a fork re-ranks under its own policy over identical inputs.
  Rank is never stored as truth.
- **Deliverables:** vote lexicon; ingestion + dedup semantics; pure ranking
  function + manifest emission; labeled ranked view.
- **Task ladder (MACHINE):**
  1. Vote lexicon — done when validation suite exits 0.
  2. Ingestion/dedup/revocation — done when semantics suite exits 0.
  3. Ranking function + manifest — done when the reproducibility test (same
     inputs + version → identical order) exits 0.
  4. Ranked lens — done when the default-view-unchanged test exits 0.
- **Exit review (HUMAN):** *Can a reader see why something ranks where it does
  — and does the default page still feel like a place rather than a contest?*
  Evidence: ranked view + its published manifest, side-by-side with the
  default view.
- **Evidence log:** (empty)

Authorized: no

### S12 — Managed cold-path operation

- **ID / Status:** S12 — parked
- **Type:** testimony, strictly observer-only — artifacts never confer
  authority and `communityd` never reads them (`AGENTS.md` boundary).
- **Thesis line:** portable observer history is the raw material of both
  memory (S4 at scale) and fork-auditing (S13's companion) — custody of
  testimony, never the portable admission ledger itself.
- **Adds:** managed operation beyond V0-M2A's explicitly invoked local CLI:
  continuous scheduling/leases, compaction and tiering policy, remote or object
  storage publication, multi-host custody, or a concurrent historical query
  service. A ratification packet must choose the concrete subset forced by
  evidence; this entry does not bundle all of them by default.
- **Still excludes:** serving authority from artifacts; any hot-path DuckDB;
  `communityd` access; treating a remote analytical service as admission,
  membership, moderation, or custody authority.
- **Entry gate (HUMAN):** V0-M2A is complete and measured operation shows an
  actual need for unattended archival, compaction/tiering, remote custody,
  multiple ingest hosts, concurrent historical consumers, or latency-sensitive
  historical queries.
- **Blocking OQs:** none registered — packet preparation must promote the
  selected retention, remote-custody, deletion, availability, and service
  policy questions implicated by the observed forcing case.
- **Donor assets:** driftwatch cold-path specs and `facts_export` atomic
  generation-sealing (its known dedup flaws are documented rejections in the
  reuse matrix).
- **Replay seam obligation:** preserve V0-M2A semantic identities, immutable
  generations, supersession, hashes, high-waters, and explicit cannot-testify
  fields across every managed lifecycle operation.
- **Deliverables:** the selected managed-operation service and lifecycle
  policy, lease/recovery receipts, scale fixtures, and hot-path isolation proof.
- **Task ladder (MACHINE):**
  1. Extend lifecycle/manifests for the selected operation — done when schema,
     migration, and invalid-transition tests exit 0.
  2. Add managed scheduling/publication with explicit leases and bounded work
     — done when crash/retry and ingest-isolation tests exit 0.
  3. Add only the ratified compaction, tiering, remote-custody, or query-service
     capability — done when its parity and fault-injection suite exits 0.
  4. Run the scale/operations proof — done when resource, recovery, and
     cannot-testify receipt validation exits 0.
- **Exit review (HUMAN):** *Does managed cold operation preserve every V0-M2A
  custody and rebuild guarantee without becoming an ingest dependency or a
  shadow authority?* Evidence: lifecycle receipts, recovery transcript, and a
  clean-machine parity rebuild.
- **Evidence log:** (empty)

Authorized: no

## Tier 5 — The differentiator

### S13 — Fork / import / replay

- **ID / Status:** S13 — parked
- **Type:** guarantee — the heaviest human gate on the ladder, and the
  project's reason to exist (doctrine clause 5: the differentiator, not a
  garnish). A fork mints a NEW community actor with new keys — a second
  `communityd`, full firewall discipline.
- **Thesis line:** adjacency survives governance failure because the place,
  not the platform, is portable. Exit rights are what make every other slice
  trustworthy.
- **Adds:** an import/provenance record shape — the fork declares its
  ancestor, cut point, and what it kept, dropped, and re-signed (OQ-R12); a
  replay engine that feeds the ancestor ledger through the pure reducer under
  the fork's policy (keep admissions, drop bans, re-evaluate under new rules —
  the `linux.neutral.zone` scenario from `IDEAS.md`); a divergence surface
  ("this view differs from its ancestor at these decisions"); a fork-side
  re-signing ceremony. The canonical replay source is the community repo's own
  signed records — portable by protocol; V0-M2A supplies the baseline
  observer-history audit companion, while S12 may later operate it at scale.
- **Still excludes:** fork UI for end users; automated fork triggering;
  contested-succession arbitration — a fork is a new place with receipts, not
  a court ruling. Cross-observer identity merging stays forbidden
  (`observer_sequence` is never portable — already law).
- **Entry gate (HUMAN):** solo, ceremonial packet: a real fork demand or
  governance crisis — or, absent luck, a deliberate constitutional drill (fork
  the real community on purpose); the replay seam register below fully green
  across every shipped record kind; OQ-R12 decision.
- **Blocking OQs:** OQ-R12
- **Donor assets:** everything — this slice is why the deterministic reducer,
  generation-scoped rebuilds, strongRefs, deterministic rkeys, versioned
  rules, interval-typed roles/bans, and ranking manifests were shaped the way
  they were. Divergence rendering borrows the labelwatch boundary-edges
  concept from the reuse map.
- **Replay seam obligation:** this slice IS the audit of every seam reserved
  before it. A replay failure here is a defect in an earlier slice, not in
  S13.
- **Deliverables:** provenance lexicon; replay engine; fork bootstrap tooling
  (new actor, new keys, import ceremony); divergence/ancestry surfaces; golden
  fork fixture.
- **Task ladder (MACHINE):**
  1. Provenance lexicon — done when validation suite exits 0.
  2. Replay engine — done when property tests exit 0: full ledger under
     identity policy → byte-identical projection; under drop-bans policy →
     exactly the documented diff.
  3. Fork bootstrap — done when firewall tests over the second actor exit 0.
  4. Divergence surfaces — done when rendering suite exits 0.
  5. Golden fork end-to-end — done when community A → fork B both render over
     the same user posts with a byte-stable, auditable difference report.
- **Exit review (HUMAN):** *Can a rival view over the same posts stand up in a
  weekend — and can any observer verify exactly what it inherited, dropped,
  and changed? When the place splits, do both rooms still stand?* Evidence:
  the golden fork, both rendered rooms, the divergence report. If yes, the
  goblin is constitutional.
- **Evidence log:** (empty)

Authorized: no

## Tier 6 — Frontier, parked

Named so they stay visible and nobody smuggles them in earlier. No task
ladders until a slice reaches candidate.

### S14 — Explicit membership records

- **ID / Status:** S14 — parked
- **Type:** guarantee
- **Thesis line:** prefer observed recurrence (S3); "member" as a database row
  is the server-bucket smell clause 2 exists to prevent.
- **Adds:** opens only when a ratified policy needs membership as an input
  (member-only voting, S16 privacy). S3 is the experiment that informs this.
- **Still excludes:** member-only permissions until a consumer exists.
- **Entry gate (HUMAN):** a ratified consumer policy that observed recurrence
  provably cannot serve; OQ-R3.
- **Blocking OQs:** OQ-R3
- **Donor assets:** resolver/identity substrate from S3.
- **Replay seam obligation:** if minted, membership must be interval events
  like roles — replayable, droppable by a fork.
- **Deliverables:** none named — parked.
- **Task ladder (MACHINE):** none — parked; drafted at candidate.
- **Exit review (HUMAN):** *Does joining mean something without becoming
  enclosure?*
- **Evidence log:** (empty)

Authorized: no

### S15 — Community-aware client

- **ID / Status:** S15 — parked
- **Type:** testimony-flavored (client/ecosystem work)
- **Thesis line:** the `IDEAS.md` V2 rung; every prior slice must keep the
  stock-client degradation path working (the overlay promise), which is why
  this is last and deliberately unspecced.
- **Adds:** opens only when S10/S11 exist to surface natively and friction
  evidence shows the generic-client submit path is losing returning
  contributors.
- **Still excludes:** everything — resist speccing this.
- **Entry gate (HUMAN):** friction evidence; scope sketch at candidate.
- **Blocking OQs:** none registered.
- **Donor assets:** none named.
- **Replay seam obligation:** none — client work adds no records.
- **Deliverables:** none named — parked.
- **Task ladder (MACHINE):** none — parked; drafted at candidate.
- **Exit review (HUMAN):** *Does native UX deepen the room or just polish the
  door?*
- **Evidence log:** (empty)

Authorized: no

### S16 — Private communities

- **ID / Status:** S16 — parked (hard)
- **Type:** guarantee — maximal
- **Thesis line:** parity — thesis-neutral, and doctrinally dangerous: bolting
  privacy onto public repo primitives is a doctrine-level error, not a
  scheduling problem.
- **Adds:** nothing until ATProto grows a non-public-data primitive upstream
  (`IDEAS.md` and the protocol docs both mark this a missing/planned spec
  area).
- **Still excludes:** everything, on purpose.
- **Entry gate (HUMAN):** upstream protocol movement, then a fresh doctrine
  review — this entry does not survive contact with a real primitive
  unchanged.
- **Blocking OQs:** upstream protocol gap (not locally numberable).
- **Donor assets:** none.
- **Replay seam obligation:** unknown — part of why it is hard-parked.
- **Deliverables:** none named — parked.
- **Task ladder (MACHINE):** none — parked; drafted at candidate.
- **Exit review (HUMAN):** *Can a private room exist without pretending public
  substrate is private?*
- **Evidence log:** (empty)

Authorized: no

### S17 — Reports & T&S infrastructure

- **ID / Status:** S17 — parked
- **Type:** guarantee-adjacent (report records are user testimony; queues
  route authority attention)
- **Thesis line:** parity — thesis-neutral. Until abuse volume forces
  infrastructure, T&S lives as the per-slice proportional-posture review in
  the cross-cutting tracks, not as a system.
- **Adds:** opens on abuse-volume evidence after S8: observed user-side report
  records, an admin review queue.
- **Still excludes:** generalized trust-and-safety infrastructure (permanently
  replaced by the per-slice posture unless evidence forces this open).
- **Entry gate (HUMAN):** abuse-volume evidence post-S8.
- **Blocking OQs:** none registered.
- **Donor assets:** receipted-decision ledger patterns.
- **Replay seam obligation:** reports are user-side observable events; queues
  are local operational state, never portable truth.
- **Deliverables:** none named — parked.
- **Task ladder (MACHINE):** none — parked; drafted at candidate.
- **Exit review (HUMAN):** *Does the place handle harm legibly without
  becoming a surveillance instrument?*
- **Evidence log:** (empty)

Authorized: no

---

## Replay seam register

The mechanical enforcement of doctrine clause 5. Every ratified slice must
extend this table before its exit review. A candidate slice that cannot state
its row here is misdesigned; redesign before ratification.

| Obligation | Established by | Verified by |
|---|---|---|
| strongRef (URI+CID) subjects; deterministic rkeys | V0 | lexicon validation tests |
| Semantic event identity, payload hashes, distinct source/received/signed times | V0 schema v1 | schema/receipt tests |
| Pure reducer; projections always rebuildable from events | V0 | rebuild-parity test (standing gate, every slice) |
| Regulars/memory views derived from events only | S3/S4 | recompute-parity tests |
| Rules versioned; decisions cite ruleset by strongRef | S7 | citation-validity fixtures |
| Reply visibility replayable: fixed rule (S18), then policy records (S10) | S18/S10 | thread-projection goldens |
| Roles/bans as interval events; historical authority recomputable from the ledger | S6/S8 | authority-interval property tests |
| Ranking = versioned policy + published inputs | S11 | manifest reproducibility test |
| Community identity = DID everywhere, never deployment-local | S9 | export-scoping tests |
| Sealed observer history with limitation fields | V0-M2A | manifest/parity tests |

## Cross-cutting tracks

Not slices; obligations that ride along.

- **Abuse/T&S posture:** a review checklist attached to every guarantee-typed
  slice-ratification packet — what new abuse does this authority enable, and
  what receipts make it auditable. Each exposure-increasing slice (S1, S2, S9,
  S18) states its minimal posture (rate limits, kill switch, refusal states) at
  ratification. Hardens into S17 only on evidence.
- **Ops/observability:** heartbeats, staleness banners, and degradation
  semantics extend per slice (donor: labelwatch runner/report patterns).
- **Automation harness:** `docs/GOVERNED-LOOP.md` is the proposed execution
  contract and V0 queue. Each slice's ratified task ladder later joins that
  queue. Standing gates (full suite, boundary suite, rebuild parity, roadmap
  linter) apply to every slice. `V0-G0` is the explicit self-hosting task for
  the linter, operator-question/decision validators, and execution-evidence
  validator; an OQ-7 A/B decision and narrow positive `BUILD.md` row must make
  it eligible. Its generated program/schema digests require independent human
  acceptance; unattended `next` additionally requires OQ-7 answer A. Until
  then, "all gates green" is a pile of terminal output, not a review object.

## Ordering rationale

1. **Harden before widening.** Production posture (S1) and the stock-client
   door (S2) consolidate the V0 answer before any new semantics; every thesis
   claim is longitudinal, and S1 exists to let time pass in one place.
2. **Thesis before parity.** S3, S4, and S18 are guarantee-free and test
   adjacency-through-recurrence directly — recognition, memory, and the talk
   where adjacency actually forms. If they land flat, that is decision-grade
   evidence before any authority expansion is paid for.
3. **Authority is bought smallest-first, on evidence.** Restore < roles <
   bans, each opened by a real operational forcing case, never speculatively;
   each guarantee slice carries a solo slice-ratification packet and its own
   emit-mode graduation. Conversation splits along the same line: its surface is
   a thesis experiment (S18); its authority half (S10) waits for governance
   basics.
4. **Scale-out after governance basics.** Comment moderation and votes without
   removal hygiene and roles is moderation debt; multi-community (S9) waits
   until one room has held talk — prove the room before opening a hotel.
5. **The differentiator is last on the ladder and first in every design.**
   S13 sits late because forking an empty room proves nothing, but the replay
   seam register makes every earlier slice pay its seam obligation up front;
   a replay failure at S13 is a defect in an earlier slice.
6. **Salience last.** Votes (S11) are ordered after regulars (S3) and memory
   (S4) so that if ranking ever arrives, recurrence-aware views already exist
   to compete with it — the thesis gets first-mover advantage inside its own
   project.

## Human-gate inventory

The total human budget, so autonomy is spent where it is safe and attention
where it is owed. Per slice: one slice-ratification packet + one exit review.
Everything between an authenticated slice-ratification decision and an exit
review is exit-code-gated and runs without stopping.

- Testimony slices may batch their packets and reviews (S3+S4+S18 naturally;
  S2 with any).
- Guarantee slices are solo by rule — never batch an authority expansion with
  anything (S1, S5, S6, S7, S8, S13).
- Extra, unbatchable stops: S1 production key ceremony; S6 firewall
  re-review; S8 T&S review; S13 fork ratification (the heaviest, and
  deliberately ceremonial).
- Rough budget: about two human touches per slice; on the expected path
  through Tier 2 (V0 exit, S1 packet + ceremony + exit, S2–S4 batched packets
  and reviews) roughly seven sit-downs — front-loaded into packets agents
  fully prepare.

## Candidate open questions (OQ-R register)

Registered here so they exist as handles; each is promoted into
`docs/OPEN-QUESTIONS.md` (with a real OQ number) only when its
slice-ratification packet is being prepared. Promotion creates a real OQ entry
and permits an operator-question packet to be prepared; it does not supply a
ruling.
`docs/OPEN-QUESTIONS.md` remains the register of blocked authorized work; this
list is speculation with names. A cross-cutting question may be promoted earlier
when it blocks the authorized V0 runway; OQ-R13 is the first such case.

- **OQ-R1 — Production key custody and rotation** (S1). Extends OQ-3 to
  production: custody location, rotation policy, and how rotation events keep
  historical signature verification intact.
- **OQ-R2 — Feedgen identity vs the firewall** (S2). The generator record must
  be emitted by `communityd` (the observer cannot publish records); which DID
  *serves* the feed, and where that process sits relative to the
  observer/authority split.
- **OQ-R3 — Membership: observed recurrence vs join records** (S14; informed
  by S3). Is membership ever a record, or always observed recurrence plus
  optional user-side declared affiliation? Which ratified policy first
  *requires* the record?
- **OQ-R4 — Recurrence-display ethics and gaming** (S3). The exact recurrence
  predicate; opt-out/visibility stance for surfacing a person's recurrence;
  the anti-leaderboard rule (tenure and recency may show; ranked counts may
  not); and gaming resistance — once recurrence is rendered, the label itself
  is status even without a count, so the predicate must weigh performative and
  low-effort presence; whether reply participation (S18) counts is part of the
  same decision.
- **OQ-R5 — Restore vs terminalized states** (S5). What restore pins
  (admission vs subject), and the deterministic-rkey collision: re-admitting
  the same exact subject after terminal removal needs a generation component
  in the hash input or a distinct record kind, without breaking V0's
  "reverting a CID never revives the old admission" law.
- **OQ-R6 — Delegated authority as replayable intervals** (S6). Grant/revoke
  representation; revocation propagation latency; and the replay law: are a
  later-revoked mod's past actions valid at their timestamps? (Recommended:
  yes — authority is evaluated as-of event time; state it as law.)
- **OQ-R7 — Delegated admin authentication** (S6). OQ-4's proposed local-OS
  model does not extend to remote mods: separate keys per mod vs authenticated
  capability through `communityd`; compromise and revocation story.
- **OQ-R8 — Ban scope, expiry, re-entry** (S8). Ban record shape; whether the
  banned party's existing admitted history is affected (recommended: no, per
  clause 4); appeal shape.
- **OQ-R9 — Multi-community storage topology** (S9). Database per community vs
  scoped tables; blast radius, rebuild cost, and key-isolation model.
- **OQ-R10 — Native-comment failure criteria** (S10). The pre-registered
  criteria under which the projection-over-replies approach is declared failed
  (reply-graph noise, cross-community ambiguity, thread illegibility) — the
  only branch that would justify a native comment record.
- **OQ-R11 — Vote shape and posture** (S11). Vote record shape; revocation
  semantics; anti-sybil/brigading inputs; whether ranking must
  refuse-to-render on incomplete vote observation, per the admissibility
  pattern.
- **OQ-R12 — Fork provenance disclosure** (S13). What a fork must assert about
  its ancestor: per-event citation vs manifest-level cut point; how importing
  under different rules is expressed given S7's rules provenance.
- **OQ-R13 — Governor-loop entry, decision, and evidence contract** (all
  slices). Promoted to OQ-7 in `docs/OPEN-QUESTIONS.md`; OQ-R13 is now a
  historical alias and must not appear in a slice's canonical blocker field.
  `docs/GOVERNED-LOOP.md` contains the proposed minimum contract; unattended
  selection remains blocked until a human selects answer A and independently
  accepts the protected validator/schema/program digests.
- **OQ-R14 — Discovery without salience maximization** (S9). How communities
  are findable without a trending machine: directory, webring, and
  cross-community-regulars shapes.

## Non-goals of this document

- It authorizes nothing and cannot be cited as scope in a review. `BUILD.md`
  is the belt; the per-slice `Authorized:` line is the suspenders.
- It does not fix ordering permanently — exit-review evidence reorders it, and
  the ladder records best guess, not law.
- It does not replace `docs/OPEN-QUESTIONS.md` — OQ-R entries migrate there
  only when their slice-ratification packet is being prepared.
- It never carries implementation detail beyond deliverable names and
  done-condition commands. `docs/IMPLEMENTATION-PLAN.md`-depth planning is
  written per slice at ratification, not before.
