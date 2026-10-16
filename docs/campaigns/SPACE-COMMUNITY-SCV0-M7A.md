# SCV0-M7A — Deterministic static public-demo export

Status: **implemented and qualified** (2026-08-22)

## Mission

M7A converts the four exact synthetic M6B/M6C lifecycle sites into one
portable static publication bundle:

```text
synthetic M6B sites
        ↓
M6C cue qualification
        ↓
static demo compiler
        ↓
HTML + exact feed JSON + manifest + checksums
```

The compiler does not observe ATProto, fetch source records, authenticate a
reader, decide admission, moderate, or serve network traffic. Its local writer
accepts only an explicit absent/empty directory and never deletes or replaces
an existing non-empty directory.

## Published shape

The qualified bundle contains 20 files:

* one script-free landing page and `.nojekyll` marker;
* exact ordinary and audit M6B pages for `Added`, `ChangedAtSource`,
  `SourceUnavailable`, and `Removed`;
* exact M6A ordinary/audit feed JSON for each state;
* a canonical manifest and checksum list.

The landing page states that the corpus is synthetic, contains no live account
or private Space data, and does not establish reader permission or production
readiness. Each lifecycle page remains byte-identical to canonical M6B output;
the exporter does not rewrite community meaning for presentation convenience.

Bundle ID:
`sha256:9bc2a8935f1f239fbcd311287fcf3602fa4a7f1ebfd9bcada0d413dc26455b5e`.

Fixture: `tests/fixtures/space-community/scv0-m7a.json`, SHA-256
`6fd31b82b86fdf5bcae3677956810d23f5313420e20ebae034098b3c43d6709a`.

## Guarantees

M7A establishes only that:

* all four sites replay through canonical M6B;
* each site has an M6C `synthetic_information_sufficient` receipt;
* emitted page and feed bytes exactly match those qualified inputs;
* file paths are normalized and traversal-free;
* every payload except the checksum file itself is digest-listed;
* a written directory contains exactly the expected file set and bytes.

## Hostile witnesses

The suite refuses:

* missing or reordered lifecycle scenarios;
* path traversal, absolute paths, backslash ambiguity, and non-normal paths;
* caller-provided digest substitution;
* replacement of a non-empty directory;
* mutation or unmanifested files after export;
* symbolic links in a retained export;
* removal of fixed human-usability or authority non-claims;
* filesystem-root or home-directory output targets.

## Non-claims

The bundle does not prove live ATProto data, human comprehension or usability,
reader identity or authorization, membership, moderator or governance
authority, source truth or ownership, repository currentness, production
readiness, or hosted-byte parity. M7B must separately establish only that a
public host returned the exact M7A bytes.

## Replacement boundary

The demo package is separately installable and contains no HTTP client,
server, observer, writer, credentials, signing, database, cache, analytics,
telemetry, ranking, or recommendation code. The static hosting provider can be
replaced without changing M1–M6C semantics.
