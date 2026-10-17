# Proposed opt-in interaction release

Experimental ATProto/Bluesky client; not full Bluesky parity. Proposed from private
implementation `bf10f79f49643999146b80a6c4e3f732b975a99e`; not deployed.

Content interaction is off by default. Settings requests separate provider OAuth
consent for create/delete on exactly `app.bsky.feed.post`, `app.bsky.feed.like`,
and `app.bsky.feed.repost`, retaining the disclosed reader tier. No wildcard
repository permissions are requested. Ordinary reader and Cabinet access remain.

Text posts/replies support 300 graphemes and 3,000 UTF-8 bytes, without linked
mentions, link facets or uploads. Replies preserve exact root/parent URI and CID.
Likes/reposts and their undo verify the signed-in account's exact record. The app
offers deletion only of posts it created, although provider permission covers any
post in those collections. Provider state can take time to propagate to feeds.

Disable explicitly disconnects this account in all browsers, deletes stored
provider tokens, and requests provider revocation. Normal reconnection requests
reader permissions. Provider refusal or unavailable revocation is reported
truthfully. No selective downgrade or instantaneous revocation across every PDS
is promised. Existing public records survive disconnect and local data erasure.

Interrupted operations remain in the existing journal and are recoverable from
Settings. Check outcome is read-only. Explicit Retry uses the same exact address,
checks current permissions/pause/eligibility, and reconciles before further effects.
New publication is refused while an earlier publication remains unresolved.

Frozen source passes TypeScript, 340 named unit/integration tests and 17 Chromium
checks, including mobile presentation. Independent source review found and
verified corrections to eight permission, identity, concurrency and recovery
findings; it is an AI source review, not a human security audit or release approval.
Actual disposable-PDS OAuth tested reader refusal, exact consent, public record
URI/CID readback, reply lineage, undo, lost-response/restart reconciliation,
disconnect, old refresh-token refusal and reader-only reconnection. All public
fixture records and these OAuth grants were removed after testing. This does not
establish fresh interaction consent on a Bluesky-hosted account or a deployed
production cutover; normal external reader OAuth was previously qualified.

Following, conversations, saved feeds, panes, local attention controls, personal
curation, manual Cabinet admission, source distinctions and limited Labelwatch
context remain supported. Follow/unfollow, DMs, notification inbox, media upload,
rich composition, ranking/AI feeds, hosted registration and broader parity are
outside this release. Eligibility remains 18+; policies remain explicitly not
legally reviewed. Cabinet reconsideration limits, decline categories and moderation
record retention remain owner decisions.

Release/deployment identifiers, complete test and independent review evidence,
rollback and owner dispositions are pinned in the implementation/product pull
requests. No merge, deployment, OAuth registration change or announcement follows
from this snapshot.
