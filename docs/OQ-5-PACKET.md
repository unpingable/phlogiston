# OQ-5 operator-question packet

**Status:** prepared unsigned; non-authorizing

**Schema:** manually reviewed Markdown, following the OQ-7 bootstrap exception
format pending V0-G0's strict JSON schemas

**Packet ID:** `OQP-OQ-5-2026-08-14-01`

**Question ID:** OQ-5

**Prepared:** 2026-08-14 against base commit
`e81e499f5d0f9caa6a3a420eeb6e811abbd1ac47`

**Preparer:** agent-produced proposal

**Authority effect:** none

**Human receipt required:** yes

This is a review object, not an operator decision, a controller-entry packet,
an execution-evidence bundle, a `BUILD.md` amendment, or a community authority
record. It contains no ruling or signature field.

## Protected review inputs

| Role | URI | SHA-256 |
|---|---|---|
| promoted-question register (post-OQ-7 change set) | `repo:docs/OPEN-QUESTIONS.md` | `sha256:4a36e91b81a414f6e557b4777a3f4a839b6343f596b19da34b917ed290340f65` |
| authorized V0 milestone design | `repo:docs/IMPLEMENTATION-PLAN.md` | `sha256:9713bfb4729844bbd029423f3f66cf192ab9b90c172b7585bfd6d5b4fd55da35` |
| proposed acceptance design | `repo:docs/TEST-PLAN.md` | `sha256:df4f8508b6c436c14f3a9d5273660c99c208a3c3f58d5a0d882190b5c93c8af6` |
| state machine | `repo:docs/V0-STATE-MACHINE.md` | `sha256:fb98cc0c9f8e47b851a7c22633e6263f81a43729216ac783b05a69ecc479d2d6` |

`BUILD.md`, `DOCTRINE.md`, and `AGENTS.md` bound every answer. No answer
changes product scope, architectural invariants, credential rules, signing
behavior, or ATProto records.

## Question

If the author updates or deletes only the `invalid.community.submit` record
after a valid admission, does the post leave the community view?

The post itself remains exact and available; this is a consent/governance
choice, not a transport failure.

## Why this is being asked now

OQ-5 blocks V0-M4, the state-hardening milestone, whose submission-mutation
reducer fixture cannot encode an unselected rule. The operator issued a
disposition on 2026-08-14 ("submission-as-signed-intent, per the current
register recommendation"); this packet exists so that the ruling binds to an
exact, reviewable artifact rather than to prose.

## Observed forcing case

1. OQ-5 is a named blocker for V0-M4 in `docs/OPEN-QUESTIONS.md`.
2. V0-M3 is implemented: the vertical acceptance path exists and explicitly
   contains no submission-mutation scenario.
3. The M2/M3 reducer currently records `projection_incomplete` for this case
   rather than silently selecting a policy — the leakage guard held, and M4
   must replace it with the selected rule.
4. The decision is self-contained: it changes reducer semantics for one case
   and one fixture, with no protocol, credential, or authority impact.

## Admissible answers

### A — Submission is signed intent at admission time

A later update or deletion of the submission record remains audit-visible but
does not revoke the community's separate admission. Post update/deletion still
hides the post. V0 defines no author-withdrawal record.

**Doctrine and authorization fit:** matches the register's standing
recommendation; keeps admission as the community actor's independent authority
record; no scope change.

**Fit criterion:** choose A if submission consent is evaluated at admission
time and withdrawal is deliberately absent from V0.

### B — Submission mutation revokes

Updating or deleting the submission record after admission withdraws consent
and hides the post; the admission loses effect while the submission is
mutated/deleted.

**Doctrine and authorization fit:** also internally coherent, but adds an
implicit author-withdrawal channel that `BUILD.md` neither names nor excludes,
and complicates replay (visibility becomes a function of the submission's
current state rather than of observed intent at admission).

**Fit criterion:** choose B if ongoing consent, not admission-time consent, is
the desired V0 semantic.

## Evidence by answer

### A

**Supporting:** the admission is a distinct signed authority record referencing
exact submission and subject; the community's ledger stays append-only;
replay/lifecycle rules in `docs/IMPLEMENTATION-PLAN.md` were written around
admission-time intent ("treat submission as signed intent at admission time");
audit keeps the later mutation visible, so nothing is hidden from review.

**Opposing:** an author who deletes a submission may believe they withdrew the
post; V0 offers no self-service withdrawal, so misunderstanding is possible.
Mitigation: presentation/audit text can state the rule.

**Residual uncertainty:** post-V0 restore/withdrawal design (S5/OQ-R5) may
change operator expectations.

### B

**Supporting:** maximizes author control; matches a naive reading of
"deleting the submission should undo it".

**Opposing:** creates a withdrawal channel V0 explicitly does not define;
makes community view state depend on author-side mutation after the fact;
conflicts with the plan's admission-time-intent language.

**Residual uncertainty:** none material beyond the policy preference itself.

## Recommendation

**Recommended answer:** A

A matches the plan's written semantics, keeps the ledger append-only, and
keeps M4's fixture deterministic and replay-stable. The register has carried
this recommendation since promotion.

## Consequences by answer

### A

- **Authority delta:** none; the receipt satisfies only the OQ-5 blocker.
- **Guarantee delta:** submission mutation after admission becomes defined,
  testable behavior: audit-visible, non-revoking.
- **Blockers satisfied:** OQ-5. V0-M4's submission-mutation fixture may encode
  the rule. All other gates remain.
- **Documents:** `docs/OPEN-QUESTIONS.md` OQ-5 fields record the decision and
  the stable receipt ID `OQDR-OQ-5-2026-08-14-A-01`. No `BUILD.md` change.
- **Replay/fork implications:** none; the rule is deterministic over observed
  events.
- **Abuse/T&S implications:** removal remains the operator's tool; authors
  retain full control of the underlying post (post deletion always hides).

### B

- Same shape, with the opposite reducer rule; M4's fixture encodes revocation;
  the plan's admission-time-intent language would later need amendment.

## Novelty condition

A replacement packet is required if evidence shows either answer conflicts
with `BUILD.md`, `DOCTRINE.md`, or `AGENTS.md`, or if the operator wants a
hybrid (e.g., deletion revokes but update does not).

## Operator ruling

Absent by design. A separate human operator-decision receipt pins this
packet's digest and uses one ruling from
`select | defer | reject_packet | repack_required`.
