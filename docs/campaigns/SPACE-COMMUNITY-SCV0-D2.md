# SCV0-D2 — live disposable-alpha contract

Status: **frozen for implementation** (2026-08-24)

This packet closes only the decisions that block the Juniper Commons live
vertical. It does not define a general community protocol.

## Product contract

> A community can make durable, inspectable editorial decisions about things
> it does not own.

The disposable V0 loop is self-submission only. A community decision always
targets an exact Space URI and CID. Public publication is a separate community
decision over a bounded presentation; the renderer never receives a Space
credential or raw permissioned repository.

## Experimental identifiers

The namespace authority is the isolated disposable Spaces-alpha identity
`authority.juniper-pds.sp00ky.net`, DID
`did:plc:wklgd4ebjiajx4gj3fthp62m`. These identifiers are intentionally tied
to that disposable alpha authority and are not the answer to permanent OQ-1.

| Role | Experimental NSID |
| --- | --- |
| Space type | `net.sp00ky.juniper-pds.authority.juniperCommunity` |
| permission set | `net.sp00ky.juniper-pds.authority.juniperPermissions` |
| author post | `net.sp00ky.juniper-pds.authority.juniperPost` |
| author submission | `net.sp00ky.juniper-pds.authority.juniperSubmission` |
| community admission | `net.sp00ky.juniper-pds.authority.juniperAdmission` |
| community removal | `net.sp00ky.juniper-pds.authority.juniperRemoval` |
| author withdrawal | `net.sp00ky.juniper-pds.authority.juniperWithdrawal` |

L10 corrected the initial extra `.juniper` segment before publication. The
preferred hosted authority then returned OAuth `access_denied` for the exact
Lexicon create grant. Because no Juniper Lexicon or record had been published,
L11 atomically rebound the unchanged schemas to the isolated authority above.
Their reversed NSID authority is exactly
`authority.juniper-pds.sp00ky.net`. The hosted names remain compatibility
evidence, not aliases or a prior schema generation.

No public-projection ATProto record is required. The existing deterministic
projection artifact is the publication contract; minting another record type
would create a second provenance universe for no V0 benefit.

The Space declaration freezes exactly the five record collections above. Any
later declaration expansion may widen the alpha protocol grant but cannot
widen a previously frozen governed authorization.

## Exact record meanings

* **post** — author-owned title/body and creation time.
* **submission** — author-authored exact strong reference, named community
  actor, bounded public presentation, consent profile, and submission time.
* **admission** — community-actor-authored exact submission and post
  references, per-occurrence authorization receipt ID, and decision time.
* **removal** — community-actor-authored exact admission and post references,
  per-occurrence authorization receipt ID, reason category, and decision time.
* **withdrawal** — author-authored exact submission, admission, and post
  references, named community actor, and withdrawal time.

Unknown fields fail closed at the local compatibility boundary. Exact
submission presentation is limited to title, body, and author display
reference. Credentials, private source metadata, and moderator capability are
never presentation fields.

## Consent

For this V0 only:

> Submission by the post author of an exact URI+CID constitutes explicit
> consent for that exact version's bounded presentation to be published by
> the named community under consent profile
> `scv0-exact-public-presentation-consent/1`.

Consent does not cover later source versions, other communities, private
metadata, or an admission the community never made. Third-party nomination is
not supported.

## Withdrawal

A qualified exact withdrawal immediately prevents continued ordinary active
presentation for its targeted submission/admission. It is distinct from
source deletion, observation failure, and community removal.

Withdrawal does not erase the admission or the fact that publication
occurred. The renderer may retain a tombstone and the bounded technical
receipt, but it must not continue displaying the withdrawn title/body as a
current feed item. The community's historical statement remains the
community's statement; the author does not acquire retroactive write authority
over it. Re-entry requires a new exact post version, self-submission, and
community admission. V0 has no withdrawal reversal.

Public disclosure cannot be clawed back from third-party caches. The product
must say so rather than claim revocation of already received bytes.

## Product-comprehension release gate

The earlier synthetic showcase produced a stronger adverse observation than
an aesthetics complaint: after considering it, a technically uninvolved
person reported, verbatim, **“yeah I chewed on it and I don't get it.”** The
live slice therefore has to demonstrate its proposition through use.

The default surface puts the useful community feed first. A user must be able
to create, submit, see an exact version admitted, edit the source, observe the
honest divergence, inspect “Why is this here?”, and see community removal
leave the source untouched without first receiving an architecture lecture.
Protocol identifiers and receipts are progressive disclosure.

After deployment, at least one fresh no-coaching participant must exercise the
lifecycle and explain the product in their own words before the intended model
is explained. Equivalent language such as “a curated feed where the community
doesn't own the posts” qualifies; repository vocabulary is not required. The
verbatim explanation is retained as product evidence. If the participant
still cannot identify the utility, close the trial as
`PRODUCT COMPREHENSION FAILURE` and inspect the interaction model/proposition
before adding features or explanatory prose.

## Role custody

| Role | Identity/custody |
| --- | --- |
| author | `did:plc:amynaqqmdog7ualmiopxhh4x`; browser OAuth/session process; post/submission/withdrawal only |
| Space and Lexicon authority | `did:plc:wklgd4ebjiajx4gj3fthp62m`; authority/credential issuance and experimental Lexicon publication only |
| community actor/moderator | `did:plc:3yjj2vbc42du6epwxyfccw4v`; `communityd` process; admission/removal only |
| observer/publisher | no writer key; transient read credential only; public artifact output |
| renderer | public artifact only; no Space credential or writer capability |

The three role DIDs are distinct and bound before the first write. Their
credentials remain separate deployment inputs and may not be substituted or
collapsed.

Raw tokens, DPoP private keys, delegation tokens, Space credentials, cookies,
and app passwords are runtime/session secrets. They never enter Git, receipts,
public artifacts, observer state, or logs.

## Non-goals

No membership, private reader, invitation, voting, ranking, comments,
recommendations, generalized account system, remote browser moderation,
production identity, permanent namespace, or PDS modification is authorized.

## Upstream pins

The compatibility source remains the frozen Spaces alpha/reference set:

* proposal main observed at `54c9cf5153d668c4f4fb4438529967412e861775`;
* `bluesky-social/atproto` `permissioned-data` at
  `89deb9faca20e56fa2a262fe9746ed52bc1095ba`;
* Bulletin at `ccca73d212167e20da56db4691ba7c94e9ad5ccc`.

Alpha changes create compatibility evidence. They do not silently alter this
consent, custody, withdrawal, or authority contract.
