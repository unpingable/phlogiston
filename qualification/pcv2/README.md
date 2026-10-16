# PCV2 synthetic-user qualification (isolated, real PDS)

`run-synthetic-user.sh` lets a synthetic participant and a synthetic moderator
traverse the actual PCV2 first-trial path — real OAuth against a real PDS, the
real `community-live`, `communityd`, `communitywatch`, `communitywatch-web`
and `community-notify` code from this checkout — with nothing shared,
public, or persistent. It writes one secret-free JSON receipt.

## Run

```sh
qualification/pcv2/run-synthetic-user.sh            # receipt in evidence/synthetic-user-<date>.json
qualification/pcv2/run-synthetic-user.sh --receipt /abs/path.json
PCV2_KEEP_LOGS=/abs/dir qualification/pcv2/run-synthetic-user.sh   # also keep process logs
```

Requirements: Docker with the pinned PDS image
`ghcr.io/bluesky-social/pds@sha256:d155af1c906d7848e7dea9d59a8a7def065a04b77aa98ae56ea05a8d4eadb63a`
(@atproto/pds 0.5.34) already present locally, `openssl`, `curl`, Node 24 with
`apps/community-live/node_modules` installed by `pnpm install
--frozen-lockfile` from its committed lockfile (the driver borrows its
`playwright-core` and `tsx`), the Playwright headless Chromium shell that
`apps/community-live/src/browser.suite.ts` also uses, and a Python 3.12 venv
carrying the `communitywatch` dependencies (`PCV2_PYTHON`, default
`/data/git/atproto-nutrition/atproto-community/.venv/bin/python`). The Python
packages themselves are taken from this checkout through `PYTHONPATH`.

A run takes about two minutes. Exit status is 0 only when every happy-path
step and every negative case passed; the receipt says which did not.

## What is real

- Three PDS containers from the pinned image in dev mode on a Docker
  user-defined bridge, published on loopback only: the community actor on one,
  the participant on a second, the moderator on a third. Accounts are created
  through `com.atproto.server.createAccount`; the participant's posts are
  ordinary `app.bsky.feed.post` records made through the PDS API.
- The PDS's own OAuth authorization server and consent UI. `community-live`'s
  loopback OAuth client (`http://localhost?redirect_uri=...`, which
  `@atproto/oauth-provider` accepts by default) sends headless Chromium to the
  PDS sign-in page, where the harness types the password and clicks
  **Authorize** or **Deny access**; the callback, DPoP-bound session, record
  writes and `signOut` are the library's real code paths.
- `community-live` started as `node --import tsx src/server.ts` with an
  ordinary environment file's worth of variables, `communityd` through
  `communityd.serve_cli` with a strict TOML, a Unix socket and the
  `env_file` app-password credential provider, the `communitywatch`
  `ObserverStore` + `VerifyingEventSource` (every event is proven against the
  repository's signed commit fetched from the PDS), `communitywatch-web` on
  loopback, and `community-notify --once` per step with its real HTTPS sender.
- `community-policy run-once` per step: the real unprivileged worker with its
  own SQLite state, reading `/reply-candidates` from the projection and
  requesting `reply_admit` over the `communityd` socket. `communityd` refuses
  equal web and policy peer UIDs, so the worker runs as UID+1 inside a
  container that mounts the host's `/usr` (and so the same Python 3.12) and
  the two package source trees read-only, plus the socket directory and its
  state directory; `SO_PEERCRED` on the socket sees the distinct UID.
- Three browser contexts: participant, moderator, signed-out.
- The `community-live` dependency tree: a run must use
  `apps/community-live/node_modules` installed from the committed
  `pnpm-lock.yaml` with `pnpm install --frozen-lockfile`, so the receipt
  qualifies the locked tree and nothing else. The runner refuses a
  `node_modules` that resolves into a sibling package's tree
  (`apps/juniper-live`).

## What is synthetic

- `identity-stub.js`: the did:plc directory and handle resolver. It stores the
  PLC operations the PDSes submit and serves the resulting DID documents and
  `com.atproto.identity.resolveHandle`; it validates nothing. Both the PDSes
  (`PDS_DID_PLC_URL`), `communityd` (`plc_directory_url` with
  `allow_loopback_public_endpoints`), the observer and `community-live`
  (`COMMUNITY_PLC_DIRECTORY_URL`, `COMMUNITY_HANDLE_RESOLVER_URL`) point at it.
- The AppView: there is no isolated AppView, so the driver answers
  `app.bsky.actor.getProfiles` and `app.bsky.feed.getPosts` by reading the real
  records from the PDSes and returning their real current CIDs. It can be
  switched to *unavailable* (HTTP 503) and *mismatched CID*.
- The room webhook: a loopback HTTPS receiver with a throwaway self-signed
  certificate that `community-notify` trusts only through `SSL_CERT_FILE`. It
  records payloads and can reject one delivery.
- The observer transport: `observer_service.py` polls
  `com.atproto.repo.listRecords` on the three repositories instead of reading
  a firehose, turning each new record into a commit claim. Verification and
  projection are the unmodified packages.

## Steps

Happy path, in order: H0 notify baseline; H1 signed-out home; H2 participant
OAuth sign-in; H2b off-site return path not reflected; H3–H4 existing post
submitted by `at://` URI through the journal; H5 `/mine` waiting; H6 pending
notification; H12 restart without duplicates; H4b submit by `bsky.app` handle
link; H7a–H7c moderator sign-in, queue, admission; H8 admitted notification
surviving one webhook rejection; H9–H9c anonymous permalink, return-to-permalink
sign-in, not-found and malformed permalinks; H15 reply posted from the
permalink (one `app.bsky.feed.post` with `reply.root`/`reply.parent`, one
submit with `discussion`); H16 `community-policy` requests admission and
`communityd` writes one `replyAdmission`, retry idempotent; H17 reply visible
signed-out and signed-in; H18 reply removed with a reason (tombstone: reason,
public-post link, no text); H19 reply restored; H11 unread badge 1→0;
H10 root removed (tombstone); H10b `/mine` hides the removed root's text and
links to the tombstone; H13 interrupted new post resumed from "Unfinished
actions" and listed in the moderation queue; H14 sign-out.

Negatives cover malformed and unknown handles, declined consent, forged and
replayed callbacks, a callback completed from a browser that did not start the
sign-in, signed-out and cross-origin requests to every route, the participant
on moderator routes, others' posts by DID, handle and mismatched URL, malformed
references, a deleted source, a forged CID field, the AppView unavailable
(participant and moderator), a mismatched CID, a replaced source post,
`handle.invalid` from the AppView, admit retry and duplicate admission, a
duplicate submission pending and after removal, a reply attempted on the
removed root (form gone; a hand-replayed form is recorded), and a lost OAuth
session at the next write and at Disconnect.

## Known limitations

- `community-notify` refuses a non-HTTPS `public_base_url`, so the links it
  posts use `https://127.0.0.1:<port>` while `community-live` serves
  `http://127.0.0.1:<port>`; the receipt asserts the path only.
- PDS 0.5.34 in dev mode fixes its public URL to `http://localhost:<port>`, so
  each container listens on its host port number and is published on both
  `127.0.0.1` and `[::1]`.
- Still not covered: Jetstream live ingestion (the observer polls
  `listRecords`), real handle resolution and DNS failures, token refresh over
  hours, and indexing lag or takedowns in the AppView stand-in (it serves the
  PDS's current record immediately, or one of three fixed faults).
- The interrupted-operation case reaches the operation from "Unfinished
  actions" on `/mine`; the plan store on disk is read only as a cross-check.
- The harness is sequential and single-community; it is qualification
  evidence, not a load or soak test.
