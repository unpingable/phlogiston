# PCV1 — reference-client candidate

> Historical campaign handoff; its namespace/account proposals and resume
> instructions are superseded. Current canonical Lexicons and eight digests:
> [Phlogiston namespace](../PHLOGISTON-NAMESPACE.md). Current deployment
> authority and frozen artifacts: [Phlogiston handoff](https://github.com/unpingable/phlogiston-pds-appview/blob/main/docs/FROZEN-DEPLOYMENT-HANDOFF.md).
> Do not execute the historical instructions below.

Status: **implementation complete in the working tree; uncommitted; promotion
gated on the two-account dogfood campaign** (captured 2026-09-11)

## Standing gates

Both PCV0 gates remain open and unchanged (BUILD.md, "PCV1 reference-client
candidate composition amendment"):

1. **Lexicon publication acceptance.** Live writes stay disabled until the
   reviewed schemas are published under `_lexicon.community.neutral.zone` and
   read back byte-for-byte (BUILD.md, "PCV0 public-community social-loop
   amendment"; docs/campaigns/PUBLIC-COMMUNITY-PCV0.md, "Publication gate").
2. **Two-human dogfood gate.** Human dogfood remains
   `BLOCKED_MISSING_PARTICIPANTS` until two distinct named maintainers
   (including the configured moderator), a topic, and a specific activity are
   recorded (docs/campaigns/PUBLIC-COMMUNITY-PCV0.md, "Paused handoff").

Until both are met, PCV1 proceeds against local fixtures and fakes, and the
deliverable is named "reference-client candidate", never "reference client".

## Automated browser qualification (complete)

`apps/community-live/src/browser.suite.ts` drives a real browser
(playwright-core, no browser download) against the in-process app with stub
observer and stub AppView servers: desktop rendering, a 360px viewport,
keyboard-only operation with skip-link and focus-visible checks, AppView
outage with DID fallback and a zero-off-origin-request assertion, long and
missing profiles, tombstones, hostile payloads in the live DOM, sign-out and
Disconnect round trips, and pagination. Run it with:

    pnpm --config.verify-deps-before-run=false test:browser

`pnpm check` runs typecheck, the unit/route suite, and this suite. The browser
executable resolves from `COMMUNITY_BROWSER_EXECUTABLE`, then the cached
Playwright headless shell, then system Chrome; absence is a failure, not a
skip. Screenshots land in the gitignored `apps/community-live/.browser-shots/`
for human review.

## Two-account cross-PDS journey

Provision two maintainers on **distinct normal PDSes**: A (the configured
moderator) and B. Neither may operate the other's account. Exercise, in order:

1. A and B each sign in with their ATProto handle in separate browser
   profiles. Confirm DID presentation and the account nav.
2. B starts a discussion with "Post publicly and submit". Verify the post
   exists in B's own repository and, after observer catch-up, appears on the
   community index with the "Community view" badge and a "Why is this here?"
   explanation.
3. A opens `/moderation` and admits B's root. Verify the admission record by
   exact AT URI and CID, and the index transition.
4. B replies from the discussion page ("Post public reply and opt in"). A
   sees the reply with its own badge and explanation.
5. A removes B's reply with a reason. Both see the tombstone: the reason, the
   statement that the public post is not deleted or changed, and the outbound
   Bluesky link. Read B's reply record back from B's PDS: unchanged.
6. A restores the reply. Verify visibility for both accounts.
7. B returns in a fresh browser session, opens `/mine`, sees the unread
   badge, and marks the displayed version seen; on the next visit the badge
   is gone.
8. B uses Disconnect. The explanation page states that access is revoked,
   public posts remain public on B's PDS, and admission history is unchanged.
   B's sign-in still works afterwards.
9. A removes the root. The tombstone banner appears; B's public root post is
   read back unchanged from B's PDS.

## Evidence to capture

- Secret-free observer readbacks of the admission, replyAdmission, and
  replyAction records, each with exact AT URI and CID.
- PDS `repo.getRecord` readbacks of both accounts' posts before and after
  each removal, proving author repositories were never mutated.
- Screenshots of every surface touched: index, discussion, tombstones,
  `/mine` unread state, `/moderation`, the Disconnect explanation.
- The browser suite output from the deployment host.
- An anomaly log with timestamps; any lost-response or restart recovery is
  recorded, not smoothed over.

## Observer-data gaps found during PCV1-M5 (M4 justification candidates)

1. Moderation-queue entries carry no post text and no timestamp, so a
   moderator must open the public-post link to judge a candidate. A proven
   operational need for text and time in the queue payload is M4 evidence.
2. Reply tombstones cannot link an observer permalink: the observer item
   route serves root admissions only. A proven need for reply-admission
   permalinks is M4 evidence.

Neither gap is resolved client-side; both wait on the separately authorized
M4 observer change, and only if dogfood use proves the need.

## Promotion rule

The candidate becomes the **reference client** only after both standing gates
are met and the journey above is completed by the two named maintainers on
distinct PDSes with the evidence retained. Any skipped step, substituted
account, or shared PDS voids the campaign; the "reference client" claim is
earned, not declared.

## Custody capture (2026-09-11)

This section is a frozen state record, not a task list. It exists so the
campaign can be resumed cold. Nothing in it authorizes new work.

- PCV1 implementation is **complete in the working tree**, sitting atop the
  equally uncommitted PCV0 campaign. All six milestones were executed; M4
  remained intentionally deferred because no projection or schema change was
  justified (acquisition ceilings were never hit; rich text was never
  required).
- Verification at capture: `pnpm check` in `apps/community-live` is green —
  72/72 unit+route tests, 9/9 browser tests; root `scripts/check` reports
  1308 passed, unchanged from the pre-PCV1 baseline. No Python changes were
  required anywhere in the campaign.
- The trust boundary held: the `communitywatch` projection is the essential
  read; Bluesky profile data is decorative; the DID is identity. No
  membership, ranking, threading, client-fork, or juche semantics were
  introduced.
- Presentation work delivered: coded HTTP error pages; same-origin CSS and
  layout; bounded local pagination with truthful over-ceiling refusal;
  centralized HTML escaping with validated Bluesky URL constructors;
  explicit Sign out versus Disconnect (OAuth revocation) semantics; profile
  hydration with batching, timeouts, body caps, TTL plus negative caching,
  and DID fallback; richer discussion index, community context, tombstones,
  observer links, and accessibility landmarks; and the real browser suite
  described above.
- **Repo state: nothing is committed.** PCV1 sits on top of the existing
  uncommitted PCV0 worktree. This is preserved exactly as found; commits
  were deliberately not sliced during capture.
- Known environment wart (cleanup item, not an active task):
  `playwright-core@1.63.0` is pinned in `apps/community-live/package.json`
  but was provisioned additively from a registry-integrity-verified tarball,
  because `pnpm install` insisted on destructively rebuilding the
  cross-linked `node_modules`. No `pnpm-lock.yaml` was regenerated for the
  app. Normalizing the lock state is future work.

## Resume here

1. Inspect the existing PCV0+PCV1 working tree and this handoff.
2. Decide whether to slice milestone commits or first normalize the pnpm
   lock state.
3. Run the gated two-account, cross-PDS human dogfood journey above.
4. Publish lexicons only when that gate is intentionally opened.
5. Promote from reference-client candidate only if the dogfood evidence
   supports it.

None of these actions were taken during the 2026-09-11 capture; that pass
was documentation and custody only, and the worktree was left untouched
afterwards.
