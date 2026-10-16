# P0: a public Phlogiston community, using existing ATProto identities

Accepted for bounded implementation by the owner, 2026-10-11, with the binding Bluesky-only clarification below. Production activation is not authorized.
Canonical work item: https://github.com/unpingable/atproto-community/issues/8.
This proposal changes the launch acceptance contract. It does not claim the old
human trial passed, and does not authorize production activation.

## The outcome

At `https://phlogiston.app`, a signed-out visitor can explore one useful, named,
populated community, open a stable item link, and understand why the community
includes that exact version of the author's post. An existing ATProto account
can opt in, submit an existing public post it owns, and see the request's status.
One consenting operator can run the community and moderate submissions.

There is no recruited-user, second-maintainer, second-moderator, invite, or
third-party notification-room prerequisite. Subsequent voluntary use supplies
usability and demand evidence; lack of that evidence does not block exposure.
Neither automated qualification nor two operator-controlled accounts count as
two-human testing or demonstrated demand.

## Firm scope

- `phlogiston.app` is the product and sole participant origin, served by the
  existing PCV0 `community-live`. Keep `communitywatch` read-only and
  `communityd` the sole authority-bearing writer. No replacement frontend,
  general AppView, feed/ranking stack, membership system or service manager.
- Existing external PDSes supply identity, authentication, and custody of
  author-owned records. **Participation must work without moving an identity
  to a Phlogiston PDS.** The community actor and dedicated publisher also use
  their existing/approved external hosting arrangements.
- `lexicon.phlogiston.app` on existing Bluesky hosting is the already approved
  publisher intent. `community.phlogiston.app` is DNS-only Lexicon authority.
  Retain all eight canonical `app.phlogiston.community.*` schemas unchanged.
- `phlogiston.social` account hosting, registration, blobs, migration and PDS
  recovery are out of this critical path. Do not resume hosting development
  until a concrete user benefit is identified and that work is separately
  admitted. Application state, OAuth custody and moderation recovery still
  have their own bounded operational obligations.
- P0 is a curated collection of root posts. Existing-post submission is the
  primary write. Defer composition, replies and automatic reply admission for
  this public profile; reject their mutation paths rather than merely hiding
  controls. This narrows the first exposure and avoids expanding reply
  moderation. Existing historical qualification remains unchanged.
  Current `root_admit` also publishes a reply policy: the P0 authority profile
  must omit that new policy record and refuse reply-admission actions, while
  preserving historical records and exact admission recovery.
  Qualify a submission-only OAuth scope for this profile: current source also
  requests creation of `app.bsky.feed.post`, which this narrower flow does not
  need. Show the actual granted/requested scopes and public-record consequence
  at opt-in; do not claim sign-in alone admits a post or grants moderator power.
- External notification is disabled by default and absent from startup
  requirements: no placeholder webhook, destination, notification unit or
  notification credential. A later enabled room needs its actual controller's
  consent. In-app queue and submitter status remain functional without it.

## User-visible decisions and evidence

Admission pins both AT URI and exact CID. Preserve existing source mutation,
deletion, terminalization and refusal rules; a changed/reverted record does not
quietly revive an old admission. Missing evidence is unknown, never approval.
Removing an item from the collection never deletes or changes its author's post.

The current `modAction` schema requires an admission and only understands
removal. Therefore P0 must not encode an unadmitted refusal as a fictitious
admission followed by removal or silently change the accepted Lexicons.

Proposed narrow implementation: an authenticated moderator can **decline this
submission for this site**. Preserve a durable, private operator decision in
the existing authority service's local state, with actor DID, exact submission
and subject URI/CID, time, reason and operation identity. Expose the decision to
that submitter and the operator; it is not a published ATProto moderation record
or portable community-wide assertion. The observer does not make this decision.
Admission and local decline must reconcile against the same operation state so
a concurrent admit/decline cannot produce contradictory terminal outcomes.
Readback uncertainty remains pending/unknown until reconciled.

Freeze a shared decision/reservation key over community DID, submitter DID and
exact subject URI/CID, with the exact submission URI/CID retained in each receipt.
Serialize admission and decline across different operation IDs and duplicate
submission records. The existing external-write journal alone does not provide
this property. Provide a bounded authenticated status read for the exact
submitter and moderator, merged with the observer queue by the application.
Recover this private state separately from observer replay; neither a UI filter
nor observer reconstruction is a substitute for the decision record.

Repeat submission of the same exact subject version does not evade a decline
or consume extra queue slots. A changed CID is a new version subject to the
same limits; it does not inherit acceptance. No appeal system or delegated role
is added. Public removal of an admitted item remains the real published action.
Public tombstones may explain that action without redisplaying removed content;
pending/private-declined content and reasons are not anonymously exposed.

## Bounded first exposure

Initial proposed defaults: at most 3 active pending subjects per DID, 10 new
site submission intents per DID per rolling 24 hours, 100 active review items
in total, and 25 items per queue page. These are conservative configuration
choices, not measured capacity claims. Qualification must establish bounds and
fair reachability; requests outside the active intake are visibly deferred or
refused before new app-originated writes, never quietly accepted as queued.

Capacity reservation is atomic and durable across concurrency, retries and
restart. Replaying the same operation consumes no new slot. An uncertain
external write retains its reservation until reconciled. Quotas apply before
writing into a user's repository, not only after the observer catches up.

Separately bound observer acquisition and active-review selection for records
published through other clients. An app quota cannot stop a person writing to
their own PDS. Pagination alone does not bound intake, storage, or processing.
Per-DID fairness, explicit overflow/coverage status, request-size limits and
bounded read work must cover this independent path. Do not infer a refusal
from a missing/deferred record or claim complete coverage when capped.

The operator has two named controls: suspend new site submissions and suspend
new intake/admissions. Safe anonymous reads, signout/disconnect, read-only
uncertain-outcome reconciliation, and authenticated removal remain available.
Pause blocks new mutation attempts at the actual action boundary, including
resume/retry routes; it cannot undo an external effect already committed.
Configuration-level suspension must work without the moderator's OAuth provider
being available. It must not silently stop every read service as a substitute.
Site suspension leaves other clients' PDS writes outside its control. Intake
suspension stops new active-review selection and admissions, not the external
stream or PDS; preserve necessary observation of existing authority/source state.
Existing `attempted_unknown` operations retain their reservation and permit
readback under pause; any fresh mutation dispatch remains suspended. A paused
or deferred request is not a declined request.

## Launch qualification that survives the scope change

1. One operator controls two distinct technical identities on distinct normal,
   compatible PDS origins; the submitting DID is not the moderator DID. Verify
   exact submit → admit → independently observe → anonymous render, plus
   decline and published removal. This is interoperability evidence only.
2. Exercise OAuth/browser-state binding, CSRF, non-moderator refusals,
   submitter-only status, exact-CID/source loss, duplicate requests, concurrent
   decisions, unknown/lost responses, restart and replay using the existing
   harness and negative controls. Test both web and direct-repository submission.
   Add a normal streaming-discovery case with a DID absent from initial fixture
   configuration. The existing PCV2 closed-repository poller does not establish
   this behavior. Record stream visibility, cursor/replay coverage and recovery
   limits; never present a missed delivery as a moderator decision. A completed
   PDS write must have an honest “awaiting observation” state until verified.
3. Test queue saturation and one noisy DID alongside another DID, restart-safe
   reservations, truthful overflow, all pause/resume boundaries, manual-only
   root admission, and absent notifier configuration/startup/outbound delivery.
4. Qualify one exact successor community release, its installed configuration,
   canonical OAuth origin, single-writer/socket/UID boundaries, fault seams
   disabled, and the unchanged eight schema digests. A documentary scope change
   cannot make the old frozen bytes implement these missing controls.
5. Preserve exact actual publisher DID/PDS and manifest acceptance before
   publication, create-only publication and exact readback, Q2 receipt checks,
   credential custody, application host-loss reconstruction and one bounded
   recovery/rollback rehearsal. Distinguish rollback of the app from records
   already published to external PDSes. Do not promise total-site-loss recovery,
   zero loss, 24/7 availability or PDS-hosting durability.
6. Seed and moderate a few real operator-owned public posts through the actual
   path. Record their identities and decisions. No invented users, backdated
   decisions, synthetic demand or automatic claim of usability success.

## First community

Working proposal: **The Cabinet — small discoveries worth keeping.**
An item should offer a concrete curiosity, a link or original observation, and
a short explanation of why it is interesting. Start with three to five genuine
operator-authored posts covering different kinds of discovery. This content
selection is ordinary editorial work, not a recruited-user experiment.

The landing page leads with the collection and a useful first item. A detail
page offers “Original post” and “Why it is here” with exact version and admission
identity. Sign-in appears at the contribution boundary. A separately labeled
real removal example demonstrates that the original still belongs to its author.
Source-unavailable and empty states tell the truth. Do not populate a public
site with these proposed themes as if actual records already existed.

## Explicit supersession instructions

On acceptance, record this as a new `P0` amendment; retain sealed historical
receipts and mark old trial requirements out of scope, not passed.

| Owning surface | Concrete change |
| --- | --- |
| Integration #1 | Make P0 the initial integration outcome; remove second-human and room recruitment from its prerequisite list; keep real identity/manifest/publication, authority and recovery checks. State the October 6 publisher intent and Q2 are already approved. |
| D0 #6 | Supersede the supervised-demo/trusted-peer prerequisite with #8's self-service outcome. Human feedback becomes post-exposure evidence; it does not unlock a wider architecture automatically. |
| Community `BUILD.md` | Add the P0 successor scope and local-only decline semantics above, authorize bounded implementation/qualification, preserve all architectural invariants and historical dogfood classifications. |
| PCV0 config, validator and runbook | Add an explicit public-playground profile, canonical `https://phlogiston.app` origin, disabled notifier and policy-worker paths, bounded intake and pause checks. Retain distinct technical identities; one person may control both. Keep historical `humanDogfood` truthful. |
| Frozen handoff/current standing | Add a superseding P0 handoff naming the newly qualified release and mode. Retain original archive identities/receipts unchanged. Do not repeat an approval request for the already accepted publisher intent. |
| Phase 2 trial/participant packet | Label recruited cohort/activity, second-human validation and room participation as deferred optional trial work; preserve consent if that work actually resumes. |
| Product architecture/public surfaces/explainer | State product-first, existing-PDS participation, PDS-hosting deferral, and self-service readiness accurately. Change deployed copy only with the separately admitted cutover. |

Approval of this proposal accepts the replacement launch scope and permits its
bounded local implementation and qualification. It is **not** approval to create
accounts, enroll production credentials, modify DNS, publish Lexicons, seed live
posts or deploy. The final activation packet must name the actual manifest,
qualified release/configuration and rollback evidence for the existing approval
boundary. This separation follows the owner's supplied #8 instruction, not a
new human-trial gate.

## Binding owner clarification, 2026-10-11

P0 supports ordinary Bluesky-hosted ATProto accounts: bsky.social discovery and Bluesky-operated PDS infrastructure. Juche accounts, infrastructure and migration are excluded; no fallback. phlogiston.social hosting stays deferred. Real qualification must use an isolated test environment and explicitly authorized controlled test accounts/credential custody. OAuth alone is insufficient: prove authorized record write, actual streaming observation, bounded intake, admit/decline, anonymous rendering, exact DID/custody/scopes, duplicates and observer recovery. If the actual Bluesky path fails, report the incompatibility; do not substitute another PDS. Local fixtures never count as the real provider result. No production enrollment, publication, DNS, deployment or public launch is authorized.

## Subsequent owner correction: isolated Juche integration tests

The owner permits existing Juche test accounts through explicitly configured
isolated test mode and existing protected credential enrollment. Public P0 remains
Bluesky-only; an ordinary Bluesky-hosted end-to-end lifecycle is still required
before launch. No fallback, account migration, PDS service change or public
activation follows. Keep test state and receipts separate and label provider
identity; a Juche success cannot be promoted to Bluesky compatibility.
