# SCV0-D0 — Space-backed community vertical design

Status: **design frozen; implementation not authorized** on 2026-08-21.

SCV0 is a product slice, not SA11. SA0–SA10d remain the frozen qualification
substrate. The public V0 remains an independently valid public-ATProto path.
This document defines the smallest product experiment that could make the
Spaces work earn its keep without turning access, authentication, or evidence
into community authority.

## Product question

> Can one small group use one Space as a recognizable community where authors
> contribute posts, one configured moderator admits or removes exact versions,
> and ordinary readers can understand why an item is present or absent?

The bounded loop is:

```text
author writes post + self-submission in the author's Space repo
        ↓
observer independently qualifies exact Space state
        ↓
configured moderator authorizes one admission occurrence
        ↓
community actor writes an immutable admission in its Space repo
        ↓
observer independently qualifies that authority record
        ↓
authenticated community view renders the exact admitted post
        ↓
configured moderator may append one removal
```

The success signal is not protocol completeness. A small group should be able
to browse the place, contribute without understanding receipts, and explain in
ordinary language why an item appeared or disappeared.

## Frozen scope

SCV0 contains exactly:

- one Space identity;
- one community actor;
- one configured administrator using the existing local per-occurrence
  authorization model;
- multiple author identities only when a later fixture/live milestone reaches
  that witness;
- author-owned posts and self-submissions;
- immutable community admissions and append-only removals;
- reverse-chronological order by admission time;
- one authenticated read surface and one technical audit disclosure;
- explicit empty, unavailable, changed-at-source, deleted, and removed states.

It excludes replies, native comments, roles, membership records, invites as
community policy, bans, locks, flair, votes, ranking, discovery, notifications,
third-party nomination, remote moderation, fork UI, production deployment,
and more than one community.

Protocol Space access is prerequisite transport access only. SCV0 defines no
community membership record. A person who can read or write under the Space
protocol still has no community standing until a future explicit governed rule
says otherwise; SCV0 needs no such rule.

## Two meanings of admission

The word is overloaded in the existing layers and must be qualified in code,
documentation, and UI:

```text
evidence admission
    = observer accepts a qualified record as evidence input

community admission
    = community actor accepts an exact submitted post into its view
```

An `EvidenceAdmission` can be necessary input to community policy. It can
never substitute for a signed community-admission record or the
per-occurrence authorization to create one.

## Record vocabulary and placement

The semantic vocabulary is frozen; permanent wire identifiers are not.

| Role | Record authority and repo | Minimum meaning |
| --- | --- | --- |
| community profile | community actor's `(actor, Space)` permissioned repo | name, description, creation time |
| post | author's `(author, Space)` permissioned repo | author-owned community content |
| self-submission | same author's permissioned repo | intent to submit one exact post CID to this community |
| community admission | community actor's permissioned repo | acceptance of the exact submission and exact post |
| removal | community actor's permissioned repo | append-only removal of one exact admission/post from the assembled view |

The existing public shapes are semantic inputs, not automatically valid Space
schemas. A public `RecordRef` derives authorship from the AT-URI authority. A
Space record URI instead has the Space authority in the URI authority and the
record author in its path. A later model milestone must therefore use a
Spaces-specific exact reference binding at least:

```text
Space identity + record author DID + collection + rkey + canonical URI + CID
```

It must not force a Space URI through public-repo ownership semantics or use a
public MST proof. The wire representation may remain URI+CID if the eventual
Lexicons allow it, but contextual validation must retain the separate Space
and author bindings.

No permanent `zone.neutral.community.post` or Space-type NSID is selected by
this design. OQ-8 holds that irreversible consent/schema decision. Synthetic
fixtures may use an explicitly noncanonical `invalid.test` namespace only
after an implementation milestone is authorized.

## Identities and capability custody

| Component/role | May hold | Must not infer or hold |
| --- | --- | --- |
| Space authority | protocol access/admission policy and credential signing | community standing or moderation authority merely from credential issuance |
| author-side client | one user's narrowly scoped post/submission write session | community-actor credential, admission/removal capability |
| `communitywatch-spaces-alpha` | read acquisition material transiently and secret-free evidence receipts | writer dependency, standing, policy, effects |
| `communityd` | separate community-actor capability scoped explicitly to profile/admission/removal collections | observer credential/store, user credentials, bare dynamically widened governed scope |
| projector/AppView | qualified evidence and signed community decisions | keys, writes, policy invention |
| reader-session boundary | only the minimum credential/session material needed to prevent permissioned-data disclosure | community standing, moderation, durable evidence authority |

The Space authority DID and community actor DID are distinct logical roles even
if a lab configuration later uses the same synthetic DID. Receipts and
capabilities must still name the role exercised. A live milestone needs a
separate OQ-10 custody decision and sacrificial identities.

`communityd` remains the only community-authority writer. An author-side
writer is a different user-delegated component, analogous in role to the
existing `community-submit` package, and must not be placed in
`communitywatch` or smuggled into `communityd`. Observer and writer
configuration, credentials, dependencies, and processes remain disjoint.
Any future `communityd` Spaces adapter must not import the observer package;
authority-side alpha compatibility stays behind its own adapter or uses only
separately reviewed inert value/schema code.

Every governed write freezes the exact Space and effective collection set at
the occurrence boundary. A later Space-type declaration change may widen an
OAuth grant at the protocol layer, but cannot widen the stored community
authorization.

## Projection and lifecycle

The future projection may consume only independently qualified Space records.
The minimum state rules carry forward from public V0:

- submission requires the post and submission to have the same record author
  and Space identity;
- admission requires exact submission and post URI+CID agreement;
- the admission record must be authored by the configured community actor;
- removal requires the exact admission and identical subject;
- a post CID change or deletion hides the admitted item without creating a
  removal or mutating the author's repo;
- reverting to an old CID does not revive the prior admission;
- failed qualification, conflicting state, missing access, or unavailable
  currentness fails closed rather than rendering a plausible item;
- historical observations and audit evidence remain historical evidence.

Spaces snapshot/transition/recovery meanings remain those of SA1–SA10d. A
snapshot cannot become a transition, and recovery cannot manufacture the
missing provenance of an admission lifecycle.

## Human surface

The ordinary surface is deliberately small:

1. **Community page:** name, description, chronological admitted posts, and an
   honest empty/unavailable state.
2. **Post page:** exact admitted version, author, admission time, current
   lifecycle state, and a stable community permalink.
3. **Contribution action:** create an author-owned post and self-submission;
   no third-party nomination.
4. **Moderator operation:** the existing local CLI semantics for admit/remove;
   no browser administration in SCV0.
5. **Why disclosure:** a short human explanation with optional technical
   details.

Human terms follow the V0 trial findings:

| Human term | Meaning |
| --- | --- |
| Suggested | qualified submission awaiting a community decision |
| Added | exact version currently admitted |
| Removed | community view stopped showing it; source record was not deleted |
| Changed at source | author's current CID differs from the admitted CID |
| Deleted by author | source record is absent |
| Can't check right now | current source or Space evidence is unavailable |
| Not shown | invalid, unauthorized, or conflicting evidence |
| Community unavailable | projection/access/schema state is not safely renderable |

Routine UI never asks a user to understand LtHash, CAR, DPoP, MST, receipt
hashes, or governance packets.

## Receipt presentation

Receipts are plumbing with two bounded surfaces:

- the default “Why is this here?” disclosure says who authored the post, that
  the community added or removed the exact version, and whether the source can
  currently be checked;
- an audit disclosure names exact Space/record URI+CID values and the separate
  identity-resolution, service-binding, authentication/acquisition,
  state/transition, evidence-admission, community-decision, and
  per-occurrence-authorization receipt IDs.

No view stores or emits access tokens, refresh tokens, Space credentials,
delegation tokens, DPoP private keys, cookies, or authorization headers.
Receipt repetition, later acquisition time, or successful access never
strengthens standing, authorization, history, or currentness.

## Permissioned serving boundary

The public V0 AppView is intentionally unauthenticated. It cannot simply serve
permissioned Space records without an explicit disclosure policy and reader
session boundary. Likewise, successful SA9a/SA9d acquisition by an observer
does not authorize rebroadcast to arbitrary readers.

SCV0 therefore requires a separately qualified reader-delivery design before
a shared human trial. It must answer how a current reader demonstrates
protocol access without turning that access into standing, leaking reusable
credentials to the AppView, or teaching the observer to manage browser
sessions. OQ-9 records this blocker. Until decided, implementation may reach
only deterministic fixtures and a single-user loopback lab surface; it may not
publish permissioned content through the existing public routes.

## Replacement boundaries

```text
author/community write adapters  (replaceable alpha boundary)
        ↓
raw Space artifacts
        ↓
SA0–SA10d qualification          (unchanged evidence boundary)
        ↓
Space-aware governance reducer   (future, separate policy boundary)
        ↓
committed projection
        ↓
reader-session delivery          (future disclosure boundary)
```

Public V0 verification and projection do not call into the Spaces verifier.
The Spaces verifier does not depend on `communityd`. Alpha churn remains in
the existing compatibility package and future adapters, not in governance
semantics.

## Predeclared implementation ladder

No item below is authorized by SCV0-D0. Each requires an explicit task and one
bounded commit.

1. **SCV0-M1 — inert model and hostile fixtures.** Define Space-specific exact
   references and conceptual record validators in an inert package; prove
   wrong Space/author/CID, access-as-standing, and evidence-as-admission
   refusals. No transport or writers.
2. **SCV0-M2 — fixture projection.** Feed already-qualified SA1/SA10d records
   through a separate Space-aware governance reducer and render the complete
   `suggested → added → removed/changed/deleted` lifecycle. No credentials or
   writes.
3. **SCV0-M3 — author-side lab writer.** Add a separately packaged,
   user-delegated fixture/local-reference adapter for only post and
   self-submission. It may not import observer storage or communityd.
4. **SCV0-M4 — community-actor lab writer.** Add a Spaces writer adapter only
   inside `communityd`, preserve local UID per-occurrence authorization, use
   exact Space/collection scoping, and re-observe every effect through the
   read path. No remote admin endpoint.
5. **SCV0-M5 — bounded reader surface.** Only after OQ-9, add the selected
   session/disclosure boundary and ordinary-language UI without weakening the
   canonical projection.
6. **SCV0-M6 — sacrificial multi-identity trial.** Only after OQ-8–OQ-10,
   exercise distinct author, community actor, Space authority, and
   administrator roles with synthetic data against local reference
   infrastructure first. Hosted alpha remains optional compatibility evidence,
   never a production dependency.

The program stops if it requires public disclosure of permissioned data,
credential sharing between roles, a weaker qualification claim, remote
moderation, production identities, or governance semantics not independently
authorized.

## What is established

This design establishes the product target, the minimum semantic record roles,
their repository ownership, capability separation, lifecycle, human
vocabulary, receipt presentation, and implementation order.

It does not establish permanent Lexicons, a Space-type consent boundary,
reader access delivery, live actor custody, a usable application, membership,
standing, authorization, deployment, or product demand. Those omissions are
visible gates rather than implementation defaults.
