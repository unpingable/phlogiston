# SCV0-L1 — live record contract and withdrawal lifecycle

Status: **implemented** (2026-08-24)

L1 turns the D2 decisions into executable, still transport-free boundaries.
It does not perform OAuth, write a Space record, or claim that the Lexicons
have been published by the disposable authority.

## Experimental record surface

Seven pinned Lexicon documents live under
`community_space_wire/lexicons`: the Space type, permission set, post,
submission, admission, removal, and withdrawal. The Space declares exactly
the five record collections. The record schemas follow the alpha constructs
observed in Bulletin at `ccca73d212167e20da56db4691ba7c94e9ad5ccc`:
`space`, `permission-set`, records, and `com.atproto.repo.strongRef`.

The local documents have these SHA-256 digests:

| Lexicon | SHA-256 |
| --- | --- |
| admission | `2ca8b045bdc6d552ed3f286e2ebe0b293c3611d978e8b35d7dc5aa08b8f3a019` |
| community | `ce5c421e5f2ad771efec8c55f7b0ff645ae61179e3cb3a3274a60488d622f93a` |
| permissions | `8751bdb358b2ae506960162c64887ec633e8fdf64e912e5750630a53a88a0419` |
| post | `714c74c8c62cfc2529b171b86f38b251b822e6a50e448e0f750ee70a7eee13a7` |
| removal | `b8fea6ffca28c43c685db2f0967c0c4d542cef659bb008045763e605706dadf4` |
| submission | `d0829c5bc38422ecba4f6f8d6452c82b11975b81059f51e7e0209d6ec8f6d784` |
| withdrawal | `ed35e6cbd976f6f200472ba26cdf3285681ab0b1b50be9e611c0401df233d80c` |

The permission-set declaration describes the alpha protocol surface. Actual
author/community writer capabilities remain separately and more narrowly
scoped. A mutable OAuth/default collection interpretation cannot widen a
frozen per-occurrence community authorization.

## Adapter boundary

`community_space_wire.experimental` accepts a parsed record only alongside an
exact `ExactSpaceRecordReference` and the qualification receipt established by
the existing observation path. It enforces exact fields, collection, author,
Space type, strong references, consent profile, community actor, and
authorization occurrence before composing the M1 types.

The adapter proves deterministic translation and binding. It does not prove
acquisition, record bytes/CID, author identity resolution, writer permission,
moderator legitimacy, or publication. Those facts must arrive from the
existing SA/M1 boundaries.

## Withdrawal lifecycle

`AuthorWithdrawal` is author-authored and binds the exact post, submission,
admission, community, qualification receipt, and time. M2 reduces it to
`author_withdrawn`, distinct from qualified source absence, temporary source
unavailability, and community removal. It suppresses title/body in ordinary
artifacts while retaining its identifier in audit disclosure. A subsequent
community removal retains both occurrences.

The reducer refuses duplicate/conflicting withdrawal, withdrawal before
admission, withdrawal after community removal, foreign author/community/
occurrence substitution, source-state relabeling, and implicit republication.

## Additive compatibility

No existing profile/version string was incremented. This is intentional: the
old record values and artifact payloads are byte-identical, and the frozen M1
fixture retains SHA-256
`1de3f4389661752dcad50d58c2dddd9b6fbb80bdd96473a9498de18868357457`.
The new enum branch and optional `withdrawalId` appear only for the new record
occurrence. Incrementing every prior identity would have rewritten evidence
without changing its meaning.

## Non-claims

L1 does not establish live Lexicon publication, OAuth consent, writer access,
community legitimacy, reader authorization, source truth, governance
authority, or production readiness.
