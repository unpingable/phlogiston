# Product loop vs V0 plumbing — traced collisions

**Schema:** factual-governed-runway-status-v1

**Authority effect:** none

**Observed at:** 2026-08-17

**Scope:** the V0 implementation at `46903e6` and the ratified V0 decisions in
`BUILD.md` / `docs/OPEN-QUESTIONS.md`, read against the pilot product loop
described in `docs/design/PRODUCT-DIRECTION.md`

**Rulings made:** none

This note records what the current implementation does and does not support.
It selects no answer, promotes no candidate, amends no authorization, and
proposes no schema. Where it says a loop step is blocked, that is a statement
about current code and ratified decisions, not a recommendation to change
either.

## Summary

The pilot loop's **read half** is almost entirely buildable over existing V0
plumbing. Its **write half** collides with three separate ratified V0
boundaries. The common shorthand — "the first version is mostly presentation
over what we already have" — holds for browsing and provenance and does not
hold for suggesting or moderating.

## Collision 1 — third-party suggestion is not expressible

`packages/community-model/src/community_model/records.py:378`:

~~~python
if record.subject.repo_did != context.repo_did:
    raise ValidationError(
        "repo_mismatch", "self-submission must be owned by its envelope repo"
    )
~~~

`context.repo_did` is the repository the submission record lives in;
`record.subject.repo_did` is the post's author. They must be equal. The
`docs/V0-STATE-MACHINE.md` submission predicate states the same rule
("its record repo DID is the DID authority in `subject.uri`"), and `BUILD.md`
ratifies it as a V0 default ("Self-submission only: the submitting repo must
own the submitted post").

Consequence: **only a post's author can submit that post.** A member who
encounters someone else's Bluesky post cannot suggest it. The reducer
classifies any such record `invalid` with reason `repo_mismatch`, and
`communityd` has no path to admit a post with no valid submission —
`admit()` resolves the submission first (`operations.py:162`).

This is a ratified V0 default, not a defect. It is recorded here because the
pilot loop as described assumes third-party nomination.

## Collision 2 — nothing can write to a user's repository

The only authority writer is `communityd`, and it writes exclusively to the
configured community repository: `create_immutable(config.community_did, ...)`
(`operations.py:139`, `pds.py:474`). `communitywatch` and
`communitywatch-web` are structurally incapable of writing — the web process
opens SQLite `mode=ro` with `PRAGMA query_only=ON`, and the package-boundary
suite rejects any module named for a writer, signer, or credential
(`tests/test_package_boundaries.py:85-95`).

Consequence: even a *self*-submission cannot be created by this system on a
user's behalf. The user must produce a `zone.neutral.community.submit` record
in their own repository by some other means. No tooling in this repository
does that, and no V0 component holds a user credential.

A "Suggest" affordance therefore implies a writer role that does not exist:
one acting under a *user's* delegated authority rather than the community's.
That role belongs to neither existing process by charter — `communitywatch` is
detect-only, and `communityd` is the community's authority writer, not a
user-delegated agent.

## Collision 3 — moderation is local-OS-only by ratified decision

OQ-4 answer A (receipt `OQDR-OQ-4-2026-08-14-A-01`) ratifies "local OS/UID
authorization with community-attested actor attribution" and states "no remote
V0 admin endpoint." The implementation matches: `LocalAdminAuthorizer.require`
compares `os.geteuid()` against a configured UID before any credential,
reader, ledger, or writer call (`operations.py:83-89`).

Consequence: a moderator action requires shell access on the host running
`communityd`. A phone-accessible moderation affordance is remote
administration, which OQ-4 deferred to post-V0 protocol work.

## What the read half already supports

Buildable over existing plumbing with no new records and no new authority:

| Affordance | Existing source |
|---|---|
| Community name / "what this place is" | `ProfileRecord.display_name` / `.description` — already a signed record |
| Admitted corpus, reverse chronological | `CommunityQuery.list_visible` (`query.py:330`) |
| Per-item community permalink | admission URI+CID is already a stable identifier; needs a route, not a record |
| "Suggested by" | submission record's repository DID |
| "Added by" | `AdmissionRecord.actor` |
| "Source author" | DID authority of `subject.uri` |
| "Added at" | admission `createdAt` plus community-repo commit order |
| Provenance / "why is this here?" | `query.py:298-305` already returns `subject`, `submission`, `admission` URI+CID; audit returns `verificationOutcomes` (`query.py:437`) |
| Place-level failure states | `projection_incomplete`, `schema_incompatible`, `ingest_stale` reason codes (`query.py:167-180`), surfaced as 503 |
| Public read without login | the web surface is already unauthenticated and read-only |

## Two further findings

**A local "dismiss" would be the first non-derived state.** The projection is
a pure function of retained observations: `storage.py:1092` deletes every
derived table for the generation and recomputes from stored events and
observations. A moderator-local "skip/dismiss" flag is neither a record nor
derivable from records. Adding one introduces the first piece of view state
that cannot be rebuilt — the exact shape the V0 audit searched for and did not
find. A queue defined as "submitted items with no admission" needs no such
flag; not acting is already skipping.

**"Who curates it" is not protocol-visible.** The administrator DID is
configuration (`ObserverConfig.administrator_did`, `DaemonConfig.
administrator_did`). A landing page that names the curator reads it from local
config, not from any record. This is the same out-of-band dependency recorded
as the independent-reconstruction question; it is noted here because a product
affordance surfaces it directly.

## Identity coverage of the existing live evidence

The V0-X7 write smoke — the only live evidence of the complete path — ran
with **exactly one DID** in every role. Parsing
`runs/v0-m7-2026-08-14/EXR-V0-X7-WRITE-SMOKE-run-v0-x7-2026-08-15-02-20260815033140/events.ndjson`
yields a single distinct repository, `did:plc:exampleparticipantabcdef`,
acting as post author, submitter, community actor, and administrator across
all four collections.

Consequence: no live exercise has yet covered a case where submitter, author,
community, and administrator are distinct identities. Multi-identity operation
is specified and unit-tested but has never been observed end to end against a
real PDS and relay. Any pilot is the first such case.

## Not addressed here

This note does not address the OQ-1 namespace publication boundary, which
remains recorded and unresolved in
[s1-oq1-publication-gap.md](s1-oq1-publication-gap.md), nor the
independent-reconstruction question, which
[PRODUCT-DIRECTION.md](../design/PRODUCT-DIRECTION.md) carries as a distinct
candidate. Those are separate boundaries and are deliberately not merged.
