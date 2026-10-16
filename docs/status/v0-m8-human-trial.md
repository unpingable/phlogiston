# V0-M8 — Human trial and verdict

Status: **governed-complete. Human verdict: PASS WITH LIMITATIONS.**

The operator conducted the M8 human trial on 2026-08-15 against the
prepared trial state (replayed X7 -05 lifecycle; see
`runs/v0-m7-2026-08-14/trial-v0-m8/TRIAL-SETUP.md` in the evidence
repository). The verdict and observations are recorded verbatim in
`evidence-items/2026-08-15-v0-m8-trial-verdict.txt` and accepted by
live-trial human-acceptance receipt `HAR-V0-M8-2026-08-15-01`
(evidence repository, `receipts/`). The closeout commit ran under packet
`CEP-V0-M8-2026-08-15-01`; the pristine `v0-gate V0-M8` report and the
execution evidence bundle are retained under
`runs/v0-m8-2026-08-15/v0-m8/`.

## Verdict (operator's words, narrow interpretation)

> **PASS WITH LIMITATIONS**
>
> V0's core semantics and governed authority/evidence path work and are
> inspectable, but the human-facing presentation does not yet communicate
> those semantics clearly enough to count as a polished product experience.

This is not a PASS. It is not a V0 acceptance blocker either: the
limitations are presentation debt, recorded below as successor-work
findings.

## What the trial established

- Current removed state is absent from the community listing while the
  full historical state remains inspectable in the audit view; the
  underlying state machine behaved as specified.
- The audit view exposes the semantic distinctions that matter:
  submission, admission, subject observation, removal, actor, URI/CID,
  and verification status.
- The distinction between independently verified repository proof and
  transport observation is visible in the retained state.

## Limitations found (V1/successor findings — not repaired in V0)

1. **Empty-state semantics.** The community page does not explain why no
   content is visible. From the page alone the operator could not tell
   whether the community never contained anything, content was removed,
   content is hidden, or rendering failed. A future UI should distinguish
   empty-never-used, removed/hidden, loading/error, and genuinely empty
   states where appropriate.
2. **Lifecycle presentation.** Submission → admission → visible →
   removal exists in the model but is not taught by the ordinary page.
3. **Audit usability.** The audit surface is semantically useful but
   formatted primarily for technical inspection. Future work may need
   grouping, labels, timestamps, actor presentation, and
   lifecycle-oriented rendering.
4. **Evidence vocabulary.** `unauthorized`, `authenticity_unverified`,
   verified resync, transport observation, and repository proof are
   meaningful internally but not naturally understandable to a normal
   operator. Recorded as presentation debt; the V0 vocabulary is
   unchanged.
5. **Health vocabulary.** Fields such as `stale`, high-water state, and
   projection status need clearer operator interpretation if exposed in a
   future UI.

## Boundary notes

- No new live ATProto writes were made for M8; the participant account remains
  at the authorized 12 X7 records.
- No presentation repairs were made during or after the trial; the
  limitations above are preserved as evidence, not silently fixed.
- M1/M2/M2A/M3 remain implementation-complete from before governed
  execution existed; nothing in the M8 closeout retroactively claims
  governed acceptance for them.
