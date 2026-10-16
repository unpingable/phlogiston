# Controlled Phlogiston PDS browser lifecycle

`pds-browser-lifecycle.mjs` drives the installed P0 app through the normal browser OAuth consent flow on the exact configured `https://phlogiston.social` PDS. It submits an existing participant-owned post through the app, waits for the exact candidate in the moderator queue, admits it, checks anonymous rendering, removes it through moderation, and checks the anonymous removal view. A second existing post may be supplied to exercise a private decline. The script does not create posts, accounts, credentials, or repository records through administrative XRPCs.

Run this only through the campaign's approved durable execution and recovery checkpoint, after the app, authority daemon, observer, pause controls, and disposable account custody are installed. It requires:

| Environment variable | Value |
| --- | --- |
| `PDS_BROWSER_APP_ORIGIN` | Exact installed HTTPS origin or admitted loopback app origin |
| `PDS_BROWSER_PARTICIPANT_HANDLE`, `PDS_BROWSER_MODERATOR_HANDLE` | Distinct disposable account handles |
| `PDS_BROWSER_PARTICIPANT_PASSWORD_FILE`, `PDS_BROWSER_MODERATOR_PASSWORD_FILE` | Absolute paths to one-line password files, regular, runner-owned, mode 0600 |
| `PDS_BROWSER_POST_URI` | Existing participant-owned `app.bsky.feed.post` AT URI |
| `PDS_BROWSER_DECLINE_POST_URI` | Optional different existing post URI for private decline |
| `COMMUNITY_BROWSER_EXECUTABLE` | Existing Chromium executable path |
| `PDS_BROWSER_SOURCE_REVISION`, `PDS_BROWSER_RUN` | Exact source revision and unique campaign run identity |
| `PDS_BROWSER_RECEIPT` | Absolute new receipt path; existing file is never overwritten |

The receipt contains stage names/times and public post references. It contains no passwords, token, callback URL, authorization code, or screenshot. A failure names only the stage, so the supervisor must correlate it with separately protected service logs and PDS/observer receipts. The script waits at most three minutes for each candidate, anonymous admission, and anonymous removal. Stage checks establish browser-visible behavior, not stream completeness, write provenance, backup/restore, or installed acceptance by themselves. The supervisor should retain only the minimal receipt/replay inputs through independent review and then retire this run's disposable browser state and credential files under the campaign closeout plan.
