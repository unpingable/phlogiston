# SCV0-M5A — Pure synthetic projection-artifact compiler

Status: **implemented, fixture-only** (2026-08-22)

## Doctrine

```text
source record
    !=
community projection
    !=
reader artifact
```

The community owns the projection and disclosure decisions. The M5A compiler
is a pure translation boundary: given one or more already-qualified M2
lifecycle values and one explicit disclosure profile, it deterministically
constructs the exact synthetic artifact the community says it is willing to
publish. It does not fetch, qualify, admit, authorize, or infer anything.

## Compiler contract

Input:

* exact, valid `ProjectionLifecycle` values from M2;
* the compiler's bound `CommunityIdentity`;
* an exact declared lifecycle and community identity, preventing caller
  relabeling;
* one fixed `ordinary_reader` or `technical_audit` disclosure policy;
* for `Added` only, a typed bounded presentation tied to the admitted source
  URI, CID, and `PostReference` identity.

Output:

* a deterministic immutable `ProjectionArtifact` when at least one lifecycle
  is reader-publishable;
* an explicit `NonPublishedCandidate` for `Suggested`, never a feed entry;
* stable artifact, entry, presentation, policy, and candidate identities based
  on canonical payloads and compiler version
  `scv0-projection-artifact-compiler/1`.

The compiler revalidates its typed inputs. It preserves M2 lifecycle identity,
community identity, admitted source CID, source-observation identity, and the
existing admission/removal record identities. It cannot update M2 state.
Reverse admission-time ordering is a deterministic serialization convention,
not ranking or recommendation authority.

## Lifecycle disclosure

| M2 state | Artifact behavior |
| --- | --- |
| `Suggested` | Non-published candidate receipt only; presentation is refused. |
| `Added` | Published entry with an exact bounded presentation. |
| `ChangedAtSource` | Lifecycle entry only; the original presentation is not silently replaced. |
| `SourceUnavailable` | Lifecycle/tombstone entry only; no replacement content is fabricated. |
| `Removed` | Removal tombstone retaining admission and removal identities; removed content is not republished. |

`BoundedSourcePresentation` is caller-supplied disclosed copy, not a source
record. It must match the exact source version admitted by the projection. A
source change requires a later explicit disclosure decision before new
presentation can cross the artifact boundary.

## Disclosure boundary

The fixed ordinary profile includes the bounded presentation and lifecycle
identifiers necessary for rendering. It omits technical receipt references and
lifecycle links.

The fixed technical-audit profile additionally includes identifiers for the
source qualification/observation/currentness receipts, submission evidence,
moderator authorization, admission, projection, and removal, plus the locally
available immediate lifecycle links. These are references only. Their presence
does not disclose receipt bodies, prove complete history, or authorize a
reader.

Both profiles reject credential/private-authority-shaped material. This is a
defense-in-depth schema boundary, not a general secret detector. The compiler
has no dependency on OAuth, credentials, signing, transport, storage, or a
writer.

## Executable witnesses

Positive witnesses prove:

* M5A-P1 — `Added` under ordinary disclosure emits only bounded ordinary
  fields;
* M5A-P2 — technical audit explicitly emits receipt references and available
  lifecycle links;
* M5A-P3 — `Suggested` remains non-published;
* M5A-P4 — `ChangedAtSource` emits a lifecycle entry without replacement
  presentation;
* M5A-P5 — `Removed` emits a non-republishing tombstone while retaining its
  admission/removal references.

Hostile witnesses prove refusal of:

* M5A-H1 — publishing `Suggested`;
* M5A-H2 — OAuth/token-shaped material;
* M5A-H3 — private moderator-authority-shaped material;
* M5A-H4 — an invalid or untyped projection state;
* M5A-H5 — community substitution;
* M5A-H6 — lifecycle upgrades and implicit source replacement;
* M5A-H7 — treating receipt references as authorization;
* M5A-H8 — leaking audit fields through an ordinary artifact.

Additional witnesses bind presentation to the exact admitted source, refuse
duplicate current projection states, check immutability/integrity, and prevent
direct untyped presentation or disclosure-mode substitution.

Fixture:
`tests/fixtures/space-community/scv0-m5a.json`, SHA-256
`c4ac94b267b238bd8df657d4f909d073973c8dae327ae4a9a89a1d892af7b8e3`.

## Claims and non-claims

An artifact proves only that this compiler deterministically mapped the
supplied qualified projection states under the named synthetic disclosure
policy. It explicitly does **not** establish:

* reader authorization or visibility entitlement;
* membership or community legitimacy;
* moderator or governance authority;
* source truth, ownership, or repository currentness;
* authenticity of the synthetic publication reference.

M5A does not implement publication signing or community-controlled artifact
hosting. A shared renderer receives no raw repo, credential, moderator
capability, or source qualification machinery through this contract.

## Replacement boundary

The compiler and disclosure profile can be replaced or versioned without
changing M1/M2 state semantics, SA0–SA10d evidence qualification, or a future
renderer's lack of authority. Reader authentication, serving, caching,
discovery, accounts, live data, writes, governance effects, and deployment
remain outside this campaign.
