# Product direction — earn the architecture

**Status:** non-authorizing product direction. Captured 2026-08-17, after the
V0 plumbing audit; amended 2026-08-19 to add PD-E (Impro plugin as the
preferred UI surface) and its PD-E0 spike; amended 2026-08-21 to link the
separately authorized documentary SCV0-D0 Space-backed product design. Amended 2026-09-24: the bounded read-half, lifecycle-visibility, and room-notification
portions of PD-B1 and PD-C are authorized as **PCV2** in `BUILD.md`; nothing else
in this file is promoted by that amendment. This
document records emphasis and names candidate tranches. It authorizes nothing,
ratifies nothing, and selects no operator answer.

`BUILD.md` remains the sole authorizing document. `DOCTRINE.md` remains
architectural law. `ROADMAP.md` remains the canonical candidate slice ladder.
If any of those conflicts with this file, this file is wrong.

---

## Authority and promotion boundary

- Nothing here is authorized work. Every tranche below says **Authorized: no**.
- Tranches use the `PD-` prefix deliberately. They are **not** slice IDs. They
  reserve no S-number, occupy no lane, and must never be copied into
  `ROADMAP.md` under their `PD-` name. A `PD-` tranche becomes work only by
  being migrated into `ROADMAP.md` under a permanent S-number (new or
  existing), promoting its blocking questions to numbered OQs, receiving
  authenticated operator rulings, and being named in a `BUILD.md` amendment.
- No tooling reads this file. `validate_roadmap.py` and `v0_gate.py` name
  `ROADMAP.md` explicitly and glob nothing. This document has no selector role.
- `SCV0-D0` is a separately authorized documentary campaign recorded in
  `BUILD.md` and
  `docs/campaigns/SPACE-COMMUNITY-SCV0-D0.md`. It does not promote a `PD-`
  tranche, alter `ROADMAP.md`, or authorize an implementation milestone.
- Several tranches below **overlap existing slices**. Where they do, the
  existing S-number is authoritative and the tranche is a note about
  sequencing, never a parallel register. The reconciliation table is §7.
- This document does not relax a `BUILD.md` non-goal. It cannot; only a
  `BUILD.md` amendment can.

---

## 1. The change in emphasis

V0 answered "does the plumbing hold?" It does — see the audit findings
summarized in §3. The next question is not a plumbing question:

> **Stop optimizing primarily for plumbing completeness. Make the existing
> bounded corpus into a place humans voluntarily use.**

The operating rule:

> **Architecture is now good enough to deserve a product test. The product
> must earn further architecture.**

This is not a claim that V0 is finished. It is a claim about what evidence is
now scarce. Plumbing evidence is abundant; demand evidence is nonexistent.

## 2. Success criterion

Not feature parity, not formal community completeness, not engagement metrics:

> **Can a small existing group — initially a group chat, then perhaps a
> Discord — use one community naturally enough that someone eventually says
> "put that in the community" without being prompted?**

That unprompted phrase is the closest thing to product acceptance currently
available. Behavioral observations that matter, in rough priority order:

- Did anyone other than the operator submit something?
- Did anyone submit more than once?
- Did anyone visit the community without a direct prompt?
- Did anyone paste a **community permalink** back into the room instead of the
  original Bluesky URL?
- Did moderation stay trivial?
- Did anyone misunderstand why an item appeared or disappeared?
- Did users ask for the same missing affordance repeatedly?

Explicitly not measured: sessions, retention curves, growth. This is not an
analytics product.

## 3. What the audit established

Load-bearing findings carried forward as current architectural evidence:

- The `submit → admit → remove` corpus path is real, authority-bearing,
  independently verified, fail-closed, and **effect-gated at projection** —
  an unverified admission cannot render, it is not merely annotated.
- **Membership is not a protocol concept.** All four record types are
  post-scoped. The system is an *accountably curated corpus*, not a
  population system.
- Another AppView could in principle reconstruct the corpus, but today needs
  two out-of-band inputs: the authorized administrator DID and the normative
  precedence semantics.
- The product plumbing is stronger than the governance plumbing.
- Proof-carrying is architectural fact at the ATProto record/admission layer,
  not yet at the governed-execution layer.

## 4. Product principle — borrow the room, own the wall

For the pilot, **borrow social infrastructure instead of rebuilding it.**

| Supplied by the existing room (chat/Discord) | Supplied by Bluesky/ATProto | Owned here |
|---|---|---|
| membership | author identity | *this belongs here* |
| conversation | original posts | *this no longer belongs here* |
| notifications | replies / social graph | a durable community-specific corpus |
| social relationships | public record substrate | local context around global posts |
| identity context | | explicit accountable curation |
| | | a stable place someone intentionally visits |

Working mental model, for humans reasoning about the product:

> **The community is the public wall belonging to an existing room.**

This is a mental model, not protocol terminology. Nothing in `DOCTRINE.md`,
the lexicons, or the state machine adopts "wall" or "room" as a term of art,
and this document does not propose that they should.

The important object is not the original post. It is **this community's
relationship to this post** — which is exactly what an admission record
already is.

## 5. The loop, and where it collides with V0

The intended human loop: open a community and understand what it is → browse a
deliberate chronological corpus → suggest a post → moderator adds it → it
appears → moderator can later remove it → the item has a stable permalink
pastable back into the room.

**The read half is buildable over existing plumbing. The write half is not.**
Three ratified V0 boundaries block it, traced in
[docs/status/product-loop-plumbing-collisions.md](../status/product-loop-plumbing-collisions.md):

1. **Third-party suggestion is not expressible.** `records.py:378` requires the
   submission record's repository to equal the post's author. Only a post's
   author can submit it. This is a ratified `BUILD.md` default, not a defect.
2. **Nothing can write to a user's repository.** `communityd` writes only to
   the community repo; the observer and web are structurally write-incapable.
   A "Suggest" button implies a *user-delegated* writer role that no component
   holds by charter.
3. **Moderation is local-OS-only.** OQ-4 answer A ratified local UID
   authorization and "no remote V0 admin endpoint." Phone moderation is remote
   administration, deferred to post-V0.

These are not reasons to abandon the loop. They are the reason the loop cannot
be scoped as "presentation work," and the reason PD-B is split below.

Two smaller findings from the same trace: a moderator-local **dismiss** flag
would be the first view state not derivable from records (a queue of
"submitted with no admission" needs no flag — not acting is skipping); and
**"who curates it" is config-only**, surfacing PD-A's question directly on the
landing page.

## 6. Human vocabulary

Principle:

> **Proof-carrying should feel like provenance, not cryptography.**

The proposed five terms were validated against the actual state space and are
**insufficient** — V0 has ten projected states plus place-level failure. A
faithful mapping needs roughly eight terms, and must distinguish item-level
from place-level failure, which the original list collapses:

| Human term | V0 state | Notes |
|---|---|---|
| Suggested | `submitted`, `pending` | awaiting moderator; `pending` is "waiting on a referenced record" and reads the same to a human |
| Added | `visible` | currently part of this community |
| Removed | `removed` | no longer part of this community; original still exists elsewhere |
| Changed at source | `stale_cid` | admitted version is no longer the current version |
| Deleted by author | `subject_deleted` | **distinct from "changed at source"** and absent from the original list |
| Can't check right now | `subject_unavailable` | item-level, transient, reversible without new authority |
| Not shown | `invalid`, `unauthorized`, `conflict` | audit finding classes; these never render, and a human may simply see nothing |
| This community can't be shown right now | `projection_incomplete`, `schema_incompatible`, `ingest_stale` | **place-level**, not item-level |

Technical detail belongs behind a "Why is this here?" / "Technical details"
disclosure: exact URI+CID, verification outcome, repository proof versus
transport observation, receipts on demand. A moderator must never need MST,
CAR, CID, `verificationOutcome`, transport observation, repository proof, or
governance packets to do routine work. If a routine decision takes ceremony,
the affordance layer has failed.

## 7. Candidate tranches

Each tranche states **Authorized: no**. None may begin without migration into
`ROADMAP.md` and a `BUILD.md` amendment.

### PD-A — Protocol floor / independent reconstruction

- **Goal:** settle the minimum protocol-visible authority and rule context
  required before S1 freezes permanent surface.
- **The question, preserved verbatim:**

  > What is the minimum protocol-visible artifact set from which a second
  > independent implementation can derive the same admitted corpus, including
  > enough information to know whose authority counts and which bounded
  > composition/precedence rules apply?

- **Why now:** S1 publishes permanent, frozen-forever NSIDs. Anything the
  protocol floor needs is cheapest to decide before that freeze and most
  expensive after.
- **Known inputs:** the administrator DID is config-only; normative precedence
  semantics live in repository prose (`docs/V0-STATE-MACHINE.md`); therefore
  independent reconstruction currently depends on out-of-band knowledge.
- **Excludes:** membership, generalized governance, universal policy
  languages, federation machinery. The target is only enough context to
  reproduce **this community's** bounded corpus semantics.
- **Deliverable:** a decision and trace. **Not code**, unless separately
  authorized.
- **Trace recorded 2026-08-17:**
  [docs/status/pd-a-protocol-floor-trace.md](../status/pd-a-protocol-floor-trace.md)
  — minimum reconstruction inputs, visibility partition, four candidate
  shapes, bootstrap analysis, and a decision *boundary*. It selects no shape
  and carries no authority effect. Its load-bearing finding is that part of
  current validity is observer-relative and therefore not serializable at all,
  so the reconstruction target must be narrowed before any shape is chosen.
- **Kept distinct from:** OQ-1 publication authorization
  ([s1-oq1-publication-gap.md](../status/s1-oq1-publication-gap.md)),
  explicit membership (OQ-R3 / S14), and general governance redesign. These
  are three different boundaries and must not be merged into one packet.
- **Authorized: no**

### PD-B — Smallest lovable loop

Split, because the collisions in §5 fall entirely on one side.

**PD-B1 — the read half.** Community landing page (name, "what belongs here",
curator, corpus); ordinary-language state per §6; per-item community
permalink; provenance / "why is this here?" disclosure; honest empty and error
states distinguishing never-used, removed, hidden, loading, and place-level
unavailable; mobile-first read without login. Buildable over existing V0
plumbing with no new records and no new authority. Directly discharges the
M8 presentation debt recorded in
[v0-m8-human-trial.md](../status/v0-m8-human-trial.md).
**Delivery vehicle: PD-E** — an Impro plugin reading the governed projection,
not a standalone frontend built here. PD-B1 states *what* the read half must
say; PD-E states *where it is rendered*, and PD-E0 has now demonstrated that
surface end to end. Still `Authorized: no`: the vehicle is settled, the work is
not authorized.
**Authorized: no**

**PD-B2 — the write half.** Blocked on three ratified decisions, each of which
would need its own promoted operator question:

- third-party nomination versus self-submission-only for the pilot;
- whether a user-delegated submission writer may exist, and where it sits
  relative to the observer/emitter firewall;
- whether pilot moderation gets a narrow authenticated endpoint or stays on
  the host.

**No answer is proposed here.** A defensible pilot may well run
self-submission-only with host-side moderation and discover that is enough —
that is a cheaper experiment than any of the three changes above.
**Authorized: no**

### PD-C — Pilot bridge

- **Goal:** run the product with one real existing group.
- **Potential scope:** outbound webhook on admission carrying a community
  permalink (the room learns its wall changed); lightweight pilot
  configuration; enough operational visibility to know whether the loop is
  used; friction fixes found in actual use.
- **The webhook is deliberately stupid.** Not a Discord authority system, not
  an identity bridge, not a bot framework. The room remains the room. Cleanest
  placement is a separate small process reading the read-only store — adding
  outbound HTTP to the observer would widen a charter that is currently
  narrow.
- **Two risks recorded:** the participant-class actor is at its authorized
  12-record cap, so any live pilot needs fresh, bounded operator
  authorization; and no live exercise has ever covered distinct submitter /
  author / community / administrator identities (see the collisions note) —
  a pilot is the first multi-identity case.
- **Explicitly not an analytics product.**
- **Authorized: no**

### PD-D — Demand-earned extensions

**This is not a new register, and creating one would duplicate authority.**
`ROADMAP.md` Tiers 2–6 already are the parking area, and several entry gates
already demand exactly this evidence — S7's gate literally names "trial
participants asking 'what is this place for?'" as its forcing case.

PD-D is therefore a **discipline, not a list**: when the pilot produces a
repeated user failure, record it against the existing S-number as forcing-case
evidence rather than opening a parallel candidate.

Deferred unless demand forces them: protocol membership records; joins/leaves;
roles; bans; local comments/replies; votes; reactions; ranking;
recommendation/discovery; arbitrary non-ATProto URL objects; machine-readable
rule languages; tags/categories; generalized federation; generalized policy
engines; elaborate subscriptions; cross-community identity.

The rule:

> **Users should force missing social primitives into existence.**

Worked examples: repeated demand for discussion *inside* the community earns
investigation of S18/S10; repeated demand to save articles nobody posted on
Bluesky earns investigation of arbitrary content objects; a concrete problem
caused by the absence of membership earns investigation of S14/OQ-R3.

**Authorized: no**

### PD-E — Impro plugin as the preferred UI surface

**Added 2026-08-19. Read side validated by experiment the same day** — see
PD-E0's observed outcome below and
[pd-e0-impro-spike.md](../status/pd-e0-impro-spike.md). This tranche records
a preference and now also a result. It still authorizes nothing, and the
boundary section above applies unchanged: a demonstrated capability is not a
ratified slice.

- **Decision:** the preferred near-term delivery vehicle for the human-facing
  surface is an `atproto-community` **plugin inside Impro**
  (`improsocial/impro`) — an actively maintained Bluesky web client with an
  Obsidian-style plugin system, BSD-0 licensed — **not** a standalone frontend
  built here.
- **On the read side this is no longer a preference.** The whole path —
  `Impro → plugin → public AppView → governed projection → rendered community
  state` — has been run end to end in real Chromium against the real Impro
  runtime and the real `communitywatch-web` projection, including honest stale
  and failure semantics and with no record-level read standing in for
  admission. The read-side case for a standalone frontend is not deferred
  pending a trial; it has been **disproven by experiment**.
- **What it replaces:** the previously unstated assumption that anything above
  the minimal read-only AppView had to be built from scratch in this
  repository. PD-B1 was written as presentation work without naming a vehicle;
  this names one.
- **Why it fits this project specifically:** the generic half of a Bluesky
  client — auth/session, navigation, responsive and mobile shell, profile and
  post/thread rendering, preferences — is precisely the half this project has
  no thesis about and no appetite to own. §4 already says *borrow the room, own
  the wall*. This is the same trade one layer down: **borrow the client, own
  the corpus semantics.**
- **Authorized: no**

#### The three layers, stated so they cannot blur

| Layer | Owns | Must never own |
|---|---|---|
| **Impro host** | presentation shell, auth/session, navigation, host-rendered profile lists and post feeds, mobile behaviour, account-synced and device-local plugin storage | any community authority; any notion of admission |
| **`atproto-community` plugin** | community-specific interaction and UI — landing page, ordinary-language state (§6), per-item permalinks, "why is this here?" disclosure, moderator affordances | verification, precedence, projection, or any decision about what is admitted |
| **`atproto-community` (this repo)** | the governed corpus — submission/admission/removal records, exact URI+CID semantics, verification, projection, audit, receipts | nothing moves out; it remains the sole authority-bearing machinery |

The plugin is **a client of the governed projection, never a second AppView.**

#### The invariant this tranche is most likely to break

The plugin SDK's native read facilities — `getRecord(repo, collection, rkey)`
and backlink queries over arbitrary collection/field pairs — read **records**.
Records are not the corpus. Per §3 the `submit → admit → remove` path is
*effect-gated at projection*: an unverified admission does not render at all,
it is not merely annotated. Plugin-native reads would launder that gate in two
concrete ways:

1. A backlink query over the admission collection returns admissions the
   governed projection **refuses** — unauthorized actor, failed verification,
   conflict. Rendering those on a Community page converts transport
   observation into displayed membership. That is the observer/emitter
   firewall failing in the UI instead of the backend.
2. `getRecord` returns the subject's *current* version. Admission is to an
   *exact CID*. The `stale_cid` and `subject_deleted` states exist precisely
   because those diverge. A plugin rendering `getRecord` output as "what this
   community admitted" silently shows a version the community never admitted.

The rule, therefore:

> **The admitted corpus, and every item's state within it, comes from the
> governed projection — the `communitywatch-web` JSON read API — and from
> nowhere else.**

Host- and plugin-native reads are for what Bluesky already owns: rendering a
profile, rendering a post the projection has already admitted, host-rendered
feeds and lists, and the signed-in user's DID. `getRecord` and backlink reads
are admissible for *discovery hints* and for a *submitter's own* records, and
must be labelled as unverified record reads wherever shown — never used to
establish that something is in the community.

#### The write half, and the bridge

The plugin API exposes no generic authenticated
`com.atproto.repo.createRecord` / `putRecord` / `deleteRecord`; host-mediated
writes are currently limited to things like mute/block/feed-feedback. For this
project that limitation is also convenient: it removes the temptation to let a
plugin mint community records directly. Preferred shape:

```text
Impro host -> atproto-community plugin -> narrow atproto-community write bridge -> communityd
```

The bridge is deliberately narrow: a small, explicitly enumerated HTTP surface
in front of the **existing** governed write path. It carries no policy,
performs no verification of its own, and confers no authority the local
administrative CLI does not already confer. `communityd` remains the sole
authority-bearing writer (`AGENTS.md` invariant 6), `communitywatch` and the
web surface remain structurally write-incapable, and reimplementing any part of
admission inside the plugin is out of bounds.

**Two boundaries the bridge may not quietly cross:**

- OQ-4 answer A ratified **local OS/UID authorization and no remote V0 admin
  endpoint**. A loopback HTTP listener in front of `communityd` is *not*
  automatically compliant with that ruling: loopback reachability is not UID
  authentication, and a browser-reachable endpoint is reachable by any page
  the browser has loaded. Whether such a bridge is admissible is a promoted
  operator question, not an implementation detail. It is PD-B2's third blocked
  decision arriving early, and it is answered there or not at all.
- A user-delegated submission writer — the "Suggest" button — is PD-B2's
  second blocked decision and is **not** unblocked by Impro. If anything, the
  absent generic write API makes that boundary cheaper to hold.

Neither the plugin nor the bridge displaces the canonical surface: `BUILD.md`'s
ratified default that *a minimal read-only web AppView is the canonical
rendered surface* is untouched. The AppView remains canonical, remains what the
plugin reads from, and remains the independent-reconstruction target PD-A is
about. An Impro plugin is also not a native mobile client, and this tranche
relaxes no `BUILD.md` non-goal.

#### PD-E0 — Impro integration spike

A small, disposable validation before any broader UI work under PD-B1. Its job
is to decide whether the preference above survives contact — not to produce a
UI. **Authorized: no.**

1. Install or fork the Impro **sample plugin** (the sample, not Impro) and get
   it loading.
2. Add a `Community` sidebar entry.
3. Open a full plugin page from it via `registerPage()` / `openPage()`.
4. Obtain and display the signed-in user's DID.
5. Read and render one representative piece of `atproto-community` state:
   either one custom record via `getRecord`, or one backlink query over a
   community collection/field pair — labelled in the UI as an unverified
   record read, per the rule above.
6. Perform one representative governed mutation through a narrow local HTTP
   bridge in front of the existing governed write path, and display the
   resulting AT URI, CID, and receipt identifier.

**Constraint on step 6.** Until the OQ-4 boundary question above is promoted
and answered, run the mutation against the fixture / fake-PDS substrate already
used by `communityd` tests, on a disposable community. That yields lab-backed
**compatibility** evidence about the plugin↔bridge seam — which is the thing
actually in question — and must never be reported as live testimony about the
governed production path.

**Outcome, defined before running:**

- **Succeeds** — all six steps observed, and step 5 renders governed state
  without the plugin re-deriving any of it: **standalone frontend work is
  deferred indefinitely, pending demonstrated need.** PD-B1 proceeds as plugin
  work, and the result is recorded as forcing-case evidence against S15 rather
  than as a new candidate register (per PD-D's discipline).
- **Fails** — record the **concrete missing capability** — which step, which
  API, what was absent — in a `docs/status/` note *before* any custom-frontend
  option is reconsidered. "It felt awkward" is not a finding; a named missing
  capability is.
- **Partial** — the interesting case, and recorded as such. Reads working while
  the bridge does not is a statement about *our* ratified boundary, not about
  Impro.

**Outcome as observed, 2026-08-19.** The pre-registered text above is left
exactly as written; this is appended, not substituted, because the prediction
is only worth anything if it stays legible next to the result. Full evidence:
[pd-e0-impro-spike.md](../status/pd-e0-impro-spike.md).

**Partial — the third case, and it landed on the interesting side.** Steps 1–5
pass; step 6 was never attempted. The first run was blocked at step 5 because
the AppView sent no CORS headers; that was our gap, not Impro's, and the
public read routes now answer cross-origin.

Read-side conclusions now carried by evidence rather than by preference:

- **Impro is validated as the read-side UI shell.** Plugin installation and
  loading, the `Community` sidebar entry, full-page navigation and rendering,
  the signed-in DID, and a governed read that renders community identity,
  freshness, corpus state, and provenance all work in a real browser.
- **Standalone frontend work remains deferred indefinitely**, and now reopens
  only on a **demonstrated capability gap** — a named thing the plugin surface
  cannot do, recorded as such. "It would be nicer if we owned it" is not that.
- **The governed AppView remains canonical rendered truth.** The plugin renders
  what the projection says and nothing else; the one record-level read on the
  page returned zero results and stayed under its own *unverified record read*
  heading. Making the projection readable cross-origin changed who may read
  it, not what it says or what it refuses.

**The mutation leg is not unfinished frontend plumbing.** Step 6 remains
un-run, and finishing a UI will not run it. There is no governed write surface
at all — `communityd` is a local CLI; OQ-4 answer A ratified local OS/UID
authorization and no remote V0 admin endpoint; PD-B2's three decisions are
unanswered; and the public AppView is deliberately read-only and stays that
way. That makes the remaining seam a promoted **authority and security**
question, already held by OQ-4 and PD-B2, not a gap in this tranche.

**No PD-E1 is opened for it, deliberately.** A follow-on item would be a third
handle on a question that already has two, which is the duplicate-authority
failure PD-D names. PD-E0 therefore stays **formally incomplete** — a five-of-six
result honestly labelled, not a spike quietly redefined as finished at the point
it happened to succeed.

#### External compatibility debt

Recorded because it bears on *distribution*, not on the architecture, and would
otherwise be discovered late by whoever first tries to publish.

The Impro plugin SDK published to the atpkgs registry — which the sample plugin
depends on — resolves to **0.0.3**, while the SDK Impro's host actually serves
to the plugin worker is **0.0.23**. Between those versions the host's fetch
proxy began returning raw bytes, and the published package was not updated: its
`text()` returns the `ArrayBuffer` unchanged and its `json()` parses that
object, so **any published-SDK plugin that reads a fetch body is broken against
a current host.** Building against the local `impro/impro-plugin` source — the
normal arrangement when developing against a cloned Impro — avoids it entirely,
which is how PD-E0's read leg was run.

This must be resolved upstream before shipping a public plugin. It does not
invalidate anything above: the seam works, the skew is in one vendored
artifact's version, and it is an upstream packaging matter rather than a
capability the plugin API lacks.

#### Non-goals

- **Do not fork Impro.** Remain a normal plugin consumer so upstream continues
  to own the generic Bluesky-client surface. A fork becomes admissible only if
  the plugin API is *demonstrated* insufficient by PD-E0's failure record.
- **Do not depend on upstream growing collection-scoped repo writes.** Such a
  capability would be welcome and would simplify the bridge. It is explicitly
  **not** a dependency and must not appear as a precondition anywhere.
- Not a vendor evaluation. Impro's licence and maintenance state are recorded
  as architectural facts that make consumption safe, not as a procurement
  argument.

## 8. Reconciliation with existing slices

These overlap and must eventually be reconciled **rather than duplicated**.
Nothing here edits `ROADMAP.md`; slice entries are review debts and not
agent-editable.

| Existing | Overlap | Reconciliation note |
|---|---|---|
| **S1** — production actor & deployment | PD-C wants deployment, health/staleness surfaces, backup/restore, ops runbook — all S1 deliverables | **Keep separate.** S1 is guarantee-typed and irreversible (production keys, permanent published NSIDs). A pilot on the existing disposable actor is reversible and needs none of that. Letting the pilot pull S1 forward would force an irreversible ceremony on product impatience. This is the "S1 absorbs unrelated product work" risk, stated concretely. |
| **S7** — rules & community self-description | PD-B1's "what belongs here"; PD-B1's curator display | S7 already owns rules-as-records and its exit review is *"Can a newcomer tell what the room is for, without asking anyone?"* PD-B1 should use the **existing** `profile.description` and not invent a second description surface. If prose proves insufficient, that is S7's forcing case. |
| **S2** — feed-generator door | The direction demotes the custom feed as primary object | Not a conflict, a reordering. S2 stays parked; the community URL becomes the candidate primary object. Worth recording that the ladder currently places S2 in Tier 1. |
| **S15** — community-aware client | PD-B's submit friction is exactly S15's named entry evidence; PD-E occupies the same territory | **Conflict to resolve, now sharper.** S15 currently opens "only when S10/S11 exist" (comments/votes) — both explicitly deferred by this direction. S15's stated precondition assumes a path this direction rejects and needs reconciliation at candidate time. PD-E adds a second mismatch: S15 assumes client work is *ours to build last*, whereas PD-E consumes someone else's client early, which inverts the ordering rather than the scope. S15's "Still excludes: everything — resist speccing this" remains correct for a client we would own; PD-E is not that. Reconcile at candidate time. PD-E0's read-side result is now that evidence — a third-party client rendered the governed corpus without this project building or owning a client — and nothing here edits S15. |
| **S9** — multiple communities & discovery | none for the pilot | Pilot is deliberately one community. Stays parked. |
| **S14 / OQ-R3** — membership | PD-A must not absorb it | Membership is a *scope* question; PD-A is a *reconstruction* question. Keeping them separate is deliberate. |
| **M8 presentation debt** | PD-B1 discharges most of it | The five limitations in `v0-m8-human-trial.md` are the evidence base for PD-B1, not a separate workstream. |

## 9. Deliberately not promoted

Recorded so the omissions are visible rather than accidental:

- No `BUILD.md` amendment, no slice authorization, no operator question
  promoted, no answer selected.
- No `ROADMAP.md` edit — no new S-number, no status change, no blocker change.
- No ROADMAP2 material promoted; the research incubator is untouched.
- No resolution of the OQ-1 publication boundary; it stays open and separate.
- No recommendation on PD-B2's three blocked decisions. PD-E names the
  loopback-bridge question as the third of them arriving early; it does not
  answer it, and PD-E0's step 6 is constrained to fixture substrate precisely
  so that it cannot answer it by accident.
- No protocol terminology adopted from the room/wall metaphor.
- No new lexicon, record type, or schema proposed anywhere in this document.
- No change to `BUILD.md`'s ratified default that the minimal read-only web
  AppView is the canonical rendered surface. PD-E adds a client of that
  surface; it does not replace or demote it.
- No dependency taken on any upstream Impro capability, and no fork of Impro
  contemplated. PD-E records consumption, not vendoring.
- No S15 edit. PD-E overlaps it and the overlap is recorded in §8 as a review
  debt, in the same way as every other tranche.
- No authorization created by PD-E0's success. A demonstrated capability is
  evidence, not standing; PD-E, PD-E0, and PD-B1 all remain `Authorized: no`.
- No new tranche for the mutation leg, and no answer to OQ-4 or to PD-B2's
  three decisions. The seam stays where it already sits.
- The one implementation change PD-E0 required — cross-origin reads of the
  already-public AppView routes — was made as routine implementation under the
  `AGENTS.md` explicit-implementation-task provision, on the same footing as
  the PD-B1 read surface. It amended no authorizing document, and it is noted
  here so the register shows it rather than leaving it to the commit log.
