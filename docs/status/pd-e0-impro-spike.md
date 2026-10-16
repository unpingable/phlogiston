# PD-E0 — Impro integration spike, first run

Status: **steps 1–5 pass; step 6 not attempted.** First run on 2026-08-19 was
blocked at step 5; the blocker was resolved the same day and the read leg
rerun. Non-authorizing, like the PD-E tranche it serves
(`docs/design/PRODUCT-DIRECTION.md` §7).

The original blocked run is preserved below as recorded. The second run is
appended at the end rather than folded into it: the first result is the
evidence that produced the CORS decision, and rewriting it would destroy the
reason the change was made.

This is **lab-backed compatibility evidence about the plugin↔host↔AppView
seam.** It is not live testimony about the governed production path. The
browser session was a mocked OAuth session (`did:plc:testuser123`) from
Impro's own e2e harness; the AppView served the frozen V0-M8 replay store.
No credentials were used, no ATProto writes occurred, and no record was
created, mutated, or deleted anywhere.

## Substrate

- Impro `d0a2043` (BSD-0), cloned to
  `../pd-e0-impro-spike/impro`, run from its own dev/e2e harness.
- `atproto-community` plugin built at
  `../pd-e0-impro-spike/atproto-community-plugin` — a fork of
  `improsocial/impro-sample-plugin`, symlinked into `plugins-local/`. Impro
  itself was **not** forked or modified except for one added probe file under
  `tests/e2e/specs/flows/` that runs the plugin in a real browser.
- AppView: this repository's `communitywatch_web` on `127.0.0.1:8137`, serving
  `.../runs/v0-m7-2026-08-14/trial-v0-m8/observer.sqlite3` read-only.
- Browser: Chromium via Impro's Playwright harness, page origin
  `http://localhost:8081`.

## Result by step

| Step | Result |
|---|---|
| 1. Fork/install the sample plugin, get it loading | **pass** — `[plugins] loaded "test-plugin__LOCAL" v1.0.0`; the plugin is also discovered by the ordinary dev path and listed in `/plugins-local/index.json` |
| 2. `Community` sidebar entry | **pass** — rendered and clickable |
| 3. Full plugin page via `registerPage()` / `openPage()` | **pass** — navigated to `/plugin/<id>/pages/community` and rendered the plugin's virtual DOM |
| 4. Obtain and display the signed-in DID | **pass** — `app.currentUser.did` displayed (`did:plc:testuser123`, the harness's mock session) |
| 5. Read and render governed `atproto-community` state | **BLOCKED** — see below |
| 6. One governed mutation through a narrow bridge | **not attempted** — blocked by the same cause as step 5, and deliberately out of scope for this run |

One incidental confirmation worth keeping: when the governed read failed, the
plugin rendered the place-level honest failure ("This community can't be shown
right now") and did **not** fall back to a record-level read. The PD-E rule
held under failure, which is the condition that matters.

## The blocker

The governed AppView emits no CORS headers, and Impro's host-mediated fetch is
an ordinary browser `fetch` with `mode: "cors"`.

Observed in the browser, verbatim:

```
Access to fetch at 'http://127.0.0.1:8137/health' from origin
'http://localhost:8081' has been blocked by CORS policy: No
'Access-Control-Allow-Origin' header is present on the requested resource.
```

Confirmed independently against the running AppView:

- `GET` with `Origin:` set → `200`, and **no** `Access-Control-Allow-Origin`
  in the response headers.
- `OPTIONS` preflight → `405 Method Not Allowed`, `Allow: GET, HEAD`.

**The missing capability is ours, not Impro's.** `communitywatch-web` is
GET/HEAD-only and sends `Content-Security-Policy`, `X-Content-Type-Options`,
and `Referrer-Policy` but no CORS headers — correct for a surface that has
only ever been read by a browser navigating directly to it, and insufficient
for a cross-origin reader. Per the PD-E0 constraint this run **did not change
the AppView**; the gap is recorded here for a decision instead.

Deciding it is not purely mechanical. `Access-Control-Allow-Origin` on the
audit and posts endpoints is a deliberate widening of who may read the
governed projection from a browser, and it should be chosen — origin-scoped
versus wildcard, and on which routes — rather than added reflexively to make a
spike proceed.

## Verified constraints on any future write bridge

Read from Impro's `pluginFetch` implementation and its permission layer, and
recorded now so the bridge is not designed against guesses. None of this
authorizes a bridge; PD-B2's blocked decisions and OQ-4 are untouched.

- **Methods** `GET, POST, PUT, PATCH, DELETE, HEAD` are permitted by the host
  proxy, so the method is not the obstacle.
- **A JSON `POST` will trigger a CORS preflight**, which the AppView currently
  answers `405`. Any bridge needs preflight handling, not just an
  `Access-Control-Allow-Origin` on the response.
- **`credentials: "omit"` is hard-coded.** Cookie or ambient-session auth to a
  bridge is structurally impossible from a plugin. This is architecturally
  convenient: it forecloses the "browser is already logged in, so the bridge
  trusts it" shape, which is the shape OQ-4 answer A rules out anyway.
- **Only the `content-type` response header reaches the plugin.** A receipt
  identifier, AT URI, or CID must travel in the response *body*; header-carried
  receipts are invisible to a plugin.
- **`redirect: "error"`** — no redirects.
- Request body must be a string, ≤ 1,000,000 chars; response ≤ 100 MB.
- **`http://` is permitted only for loopback hosts**; everything else must be
  `https://`. Loopback development works; any non-loopback deployment of a
  bridge or AppView read surface must be HTTPS.
- Permissions are declared per-origin in the plugin manifest
  (`permissions.fetch`) and granted by the user at install.

## Not done, deliberately

- No write bridge, and no security design for one.
- No answer to OQ-4, and no production write endpoint.
- No AppView change of any kind.
- No fork of Impro.
- No live ATProto write, and no use of the participant actor's remaining X7 cap.

## To resume

Restart the AppView per `docs/V0-HANDOFF.md` "How to demo/resume V0", then
from `../pd-e0-impro-spike/impro`:

```sh
npx playwright test tests/e2e/specs/flows/pdE0Community.test.js --reporter=line
```

The probe prints the rendered page, the AppView requests attempted, and the
browser console.

---

# Second run — 2026-08-19, after public-read CORS

Same substrate as above, with one change: `communitywatch-web` now sends
`Access-Control-Allow-Origin: *` on its public read routes and answers browser
preflight. The plugin was rebuilt against the SDK the running host actually
serves (see the skew finding below). Nothing else moved: no write path, no
auth, no projection, verification, freshness, receipt, or authority change.

## Result

The acceptance condition holds:

> Impro plugin → public AppView → governed community projection → rendered
> community state, with no record-level fallback.

Rendered in Chromium, verbatim:

```
Signed-in identity
DID: did:plc:testuser123

Community corpus (governed projection)
example-x7 — did:plc:exampleparticipantabcdef
Showing the last complete projection; it may lag (ingest_stale, resolve_stale).
Nothing is currently part of this community. Items may have been removed;
removal changes this view without deleting anything from the author's
repository.
projectionVersion=v0 generatedAt=2026-08-19T18:17:28.546529Z

Unverified record read (not the corpus)
0 record(s) link here. These are raw repo records, not admissions: unverified,
unauthorized, and refused records can appear in this list, and it never means
an item is in the community.
```

| Step | Result |
|---|---|
| 1. Plugin loads | **pass** |
| 2. `Community` sidebar entry | **pass** |
| 3. Full page via `registerPage()`/`openPage()` | **pass** |
| 4. Signed-in DID | **pass** |
| 5. Read and render governed state | **pass** |
| 6. Governed mutation through a bridge | **not attempted** |

Three properties worth pinning, because they are the ones that could have
quietly gone wrong:

- **The corpus line came from the governed projection.** The backlink read
  returned zero records and is rendered under its own heading as an unverified
  record read. At no point did a record read stand in for admission.
- **Place-level and item-level failure stayed distinct.** The projection is
  genuinely stale (a frozen replay store, four days old), and `/health`
  answers `503` saying so. The plugin reports "may lag" while still showing the
  corpus, rather than collapsing that into "cannot be shown". The first run had
  this wrong — it treated any non-200 health as fatal — and that was a defect
  in the spike plugin, not in the AppView, which was behaving as specified.
- **The empty state is the honest one.** "Nothing is currently part of this
  community" with the removal explanation is the M8 finding-1 behaviour
  arriving through a third-party client.

## Two findings from the rerun

**1. Published plugin SDK is stale against the host — upstream, ours to work
around, not to fix.** The sample plugin depends on
`@impro.social/impro-plugin` from the atpkgs registry, which resolves to
**0.0.3**. The SDK vendored in Impro `main` — the one the host actually serves
to the plugin worker — is **0.0.23**. Between them the fetch proxy changed to
return raw bytes, and 0.0.3 was not updated:

| | 0.0.3 (published) | 0.0.23 (host) |
|---|---|---|
| `arrayBuffer()` | absent | returns the bytes |
| `text()` | returns the `ArrayBuffer` unchanged | decodes UTF-8 |
| `json()` | `JSON.parse(ArrayBuffer)` → throws | `JSON.parse(await this.text())` |

Observed as `Unexpected token 'o', "[object ArrayBuffer]" is not valid JSON`.
Any plugin built against the published package that reads a fetch body is
broken against a current host. Worked around here by depending on the local
`impro/impro-plugin` source, which is the correct arrangement when developing
against a locally cloned Impro anyway. A plugin intended for *distribution*
would need this resolved upstream, and that is worth knowing before anyone
plans a published plugin.

**2. Cross-origin error visibility is load-bearing, not cosmetic.** Because
CORS now applies to the `503` as well as the `200`, the plugin can read the
staleness reason codes out of the health body. Had the allowance covered only
successful responses, a stale projection would have reached the plugin as an
opaque network failure, indistinguishable from the server being down — and the
plugin would have had to render "can't be shown right now" for a community it
could in fact show. The §6 distinction between item-level and place-level
failure only survives cross-origin if the error responses carry the header
too.

## What still prevents step 6

Unchanged by this run, and none of it is a CORS problem:

- **There is no governed write surface at all.** `communityd` is a local CLI
  (`admit`, `remove`); no HTTP interface exists to call.
- **OQ-4 answer A stands**: local OS/UID authorization, no remote V0 admin
  endpoint. A loopback bridge is not automatically compliant, and that is a
  promoted operator question, not an implementation detail.
- **PD-B2's blocked decisions are still blocked**, including whether a
  user-delegated submission writer may exist.
- The AppView deliberately does **not** help here: it advertises
  `GET, HEAD, OPTIONS` and refuses everything else, so a write bridge must be
  its own surface with its own policy. It does not inherit the public-read
  allowance.
