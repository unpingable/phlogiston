# V0 open questions

Phase 0 design work is unblocked. OQ-5 is decided (submission is signed
intent at admission time) and no longer blocks V0-M4; OQ-6 blocks copying
donor source; OQ-7 is decided (answer A), activating the governed-execution
contract; OQ-2, OQ-1, OQ-3, and OQ-4 are decided (answer A each), unblocking
V0-M6 and V0-M7. OQ-8–OQ-10 are post-V0 SCV0 product blockers and do not
retroactively block V0 or the fixture-only SCV0-M1/M2 candidates. The open
questions are not license to expand scope.

## Register contract

Every promoted question carries explicit `Status`, `Operator-question packet`,
`Selected answer`, and `Operator-decision receipt` fields. Until OQ-7 selects A
or B and V0-G0's outputs are human-accepted, these fields are a documentary
projection rather than validated machine input. `open` means no valid selected
answer has been applied. `decided` requires a human `select` receipt over an
exact packet plus every required governance result. `defer`, `reject_packet`,
and `repack_required` leave the question open.

A recommendation is agent-preparable analysis, never a ruling. The register may
record a stable external receipt ID in the selected change. A later
controller-entry packet pins the receipt digest when governed execution is
requested; a no-go decision remains in the authenticated external receipt and
must be pinned by any future superseding question packet. Neither path makes a
receipt and its selected patch mutually hash each other. The full proposed
contract is in `docs/GOVERNED-LOOP.md`.

## OQ-1 — Permanent Lexicon namespace

**Status:** decided

**Operator-question packet:** [OQ-1-PACKET.md](OQ-1-PACKET.md) — prepared
unsigned packet `OQP-OQ-1-2026-08-14-01`

**Selected answer:** A — adopt `community.phlogiston.app` as the permanent
project-controlled Lexicon domain (NSID authority `app.phlogiston.community.*`)

**Operator-decision receipt:** `OQDR-OQ-1-2026-08-14-A-01` — external;
authenticated under `manual-controller-channel-v1`

**Blocks:** publishing Lexicons and creating real community records.

Which owned reverse-DNS authority will replace `invalid.community.*`? The
choice is permanent protocol surface: all four NSIDs move together, and the
reserved draft IDs must never be published or aliased.

**Decided:** the operator selected A on 2026-08-14, naming
`community.phlogiston.app` (NSIDs `app.phlogiston.community.{profile,submit,
admission,modAction}`, terminal names and record shapes preserved). The
atomic rename of the four `invalid.community.*` V0 NSIDs is the direct
consequence of this ruling.

## OQ-2 — Authority-observation authenticity

**Status:** decided

**Operator-question packet:** [OQ-2-PACKET.md](OQ-2-PACKET.md) — prepared
unsigned packet `OQP-OQ-2-2026-08-14-01` with 2026-08-14 Jetstream v2 evidence

**Selected answer:** A — require independently verifiable repository evidence
at ingest

**Operator-decision receipt:** `OQDR-OQ-2-2026-08-14-A-01` — external;
authenticated under `manual-controller-channel-v1`

**Blocks:** allowing live admissions/removals to affect the AppView.

A Jetstream-shaped JSON event identifies a repo DID and CID but is not itself
the signed repository proof asserted by the doctrine. Must `communitywatch`:

1. retain and independently verify repository commit/CAR material; or
2. trust a specifically configured relay's verification and state that trust
   boundary in every audit/export?

The same review must ratify subject-resolution trust: independently verify
repo/CID evidence or accept the hosting PDS's attestation. Event and resolver
policies remain separately labeled even if both choose an attested boundary.

**Decided:** the operator selected A on 2026-08-14 with this qualification,
recorded verbatim in the receipt's authentication evidence: Jetstream event
data is transport/discovery evidence and is not independently authoritative;
verification must validate the repository proof, identity/signature, and MST
membership or non-membership as applicable; where a fetched proof represents
a repository revision later than the triggering Jetstream event, it may
establish current repository state but must not be represented as
cryptographic authentication of that historical event — the implementation
must fail closed, resynchronize, or record that distinction explicitly.

## OQ-3 — Non-production community actor bootstrap

**Status:** decided

**Operator-question packet:** [OQ-3-PACKET.md](OQ-3-PACKET.md) — prepared
unsigned packet `OQP-OQ-3-2026-08-14-01`

**Selected answer:** A — authenticated capability on the existing disposable
actor, no signing custody

**Operator-decision receipt:** `OQDR-OQ-3-2026-08-14-A-01` — external;
authenticated under `manual-controller-channel-v1`

**Blocks:** the real `AuthorityWriter` adapter and human V0 trial.

Choose where the test community DID/repository lives, who controls it, which
supported PDS authentication flow `communityd` uses, and which external
credential provider supplies the non-production secret. Clarify whether
“communityd holds authority keys” means direct signing custody or an
authenticated capability to ask the hosting PDS to commit to the community
repo.

**Decided:** the operator selected A on 2026-08-14. The disposable V0
community actor is `did:plc:exampleparticipantabcdef`
(`participant.example.com`). `communityd` authenticates through an
externally supplied app-password/session capability; the PDS retains
signing/key custody. Credentials must remain outside repository, packets,
logs, receipts, and evidence.

## OQ-4 — Administrator authentication and attribution

**Status:** decided

**Operator-question packet:** [OQ-4-PACKET.md](OQ-4-PACKET.md) — prepared
unsigned packet `OQP-OQ-4-2026-08-14-01`

**Selected answer:** A — local OS/UID authorization with community-attested
actor attribution

**Operator-decision receipt:** `OQDR-OQ-4-2026-08-14-A-01` — external;
authenticated under `manual-controller-channel-v1`

**Blocks:** treating a real operator DID in `actor` as more than an unchecked
claim.

The offline CLI proposal treats OS access as authorization and the configured
administrator DID as attribution attested by the community actor. Ratify that
as the deliberately local V0 model, or require an independently authenticated
admin request before the community actor emits.

**Decided:** the operator selected A on 2026-08-14. The local administrator
model is ratified: OS/UID authorization with community-attested actor
attribution; no remote V0 admin endpoint. For V0, the administrator DID may
equal the community actor DID (`did:plc:exampleparticipantabcdef`). Real
delegated admin auth remains post-V0 protocol work.

## OQ-5 — Submission mutation after admission

**Status:** decided

**Operator-question packet:** [OQ-5-PACKET.md](OQ-5-PACKET.md) — prepared
unsigned packet `OQP-OQ-5-2026-08-14-01`

**Selected answer:** A — submission is signed intent at admission time

**Operator-decision receipt:** `OQDR-OQ-5-2026-08-14-A-01` — external;
authenticated under `manual-controller-channel-v1`

**Blocks:** the submission-mutation reducer fixture in implementation
milestone V0-M4. It does not block the core submit/admit/render/remove
acceptance scenario, which contains no submission mutation.

If the author updates or deletes only the `invalid.community.submit` record
after a valid admission, does the post leave the community view? The post
itself remains exact and available; this is a consent/governance choice, not a
transport failure.

**Recommended decision:** treat submission as signed intent at admission time.
Its later mutation remains audit-visible but does not revoke the community's
separate admission. Post update/deletion still hides the post, and V0 defines
no author-withdrawal record.

## OQ-6 — Donor license path

**Status:** open

**Operator-question packet:** not prepared

**Selected answer:** none

**Operator-decision receipt:** none

**Blocks:** copying any Labelwatch source rather than independently
reimplementing its patterns.

Choose the new repository's license and whether copied donor fragments follow
Labelwatch's MIT or Apache-2.0 option. Add the required license/notices and
per-file modification/provenance records before the first copy.

**Recommended decision:** use the same dual `MIT OR Apache-2.0` expression as
the donor unless the project has a broader licensing policy.

## OQ-7 — Governed-loop entry, decision, and evidence contract

**Status:** decided

**Operator-question packet:** [OQ-7-PACKET.md](OQ-7-PACKET.md) — prepared
unsigned bootstrap packet

**Selected answer:** A

**Operator-decision receipt:** `OQDR-OQ-7-2026-07-27-A-02` — external;
authenticated under `manual-controller-channel-v1`

**Blocks:** `V0-G0`, unattended `next` task selection, and product
implementation under the governed loop. A direct implementation task may still
be separately authorized under `AGENTS.md`, but it is not a governed-loop run.

`ROADMAP.md` requires a strict roadmap validator and reviewable evidence before
autonomous execution, but the validator cannot gate its own creation and the
repository has no durable definition of the launch instruction, protected task
inputs, or minimum execution-evidence bundle.

Select or replace the proposal in `GOVERNED-LOOP.md`, including:

1. how a controller authenticates the human controller-entry packet that
   satisfies `AGENTS.md`'s explicit-implementation-task rule;
2. which human-approved and human-applied positive `BUILD.md` row authorizes the
   non-product `V0-G0` tooling bootstrap;
3. which manifest, gate, schema, fixture, and governance-document digests are
   protected for a run;
4. whether evidence may live outside the Git worktree and which durable store
   retains it;
5. the minimum manifest, command transcript, test, commit, isolation, and
   artifact evidence required for PASS; and
6. the one-time `V0-G0` bootstrap and independent human-acceptance step
   before `next` selection becomes available;
7. the operator-question-packet, operator-decision-receipt, required-change-set,
   recommendation, admissible-answer, consequence, and novelty contracts; and
8. the acyclic digest order among the OQ-7 packet/receipt, positive `BUILD.md`
   row, controller-entry packet, execution evidence, and bootstrap acceptance
   receipt.

**Recommended decision:** adopt the proposed contract with external,
content-addressed evidence; require an immutable controller-supplied
controller-entry packet and separate human operator-decision receipts; use the
same fixed manual bootstrap trust policy for every OQ-7 answer and procedural
ruling; run every task in a disposable checkout; protect gates and governance
inputs from implementation tasks; repair the proposed bootstrap's mutual hash
dependency with one-way binding; add a narrow positive `BUILD.md` authorization
for explicitly named `V0-G0`; have G0 create the strict governance/evidence
schemas and validators; then keep `next` unavailable until their program and
schema digests plus the task-manifest/gate digests receive independent human
acceptance. The complete prefilled choices and consequences are in
`docs/OQ-7-PACKET.md`; this recommendation does not select one.

## OQ-8 — SCV0 Space type and post collection

**Status:** decided for the disposable hosted-alpha trial; permanent product
surface remains deferred

**Operator-question packet:**
[SPACE-COMMUNITY-SCV0-D2.md](campaigns/SPACE-COMMUNITY-SCV0-D2.md)

**Selected answer:** use the experimental
`net.sp00ky.juniper-pds.authority.juniper*` namespace and the
exact collection declaration frozen by SCV0-D2

**Operator-decision receipt:** no separate artifact; selected by the explicit
2026-08-24 live-disposable-alpha implementation instruction

**Blocks:** no longer blocks the disposable trial. It still blocks promoting
these experimental identifiers into a permanent or production product
surface.

Choose the permanent Space-type NSID and the author-owned post collection used
inside a permissioned repo. This is distinct from OQ-1: a Space type is also an
OAuth consent/default-collection boundary, and adding a post collection is new
permanent protocol surface. Fixtures may use an explicitly noncanonical
`invalid.test` namespace; they must not make that choice permanent by habit.

The decision must pin the initial exact collection declaration and how a later
declaration expansion remains protocol permission without widening any frozen
governed authorization.

**Disposable-alpha decision (2026-08-24):** D2 freezes one visibly
experimental Space type, permission set, and five record collections under
the already disposable hosted-alpha authority. The initial declaration is
exact. Later alpha declaration expansion cannot widen previously frozen
governed authorization. This is deliberately not a revision of OQ-1's
permanent public-ATProto namespace decision and does not claim that the alpha
types should survive the trial.

**Hosted compatibility observation (2026-08-25):** the BPS-hosted authority
returned OAuth `access_denied` after explicit consent for the spec-valid,
create-only `com.atproto.lexicon.schema` repo grant. No token or session was
retained. The implementation will not broaden this to `transition:generic` to
force publication. A separately hosted disposable Spaces-alpha PDS is now the
eligible fallback, without modifying `juche.social`; rebinding the exact
experimental authority/NSIDs requires a bounded D2 compatibility amendment
before the first write.

## OQ-9 — SCV0 reader-session and disclosure boundary

**Status:** decided for SCV0 V0 public projection; private-reader disclosure
deferred

**Operator-question packet:** not prepared; the decision was issued directly
as the explicit 2026-08-22 SCV0 V0 product task

**Selected answer:** public projection artifacts with community-controlled
publication

**Operator-decision receipt:** no separate artifact; this register does not
fabricate an antecedent packet or receipt retroactively

**Blocks:** no longer blocks synthetic/local public-projection feed and browser
experiments. It continues to block private reader sessions, permissioned
reader serving, membership/access-controlled feeds, and any claim that public
projection solves confidential disclosure.

Choose how an ordinary reader demonstrates current Space read access to the
product without exposing reusable credentials to the AppView, teaching the
observer to manage sessions, treating access as standing, or rebroadcasting
permissioned data through the existing unauthenticated public routes.

The decision must preserve the ability to distinguish current protocol access,
qualified historical evidence, community standing, and authorization. A
single-user loopback fixture/lab surface may precede this decision; shared or
public serving may not.

**SCV0-M4 boundary analysis (2026-08-22):**
`docs/campaigns/SPACE-COMMUNITY-SCV0-M4.md` compares three non-selected
delivery models: a community-operated reader service, reader-direct Space
synchronization, and shared multi-tenant reader infrastructure. None is the
default. A human decision must additionally pin:

1. which component receives and evaluates reader authentication and current
   Space-access evidence;
2. whether community membership exists in SCV0 at all and, if so, the explicit
   governed rule relating it to disclosure;
3. which components may hold reusable credentials or permissioned plaintext;
4. the reader-visible projection and receipt disclosure budget;
5. cache/offline retention and the honest limit of revocation after
   disclosure;
6. cross-community isolation and reader-privacy requirements; and
7. the fail-closed behavior when identity, access, qualification, projection,
   or currentness evidence is missing or conflicting.

The SCV0 V0 decision removes these choices from the public-projection
experiment rather than answering them. No shared private-reader service,
authenticated projection endpoint, private cache, or human trial serving
permissioned Space content is authorized.

**SCV0-D1 product direction (2026-08-22):** the operator selected topology D,
**community-owned projection with a shared rendering layer**, as the product
architecture to carry into a future OQ-9 packet. The community produces an
exact disclosure-scoped projection artifact; a replaceable renderer receives
neither raw author repositories nor reusable Space/moderator capability and
cannot decide admission. The contract is frozen in
`docs/campaigns/SPACE-COMMUNITY-SCV0-D1.md`.

**SCV0 V0 public-projection decision (2026-08-22):** the operator subsequently
selected public projection artifacts with community-controlled publication.
For V0, artifact publication is the community's explicit public disclosure;
the renderer consumes only that artifact and never acquires private source
state. This validates community-owned publication, portable artifacts,
replaceable renderers, and authority separation without reader sessions,
credential custody, or revocation machinery.

The decision arrived as a direct implementation instruction rather than the
antecedent packet/change-set/receipt sequence contemplated above. The record
therefore names the instruction honestly and does not invent an authenticated
receipt artifact. It authorizes only the public-projection V0 branch.
Permissioned reader authentication, membership, Space read access,
invitations, revocation, private serving, authenticated feeds, and
confidential discussion remain deferred future work. Public possession of an
artifact is disclosure, not authentication, standing, or authority.

## OQ-10 — SCV0 authority identities and capability custody

**Status:** decided for the disposable hosted-alpha trial

**Operator-question packet:**
[SPACE-COMMUNITY-SCV0-D2.md](campaigns/SPACE-COMMUNITY-SCV0-D2.md)

**Selected answer:** three distinct disposable identities and disjoint process
custody for author, Space/Lexicon authority, and community actor/moderator

**Operator-decision receipt:** no separate artifact; selected by the explicit
2026-08-24 live-disposable-alpha implementation instruction

**Blocks:** no longer blocks implementation. The first live write remains
operationally blocked until distinct author and community-actor identities are
provisioned and bound to the deployment.

Choose the sacrificial Space authority and community actor identities, whether
the same DID may fill both logical roles in the first trial, the external
credential providers for the author-side and community-side writers, and the
exact collection-scoped capabilities each process receives. Even if one DID
is selected for both roles, access issuance and community governance must
remain separately attributed and separately authorized.

No raw credential, private key, token, or browser session may enter the
repository, observer store, evidence receipts, or product logs.

**Disposable-alpha decision (updated by L11 on 2026-08-25):** the isolated
Space/Lexicon authority is `did:plc:wklgd4ebjiajx4gj3fthp62m`, the author is
`did:plc:amynaqqmdog7ualmiopxhh4x`, and the community actor is
`did:plc:3yjj2vbc42du6epwxyfccw4v`. Their credentials and processes remain
separate. The author browser process may write only post, submission, and
withdrawal records. `communityd` may write only admission and removal records.
The observer has no writer secret, and the renderer receives only the public
artifact.

## OQ-11 — Source withdrawal and author objection

**Status:** decided narrowly for exact V0 self-submissions

**Operator-question packet:**
[SPACE-COMMUNITY-SCV0-D2.md](campaigns/SPACE-COMMUNITY-SCV0-D2.md)

**Selected answer:** exact, prospective author withdrawal suppresses ordinary
active presentation while retaining bounded historical community receipts

**Operator-decision receipt:** no separate artifact; selected by the explicit
2026-08-24 live-disposable-alpha implementation instruction

**Blocks:** no longer blocks the exact V0 withdrawal record and lifecycle
state. Global author vetoes, bulk opt-out, reversal, dispute, and cross-
community policy remain deferred.

SCV0 currently distinguishes a changed source, an unavailable source, and a
community removal. That is not enough to infer why an exact source cannot be
observed. A PDS outage, resolver failure, repository migration, and a verified
record absence have different evidence, while even a verified deletion does
not by itself prove the author's motive. The product must not relabel a generic
observation failure as “the author took this down.”

The present model also gives an author custody and mutation control over the
source post but no separate veto over another community's public inclusion
decision. Adding one would require a human decision about:

1. the exact signed author-side objection/opt-out record and permanent NSID;
2. whether communities must hide, remove, annotate, or may ignore it;
3. whether the signal binds one admission occurrence, one community, one post
   path, or all future versions;
4. how retraction, reversal, dispute, and replay behave;
5. what durable audit trace survives after the source or presentation is no
   longer disclosed; and
6. how an author request differs from community moderation authority.

Until decided, the renderer may say only that the original is unavailable or
that the community removed its projection. It may not claim author intent or
author consent. This question does not block M8A's historical V0 evidence demo,
which states the narrower retained facts and introduces no author control.

**Exact V0 decision (2026-08-24):** self-submission by the source author is
explicit consent for bounded public presentation of that exact URI+CID by the
named community. A later author-authored withdrawal must target that exact
submission/post/community occurrence. Once qualified it stops ordinary active
presentation, but it does not erase the admission, rewrite the community's
historical statement, claw back bytes already received, or imply anything
about a generic source absence. V0 has no reversal. Re-entry requires a new
exact source version, self-submission, and admission.

## Deferred, not blocking

Restore/readmission policy, delegated roles and revocation, key rotation,
fork/import/replay, votes, comments, privacy, abuse policy, feed compatibility,
and production deployment are excluded by `BUILD.md`. The 2026-07-20 V0-D2
amendment ratifies the bounded observer-only DuckDB/Parquet path as V0-M2A.
Continuous archive operation, cold public serving, object-store/distributed
publication, and a networked analytical store remain deferred and require a
separate forcing case and authorization.
