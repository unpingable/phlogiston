# SA5 — Spaces alpha repo-operation acquisition boundary

**Status:** deterministic fixture implementation; no HTTP, authentication,
credential, authority, write, or deployment behavior. **Upstream observation
date:** 2026-08-21.

## Architectural result

SA5 adds one adapter before unchanged SA4:

```text
supplied listRepoOps JSON pages
        |
        v
SA5 response/page/cursor adapter
        |
        v
RepoTransition candidate (or explicit partial/empty result)
        |
        v
unchanged SA4 transition qualification
```

`parse_list_repo_ops_page()` accepts the pinned response keys (`ops`, optional
`cursor`, optional terminal `commit`) and the request metadata observed by its
caller. It converts only the operation fields that SA4 already consumes. An
optional inlined `value` is recorded only as present/absent because upstream
may omit stale values; it is not record evidence.

`acquire_repo_transition_candidate()` requires an SA1-qualified source state,
keeps the supplied page and operation order, holds `since` at that source
revision, checks each next request cursor against the preceding response, and
rejects exact duplicate operations. It returns exactly one of:

- `transition_candidate`: the observed chain ended at a response with no
  cursor and a terminal commit, and at least one operation was supplied;
- `empty_terminal_page`: the terminal response explicitly contained no
  operations; or
- `partial_retrieval`: the last supplied response still names a next cursor.

The terminal commit is retained only as a SHA-256 digest of deterministic JSON
context. SA5 does not parse or verify it. A candidate must still be attached to
independent target evidence and pass SA4.

## Guarantees

SA5 establishes, for the supplied material:

- conformity to the pinned `listRepoOps` JSON field shape;
- exact supplied page and operation order;
- continuity of the observed request/response cursor chain;
- preservation of revision, record path, current CID, and previous CID; and
- deterministic construction of the existing SA4 `RepoTransition` type when
  the observed chain is terminal and nonempty.

## Non-claims

A terminal page, absent cursor, response commit, or revision does not prove
complete retention, complete history, immediate ancestry, authentication,
authority, currentness, authorization, or governance legitimacy. Upstream
explicitly describes the oplog as a transport optimization that may be
compacted, dropped, or lost on migration. The receipt-like acquisition result
fixes all history and authority fields to `false`.

## Alpha assumptions and pins

The compatibility boundary pins:

- `com.atproto.space.listRepoOps` at
  `bluesky-social/atproto` commit
  `89deb9faca20e56fa2a262fe9746ed52bc1095ba`;
- response fields and null create/delete conventions from
  `lexicons/com/atproto/space/listRepoOps.json`;
- the reference PDS behavior that a nonterminal page carries `cursor` without
  `commit`, while a head response carries `commit` without `cursor`; and
- adapter version `sa5-v1` and method
  `listRepoOps-json+observed-cursor-chain`.

The cursor is opaque. SA5 compares it for exact equality and never parses it
as ancestry or completeness evidence.

## Replacement boundary

If endpoint shape, pagination, value inlining, or terminal-commit behavior
changes, replace `operations.py`, its compatibility constants, and SA5
fixtures. SA1 cryptography, SA2 CAR parsing, SA4 qualification, admission, and
governance semantics do not change.

## Witnesses

O1 reconstructs N→N+1 and passes unchanged SA4. O2 reconstructs the mixed
N+1→N+2 batch across three pages without sorting. O3 distinguishes an empty
terminal response from truncation. Hostile tests reject reordered pages,
cursor mismatch, duplicates, and stronger relabeling; classify a missing page
as partial; and show that a mutated operation can pass SA5 container handling
but is refused by SA4.
