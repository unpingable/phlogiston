# SCV0-M1 — exact reference and record models

Status: **qualified against deterministic fixtures** on 2026-08-21.

SCV0-M1 is the first executable product-model milestone after the SCV0-D0
design freeze. It adds no network, credential, writer, projection service, UI,
or policy runtime. The separately installable `community-space-model` package
contains inert immutable values and deterministic validation only.

## Doctrine

```text
source existence          != community admission
evidence admission        != community admission
authorization to submit   != authorization to admit
community admission       != reader visibility
projection                != source mutation
```

The package deliberately does not define one mutable `CommunityPost` with an
approval status. Each transition retains its own exact input and receipt
references:

```text
PostReference
      ↓
Submission
      ↓
ModeratorAuthorization
      ↓
CommunityAdmission
      ↓
ProjectionReference

CommunityAdmission + separate removal authorization
      ↓
RemovalRecord
```

## Models

`SpaceIdentity` retains the `(authority DID, space type NSID, skey)` tuple.
`ExactSpaceRecordReference` keeps that Space separate from the record author,
then binds collection, rkey, canonical alpha Space URI, and exact DAG-CBOR CID.
It does not use the public-repo assumption that URI authority is record author.

`PostReference` adds the identifier of the external source-qualification
receipt. It identifies a qualified exact source version; it says nothing about
community acceptance or display.

`Submission` binds an exact author-owned submission record, the exact post,
the self-submitting author, target community, submitted time, and submission
evidence reference. The model enforces common author and Space. It does not
claim acceptance, membership, standing, or permission to admit.

`ModeratorAuthorization` binds one community, one action, one exact target
occurrence, one time interval, and its basis/provenance receipt identifiers.
It is reusable for neither another submission nor another action. It is an
occurrence value, not permanent moderator standing, and M1 does not validate
the external authenticity of its basis receipt.

`CommunityAdmission` binds a community-actor-authored admission record to the
exact submission, post, source-observation receipt, admission occurrence, and
in-window admit authorization. It references the author's source; it contains
no source content or source-mutation field.

`ProjectionReference` binds a validated admission to one display state, one
current source relationship, a later source-qualification receipt, and the
time of that check. Its fields contain no source record copy. A visible item
requires the exact-source relationship; changed, deleted, and unavailable
relationships have distinct hidden states.

`RemovalRecord` binds a community-actor-authored append-only removal to the
exact prior admission and a separate in-window removal authorization. It can
remove an item from a view; it cannot delete or alter the author record.

All derived IDs are SHA-256 digests of versioned canonical JSON over exact
model fields. These are deterministic local identities, not ATProto CIDs,
signatures, or proof that referenced external receipts exist. Duplicate and
same-occurrence/conflicting admissions are classified explicitly; the model
does not sort, deduplicate, or choose a winner.

## Claim boundaries

The values establish only deterministic internal consistency of supplied,
typed references:

| Value | Bounded statement |
| --- | --- |
| `PostReference` | this exact source identity and qualification-receipt reference were supplied together |
| `Submission` | this exact self-submission targets this exact post and community |
| `ModeratorAuthorization` | this modeled decision covers this one action/occurrence/time window |
| `CommunityAdmission` | this modeled community decision exactly composes the post, submission, authorization, and community-actor record |
| `ProjectionReference` | this modeled display state refers to this admission and source-check relationship |
| `RemovalRecord` | this modeled append-only removal refers to this admission under a separate exact authorization |

M1 alone does not authenticate a receipt, signature, community actor, or
moderator. It does not prove membership, legitimacy, popularity, truth,
reader entitlement, source currentness, or governance authority. Caller labels
cannot add claims to these records. Later composition must resolve every
receipt reference against the boundary that actually issued it.

## Fixtures and witnesses

The synthetic fixture uses only `did:web:*.invalid.test` actors and
`test.invalid.*` NSIDs. Those NSIDs are explicitly noncanonical and do not
decide OQ-8. Fixture SHA-256:

```text
1de3f4389661752dcad50d58c2dddd9b6fbb80bdd96473a9498de18868357457
```

Positive witnesses M1-P1 through M1-P5 construct the exact source,
submission, admission, projection, and removal chain. Hostile witnesses refuse
admission without observation or authorization, cross-occurrence replay,
cross-community substitution, source-mutation claims, projection without
admission, removal without prior admission, stale authorization, and caller
authority relabeling. Duplicate/conflict outcomes are explicit. Supplemental
frozen-design witnesses refuse wrong Space, wrong author, invalid CID,
evidence-receipt-as-admission, access-as-standing, and visible projection of a
changed source.

## Alpha and replacement boundary

The only alpha-shaped assumption is the canonical Space/record URI form in
`community_space_model.model`, pinned by
`scv0-m1+spaces-alpha-2026-08-20`. It is localized so a later alpha URI change
does not alter admission, occurrence, or source-ownership doctrine. The
package imports only `community-model`; it has no dependency on the Spaces
observer, `communityd`, transport, credentials, signing, storage, or writer
code.

## Deferred boundaries

SCV0-M1 does not select permanent Lexicons or a Space type, project qualified
SA records, provide reader sessions, serve permissioned records, acquire Space
credentials, write author/community records, define membership or roles, add
moderation UX, replies, votes, ranking, or deploy anything. SCV0-M2 remains the
smallest next candidate: a fixture-only reducer over already-qualified records
that maps this exact model into the D0 lifecycle without transport or writes.
