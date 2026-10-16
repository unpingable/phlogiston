# Controlled negative and browser recovery cases

`pds-browser-negative.mjs` is a source-only harness for a later durable run against the already installed P0 app and exact `https://phlogiston.social` PDS. It signs in two distinct disposable authors through normal OAuth. It checks that author B cannot read the moderator queue, cannot submit a moderator action, and cannot submit author A's existing post. It then submits a *fresh* author A post twice through the app and checks the browser's duplicate-operation response against a bounded public PDS `listRecords` read: exactly one new submission record with the same URI/CID must exist. It closes Chromium, starts a fresh browser, signs in again, and verifies the author can read their own status. This does not claim recovery of an app process or a lost OAuth store.

Required variables:

| Variable | Value |
| --- | --- |
| `PDS_NEGATIVE_APP_ORIGIN` | Exact installed HTTPS or admitted loopback app origin |
| `PDS_NEGATIVE_AUTHOR_A_HANDLE`, `PDS_NEGATIVE_AUTHOR_A_DID`, `PDS_NEGATIVE_AUTHOR_A_PASSWORD_FILE` | Disposable author A identity and absolute runner-owned 0600 one-line password file |
| `PDS_NEGATIVE_AUTHOR_B_HANDLE`, `PDS_NEGATIVE_AUTHOR_B_DID`, `PDS_NEGATIVE_AUTHOR_B_PASSWORD_FILE` | Distinct disposable author B identity and protected password file |
| `PDS_NEGATIVE_OTHER_AUTHOR_POST_URI` | Existing author A post for author B's refusal case; may be a previously admitted/removed post |
| `PDS_NEGATIVE_DUPLICATE_POST_URI` | Different, fresh author A post with no existing submission |
| `COMMUNITY_BROWSER_EXECUTABLE` | Existing Chromium executable path |
| `PDS_NEGATIVE_SOURCE_REVISION`, `PDS_NEGATIVE_RUN` | Exact source revision and unique run identity |
| `PDS_NEGATIVE_PROGRESS`, `PDS_NEGATIVE_RECEIPT` | Absolute new campaign-owned paths, distinct from each other |

Optional pause case: provide **both** `PDS_NEGATIVE_SITE_PAUSE_PATH` and `PDS_NEGATIVE_PAUSE_POST_URI`. The post must be a third, fresh author A post. The control must already contain `open\n`, be a regular, no-symlink, runner-owned file with no group/other write access, and the installed app must use that exact pathname. The script writes `paused\n` through the opened object, checks that no PDS submission appears, and restores `open\n` in `finally`. The durable progress file records `pause_restore_required` before mutation and `pause_restored` afterward. Abrupt process loss can bypass `finally`; the supervisor must inspect the progress file and reconcile the exact control object before resuming service or starting another run. The root operator must serialize other control writers for the run. The script never changes a PDS admin setting.

Run through the campaign's durable execution mechanism with pre-existing source posts and protected credentials. The script itself is not a launcher or account provisioner. Its receipt contains public record identities, stage times and control restoration status, not passwords, browser screenshots, OAuth tokens, callback URLs or authorization codes. A success establishes these browser and bounded public-PDS observations only; root-owned PDS/observer evidence, app restart, backup/restore and full stream continuity remain separate qualification cases. Retain the progress/receipt and exact replay inputs through independent review, then retire disposable browser state and credential files under campaign closeout.
