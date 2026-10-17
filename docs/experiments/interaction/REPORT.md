# Content interaction release note and test record

Historical implementation record for `251e531`. The reviewed release candidate and
provider evidence supersede its downgrade/retry claims: see
[the release receipt](../../releases/interaction-rc-20261017/RELEASE.md).
Disable now explicitly disconnects; outcome checks never dispatch.

## Question

Can Phlogiston add an off-by-default, provider-consented slice for public likes,
reposts, text posts and replies without weakening reader grants, community
submission isolation, moderation presentation or durable write recovery?

## What was built

- `apps/community-live/src/p0.ts` defines exact interaction variants of each
  reader grant. The added repository scopes cover create/delete only for likes,
  reposts and posts.
- `oauth.ts` advertises the maximum grant and configures the pinned SDK's
  process-local `requestLock`, serializing the SDK refresh work that uses that
  callback within this single-process deployment. Session replacement and the
  callback's revoke/store path have their own behavior outside that lock. Ordinary
  sign-in remains reader-only; Settings performs an explicit step-up or
  downgrade. OAuth state binds a step-up/downgrade to the expected DID, and a
  callback for another subject ends expected-account access and is refused.
- `interaction.ts`, `operations.ts` and `repo-writer.ts` use a separate
  `interactions/<encoded DID>.json` journal. Each operation persists a digest
  of kind, exact subject or reply lineage, and SHA-256 of normalized text.
  Reusing an ID for another intent is a 409. Deletes are prepared and flushed
  once, send the committed CID as `swapRecord`, and map `InvalidSwap` to a
  terminal conflict. Current viewer state and provider-confirmed journal records
  suppress duplicate likes/reposts; a committed undo or confirmed absence permits
  a new operation, while an unreadable uncertain operation remains suppressed.
- Finished journal entries expire individually 30 days after their own finish
  time. Unfinished entries remain reconcilable. Retention and account erasure
  cover both submission and interaction journal directories; erasure is fenced
  against per-DID submission execution and interaction writes.
- `server.ts` separates read-only reconciliation from re-dispatch, rechecking
  scope and pause only before a write. It enforces one action/collection
  mapping, exact account ownership, Origin/CSRF, threadgates, duplicate viewer
  state, current moderation eligibility for new interactions, and global pause.
  Paused, warned/blurred, blocked or blocking cards render no interaction
  controls. Every form receives its own operation ID.
- Settings and public copy disclose the broad provider delete permission and
  Phlogiston's narrower app-created-post deletion rule, best-effort old-token
  revocation, reader scopes added from a submit-only grant, plain-text
  mentions/links, and exact journal text retention. The Settings interaction
  section exists only in reader mode.
- Regression coverage is in `interaction.test.ts`, `repo-writer.test.ts`,
  `reader-server.test.ts`, `retention.test.ts`, `frontdoor.test.ts`,
  `public-pages.test.ts` and the existing browser suite.

## How to try it locally

Run the P0 reader configuration, sign in, then choose **Settings → Content
interaction → Enable content interaction** and complete provider consent.
Following shows a text composer; eligible cards show like/repost controls, and
eligible thread cards show reply controls. Result pages report confirmed,
conflicting or uncertain repository outcomes. Settings can replace the grant
with the corresponding non-interaction reader tier.

## Deterministic evidence

Run from `apps/community-live`, strictly one command at a time:

```text
./node_modules/.bin/tsc --noEmit
node --import tsx --test src/*.test.ts
node --import tsx --test src/browser.suite.ts
```

Final verification: TypeScript passed; the unit/integration suite passed
326/326 tests; the Chromium suite passed 17/17 tests. Coverage includes intent
reuse across kinds and text, distinct per-form IDs, another browser and process
restart recovery, concurrent journal isolation, duplicate likes with different
IDs, like → unlike → like and provider-side removal → like, missing Origin,
exact CID and account checks, cross-account resume, confirmed-absent Retry,
delete-post routing, moderation and threadgate refusal, pause or permission
loss between prepare and dispatch, read-only uncertain reconciliation while
paused and without write scope, per-operation retention, exact delete swap,
real downgrade callback behavior, callback DID mismatch, unexpected DID/PDS,
restore through a fresh handler, undo on a newly blocked subject, retention
concurrency and plan preservation, and erasure during an in-flight interaction.

These are deterministic fixtures and local browser checks, not user evidence
or proof about every deployed authorization server.

## Results and decisions

The adversarial findings were reproducible and are fixed. Submission and
interaction writers no longer load/flush the same document under unrelated
locks. An operation ID cannot silently commit a different form's earlier
intent. Reconciliation can inspect an uncertain operation without write scope
or an open write gate; confirmed absence offers an explicit Retry that reuses
the exact operation and rechecks write and moderation gates before dispatch.
Retention enters the same per-account fences as live writes and preserves
finished contribution operations for every retained contribution plan.

Undo of the viewer's own like/repost remains accepted even if the subject later
becomes blurred, blocked or deleted. This is intentional: undo reduces the
participant's public records and must not trap them behind a subject's later
moderation state. Controls are not rendered on such content, as required, but
a previously loaded exact form may still remove only the signed-in account's
matching record. New like, repost and reply writes remain moderation-gated.

The result page reports only repository-provider confirmation and does not
claim immediate AppView propagation. After a confirmed write, viewer state may
briefly remain stale.

A callback that returns a different account deliberately ends both the expected
account's local access and the mismatched callback session. This fail-closed
choice avoids retaining either side of a confused account replacement.

## Not done

No follow, DM, notification inbox, media upload, facets, post editing, new
AppView, ranking, telemetry, deployment, production credential or PDS change
was added. Delete my data removes local journals but does not imply deletion of
public repository records. No live data or external API was used.

## Recommendation

**Promote after independent source review and explicit release approval.** The
slice is narrow, explicit and now has fail-closed identity, intent, concurrency,
moderation and recovery boundaries. Keep media, editing and wider social-client
parity outside this slice.
