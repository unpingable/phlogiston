# Governed loop execution contract

**Status:** proposed Phase 0 bootstrap ruling protocol for every OQ-7 outcome;
the governed-execution terms activate only if OQ-7 selects A or B and the
selected required change set is human-applied. This document authorizes no
implementation, changes no V0 invariant, and ratifies no roadmap slice. Its job
is to make already-authorized work selectable without allowing a loop to infer
authority from prose.

## Purpose

The repository is intended to run under a controller that can execute bounded
tasks, verify them in clean checkouts, preserve evidence, and stop at human
gates. It is not intended to depend on an interactive coding session deciding
what to do next.

The controller has two execution lanes:

1. the V0 runway, `V0-G0`, `V0-D1`, `V0-M1`, `V0-D2`, `V0-M2`,
   `V0-M2A`, then `V0-M3` through `V0-M8`; and
2. the post-V0 `S<N>` ladder in `ROADMAP.md`.

The V0 runway always comes first. The slice lane remains closed until V0 has a
human exit verdict. There is no selector path that falls through from blocked or
incomplete V0 work to S1.

## Artifact vocabulary

The governance objects in this contract have distinct jobs and MUST NOT be
collapsed into one generic "packet" or "bundle":

Here **operator** means the human governance operator who rules on repository
scope and policy. It does not mean the community actor, `communityd`, or the
administrator invoking a community command.

- An **operator-question packet** is an unsigned, agent-preparable governance
  proposal. It states one promoted question, the evidence that forces it now,
  admissible answer classes, a recommendation, and the exact consequences of
  each answer. It may reference evidence; it is not execution evidence and
  carries no authority.
- An **operator-decision receipt** is the separately authenticated human ruling
  over one exact operator-question-packet digest. It may satisfy a named blocker;
  it does not amend `BUILD.md`, ratify a roadmap slice, or authorize a task.
- A **slice-ratification packet** is the roadmap entry-gate bundle: forcing-case
  evidence, applicable operator-decision receipts, and the proposed
  `BUILD.md`/roadmap amendments. It remains a proposal until the human-controlled
  ratification changes land.
- A **slice-ratification receipt** is the authenticated human acceptance of one
  exact slice-ratification packet, its required change set, and the resulting
  governance commit. It makes the slice in-scope and eligible; it does not
  authorize a controller run.
- A **controller-entry packet** is the immutable execution envelope supplied to
  the controller. It pins already-ratified governance inputs and bounds a run.
- An **execution-evidence bundle** is the post-attempt record of commands,
  commits, tests, isolation, and artifacts. It can prove that a gate passed; it
  cannot make a governance decision.
- A **human-acceptance receipt** accepts generated bootstrap artifacts, the D1
  contract freeze, a live trial, or a slice exit review. It is not an
  open-question ruling and does not replace an operator-decision receipt.
- An **operator-trust policy** is the protected, versioned statement of which
  operator identities and authentication methods a controller accepts. It is
  human-controlled and content-addressed; configuration alone cannot change it.

Content-addressed bindings form acyclic chains. An OQ decision uses governance
source snapshot → required change set plus operator-question packet →
operator-decision receipt → human-applied OQ governance commit. Slice entry uses
eligible governance snapshot plus applicable OQ receipts → slice-ratification
packet plus required change set → human-applied slice governance commit/tree →
slice-ratification receipt. Either accepted governance result may then flow to
controller-entry packet → execution-evidence bundle → human-acceptance receipt.
An object may pin its antecedents, never a descendant that also pins it. In
particular, `BUILD.md` must not hash a controller-entry packet that hashes
`BUILD.md`.

## Authority order

The loop evaluates authority in this order:

1. a controller-supplied, human-approved controller-entry packet bounds the
   current run;
2. `BUILD.md` defines authorized product scope;
3. `DOCTRINE.md` defines architectural law;
4. `AGENTS.md` defines repository boundaries and work discipline;
5. decisions recorded in `docs/OPEN-QUESTIONS.md` and their valid
   operator-decision receipts satisfy named human gates;
6. a protected task manifest selects work inside those bounds; and
7. `docs/IMPLEMENTATION-PLAN.md` and `docs/TEST-PLAN.md` define behavior and
   acceptance.

A lower item can narrow a higher item but cannot expand or contradict it. A
candidate roadmap entry, a task manifest row, a passing test, or an evidence
receipt never authorizes work by itself.

The controller must return `UNAUTHORIZED` or `CONTRACT_INVALID` when these
sources disagree. It must not choose an interpretation and continue.

## Human-controlled inputs

The following remain human-controlled:

- the launch instruction that counts as the explicit implementation task
  required by `AGENTS.md`;
- `BUILD.md` amendments and roadmap `Status`, `Authorized`, entry-gate, and exit
  verdict fields;
- open-question decisions and their operator-decision receipts;
- the protected task-manifest, gate-program, validator/renderer,
  operator-question, operator-decision-receipt, required-change-set,
  controller-entry, slice-ratification-receipt, human-acceptance-receipt,
  operator-trust-policy, and evidence-schema digests named by a
  controller-entry packet;
- production key ceremonies, custody choices, deployment approval, and the V0
  experiential verdict.

An agent may prepare an operator-question packet or slice-ratification packet.
It may not select an answer, create the human receipt, promote a slice, weaken a
protected gate, or turn a candidate record into authority.

## Operator questions and decision receipts

This is the proposed reusable decision contract pending OQ-7. The strict JSON
schemas, validator, canonical renderer, and golden fixtures do not exist until
V0-G0 creates them and a human independently accepts their digests. Before
that bootstrap, the OQ-7 packet is a one-time, manually reviewed Markdown
exception; it is not evidence that the reusable contract already exists.
After bootstrap, canonical packets and receipts are exact-byte-addressed strict
JSON retained outside the implementation checkout; a Markdown rendering is a
review aid and never the source of truth.

An operator-question packet is prepared only for a question already promoted
into `docs/OPEN-QUESTIONS.md`. The OQ-R register in `ROADMAP.md` remains
lightweight speculation and is not bulk-expanded by this contract. Roadmap
questions promote only when their slice-ratification packet is eligible for
preparation, except for a cross-cutting blocker on the authorized V0 runway.

At minimum, a packet ready for human review contains:

- schema version, immutable packet ID, promoted question ID, preparation time,
  and preparer identity or process;
- the exact question, why it is being asked now, the work it blocks, and the
  higher-order governance sources that bound every answer;
- a prepared-against base commit and content digests for relevant governance
  inputs;
- an observed forcing case with a falsifiable sufficiency predicate and
  content-addressed evidence references; absent evidence is explicit rather
  than silently omitted;
- one or more admissible answers with stable answer IDs, fit criteria, and the
  doctrine/authorization basis that makes each selectable;
- the evidence supporting and opposing each answer and its residual
  uncertainty;
- exactly one recommended answer ID, or an explicit `no_recommendation`, with
  rationale;
- consequences for every answer: proposed authority and guarantee deltas,
  blockers that would be satisfied or remain, tasks that would become eligible
  only if every independent authorization gate also passes, documents and exact
  required-change-set references that would require human amendment, and
  replay/fork and abuse/T&S implications; and
- a novelty condition describing evidence that fits no admissible answer and
  therefore requires a replacement packet rather than inference.

An answer that conflicts with `BUILD.md`, `DOCTRINE.md`, or `AGENTS.md` is not
admissible under unchanged governance. The packet may list it as an excluded
answer with the conflict and the separately required constitutional amendment;
it must not render it as a selectable peer. A packet need not invent multiple
substantive answers when only one is admissible: `defer`, `reject_packet`, and
`repack_required` are receipt outcomes, not decorative policy alternatives. A
multipart question must enumerate complete joint answers or split into separate
question IDs; a controller may not compose partial answers.

The packet contains no operator selection, signature, or mutable ruling field.
Once a receipt refers to its digest, changing any byte requires a new packet ID
and a new review. Bulky forcing-case artifacts remain in the external durable
store; the packet carries their role, URI, media type, byte length, and SHA-256
digest.

An operator-decision receipt contains:

- receipt schema version, immutable receipt ID, and an optional superseded
  receipt ID/digest;
- a canonical decision payload containing the promoted question ID, exact
  operator-question-packet SHA-256 digest, human operator identity, decision
  time, and one ruling from
  `select | defer | reject_packet | repack_required`;
- for `select`, exactly one answer ID from the packet and that answer's exact
  required-change-set ID/digest or explicit `not_applicable`;
- for `defer`, a revisit trigger or deadline and optional requested-evidence
  references;
- for `reject_packet`, a reason class and `replacement_packet = required`;
- for `repack_required`, one or more content-addressed novel-evidence
  references; and
- an authentication envelope containing the decision-payload digest,
  authentication method, operator-trust-policy ID/version/digest, and
  content-addressed authentication-evidence reference/digest.

The authentication evidence attests the canonical decision-payload digest, not
the complete receipt bytes that later contain its reference. The receipt digest
covers both payload and envelope metadata without requiring either object to
hash itself. A controller-entry packet pins the exact trust policy and receipt
digests; a mutable controller configuration is never sufficient.

Only `select` can satisfy the named question. `defer` and `reject_packet` leave
the blocker open. `repack_required` states that no registered answer fits and
requires a new packet; it never accepts a free-text hybrid. A no-action policy
must therefore be an explicit admissible answer and be selected, not inferred
from rejection. An unknown answer, a mismatched packet or change-set digest,
missing authentication evidence, or a purported selection embedded in the
question packet is `CONTRACT_INVALID`.

A required change set is an immutable antecedent of the receipt. It pins each
target path's base digest, exact ordered patch operations, and proposed result
digest, or is explicitly `not_applicable`. It may contain stable packet, answer,
and receipt IDs fixed before review, but it embeds neither packet nor receipt
digests. The packet pins the antecedent change-set digest; the receipt pins the
packet, answer, and change set; the applied governance commit records only the
stable receipt ID; and the later controller-entry packet pins the receipt
digest. This preserves the acyclic binding order without an unbounded
receipt-index mutation.

The three OQ-7 bootstrap change sets are a frozen exception to the future JSON
schema. Each is a UTF-8 patch artifact whose header has one ASCII
`key = value` pair per line before one `--PATCH--` delimiter: `schema`,
`change_set_id`, `packet_id`, `question_id`, `answer_id`, `receipt_id`,
`target_count`, then, for every target in application order, `target.N.path`,
`target.N.base_sha256`, and `target.N.result_sha256`. Keys and target paths may
occur only once; indices are contiguous; values are JSON strings except decimal
`target_count`; and no value is a placeholder. The remaining bytes are the
exact unified-diff operations.
The pre-bootstrap controller accepts only the three change-set IDs and digests
pinned by the opaque OQ-7 packet, applies only their listed repository-relative
paths, and verifies every base and result digest.

A valid `select` receipt satisfies only the blocker effects declared for that
answer. Wording such as "task authorized" or "authority gained" is invalid in
a consequence field: the precise terms are "blocker would be satisfied" and
"task would become eligible." Product authority remains the independent
intersection defined in the authority order and, for slices, in the roadmap.

Validators reject unknown, duplicate, missing, placeholder, or conditionally
forbidden fields; duplicate answer IDs; recommendations or selections outside
the answer set; unavailable content-addressed references; governing-input or
required-result mismatches; incomplete consequences; free-text or multi-answer
rulings; missing authentication; and conflicting active receipts without an
explicit supersession chain. Malformation, digest mismatch, or disagreement
with applied governance is `CONTRACT_INVALID`. An absent or non-`select`
receipt, an unapplied required amendment, or evidence matching no answer is
`BLOCKED_HUMAN`.

A procedural receipt may supersede only an unapplied receipt or another
procedural receipt. It cannot revoke or replace an applied `select` decision.
Changing any applied selection requires a new packet with an explicit
transition or reversal answer, its exact required change set, a new `select`
receipt, and human application. Until that chain completes, the prior applied
selection remains active.

A slice-ratification receipt contains its kind/schema/ID, slice ID, exact
slice-ratification-packet and selected required-change-set digests, all included
operator-decision-receipt digests, the resulting governance commit/tree, human
operator identity/time, and an authentication envelope under the same protected
trust-policy discipline. The applied result records only its predeclared stable
receipt ID, never the future receipt digest. The receipt is created after that
commit and makes the slice ratified and eligible only when the declared
`BUILD.md`, roadmap, and task-manifest results match. A later controller-entry
packet pins the receipt digest and remains required to run anything.

A human-acceptance receipt contains its kind/schema/ID, one purpose from
`bootstrap_outputs | contract_freeze | live_trial | slice_exit`, the exact
subject and evidence digests, the permitted purpose-specific verdict, human
operator identity/time, and an authentication envelope. A bootstrap-output
acceptance pins every generated manifest, schema, validator, renderer, fixture,
gate, and candidate tree. A `contract_freeze` receipt pins D1's execution
evidence plus every reviewed contract and golden-fixture digest, with only
`accepted | rejected` as verdicts. A trial or exit receipt pins its prepared
evidence and experiential verdict. It answers neither an OQ nor a scope question.

The controller never emits a blank operator question. When evidence is
sufficient, it prepares the question, admissible answers, consequences, and
recommendation before stopping. When those fields cannot be completed, it emits
only a blocked receipt naming the missing facts and does not invent an answer.

## One-time self-hosting bootstrap

The roadmap linter and governance/evidence validators cannot safely require
themselves to exist before their own creation. The only bootstrap exception is
`V0-G0`.

A human launch instruction must name `V0-G0` explicitly, and `BUILD.md` must
contain a human-approved and human-applied positive authorization for that exact
governance task. Agents may pre-draft the block; only the authenticated human
decision and application give it effect. This document and the bootstrap
exception are not authority. Before `V0-G0` passes and its output digests receive
an independent bootstrap-output human-acceptance receipt, the controller may not
use `next`, select a product milestone, or select a roadmap slice. The bootstrap
task is repository process tooling only; it may not add community record
behavior, transport, credentials, signing, or deployment.

Pending an OQ-7 `select A` or `select B` decision, the proposed positive
authorization is one exact, single-use block under a
`## Governed execution authorization` heading in `BUILD.md`:

```text
<!-- governed-execution:v1 -->
authorization_id = "V0-G0-bootstrap-1"
task = "V0-G0"
decision = "authorized"
scope = "governance-bootstrap-only"
contract_sha256 = "sha256:<64 lowercase hex>"
single_use = true
<!-- /governed-execution -->
```

The pre-bootstrap controller accepts exactly one block, rejects unknown or
duplicate keys, recomputes the contract digest, and accepts no other task or
scope. The explicit bootstrap controller-entry packet separately pins the exact
`BUILD.md` digest and authorization ID, the OQ-7 operator-question-packet and
operator-decision-receipt digests, the selected required change set, the
pre-bootstrap task definition, the bootstrap trust-policy ID/version/contract
digest, and the allowed paths and modes. The `BUILD.md` block does not embed a
descendant packet or receipt digest, avoiding a mutual hash dependency.

The bootstrap and default governed-V0 trust policy is
`manual-controller-channel-v1`. It applies identically to A, B, C, `defer`,
`reject_packet`, and `repack_required`; it does not depend on the ruling it is
authenticating. The same policy separately authenticates the bootstrap launch,
bootstrap-output acceptance, and later governed-V0 launches and acceptances;
no artifact inherits authentication from an earlier ruling. It remains active
until a new operator-question packet, exact transition change set, selected
receipt, and human-applied governance result replace it. A controller-entry
packet cannot select its own trust root.

The human supplies each canonical payload digest through the same
controller-authenticated governance channel used for explicit launch
instructions. The controller records a distinct channel attestation over each
payload digest as external authentication evidence. This contract's digest pins
the concrete policy text. The accepted principal is exactly the one non-service
human principal attested by that protected channel for the OQ-7 decision. The
attestation exposes its channel ID and principal; `operator_id` must equal that
principal, and bootstrap launch and acceptance must use the same channel and
principal. Anonymous, group, service, delegated, or merely payload-asserted
identities are invalid. Evidence attests a payload digest, not enclosing bytes
that contain the evidence reference.

The bootstrap receipt is strict UTF-8 JSON. Both the whole receipt and its
`decision_payload` use RFC 8785 JSON canonicalization for digesting. Its only
top-level keys are `schema`, `receipt_id`, `supersedes`, `decision_payload`, and
`authentication`. `schema` is `oq7-bootstrap-decision-receipt-v1`;
`supersedes` is either `null` or an object containing only `receipt_id` and
`receipt_sha256`. The payload contains only `question_id`, `packet_id`,
`packet_sha256`, `operator_id`, `decided_at`, `ruling`, and the
ruling-conditional fields: `select` adds `answer_id`,
`required_change_set_id`, and `required_change_set_sha256`; `defer` adds at
least one of `revisit_trigger` or `revisit_deadline` and may add
`requested_evidence`; `reject_packet` adds `reason_class` and the fixed
`replacement_packet = "required"`; and `repack_required` adds a nonempty
`novel_evidence` array. Fields belonging to another ruling are forbidden. The
authentication object contains only `payload_sha256`, `method`,
`trust_policy_id`, `trust_policy_version`, `trust_policy_sha256`, `channel_id`,
`attested_principal`, `evidence_uri`, `evidence_media_type`, `evidence_bytes`,
and `evidence_sha256`. The fixed values are question `OQ-7`, packet ID
`OQP-OQ-7-2026-07-27-03`, method `manual_controller_channel`, policy ID
`manual-controller-channel-v1`, policy version `1`, and a policy digest equal
to this contract's SHA-256. Unknown, duplicate, missing, non-canonical, or
inapplicable fields are invalid.

For all frozen bootstrap JSON, IDs are nonempty printable ASCII without
whitespace, timestamps are UTC RFC 3339 strings, byte lengths are nonnegative
JSON integers, and SHA-256 values are `sha256:` plus exactly 64 lowercase hex
digits. An evidence reference contains only nonempty `role`, absolute `uri`,
nonempty `media_type`, `bytes`, and `sha256`; `requested_evidence` and
`novel_evidence` are arrays of those objects, with `novel_evidence` nonempty.
A `select` receipt's `receipt_id` must equal the selected frozen change set's
predeclared `receipt_id`, and its answer/change-set ID/digest must equal the
mapping reviewed in the opaque packet. A superseding receipt must name the exact
active receipt ID/digest; otherwise both receipts conflict and are invalid.

The bootstrap controller-entry packet is separately authenticated strict UTF-8
JSON. Its only top-level keys are `schema`, `packet_id`, `launch_payload`, and
`authentication`; the packet and payload use RFC 8785 canonicalization.
`schema` is `oq7-bootstrap-controller-entry-v1`. The payload contains only
`authorization_id`, `task_ids`, `base_commit`, `allowed_ancestry`,
`governance_inputs`, `oq7_decision`, `allowed_paths`, `protected_paths`,
`evidence_policy`, `frozen_verifier`, `network_mode`, `credential_mode`,
`donor_mode`, `operator_id`, and `authorized_at`. `task_ids` is exactly
`["V0-G0"]`; `allowed_ancestry` is exactly `[base_commit]`; and the modes are
exactly `denied`, `none`, and `inaccessible`.

`governance_inputs` is a lexically path-sorted array whose objects contain only
`path`, `bytes`, and `sha256`. It contains exactly `AGENTS.md`, post-change-set
`BUILD.md`, `DOCTRINE.md`, `IDEAS.md`, `ROADMAP.md`, this contract,
`docs/IMPLEMENTATION-PLAN.md`, post-change-set `docs/OPEN-QUESTIONS.md`,
`docs/TEST-PLAN.md`, `docs/OQ-7-PACKET.md`, and all three OQ-7 change-set
artifacts. `oq7_decision` contains only `packet_id`, `packet_sha256`,
`receipt_id`, `receipt_sha256`, `answer_id`, `change_set_id`, and
`change_set_sha256`, all equal to the selected A or B chain.

`allowed_paths` is exactly the lexically sorted array `governance/**`,
`scripts/v0-gate`, and `tests/governance/**`. Its `**` matches only descendant
regular files; symlinks, hard links to outside files, special files, and path
traversal are invalid. `protected_paths` is exactly every tracked repository
path present at `base_commit`; no G0 candidate may modify or delete one. Thus G0
can only add governance tooling beneath the three allowed patterns. The
`evidence_policy` object contains only an absolute `destination_uri`, UTC
`retention_until`, and `readback_required = true`.

`frozen_verifier` contains only `program_id`, `version`, absolute `uri`,
`bytes`, and `sha256`; its ID/version are exactly
`oq7-prebootstrap-verifier`/`1`. It identifies the controller-owned verifier
outside the candidate checkout, and the execution-evidence bundle must pin the
same bytes. The authentication object has the same fixed keys and policy values
as the decision receipt but attests the canonical `launch_payload` digest. It is
a distinct human launch decision, not a consequence or authentication side
effect of selecting A or B.

The bootstrap-output human-acceptance receipt is also separately authenticated
strict UTF-8 JSON under the same policy. Its only top-level keys are `schema`,
`receipt_id`, `acceptance_payload`, and `authentication`; the receipt and payload
use RFC 8785 canonicalization. `schema` is
`oq7-bootstrap-output-acceptance-v1`. The payload contains only `purpose`,
`run_id`, `controller_entry_packet_sha256`, `execution_evidence_sha256`,
`candidate_commit`, `candidate_tree`, `artifact_manifest`, `verdict`,
`rejection_reason`, `operator_id`, and `decided_at`. `purpose` is exactly
`bootstrap_outputs`; and `verdict` is `accepted` or `rejected`.
`rejection_reason` is required only for `rejected` and forbidden for
`accepted`.

`artifact_manifest` is a path-sorted array whose objects contain only `role`,
`path`, absolute `uri`, `media_type`, `bytes`, and `sha256`. It must equal both
the execution-evidence bundle's `candidate_outputs` submanifest and every
regular file added beneath the three allowed-path patterns; no accepted subset,
extra output, duplicate path, or unclassified file is valid. Its role vocabulary
is exactly
`task_manifest`, `task_manifest_schema`, `roadmap_authorization_validator`,
`operator_trust_policy_schema`, `operator_question_schema`,
`operator_decision_receipt_schema`, `required_change_set_schema`,
`slice_ratification_schema`, `controller_entry_schema`,
`human_acceptance_schema`, `execution_evidence_schema`,
`governance_validator`, `question_renderer`, `valid_fixture`,
`invalid_fixture`, `gate_program`, `protected_path_check`,
`evidence_readback_check`, `offline_preflight`, `requirement_mapping`, and
`roadmap_normalization_proposal`; every role must occur, while fixture roles may
repeat. `run_id`, `controller_entry_packet_sha256`, `candidate_commit`, and
`candidate_tree` must equal the corresponding fields in the pinned
execution-evidence manifest, and `execution_evidence_sha256` must address that
exact retained bundle. The authentication object has the same fixed keys,
channel, principal, and policy values as the earlier bootstrap artifacts and
attests the canonical `acceptance_payload` digest. Only `accepted` satisfies the
bootstrap-output gate; rejection cannot be interpreted as partial acceptance.

Before the general validators exist, the pre-bootstrap controller validates
the fixed decision-receipt, patch, bootstrap-entry, and bootstrap-acceptance
grammars above and treats the manually reviewed
`OQP-OQ-7-2026-07-27-03` Markdown packet as opaque exact bytes. The frozen
verifier is controller-owned and outside the G0 candidate checkout; generated
G0 validators cannot approve themselves. It verifies packet/change-set digests,
conditional fields, distinct common-policy attestations, and applied result
digests; it does not claim to parse the Markdown packet with a schema that does
not exist. It may validate no other question and may not accept `next`. A V0-G0
launch requires `select A` or `select B`; `select C` and every procedural ruling
keep G0 unavailable. A mention of `V0-G0` anywhere else in `BUILD.md` is not
authorization. The human removes the single-use block in the governance commit
that records the accepted bootstrap-output human-acceptance receipt; Git history
retains the authorization.

`single_use = true` permits at most one accepted V0-G0 candidate. A failed,
receipted attempt may retry from the same pinned base while every governance
input remains byte-identical; a changed base/input, human revocation, or accepted
candidate exhausts the authorization and requires new human action.

`V0-G0` delivers:

- a strict JSON task manifest and schema;
- a roadmap/authorization validator with valid and invalid golden fixtures;
- separate strict schemas and validators for operator-trust policies,
  operator-question packets, operator-decision receipts, required change sets,
  slice-ratification packets/receipts, controller-entry packets,
  human-acceptance receipts, and execution-evidence bundles;
- a deterministic human-readable question renderer that never adds, drops, or
  merges an answer;
- valid and invalid golden fixtures covering selection, deferral, packet
  rejection, novelty repacking, unknown or duplicate answers, hybrid rulings,
  digest substitution, missing evidence, changed consequences, and conflicting
  unsuperseded receipts;
- the root, side-effect-free command `./scripts/v0-gate TASK_ID`;
- protected-path and allowed-path checks;
- digest-verified external evidence write/readback and retention-policy checks;
- an offline/network-denial preflight for V0-M1, V0-D2, V0-M2, V0-M2A, and
  V0-M3 through V0-M5; and
- stable requirement IDs and milestone mappings for `docs/TEST-PLAN.md`.

Its candidate commit passes only when this command exits zero in a fresh clean
checkout:

```text
./scripts/v0-gate V0-G0
```

The bootstrap controller-entry packet pins the pre-bootstrap task definition in
this document, the OQ-7 packet/receipt pair, and the positive `BUILD.md` row. The
self-created G0 gate is test evidence only and cannot approve itself. The
resulting execution-evidence bundle pins the new manifest, evidence and
governance-artifact schemas, validator and renderer programs, gate program,
fixtures, and candidate tree. A human accepts those digests in a separate
bootstrap-output human-acceptance receipt before the controller may use `next`
selection. That receipt accepts generated artifacts; it does not answer OQ-7 a
second time.

## Pre-implementation contract freeze

`V0-D1` is a documentation-and-fixture task, not product implementation. It
closes the remaining M1 choices that a non-interactive implementation task must
not decide implicitly. It delivers:

- the supported Python/build/install matrix and canonical root environment
  contract;
- observable deep-immutability rules, including mutation of constructor inputs
  and nested values returned by accessors;
- complete `EventBatch` and `Page` value contracts, port sync/async semantics,
  and typed failure behavior;
- one consistent rule for required normalized repository revision/commit order;
- strict `$type`, unknown-field, DID, CID, AT URI, datetime, and cross-field
  result validation behavior;
- a complete ordinary-post fixture with exact bytes/CID evidence; and
- golden inputs and outputs for canonical JSON, DAG-CBOR evidence,
  delete-envelope evidence, semantic/event-variant keys, deterministic authority
  rkeys, and quarantine keys.

If this work uncovers a protocol or governance choice, it adds a named open
question and returns `BLOCKED_HUMAN`; it does not choose through it. Pure
toolchain or implementation-mechanism choices may be proposed in the contract
when their observable tests and compatibility bounds are explicit.

Its candidate commit passes only when this command exits zero in a fresh clean
checkout:

```text
./scripts/v0-gate V0-D1
```

V0-M1 may not start until the controller-entry packet pins the accepted
contract-freeze human-acceptance receipt and its human-reviewed V0-D1 contract
and fixture digests.

## Controller-entry packet

The controller receives an immutable controller-entry packet outside the task
checkout. It is independently authenticated under the pinned operator-trust
policy. An operator-decision receipt may select that policy but does not
authenticate a launch. At minimum the packet contains:

- kind, schema version, packet identifier, and applicable positive
  authorization ID;
- authorized task IDs, or the literal `next` within a bounded lane only when
  the pinned OQ-7 decision selected answer A; answer B requires exact task IDs
  and answer C makes every governed-run request unauthorized;
- base commit and allowed ancestry;
- digests of `AGENTS.md`, `BUILD.md`, `DOCTRINE.md`, `ROADMAP.md`,
  `docs/OPEN-QUESTIONS.md`, this contract, the task manifest, gate program,
  every applicable governance/evidence schema, validator and renderer program,
  fixture set, operator-trust policy, implementation plan, and test plan;
- for every applicable open question, its ID, operator-question-packet digest,
  selected answer ID, operator-decision-receipt digest, and selected required
  change-set digest or `not_applicable`;
- allowed and protected paths;
- external evidence destination and retention/readback policy;
- network mode, credential mode, and donor mode; and
- human authorization identity, time, and authentication evidence.

For a controlled live exercise, the packet additionally pins its operation ID,
protected harness digest, target allow-list, request/write ceilings, timeout and
retry bounds, idempotency input, allowed record kinds, retention behavior, and
receipt schema.

The packet never embeds a credential or secret. The controller passes only an
allow-listed environment to the task checkout and never records the full host
environment in evidence.

`network_mode` is one of:

- `denied`: no network route is available;
- `public_read`: separately authorized public read access for a V0-M6 exercise;
  or
- `nonproduction_write`: separately authorized access to the disposable actor
  selected under OQ-3 for a V0-M7/M8 exercise.

`credential_mode` is one of:

- `none`; or
- `nonproduction_external_ref`: the task receives only an allow-listed external
  reference under OQ-3, never secret material in the packet or repository.

Production credentials, production identity, and production write targets are
invalid in every V0 mode regardless of packet contents. Their presence returns
`UNAUTHORIZED` before task code runs.

`donor_mode` is one of:

- `inaccessible`: the task cannot read donor repositories and implements from
  the local contracts; OQ-6 does not block it; or
- `licensed`: OQ-6 is decided with a selected answer permitting the copy, its
  valid operator-decision receipt is pinned, and every copied fragment has the
  required reuse-matrix and license evidence.

There is no machine-verifiable “consulted but did not copy” mode.

## V0 task queue

No V0 milestone is presumed complete from prose, commit messages, or the
existence of files. Completion is computed only by the protected cumulative
gate at the pinned candidate tree.

| Task | Class | Prerequisites and human blockers | Side-effect-free done command |
|---|---|---|---|
| `V0-G0` | governance bootstrap | OQ-7 decided with selected A or B; valid decision receipt/change set; positive BUILD row; explicit human bootstrap controller-entry packet; clean pinned base | `./scripts/v0-gate V0-G0` |
| `V0-D1` | documentation and golden fixtures | V0-G0 PASS; bootstrap-output human-acceptance receipt; protected controller-entry packet | `./scripts/v0-gate V0-D1` |
| `V0-M1` | agent-local, offline | V0-D1 PASS; accepted contract-freeze human-acceptance receipt; donor mode fixed | `./scripts/v0-gate V0-M1` |
| `V0-D2` | documentation; storage refreeze | V0-M1 PASS; explicit human storage-refreeze instruction | `./scripts/v0-gate V0-D2` |
| `V0-M2` | agent-local, offline | V0-D2 PASS | `./scripts/v0-gate V0-M2` |
| `V0-M2A` | agent-local, offline archive tooling | V0-M2 PASS | `./scripts/v0-gate V0-M2A` |
| `V0-M3` | agent-local, offline | V0-M2A PASS | `./scripts/v0-gate V0-M3` |
| `V0-M4` | agent-local, offline | V0-M3 PASS; OQ-5 decided with a valid selected answer | `./scripts/v0-gate V0-M4` |
| `V0-M5` | agent-local, offline | V0-M4 PASS | `./scripts/v0-gate V0-M5` |
| `V0-M6` | agent-local plus live read boundary | V0-M5 PASS; OQ-2 decided with a valid selected answer | `./scripts/v0-gate V0-M6` |
| `V0-M7` | guarantee; isolated live writer | V0-M6 PASS; OQ-1, OQ-3, and OQ-4 decided with valid selected answers; OQ-6 only for donor copying | `./scripts/v0-gate V0-M7` |
| `V0-M8` | human trial and verdict | V0-M7 PASS; non-production trial authorization | `./scripts/v0-gate V0-M8` validates the completed live-trial human-acceptance receipt |

The implementation scope of M1, D2, M2, M2A, and M3 through M8 remains the
numbered list in `docs/IMPLEMENTATION-PLAN.md`. Gates are cumulative:

- M1 proves the three clean-build distributions, strict models and provisional
  schemas, deterministic hash vectors, fixtures, and dependency/import
  boundaries.
- D2 records the human-selected storage forcing case and refreezes the V0
  hot/cold custody, retention, dependency, and process boundaries.
- M2 adds SQLite schema/migration, compact observation/audit state, archive
  controls, reducer, replay, and hot-tail rebuild proof.
- M2A adds separately installed archive tooling, sealed Parquet
  generations/manifests, bounded read-only DuckDB, verified prefix retention,
  and sealed-history-plus-tail parity/rebuild proof.
- M3 adds the named offline vertical acceptance test and sanitized rendered,
  audit, fake-call, and rebuild evidence.
- M4 adds the complete hardening matrix, including the selected OQ-5 fixture.
- M5 adds the canonical read-only AppView, wire contracts, security headers,
  health/freshness, subprocess, and WAL-concurrency proof.
- M6 adds authenticated live read ingestion and resolution under OQ-2.
- M7 adds the isolated real authority adapter and CLI under OQ-1/OQ-3/OQ-4.
- M8 prepares evidence, stops for the human trial, and passes only after the
  live-trial human-acceptance receipt exists. A machine cannot decide whether
  the surface feels like a real place.

An unattended offline tranche may cover M1, D2, M2, M2A, and M3. It may extend
through M5 only when OQ-5 is already decided with a valid selected answer and
pinned in the controller-entry packet. It must not skip M4 and run M5 because
M4 is blocked.

## Selector algorithm

The controller applies this algorithm without speculative work:

1. Refuse a dirty or unpinned base. If resuming, require a matching active-run
   receipt and resume only that task.
2. Validate the controller-entry packet, protected digests, applicable
   operator-question-packet/operator-decision-receipt pairs, selected required
   change sets, and allowed path set. A selected answer clears only its named
   blocker and only when the repository decision and required result digests
   agree. Before G0 exists, apply only the frozen OQ-7 bootstrap checks; do not
   pretend to run the absent general validator.
3. After G0, validate the V0 task manifest and the V0-relevant governance AST
   before selecting V0 work. Parse and report post-V0 roadmap defects, but do
   not let them block the V0 lane. Require a completely valid roadmap AST only
   at the V0-to-slice transition.
4. Before the G0 bootstrap-output human-acceptance receipt exists, accept only a
   controller-entry packet that explicitly names `V0-G0`; after G0 PASS, return
   `AWAITING_HUMAN` until that receipt pins its generated digests.
5. In the V0 lane, inspect tasks in the table order. A task is complete only
   when its protected done command exits zero at the pinned tree and its
   evidence validates.
6. Select the first incomplete task. If a prerequisite or named human decision
   is absent, emit `BLOCKED_HUMAN` and stop. Emit or reference a complete
   operator-question packet when its required fields can be filled; otherwise
   identify the missing evidence in the blocked receipt. Never skip to a later
   task.
7. After a task candidate passes, emit evidence and stop or continue only if the
   same controller-entry packet authorizes the next task. Advance the per-task
   base to the accepted candidate; each task remains one bounded commit.
8. At M8, prepare the trial bundle and emit `AWAITING_HUMAN`. Advance only after
   the controller receives the live-trial human-acceptance receipt.
9. If the V0 verdict is not “feels real,” halt the slice ladder. If it is
   “feels real,” close the V0 lane and evaluate the slice lane.
10. At the slice transition, first prove that every `done` predecessor has a
    valid slice-exit human-acceptance receipt. Then, in document order, select
    the earliest incomplete slice whose canonical status is `ratified`.
    Validate its literal `Authorized: yes`, positive `BUILD.md` row,
    slice-ratification receipt, dependencies, and blocker decisions. Any
    disagreement is `CONTRACT_INVALID`; any missing prerequisite is
    `BLOCKED_HUMAN`. Do not filter it out and consider a later slice.
11. Run the first failing side-effect-free task gate in that selected slice.
    When every task passes, emit `AWAITING_HUMAN` for exit review; do not select
    another slice until the human records a valid exit verdict and slice-exit
    human-acceptance receipt.

Only when no ratified slice is active, blocked, machine-complete awaiting review,
or inconsistent may a controller-entry packet separately authorize preparation
of the earliest candidate slice-ratification packet whose prerequisites exist.
Packet preparation cannot modify its status, `Authorized` line, or entry gate,
and it ends with `AWAITING_HUMAN`.

## Task transaction

Every task runs in a disposable checkout rather than cleaning, resetting, or
reusing a person's worktree. The controller-entry packet pins a run-root commit.
The first task base is that root; in a multi-task tranche, each later task base
is the previous task's accepted candidate.

1. Record the exact clean task-base commit and protected input digests.
2. Create implementation and tests together within the allowed paths.
3. Run the task gate and all cumulative gates required at that milestone.
4. Create exactly one non-merge candidate commit whose parent is the current
   task base and whose message carries `Governor-Task: TASK_ID`.
5. Verify the commit again in a fresh clean checkout with the allow-listed
   environment and required network denial.
6. Validate changed paths, commit count, evidence, and final clean status.
7. Make the candidate available for promotion only after the external evidence
   bundle validates.

A failed candidate is not amended into apparent success and is not promoted.
Retry from the same approved task base as a new disposable attempt. Advance the
task base only after acceptance, and obtain a new controller-entry packet if
governance inputs changed.

## Gate rules

Every done command is a probe, never an action. It must be safe to run repeatedly
and must not deploy, publish, emit authority records, mutate a user repository,
or contact a live service merely to determine completion.

The root gate:

- exits zero only on PASS and nonzero otherwise;
- runs the cumulative suite through the selected task;
- runs boundary/isolation checks whenever package scaffolding exists;
- runs the offline vertical acceptance and rebuild-parity gates from M3 onward;
- uses stable requirement IDs from `docs/TEST-PLAN.md` and emits a coverage
  report showing every requirement as pass, fail, or explicitly not applicable;
- produces machine-readable test output and sanitized transcripts; and
- refuses a task that altered its own protected task definition, gate, schema,
  golden acceptance fixture, or authorization input.

G0, D1, M1, D2, M2, M2A, and M3 through M5 run in `network_mode=denied` and
`credential_mode=none`. All tests use fake adapters and temporary directories.
Every done gate, including M6 and M7, remains offline and side-effect-free. An
M6 exercise alone may use `public_read` with `none`; an M7 or M8 exercise alone
may use `nonproduction_write` with `nonproduction_external_ref`. Every other
task/mode combination is `UNAUTHORIZED`. Separately authorized exercises emit
receipts; the done gate validates those receipts without replaying the network
action or authority write.

## Controlled live exercises

The implementation task shell always has `network_mode=denied` and
`credential_mode=none`. It cannot invoke a general network client. Only the
controller may launch a protected, digest-pinned exercise harness in a separate
process with one of these operation IDs:

| Operation | Mode | Allowed action | Stop rule |
|---|---|---|---|
| `V0-X6-READ-SMOKE` | `public_read` + `none` | Bounded reads from the packet's public event/resolver allow-list; zero writes | Bounded retry from packet, then stop and receipt failure |
| `V0-X7-WRITE-SMOKE` | `nonproduction_write` + `nonproduction_external_ref` | Create only the packet-bounded admission/removal records in the OQ-3 disposable community repo | Never blind-retry an ambiguous write; resolve the deterministic operation ID, then return success or stop |
| `V0-X8-HUMAN-TRIAL` | packet-bounded non-production modes | Human trial procedure using accepted M7 artifacts and only the disposable actors/records named in the packet | Always stop for the human trial/verdict receipt |

The controller-owned invocation is:

```text
./scripts/v0-exercise OPERATION_ID --packet READ_ONLY_PATH
```

The protected harness refuses an unrecognized operation, target, DID/repo,
record collection, method, or ceiling. The M7 packet gives an exact maximum
write count and allows only the permanent admission and removal NSIDs pinned by
the selected OQ-1 decision receipt; `invalid.community.*` is never emitted. It supplies
the semantic operation/idempotency inputs before the first attempt.

Exercise records are not deleted as cleanup: they remain in the disposable
non-production repository and their retention is stated in the receipt. No
exercise may touch a production DID, repo, endpoint, credential, or user post.
The harness returns a schema-valid external receipt; it does not modify a task
checkout or claim community authority for the receipt itself.

These modes are V0-only. S1's future slice-ratification packet must define and
ratify a separate production operation model; it may not relabel a V0 mode as
production.

## Execution-evidence bundle

Evidence lives outside the Git worktree so that committing evidence cannot
change the tree it claims to attest. The controller chooses the destination and
retains it as a CI artifact or equivalent durable object.

Before returning `PASS`, the controller closes its writer, reads every manifest
and artifact back from the destination named by the controller-entry packet,
and rechecks byte length and SHA-256. Failed write/readback is
`ENVIRONMENT_BLOCKED` or `CHECK_FAILED` according to whether the store or the
produced bytes failed; it never degrades to unretained local output.

Every attempt contains a canonical `manifest.json` with:

- evidence schema, run, task, controller-entry-packet, base, candidate commit,
  and tree identifiers;
- protected-input and gate digests;
- exact command argument arrays, exit codes, start/end times, and transcript
  hashes;
- changed paths, commit topology, and clean-tree assertions;
- network, credential, and donor modes;
- a `candidate_outputs` submanifest giving exactly `role`, `path`, absolute
  retained `uri`, `media_type`, `bytes`, and `sha256` for every regular file
  added or changed in the candidate tree;
- a separate `evidence_artifacts` submanifest for transcripts, test reports,
  screenshots, and other non-candidate review evidence;
- requirement coverage and applicable invariant results; and
- one final outcome from the vocabulary below.

Common artifacts are sanitized stdout/stderr transcripts, JUnit XML, the
requirement-coverage report, commit/path report, and a SHA-256 artifact
manifest. They remain in `evidence_artifacts`, never `candidate_outputs` unless
the task also commits those exact bytes as declared deliverables. Task-specific
artifacts begin only when the task creates the relevant surface. Earlier bundles
mark them `not_applicable`; they do not silently omit them.

Rendered snapshots, audit exports, hashes, and receipts are test or observer
evidence. They must never be described as community authority.

An operator-question packet is not an execution-evidence bundle: it references
forcing-case evidence by digest. Antecedent operator-decision and prior
human-acceptance receipts may be retained beside execution evidence and
referenced from its manifest, but they remain human governance inputs rather
than gate-generated artifacts. A receipt accepting the current run, trial, or
exit must point one-way to the completed evidence; that evidence must not refer
to its future acceptance receipt. A validator rejects any artifact whose fixed
kind is reclassified into another role.

## Outcomes and stop behavior

The controller uses these terminal outcomes:

- `PASS`: the candidate and evidence passed; advance only if the
  controller-entry packet authorizes another task.
- `CHECK_FAILED`: a test or implementation gate failed; retry the same task or
  stop. This is not a governance decision.
- `BLOCKED_HUMAN`: a named decision or approval is absent, deferred, rejected,
  novel, or not yet applied; emit or reference a complete operator-question
  packet when possible and stop without an implementation commit.
- `AWAITING_HUMAN`: machine work passed but a trial, slice ratification, or exit
  review remains human.
- `UNAUTHORIZED`: the requested task is outside the positive authorization
  intersection; hard stop without mutation.
- `DIRTY_BASE`: the supplied base is not the clean pinned tree; hard stop.
- `ENVIRONMENT_BLOCKED`: a required sandbox, isolation, or external test
  facility is unavailable; hard stop without weakening the gate.
- `CONTRACT_INVALID`: governance inputs conflict, fail validation, or cannot be
  parsed strictly; hard stop without guessing.

A blocked receipt records the task, base, blocker IDs, source locations, facts,
missing evidence, and the operator-question-packet digest when one exists. It
never duplicates, extends, or invents an answer and never records an
agent-selected governance answer.

## Protected governance changes

During V0-M1, V0-D2, V0-M2, V0-M2A, V0-M3 through V0-M8, and every slice task,
task manifest, gate program, operator-question packets, operator-decision
receipts, required change sets, operator-trust policies, slice-ratification
packets/receipts, human-acceptance receipts, governance/evidence schemas,
validators and renderers, `AGENTS.md`, `BUILD.md`, `DOCTRINE.md`, `ROADMAP.md`,
`docs/OPEN-QUESTIONS.md`, implementation/test plans, golden acceptance fixtures,
and human receipts are read-only. If one must change, the controller stops. A
separately authorized governance task produces a one-commit proposal and new
evidence; a human then issues a new controller-entry packet pinning the result.

This prevents an implementation task from weakening its own definition of done.
