# Public community PCV0 deployment and integration campaign

> The owner-approved P0 implementation successor uses the explicit [P0 profile](p0/README.md). Historical second-human/room gates below do not govern P0; frozen receipts are not rewritten or promoted. Production activation remains separate.

> Use the already-qualified, retained artifacts in the
> [frozen Phlogiston handoff](https://github.com/unpingable/phlogiston-pds-appview/blob/main/docs/FROZEN-DEPLOYMENT-HANDOFF.md); no rebuild is required.
> **DO NOT DEPLOY or enroll credentials until owner approval of the exact Lexicon
> publication account/location, a consenting second participant/moderator, and
> notification-room consent all exist.** `community.phlogiston.app` is DNS-only
> Lexicon authority; the intended participant origin is `phlogiston.app`.

This is a single-host, internal-dogfood topology for
`https://phlogiston.app`. It is not a production deployment or an
external-pilot authorization. No command in this directory provisions an
account, changes DNS, publishes a Lexicon, installs a unit, or starts a
service.

The selected community actor is fixed:

```text
handle: participant.example.com
DID:    did:plc:exampleparticipantabcdef
PDS:    https://phellinus.us-west.host.bsky.network
```

The schema authority is a new, recoverable account and must not be that
community actor or either participant. Two dedicated integration identities
must use different normal PDS origins; exactly one is the configured test
moderator. They may be controlled by one operator for integration, but that
does not satisfy the separate two-human-maintainer dogfood gate.

## Process and custody topology

```text
public HTTPS -> community-live (community-web UID; browser OAuth sessions)
                   | public writes to each participant's own PDS
                   | peer-authenticated Unix socket
                   v
              communityd (communityd UID; sole community credential)
                   ^
                   | policy-only Unix peer
communitywatch -> community-policy
      |
      +-> communitywatch-web (loopback read API)
                   |
                   v
              community-notify (read-only; one outbound HTTPS room webhook)
```

Use five distinct service users and numeric UIDs. The committed template uses:

| process | UID | credential/state boundary |
| --- | ---: | --- |
| `community-live` | 42001 | browser OAuth/session and participant journals only |
| `community-policy` | 42002 | policy operation state; no credentials |
| `communityd` | 42003 | sole community writer capability and authority journal |
| `communitywatch` | 42004 | observer database only; no credentials or socket access |
| `community-notify` | 42005 | notification cursor only; no credentials or socket access |

The numeric UIDs are deployment inputs, not network roles. Replace them
consistently if already allocated. `communityd.toml` must set `allowed_uid` to
the `communityd` process UID and set the two peer UIDs to the web and policy
UIDs. `community-notify` is not a `communityd` peer and is not in the
`community-authority` group. The requesters share traversal/write access to
`/run/community-authority/communityd.sock` through the
`community-authority` group; `SO_PEERCRED`, not group membership, selects the
verbs each may request.

Keep these stores disjoint:

- `/var/lib/communitywatch/communitywatch.sqlite3`: observer projection only.
- `/var/lib/community-policy/operations.sqlite3`: policy worker state only.
- `/var/lib/community-notify/cursor.json`: already-announced event keys only;
  never an authority or delivery record.
- `/var/lib/communityd/communityd-operations.sqlite3`: authority intents and
  ambiguity states.
- `/var/lib/community-web/`: OAuth library state, opaque web sessions,
  contribution plans, participant journals, and private last-seen markers.
- `/var/lib/community-web/integration-faults/`: browser-writer one-shot
  campaign triggers, writable only by `community-web`.
- `/var/lib/communityd/integration-faults/`: authority-writer one-shot
  campaign triggers, writable only by `communityd` except while the operator
  deliberately arms an exercise.
- `/var/lib/community-lexicon-publisher/`: one-time publisher OAuth state and
  the publication receipt; never mounted into an application service.
- `/etc/atproto-community/communityd.env`: the sole community writer
  credential reference target, readable only by `communityd`.
- `/etc/atproto-community/community-web.env`: browser configuration and the
  snapshot-signing secret, readable only by `community-web`; it must not carry
  the community writer credential.

`community-live` hydrates author handles and display names from the
operator-pinned AppView origin (`COMMUNITY_APPVIEW_ORIGIN`, default
`https://public.api.bsky.app`); hydration is presentation-only and degrades to
DID display on any failure. Avatar images are omitted by default. Setting
`COMMUNITY_AVATARS=enabled` renders avatars from `https://cdn.bsky.app` only,
which makes every viewer's browser — signed-in or anonymous — request those
images directly from that CDN, disclosing the viewer's IP address and
page-view timing to it. Leave the flag unset unless that disclosure has been
explicitly accepted for the deployment's viewers.

Removed discussions link their public Bluesky post from the tombstone banner.
Setting `COMMUNITY_OBSERVER_PUBLIC_URL` to the observer's public `/c/{slug}`
base additionally links the observer's admission record from that banner. The
reference topology keeps the observer on loopback, so the variable stays unset
and the permalink is omitted; set it only for a deployment that deliberately
publishes the observer API.

The Phase 2 host also runs `phlogiston-web` from the phlogiston kit as a
fourth loopback reader of `communitywatch-web`: it listens on `127.0.0.1:8092`
behind Caddy on its own hostname, reads only
`/api/v0/communities/<did>/members` and `/api/v0/communities/<did>/discussions`
from the observer at `http://127.0.0.1:8080`, holds no community credential,
is not a `communityd` peer, is not in the `community-authority` group, and
has no access to the authority socket; the phlogiston kit's own
`communityd`/`communitywatch` units are withdrawn and must never run beside
this topology (step 9 below refuses them).

SQLite, publisher evidence, campaign receipts, and observer data confer no
community authority. `communityd` must not read them except for its own
authority operation journal.

## Freeze the public campaign inputs

Copy `campaign.example.json` to a protected host-side campaign directory and
replace every `REPLACE...` or `.invalid` value. Record public DIDs, handles,
PDS origins, and account controllers only—never passwords, tokens, cookies,
authorization codes, DPoP keys, app passwords, or credential paths.

The validator is deliberately offline and reads no credential file (the
`host-preflight` command in step 9 below is the one exception: it reads
installed unit files and the passwd database on the host):

```sh
/opt/atproto-community/.venv/bin/python \
  /opt/atproto-community/deploy/public-community-pcv0/validate_deployment.py \
  validate-bundle --repository-root /opt/atproto-community

/opt/atproto-community/.venv/bin/python \
  /opt/atproto-community/deploy/public-community-pcv0/validate_deployment.py \
  validate-campaign /var/lib/pcv0-campaign/campaign.json --ready
```

`validate-bundle` strictly parses the committed observer, policy, authority,
browser, campaign, receipt, and Caddy examples and checks their identities,
UIDs (all five `servicePrincipals`, including `communityNotifyUid`), sockets,
origins, the `community-live` start path, and process boundaries. It accepts exactly two
integration-fault shapes. Campaign mode sets
`COMMUNITY_INTEGRATION_FAULTS=enabled`,
`COMMUNITY_INTEGRATION_FAULT_DIR=/var/lib/community-web/integration-faults`,
and `integration_fault_directory = "/var/lib/communityd/integration-faults"`.
Normal mode omits all three; `community-live` has no explicit disabled value.
Any partial or mismatched combination is refused, and every other check
applies in both modes. `validate-campaign --ready`
refuses unresolved identities, same-PDS participants, identity reuse, a wrong
TXT binding, extra JSON fields, or fabricated human-dogfood participation. It
does not claim that an identity, hostname, PDS, or published record exists.

## Permanent Lexicon publication gate

Use the separately installed `packages/community-lexicon-publisher` package.
It must be absent from the browser, policy, observer, and `communityd`
dependency closures. Its only OAuth scope is:

```text
atproto repo:com.atproto.lexicon.schema?action=create
```

The publisher interface and protected locations are:

```text
PCV0_LEXICON_RUNTIME_DIR=/var/lib/community-lexicon-publisher
PCV0_LEXICON_CALLBACK_ORIGIN=http://127.0.0.1:<operator-selected-port>
PCV0_LEXICON_AUTHORITY_DID=<dedicated-schema-authority-DID>
PCV0_LEXICON_MANIFEST=/etc/atproto-community/lexicon-publication-manifest.json
PCV0_LEXICON_ACCEPTANCE=/etc/atproto-community/lexicon-publication-acceptance.json
PCV0_LEXICON_RECEIPT=/var/lib/community-lexicon-publisher/publication-receipt.json
```

From that package, run `pnpm start -- manifest <output-path>`, review its exact
eight document digests, and create the publisher's matching human-acceptance
artifact. Configure `_lexicon.community.phlogiston.app` as a TXT record with the
exact value `did=<dedicated-schema-authority-DID>`. Only after independent
review may the operator run the package's `auth-listen`, `auth-start`, and
`publish` flow. The loopback callback consumes OAuth parameters directly;
they must not be copied through chat or shell history.

The publication gate passes only when the publisher receipt establishes all
of the following:

- the accepted manifest contains exactly the eight packaged
  `app.phlogiston.community.*` documents;
- every deterministic `rkey` equals its NSID;
- the dedicated authority DID owns every exact repository record;
- create success or exact readback returned the accepted bytes and CID;
- `_lexicon.community.phlogiston.app` resolved to the same authority DID.

Conflict, partial publication, digest drift, DNS mismatch, substituted URI,
CID, DID, or bytes is a hard stop. There is no update, overwrite, blind retry,
or unattended publication path. Keep the publisher receipt; destroy or
archive its OAuth state according to the separately reviewed custody policy.

## Host preflight and startup

Install the current milestone from the verified community release artifact,
not an editable workspace. Phlogiston's canonical
[`deploy/build-communitywatch-release.sh`](https://github.com/unpingable/phlogiston-pds-appview/blob/80a868973903d7e5ec478b6e112dbb6147a04923/deploy/build-communitywatch-release.sh)
builds eight hot-runtime wheels, immutable `community-live` source/static/package/
lockfile and the exact closed offline pnpm store. Its bundled verifier binds the
exact community and builder Git revisions; verify the externally retained archive
SHA256 before extraction and invoke that verifier with both expected revisions.
Historical six-wheel v1 archives do not satisfy this milestone.

Retain the verified extracted generation unchanged. Stage its payload at the
existing PCV0 paths, using the admitted Python3.12, Node24+ and pnpm11.11.0
executables; no unit layout or service authority changes:

```sh
# Only after archive/source verification and admitted host preflight.
# /absolute/verified-generation is the extracted communitywatch archive root.
test ! -e /opt/atproto-community/.venv
python3.12 -m venv /opt/atproto-community/.venv
/opt/atproto-community/.venv/bin/python -m pip install --no-index --no-deps \
  /absolute/verified-generation/wheels/*.whl
/opt/atproto-community/.venv/bin/python -m pip check
# Both targets must be absent in a new admitted staging generation.
test ! -e /opt/atproto-community/apps/community-live
test ! -e /absolute/staged-pnpm-store
mkdir -p /opt/atproto-community/apps
cp -a /absolute/verified-generation/community-live \
  /opt/atproto-community/apps/community-live
cp -a /absolute/verified-generation/pnpm-store /absolute/staged-pnpm-store
cd /opt/atproto-community/apps/community-live
pnpm install --offline --frozen-lockfile --trust-lockfile --ignore-scripts \
  --store-dir /absolute/staged-pnpm-store
pnpm typecheck
test -x node_modules/.bin/tsx
```

The store and application runtime copies acquire installation metadata and
local dependency links; they are distinct from the retained sealed generation.
`--trust-lockfile` is limited to the already reviewed digest-bound lockfile and
avoids pnpm11 fresh-cache registry policy revalidation while keeping all
package bytes verified and resolution frozen. Do not use sibling
`node_modules`. Confirm the service's actual Node executable is the admitted
Node24+ runtime, including under `ProtectHome=true`; an interactive-shell PATH
alone does not establish that binding. Mechanically rebind the existing action's
source/runtime inputs to these exact artifact hashes and executable paths before
admission; sealed historical Action3 records remain unchanged.

The following unit already runs from the installed artifact directory; no Git
checkout is required at runtime. Packaging does not provide Q2 authority,
Lexicon acceptance, participant consent or credential enrollment. Continue with
the actual approved configuration and readiness checks below. The
`community-live.service` unit starts the installed binary directly
(`node_modules/.bin/tsx src/server.ts`) because `ProtectSystem=strict` and
`ProtectHome=true` leave `corepack` no writable cache and no network fetch
path. `tsx` is a devDependency, so the host install must not add `--prod`;
verify `node_modules/.bin/tsx` exists under `apps/community-live` before
installing the unit. Copy the
TOML and unit examples, substitute the accepted moderator DID and allocated
UIDs, and create the two real environment files with `umask 077`. Never put
the schema-publisher credential in either application environment.

Before enabling any live unit, all of these checks must pass:

1. The protected campaign JSON passes `validate-campaign --ready`.
2. Both integration DIDs and their distinct PDS origins have been recorded;
   one and only one DID matches every moderator setting.
3. The publisher's accepted manifest, acceptance, and successful publication
   receipt exist at the three campaign paths and match the schema-authority
   DID and TXT value. Re-run the publisher's readback verification if its CLI
   provides a separate verification command.
4. `communitywatch.toml`, `community-policy.toml`, `community-notify.toml`,
   and `communityd.toml` pass their installed strict parsers. The observer binds only to loopback.
5. `communityd.env` is mode `0600`, owned by `communityd`, and is not readable
   by web, policy, or observer users. `community-web.env` is mode `0600` and
   owned by `community-web`. `community-notify.toml` is mode `0600` and owned
   by `community-notify`: its webhook URL is a bearer capability for the room.
   Check metadata only; do not print any of these files.
6. All state directories are owned by exactly their service users. Only web
   and policy can traverse the authority socket directory through its group.
7. `systemd-analyze verify` accepts all six units, `caddy validate` accepts
   the exact fragment, and only Caddy has a public listener.
8. OAuth metadata requests direct create permission only for
   `app.bsky.feed.post` and `app.phlogiston.community.submit`. The community
   credential has not entered the browser runtime.
9. The double-writer guard passes:

   ```sh
   /opt/atproto-community/.venv/bin/python \
     /opt/atproto-community/deploy/public-community-pcv0/validate_deployment.py \
     host-preflight --campaign /var/lib/pcv0-campaign/campaign.json
   ```

   It reads the installed unit files and the passwd database only (no
   `systemctl`) and refuses unless exactly one installed, unmasked unit has
   an `ExecStart` containing `communityd-serve` and that unit is
   `communityd.service`; unless the phlogiston kit's withdrawn
   `phlogiston-communityd.service` is absent or masked
   (`systemctl mask phlogiston-communityd.service`); and unless every
   installed PCV0 unit's `User=` resolves to its `servicePrincipals` UID.
   An unreadable unit directory is a refusal, not a pass. Re-run it before
   any later `communityd` start that follows a unit change.

Start one service at a time and check its journal/health before continuing:

```sh
systemctl start communityd.service
systemctl start communitywatch-index.service
systemctl start communitywatch-web.service
systemctl start community-policy.service
systemctl start community-live.service
systemctl start community-notify.service
systemctl reload caddy
```

Do not enable the units or reload Caddy if publication evidence or any local
preflight check is incomplete. Caddy exposes only
`phlogiston.app`; the observer API and authority socket remain local.

### Room notification (PCV2-B)

`community-notify` is an optional, unprivileged poller of the loopback
observer API. It keeps one cursor file and POSTs a fixed message (event kind,
community name, one line, and a link) to the single `webhook_url` when a root
submission becomes pending and when a root is admitted. A pending message
links the community home page and adds a `Public post:` line with the
submitted post's Bluesky link; an admitted message links `/d/<rkey>`. It
never includes post text. Set `webhook_payload_key` to `content`
for Discord-style or `text` for Slack-style incoming webhooks. On first start
it records existing events without announcing them. Delivery is best-effort:
each new event is attempted every poll, and a failure is logged without the
URL and retried on the next poll without holding back other events. Replace the
`.invalid` placeholder URL only on the host; never commit a real webhook URL.
PCV2 authorizes this unit as an example only; starting it follows the same
deployment gates as every other unit.

## Supervised cross-PDS integration journey

Create the secret-free receipt before opening browsers:

```sh
/opt/atproto-community/.venv/bin/python \
  /opt/atproto-community/deploy/public-community-pcv0/validate_deployment.py \
  new-receipt /var/lib/pcv0-campaign/campaign.json \
  /var/lib/pcv0-campaign/integration-receipt.json
```

Use two isolated browser profiles. Establish both OAuth sessions
interactively. The driver is the fixed ordered `checks` list in the receipt;
do not put browser storage, cookies, OAuth responses, or screenshots carrying
private data in `evidence`.

1. Sign in both identities and confirm each restored DID and PDS origin.
2. The moderator posts a root plus exact opt-in, then admits it through the
   browser; record the post, submission, admission, and immutable reply-policy
   AT URI and CID pairs.
3. The participant replies and opts that exact reply into the discussion;
   verify automatic admission through the unprivileged policy path.
4. In a fresh moderator browser context, verify “My discussions” and the
   unread marker without operator-carried state.
5. Remove the reply, verify the ordinary tombstone discloses no reply text,
   and directly verify that the author-owned reply still exists unchanged.
6. Restore from the tombstone, verify the chained authority action, and
   verify reappearance only after the exact author source remains eligible.
7. Run each post-commit/lost-response exercise described below and reconcile
   from the browser without creating a duplicate.
8. Restart authority, observer index, observer API, policy, and browser
   services. Verify discussion projection, both sessions, pending operation
   recovery, “My discussions,” and unread state.

For each step, set `status` to `pass` or `fail` and add only public strong
references, digests, version identifiers, or a concise redacted observation.
Set the top-level status to `pass` only when every fixed check passes, add at
least one exact public record, record service versions and completion time,
then run:

```sh
/opt/atproto-community/.venv/bin/python \
  /opt/atproto-community/deploy/public-community-pcv0/validate_deployment.py \
  validate-receipt /var/lib/pcv0-campaign/integration-receipt.json --complete \
  --campaign /var/lib/pcv0-campaign/campaign.json
```

### Deterministic post-commit recovery exercises

The hooks are off in normal application configuration. This campaign's
examples enable their wrappers explicitly, but no crash occurs unless a local
one-shot trigger file exists. Triggers are not exposed through HTTP and the
wrapper consumes each by atomically renaming `.once` to `.consumed` after the
real PDS create returns and before the corresponding journal records success.

Run these exercises one at a time with no unrelated writes in flight. The
trigger selects the next write of that class, so the operator must arm it only
immediately before the exact browser intent under test.

For the participant path:

1. Verify the browser service has
   `COMMUNITY_INTEGRATION_FAULTS=enabled` and its bounded fault directory, and
   that the directory is owned only by `community-web`.
2. As the service user, create exactly one `post.once` file in
   `/var/lib/community-web/integration-faults/`. (`submit.once` exists for a
   separately planned submission-write exercise; do not arm both.)
3. In the participant browser, start one new post operation. The PDS create
   returns, `post.once` becomes `post.consumed`, and `community-live` receives
   `SIGKILL` before its journal moves beyond `attempted_unknown`.
4. Confirm systemd restarted the process. Open the same pending operation page
   and choose **Check exact records and continue**. Record the single AT URI,
   CID, rkey, journal result, consumed-trigger observation, and service restart
   identifier. Confirm that no second post exists.

For the authority path:

1. Verify `communityd.toml` names
   `/var/lib/communityd/integration-faults` and that no non-authority service
   can write there.
2. As `communityd`, create exactly one `authority.once` immediately before one
   moderator admission/removal/restore request. The immutable create returns,
   the trigger becomes `authority.consumed`, and `communityd` exits with code
   86 before its journal records `committed`.
3. Confirm systemd restarted the authority service. Repeat the exact same
   browser intent/operation identity so `communityd` performs exact repository
   readback. Record the single authority AT URI, CID, rkey, reconciled journal
   result, consumed-trigger observation, and restart identifier. Confirm that
   no second authority record exists.

Remove each `.consumed` marker after its evidence has been recorded. Remove
both fault-enablement settings after the campaign and remove
`integration_fault_directory` from the deployed authority TOML; strict config
then returns both processes to the default hook-disabled behavior, and
`validate-bundle` treats that shape as normal mode. Removing only one side is
refused. Arbitrary network cuts or kills do not prove a post-commit unknown
response and cannot substitute for these exercises.

## Separate human dogfood gate

The machine-assisted integration campaign and human dogfood are different
claims. Keep `humanDogfood.status` and the receipt's corresponding status at
`BLOCKED_MISSING_PARTICIPANTS` until two distinct people are named, one of
them is the configured moderator, and a specific topic and activity are
chosen. Two accounts controlled by one person never satisfy this gate. An external
Phase 2 cohort is not authorized by this README, by PCV0 ("internal dogfood is
the only human trial"), or by PCV2 (which authorizes no public trial): it
requires its own `BUILD.md` amendment that names the accepted participant
packet (phlogiston `docs/PHASE-2-PARTICIPANT-PACKET.md`) and the Q2 receipt.
Until that amendment exists the gate stays `BLOCKED_MISSING_PARTICIPANTS`.

When those inputs exist, use a separate receipt and run the uninterrupted
human journey from `docs/campaigns/PUBLIC-COMMUNITY-PCV0.md` without an
architecture briefing or shell intervention. Do not report an external pilot,
production readiness, or product comprehension from the integration receipt.
