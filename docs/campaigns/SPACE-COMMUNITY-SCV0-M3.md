# SCV0-M3 — author/post/submission wire adapter

Status: **qualified against deterministic fixtures** on 2026-08-22.

SCV0-M3 adds the separately installable `community-space-wire` package. It is
a strict, fixture-only JSON translation boundary from one explicitly
noncanonical wire profile into the immutable SCV0-M1 model. It has no
transport, repository verifier, credentials, signing, writer, projection
policy, persistence, UI, or serving behavior.

## Doctrine

```text
record-shape translation != record qualification
source reference          != community admission
wire occurrence           != authorization
adapter output             != reader visibility
```

The adapter answers only:

> Given these exact canonical fixture bytes and separately supplied expected
> context, can the corresponding M1 value be constructed deterministically?

It does not establish where the bytes came from or authenticate any receipt
identifier embedded in them.

## Frozen fixture profile

The compatibility profile is `scv0-m3-test-wire/1`. Every input must declare
`synthetic-noncanonical-invalid.test`; all NSIDs must begin `test.invalid.` and
all DIDs must use the synthetic `.invalid.test` fixture suffix. These are
deliberate refusal rules, not candidates for publication. They keep OQ-8 open
and make it impossible to turn fixture habit into a permanent Space type or
post collection accidentally.

Inputs use canonical JSON bytes with duplicate keys refused. Unknown or
missing fields refuse. The exact-byte SHA-256 digest is retained in a
translation receipt, so semantically similar but byte-different inputs cannot
silently share one receipt.

## Adapter inputs

### Source post record

The source-post shape contains only:

- the exact Space tuple and its canonical alpha URI;
- author DID, collection, rkey, record URI, and DAG-CBOR CID;
- an existing source-qualification receipt reference.

`adapt_source_post` also requires a separately supplied expected Space and
author. Successful translation produces the existing `PostReference`; it does
not validate the referenced observation receipt.

### Submission record

The submission shape contains its exact author-owned record, exact source
reference ID/URI/CID, target community identity, submitting actor, time,
submission-evidence reference, and expected occurrence ID.

`adapt_submission` requires the already constructed `PostReference` and a
separately supplied expected `CommunityIdentity`. The adapter reconstructs the
M1 `Submission` and requires the supplied occurrence ID to equal its
deterministic `submission_id`. It neither finds a source record nor decides
whether the community accepts it.

### Admission input placeholder

The admission-input shape is fixture scaffolding, not a final Lexicon or
writer record. It retains the exact proposed community-actor record,
community/post/submission IDs, source-observation receipt, and admission time.
`adapt_admission_input` can construct the existing M1 `CommunityAdmission`
only when the caller separately supplies the exact M1 community, post,
submission, and `ModeratorAuthorization`. The adapter does not manufacture or
authenticate that authorization and has no writing capability.

## Translation receipt

Every result includes a deterministic `WireTranslationReceipt` binding:

- compatibility profile and record kind;
- SHA-256 of the exact canonical wire bytes;
- resulting M1 value identity;
- the exact structural checks performed;
- a fixed set of explicit non-claims.

The receipt proves deterministic translation only. Its fixed non-claims are
live ATProto validity, DID resolution, writer authorization, community
admission policy, reader visibility, and governance authority. Caller labels
cannot remove those non-claims or add approval semantics.

## Fixtures and witnesses

The deterministic fixture is
`tests/fixtures/space-community/scv0-m3.json`, SHA-256:

```text
0b262423d51b7503bf8c540712d7d71e5bf047a0e7bd2fb8c6c5b7bd6e6d3fa4
```

Positive witnesses establish exact source translation, submission and
occurrence translation, admission-placeholder composition with an existing
authorization, deterministic replay, and unchanged M3 → M1 → M2 composition.

Hostile witnesses refuse:

- malformed source references;
- wrong expected Space or author;
- invalid CIDs;
- submission references that do not match the supplied source;
- cross-community substitution;
- missing or changed occurrence identity;
- substituted record fields whose canonical URI was not changed;
- caller-supplied `approved` fields;
- UI score/moderator/governance fields;
- duplicate JSON keys or noncanonical encoding;
- non-fixture namespaces; and
- translation-receipt claim relabeling.

## Package and replacement boundary

`community-space-wire` depends only on `community-model` and
`community-space-model`. It deliberately does not import M2: composition tests
feed its M1 outputs into the unchanged projection reducer from outside the
package. A future real schema adapter can replace the entire M3 profile without
changing M1 identities, M2 lifecycle semantics, or any governance boundary.

## Non-claims and deferred work

M3 proves neither live ATProto validity, identity resolution, source
currentness, authorization, admission, nor visibility. It adds no permanent
NSID, identity, network path, Space record, credential, writer, database,
server, UI, ranking, membership, moderation workflow, or deployment.

OQ-8 remains open. SCV0-M4 is documentary only: it analyzes the reader-session
and disclosure boundary blocked on OQ-9 without choosing or implementing a
serving model.
