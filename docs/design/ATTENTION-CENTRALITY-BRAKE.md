# Attention centrality brake — anti-main-character filter

**Status:** non-authorizing idea capture, 2026-09-06. This note preserves a
product concept accurately enough to evaluate later. It authorizes nothing,
ratifies nothing, proposes no lexicon, reserves no slice number, and selects no
answer to any open question.

`BUILD.md` remains the sole authorizing document. `DOCTRINE.md` remains
architectural law. `ROADMAP.md` remains the canonical candidate slice ladder.
If any of those conflicts with this file, this file is wrong.

**Not a register.** This note deliberately carries no `PD-`, `S-`, `OQ-`, or
campaign identifier. Per `design/PRODUCT-DIRECTION.md` §7 (PD-D), creating a
parallel candidate register duplicates authority. If this concept is ever
pursued it enters through the existing ladder, not through this file.

**Authorized: no.**

---

## 1. One-sentence pitch

> Install this and Bluesky becomes less dominated by whoever Bluesky is
> collectively yelling about this week.

Alternate framings kept because they carry the intent better than a spec does:

> Do not let the network's collective obsession become my compulsory reading
> list.

> Client-side cultural de-Twitterization.

A reader should understand the value in about ten seconds. If an explanation
of this feature needs a diagram, the explanation is wrong.

## 2. Motivation

Large social networks recreate a familiar failure mode regardless of
substrate: a small number of accounts become temporary gravitational centers
of attention. Users encounter them not because they followed or sought them
out, but because the surrounding network repeatedly quotes, replies to,
references, dunks on, praises, or otherwise revolves around them.

Observed on ATProto/Bluesky as much as anywhere: main-character cycles,
attention concentration, recurring discourse singularities, socially
compulsory awareness of specific accounts, and the network effectively
choosing a user's reading list for them.

## 3. Product behavior

A service computes a rolling measure of attention concentration for accounts
over a recent window — initially something crude like 7–14 days. Accounts
above a threshold are marked. Users may then suppress them, and the mark
decays automatically when the account stops being a discourse singularity.

The distinction that defines the product:

| Popularity ranking | This feature |
|---|---|
| "these people are important" | "these people currently occupy an unusually large fraction of network attention" |
| persistent | rolling and decaying |
| a prestige signal | a saturation signal |

Suppression scope, in preference order, all unresolved:

- top N accounts; or
- percentile threshold; or, preferably later,
- suppress enough accounts to remove some target fraction of aggregate
  concentrated attention.

**Decay is mandatory, not a nicety.** A mark that does not expire is a
reputation system, which this is explicitly not. See §8.

## 4. Measurement

Candidate inputs, none settled:

- unique users engaging with an account (probably the strongest single signal)
- reposts, quote posts, replies, mentions
- cross-community / cross-cluster diffusion
- recency weighting
- follower-independent reach

The first implementation **should favor an understandable, crude metric over
graph-theoretic cleverness**. A simple external ranking — BlueFacts' "most
engaging users of the last week", or similar — may be sufficient to prototype,
if it is practically and legally usable. Elaborate graph science before anyone
has demonstrated they want the feature is the failure mode, not the goal.

The measurement must be explainable in one line to the user, e.g.:

> top 0.1% of network attention over the last 7 days

## 5. ATProto-native shape

A plausible implementation is a dynamic moderation labeler that applies a
label while an account exceeds the rolling threshold and removes it when the
condition no longer holds.

Candidate label names — **naming is explicitly unresolved**:
`attention-saturated`, `overcentralized`, `attention-central`.

The label is **descriptive, not normative**. It means approximately:

> This account currently occupies unusually high network attention.

It does **not** mean: bad actor, toxic, misinformation, spam, untrustworthy,
politically undesirable, or low quality. Users decide what to do with it.

Open at the platform level, and recorded as a **constraint rather than a
design problem to solve now**: whether current Bluesky/ATProto clients support
sufficiently granular per-label/per-subject exceptions (§6). If they do not,
that is a platform fact to document, not an invitation to build a workaround.

## 6. The critical architectural rule

> **Centrality is measurement. Exemption is user preference. Never mix these.**

There must be **no service-level whitelist of "worthy" influential accounts.**

Globally exempting, say, ProPublica or other journalism/public-service
accounts was considered and rejected immediately, because it produces an
editorial governance problem with no defensible stopping point: which
journalists? which outlets? government accounts? weather services? emergency
services? researchers? advocacy groups? who decides? That is precisely the
social-selection machinery the feature exists to avoid.

The desired conceptual preference shape is per-user and per-subject:

```text
(labeler, label, subject) -> ignore
```

Worked example. One user sets:

```text
attention-saturated -> hide
ignore attention-saturated for @propublica.org
```

Another user does not add that exemption. **Both are legitimate**, because the
labeler reports attention concentration; it does not adjudicate whether the
attention is deserved.

Possible fallback semantics if per-subject exceptions are unavailable — open
design choices, **not requirements**:

- followed accounts implicitly exempt (optional)
- an explicit local "never suppress" set
- an optional strict mode where follows are not exempt

## 7. Product philosophy

This is a negative-feedback controller for social attention.

```text
conventional engagement system:
  attention -> more distribution -> more attention -> more distribution

this feature:
  excess attention -> damping -> redistributed exposure -> reduced concentration
```

Informally: automatic gain control for people, or cultural rate limiting.

The goal is **not** to decide what users should see. The goal is to reduce the
degree to which network-wide attention concentration overrides explicit user
intent.

## 8. Non-goals

Not in any first slice, and mostly not ever:

- ideology or viewpoint classification
- semantic content analysis
- toxicity models
- a global whitelist of exempt accounts (§6)
- a reputation, trust, or credibility score
- a generalized governance framework
- a formal-proof or admissibility campaign
- elaborate graph science before demand is demonstrated
- a published prestige leaderboard (see the open question in §11)

## 9. Existing machinery that could support this — and what it is not

The repository already contains directly relevant read-side plumbing. It is
**support, not the product**:

| Existing | Possible role |
|---|---|
| `packages/communitywatch/jetstream.py`, `websocket.py` | read-only firehose/Jetstream consumption with cursor and replay handling; the natural engagement-event intake |
| `packages/communitywatch/storage.py`, `query.py`, `reducer.py` | rolling indexed state over observed events |
| `packages/community-model/identifiers.py`, `values.py`, `canonical.py` | exact subject resolution and deterministic values |
| `packages/communitywatch-web/app.py` (`STALE_AUDIT_BANNER`, `stale_threshold_seconds`, ingest/resolve heartbeats) | honest staleness semantics — a decaying measure that silently serves stale data is a defect |
| `packages/communitywatch-archive/` | archive/rebuild, i.e. reproducibility of a published measurement |
| `DOCTRINE.md` clause 7 and the `communitywatch` / `communityd` split | the observer/emitter firewall the labeler would need (§10) |

Provenance, explainability, reproducibility, exact subject resolution, stale
handling, and authority boundaries are all genuinely useful here. **They are
not the product.** The product is a user hiding accounts the network is
shouting about.

## 10. Conflicts with the current architecture

Recorded so they are visible, not resolved here. Each would need an explicit
`BUILD.md` amendment; none is dissolved by argument in this file.

1. **Subject scope is the sharpest conflict.** Every record type in V0 is
   post-scoped and community-scoped, and `communityd` writes only to the
   community repository. This feature labels **third-party accounts,
   network-wide**. Nothing in the current charter emits anything about an
   account it does not control.
2. **Explicit non-claims.** `README.md` disclaims "voting, ranking, comments,
   social graphs, recommendations, or a general trust-and-safety platform",
   and `BUILD.md` §"Explicitly out of scope" lists "community-scoped voting or
   ranking algorithms" and "generalized trust-and-safety infrastructure". This
   feature is network-graph measurement feeding moderation labels. It is
   arguably outside the *community-scoped* ranking exclusion and arguably
   inside the trust-and-safety one; that argument is not settled here.
3. **`AGENTS.md` invariant 4** allows labels as presentation hints only, never
   as admission, membership, roles, or moderation authority. A descriptive
   centrality label consumed by a user preference plausibly qualifies as a
   presentation hint — but the invariant was written about labels on *this
   community's* items, and should not be stretched by implication.
4. **Observer/emitter firewall.** Computing centrality is observation;
   publishing labels is emission. `DOCTRINE.md` clause 7 and `AGENTS.md`
   invariants 5–6 already give the required shape: separate processes,
   separate credentials, separate dependency graphs, no shared keys or moral
   vocabulary. This is a constraint the repository is unusually well prepared
   to satisfy.
5. **`DOCTRINE.md` clause 6 — "ranking is view policy, not truth" — supports
   this feature** rather than conflicting with it. Centrality output is view
   policy. Saying so out loud is the whole point of §6.

## 11. Open questions — preserve, do not launch campaigns to answer

- Can the required ranking be computed cheaply from public ATProto data?
- Could BlueFacts or another existing ranking source bootstrap an MVP?
- What metric best captures "the network is forcing this account into my
  experience"?
- Top-N versus percentile versus attention-share threshold?
- How quickly should centrality decay?
- Should explicit follows be exempt by default?
- What client/moderation APIs exist for per-label/per-subject exceptions?
- Must suppression affect indirect exposure (quote-posts, replies) rather than
  only direct posts?
- Is a labeler sufficient, or is a custom feed or client component also
  necessary?
- What would make the feature difficult to game?
- How is the measurement kept explainable without publishing a prestige
  leaderboard?

These are preserved because they are good questions, not because they are
scheduled. **Answering them is not authorized work.**

## 12. MVP bias — intentionally crude

If pursued, the first slice is, in order:

1. obtain a rolling attention ranking (borrowed is fine)
2. mark accounts crossing a threshold
3. provide a suppression experience
4. provide user-owned exceptions if the platform permits
5. expose a one-line explanation of why an account is marked

Nothing in §8 enters step 1 through 5.

## 13. Do not turn this into another infrastructure project

**The product must be validated before substantial machinery is built.**

`design/PRODUCT-DIRECTION.md` §1 already recorded the relevant diagnosis on
2026-08-17: "Plumbing evidence is abundant; demand evidence is nonexistent",
and the operating rule "the product must earn further architecture". The
evidence since then is consistent with that finding rather than against it —
the repository holds fifty-plus campaign records under `docs/campaigns/`,
twenty-plus packages, a parked formal-assurance line, and a well-developed
vocabulary of qualification, admissibility, provenance, and evidence
boundaries, while `PD-B1` (the human-readable read surface) and `PD-E` (the
client that would render it) both still read `Authorized: no`. This note is
not a criticism of that work, which is real and tested; it is a reminder that
this concept is attractive **because** it is closer to something a person
would install and use, and that advantage is lost the moment it becomes an
infrastructure campaign.

Concrete guardrails for that failure mode:

- **No formal-methods or admissibility campaign.** Not for the metric, not for
  the label, not for decay.
- **No generalized governance machinery.** §6 exists precisely to keep
  governance out; do not reintroduce it as a framework.
- **Borrow the ranking before computing it.** A borrowed ranking that proves
  nobody wants the feature costs a weekend. A firehose-derived centrality
  pipeline that proves the same thing costs a quarter.
- **The suppression experience is the deliverable**, not the measurement
  pipeline. If a user cannot try it, nothing has been validated.
- **Reuse §9's machinery only where it is already load-bearing** for the
  product — staleness honesty and exact subject resolution qualify early;
  provenance, reproducibility, and archive/rebuild almost certainly do not
  until someone is depending on a published label.
- If the first honest attempt produces an explanation nobody understands in
  ten seconds, park it. That is a legitimate outcome.

## 14. Deliberately not done here

- No `BUILD.md` amendment, no slice authorization, no operator question
  promoted, no answer selected.
- No `ROADMAP.md` edit; no new or changed S-number.
- No new candidate register, ID prefix, or parallel ladder.
- No lexicon, NSID, record type, or schema proposed.
- No code, package, test, or fixture added.
- No label name chosen; no metric chosen; no threshold chosen.
- No claim that this concept is compatible with the current charter — §10
  records the conflicts and leaves them open.
- No edit to `PRODUCT-DIRECTION.md`, `DOCTRINE.md`, `IDEAS.md`, or any
  campaign record.
