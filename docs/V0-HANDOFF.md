# V0 handoff — how to resume or demo

V0 is governed-complete as of 2026-08-15. Human trial verdict:
**PASS WITH LIMITATIONS** (`docs/status/v0-m8-human-trial.md`). This note
is the resume point for the next session. It introduces no new tooling.

## Park state — 2026-08-17

The project is parked. Nothing is authorized; no work is in flight.

- V0 is **pushed** to `origin/main`. Git history is no longer the only
  copy of the governed work.
- Three documentary repairs landed after the V0 closeout, correcting
  sentences the OQ-1 rename sweep had inverted. They carry no authority
  effect and touch no code, schema, or fixture.
- The parked Roadmap 2 research documents are now tracked. Tracking is
  preservation, not promotion; neither is a selector input.
- Suite green at the park point: ruff clean, **557 tests pass**.

**One governance item is open and waiting on a human**, beyond the
already-open OQ-6 (donor license):

> S1's dependency on OQ-1 is **not** discharged. OQ-1 answered a namespace
> *selection* question scoped to V0-M7; S1 requires namespace
> *publication*, which the OQ-1 record neither authorizes nor specifies.

The full trace — ownership evidence, publication mechanism,
actor/ceremony, freeze point, and whether the existing receipt is
sufficient — is in `docs/status/s1-oq1-publication-gap.md`. It states the
gap and deliberately does not resolve it. Read it before preparing an S1
packet.

Unchanged by the park: the participant account remains at its authorized
12-record X7 cap, and no new live ATProto writes may occur without fresh
operator authorization.

**Product direction (2026-08-17).** A non-authorizing product direction and
candidate tranche decomposition is recorded in
[design/PRODUCT-DIRECTION.md](design/PRODUCT-DIRECTION.md). It authorizes nothing and
changes no slice status. Its load-bearing evidence — which parts of the
intended human loop are buildable over existing V0 plumbing and which collide
with ratified V0 decisions — is traced in
[status/product-loop-plumbing-collisions.md](status/product-loop-plumbing-collisions.md).
The park is unchanged: still nothing authorized, still no work in flight.

## What V0 proved

- **Deterministic community state/reducer semantics** — submission,
  admission, visibility, moderation/removal, and audit retention behave
  per `docs/V0-STATE-MACHINE.md`; golden vectors and acceptance tests in
  `tests/` pin them.
- **Archive/rebuild behavior** — Parquet export and DuckDB query surface
  (V0-M2A), exercised offline.
- **Read-only AppView** — `communitywatch-web` serves community, audit,
  and health surfaces over the observer store with no mutation path
  (V0-M3/M5).
- **Governed execution machinery** — packets, receipts, gates, bundles:
  `docs/GOVERNED-LOOP.md`, exercised from V0-G0 onward.
- **Live Jetstream v2 ingestion** — V0-M6/X6 against
  `wss://jetstream.us-west.bsky.network`.
- **Independent repository proof verification** — `sync.getRecord` proof
  CARs verified (DID, signature, MST membership) per the OQ-2/A ruling,
  including the spec-legal empty-intermediate-node repair (`c757ad9`).
- **Real PDS authority writer** — `communityd` admission/removal writes
  with deterministic rkeys, ambiguity readback, no blind retry (V0-M7).
- **Controlled live write smoke** — X7 -05: four authorized writes on the
  disposable participant repo within one 24-request accounting envelope.
- **Complete live path** — authorized operation → PDS-signed mutation →
  Jetstream v2 → independent proof → verified ingestion → projection →
  audit, retained as governed evidence.
- **M8 human verdict** — PASS WITH LIMITATIONS; the limitation is
  presentation, not semantics.

Governed evidence root (sibling repository, not this one):
`/home/jbeck/git/atproto-nutrition/atproto-community-evidence/`

- task bundles: `runs/v0-g0-2026-08-14/`, `runs/v0-m4-m5-2026-08-14/`
  (v0-m4, v0-m5), `runs/v0-m6-2026-08-14/`, `runs/v0-m6-2026-08-15/`
  (MST repair), `runs/v0-m7-2026-08-14/v0-m7/`, `runs/v0-m8-2026-08-15/`
- X7 exercise runs: `runs/v0-m7-2026-08-14/EXR-V0-X7-WRITE-SMOKE-*`
  (-05 run `...-20260815033140` is the passing chain)
- operator rulings and verdict: `evidence-items/`; packets: `packets/`;
  receipts: `receipts/` (incl. `HAR-V0-M8-2026-08-15-01.json`)

Historical boundary: M1/M2/M2A/M3 were implementation-complete and
verified before governed execution existed (V0-G0 bootstrap, 2026-08-14).
They are starting state, not retroactively governed-accepted.

## What V0 deliberately did not solve

- polished human UX / presentation of state and provenance;
- richer audit/provenance visualization;
- remote administration (V0 admin is local OS/UID only);
- feed-generator compatibility;
- successor/fork UI;
- multi-PDS subject resolution (single-PDS deployment assumption);
- anything else marked post-V0 in `ROADMAP.md` / `BUILD.md`.

## First sensible V1 question

**How should the system explain its state and authority model to a human
without requiring them to understand the implementation?**

The M8 findings (`docs/status/v0-m8-human-trial.md`) are the evidence
base for that question. This is not a V1 plan; a slice becomes work only
through a `BUILD.md` amendment naming its ID.

## How to demo/resume V0

The trial store replays the retained live X7 -05 chain (real PDS writes,
Jetstream v2 events, verified proofs; lifecycle `submitted → visible →
removed`). Everything below is local and read-only.

1. Rebuild or locate the trial state. The prepared store is
   `/home/jbeck/git/atproto-nutrition/atproto-community-evidence/runs/v0-m7-2026-08-14/trial-v0-m8/observer.sqlite3`.
   To rebuild it from the retained X7 artifacts instead:
   `cd` into that directory and run
   `python3 replay_x7_into_store.py` (see `TRIAL-SETUP.md` there).
2. Launch the AppView from the product repo root:

   ```sh
   cd /home/jbeck/git/atproto-nutrition/atproto-community
   env -u V0_X7_CREDENTIAL_REF \
     PYTHONPATH=packages/communitywatch-web/src:packages/communitywatch/src:packages/community-model/src \
     .venv/bin/python -m communitywatch_web \
     --config /home/jbeck/git/atproto-nutrition/atproto-community-evidence/runs/v0-m7-2026-08-14/trial-v0-m8/communitywatch.toml
   ```

   (Background it with `nohup ... > /tmp/m8-appview.log 2>&1 &` if you
   want your shell back.)
3. Open:
   - community page: `http://127.0.0.1:8137/c/example-x7`
   - audit page: `http://127.0.0.1:8137/c/example-x7/audit`
   - health: `http://127.0.0.1:8137/health`
   - JSON: `/api/v0/communities/did:plc:exampleparticipantabcdef/posts`
     and `.../audit` (API paths take the DID, not the slug)
4. Stop the service: `kill <pid>` (or `pkill -f communitywatch_web`).
5. Final V0 evidence bundle and human verdict:
   `runs/v0-m8-2026-08-15/v0-m8/manifest.json` and
   `receipts/HAR-V0-M8-2026-08-15-01.json` in the evidence repository.

No credentials are needed for the demo; none may be introduced. The
participant account is at its authorized 12-record X7 cap — no new live
ATProto writes without fresh operator authorization.
