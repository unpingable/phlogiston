# OQ-7 bootstrap operator-question packet

**Status:** prepared unsigned; non-authorizing; no operator ruling

**Schema:** `oq7-bootstrap-question-packet-v1`

**Bootstrap format:** manually reviewed Markdown exception pending V0-G0

**Packet ID:** `OQP-OQ-7-2026-07-27-03`

**Question ID:** OQ-7

**Source handle:** OQ-R13

**Prepared:** 2026-07-27 against base commit
`fd3cf3ffbf0ffd3f91ce432e27b44ef7df6aaafd`

**Preparer:** agent-produced proposal

**Authority effect:** none

**Human receipt required:** yes

This is the one-time bootstrap packet described by
`docs/GOVERNED-LOOP.md`. It is a review object, not an operator decision, a
controller-entry packet, an execution-evidence bundle, a `BUILD.md` amendment,
or a community authority record. A `select` receipt must content-address this
packet and exactly one answer's required change set; a procedural receipt pins
the packet and its ruling-specific reason or evidence fields. This file
contains no ruling or signature field.

## Protected review inputs

The packet was prepared from the base commit above and the following exact
proposed governance bytes. `repo:` URIs identify repository-relative paths in
the reviewed tree. Any mismatch requires a new packet ID rather than
interpretation.

| Role | URI | Media type | Bytes | SHA-256 |
|---|---|---|---:|---|
| repository boundary | `repo:AGENTS.md` | `text/markdown; charset=utf-8` | 3332 | `sha256:1a4c9b2b0b0779c1a9caa255eef977f67f77989d4720796a2e1861494413c7ac` |
| positive scope authority | `repo:BUILD.md` | `text/markdown; charset=utf-8` | 4984 | `sha256:5c0d2de321a05c0e26e10c085a96358e059de17639e08dffb530ba482d0a85bd` |
| architectural law | `repo:DOCTRINE.md` | `text/markdown; charset=utf-8` | 2622 | `sha256:cf7bb22ae2e1d2a117bf7b35c1746d5f0045e69eee40784b0a10889efb22584c` |
| candidate-slice contract | `repo:ROADMAP.md` | `text/markdown; charset=utf-8` | 67167 | `sha256:49e6efc44c9124dda08afb4e1bc211a4d449ade18cef7798654eed25ecf3da19` |
| proposed execution and decision contract | `repo:docs/GOVERNED-LOOP.md` | `text/markdown; charset=utf-8` | 50121 | `sha256:5196331349155397bb0f6b4f85a9adda5ed4e1741e75b043341f4a1f0ec0afa1` |
| promoted-question register | `repo:docs/OPEN-QUESTIONS.md` | `text/markdown; charset=utf-8` | 9465 | `sha256:fc704af74e51a29b29d35c58cc4aa0c295ce11729f12e40b6bf62b4f93986e28` |
| authorized V0 milestone design | `repo:docs/IMPLEMENTATION-PLAN.md` | `text/markdown; charset=utf-8` | 43789 | `sha256:9713bfb4729844bbd029423f3f66cf192ab9b90c172b7585bfd6d5b4fd55da35` |
| proposed acceptance design | `repo:docs/TEST-PLAN.md` | `text/markdown; charset=utf-8` | 24018 | `sha256:df4f8508b6c436c14f3a9d5273660c99c208a3c3f58d5a0d882190b5c93c8af6` |

The current `BUILD.md`, `DOCTRINE.md`, and `AGENTS.md` bound every answer.
`ROADMAP.md` remains non-authorizing. No answer may change product scope,
architectural invariants, credential rules, signing behavior, or ATProto
records through this packet.

## Superseded preparation history

`OQP-OQ-7-2026-07-16-02`, 19416 bytes,
`sha256:ffd8a0106ecb36382a87e1ed5c4aa3d222f7bfeef654ad46467c3e5d0610638b`,
is a superseded unsigned preparation, not a ruling. Its proposed change sets
were:

- `OQCS-OQ-7-2026-07-16-A-02`, 1437 bytes,
  `sha256:58119312f169d23a9ac5b185a36c6fbfca0d01cea1e8b22ba9b5e70372b3fb75`;
- `OQCS-OQ-7-2026-07-16-B-02`, 1437 bytes,
  `sha256:d0350dcd76f03b58d250fde1802370c5baca256bb45d5d7b045cea52b98d6eab`;
  and
- `OQCS-OQ-7-2026-07-16-C-02`, 832 bytes,
  `sha256:332db8ea521a10b345c6f99c140a762926f77df38800934ed7f36020002d6749`.

Those uncommitted proposal bytes were replaced only after their exact lengths
and digests were recorded here. No decision receipt or ruling existed for that
generation. Its protected `docs/GOVERNED-LOOP.md` value was 49396 bytes,
`sha256:75b5548f97e87c7cea7ec96b9dabc9468b6d3412b23ae027db0cf77a4bb34a3d`;
the mismatch with the reviewed proposal required this new packet generation.

At repack inspection, the reviewed contract was 50121 bytes,
`sha256:e16da6813b62c9fdeb5438d444b1e3565edb0c44e7c68b0d17760fd2de9687f6`,
but its frozen receipt and verifier clauses still named the superseded packet
ID. Advancing only those two equal-length identity references to
`OQP-OQ-7-2026-07-27-03` produced the 50121-byte contract digest protected
above. This identity-coherence edit changes no answer, trust policy,
authorization, task scope, or acceptance rule.

## Question

Which governed-execution contract, if any, shall control V0-G0 and later V0
task selection?

## Why this is being asked now

OQ-7 blocks V0-G0 and governed product implementation. The roadmap requires
strict, evidence-backed selection, while the repository has no task manifest,
roadmap validator, gate program, execution-evidence schema, operator-question
schema, decision-receipt validator, or accepted controller trust policy. A
bounded human decision is required before the tooling that validates later
decisions may be built.

## Observed forcing case

The forcing-case predicate is satisfied when all of these are true:

1. OQ-7 is a named blocker for V0-G0 or unattended selection.
2. The roadmap promises machine-enforced selection and reviewable evidence.
3. The promised validators and protected manifests do not yet exist.
4. A one-time bootstrap can be confined to governance tooling without changing
   product scope, doctrine, credentials, signing, transport, or ATProto records.
5. The bootstrap still requires independent human acceptance before `next` can
   become available.

The protected inputs satisfy that predicate:

- `docs/OPEN-QUESTIONS.md` names OQ-7 as a blocker for V0-G0 and `next`.
- `ROADMAP.md` says the automation contract is prose until V0-G0 creates and
  tests strict machinery.
- `docs/GOVERNED-LOOP.md` confines V0-G0 to repository-process tooling and
  requires a separate bootstrap-output human-acceptance receipt.
- The base commit contains implementation/document artifacts for V0-M1,
  V0-D2, and V0-M2, but no accepted governed PASS evidence for them. This
  proposal adds three non-authorizing patch artifacts, not executable code,
  schemas, credentials, clients, or gates.
- `BUILD.md` contains no positive V0-G0 authorization. This packet cannot
  supply one.
- The earlier proposal mutually hashed `BUILD.md` and its controller-entry
  packet. The reviewed contract replaces that cycle with one-way binding.
- The earlier proposal mentioned governance decisions and receipts without
  exact answer, consequence, authentication, or novelty semantics. The
  reviewed contract makes them disjoint protected artifact kinds.

## Existing-artifact boundary

The V0-M1 implementation at
`bf49331891ba119fe501215e1bbd55ce18c7fde7`, the V0-D2 documentation at
`8e44ca5ad6ccd76c8364bf5b94213b75ec8dcafe`, and the V0-M2 implementation at
`6269c36986e2f6e1865758b047ffb5b7e4e8a243` remain governed-incomplete. Their
existence does not satisfy V0-D1, accepted contract-freeze, controller-entry,
protected-gate, execution-evidence, or human-acceptance requirements.

Whether and how those exact existing trees may later be reconciled is outside
OQ-7 and requires a separate human-governed contract or decision. This packet
adds no retroactive acceptance policy, and no answer in this packet accepts,
ratifies, or promotes those artifacts.

## Admissible answers

### A — Adopt the corrected full governed-loop contract

Adopt the protected `docs/GOVERNED-LOOP.md` contract with all of these terms:

1. Operator-question packets are unsigned proposals; separately authenticated
   human receipts select exactly one admissible answer.
2. A selected receipt satisfies only its declared blocker. It never supplies
   `BUILD.md` authority, slice ratification, or task authorization.
3. The fixed trust policy applies to every answer and procedural ruling, then
   separately to bootstrap and later governed-V0 launches and acceptances until
   a selected transition replaces it. The same attested human principal and
   channel supply distinct evidence for each canonical payload digest without
   requiring an enclosing artifact to hash itself.
4. The positive V0-G0 `BUILD.md` block binds only its authorization ID, exact
   task/scope, and contract digest. A later controller-entry packet pins that
   `BUILD.md`, the OQ-7 packet/receipt, base, task definition, paths, modes, and
   evidence destination.
5. Evidence is stored outside the checkout in a controller-managed durable
   destination. PASS requires digest-verified readback.
6. The bootstrap launch separately pins the external frozen verifier, every
   governance input, every existing path as protected, and a maximum add-only
   write set of `governance/**`, `scripts/v0-gate`, and
   `tests/governance/**`.
7. V0-G0 creates strict schemas, validators, canonical rendering, and valid and
   invalid fixtures for every protected governance and execution artifact.
8. Tasks run in disposable checkouts with protected paths, offline done gates,
   exact command and commit evidence, and the fixed stop vocabulary.
9. Bootstrap acceptance must cover every candidate output and every mandatory
   role; accepted subsets and G0-generated self-approval are invalid.
10. `next` remains unavailable until a human-acceptance receipt pins the
   generated schemas, programs, fixtures, manifest, gate, and candidate tree.

**Doctrine and authorization fit:** this is automation-first, preserves the
existing authority intersection, and adds only a separately authorized
governance bootstrap.

**Fit criterion:** choose A if the operator wants a controller eventually to
select the next eligible task within a separately bounded lane.

**Required change set:** `OQCS-OQ-7-2026-07-27-A-03`,
`repo:docs/OQ-7-CHANGESET-A.patch`, `text/x-diff; charset=utf-8`, 1437
bytes, `sha256:bc8885584dad8642ae9dea9b5fe4d5164a0be5559701015a5c6116bb8bf00d0f`.

### B — Adopt the corrected contract for explicitly named tasks only

Adopt every safeguard in A, including the one-time V0-G0 bootstrap and
independent acceptance of its outputs, but reject the literal `next` selector.
Every later controller-entry packet must name exact task IDs. The contract may
retain `next` in its vocabulary only so validation can reject it under B.
Enabling it would require a new operator question and human change set.

**Doctrine and authorization fit:** this remains automation-first while
requiring a human to bound every execution tranche by exact task ID.

**Fit criterion:** choose B if immutable packets, external evidence, strict
gates, and disposable task execution are desired but automatic selection among
eligible tasks is not.

**Required change set:** `OQCS-OQ-7-2026-07-27-B-03`,
`repo:docs/OQ-7-CHANGESET-B.patch`, `text/x-diff; charset=utf-8`, 1437
bytes, `sha256:cedded152b54e68746c33e1326177fb429032fcaf16e05c4c9956cb81ad10aee`.

### C — Decline the governed-loop contract

Do not authorize or implement V0-G0. Keep `next` unavailable. Work may proceed
only through separately explicit tasks inside the existing `AGENTS.md`,
`BUILD.md`, and `DOCTRINE.md` boundary; this proposed controller contract
supplies no authority or completion claim.

**Doctrine and authorization fit:** this changes no existing authority. Direct
work must still use orchestration consistent with the automation-first build
condition and must receive its own explicit implementation task.

**Fit criterion:** choose C if the governance machinery is not worth building
before direct V0 implementation. Selecting C is an affirmative no-go policy;
procedurally rejecting this packet is not equivalent to selecting C.

**Required change set:** `OQCS-OQ-7-2026-07-27-C-03`,
`repo:docs/OQ-7-CHANGESET-C.patch`, `text/x-diff; charset=utf-8`, 832
bytes, `sha256:fd3d42aff6c506ec69b1a0a2a5332a32ff5318c81e65ef1c564549cd4dfead88`.

## Evidence by answer

### A

**Supporting evidence**

- It implements the automation-first build condition while keeping scope,
  policy, protected digests, and experiential judgments human-controlled.
- Bounded lanes, disposable checkouts, side-effect-free gates, protected
  inputs, explicit stop outcomes, and independent bootstrap acceptance are all
  specified in the reviewed contract.
- The packet/receipt split makes pre-drafting useful without laundering an
  agent recommendation into ratification.
- Defining the primitive once at V0-G0 lets later promoted OQ-Rs reuse one
  contract rather than inventing governance semantics per slice.
- One-way digest binding repairs an otherwise uninstantiable bootstrap without
  weakening positive `BUILD.md` authorization.

**Opposing evidence**

- No controller, validator, gate, or evidence-store integration has run in this
  repository.
- Strict validation and `next` selection make V0-G0 larger and place more trust
  in the accepted selector than B does.
- The roadmap has normalization defects that G0 must report and stop on, not
  silently repair.

**Residual uncertainty**

- The fixed trust channel's provider implementation and availability, durable
  evidence destination, and retention period remain controller-entry inputs.
- The implementation cost of strict roadmap parsing and invalid-fixture
  coverage is not measured.
- Operational experience may favor named tasks over `next`.

### B

**Supporting evidence**

- It retains A's isolation, receipts, evidence retention, and deterministic
  gates while reducing selector discretion.
- Exact task IDs make each launch's human intent directly reviewable and avoid
  relying on roadmap ordering to choose work.
- The reviewed contract already has answer-sensitive validation, so B needs no
  post-decision rewrite of the selector vocabulary.

**Opposing evidence**

- Every new tranche requires another human-prepared controller-entry packet,
  spending attention on task choice even when all policy gates are settled.
- It does not realize the roadmap's unattended `next` objective.
- More launch boundaries can fragment evidence and slow small sequential tasks.

**Residual uncertainty**

- The practical human cost per exact-task packet is unknown.
- It is unknown whether bounded multi-task tranches will provide enough
  autonomy without `next`.

### C

**Supporting evidence**

- It avoids implementing an untested governance subsystem before product code.
- Beyond the authenticated decision channel, it requires no launch/evidence
  provider, durable evidence store, or bootstrap exception now.
- Existing positive `BUILD.md` scope and explicit tasks can still bound direct
  V0 work.

**Opposing evidence**

- The roadmap's machine-selection and reviewable-evidence promises remain
  unenforced prose.
- Repeated direct tasks must recreate launch, evidence, and stop discipline
  without the proposed validators.
- It forgoes a reusable decision-packet primitive for later slice gates.

**Residual uncertainty**

- The relative cost of direct orchestration versus V0-G0 is not measured.
- It is unknown whether the existing explicit-task channel will preserve enough
  durable evidence for later review.

## Recommendation

**Recommended answer:** A

A best matches the declared automation-first direction while preserving the
human boundary: the agent fills the question, choices, evidence, recommendation,
and exact patches, but only a separate receipt can select one. B is the safer
choice if selector discretion is the concern; C is internally coherent but
abandons the roadmap's governed-loop objective.

## Consequences by answer

### A — Corrected full contract

- **Authority delta:** the receipt alone adds none and satisfies only OQ-7. If
  the human applies the reviewed change set, `BUILD.md` gains one single-use,
  governance-only V0-G0 authorization; no product or ATProto authority changes.
- **Guarantee delta:** adds validated governance artifacts, external evidence
  retention/readback, an acyclic digest graph, and independently accepted
  bootstrap outputs.
- **Blockers:** OQ-7 would be satisfied. Every other OQ, every slice entry/exit
  gate, and all independent task prerequisites remain.
- **Task eligibility:** V0-G0 would become eligible only after the valid A
  receipt, exact change-set application, authenticated bootstrap
  controller-entry packet, explicit human launch, and clean pinned base. `next`
  remains unavailable until G0 PASS and bootstrap-output acceptance.
- **Documents and patch:** apply only
  `OQCS-OQ-7-2026-07-27-A-03`. It adds the exact V0-G0 block to `BUILD.md` and
  records status, A, and stable receipt ID
  `OQDR-OQ-7-2026-07-27-A-02` in `docs/OPEN-QUESTIONS.md`.
- **Tasks still disabled:** V0-D1, V0-M1 through V0-M8, all roadmap slices, and
  any live or credentialed work until their own prerequisites pass.
- **Replay/fork implications:** no community record changes. Governance runs
  gain content-addressed replay inputs; those artifacts confer no community
  authority.
- **Abuse/T&S implications:** no new user-facing or moderation capability.
  Mis-selection risk moves into a protected selector and is bounded by exact
  task scope, paths, modes, gates, receipts, and stop outcomes.

### B — Named governed tasks only

- **Authority delta:** same single-use V0-G0 process authorization as A after
  human change-set application; the receipt itself adds none.
- **Guarantee delta:** A's guarantees plus the rule that every run names exact
  task IDs and `next` is invalid.
- **Blockers:** OQ-7 would be satisfied for named execution. Unattended `next`
  remains deliberately blocked unless a later promoted question changes B.
- **Task eligibility:** V0-G0 would have A's independent prerequisites. Later
  exact task IDs may become eligible under new controller-entry packets; no
  packet may request `next`.
- **Documents and patch:** apply only
  `OQCS-OQ-7-2026-07-27-B-03`. It adds the same exact V0-G0 block to `BUILD.md`
  and records status, B, and stable receipt ID
  `OQDR-OQ-7-2026-07-27-B-02` in `docs/OPEN-QUESTIONS.md`.
- **Tasks still disabled:** every task not named in an independently valid
  controller-entry packet, plus the same product and slice gates as A.
- **Replay/fork implications:** same content-addressed governance replay as A;
  exact task naming becomes part of each run's replay boundary.
- **Abuse/T&S implications:** no product capability changes and less automatic
  selector discretion than A. More frequent human launches create operator
  fatigue risk but cannot weaken machine gates.

### C — No governed loop

- **Authority delta:** none. The C receipt records a no-go and the change set
  does not amend `BUILD.md`.
- **Guarantee delta:** none; the proposed governed-loop guarantees remain
  unavailable.
- **Blockers:** OQ-7 would be decided as no-go. V0-G0 and `next` remain
  unavailable rather than ambiguously open.
- **Task eligibility:** no governed task becomes eligible. Separately explicit
  direct tasks remain possible only under existing authority and discipline.
- **Documents and patch:** apply only
  `OQCS-OQ-7-2026-07-27-C-03`. It records status, C, and stable receipt ID
  `OQDR-OQ-7-2026-07-27-C-02` in `docs/OPEN-QUESTIONS.md`; it leaves
  `BUILD.md` untouched. The conditional proposal documents remain historical,
  non-authorizing review material.
- **Tasks still disabled:** V0-G0, `next`, and every governed-loop run.
- **Replay/fork implications:** no community or governance-run replay change.
- **Abuse/T&S implications:** no new product capability or authority. Direct
  work lacks the proposed standardized evidence checks, increasing audit
  variance rather than changing moderation power.

## Procedural receipt outcomes

Every outcome uses the same `manual-controller-channel-v1` policy and the fixed
receipt grammar in `docs/GOVERNED-LOOP.md`:

- `select` must name exactly A, B, or C and its exact required-change-set ID and
  digest.
- `defer` must supply a concrete revisit trigger or deadline and may request
  named evidence. It leaves OQ-7 open.
- `reject_packet` must supply a reason class and
  `replacement_packet = required`. It leaves OQ-7 open and is not C.
- `repack_required` must supply one or more content-addressed novel-evidence
  references. It leaves OQ-7 open and forbids inferred hybrid policy.

Missing authentication, a missing required result, or an unavailable launch or
storage input blocks execution. It never turns a procedural outcome into a
selection.

## Novelty condition

The ruling must be `repack_required`, with no inferred policy, if:

- any protected input or required-change-set digest changes before decision;
- the operator requests a hybrid, condition, or trust policy not exactly
  represented by A, B, or C;
- the common bootstrap channel cannot attest the canonical decision-payload
  digest;
- a selected change set differs from the packet-reviewed operations or results;
- resolution would change product behavior, doctrine, credentials, signing,
  network scope, community authority, or a roadmap slice status; or
- new evidence contradicts a stated answer consequence or fits no answer.

A concrete authentication provider, evidence destination, or retention period
not yet being available is a declared run blocker under A/B, not permission to
infer a fourth answer.

## Operator ruling

Absent by design. A separate human operator-decision receipt must pin this
packet's exact digest and use one ruling from
`select | defer | reject_packet | repack_required`. The common bootstrap trust
policy applies regardless of the ruling. The frozen pre-bootstrap verifier may
verify this Markdown packet only as opaque bytes; V0-G0 may validate an
equivalent JSON golden but cannot retroactively create or authorize the human
decision.
