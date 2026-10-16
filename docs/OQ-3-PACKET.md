# Operator question OQ-3

- Packet ID: `OQP-OQ-3-2026-08-14-01`
- Schema: `operator-question-packet-v1`
- Prepared: 2026-08-14T21:55:44Z by agent-prepared draft
- Prepared-against base commit: `c87b198f5ce14efde1f485fbff85c8cc9d335fba`

## Question

Where does the non-production test community DID/repository live, who controls it, which supported PDS authentication flow does communityd use, and which external credential provider supplies the secret? Does 'communityd holds authority keys' mean direct signing custody or an authenticated capability to ask the hosting PDS to commit?

## Why now

OQ-3 blocks the real AuthorityWriter adapter (V0-M7) and the human trial (V0-M8). M6 is complete and already pinned a pre-existing operator-controlled non-production identity for reads; the write side needs its own explicit decision before any write-enabled packet.

## Work blocked

The real AuthorityWriter adapter (V0-M7) and the human V0 trial (V0-M8).

## Bounded by

- BUILD.md
- DOCTRINE.md
- AGENTS.md
- docs/GOVERNED-LOOP.md

## Governing inputs

- scope authority: `BUILD.md` (5884 bytes, `sha256:ee50d817d9a81032731a962cfb843525e8c99a29332f25b066734a3a832862cc`)
- architecture doctrine: `DOCTRINE.md` (2622 bytes, `sha256:cf7bb22ae2e1d2a117bf7b35c1746d5f0045e69eee40784b0a10889efb22584c`)
- agent instructions: `AGENTS.md` (3332 bytes, `sha256:1a4c9b2b0b0779c1a9caa255eef977f67f77989d4720796a2e1861494413c7ac`)
- open-question register: `docs/OPEN-QUESTIONS.md` (10489 bytes, `sha256:41f28cc5117cd9855f876e035b7651344a5d9f5a20bfa5013e0d4b86bb3acfc5`)
- governed execution contract: `docs/GOVERNED-LOOP.md` (50121 bytes, `sha256:5196331349155397bb0f6b4f85a9adda5ed4e1741e75b043341f4a1f0ec0afa1`)
- authorized V0 milestone design: `docs/IMPLEMENTATION-PLAN.md` (43789 bytes, `sha256:9713bfb4729844bbd029423f3f66cf192ab9b90c172b7585bfd6d5b4fd55da35`)

## Forcing case

Sufficiency predicate: M7 cannot implement the real adapter until the credential custody model and the community repository location are fixed; the X7 packet must pin the exact DID, PDS origin, and credential reference mode.

- custody-model analysis: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-3-analysis.txt` (text/plain; charset=utf-8, 1604 bytes, `sha256:9f2113b3e3cac33436dbe85adde6e091a94a5bdca0c6bbad0963cd5a725045d3`)

## Answer A

- Fit: Authenticated capability on the existing disposable actor: participant.example.com (did:plc:exampleparticipantabcdef, PDS https://phellinus.us-west.host.bsky.network) is the community actor; communityd authenticates with an account app-password supplied as an external credential reference; the PDS signs and commits. 'Holds authority keys' means the capability, not key custody.
- Basis: Register recommendation verbatim: one disposable actor on an ordinary PDS, one least-privilege external credential reference, no production identity/key, no raw signing material exposed to shared or observer code.
- Uncertainty: ATProto app-passwords are account-wide in V0; finer capability scoping does not exist to choose.

### Supporting evidence

- custody-model analysis: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-3-analysis.txt` (text/plain; charset=utf-8, 1604 bytes, `sha256:9f2113b3e3cac33436dbe85adde6e091a94a5bdca0c6bbad0963cd5a725045d3`)

### Opposing evidence

- account-wide app-password scope risk on a disposable account: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-3-analysis.txt` (text/plain; charset=utf-8, 1604 bytes, `sha256:9f2113b3e3cac33436dbe85adde6e091a94a5bdca0c6bbad0963cd5a725045d3`)

### Consequences

- Authority deltas: communityd gains an authenticated session capability in the disposable community repo only.
- Guarantee deltas: Credential isolation guarantee: the secret never enters a packet, the repository, logs, or evidence.
- Blockers satisfied:
  - OQ-3 blocks V0-M7 and V0-M8
- Blockers remaining:
  - OQ-1 and OQ-4 remain open until separately ruled
- Tasks eligible:
  - V0-M7 becomes selectable once OQ-1 and OQ-4 are also decided
- Amendments required: none
- Replay/fork implications: No replay seam impact.
- Abuse/T&S implications: App-password misuse is bounded by the disposable account, packet write ceilings, and redaction tests.

## Answer B

- Fit: Direct signing custody: communityd holds a private signing key and produces signed commits for the community repo itself.
- Basis: Maximal control; signing works without PDS session cooperation.
- Uncertainty: Rotation and recovery semantics under direct custody are undesigned.

### Supporting evidence

- control argument: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-3-analysis.txt` (text/plain; charset=utf-8, 1604 bytes, `sha256:9f2113b3e3cac33436dbe85adde6e091a94a5bdca0c6bbad0963cd5a725045d3`)

### Opposing evidence

- key custody/rotation machinery and exposure risk: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-3-analysis.txt` (text/plain; charset=utf-8, 1604 bytes, `sha256:9f2113b3e3cac33436dbe85adde6e091a94a5bdca0c6bbad0963cd5a725045d3`)

### Consequences

- Authority deltas: communityd would hold live signing material, expanding its custody surface beyond V0 need.
- Guarantee deltas: Would require new key-custody guarantees not currently specified.
- Blockers satisfied:
  - OQ-3 blocks V0-M7 and V0-M8
- Blockers remaining:
  - OQ-1 and OQ-4 remain open until separately ruled
- Tasks eligible: none
- Amendments required:
  - Key custody design work not presently scoped in V0
- Replay/fork implications: No replay seam impact.
- Abuse/T&S implications: A leaked signing key is strictly worse than a leaked revocable app-password.

## Answer C

- Fit: A fresh self-hosted PDS with a newly created actor hosts the community repo.
- Basis: Full infrastructure control.
- Uncertainty: Self-hosted PDS behavior differences from bsky.network are unmeasured.

### Supporting evidence

- infrastructure control argument: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-3-analysis.txt` (text/plain; charset=utf-8, 1604 bytes, `sha256:9f2113b3e3cac33436dbe85adde6e091a94a5bdca0c6bbad0963cd5a725045d3`)

### Opposing evidence

- setup cost and new trust surface; abandons the pinned identity: `file:///home/jbeck/git/atproto-nutrition/atproto-community-evidence/evidence-items/2026-08-14-oq-3-analysis.txt` (text/plain; charset=utf-8, 1604 bytes, `sha256:9f2113b3e3cac33436dbe85adde6e091a94a5bdca0c6bbad0963cd5a725045d3`)

### Consequences

- Authority deltas: A new actor and self-hosted PDS become the community authority host.
- Guarantee deltas: No guarantee changes.
- Blockers satisfied:
  - OQ-3 blocks V0-M7 and V0-M8
- Blockers remaining:
  - OQ-1 and OQ-4 remain open until separately ruled
- Tasks eligible: none
- Amendments required:
  - PDS provisioning work outside the repository
- Replay/fork implications: No replay seam impact.
- Abuse/T&S implications: A misconfigured self-hosted PDS is its own abuse surface.

## Recommendation

Recommended answer: `A`

Matches the register recommendation, reuses the already-pinned pre-existing identity, keeps V0 free of key-custody machinery, and maps directly onto credential_mode=nonproduction_external_ref.

## Novelty condition

A replacement packet is required if the participant account becomes unavailable or compromised, if the hosting PDS rejects app-password sessions for this use, or if a finer-grained credential capability becomes available and preferred.
