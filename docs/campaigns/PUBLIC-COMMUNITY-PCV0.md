# PCV0 — public community social loop

> Historical campaign handoff; its namespace/account proposals and resume
> instructions are superseded. Current canonical Lexicons and eight digests:
> [Phlogiston namespace](../PHLOGISTON-NAMESPACE.md). Current deployment
> authority and frozen artifacts: [Phlogiston handoff](https://github.com/unpingable/phlogiston-pds-appview/blob/main/docs/FROZEN-DEPLOYMENT-HANDOFF.md).
> Do not execute the historical instructions below.

Status: **authorized for bounded implementation; live writes publication-gated**
(2026-09-07)

## Paused handoff — 2026-09-09

Active work on this track is paused. The operator reports that
`community.neutral.zone` has been configured and is waiting for DNS TTLs to
clear. Treat the public origin as complete only after DNS, HTTPS, and the Caddy
route are independently verified; this does not by itself satisfy the separate
Lexicon namespace or publication gate.

Resume with these remaining tasks, in order:

1. Provision a recoverable schema-authority account whose DID is distinct from
   the community actor and all participant identities. Publish
   `_lexicon.community.neutral.zone TXT did=<authority-DID>` and verify it after
   propagation.
2. Generate the seven-schema publication manifest, obtain the named human
   acceptance artifact, authenticate through the publisher's bounded
   `auth-listen` flow, publish once, and retain the exact-readback,
   secret-free receipt. Before using the deployment runbook, remove its stale
   `auth-start` reference: the finalized publisher exposes only `manifest`,
   `auth-listen`, and `publish`.
3. Provision two dedicated integration identities on distinct normal PDSes,
   designate exactly one as moderator, and replace every fail-closed campaign
   and service-config placeholder with the same accepted DIDs, handles, and
   PDS origins.
4. Provision host-only runtime material: the community actor credential for
   `communityd`, the browser snapshot secret, private OAuth state, isolated
   service users, state directories, environment files, and socket ownership.
   No credential or credential path belongs in campaign receipts or Git.
5. Run the ready-campaign validator and host preflight, including strict config
   parsing, unit and Caddy validation, credential-boundary checks, and the
   public-listener check. Start each service separately and verify health.
6. Run the fixed cross-PDS journey: post and opt in, reply and opt in,
   remove/restore, participant and authority lost-response reconciliation,
   complete service restart, discussion recovery, and unread recovery. Retain
   and validate the secret-free integration receipt.

The two-account supervised integration may be operated by one person. It does
not satisfy the separate human-dogfood gate. Human dogfood remains
`BLOCKED_MISSING_PARTICIPANTS` until two distinct named maintainers (including
the configured moderator), a topic, and a specific activity are recorded. An
external pilot remains deferred and requires its own authorization.

## Product contract

Two maintainers using normal ATProto identities can start, moderate, continue,
leave, and resume one community discussion without an operator carrying state
between browser actions. Authors retain their public posts and replies. The
community separately records why an exact version enters or leaves its view.

Execution order is fixed: settle semantics and compatibility; implement and
test locally; accept and publish exact schemas; supervise the application;
then run dogfood and one restart-recovery exercise.

## Spaces assumptions replaced

| Frozen alpha assumption | PCV0 replacement |
| --- | --- |
| disposable Juniper accounts and PDS | normal ATProto identities and PDSes |
| `juniperPost` in a permissioned Space | public `app.bsky.feed.post` |
| Space URI and permissioned credentials | community DID and public records |
| authenticated CAR acquisition | public discovery plus exact repo proof |
| alpha author-action discovery journal | public submission/context records |
| artifact directory as primary state | committed `communitywatch` projection |
| Spaces authority adapter | public-PDS `communityd` writer |

The alpha packages, fixtures, receipts, and deployments remain unchanged.

## Reply and moderation semantics

A legacy submission without `discussion` requests root admission. A submission
with an exact root-admission `discussion` reference opts its author's exact
Bluesky reply into that discussion. The reply must point through its signed
`reply.root` and `reply.parent` fields to the admitted root or an eligible
reply. Old local readers reject the new field as schema-incompatible; they may
not reinterpret it as a root.

Each root admission binds one immutable reply policy. A separate unprivileged
policy worker discovers candidates, but `communityd` independently resolves
and validates the subject, context, root, parent, policy, and current lifecycle
before recording automatic reply admission. `communityd` serializes reply
admission and root closure, so the community actor's own repository order is
authoritative.

Reply moderation is keyed by the digest of community DID, exact root admission,
and reply URI. Actions cite an exact reply admission, but removal state applies
to every later CID/admission at that logical key until a chained explicit
restore. A tombstone hides text in every ordinary surface while independently
eligible descendants remain visible. Missing non-root evidence affects only
that node or relationship; it does not blank unrelated verified branches.

Qualified deletion of author-owned community context withdraws active
presentation. It does not erase the community's historical decision or imply
that the public source was deleted. If withdrawal races a community write, the
separately committed facts converge when observed; no instantaneous
cross-repository order is claimed.

## Trusted request path

`community-web` terminates OAuth and retains session tokens server-side. For
each moderator POST it restores the session, checks the DID against the single
configured moderator, checks same-origin/CSRF and exact operation input,
derives a stable identifier from that exact human/command intent, then forwards
a bounded envelope to `communityd`, whose journal durably reserves it before
the authority write. Unix peer credentials establish that this assertion came from
the configured broker process; the assertion identifies the human. The
policy-worker peer has a distinct UID and may request only automatic reply
admission. `communityd` holds the sole community writer credential.

## Ambiguity and restart law

Before dispatch, every participant or authority write persists its operation
identity, repo, collection, predetermined rkey, canonical expected record hash,
and phase. A lost response is `attempted_unknown`, never failure. Exact
readback settles equal, conflicting, or absent state before retry. After
restart, browser-visible recovery resumes the missing phase without duplicating
the source, context, admission, or action.

## Acceptance

The uninterrupted dogfood path is: understand the place; submit a root in the
browser; admit it in the browser; reply from a second account; return in a new
session and find the unread reply; remove a reply and understand its tombstone;
verify that the public source remains. No shell intervention is allowed.

## Why three reply records are permanent

The existing root `admission` cannot represent automatic reply acceptance
without pretending the reply is a root and losing its author opt-in, root,
parent, and policy relationship. `replyAdmission` therefore records the
community's independently observable decision about one exact reply context.
The existing `modAction` terminalizes one exact root subject and cannot
express a sticky logical-reply chain across edited CIDs. `replyAction`
therefore carries the logical moderation key and an explicit remove/restore
chain. `replyPolicy` is immutable and bound to the exact root admission so a
later policy edit cannot retroactively change why replies were accepted.

The optional `submit.discussion` field is intentionally fail-closed. Updated
readers distinguish reply opt-ins from root submissions. Readers using the
old closed schema reject the unknown field; compatibility tests forbid silently
admitting it as a root.

## Publication gate

The accepted schema set is `zone.neutral.community.submit` plus
`replyPolicy`, `replyAdmission`, and `replyAction` under
`_lexicon.community.neutral.zone`. Local implementation and fixtures may run
before publication. Public OAuth metadata must request direct collection
permissions, and live writes remain disabled until the exact reviewed schemas
are published and read back byte-for-byte from that namespace.

## Explicitly deferred

General membership and roles, subscriptions, push/email notifications,
community-memory relationships, clustering, temporal standing, multi-community
discovery, fork/replay UI, replaceable renderers, and an external pilot are not
part of PCV0. An external pilot is gated by a named cohort and recurring
activity. The internal trial establishes interaction and operating cost only;
it cannot establish outside demand.
