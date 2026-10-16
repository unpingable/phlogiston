# ATProto Portable Communities — scratch

**Status:** non-normative idea capture, 2026-07-06. V0 is now authorized only by `BUILD.md`;
material here does not expand that scope.
**Build rule:** automation-first (mine the labelwatch codebase via orchestration, not the
hands-on method). Layer law + observer/emitter split are normative in `DOCTRINE.md`.
**One-liner:** "Bsky with subreddits" done at the *right* layer — communities as signed ATProto
actors with their own records, not subreddit-law bolted inside PDS behavior.

---

## The core correction

The naive framing — "make Bsky but with subreddit functionality **at the PDS level**" — is
wrong-layer sludge. It turns the PDS into a little phpBB kingdom with DID paperwork. PDSes are
good at custody and repo ops; they are *not* the place for ranking, search, threaded views, mod
queues, hot/new/top, or cross-user consistency.

The clean version:

> **PDS-adjacent communities:** a PDS can *host* communities, but a community is a signed
> actor/service with its own DID, repo, lexicon-defined records, rules, mods, and index.

ATProto already wants this split:
- user data → signed repositories
- PDSes → host/manage repos + signing keys
- AppViews/indexers → assemble raw records into application views
- Lexicons → define new record/API schemas

A "subreddit mode" needs **custom records + an AppView-like indexer**, not PDS storage magic.

---

## The shape

```text
community DID (its own actor):
  community.profile
  community.rules
  community.roles
  community.member
  community.ban
  community.admission
  community.modDecision / modAction
  community.threadLock
  community.flair
  community.votePolicy

user DID:
  app.bsky.feed.post        # the post stays in the USER's repo
  community.submit          # intent: submit post URI+CID to a community
  community.vote            # community-scoped, later
  community.joinRequest
  community.report
```

**Key move:** the post stays in the user's repo. The community does **not** own the post. The
community mints an **admission record**:

> this post/comment is accepted into this community view, under these rules, at this time, by
> this authority.

Reference by **AT URI + CID**. URI alone = "that record path" (mutable). URI+CID pins the exact
version — otherwise someone submits "nice NAS build," gets admitted, edits into "buy my plague
coins," and the mod ledger is wearing clown shoes.

Labels are tempting for moderation (self-authenticating, source DID + subject URI + value), but
use them for **presentation/mod hints only**, NOT the core membership/admission contract.
Otherwise you reinvent authority laundering with smaller JSON.

---

## What it buys you

1. **Communities fork without stealing user content.** If `linux.neutral.zone` melts down,
   someone builds a rival view over the same underlying posts, minus the old mod decisions.
2. **Moderation becomes receipt-shaped.** Removed-from-community ≠ deleted-from-existence. The
   official view just stops admitting it.
3. **PDSes become neighborhoods.** A PDS hosts `r/pittsburgh`, `r/homelab`, etc. — but users
   from other PDSes still participate if admitted.
4. **Reddit lock-in weakens.** Community graph, posts, mod actions independently indexable.
5. **Composable views.** One AppView renders Reddit threads; another mailing-list mode; another
   StackOverflow mode — same substrate.

## The fatal trap

> If "PDS-level subreddit" means "the PDS **is** the subreddit authority," it's wrong.

PDS/AppView is eventually-consistent, not transactional magic. Authority lives in signed
community records, rendered by AppViews — not in PDS storage.

---

## Architecture

```text
PDS               stores user/community repos
Community service signs admissions, memberships, bans, mod actions (authority-bearing writer)
Indexer/AppView   renders subreddit-like pages
Client            writes user records to user PDS; asks community service for admission;
                  reads community view from AppView
```

Overlay, not fork. Graceful degradation:

```text
Unsupported client / stock Bsky AppView:
  sees a normal app.bsky.feed.post, ignores community.* records
Community-aware AppView:
  sees the same post + submit/admission/mod/vote records → renders /c/homelab
```

Votes are the sharp edge: **community-scoped**, not global likes in a hat.
`vote { subject, community, value, voter, createdAt }`. Ranking is a **view policy**, not
canonical truth: `hot = community policy + vote records + decay + mod state`. Publish the inputs
so another AppView can reconstruct or challenge the view.

---

## The cursed-but-viable MVP

Smallest object Reddit never had: **a portable community admission ledger over user-owned posts.**
`submit → admit → render → remove`.

```text
1. User writes a normal Bsky post.
2. User creates community.submit → post URI+CID.
3. Community actor signs community.admission.
4. AppView renders "the subreddit."
5. Mods sign modAction for removal/lock/flair/ban.
```

**Compatibility ladder:**
- **V0 Feed generator** — return admitted post URIs as a custom feed. Shows up in existing Bsky
  clients. Lossy (a feed is a slit in the wall; a community is a room), but functional proof.
- **V1 Community AppView** — real pages: submissions, admissions, removals, roles, flairs, modlog.
- **V2 Community-aware client** — native post-to-community UX, scoped comments, votes, mod tools.
- **V3 Fork/import/replay** — community ledger becomes portable + replayable. The goblin becomes
  constitutional.

Phase punt list for first cut: no global search, no ranking, no fork UI, no native mobile, no
"replace Reddit," no novel PDS behavior, no protocol politics.

**Real work that remains:** thread model (Bsky replies vs native comments); community-scoped
votes; moderation semantics (view removal ≠ network deletion); fork/import provenance; abuse
(spam/brigading/sybils/mod capture); client affordance. Private/group communities are a *different
beast* — ATProto spec calls non-public data sharing a missing/planned area; don't bolt privacy
onto public repo primitives.

---

## Labelwatch reuse map (uncomfortably high)

This is **labelwatch-shaped**: crawl public records → compile a derived surface → expose receipts
→ don't confuse the compiled view with substrate truth.

```text
labelwatch                    portable communities
---------------------------------------------------------
labeler registry              community registry
label_events                  community_events
labeler_evidence              community_evidence
alerts                        invariant_failures / mod audit findings
discovery_events              community discovery audit trail
boundary_edges                fork/divergence edges
climate API                   community/post/user context API
static report                 read-only community web surface
runner/meta heartbeats        same
systemd deployment            same
SQLite WAL                    same at MVP scale
receipt hashes                same — but see caveat below
```

**Borrow almost directly:** `config.py`, `db.py` shape + migrations + `meta` table + WAL +
heartbeats; `discovery_stream.py` (Jetstream listener, worker queue, cursor persistence,
reconnect/rewind); `runner.py` (isolated loop stages — one subsystem dying ≠ whole death);
`server.py` (rate limits, disk cache, concurrency gate, kill switch); `report.py` (static
HTML+JSON, atomic dir swap, staleness banners); `receipts.py` (config/input hashing).

**Rewrite, same bones:**
- `ingest.py`: labeler queryLabels polling → community record ingestion (profile/submit/admission/
  modAction/role/member/vote).
- `rules.py`: labeler anomaly rules → community ledger invariants (admission subject missing;
  admission CID mismatch; admission before/without ruleset; modAction by non-mod; removal without
  reason/rule; duplicate conflicting admission; vote from non-member if policy requires membership;
  fork import missing provenance).
- `derive.py`: labeler regime/risk → community state (active / stale / capture-risk / forked /
  degraded / read-only).

**The big NEW thing labelwatch does NOT give you: the authority-bearing write path.**
Labelwatch is structurally detect-only — it observes, never emits into the governed ecosystem.
Portable communities *cross that line*: a community service mints authority records
(admission/removal/roleGrant/ban/threadLock) with real keys. Labelwatch's SHA-256 receipts are
*reproducibility* receipts, not authority signatures.

⚠️ **This is the constraint collision to think hard about before ever building this.** The
observatory family's central design constraint is **detect-only is structural, not configuration**
— "the moment the observatory emits, the observer/combatant boundary collapses." A community
service is an emitter by definition. So `communityd` (authority-bearing actor) MUST live behind a
separately installable package, process, configuration, dependency set, and identity from observer
code, and must NOT reuse the labelwatch actor/keys at all. V0 permits those packages to share this
source repository; it does not permit a runtime or authority collapse. Keep the split:

```text
communitywatch    # observer / indexer / AppView   (labelwatch-shaped, detect-only)
communityd        # authority-bearing community actor service (NEW, emits)
```

Reuse estimate: read-only proof ~60–70% of plumbing; functional MVP ~40–50% (writer path is new);
"real communities people use" — plumbing is the easy part, the rest is UX + semantics + abuse +
"why is there a constitutional crisis in /c/homelab at 2:13 AM."

**Do NOT start as a PDS fork.** Start as sidecar observer + SQLite compiler + public surface. The
goblin gets a hat, not root.

---

## Verdict (as captured)

> Not "Bsky with subreddits on the PDS level." Rather: **ATProto communities where PDSes host
> neighborhoods, but authority lives in signed community records** — an optional semantic overlay,
> ordinary posts underneath, signed community context above, rendered by AppViews that choose to
> support it.

Doesn't require consensus to start. Needs one lexicon namespace, one community actor, one indexer,
and enough UI that humans don't admire JSON in the rain. "Dangerously coherent." Bad idea confirmed.

---

## Channel characterization — community-relative source profiles (captured 2026-07-29)

**Status:** non-normative, same as the rest of this file. Names an object; authorizes nothing.
Most of the *seams* below were already spec'd — see "What was already here" — so this is
vocabulary landing in existing slots, not a new surface.

### The move

A source is not globally good or bad. It has a **behavior profile relative to a community's
purposes**. The useful object is a **channel characterization**, not a reputation score — and the
vocabulary is deliberately signal-processing, not moral:

| Dimension | Reads |
|---|---|
| signal domains | where this account reliably notices things early |
| noise floor | how much unsupported or repetitive output surrounds it |
| gain | how strongly it amplifies weak inputs |
| compression | whether minor and major events emerge at the same intensity |
| distortion | recurring frame substitutions (e.g. technical failure → criminal conspiracy) |
| latency | early-but-messy vs late-but-verified |
| recovery behavior | corrects, quietly moves on, or doubles down |
| community fit | useful in security-watch, unbearable in general-discussion |

That becomes **community-relative view policy**:

> We admit this source into the monitoring feed because it has high detection value, but attenuate
> repost propagation because it saturates easily.

More interesting than mute/block/`MISINFORMATION`-on-the-forehead. The source stays user-owned;
the community owns admission context, weighting, and the resulting view. Exactly the
portable-community split.

### Receipt-shaped and decomposable

Not:

```text
trust_score: 63
```

But:

```text
early_detection:      supported
claim_precision:      mixed
severity_compression: high
correction_observed:  low
scope:                ai-industry-discourse
basis:                community-observed sample
expires:              <ts>
```

`scope` + `basis` + `expires` are load-bearing, not garnish. A characterization is an
**observation with a declared basis and a freshness horizon**, not a standing fact about a person.
Without them it silently becomes the dangerous version. (Compare the observatory side: a delta may
only be named as a change in a property if the view can separate that property, and the basis
travels with the claim — driftwatch `docs/architecture/COMPARISON-BASIS-BINDING.md`, labelwatch
Bundle E state-basis freshness.)

### What was already here

This is why it slotted in suspiciously well — the authority seam was already in the shrubbery:

- **Clause 6, "Ranking is view policy, not truth"** — the attenuation seam. A characterization is
  just another declared input to `hot = community policy + vote records + decay + mod state`, and
  the existing rule *"publish the inputs so another AppView can reconstruct or challenge the view"*
  already forces it to be receipt-shaped.
- **Clause 3, "Admission is context, not ownership"** — the community-relative scope boundary.
  Characterizations are admission context; they never touch the user's repo.
- **Labels-as-presentation-hints** (§The shape): *"use them for presentation/mod hints only, NOT
  the core membership/admission contract. Otherwise you reinvent authority laundering with smaller
  JSON."* Labelers publish testimony; the community decides whether that testimony becomes
  attenuation, annotation, feed placement, or nothing. Same seam, now with a second producer.
- **Clause 7 / observer-emitter split** — `communitywatch` may compile characterizations;
  `communityd` may act on them; they do not share keys or moral vocabulary. A characterization
  crossing from observation to ranking effect **is** the authority crossing, and it must be
  minted by the emitter under community policy, never inherited from the observer.

### The failure mode, named

- **Dangerous version:** universal psychometrics for posters. Klout for moral scolds. Global
  scalar, no scope, no expiry, portable across contexts it was never measured in.
- **Good version:** community-owned signal processing with explicit custody over how observations
  become ranking effects.

The distance between them is entirely `scope` / `basis` / `expires` plus clause 7. If a
characterization is ever globally aggregated, un-scoped, or consumed by anyone other than the
community that observed it, it has become the dangerous version regardless of intent.

### Why this matters to the project

Possibly the first answer to "why does `atproto-community` exist beyond Reddit-but-portable" that
isn't ergonomics. Fork/replay (clause 5) is the *mechanical* differentiator; this is a **purpose**
differentiator: communities as places that own their own signal processing, with the custody
receipts to show their work.

Not authorized by `BUILD.md`. Not a V0 concern — V0's one question (does it feel like a real
place) is unchanged. Revisit if/when V1 ranking gets scoped, since that is the first moment view
policy needs inputs at all.

---

## Attention-pressure — per-author exposure decay (captured 2026-09-14)

Preserved from an untracked scratch note so the idea survives cleanup.
**Not authorized by `BUILD.md`**; does not expand V0 scope.

Proposed split: `atproto-community` owns the **reusable mechanism**;
`instantinternet.news` is the **opinionated dogfood experiment** ("this feed
deliberately prevents a few extremely active accounts from monopolizing your
attention").

The mechanism:

- ingest account-activity signals from a labeler *or* derive them from public activity;
- maintain bounded rolling activity/exposure facts;
- expose an **attention-pressure score**, not a moral label;
- provide a feed-generator policy primitive like `author_exposure_decay`;
- thresholds/configuration are user- or feed-defined — never "20 replies/day = pest."

The load-bearing separation:

```text
activity observation ≠ judgment ≠ distribution policy
```

Do not throttle on global posting frequency — that punishes people who are
merely conversational in their own corner. The interesting variable is **how
much of a particular reader's ambient surface one author is consuming**:

```text
w = 1 / (1 + α · E_{u,a})
```

where `E_{u,a}` is recent exposure of user `u` to author `a`, with additional
decay for repeated participation in the same thread/topic cluster. Explicit
follows override: a reader who wants all 80 daily posts from a prolific
author still gets them; the discovery machinery just stops deciding that
everyone else also deserves 80 units.

Principle: **attention is a governed resource; prolific production does not
create an entitlement to proportional distribution.** A news-ish feed
especially should favor source/information diversity over whoever is
vibrating hardest that afternoon.

Status: pinned future experiment — implementable and falsifiable, but parked.
Related but distinct: the `atproto-acl` negative-attention ("quench") design
note suppresses discourse *lineage* at the user's request; this is per-reader
exposure *weighting*. Do not conflate them.

---

## Receipts (source docs to re-read when scoping)

- ATProto overview — https://docs.bsky.app/docs/advanced-guides/atproto
- AT URI scheme — https://atproto.com/specs/at-uri-scheme
- Labels spec — https://atproto.com/specs/label
- Custom schemas / Lexicons — https://docs.bsky.app/docs/advanced-guides/custom-schemas
- Federation architecture — https://docs.bsky.app/docs/advanced-guides/federation-architecture
- API hosts / auth — https://docs.bsky.app/docs/advanced-guides/api-directory
- ATP spec (non-public data = missing/planned) — https://atproto.com/specs/atp
- Repository spec / CIDs — https://atproto.com/specs/repository , https://atproto.com/guides/data-repos
- Feeds guide — https://atproto.com/guides/feeds
- labelwatch repo + ARCHITECTURE.md — https://github.com/unpingable/atproto-labelwatch
