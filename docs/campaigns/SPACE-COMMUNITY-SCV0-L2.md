# SCV0-L2 — exact live author write primitive

Status: implemented and fixture-qualified 2026-08-24.

## Contract

The live adapter composes one authenticated Spaces session with exactly four
author-side operations:

* create an author-owned experimental post;
* create a self-submission that embeds the returned exact post URI and CID;
* update or delete that exact author-owned post path; and
* create an author withdrawal binding the exact post, submission, admission,
  and community actor.

The source write and submission write are separate effects. If the source
succeeds and submission fails, `SubmissionWriteFailed` retains the exact source
reference and refuses to report a submission. There is no compensating delete
and no optimistic community publication.

The adapter is pinned to Spaces alpha package version
`0.0.0-spaces-alpha-20260818163953`, proposal commit
`54c9cf5153d668c4f4fb4438529967412e861775`, and ATProto
permissioned-data commit `89deb9faca20e56fa2a262fe9746ed52bc1095ba`.

## Claims

Successful calls establish only that the authenticated client received exact
URI/CID results for its bounded record writes. Community observation,
qualification, admission, projection, and public disclosure remain later
boundaries. A self-submission records consent for the exact version under
`scv0-exact-public-presentation-consent/1`; it does not admit the item.

## Non-claims

This primitive does not prove identity resolution, live OAuth ceremony,
community authority, successful observation, admission, currentness, reader
authorization, governance standing, or human comprehension. It performs no
network activity in its deterministic tests and contains no credentials.

## Refusal witnesses

Tests retain exact write order and subject binding, reject foreign author
paths and malformed inputs before writes, keep edit/delete operations inside
the author post collection, bind withdrawals to every exact occurrence, and
classify the two-write partial-success case without laundering it into a
completed submission.
