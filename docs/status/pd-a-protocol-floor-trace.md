# PD-A — protocol floor / independent reconstruction: decision trace

**Schema:** factual-governed-runway-status-v1

**Authority effect:** none

**Observed at:** 2026-08-17

**Scope:** the V0 record model, reducer, and validators at `ef32085`, read
against the PD-A question in [PRODUCT-DIRECTION.md](../design/PRODUCT-DIRECTION.md)

**Rulings made:** none

This is non-authorizing PD-A material. It traces facts and compares candidate
shapes. It **selects no shape**, promotes no operator question, proposes no
lexicon, and amends nothing. Where it says "dominant," that is a statement
about traced evidence on one named axis, not a ruling.

## The question

> What is the minimum protocol-visible artifact set from which a second
> independent implementation can derive the same admitted corpus, including
> enough information to determine whose authority counts and which bounded
> composition/precedence semantics apply?

Held separate throughout, and not addressed here: OQ-1 publication
authorization ([s1-oq1-publication-gap.md](s1-oq1-publication-gap.md)), S1
implementation, membership (S14 / OQ-R3), remote administration (OQ-4), and
product affordances.

---

## 1. Minimum reconstruction inputs

Every fact a fresh independent AppView must possess to derive the current
admitted corpus, traced to where it lives now.

| # | Fact | Where it lives today |
|---|---|---|
| 1 | The community DID | supplied by the reader; the thing being read |
| 2 | The community's signing key and PDS endpoint | DID document (`repoproof.py:349,374`) |
| 3 | The four collection NSIDs | `constants.py:7-10`, code |
| 4 | Subject collection is `app.bsky.feed.post` | `constants.py`, enforced `records.py:382,402,418` |
| 5 | Authority records must live in the community repo | `records.py:435` |
| 6 | Authority records are create-only | `records.py:445` |
| 7 | **The authorized administrator DID** | **configuration only** (`ObserverConfig`/`DaemonConfig`) |
| 8 | Self-submission rule (submission repo == subject author) | `records.py:378` |
| 9 | Submission `community` field must equal the community DID | `records.py:374` |
| 10 | Deterministic rkey derivation for admission/removal | `records.py:406,422`, `admission_rkey`/`removal_rkey` |
| 11 | strongRef exactness (URI **and** CID) across submission/admission/removal | `records.py:451-467` |
| 12 | The ten projected states and their meanings | `docs/V0-STATE-MACHINE.md` prose |
| 13 | The eight-step precedence order | `docs/V0-STATE-MACHINE.md` prose, implemented `reducer.py:175-187` |
| 14 | Removal masks *every* duplicate admission for the exact version | prose + `reducer.py` |
| 15 | Terminality: CID mismatch / deletion is terminal for that lifecycle | prose |
| 16 | Five-minute `createdAt` skew tolerance | `records.py:335` |
| 17 | Reducer/schema version identity | `PROJECTION_VERSION = "v0"`, `SCHEMA_VERSION = 1` (`storage.py:47-48`) |
| 18 | Trust policy: which verification outcomes count as accepted | `storage.py:385-390` constructor default, no config surface |
| 19 | **Observer-relative lifecycle eligibility** | **local state, not derivable** — see §3 |
| 20 | **Observer-relative first-acceptance time** | **local state, not derivable** — see §3 |

## 2. Partition

**Already protocol-visible** — 1 (as the reader's own input), 5, 6, 9, 10, 11.
Facts 5/6/9/10/11 are visible in the sense that they are checkable *against*
the records themselves once the rules are known; they are self-evidencing, not
self-describing.

**Derivable from ATProto/DID machinery** — 2. DID resolution yields the
verification key and PDS endpoint; the signed commit yields revision and
order. This is the part that already works with no local knowledge.

**Configuration-only** — 7 (administrator DID), 18 (accepted verification
outcomes). Both are load-bearing for the derived corpus and neither is
recorded anywhere a second implementation can read.

**Repository/documentation-only** — 3, 4, 8, 12, 13, 14, 15, 16, 17. These
live in code constants and `docs/V0-STATE-MACHINE.md`. A second implementation
reproduces them only by reading this repository.

**Neither, and not fixable by any descriptor** — 19, 20. See below.

## 3. The hard bound: an observer-relative residue

Two inputs to validity are functions of *local observation history*, not of
repository state. No protocol-visible artifact can supply them, because they
are not facts about the records.

**(a) First-acceptance time gates the skew rule.** `records.py:329-344`
compares a record's signed `createdAt` against
`context.first_accepted_at + 5 minutes`. `first_accepted_at` is when *this
observer* first accepted the record. A submission with a `createdAt` more than
five minutes in the future is `invalid` for an observer that saw it live, and
**valid** for an observer that first reads it an hour later. Same bytes,
different verdict.

**(b) Local observer sequence gates revival after terminality.**
`reducer.py:516-601` maintains `terminal_by_subject` keyed on
`observer_sequence`, and a new submission+admission may create a lifecycle
after a terminal event only if both records' `first_observed_sequence` exceed
the latest terminal observation sequence. A fresh indexer has no record of the
terminal observation, so `prior_terminal` is 0 and the lifecycle is eligible.
The state machine states the intent directly: "equivalent intent or authority
that predated the terminal event cannot be held in reserve as a restore." That
protection is enforced against *observation* order, which a newcomer does not
have.

The state machine already concedes the general form (§Audit limits): "A fresh
indexer reading only current repo state cannot recover records edited/deleted
before it saw them."

**Consequence for PD-A.** "Derive the same admitted corpus" is not achievable
in general by any artifact set, because part of the current semantics is not a
function of the records. A fresh implementation will in general derive a
**more permissive** corpus than a long-running one. The achievable target is
narrower and should be stated as such:

> the same corpus, for records whose lifecycles contain no terminal event and
> no future-dated `createdAt`, given the same repository state and the same
> subject-resolution results at the same as-of time

Everything below is scoped to that narrower target. Widening it is a semantics
change, not a descriptor change — see §9.

## 4. Can the community DID be the root of authority?

Traced, not assumed.

`_validate_authority_context` (`records.py:434-448`) enforces three things for
admissions and removals:

1. `context.repo_did == context.community_did` — the record is in the
   community repo. **Cryptographically grounded**: `verify_commit`
   (`repoproof.py:253`) checks the commit signature against the key in the
   community DID's document, and `verify_record_proof` proves MST membership
   from that signed root. Nothing but the community's key can place a record
   there.
2. `context.operation is CREATE` — also grounded in observed repository
   operations.
3. `actor == context.administrator_did` — **not grounded in anything a reader
   can check.** `actor` is a field inside a record written by the community
   actor itself.

Under the current writer architecture this third check cannot be an
authorization boundary. OQ-3 answer A places signing custody with the PDS and
gives `communityd` an authenticated capability; OQ-4 answer A makes the
administrator DID "community-attested attribution." Anyone holding the
community credential writes any `actor` value they choose, and the reducer
would accept it if it matched the configured DID — and reject it if it did
not, regardless of who actually acted. The check therefore detects
**misconfiguration and drift**, not compromise.

Two consequences pull in opposite directions and must not be collapsed:

- **For authority strength**: the community DID is already the complete root.
  The administrator roster adds attribution fidelity, not authorization.
- **For corpus identity**: the check is nonetheless *corpus-affecting*. An
  implementation ignorant of the administrator DID would accept admissions the
  reference implementation marks `unauthorized`. So the fact is required for
  identical output even though it is not required for security.

The V0 evidence is degenerate on this point: in the only live exercise the
administrator DID **equals** the community DID
(`did:plc:exampleparticipantabcdef` in all roles), which OQ-4 explicitly
permits. Under that configuration the check is a tautology and the
administrator roster problem does not exist. It appears only when the two
diverge, which has never been run.

**Bootstrap circularity does not arise.** A record in the community repo
naming its administrators is signed by the community's key via the PDS commit
and proven by MST membership from that signed root. An independent client is
entitled to trust it exactly as far as it trusts the community DID to define
its own community — which is `DOCTRINE.md` clause 2 ("Community is a signed
actor"). The root is supplied by the reader as the identifier of the thing
being read, the same way any AT-URI reader must know the repo it is reading.
There is no step that asks a reader to trust an unauthenticated assertion.

## 5. Do precedence semantics need serializing?

No, and serializing them is the worse option on the traced evidence.

The precedence order is eight ranked cases (`reducer.py:175-187`) over ten
states, plus terminality, duplicate-masking, and reference-pending rules.
Serializing that into records requires a machine-readable rule language —
which `PRODUCT-DIRECTION.md` §7 defers and `BUILD.md` excludes.

A stable `ruleset_id` plus version/digest referencing a publicly specified
bounded state machine is sufficient **for the narrowed target in §3**,
because:

- the rules are already deterministic given the inputs, and already carry a
  version identity in code (`PROJECTION_VERSION = "v0"`, `SCHEMA_VERSION = 1`)
  which the serving path already enforces (`query.py:161-165`);
- a digest makes the referenced specification tamper-evident;
- an identifier makes ruleset evolution expressible without touching records.

Two conditions that the evidence says such a reference must satisfy:

1. **It must declare its observer-relative residue.** A spec claiming full
   determinism would be false per §3. The honest form names which predicates
   are observation-relative and therefore reproducible only within stated
   bounds.
2. **It must cover the trust policy (fact 18).** Accepted verification
   outcomes are currently a constructor default with no config or record
   surface. Two implementations with different accepted-outcome sets derive
   different corpora from identical records.

## 6. Candidate minimal artifact shapes

| | Shape 1 — extend `profile` | Shape 2 — separate descriptor record | Shape 3 — identifiers/digests only | Shape 4 — no new surface |
|---|---|---|---|---|
| Facts made discoverable | 7, and 3/12–17 by reference | 7, 17, 18, and 3/12–16 by reference | 12–17 by reference; **not** 7 or 18 unless carried | none new |
| Still out of band | 18 unless added; §3 residue | §3 residue | 7, 18; §3 residue | 7, 18, 12–17; §3 residue |
| V0 records interpretable unchanged | **No** — see §7 | **Yes** | Yes if carried in a new record; No if added to `profile` | Yes |
| Changes/freezes lexicon surface | Changes `profile`, an already-ratified permanent NSID | Adds one new NSID to the permanent family | Same as 1 or 2 depending on carrier | None |
| Authority rotation representable | Partially — `profile` is `literal:self`, single mutable record; history only via repo versions | Yes — append-only descriptor versions, each signed | Yes, by publishing a new digest | No |
| Rule evolution representable | Awkward — conflates identity and rules in one record | Yes | Yes — that is its purpose | No |
| Malicious/stale descriptor detectable | Stale: partially. Malicious: no — a compromised community key rewrites it | Same: signed by the same key it authorizes | Digest detects spec tampering; not community-key compromise | n/a |
| New trust assumption | none beyond the community key | none beyond the community key | **yes** — availability and stability of an external specification locator | none |

**Shape 4 in detail** — the smallest option latent in existing semantics.
It requires no new record at all, and follows from §4: if `actor` is
reclassified as attribution rather than authorization, fact 7 stops being
corpus-affecting, and the permanent NSID family itself identifies the ruleset
generation (NSIDs are frozen forever, so `zone.neutral.community.*` already
names one semantics generation). Reconstruction inputs collapse to: community
DID + NSID family + a published specification.

This is not free. Reclassifying `actor` **changes the derived corpus** — it
would accept authority records the current reducer rejects — so it is a
semantics change requiring its own ruleset version, and it discards the
misconfiguration-detection the check currently provides. It is listed because
it is genuinely the smallest surface, not because it is obviously right.

**A fifth option was considered and is weaker.** The community DID document
could carry a `service` entry pointing at a descriptor or specification. This
needs no lexicon change at all. But the DID document is attested by PLC under
rotation-key custody, not signed by the repository key, so it introduces a
*different* trust root and a different custody operation for what is otherwise
repository-level information. It also cannot be verified by the existing
proof path, which only verifies repository commits. Recorded and not
recommended.

## 7. Compatibility implications

Traced, and decisive on one axis.

**Record validators are closed-world.** `lexicons.py:162-163` computes
`allowed_fields` from the lexicon's declared properties and calls
`_reject_unknown_fields` on the record instance. Any field added to `profile`
makes such records **invalid** under every deployed V0 validator, which raises
`unknown field`. The module docstring notes open-world semantics for
`knownValues` specifically; the field check is not open-world.

**A new collection is invisible to deployed V0 observers, safely.** The
Jetstream subscription pins `COMMUNITY_COLLECTIONS` (`jetstream.py:85`, filtered
again at `:218`), so a descriptor in a fifth collection is never delivered; and
if it arrived by another path the reducer marks it `AuditOutcome.IGNORED`
(`reducer.py:239`). Old observers keep working, unaware.

On the compatibility axis alone this makes **Shape 2 dominant over Shape 1**:
a separate record is additive and ignorable, while extending `profile`
invalidates existing profile records against existing validators. Shape 1 also
conflates community identity with community authority in one `literal:self`
record, which cuts against `DOCTRINE.md`'s separation of identity from
authority emission.

This does not decide between Shapes 2, 3, and 4, which differ on axes the
evidence does not rank.

**One caution independent of shape.** Proof verification resolves the *current*
DID document and uses the current key (`verifying.py:105-107` → `repoproof.py:349`).
There is no key history. After a community key rotation, historical proof CARs
stop verifying. S1's replay-seam obligation anticipates this ("key rotation is
recorded as events so historical signatures remain verifiable") but nothing
implements it. Any shape claiming to represent authority rotation inherits this
unsolved problem; a descriptor that *names* rotation without a verification
path would overstate what a reader can check.

## 8. Recommended decision boundary

A boundary is justified by the evidence. A shape selection is not.

**Boundary 1 — split the question in two.** Authority and rules have different
answers and should not travel in one packet:

- *Authority* — the community DID is already sufficient as a root (§4). The
  only genuinely open sub-question is whether `actor` is an authorization gate
  or attribution. That is decidable now, needs no new protocol surface either
  way, and determines whether fact 7 must be published at all.
- *Rules* — a `ruleset_id` + version/digest is sufficient (§5); full
  serialization is unnecessary and requires a deferred rule language.

**Boundary 2 — the target must be restated honestly before any shape is
chosen.** "The same admitted corpus" is unachievable in general (§3). The
narrowed target in §3 is achievable. Selecting a shape against the unachievable
target would produce a descriptor that promises determinism the semantics do
not deliver.

**Boundary 3 — do not extend the `profile` record.** This is the one place the
evidence is one-sided: closed-world validators make it a compatibility break
against already-ratified permanent surface, and it conflates identity with
authority. Recorded as a traced finding, not a ruling.

**Boundary 4 — whatever is chosen must cover fact 18.** The accepted
verification-outcome set is corpus-affecting and currently invisible in both
configuration and records. It is easy to overlook because it is a constructor
default that no deployment has ever varied.

## 9. What cannot be decided yet

- **Whether `actor` is authorization or attribution.** This changes derived
  corpus semantics and is an operator question, not an implementation choice.
  Everything else in the authority half depends on it.
- **Whether the observer-relative residue should be removed.** Making validity
  a pure function of records would mean changing the skew rule and the revival
  rule — a `docs/V0-STATE-MACHINE.md` change with fork/replay consequences,
  well beyond PD-A. Until then, any specification must state the residue.
- **Where a referenced specification is published, and under what stability
  guarantee.** This touches OQ-1's namespace question and must not be merged
  with it; OQ-1 governs NSID publication authorization, not specification
  hosting.
- **Key rotation representation.** Currently unimplemented and unverifiable
  (§7). It is an S1 replay-seam obligation and needs its own question.
- **Whether a second implementation is wanted at all in the near term.** PD-A
  is cheap as a decision and expensive as an implementation; nothing here
  argues for building one.

## 10. Not done here

No shape selected. No lexicon proposed or drafted. No operator question
promoted. No `BUILD.md`, `ROADMAP.md`, `DOCTRINE.md`, or state-machine change.
No membership, roles, or generalized governance considered. No live operation.
The OQ-1 publication boundary and OQ-R3 membership question remain open,
separate, and untouched.
